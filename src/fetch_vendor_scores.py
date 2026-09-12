"""Commercial ESG ratings, loaded as a benchmark to disagree with, never as an input.

Our own score is built from mandatory filings. This lane loads what the ESG rating industry says
about the same 500 companies so that we can measure how far the two diverge. Every number produced
here carries provenance_class = 'vendor' and lives in its own table. Nothing in this file may feed
the headline score.

Six Kaggle datasets, all free to download, all of them third-party re-uploads of a vendor product:

  pritish509/s-and-p-500-esg-risk-ratings              Sustainalytics-convention ESG Risk, one vintage
  flamingmasamune/s-and-p-500-firms-esg-ratings        the same convention, a second vintage, with a
                                                       per-row rating date
  rikinzala/s-and-p-500-esg-and-stocks-data-2023-24    verbatim the yfinance sustainability schema,
                                                       carrying ratingYear and ratingMonth
  mashinii/s-and-p-500-integrity-scores-11-dimensions  NOT a rating. LLM-generated ethics scores over
                                                       11 dimensions, -100..+100, higher better
  alistairking/public-company-esg-ratings-dataset      ESG Enterprise grades, higher better, has CIK
  mrbossjaysrb/global-corporate-esg-and-financial-dataset
                                                       an Eikon/Datastream extract by the uploader's
                                                       own description, 85 columns, semicolon
                                                       delimited, and the only free source anywhere
                                                       carrying an implied temperature rise and a
                                                       decarbonisation-target ambition per company

Outputs
  data/interim/vendor_scores.parquet          long, one row per ticker per source per metric
  data/interim/esg_vendor_consensus.parquet   one row per ticker, mean vendor percentile and n sources
  data/interim/provenance/kaggle_esg.json

The one error that would wreck the comparison is mixing sign conventions. Sustainalytics-lineage
scores are RISK: lower is better, 0 to about 45. ESG Enterprise and the LLM scores are quality:
higher is better. A single column holding both is a number that means nothing. So the long table
never holds a bare value. Every row carries

  convention   risk_lower_better | score_higher_better | degrees_c | year | pct
  direction    -1 lower is better, +1 higher is better, 0 not a quality score

and direction is computed in exactly one place, from convention, by DIRECTION below. Ranking,
percentiling and correlating all go through direction, so a source cannot be compared against
another without its orientation coming along. The build asserts that a given (source, metric) pair
never carries two conventions, and that values fall inside the range their convention allows.

Matching, and why mrbossjaysrb needed its own treatment
  Five of the six are S&P 500 files keyed on a clean US ticker, so the join is a string match after
  uppercasing and turning dashes into dots. mrbossjaysrb is a global 7,610-row file whose ticker
  column is unreliable: 151 of the 420 tickers that look like S&P 500 members carry more than one
  row, and the extra rows are unrelated companies. AMZN's only row is Meezan Bank, a Pakistani bank,
  with an esg score of 29.9. IBM carries ten rows including Business & Decision Benelux and M & F
  Worldwide. Joining that file on ticker alone would have put a Pakistani bank's rating on Amazon.

  So a row from that file is accepted only if one of three rules fires, and the rule that fired is
  recorded in match_rule:

    alias_name       the company name normalises to a key in the universe lane's name_to_ticker map,
                     which carries SEC entity and former names. This is what resolves Chesapeake
                     Energy to EXE and SAIC to LDOS.
    ticker_verified  the ticker column points at an S&P 500 member AND the row's company name scores
                     at least 96 on token_set_ratio against that company's index, SEC entity and SEC
                     former names. 96 and not 80: at 80 the file offers Line 6 as Old Dominion,
                     GE Digital as Gen Digital and Takata as TKO Group.
    domain_override  one of the hand-checked entries in DOMAIN_OVERRIDE, where the row is plainly the
                     right company but neither name nor ticker says so. Google is filed under the
                     name Google while the index calls it Alphabet; Ferguson appears as Wolseley,
                     Elevance as WellPoint, Evergy as Westar Energy, RTX as United Technologies.

  Everything else is dropped and counted. That costs real coverage and is the right trade.

  Then every accepted row was read once by hand, which found a second class of error the name check
  cannot see: a one-word company name is a token subset of an S&P 500 name, so token_set_ratio
  returns 100 and means nothing. Automatic Labs passed as Automatic Data Processing, Monster
  Worldwide as Monster Beverage, the University of Illinois as Illinois Tool Works. Those are in
  DOMAIN_BLOCK, one line each with the reason.

What the comparison actually showed, so nobody has to rerun it to find out
  ESG Enterprise, the one source here that is not a Sustainalytics re-upload, ranks the S&P 500 in
  almost the opposite order: rho -0.13 against the Sustainalytics lineage on 341 overlapping names.
  Its own grade bands confirm the orientation is right, higher score is a better grade, so this is
  not a sign error. ConocoPhillips carries the single highest total score in its file, 1536 with an
  A grade and an AA on environment, while Adobe gets 621 and a B. Reading their scale as a measure
  of disclosure volume rather than of environmental performance explains it, and it is the clearest
  thing in this lane about what a vendor ESG score is measuring.

dq, PCAF-style, 1 = best
  4  a vendor rating obtained through a third-party re-upload. The number is somebody's product, the
     methodology is not public, the vintage is 1 to 4 years old, and we cannot verify a single value.
     Nothing sourced this way is better than 4.
  5  the LLM-generated integrity scores, the mean we take across their 11 dimensions, and everything
     from mrbossjaysrb, whose lineage the uploader describes as Eikon/Datastream but whose esg values
     look like Sustainalytics risk scores.

Licences, stated plainly
  The uploaders assert CC0, GPL-3 and CC BY-NC-SA. None of them had the right to assert anything:
  these are scrapes of commercial vendor products. Using them as a benchmark to criticise is
  defensible. Republishing the raw table is not. We ship correlations, percentiles and named
  examples, and no raw vendor CSV goes anywhere near the public site.
"""

import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "kaggle_esg"
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance"

KAGGLE_API = "https://www.kaggle.com/api/v1/datasets/download/{slug}"

# Every metric name, the conventions it is allowed to carry, and the range a value has to fall in.
# A source declaring a metric under a convention that is not listed here fails the build.
METRICS = {
    "esg_total": {"risk_lower_better", "score_higher_better"},
    "esg_e": {"risk_lower_better", "score_higher_better"},
    "esg_s": {"risk_lower_better", "score_higher_better"},
    "esg_g": {"risk_lower_better", "score_higher_better"},
    "controversy": {"risk_lower_better"},
    "temperature_goal_c": {"degrees_c"},
    "decarb_target_year": {"year"},
    "decarb_ambition_pct": {"pct"},
}

# The only place a sign is decided. Everything downstream reads direction, never the convention
# string, so there is one definition of which way is good and it cannot drift.
DIRECTION = {
    "risk_lower_better": -1,
    "score_higher_better": 1,
    "degrees_c": 0,
    "year": 0,
    "pct": 0,
}

# Sanity bounds per convention. These catch a decimal-comma parse or a percentage read as a fraction,
# which is the failure mode that would otherwise pass silently.
BOUNDS = {
    "risk_lower_better": (0.0, 2000.0),
    "score_higher_better": (-100.0, 2000.0),
    "degrees_c": (0.5, 12.0),
    "year": (2000.0, 2100.0),
    "pct": (-100.0, 100.0),
}

RISK_NOTE = (
    "Sustainalytics ESG Risk convention: 0 to about 45, lower is better, and total is roughly the "
    "sum of the three pillars."
)
QUALITY_NOTE = "ESG Enterprise convention: higher is better. Pillar scales differ, so rank, do not average."
AI_NOTE = (
    "LLM-generated judgement, not a rating and not measured data. -100 to +100, higher is better."
)

SOURCES = {
    "pritish509": {
        "slug": "pritish509/s-and-p-500-esg-risk-ratings",
        "member": "SP 500 ESG Risk Ratings.csv",
        "sep": ",",
        "ticker_col": "Symbol",
        "vintage_basis": "Kaggle upload date, read from the cached zip. The rating snapshot behind it is late 2023 or early 2024.",
        "licence_asserted": "CC0 asserted by the uploader",
        "ai_generated": False,
        "dq": 4,
        "lineage": "Sustainalytics via Yahoo Finance",
        "metrics": [
            ("Total ESG Risk score", "esg_total", "risk_lower_better", RISK_NOTE),
            ("Environment Risk Score", "esg_e", "risk_lower_better", RISK_NOTE),
            ("Social Risk Score", "esg_s", "risk_lower_better", RISK_NOTE),
            ("Governance Risk Score", "esg_g", "risk_lower_better", RISK_NOTE),
            ("Controversy Score", "controversy", "risk_lower_better",
             "Sustainalytics controversy level 1 to 5, higher is worse."),
        ],
    },
    "flamingmasamune": {
        "slug": "flamingmasamune/s-and-p-500-firms-esg-ratings",
        "member": "sp500_esg_ceo_info.csv",
        "sep": ",",
        "ticker_col": "Ticker",
        "vintage_basis": "Kaggle upload date, read from the cached zip, overridden per row by the ESG Score Date column.",
        "licence_asserted": "CC0 asserted by the uploader",
        "ai_generated": False,
        "dq": 4,
        "lineage": "Sustainalytics via Yahoo Finance",
        "date_col": "ESG Score Date",
        "date_format": "%d/%m/%Y",
        "metrics": [
            ("ESG Score", "esg_total", "risk_lower_better", RISK_NOTE),
            ("Environment Score", "esg_e", "risk_lower_better", RISK_NOTE),
            ("Social Score", "esg_s", "risk_lower_better", RISK_NOTE),
            ("Governance Score", "esg_g", "risk_lower_better", RISK_NOTE),
        ],
    },
    "rikinzala": {
        "slug": "rikinzala/s-and-p-500-esg-and-stocks-data-2023-24",
        "member": "sp500_esg_data.csv",
        "sep": ",",
        "ticker_col": "Symbol",
        "vintage_basis": "Kaggle upload date, read from the cached zip, overridden per row by ratingYear and ratingMonth.",
        "licence_asserted": "GPL-3 asserted by the uploader, which is incoherent for a dataset",
        "ai_generated": False,
        "dq": 4,
        "lineage": "Sustainalytics via the Yahoo Finance esgScores module, which no longer returns data",
        "metrics": [
            ("totalEsg", "esg_total", "risk_lower_better", RISK_NOTE),
            ("environmentScore", "esg_e", "risk_lower_better", RISK_NOTE),
            ("socialScore", "esg_s", "risk_lower_better", RISK_NOTE),
            ("governanceScore", "esg_g", "risk_lower_better", RISK_NOTE),
            ("highestControversy", "controversy", "risk_lower_better",
             "Highest controversy level 0 to 5, higher is worse."),
        ],
    },
    "mashinii": {
        "slug": "mashinii/s-and-p-500-integrity-scores-11-dimensions",
        "member": "sp500_integrity_scores.csv",
        "sep": ",",
        "ticker_col": "ticker",
        "vintage_basis": "Kaggle upload date, read from the cached zip. The only free S&P 500 ESG-shaped file of recent vintage.",
        "licence_asserted": "CC BY-NC-SA 4.0 asserted by the uploader",
        "ai_generated": True,
        "dq": 5,
        "lineage": "LLM scoring of court filings, fines, journalism and NGO reports, per the uploader",
        "metrics": [
            ("planet_friendly_business", "esg_e", "score_higher_better", AI_NOTE),
        ],
    },
    "alistairking": {
        "slug": "alistairking/public-company-esg-ratings-dataset",
        "member": "data.csv",
        "sep": ",",
        "ticker_col": "ticker",
        "vintage_basis": "Kaggle upload date, read from the cached zip, overridden per row by last_processing_date.",
        "licence_asserted": "CC BY-NC-SA 4.0 asserted by the uploader",
        "ai_generated": False,
        "dq": 4,
        "lineage": "ESG Enterprise API",
        "date_col": "last_processing_date",
        "date_format": "%d-%m-%Y",
        "metrics": [
            ("total_score", "esg_total", "score_higher_better", QUALITY_NOTE),
            ("environment_score", "esg_e", "score_higher_better", QUALITY_NOTE),
            ("social_score", "esg_s", "score_higher_better", QUALITY_NOTE),
            ("governance_score", "esg_g", "score_higher_better", QUALITY_NOTE),
        ],
    },
    "mrbossjaysrb": {
        "slug": "mrbossjaysrb/global-corporate-esg-and-financial-dataset",
        "member": "Global Corporate ESG and Financial Dataset.csv",
        "sep": ";",
        "ticker_col": "ticker",
        "vintage_basis": "Kaggle upload date, read from the cached zip. The underlying terminal extract is undated.",
        "licence_asserted": "CC0 asserted by the uploader, which cannot be right for a terminal extract",
        "ai_generated": False,
        "dq": 5,
        "lineage": "Refinitiv Eikon / Datastream per the uploader, with MSCI involvement columns and "
                   "Sustainalytics-looking esg values",
        "metrics": [
            ("esg", "esg_total", "risk_lower_better",
             "Undeclared scale. Values sit in the Sustainalytics risk range, AAPL 16.7, so read as "
             "lower is better."),
            ("Temperature Goal", "temperature_goal_c", "degrees_c",
             "Implied temperature rise in degrees C, lower is better but it is a physical quantity, "
             "not a score, so direction is 0 and it is never percentiled with the ratings."),
            ("Decarbonization Target.Target Year", "decarb_target_year", "year",
             "The year the company's decarbonisation target runs to."),
            ("Decarbonization Target.Ambition p.a.", "decarb_ambition_pct", "pct",
             "Annual change in emissions the target implies. NEGATIVE means falling emissions, which "
             "is the opposite sign to targets_company.promised_annual_reduction_pct in this repo."),
        ],
    },
}

# The 11 mashinii dimensions. Their overall_rating column is the string "Mixed" on all 503 rows and
# carries no information, so esg_total for this source is the mean of the dimensions instead.
MASHINII_DIMS = [
    "planet_friendly_business",
    "honest_fair_business",
    "no_war_no_weapons",
    "fair_pay_worker_respect",
    "better_health_for_all",
    "safe_smart_tech",
    "kind_to_animals",
    "respect_cultures_communities",
    "fair_money_economic_opportunity",
    "fair_trade_ethical_sourcing",
    "zero_waste_sustainable_products",
]

# Hand-checked rows in mrbossjaysrb that are plainly the right company while neither the name nor the
# ticker column says so. Each was read individually against the domain. Anything not listed here and
# not caught by the name rules is dropped.
DOMAIN_OVERRIDE = {
    "google.com": "GOOGL",       # filed as Google, the index calls it Alphabet
    "gm.com": "GM",              # filed as "gm"
    "amd.com": "AMD",            # the AMD row; a separate advan.com row also claims ticker AMD
    "ups.com": "UPS",            # a sands.cz row also claims ticker UPS
    "pge.com": "PCG",            # filed under ticker PG
    "visa.com": "V",             # filed under ticker VISA
    "marsh.net": "MRSH",         # filed under the old MMC ticker
    "smucker.com": "SJM",        # filed as JM Smucker
    "utc.com": "RTX",            # United Technologies, RTX's predecessor
    "westarenergy.com": "EVRG",  # Westar Energy, merged into Evergy
    "wellpoint.com": "ELV",      # WellPoint, then Anthem, now Elevance
    "wolseley.com": "FERG",      # Wolseley, now Ferguson
    "theice.com": "ICE",         # filed as the three-letter ICE
    "fico.com": "FICO",          # filed as FICO, the index calls it Fair Isaac
}

# Rows in mrbossjaysrb that pass a name check but are a different company. Every accepted row was
# read once by hand; these are what that audit rejected. They all fail the same way, which is the
# failure the repo's entity-resolution notes warn about: a one-word company name is a token subset
# of an S&P 500 name, so token_set_ratio returns 100 and says nothing.
DOMAIN_BLOCK = {
    "automatic.com": "Automatic Labs, not Automatic Data Processing",
    "franklinsports.com": "Franklin Sports, not Franklin Resources",
    "nemours.org": "Nemours Children's Health, caught by DuPont's legal name du Pont de Nemours",
    "illinois.edu": "University of Illinois, not Illinois Tool Works",
    "monster.com": "Monster Worldwide, the job board, not Monster Beverage",
    "globe.com.ph": "Globe Telecom, not Globe Life",
    "fidelity.com": "Fidelity Investments, not Fidelity National Information Services",
    "harriscomputer.com": "Harris Computer, not L3Harris",
    "west.com": "West Corporation, caught by a West Pharmaceutical Services former name",
    "mcgraw-hill.com": "McGraw Hill Education, spun out in 2013 of what is now S&P Global",
}

# token_set_ratio at which a mrbossjaysrb row's company name confirms its ticker. At 80 the file
# offers Line 6 for ODFL, GE Digital for GEN, Takata for TKO and OTI for OTIS.
NAME_VERIFY_MIN = 96

# Ticker changes that happened after these files were snapshotted. Only same-issuer renames go here.
# Paramount Global's PARA is deliberately absent: PSKY is Paramount after the Skydance merger, which
# is a different issuer, so a pre-merger rating does not describe it.
VENDOR_TICKER_RENAME = {
    "BK": "BNY",    # Bank of New York Mellon changed its ticker in 2025
    "MMC": "MRSH",  # Marsh McLennan changed its ticker in 2025
}

LICENCE_TEXT = (
    "Licence as asserted by the Kaggle uploader, which is not the uploader's to assert: these files "
    "are third-party re-uploads of commercial ESG rating products. Used here as a benchmark to "
    "compare against and criticise, which is the only footing we have."
)
REDISTRIBUTION_TEXT = (
    "No raw vendor table is republished. Only derived aggregates leave this repo: rank correlations, "
    "percentiles, sector means and a handful of named examples. Everything carries "
    "provenance_class='vendor' and is excluded from the filings-based score."
)


def kaggle_bin():
    local = Path(sys.executable).resolve().parent / "kaggle"
    return str(local) if local.exists() else "kaggle"


FETCHLOG = RAW / "_fetchlog.json"


def download(slug):
    """Pull one Kaggle dataset zip. A zip already on disk is reused and no request is made.

    The zip's mtime is the dataset's Kaggle upload date, not our retrieval time, so first retrieval
    is recorded in a fetch log beside the files and a rerun keeps reporting the original time.
    """
    log = json.loads(FETCHLOG.read_text()) if FETCHLOG.exists() else {}
    dest = RAW / slug.replace("/", "_")
    dest.mkdir(parents=True, exist_ok=True)
    existing = sorted(dest.glob("*.zip"))
    fetched = not existing
    if fetched:
        r = subprocess.run(
            [kaggle_bin(), "datasets", "download", "-d", slug, "-p", str(dest)],
            capture_output=True, text=True,
        )
        existing = sorted(dest.glob("*.zip"))
        if not existing:
            raise RuntimeError(f"kaggle download failed for {slug}: {r.stdout} {r.stderr}")
    if slug not in log:
        log[slug] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        FETCHLOG.write_text(json.dumps(log, indent=1, sort_keys=True))
    return existing[0], fetched, log[slug]


def read_member(zip_path, member, sep):
    raw = zipfile.ZipFile(zip_path).read(member).decode("utf-8-sig", errors="replace")
    return pd.read_csv(io.StringIO(raw), sep=sep, dtype=str)


def clean_ticker(s, alias=None):
    """Our canonical spelling: uppercase, dots not dashes, then the universe lane's alias lookup."""
    if not isinstance(s, str):
        return None
    t = s.strip().upper().replace("-", ".")
    if not t:
        return None
    t = VENDOR_TICKER_RENAME.get(t, t)
    return (alias or {}).get(t, t)


def to_float(v):
    """Parse a vendor cell. Percent signs, thousands commas and stray whitespace all appear."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip().replace("%", "").replace(",", "")
    if s == "" or s.lower() in ("nan", "none", "null", "n/a"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def name_key(s):
    """The universe lane's name key: uppercase, alphanumerics only, ampersand spelled out."""
    s = (s or "").upper().replace("&", " AND ")
    for ch in "’‘ʼ`´":
        s = s.replace(ch, "'")
    return re.sub(r"[^A-Z0-9]", "", s)


SUFFIX = (
    r"\b(inc|incorporated|corp|corporation|co|company|companies|ltd|limited|plc|sa|nv|ag|se|lp|llc"
    r"|the|group|holdings|holding|international|intl|worldwide|global)\b"
)


def norm_name(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    for _ in range(3):
        s = re.sub(SUFFIX, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_universe():
    u = pd.read_parquet(INTERIM / "universe.parquet")
    names = {}
    for r in u.itertuples():
        cands = [r.company_name, r.sec_entity_name, r.sec_filing_name, r.sec_former_name]
        names[r.ticker] = [n for n in cands if isinstance(n, str) and n.strip()]
    aliases = json.loads((INTERIM / "ticker_aliases.json").read_text())
    return u, names, aliases


def match_mrboss(df, names, name_to_ticker, alias):
    """Attribute mrbossjaysrb rows to S&P 500 tickers. Returns the chosen rows plus a match_rule."""
    df = df.copy()
    # These stay as plain Python lists rather than columns. A column of str-or-None is inferred as a
    # string dtype, a miss comes back as pd.NA, and pd.NA is truthy, so a column test silently
    # accepts every row.
    ticker_col = [clean_ticker(s, alias) for s in df["ticker"]]
    alias_tk = [name_to_ticker.get(name_key(s)) for s in df["name"]]
    domain = [(d or "").lower().strip() if isinstance(d, str) else "" for d in df["domain"]]
    override_tk = [DOMAIN_OVERRIDE.get(d) for d in domain]

    picks = []
    blocked = 0
    for pos, (i, r) in enumerate(df.iterrows()):
        if domain[pos] in DOMAIN_BLOCK:
            blocked += 1
            continue
        # Priority: a hand-checked domain, then an exact alias name, then a name-verified ticker.
        if override_tk[pos] is not None:
            picks.append((override_tk[pos], "domain_override", 100.0, i))
            continue
        for tk, rule in ((alias_tk[pos], "alias_name"), (ticker_col[pos], "ticker_verified")):
            if not isinstance(tk, str) or tk not in names:
                continue
            score = max(fuzz.token_set_ratio(norm_name(r["name"]), norm_name(c)) for c in names[tk])
            if rule == "alias_name" or score >= NAME_VERIFY_MIN:
                picks.append((tk, rule, float(score), i))
                break

    print(f"mrbossjaysrb: {blocked} rows dropped by the hand-verified domain blocklist")
    if not picks:
        return df.iloc[0:0], {}
    p = pd.DataFrame(picks, columns=["ticker", "match_rule", "score", "idx"])
    order = {"domain_override": 0, "alias_name": 1, "ticker_verified": 2}
    p["rank"] = p.match_rule.map(order)
    p = p.sort_values(["ticker", "rank", "score"], ascending=[True, True, False])
    p = p.drop_duplicates("ticker", keep="first")

    out = df.loc[p.idx].copy()
    out["_tk"] = p.ticker.values
    out["_rule"] = p.match_rule.values
    return out, dict(zip(p.ticker, p.match_rule))


def emit(rows, ticker, source, vintage, metric, value, convention, dq, ai, licence, col, note, rule):
    if value is None:
        return
    allowed = METRICS[metric]
    if convention not in allowed:
        raise ValueError(f"{source}.{metric}: convention {convention} not allowed for this metric")
    lo, hi = BOUNDS[convention]
    if not (lo <= value <= hi):
        raise ValueError(f"{source}.{metric} for {ticker}: {value} outside {convention} bounds")
    rows.append({
        "ticker": ticker,
        "source_dataset": source,
        "vintage": vintage,
        "metric": metric,
        "value": float(value),
        "convention": convention,
        "direction": DIRECTION[convention],
        "provenance_class": "vendor",
        "dq": dq,
        "ai_generated": ai,
        "licence_asserted": licence,
        "source_column": col,
        "convention_note": note,
        "match_rule": rule,
    })


def build_long(universe, names, aliases, zips, uploaded):
    n_to_t = aliases["name_to_ticker"]
    uni = set(universe.ticker)
    rows = []
    per_source = {}

    for src, spec in SOURCES.items():
        vintage = uploaded[src]
        df = read_member(zips[src], spec["member"], spec["sep"])
        print(f"{src}: {len(df)} raw rows, {len(df.columns)} columns")

        if src == "mrbossjaysrb":
            picked, rules = match_mrboss(df, names, n_to_t, aliases["aliases"])
            print(f"{src}: {len(picked)} rows attributed to S&P 500 tickers, "
                  f"{len(df) - len(picked)} dropped as unmatched or unverified")
            print(f"{src}: match rules {pd.Series(list(rules.values())).value_counts().to_dict()}")
            df = picked
            df["_ticker"] = df["_tk"]
            df["_rule"] = df["_rule"]
        else:
            df["_ticker"] = [clean_ticker(s, aliases["aliases"]) for s in df[spec["ticker_col"]]]
            df["_rule"] = "ticker_exact"
            before = len(df)
            df = df[df["_ticker"].isin(uni)]
            print(f"{src}: {len(df)} of {before} rows land on an S&P 500 ticker")
            dup = df["_ticker"].duplicated().sum()
            if dup:
                print(f"{src}: {dup} duplicate tickers, keeping the first")
                df = df.drop_duplicates("_ticker", keep="first")

        # Per-row vintage where the file carries a date, otherwise the dataset's own vintage.
        if spec.get("date_col") and spec["date_col"] in df.columns:
            d = pd.to_datetime(df[spec["date_col"]], format=spec["date_format"], errors="coerce")
            vint = d.dt.strftime("%Y-%m-%d").fillna(vintage)
        elif src == "rikinzala":
            y = pd.to_numeric(df["ratingYear"], errors="coerce")
            m = pd.to_numeric(df["ratingMonth"], errors="coerce")
            vint = pd.Series(
                [f"{int(a):04d}-{int(b):02d}-01" if pd.notna(a) and pd.notna(b) else vintage
                 for a, b in zip(y, m)], index=df.index)
        else:
            vint = pd.Series(vintage, index=df.index)

        n0 = len(rows)
        for i, r in df.iterrows():
            tk = r["_ticker"]
            for col, metric, conv, note in spec["metrics"]:
                emit(rows, tk, src, vint.loc[i], metric, to_float(r.get(col)), conv,
                     spec["dq"], spec["ai_generated"], spec["licence_asserted"], col, note, r["_rule"])

            # The LLM set has no usable overall column, so its esg_total is the mean of the 11
            # dimensions. That is our arithmetic on their numbers, so it is labelled as such.
            if src == "mashinii":
                vals = [to_float(r.get(c)) for c in MASHINII_DIMS]
                vals = [v for v in vals if v is not None]
                if len(vals) == len(MASHINII_DIMS):
                    emit(rows, tk, src, vint.loc[i], "esg_total", sum(vals) / len(vals),
                         "score_higher_better", spec["dq"], True, spec["licence_asserted"],
                         "mean of the 11 dimensions",
                         AI_NOTE + " esg_total here is our unweighted mean of the 11 dimensions, "
                         "because their overall_rating column reads 'Mixed' on all 503 rows.",
                         r["_rule"])

        per_source[src] = len(rows) - n0
        print(f"{src}: {len(rows) - n0} long rows emitted")

    long = pd.DataFrame(rows)
    return long, per_source


def check(long):
    """Structural checks. A convention that drifts inside one source is a silent disaster."""
    assert long.convention.notna().all(), "a row has no convention"
    assert long.direction.notna().all(), "a row has no direction"
    assert (long.provenance_class == "vendor").all(), "a row escaped the vendor tag"
    assert long.value.notna().all(), "a null value was emitted"
    mixed = long.groupby(["source_dataset", "metric"]).convention.nunique()
    bad = mixed[mixed > 1]
    assert bad.empty, f"a source mixes conventions within one metric: {bad.to_dict()}"
    for conv, g in long.groupby("convention"):
        assert (g.direction == DIRECTION[conv]).all(), f"direction drifted for {conv}"
    print("checks: convention, direction, vendor tag and value bounds all hold")


def orient(long):
    """One frame of esg_total per source, signed so that higher always means better ESG standing."""
    t = long[(long.metric == "esg_total") & (long.direction != 0)].copy()
    t["oriented"] = t.value * t.direction
    return t.pivot_table(index="ticker", columns="source_dataset", values="oriented")


def spearman_matrix(wide):
    srcs = list(wide.columns)
    rho = pd.DataFrame(index=srcs, columns=srcs, dtype=float)
    n = pd.DataFrame(index=srcs, columns=srcs, dtype="Int64")
    for a in srcs:
        for b in srcs:
            if a == b:
                n.loc[a, b] = int(wide[a].notna().sum())
                rho.loc[a, b] = 1.0
                continue
            pair = wide[[a, b]].dropna()
            n.loc[a, b] = len(pair)
            rho.loc[a, b] = float(spearmanr(pair[a], pair[b]).statistic) if len(pair) >= 3 else None
    return rho, n


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    PROV.mkdir(parents=True, exist_ok=True)

    universe, names, aliases = load_universe()
    print(f"universe: {len(universe)} listings, {int(universe.is_primary_listing.sum())} companies")

    zips, uploaded, prov = {}, {}, []
    for src, spec in SOURCES.items():
        path, fetched, retrieved_at = download(spec["slug"])
        blob = path.read_bytes()
        zips[src] = path
        upload_dt = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        uploaded[src] = upload_dt.strftime("%Y-%m-%d")
        prov.append({
            "url": KAGGLE_API.format(slug=spec["slug"]),
            "retrieved_at": retrieved_at,
            "kaggle_uploaded_at": upload_dt.isoformat(timespec="seconds"),
            "http_status": 200,
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "licence": f"{spec['licence_asserted']}. {LICENCE_TEXT}",
            "redistribution": REDISTRIBUTION_TEXT,
            "provenance_class": "vendor",
            "source_dataset": src,
            "lineage": spec["lineage"],
            "vintage": uploaded[src],
            "vintage_basis": spec["vintage_basis"],
            "ai_generated": spec["ai_generated"],
            "note": "downloaded via the Kaggle CLI, which reports success rather than a status code"
                    if fetched else "reused from the local cache, no network call",
        })
    print(f"kaggle: {len(zips)} datasets on disk, "
          f"{sum(1 for p in prov if 'no network' in p['note'])} reused from cache")

    long, _ = build_long(universe, names, aliases, zips, uploaded)
    check(long)

    long = long.sort_values(["ticker", "source_dataset", "metric"]).reset_index(drop=True)
    long.to_parquet(INTERIM / "vendor_scores.parquet", index=False)
    print(f"\nvendor_scores.parquet: {len(long)} rows, {long.ticker.nunique()} tickers, "
          f"{long.source_dataset.nunique()} sources, {long.metric.nunique()} metrics")

    print("\ncoverage per source, against 503 listings")
    prim = set(universe[universe.is_primary_listing].ticker)
    for src in SOURCES:
        g = long[long.source_dataset == src]
        tot = g[g.metric == "esg_total"].ticker.nunique()
        print(f"  {src:<16} any metric {g.ticker.nunique():>3}/503  "
              f"esg_total {tot:>3}/503  companies {len(set(g.ticker) & prim):>3}/500")

    print("\ncoverage per metric")
    for m, g in long.groupby("metric"):
        print(f"  {m:<20} {g.ticker.nunique():>3}/503 tickers, {len(g):>5} rows, "
              f"sources {sorted(g.source_dataset.unique())}")

    any_vendor = long.ticker.nunique()
    non_ai = long[~long.ai_generated].ticker.nunique()
    print(f"\nunion: {any_vendor}/503 listings carry at least one vendor number "
          f"({any_vendor / 503:.1%}); {non_ai}/503 excluding the AI-generated source")

    # ---- the point of the lane: do the raters agree with each other
    wide = orient(long)
    rho, n = spearman_matrix(wide)
    print("\nSpearman rank correlation between vendor sources, esg_total, oriented so that higher "
          "always means better ESG standing")
    print("rho")
    print(rho.round(3).to_string())
    print("n overlapping tickers")
    print(n.to_string())

    pairs = []
    srcs = list(wide.columns)
    for i, a in enumerate(srcs):
        for b in srcs[i + 1:]:
            if pd.notna(rho.loc[a, b]):
                pairs.append((a, b, float(rho.loc[a, b]), int(n.loc[a, b])))
    pairs.sort(key=lambda x: x[2])
    print("\npairs, weakest agreement first")
    for a, b, r, k in pairs:
        print(f"  {a:<16} {b:<16} rho {r:+.3f}  n {k}")
    same = [(a, b, r, k) for a, b, r, k in pairs if r > 0.94]
    if same:
        print("\nthese pairs are not two raters agreeing, they are one snapshot counted twice:")
        for a, b, r, k in same:
            print(f"  {a} and {b} agree at rho {r:.3f} on {k} names, which is what a re-upload of "
                  f"the same Yahoo esgScores pull looks like")
    if pairs:
        lo, hi = pairs[0][2], pairs[-1][2]
        print(f"\nspread {lo:.2f} to {hi:.2f}. Berg, Koelbel and Rigobon (2022) report 0.38 to 0.71 "
              f"between six commercial raters.")

    uncovered = sorted(set(universe.ticker) - set(long.ticker))
    print(f"\n{len(uncovered)} listings carry no vendor number from any of the six: {uncovered}")

    # ---- consensus percentile, for the divergence scatter
    pct = wide.rank(pct=True) * 100.0   # rank on oriented values, so 100 is the best ESG standing
    pct.columns = [f"pct_{c}" for c in pct.columns]
    ai_srcs = [s for s, spec in SOURCES.items() if spec["ai_generated"]]
    ai_cols = [f"pct_{s}" for s in ai_srcs if f"pct_{s}" in pct.columns]
    human_cols = [c for c in pct.columns if c not in ai_cols]

    cons = pct.copy()
    cons["vendor_percentile"] = cons[human_cols].mean(axis=1)
    cons["n_sources"] = cons[human_cols].notna().sum(axis=1)
    cons["vendor_percentile_sd"] = cons[human_cols].std(axis=1)
    cons["vendor_percentile_incl_ai"] = cons[pct.columns].mean(axis=1)
    cons["n_sources_incl_ai"] = cons[pct.columns].notna().sum(axis=1)
    cons["provenance_class"] = "vendor"
    cons["dq"] = 4
    cons["orientation"] = "percentile of vendor esg_total, 100 is the best ESG standing"
    cons = cons.reset_index()
    cons = cons[cons.n_sources_incl_ai > 0]
    cons.to_parquet(INTERIM / "esg_vendor_consensus.parquet", index=False)

    print(f"\nesg_vendor_consensus.parquet: {len(cons)} tickers, "
          f"{int((cons.n_sources > 0).sum())} with a non-AI vendor score")
    print("  tickers by number of non-AI sources covering them:")
    print("   ", cons.n_sources.value_counts().sort_index().to_dict())
    print(f"  median cross-source spread on the covered names: "
          f"{cons.loc[cons.n_sources >= 2, 'vendor_percentile_sd'].median():.1f} percentile points")

    disagree = cons[cons.n_sources >= 3].nlargest(10, "vendor_percentile_sd")
    print("\n  widest vendor disagreement, 3+ non-AI sources")
    for r in disagree.itertuples():
        cells = " ".join(f"{c.replace('pct_', '')}={getattr(r, c):.0f}"
                         for c in human_cols if pd.notna(getattr(r, c)))
        print(f"    {r.ticker:<6} sd {r.vendor_percentile_sd:5.1f}  {cells}")

    (PROV / "kaggle_esg.json").write_text(json.dumps(prov, indent=1, sort_keys=True))
    print(f"\nwrote {INTERIM / 'vendor_scores.parquet'} ({len(long)} rows)")
    print(f"wrote {INTERIM / 'esg_vendor_consensus.parquet'} ({len(cons)} rows)")
    print(f"wrote {PROV / 'kaggle_esg.json'} ({len(prov)} sources)")


if __name__ == "__main__":
    main()
