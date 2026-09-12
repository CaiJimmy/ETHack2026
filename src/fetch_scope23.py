"""Scope 2 and Scope 3 emissions, from the only free sources that actually carry tonnes.

NEVER SUM tonnes_co2e ACROSS COMPANIES. The GHG Protocol Corporate Value Chain (Scope 3)
Standard is explicit that the same tonne is legitimately reported by several firms in one value
chain: a steelmaker's Scope 1 is an automaker's Scope 3 category 1 and a fleet buyer's Scope 3
category 11. Scope 3 is designed for company-level decisions, not for portfolio aggregation, and
adding it up double counts by construction. The same goes for Scope 2, which is the generator's
Scope 1 seen from the meter. Every scope sits in its own row here, and nothing in this file is
ever pre-summed, so that no downstream groupby can quietly commit that error. If you need one
number per company, pick one scope and say which.

The gap this fills. The mandatory spine (EPA GHGRP and CAMD) is Scope 1 and US-only, and it
covers 142 of 503 listings because most of the index runs no US facility over the 25,000 tCO2e
threshold. Purchased electricity is exactly where an asset-light company's emissions live, and no
regulator compels its disclosure in the US, so there is no mandatory source to fetch. Everything
with a tonnage in this table is therefore provenance_class='voluntary': a number the company chose
to publish in its own sustainability report. It is a benchmark for our score, never an input.

What each source turned out to be, measured rather than hoped for:

  nopperl/corporate-emission-reports (HF, PDDL)
      100 reports, hand extracted, with Scope 2 split into market and location basis and all 15
      Scope 3 categories broken out. The cleanest emissions rows in the free world. 39 are NYSE
      listings, of which 15 are in the S&P 500 today.

  nopperl/sustainability-report-emissions (HF, PDDL)
      3,233 reports, Scope 1/2/3 totals extracted by Mixtral-8x7B, which the author measures at
      68% accuracy against the hand-extracted set above. Wider but weaker, so it gets dq=3 and the
      hand set gets dq=2. Its Scope 2 is market-based by construction: the extraction prompt says
      "For scope 2 emissions, extract only market-based emissions".

      Treat any single figure from it as indicative. Spot-checking shows the extractor sometimes
      lands on the wrong row of the right table: Microsoft FY2014 comes back with a Scope 1 of
      exactly zero, which no operating company has. Use it for cohort statistics and for ranking,
      not for a company-level claim you would defend on stage.

      TRAP. The ids are EXCHANGE_TICKER_YEAR and the exchange prefix is load bearing. LSE_BA is
      BAE Systems, not Boeing; ASX_DOW is Downer, not Dow; TSX_T is Telus, not AT&T. Ignoring the
      prefix produces 130 false-positive rows on our universe. Only NASDAQ, NYSE and OTC ids are
      used here, which is 101 S&P 500 tickers, not the 126 a name-only match suggests.

  CDP 2025 corporate scores, via the public Flourish embeds behind cdp.net/en/data/scores
      CARRIES NO EMISSIONS. Measured, not assumed: 30,458 rows, 5 columns, which are company name,
      country, and three grade columns holding an icon URL such as Climate-A-minus-Icon.svg. Zero
      cells in the grade columns contain a number. CDP's letter grade is a disclosure-quality
      assessment, and the tonnes behind it sit in the licensed corporate response database. This
      script fetches the embeds, proves the absence and writes zero rows from them.

  Kaggle jaidityachopra/esg-sustainability-reports-of-s-and-p-500-companies
      CARRIES NO EMISSIONS. 866 report texts over 263 tickers. 804 of them contain the word
      "scope" and not one contains a single digit anywhere in its text: the uploader's
      preprocessing strips every numeral. The bundled e/s/g scores are Sustainalytics-lineage risk
      scores, not tonnes. Zero rows.

  Kaggle mrbossjaysrb/global-corporate-esg-and-financial-dataset
      CARRIES NO EMISSIONS. 85 columns of product-involvement flags, controversy counts, SDG
      alignment and decarbonisation-target fields. Not one tonnage column. Only its header is read
      here; its values are a Refinitiv/MSCI extract published under a CC0 claim the uploader cannot
      make, so nothing from it enters this table.

How wrong the LLM extraction actually is, measured against the mandatory spine.

A company's global Scope 1 cannot be smaller than its US-only GHGRP total, so the 77 ticker-years
where a nopperl figure meets a GHGRP figure are a free accuracy test. The median ratio of reported
to GHGRP is 1.29, which is the shape you expect once non-US facilities are added. Seven of the 77
come in below a tenth of the GHGRP number, which no disclosure boundary explains: Steel Dynamics
2018 at 1,081 tonnes against a measured 2,300,475, Skyworks 2019 at 23 against 33,708, Amgen 2013
at 101 against 50,646. Those are kiloton-versus-tonne misreads. Every row extracted from one of
those report PDFs carries magnitude_suspect=True, Scope 2 and 3 rows included, because the error
belongs to the extraction and not to the scope. FILTER magnitude_suspect BEFORE USING A TONNAGE.

Estimated Scope 2, and why this file stops short of a tonnage.

Location-based Scope 2 is an emission factor times electricity consumed. The factor is free and
public; the consumption is not. There is no free per-company electricity purchase figure anywhere
in the US: EIA-861 reports utility retail sales by state and customer class, and nobody publishes
the buyer side. Multiplying a sector-average kWh-per-dollar by revenue would produce a number that
looks like data and is not, so this script does not do it. It emits the half that is real instead:
one row per listing per eGRID year carrying scope='2_location_factor_input', tonnes_co2e NULL, and
the grid factor for the company's HQ region in scope2_factor_g_per_kwh_hq_region, at dq=5. Whoever
later finds a consumption estimate multiplies by this and owns the dq.

The HQ state is a weak proxy for where a company actually buys power, and it is stated as such:
hq_subregion_gen_share says how much of that state's generation sits in the subregion we assigned,
which runs from 0.40 in Mississippi to 1.00 in single-subregion states. New York is the one state
where the dominant-generation rule is wrong for headquarters rather than merely imprecise, because
upstate hydro and nuclear dominate generation while 40 of the index's 52 New York HQs are in New
York City, so the five boroughs and Long Island are assigned by hand to NYCW and NYLI.

Outputs:
  data/interim/scope23.parquet
  data/interim/provenance/hf_nopperl.json
  data/interim/provenance/cdp_flourish_scores.json
  data/interim/provenance/kaggle_esg_datasets.json
"""

import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance"
RAW_HF = ROOT / "data" / "raw" / "hf_nopperl"
RAW_CDP = ROOT / "data" / "raw" / "cdp_flourish"
RAW_KAGGLE = ROOT / "data" / "raw" / "kaggle_esg"
OUT = INTERIM / "scope23.parquet"

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"

HF_FILES = [
    {
        "key": "corp",
        "dataset": "nopperl/corporate-emission-reports",
        "url": "https://huggingface.co/datasets/nopperl/corporate-emission-reports/resolve/main/corp_emissions.parquet",
        "cache": "corp_emissions.parquet",
    },
    {
        "key": "train",
        "dataset": "nopperl/sustainability-report-emissions",
        "url": "https://huggingface.co/datasets/nopperl/sustainability-report-emissions/resolve/main/emissions_train.parquet",
        "cache": "emissions_train.parquet",
    },
]

# The two sibling datasets are the same 3,233 instances reformatted for finetuning, so they add no
# coverage. Checked with the datasets-server info endpoint rather than by pulling 52 MB of prompts.
HF_SIBLINGS = [
    "nopperl/sustainability-report-emissions-instruction-style",
    "nopperl/sustainability-report-emissions-dpo",
]

HF_LICENCE = "Open Data Commons Public Domain Dedication and Licence (PDDL), declared on both dataset cards."
HF_REDIST = (
    "PDDL is a public domain dedication, so derived numbers may be published with attribution to "
    "the dataset author and to the underlying company reports."
)

# cdp.net/en/data/scores renders its tables through these public Flourish embeds. The /embed URL
# 301s to flo.uri.sh, so redirects have to be followed.
CDP_EMBEDS = {
    "28119771": "Public corp scores 2025",
    "28119907": "Corp A List 2025",
}
CDP_LICENCE = (
    "CDP Terms of Website Use: scores must not be used for anything other than internal, "
    "non-commercial use without prior written consent from CDP."
)
CDP_REDIST = (
    "Do not publish per-company CDP grades. Internal benchmarking only. Nothing from this source "
    "is written to any table in this repo; the fetch exists to document that the embeds carry no "
    "emissions figures."
)

KAGGLE_DATASETS = [
    {
        "key": "reports",
        "slug": "jaidityachopra/esg-sustainability-reports-of-s-and-p-500-companies",
        "file": "preprocessed_content.csv",
        "licence": "Apache 2.0 asserted by the uploader; the underlying text is the companies' own published reports.",
        "redistribution": "Derived statistics may be published with attribution to the uploader. No tonnage is extracted because none survives the preprocessing.",
    },
    {
        "key": "global",
        "slug": "mrbossjaysrb/global-corporate-esg-and-financial-dataset",
        "file": "Global Corporate ESG and Financial Dataset.csv",
        "licence": "CC0 claimed by the uploader. The content is a Refinitiv Eikon / MSCI extract, which the uploader has no right to place in the public domain, so the claim is invalid.",
        "redistribution": "Do not publish. Only the header row is read, to establish that the dataset carries no emissions column.",
    },
]

# GHG Protocol Scope 3 category order, 1 to 15, mapped to the column names in corp_emissions.
# "captial_goods" is the dataset author's typo and is kept verbatim so the read does not silently
# drop category 2.
SCOPE3_CATEGORY_COLS = {
    1: "purchased_goods_and_services",
    2: "captial_goods",
    3: "fuel_and_energy",
    4: "upstream_transportation_and_distribution",
    5: "waste",
    6: "business_travel",
    7: "employee_commuting",
    8: "upstream_leased_assets",
    9: "downstream_transportation_and_distribution",
    10: "processing_of_sold_products",
    11: "use_of_sold_products",
    12: "end_of_life",
    13: "downstream_leased_assets",
    14: "franchises",
    15: "investment_portfolio",
}

# corp_emissions identifies a company only by the URL of its report, so the host has to be mapped
# by hand. Every entry below was read off the URL and checked against the report's own cover page.
# Automatic matching is not safe here: the project's name normaliser strips a trailing CO, which
# turns wesco into WES (Western Midstream) and graco into GRA (W R Grace).
CORP_HOST_TICKER = {
    "www.sempra.com": "SRE",
    "assets.aon.com": "AON",
    "www.bms.com": "BMY",
    "www.marathonpetroleum.com": "MPC",
    "www.ecolab.com": "ECL",
    "mcdn.martinmarietta.com": "MLM",
    "www.kindermorgan.com": "KMI",
    "www.idexcorp.com": "IEX",
    "dam.abbott.com": "ABT",
    "www.xylem.com": "XYL",
    "corporate.lowes.com": "LOW",
    "cdn.hasbro.com": "HAS",
    "sustainability.lockheedmartin.com": "LMT",
    "www.assurant.com": "AIZ",
    "www.jacobs.com": "J",
}

# Reports that belong to a company the index no longer holds separately. Attributing a standalone
# subsidiary report to its acquirer is the Energy Harbor / Vistra mistake the entity-resolution
# audit already caught once: the parent's own report covers a different perimeter and a different
# year, so these are dropped rather than merged.
CORP_HOST_BLOCKED = {
    "www.redhat.com": "Red Hat has been an IBM subsidiary since 2019; this is a subsidiary-only report, not IBM's.",
    "www.vmware.com": "VMware's 2022 standalone report predates the Broadcom acquisition and is not AVGO's perimeter.",
    "www.evoqua.com": "Evoqua's 2022 standalone report predates the Xylem acquisition and would double count with XYL's own row.",
}

# Facebook renamed itself to Meta Platforms in 2021 and kept CIK 0001326801, so the 2020 report
# under the old ticker is the same registrant. Only same-entity renames belong here. Acquisitions
# do not: XLNX is not AMD and ATVI is not MSFT, because the acquirer's report covers a perimeter
# the target's report never did.
FORMER_TICKER = {"FB": "META"}

US_EXCHANGES = {"NASDAQ", "NYSE", "OTC"}

STATE_TO_USPS = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY", "D.C.": "DC", "District of Columbia": "DC",
}

# NYISO splits New York into three eGRID subregions and generation weight puts the whole state on
# upstate hydro and nuclear. 40 of the index's 52 New York headquarters are in the five boroughs,
# which is NYCW, and the Nassau and Suffolk ones are NYLI. Every other multi-subregion state was
# checked and its dominant subregion is also the one its headquarters sit in.
CITY_SUBREGION = {
    ("NY", "NEW YORK CITY"): "NYCW",
    ("NY", "BROOKLYN"): "NYCW",
    ("NY", "MANHATTAN"): "NYCW",
    ("NY", "MELVILLE"): "NYLI",
    ("NY", "JERICHO"): "NYLI",
    ("NY", "LAKE SUCCESS"): "NYLI",
}

_NAME_SUFFIX = re.compile(
    r"(CORPORATION|CORP|COMPANY|COMPANIES|INCORPORATED|INC|PLC|LTD|LIMITED|LLC|LP|"
    r"HOLDINGS|HOLDING|GROUP|TRUST|THE|SA|NV|AG|CO)$"
)


def normalise_name(raw):
    """Same rule as fetch_universe.normalise_name, so the keys in ticker_aliases.json match."""
    if raw is None or raw != raw:
        return ""
    s = re.sub(r"[^A-Za-z0-9]", "", str(raw).upper())
    prev = None
    while s != prev:
        prev = s
        s = _NAME_SUFFIX.sub("", s)
    return s


def fetch(url, path, prov, licence, redistribution, provenance_class):
    """GET url into path once. A second run reads the file and makes no request."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = path.exists() and path.stat().st_size > 0
    if cached:
        body = path.read_bytes()
        status = None
    else:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=180, allow_redirects=True)
        status = r.status_code
        r.raise_for_status()
        body = r.content
        path.write_bytes(body)
    prov.append(
        dict(
            url=url,
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            http_status=status if status is not None else "not requested, served from cache",
            bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            local_path=str(path.relative_to(ROOT)),
            licence=licence,
            redistribution=redistribution,
            provenance_class=provenance_class,
            served_from_cache_this_run=cached,
        )
    )
    return body


def kaggle_download(slug, filename, prov, licence, redistribution, provenance_class):
    """Pull one Kaggle dataset with the CLI. Returns the local path, or None if it failed."""
    RAW_KAGGLE.mkdir(parents=True, exist_ok=True)
    path = RAW_KAGGLE / filename
    cached = path.exists() and path.stat().st_size > 0
    if not cached:
        cli = ROOT / ".venv" / "bin" / "kaggle"
        proc = subprocess.run(
            [str(cli), "datasets", "download", "-d", slug, "-p", str(RAW_KAGGLE), "--unzip"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not path.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["no output"]
            print(f"  kaggle {slug}: FAILED, {tail[0][:200]}")
            return None
    body_hash = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            body_hash.update(chunk)
            size += len(chunk)
    prov.append(
        dict(
            url=f"https://www.kaggle.com/datasets/{slug}",
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            http_status="200 via kaggle CLI" if not cached else "not requested, served from cache",
            bytes=size,
            sha256=body_hash.hexdigest(),
            local_path=str(path.relative_to(ROOT)),
            licence=licence,
            redistribution=redistribution,
            provenance_class=provenance_class,
            served_from_cache_this_run=cached,
        )
    )
    return path


def row(**kw):
    """One emissions row. Every column exists on every row so the parquet schema is stable."""
    base = dict(
        ticker=None,
        fy=None,
        scope=None,
        tonnes_co2e=None,
        source=None,
        provenance_class=None,
        dq=None,
        reported_or_estimated=None,
        scope2_factor_g_per_kwh_hq_region=None,
        scope2_factor_g_per_kwh_hq_state=None,
        scope2_factor_basis=None,
        hq_state=None,
        hq_country=None,
        hq_subregion_code=None,
        hq_subregion_gen_share=None,
        extraction=None,
        match_method=None,
        source_url=None,
        source_pages=None,
        ghgrp_crosscheck_ratio=None,
        magnitude_suspect=False,
        note=None,
    )
    base.update(kw)
    return base


def load_universe():
    u = pd.read_parquet(INTERIM / "universe.parquet")
    aliases = json.load(open(INTERIM / "ticker_aliases.json"))
    return u, aliases


def parse_nopperl_id(raw):
    """EXCHANGE_TICKER_YEAR, sometimes with a trailing uuid. Returns (exchange, ticker, year)."""
    parts = str(raw).split("_")
    if len(parts) < 3:
        return None
    exchange, ticker, year = parts[0], parts[1], parts[2]
    if not re.fullmatch(r"\d{4}", year):
        return None
    return exchange.upper(), ticker.upper().replace("-", "."), int(year)


def build_train_rows(df, aliases, report):
    """Scope 1/2market/3total from the Mixtral-extracted set, US listings only."""
    alias = aliases["aliases"]
    rows = []
    n_parsed = 0
    n_us = 0
    foreign_collisions = 0
    for rec in df.to_dict("records"):
        parsed = parse_nopperl_id(rec["id"])
        if parsed is None:
            continue
        n_parsed += 1
        exchange, raw_ticker, year = parsed
        if exchange not in US_EXCHANGES:
            # The trap this guard exists for: a foreign ticker that happens to spell an S&P one.
            if raw_ticker in alias:
                foreign_collisions += 1
            continue
        n_us += 1
        ticker = FORMER_TICKER.get(raw_ticker, raw_ticker)
        canonical = alias.get(ticker)
        if canonical is None:
            continue
        method = "exchange_ticker" if raw_ticker == ticker else "exchange_ticker_former_name"
        pages = rec.get("sources")
        pages_str = (
            ",".join(str(int(p)) for p in pages if p == p) if pages is not None and len(pages) else None
        )
        for col, scope in (("scope_1", "1"), ("scope_2", "2_market"), ("scope_3", "3_total")):
            v = rec.get(col)
            if v is None or v != v:
                continue
            rows.append(
                row(
                    ticker=canonical,
                    fy=year,
                    scope=scope,
                    tonnes_co2e=float(v),
                    source="hf_nopperl_sustainability_report_emissions",
                    provenance_class="voluntary",
                    dq=3,
                    reported_or_estimated="reported",
                    extraction="llm_mixtral_8x7b_68pct_accuracy",
                    match_method=method,
                    source_url=rec.get("url"),
                    source_pages=pages_str,
                    note="fy is the report year in the dataset id, which may lead the fiscal year by one",
                )
            )
    report["nopperl_train_ids_parsed"] = n_parsed
    report["nopperl_train_us_rows"] = n_us
    report["nopperl_train_foreign_ticker_collisions_avoided"] = foreign_collisions
    return rows


def build_corp_rows(df, aliases, report):
    """Hand-extracted set: Scope 2 on both bases, plus all 15 Scope 3 categories."""
    alias = aliases["aliases"]
    rows = []
    hosts_seen = {}
    for rec in df.to_dict("records"):
        host = urlparse(str(rec["url"])).netloc
        hosts_seen[host] = hosts_seen.get(host, 0) + 1
        if host in CORP_HOST_BLOCKED:
            continue
        ticker = CORP_HOST_TICKER.get(host)
        if ticker is None:
            continue
        canonical = alias.get(ticker)
        if canonical is None:
            continue
        fy = int(rec["emission_year"])
        pages = {
            "1": rec.get("scope_1_page"),
            "2_market": rec.get("scope_2_market_page"),
            "2_location": rec.get("scope_2_location_page"),
            "3_total": rec.get("scope_3_page"),
        }
        totals = {
            "1": rec.get("scope_1"),
            "2_market": rec.get("scope_2_market"),
            "2_location": rec.get("scope_2_location"),
            "3_total": rec.get("scope_3"),
        }
        for scope, v in totals.items():
            if v is None or v != v:
                continue
            p = pages.get(scope)
            rows.append(
                row(
                    ticker=canonical,
                    fy=fy,
                    scope=scope,
                    tonnes_co2e=float(v),
                    source="hf_nopperl_corporate_emission_reports",
                    provenance_class="voluntary",
                    dq=2,
                    reported_or_estimated="reported",
                    extraction="manual",
                    match_method="report_url_host_override",
                    source_url=rec.get("url"),
                    source_pages=",".join(str(x) for x in p) if p is not None and len(p) else None,
                )
            )
        for cat, col in SCOPE3_CATEGORY_COLS.items():
            v = rec.get(col)
            if v is None or v != v:
                continue
            rows.append(
                row(
                    ticker=canonical,
                    fy=fy,
                    scope=f"3_cat{cat}",
                    tonnes_co2e=float(v),
                    source="hf_nopperl_corporate_emission_reports",
                    provenance_class="voluntary",
                    dq=2,
                    reported_or_estimated="reported",
                    extraction="manual",
                    match_method="report_url_host_override",
                    source_url=rec.get("url"),
                    note="Scope 3 categories do not necessarily sum to 3_total; the company reports each separately",
                )
            )
    unmapped = sorted(h for h in hosts_seen if h not in CORP_HOST_TICKER and h not in CORP_HOST_BLOCKED)
    report["corp_hosts_total"] = len(hosts_seen)
    report["corp_hosts_mapped"] = len([h for h in hosts_seen if h in CORP_HOST_TICKER])
    report["corp_hosts_blocked"] = len([h for h in hosts_seen if h in CORP_HOST_BLOCKED])
    report["corp_hosts_out_of_universe"] = len(unmapped)
    return rows


def probe_cdp(prov, aliases, report):
    """Fetch the CDP score embeds and measure whether they carry any tonnage. They do not."""
    alias_names = aliases["name_to_ticker"]
    for vis_id, label in CDP_EMBEDS.items():
        body = fetch(
            f"https://public.flourish.studio/visualisation/{vis_id}/embed",
            RAW_CDP / f"flourish_{vis_id}.html",
            prov,
            CDP_LICENCE,
            CDP_REDIST,
            "vendor",
        )
        text = body.decode("utf-8", errors="replace")
        m = re.search(r"_Flourish_data\s*=\s*", text)
        cols_m = re.search(r"_Flourish_data_column_names\s*=\s*", text)
        if not m:
            print(f"  cdp {vis_id} ({label}): no _Flourish_data in the embed")
            continue
        data = json.JSONDecoder().raw_decode(text, m.end())[0]
        colnames = json.JSONDecoder().raw_decode(text, cols_m.end())[0] if cols_m else {}
        rows = [r["columns"] for r in data.get("rows", [])]
        names = colnames.get("rows", {}).get("columns", [])
        # Anything that could be a tonnage: a cell outside the name and country columns that parses
        # as a number, or a column whose header mentions emissions.
        numeric_cells = 0
        for r in rows:
            for c in r[2:]:
                s = str(c).replace(",", "").strip()
                try:
                    float(s)
                except ValueError:
                    continue
                numeric_cells += 1
        emissions_headers = [n for n in names if re.search(r"emiss|scope|tco2|tonne", str(n), re.I)]
        matched = sum(1 for r in rows if normalise_name(r[0]) in alias_names)
        graded = 0
        for r in rows:
            if normalise_name(r[0]) in alias_names and str(r[2]).startswith("http"):
                graded += 1
        print(
            f"  cdp {vis_id} ({label}): {len(rows)} rows, columns {names}, "
            f"numeric cells outside name/country {numeric_cells}, emissions-named columns "
            f"{len(emissions_headers)}, S&P 500 names matched by exact normalised name {matched} (unaudited), of those carrying a letter grade {graded}"
        )
        report[f"cdp_{vis_id}_rows"] = len(rows)
        report[f"cdp_{vis_id}_numeric_cells"] = numeric_cells
        report[f"cdp_{vis_id}_sp500_matched"] = matched
        report[f"cdp_{vis_id}_sp500_graded"] = graded
        report[f"cdp_{vis_id}_emission_columns"] = len(emissions_headers)


def probe_kaggle_reports(path, aliases, report):
    """Does the S&P 500 report-text dataset carry any tonnage? Measured: not one digit."""
    alias = aliases["aliases"]
    csv.field_size_limit(sys.maxsize)
    scope_pat = re.compile(r"scope\s*(?:1|2|3|one|two|three)\D{0,40}?(\d[\d ]{2,})")
    n = 0
    with_digit = 0
    with_scope_word = 0
    with_scope_number = 0
    tickers = set()
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames
        for rec in reader:
            n += 1
            t = rec.get("preprocessed_content") or ""
            if re.search(r"\d", t):
                with_digit += 1
            if "scope" in t:
                with_scope_word += 1
            if scope_pat.search(t):
                with_scope_number += 1
            tk = str(rec.get("ticker") or "").upper().replace("-", ".")
            if tk in alias:
                tickers.add(alias[tk])
    print(
        f"  kaggle esg reports: {n} reports, columns {cols}, {len(tickers)} S&P 500 tickers, "
        f"{with_scope_word} texts contain the word 'scope', {with_digit} contain any digit, "
        f"{with_scope_number} yield a scope-and-number match"
    )
    report["kaggle_reports_rows"] = n
    report["kaggle_reports_sp500_tickers"] = len(tickers)
    report["kaggle_reports_texts_with_any_digit"] = with_digit
    report["kaggle_reports_tonnage_rows"] = with_scope_number


def probe_kaggle_global(path, report):
    """Header only. The values are an unlicensed vendor extract and must not enter any table."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        header = fh.readline()
    cols = [c.strip() for c in header.rstrip("\n").split(";")]
    nearby = [c for c in cols if re.search(r"emiss|carbon|decarbon", c, re.I)]
    # A tonnage column would have to name a scope, a unit or the gas. None of these do: the seven
    # near misses are decarbonisation-target and controversy-count fields.
    tonnage = [c for c in cols if re.search(r"\b(scope\s*[123]|tco2|co2e?|ghg|tonnes?|metric tons?)\b", c, re.I)]
    print(
        f"  kaggle global esg: {len(cols)} columns, {len(tonnage)} tonnage columns, "
        f"{len(nearby)} that merely mention emissions or decarbonisation: {nearby}"
    )
    report["kaggle_global_columns"] = len(cols)
    report["kaggle_global_tonnage_columns"] = len(tonnage)
    report["kaggle_global_emissions_word_columns"] = len(nearby)


def build_scope2_factor_rows(universe, report):
    """One row per listing per eGRID year with the grid factor for its HQ region. No tonnage."""
    sub = pd.read_parquet(INTERIM / "egrid_subregion.parquet")
    plant = pd.read_parquet(INTERIM / "egrid_plant.parquet")
    years = sorted(sub["year"].unique())
    latest = max(years)

    # State to subregion, by where the state's generation physically sits. The assignment uses the
    # newest eGRID year so it reflects today's grid, and is held fixed across years so that a
    # company's factor series moves only because the grid decarbonised.
    gen = plant[(plant["year"] == latest) & plant["net_generation_mwh"].notna()]
    gen = gen[gen["net_generation_mwh"] > 0]
    by_state = gen.groupby(["state", "subregion_code"])["net_generation_mwh"].sum().reset_index()
    state_total = by_state.groupby("state")["net_generation_mwh"].sum()
    by_state["share"] = by_state["net_generation_mwh"] / by_state["state"].map(state_total)
    dominant = by_state.sort_values("share", ascending=False).groupby("state").first()
    state_subregion = dominant["subregion_code"].to_dict()
    state_share = dominant["share"].to_dict()

    # The state's own generation-weighted rate, kept beside the subregion rate so a later estimate
    # can see how much the choice of basis matters. tonnes -> g is 1e6, MWh -> kWh is 1e3.
    st = gen.groupby("state")[["co2e_tons", "net_generation_mwh"]].sum()
    st = st[st["net_generation_mwh"] > 0]
    state_factor = {
        s: float(r["co2e_tons"] * 0.90718474 * 1000.0 / r["net_generation_mwh"])
        for s, r in st.iterrows()
    }

    sub_factor = {
        (r["subregion_code"], int(r["year"])): (
            float(r["co2e_rate_g_per_kwh"]) if pd.notna(r["co2e_rate_g_per_kwh"]) else None
        )
        for _, r in sub.iterrows()
    }
    national = {}
    for y, g in sub.groupby("year"):
        mwh = g["net_generation_mwh"].sum()
        national[int(y)] = float(g["co2e_tonnes"].sum() * 1000.0 / mwh) if mwh else None

    rows = []
    counts = {"us_state": 0, "foreign_hq": 0, "unknown_hq": 0}
    for rec in universe.to_dict("records"):
        hq = str(rec.get("hq_location") or "").strip()
        hq = re.sub(r"\[\d+\]", "", hq).strip()  # Wikipedia footnote markers leak into two rows
        city, _, region = hq.rpartition(",")
        region = region.strip()
        city = city.strip().upper()
        usps = STATE_TO_USPS.get(region)
        if usps is not None:
            subregion = CITY_SUBREGION.get((usps, city), state_subregion.get(usps))
            # null, not 1.0: the city override is an assignment, not a measured concentration
            share = None if (usps, city) in CITY_SUBREGION else state_share.get(usps)
            basis = "egrid_subregion_of_hq_city" if (usps, city) in CITY_SUBREGION else "egrid_subregion_dominant_in_hq_state"
            country = "US"
            counts["us_state"] += 1
        elif hq and hq.lower() != "none":
            subregion, share, basis, country = None, None, "us_national_average_foreign_hq", region
            counts["foreign_hq"] += 1
        else:
            subregion, share, basis, country = None, None, "hq_unknown", None
            counts["unknown_hq"] += 1
        for y in years:
            if subregion is not None:
                factor = sub_factor.get((subregion, y))
            elif basis == "us_national_average_foreign_hq":
                factor = national.get(y)
            else:
                factor = None
            rows.append(
                row(
                    ticker=rec["ticker"],
                    fy=int(y),
                    scope="2_location_factor_input",
                    tonnes_co2e=None,
                    source="epa_egrid_subregion_via_hq_location",
                    provenance_class="modelled",
                    dq=5,
                    reported_or_estimated="factor_input",
                    scope2_factor_g_per_kwh_hq_region=factor,
                    scope2_factor_g_per_kwh_hq_state=state_factor.get(usps) if usps else None,
                    scope2_factor_basis=basis,
                    hq_state=usps,
                    hq_country=country,
                    hq_subregion_code=subregion,
                    hq_subregion_gen_share=share,
                    match_method="hq_location_to_state",
                    note="multiply by purchased kWh for location-based Scope 2; no free per-company kWh exists, so no tonnage is written here",
                )
            )
    report["scope2_factor_hq_us"] = counts["us_state"]
    report["scope2_factor_hq_foreign"] = counts["foreign_hq"]
    report["scope2_factor_hq_unknown"] = counts["unknown_hq"]
    report["egrid_years"] = [int(y) for y in years]
    report["us_national_factor_g_per_kwh"] = {int(k): (round(v, 1) if v else None) for k, v in national.items()}
    return rows


# A global Scope 1 figure cannot be smaller than the company's US-only GHGRP total, so a ratio far
# below 1 is an extraction error rather than a disclosure difference. A tenth is the line: above it
# a gap can be explained by an unconsolidated joint venture, below it the only explanation is a
# misread magnitude, which is what a kiloton-versus-tonne confusion looks like.
MAGNITUDE_SUSPECT_RATIO = 0.1


def flag_magnitude_errors(df, report):
    """Cross-check reported Scope 1 against the mandatory spine and flag impossible rows.

    The flag is set on every row extracted from the same report PDF, not just the Scope 1 row,
    because a misread magnitude is a property of that extraction and the Scope 2 and 3 figures on
    the same page are no more trustworthy for it.
    """
    em = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    ghgrp = em[["ticker", "year", "scope1_ghgrp_tonnes"]].rename(columns={"year": "fy"})
    ghgrp = ghgrp[ghgrp["scope1_ghgrp_tonnes"].notna() & (ghgrp["scope1_ghgrp_tonnes"] > 0)]
    s1 = df[(df["scope"] == "1") & df["tonnes_co2e"].notna()].copy()
    chk = s1.merge(ghgrp, on=["ticker", "fy"], how="inner")
    if not len(chk):
        return df
    chk["ratio"] = chk["tonnes_co2e"] / chk["scope1_ghgrp_tonnes"]
    ratio_by_url = dict(zip(chk["source_url"], chk["ratio"]))
    bad_urls = set(chk.loc[chk["ratio"] < MAGNITUDE_SUSPECT_RATIO, "source_url"])
    df["ghgrp_crosscheck_ratio"] = df["source_url"].map(ratio_by_url)
    df["magnitude_suspect"] = df["source_url"].isin(bad_urls)

    print(
        f"\nscope 1 cross-check against GHGRP on {len(chk)} ticker-years, "
        f"{chk['ticker'].nunique()} tickers: reported / GHGRP median {chk['ratio'].median():.2f}, "
        f"below 1.0 on {(chk['ratio'] < 1).sum()}, below {MAGNITUDE_SUSPECT_RATIO} on "
        f"{(chk['ratio'] < MAGNITUDE_SUSPECT_RATIO).sum()}"
    )
    for _, r in chk.sort_values("ratio").head(7).iterrows():
        print(
            f"  {r['ticker']} {int(r['fy'])}: reported {r['tonnes_co2e']:,.0f} vs GHGRP "
            f"{r['scope1_ghgrp_tonnes']:,.0f}, ratio {r['ratio']:.4f}"
        )
    # A company with any operations burns something, so a literal zero Scope 1 is an extraction
    # failure, not a disclosure. A zero market-based Scope 2 is the opposite: it is what a 100%
    # renewable power purchase agreement is supposed to produce, so those are left alone.
    zero_s1 = (df["scope"] == "1") & df["tonnes_co2e"].eq(0)
    df.loc[zero_s1, "magnitude_suspect"] = True
    report["zero_scope1_rows_flagged"] = int(zero_s1.sum())
    zeros = df[df["tonnes_co2e"].eq(0)].groupby("scope").size().to_dict()
    print(f"  zero tonnages by scope: {zeros}; the {int(zero_s1.sum())} zero Scope 1 rows are flagged too")

    reported_s1_tickers = s1["ticker"].nunique()
    print(
        f"  magnitude_suspect set on {int(df['magnitude_suspect'].sum())} rows in total: everything "
        f"extracted from the {len(bad_urls)} report PDFs above, plus the zero Scope 1 rows. "
        "Filter them out before using any voluntary tonnage."
    )
    print(
        f"  the cross-check reaches {chk['ticker'].nunique()} of the {reported_s1_tickers} tickers "
        f"with a reported Scope 1; the rest run no GHGRP facility, so their extraction is unverified"
    )
    report["scope1_crosscheck_tickers_unverified"] = int(reported_s1_tickers - chk["ticker"].nunique())
    report["scope1_crosscheck_ticker_years"] = int(len(chk))
    report["scope1_crosscheck_tickers"] = int(chk["ticker"].nunique())
    report["scope1_crosscheck_median_ratio"] = round(float(chk["ratio"].median()), 3)
    report["scope1_crosscheck_below_1"] = int((chk["ratio"] < 1).sum())
    report["magnitude_suspect_rows"] = int(df["magnitude_suspect"].sum())
    report["magnitude_suspect_reports"] = len(bad_urls)
    return df


def main():
    INTERIM.mkdir(parents=True, exist_ok=True)
    PROV.mkdir(parents=True, exist_ok=True)
    universe, aliases = load_universe()
    report = {}
    print(f"universe: {len(universe)} listings, {int(universe['is_primary_listing'].sum())} primary")

    print("\nhugging face, nopperl")
    hf_prov = []
    blobs = {}
    for spec in HF_FILES:
        body = fetch(spec["url"], RAW_HF / spec["cache"], hf_prov, HF_LICENCE, HF_REDIST, "voluntary")
        blobs[spec["key"]] = RAW_HF / spec["cache"]
        print(f"  {spec['dataset']}: {len(body)} bytes")
    for ds in HF_SIBLINGS:
        info_path = RAW_HF / f"info_{ds.split('/')[-1]}.json"
        body = fetch(
            f"https://datasets-server.huggingface.co/info?dataset={ds}",
            info_path,
            hf_prov,
            HF_LICENCE,
            HF_REDIST,
            "voluntary",
        )
        info = json.loads(body)["dataset_info"]["default"]
        print(
            f"  {ds}: {info['splits']['train']['num_examples']} rows, features "
            f"{sorted(info['features'])}, carries no company identifier, adds no coverage"
        )

    corp = pd.read_parquet(blobs["corp"])
    train = pd.read_parquet(blobs["train"])
    print(f"  corp_emissions {corp.shape}, emissions_train {train.shape}")
    corp_rows = build_corp_rows(corp, aliases, report)
    train_rows = build_train_rows(train, aliases, report)
    print(
        f"  corp: {len(corp_rows)} rows from {report['corp_hosts_mapped']} of "
        f"{report['corp_hosts_total']} report hosts "
        f"({report['corp_hosts_blocked']} blocked as subsidiary reports, "
        f"{report['corp_hosts_out_of_universe']} not in the S&P 500)"
    )
    print(
        f"  train: {report['nopperl_train_ids_parsed']} ids parsed, "
        f"{report['nopperl_train_us_rows']} on US exchanges, {len(train_rows)} rows kept, "
        f"{report['nopperl_train_foreign_ticker_collisions_avoided']} foreign-exchange rows "
        f"rejected that would have collided with an S&P 500 ticker"
    )

    print("\ncdp corporate scores, public flourish embeds")
    cdp_prov = []
    probe_cdp(cdp_prov, aliases, report)

    print("\nkaggle")
    kg_prov = []
    for spec in KAGGLE_DATASETS:
        path = kaggle_download(
            spec["slug"], spec["file"], kg_prov, spec["licence"], spec["redistribution"], "vendor"
        )
        if path is None:
            report[f"kaggle_{spec['key']}_available"] = False
            continue
        report[f"kaggle_{spec['key']}_available"] = True
        if spec["key"] == "reports":
            probe_kaggle_reports(path, aliases, report)
        else:
            probe_kaggle_global(path, report)

    print("\negrid scope 2 factors by hq region")
    factor_rows = build_scope2_factor_rows(universe, report)
    print(
        f"  {len(factor_rows)} factor rows over {report['egrid_years']}: "
        f"{report['scope2_factor_hq_us']} US HQ, {report['scope2_factor_hq_foreign']} foreign HQ "
        f"on the US national average, {report['scope2_factor_hq_unknown']} with no usable HQ"
    )
    print(f"  US national average gCO2e/kWh by year: {report['us_national_factor_g_per_kwh']}")

    df = pd.DataFrame(corp_rows + train_rows + factor_rows)
    meta = universe[["ticker", "company_name", "gics_sector", "is_primary_listing"]]
    df = df.merge(meta, on="ticker", how="left")
    df["fy"] = df["fy"].astype("Int64")
    df["dq"] = df["dq"].astype("Int8")
    df = df.sort_values(["ticker", "fy", "scope", "source"]).reset_index(drop=True)
    df = flag_magnitude_errors(df, report)

    assert df["ticker"].isin(set(universe["ticker"])).all(), "a row escaped the universe"
    assert not df["scope"].isna().any()
    tonnage = df[df["tonnes_co2e"].notna()]
    assert (tonnage["tonnes_co2e"] >= 0).all(), "negative tonnage"
    assert df.loc[df["scope"] == "2_location_factor_input", "tonnes_co2e"].isna().all()
    assert df.loc[df["provenance_class"] == "mandatory"].empty, "nothing here is mandatory"

    df.to_parquet(OUT, index=False)

    print(f"\nwrote {OUT.relative_to(ROOT)}: {len(df)} rows, {df['ticker'].nunique()} tickers")
    print("\nrows by source and provenance class")
    print(df.groupby(["source", "provenance_class"]).size().to_string())
    print("\nrows by scope")
    print(df.groupby("scope").agg(rows=("scope", "size"), tickers=("ticker", "nunique")).to_string())

    primary = set(universe.loc[universe["is_primary_listing"], "ticker"])
    print("\ncoverage of the 503 listings, and of the 500 primary listings")
    for label, mask in [
        ("any reported tonnage", df["tonnes_co2e"].notna()),
        ("the same, suspect dropped", df["tonnes_co2e"].notna() & ~df["magnitude_suspect"]),
        ("scope 1 reported", df["scope"].eq("1") & df["tonnes_co2e"].notna()),
        ("scope 2 either basis", df["scope"].isin(["2_market", "2_location"]) & df["tonnes_co2e"].notna()),
        ("scope 2 location basis", df["scope"].eq("2_location") & df["tonnes_co2e"].notna()),
        ("scope 3 total", df["scope"].eq("3_total") & df["tonnes_co2e"].notna()),
        ("scope 3 by category", df["scope"].str.startswith("3_cat") & df["tonnes_co2e"].notna()),
        ("scope 2 factor input", df["scope2_factor_g_per_kwh_hq_region"].notna()),
    ]:
        tk = set(df.loc[mask, "ticker"])
        print(f"  {label:24s} {len(tk):3d} / 503 listings   {len(tk & primary):3d} / 500 primary")

    fy_have = df[df["tonnes_co2e"].notna()].groupby("ticker")["fy"].max()
    counts = {int(k): int(v) for k, v in fy_have.value_counts().sort_index().items()}
    print(f"\nmost recent fiscal year with a reported tonnage, by ticker count: {counts}")
    print(
        f"  the newest voluntary figure in the whole table is FY{int(fy_have.max())}. The upstream "
        "dataset was built in 2024 and stops there, so this benchmarks 2020-2022, not today."
    )
    report["latest_fy_with_tonnage"] = int(fy_have.max())
    report["tickers_by_latest_fy"] = counts

    for name, entries, class_ in [
        ("hf_nopperl", hf_prov, "voluntary"),
        ("cdp_flourish_scores", cdp_prov, "vendor"),
        ("kaggle_esg_datasets", kg_prov, "vendor"),
    ]:
        (PROV / f"{name}.json").write_text(json.dumps(entries, indent=1))
    (PROV / "scope23_findings.json").write_text(json.dumps(report, indent=1, default=str))
    print(f"\nprovenance written for {len(hf_prov)} hf, {len(cdp_prov)} cdp, {len(kg_prov)} kaggle URLs")
    print("REMINDER: tonnes_co2e must not be summed across companies. See the module docstring.")


if __name__ == "__main__":
    main()
