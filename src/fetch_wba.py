"""World Benchmarking Alliance Climate and Energy Benchmark, joined to the S&P 500.

WBA assesses the 2,000 most influential companies (the SDG2000) on their low-carbon transition using
the ACT framework. Everything here is company-disclosed and third-party assessed, so it is
provenance_class 'voluntary' and must never be merged into a mandatory column. The EPA spine is what
a company is legally compelled to file; this is what it chose to say.

Input is an Airtable export of six CSVs under data/raw/wba/WBA Data/. Airtable writes multi-value
cells as brace-wrapped lists, "{277717}" or "{S2.MB,S2.LB,S1+2}", so every cell is parsed as a list
and a column that is meant to hold one value is nulled and counted when it holds more.

Outputs, all keyed on the project's canonical ticker:
  data/interim/wba_company.parquet     one row per matched ticker
  data/interim/wba_emissions.parquet   ticker, fy, scope, tonnes_co2e, unit, estimated_flag, dq
  data/interim/wba_targets.parquet     one row per WBA target slot
  data/interim/wba_pathway.parquet     ticker, year, series, value for the modelled pathways
  data/interim/wba_sources.parquet     the documents WBA read, per company
  data/interim/provenance/wba.json

The join runs best key first and records which tier matched each company: ISIN through OpenFIGI, LEI
through GLEIF to an ISIN and then OpenFIGI, then an exact match on normalised names against the
universe lane's alias map. Name matching alone is dangerous here: WBA holds Toronto-Dominion as "TD"
and Merck KGaA as "Merck", which normalise onto TransDigm and Merck & Co. The ISIN veto below is what
stops that.
"""

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
WBA_DIR = RAW / "wba" / "WBA Data"
CACHE_DIR = RAW / "wba"

sys.path.insert(0, str(ROOT / "src"))
from fetch_universe import canonical_ticker, normalise_name  # noqa: E402

OPENFIGI = "https://api.openfigi.com/v3/mapping"
GLEIF_ISINS = "https://api.gleif.org/api/v1/lei-records/{lei}/isins"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "ETHack2026 research artemiy.v.burov@gmail.com"

# Countries that actually host an S&P 500 domicile. The LEI tier costs one GLEIF request per company
# and there is no point spending it on a company that cannot be in the index.
SP500_DOMICILES = {
    "USA", "IRL", "CHE", "GBR", "BMU", "NLD", "PAN", "LBR", "JEY", "CAN", "ISR", "SGP", "LUX",
}

# Verified false positives from the name tier that the ISIN veto does not already catch. It is
# still empty: reading every name hit by hand found four false positives, Toronto-Dominion onto
# TransDigm, T&D Holdings onto TransDigm, EQT AB onto EQT Corp and Merck KGaA onto Merck & Co, and
# the ISIN veto rejects all four because each resolves to a real US listing outside the index.
NAME_BLOCKLIST = set()

# Legal-form phrases WBA spells out in company_full_name. normalise_name strips the abbreviations
# but not the long forms, so "Seagate Technology Public Limited Company" normalises to
# SEAGATETECHNOLOGYPUBLIC and misses SEAGATETECHNOLOGY.
LEGAL_FORMS = [
    ("public limited company", "plc"),
    ("public company limited", "plc"),
    ("company limited", "ltd"),
    ("corporation limited", "ltd"),
]


def clean_legal_form(raw):
    if raw is None or raw != raw:
        return raw
    s = str(raw)
    for long, short in LEGAL_FORMS:
        s = re.sub(long, short, s, flags=re.IGNORECASE)
    return s


# ------------------------------------------------------------------ Airtable cell parsing

_SPLIT = re.compile(r',(?=(?:[^"]*"[^"]*")*[^"]*$)')


def cell(raw):
    """Airtable cell to a list of strings. "{a,b}" -> [a, b]; "" and "{NULL}" -> []."""
    if raw is None or raw != raw:
        return []
    s = str(raw).strip()
    if not s:
        return []
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1]
        parts = [p.strip().strip('"').strip() for p in _SPLIT.split(inner)] if inner else []
    else:
        parts = [s]
    return [p for p in parts if p and p != "NULL"]


MULTI = {"count": 0, "columns": {}}


def scalar(raw, column=""):
    """The single value in a cell. A cell holding several values is nulled and counted, never
    silently truncated to its first element."""
    vals = cell(raw)
    if not vals:
        return None
    if len(vals) > 1:
        MULTI["count"] += 1
        MULTI["columns"][column] = MULTI["columns"].get(column, 0) + 1
        return None
    return vals[0]


def scalar_num(raw, column=""):
    v = scalar(raw, column)
    if v is None:
        return None
    v = v.replace("%", "").replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def scalar_bool(raw, column=""):
    """WBA writes true as 't' or 'Yes' and false as an absent value or 'No'."""
    v = scalar(raw, column)
    if v is None:
        return None
    return v.lower() in ("t", "true", "yes", "1")


def joined(raw):
    vals = cell(raw)
    return ",".join(vals) if vals else None


# ------------------------------------------------------------------ provenance

PROV_FILES = []


def record_file(path, note):
    b = path.read_bytes()
    PROV_FILES.append(
        {
            "file": str(path.relative_to(ROOT)),
            "bytes": len(b),
            "sha256": hashlib.sha256(b).hexdigest(),
            "note": note,
        }
    )


# ------------------------------------------------------------------ identifier resolution


def load_figi_cache():
    """The targets lane's ISIN cache is read-only here. New lookups go to this lane's own file so
    two scripts running at once cannot clobber each other; the format is identical and the two can
    be merged."""
    shared = RAW / "openfigi" / "isin_ticker.json"
    mine = CACHE_DIR / "isin_ticker_wba.json"
    cache = {}
    if shared.exists():
        cache.update(json.loads(shared.read_text()))
    print(f"openfigi: {len(cache)} ISINs from the shared targets-lane cache")
    own = json.loads(mine.read_text()) if mine.exists() else {}
    cache.update(own)
    print(f"openfigi: {len(own)} ISINs from this lane's cache, {len(cache)} total")
    return cache, own, mine


def figi_lookup(isins, cache, own, mine):
    """Resolve ISINs to a US-listed ticker. Cached, so a second run makes no request."""
    todo = sorted({i for i in isins if i and i not in cache})
    print(f"openfigi: {len(todo)} ISINs not yet cached")
    for k in range(0, len(todo), 10):
        batch = todo[k : k + 10]
        body = json.dumps([{"idType": "ID_ISIN", "idValue": i, "exchCode": "US"} for i in batch])
        r = SESSION.post(OPENFIGI, data=body, headers={"Content-Type": "application/json"}, timeout=60)
        if r.status_code == 429:
            time.sleep(30)
            r = SESSION.post(
                OPENFIGI, data=body, headers={"Content-Type": "application/json"}, timeout=60
            )
        r.raise_for_status()
        for isin, res in zip(batch, r.json()):
            hit = (res.get("data") or [None])[0]
            val = {"ticker": hit["ticker"], "name": hit.get("name")} if hit else None
            cache[isin] = val
            own[isin] = val
        if (k // 10) % 20 == 0:
            print(f"openfigi: {min(k + 10, len(todo))}/{len(todo)} resolved")
        time.sleep(2.6)
    if todo:
        mine.parent.mkdir(parents=True, exist_ok=True)
        mine.write_text(json.dumps(own, indent=1, sort_keys=True))
    hits = sum(1 for i in isins if cache.get(i))
    print(f"openfigi: {hits}/{len(set(isins))} distinct ISINs resolved to a US ticker")
    return cache


def gleif_isins(leis):
    """LEI to the ISINs issued under it. One request per LEI, cached."""
    path = CACHE_DIR / "lei_isin.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    todo = sorted(l for l in leis if l and l not in cache)
    print(f"gleif: {len(todo)} LEIs not yet cached")
    for n, lei in enumerate(todo, 1):
        try:
            r = SESSION.get(GLEIF_ISINS.format(lei=lei), timeout=30)
            if r.status_code == 429:
                time.sleep(20)
                r = SESSION.get(GLEIF_ISINS.format(lei=lei), timeout=30)
            cache[lei] = (
                [d["attributes"]["isin"] for d in r.json().get("data", [])]
                if r.status_code == 200
                else []
            )
        except requests.RequestException as exc:
            print(f"gleif: {lei} failed, {exc}")
            cache[lei] = []
        if n % 25 == 0:
            print(f"gleif: {n}/{len(todo)}")
        time.sleep(0.25)
    if todo:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    print(f"gleif: {sum(1 for v in cache.values() if v)}/{len(cache)} LEIs carry at least one ISIN")
    return cache


# ------------------------------------------------------------------ the join


def build_ticker_map(co, alias, name_to_ticker, primary_by_cik, ticker_to_cik):
    """WBA company_id to S&P 500 ticker, best key first. Returns a frame with the tier that won."""

    # Base ticker to the CIKs behind it, for the index's own share classes (BRK.B, BF.B).
    class_base = {}
    for t, cik in ticker_to_cik.items():
        if "." in t:
            class_base.setdefault(t.split(".")[0], set()).add(cik)

    def to_sp500(raw_ticker):
        """A raw exchange ticker to the project's canonical primary-listing ticker, or None."""
        if not raw_ticker:
            return None
        canon = canonical_ticker(raw_ticker)
        t = alias.get(canon)
        if t is None and "." in canon:
            # A share class the index does not list. WBA carries Berkshire under its class A ISIN,
            # which OpenFIGI returns as BRK/A while the index holds only BRK.B. Accept it only when
            # the index itself lists a class under that base and exactly one company owns it.
            ciks = class_base.get(canon.split(".")[0], set())
            if len(ciks) == 1:
                t = primary_by_cik.get(next(iter(ciks)))
        if t is None:
            return None
        cik = ticker_to_cik.get(t)
        return primary_by_cik.get(cik, t) if cik else t

    co = co.copy()
    co["isin"] = co["company_isin"].map(lambda s: s.strip() if isinstance(s, str) else None)
    co["lei"] = co["company_lei"].map(lambda s: s.strip() if isinstance(s, str) else None)

    figi, own, mine = load_figi_cache()
    figi = figi_lookup(co["isin"].dropna().tolist(), figi, own, mine)

    def figi_ticker(isin):
        hit = figi.get(isin)
        return hit["ticker"] if hit else None

    co["isin_us_ticker"] = co["isin"].map(lambda i: figi_ticker(i) if i else None)
    co["t_isin"] = co["isin_us_ticker"].map(to_sp500)
    print(f"tier 1 ISIN: {co['t_isin'].notna().sum()} companies matched")

    # Tier 2. Only worth a request where tier 1 could not run and the domicile is one the index
    # actually uses.
    need_lei = co[
        co["t_isin"].isna()
        & co["lei"].notna()
        & co["company_location_hq_country_iso"].isin(SP500_DOMICILES)
    ]
    print(f"tier 2 LEI: {len(need_lei)} candidates in S&P 500 domiciles")
    lei_map = gleif_isins(need_lei["lei"].tolist())
    extra = sorted({i for v in lei_map.values() for i in v[:15]})
    figi = figi_lookup(extra, figi, own, mine)
    lei_ticker = {}
    for _, row in need_lei.iterrows():
        hits = {to_sp500(figi_ticker(i)) for i in lei_map.get(row["lei"], [])[:15]}
        hits.discard(None)
        if len(hits) == 1:
            lei_ticker[row["company_id"]] = hits.pop()
    co["t_lei"] = co["company_id"].map(lei_ticker)
    print(f"tier 2 LEI: {co['t_lei'].notna().sum()} companies matched")

    # Tier 3. An exact match on normalised names, with two vetoes.
    co["n_short"] = co["company_name"].map(lambda s: normalise_name(clean_legal_form(s)))
    co["n_full"] = co["company_full_name"].map(lambda s: normalise_name(clean_legal_form(s)))
    t_name = co["n_short"].map(name_to_ticker.get)
    t_name = t_name.fillna(co["n_full"].map(name_to_ticker.get))
    # Veto one: the ISIN resolved to a real US listing that is not in the index, so this is a
    # different company that happens to share a normalised name.
    vetoed_isin = co["isin_us_ticker"].notna() & co["t_isin"].isna()
    # Veto two: a hand-verified blocklist.
    vetoed_list = co["company_id"].isin(NAME_BLOCKLIST)
    co["t_name_raw"] = t_name
    co["t_name"] = t_name.where(~(vetoed_isin | vetoed_list))
    print(
        f"tier 3 name: {t_name.notna().sum()} raw hits, "
        f"{(t_name.notna() & vetoed_isin).sum()} vetoed by a US listing outside the index, "
        f"{(t_name.notna() & vetoed_list).sum()} vetoed by the blocklist, "
        f"{co['t_name'].notna().sum()} kept"
    )

    co["ticker"] = co["t_isin"].fillna(co["t_lei"]).fillna(co["t_name"])
    co["match_method"] = None
    co.loc[co["t_name"].notna(), "match_method"] = "name"
    co.loc[co["t_lei"].notna(), "match_method"] = "lei"
    co.loc[co["t_isin"].notna(), "match_method"] = "isin"

    disagree = co[
        co["t_isin"].notna() & co["t_name"].notna() & (co["t_isin"] != co["t_name"])
    ]
    print(f"join: {len(disagree)} companies where the ISIN and the name tiers disagree")
    for _, r in disagree.iterrows():
        print(f"  {r['company_name']}: isin->{r['t_isin']} name->{r['t_name']}, ISIN wins")

    matched = co[co["ticker"].notna()]
    dupes = matched[matched.duplicated("ticker", keep=False)].sort_values("ticker")
    print(f"join: {len(dupes)} rows share a ticker with another WBA company")
    for _, r in dupes.iterrows():
        print(f"  {r['ticker']}: {r['company_name']} ({r['company_id']}, {r['match_method']})")
    return co


# ------------------------------------------------------------------ main


def main():
    INTERIM.mkdir(parents=True, exist_ok=True)
    (INTERIM / "provenance").mkdir(parents=True, exist_ok=True)

    co = pd.read_csv(WBA_DIR / "companies.csv", dtype=str)
    cp = pd.read_csv(WBA_DIR / "climateprofiles.csv", dtype=str)
    em = pd.read_csv(WBA_DIR / "emissions.csv", dtype=str)
    tg = pd.read_csv(WBA_DIR / "targets.csv", dtype=str)
    sr = pd.read_csv(WBA_DIR / "sources.csv", dtype=str)
    for name, df in [
        ("companies", co), ("climateprofiles", cp), ("emissions", em),
        ("targets", tg), ("sources", sr),
    ]:
        print(f"read {name}.csv: {len(df)} rows, {df['company_id'].nunique()} companies")
        record_file(WBA_DIR / f"{name}.csv", f"{len(df)} rows as parsed")

    alias_blob = json.loads((INTERIM / "ticker_aliases.json").read_text())
    alias = alias_blob["aliases"]
    name_to_ticker = alias_blob["name_to_ticker"]
    ticker_to_cik = alias_blob["ticker_to_cik"]
    primary_by_cik = alias_blob["primary_ticker_by_cik"]
    universe = pd.read_parquet(INTERIM / "universe.parquet")
    n_companies = int(universe["is_primary_listing"].sum())
    print(f"universe: {len(universe)} listings, {n_companies} companies")

    co = build_ticker_map(co, alias, name_to_ticker, primary_by_cik, ticker_to_cik)
    # Two WBA companies can land on one ticker, usually a parent and a subsidiary. Keep the one
    # matched on the stronger key, and among equals the one that actually carries emissions.
    tier = {"isin": 0, "lei": 1, "name": 2}
    has_data = set(em.dropna(subset=["emissions_s1x2"])["company_id"]) | set(
        em.dropna(subset=["emissions_s3"])["company_id"]
    )
    co["_tier"] = co["match_method"].map(tier)
    co["_data"] = (~co["company_id"].isin(has_data)).astype(int)
    keep = (
        co[co["ticker"].notna()]
        .sort_values(["ticker", "_tier", "_data", "company_id"])
        .drop_duplicates("ticker", keep="first")
        .drop(columns=["_tier", "_data"])
    )
    print(f"join: {len(keep)} tickers matched of {n_companies} S&P 500 companies")
    print("join: by tier " + str(dict(keep["match_method"].value_counts())))
    id_to_ticker = dict(zip(keep["company_id"], keep["ticker"]))

    # -------------------------------------------------------------- wba_company
    prof = cp.set_index("company_id")
    rows = []
    for _, c in keep.iterrows():
        p = prof.loc[c["company_id"]] if c["company_id"] in prof.index else None
        tags = cell(p["climate_profile_tags"]) if p is not None else []
        rows.append(
            {
                "ticker": c["ticker"],
                "wba_company_id": c["company_id"],
                "wba_company_name": c["company_name"],
                "wba_company_full_name": c["company_full_name"],
                "wba_industry": c["company_wba_industry"],
                "isic": c["company_industry_isic"],
                "hq_country_iso": c["company_location_hq_country_iso"],
                "isin": c["isin"],
                "lei": c["lei"],
                "wikidata_qid": c["company_wikidata_qid"],
                "assessment_years": c["company_assessment_years"],
                "match_method": c["match_method"],
                "climate_profile_year": None if p is None else scalar_num(p["climate_profile_year"]),
                "disclosure_level": None if p is None else scalar(p["climate_profile_disclosure_level"]),
                "valid_accounting": None if p is None else scalar_bool(p["climate_profile_valid_accounting"]),
                "valid_methodology": None if p is None else scalar_bool(p["climate_profile_valid_methodology"]),
                "significant_s3": None if p is None else scalar_bool(p["climate_profile_significant_s3_emissions"]),
                "consistent_s1x2_data": None if p is None else scalar_bool(p["climate_profile_consistent_s1x2_data"]),
                "consistent_s3_data": None if p is None else scalar_bool(p["climate_profile_consistent_s3_data"]),
                "independently_verified": None if p is None else ("Independently verified" in tags),
                "profile_tags": None if p is None else joined(p["climate_profile_tags"]),
                "assumed_annual_growth_pct": None if p is None else scalar_num(p["climate_profile_assumed_annual_growth"]),
                "s1x2_pathway": None if p is None else scalar(p["climate_profile_s1x2_pathway"]),
                "s3_pathway": None if p is None else scalar(p["climate_profile_s3_pathway"]),
                "lci_group": None if p is None else scalar(p["climate_profile_lci_group"]),
                "required_emissions": None if p is None else joined(p["climate_profile_required_emissions"]),
                "available_emissions": None if p is None else joined(p["climate_profile_available_emissions"]),
                "profile_scope_1": None if p is None else scalar_num(p["climate_profile_scope_1"]),
                "profile_scope_2": None if p is None else scalar_num(p["climate_profile_scope_2"]),
                "profile_scope_3": None if p is None else scalar_num(p["climate_profile_scope_3"]),
                "profile_scope_1x2": None if p is None else scalar_num(p["climate_profile_scope_1x2"]),
                "profile_scope_1x2x3": None if p is None else scalar_num(p["climate_profile_scope_1x2x3"]),
                "unit": None if p is None else scalar(p["climate_profile_scope_1_unit"]),
                "lc_share_capex": None if p is None else scalar_num(p["climate_profile_lc_share_capex"]),
                "lc_share_revenue": None if p is None else scalar_num(p["climate_profile_lc_share_revenue"]),
                "provenance_class": "voluntary",
            }
        )
    company = pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)
    print(f"wba_company: {len(company)} rows, {company['ticker'].nunique()} tickers")
    print("wba_company: disclosure level " + str(dict(company["disclosure_level"].value_counts(dropna=False))))

    unit_by_ticker = dict(zip(company["ticker"], company["unit"]))
    verified = dict(zip(company["ticker"], company["independently_verified"]))
    accounting = dict(zip(company["ticker"], company["valid_accounting"]))

    def dq_for(ticker, estimated):
        if estimated:
            return 4  # WBA's own estimate, not a company figure
        if verified.get(ticker):
            return 1
        if accounting.get(ticker):
            return 2
        return 3

    # -------------------------------------------------------------- wba_emissions
    erows = []
    em = em[em["company_id"].isin(id_to_ticker)]
    for _, r in em.iterrows():
        t = id_to_ticker[r["company_id"]]
        fy = scalar_num(r["emissions_year"], "emissions_year")
        for scope, col, flag in [
            ("1+2", "emissions_s1x2", "emissions_estimated_s1x2"),
            ("3", "emissions_s3", "emissions_estimated_s3"),
        ]:
            v = scalar_num(r[col], col)
            if v is None:
                continue
            est = bool(scalar_bool(r[flag], flag))
            erows.append(
                {
                    "ticker": t, "fy": int(fy), "scope": scope, "tonnes_co2e": v,
                    "unit": unit_by_ticker.get(t), "estimated_flag": est,
                    "source_table": "emissions_timeseries", "dq": dq_for(t, est),
                    "provenance_class": "voluntary",
                }
            )
    n_ts = len(erows)
    cpm = cp[cp["company_id"].isin(id_to_ticker)]
    for _, r in cpm.iterrows():
        t = id_to_ticker[r["company_id"]]
        fy = scalar_num(r["climate_profile_year"], "climate_profile_year")
        if fy is None:
            continue
        for scope, col in [
            ("1", "climate_profile_scope_1"), ("2", "climate_profile_scope_2"),
            ("3", "climate_profile_scope_3"), ("1+2", "climate_profile_scope_1x2"),
            ("1+2+3", "climate_profile_scope_1x2x3"),
        ]:
            v = scalar_num(r[col], col)
            if v is None:
                continue
            erows.append(
                {
                    "ticker": t, "fy": int(fy), "scope": scope, "tonnes_co2e": v,
                    "unit": scalar(r["climate_profile_scope_1_unit"]), "estimated_flag": False,
                    "source_table": "climate_profile", "dq": dq_for(t, False),
                    "provenance_class": "voluntary",
                }
            )
    emissions = pd.DataFrame(erows)
    # The two tables disagree on Scope 2 basis for some companies, so both are kept and the
    # timeseries, which is what the pathways are anchored on, is the preferred row.
    order = {"emissions_timeseries": 0, "climate_profile": 1}
    emissions["_o"] = emissions["source_table"].map(order)
    emissions = emissions.sort_values(["ticker", "fy", "scope", "_o"])
    emissions["preferred"] = ~emissions.duplicated(["ticker", "fy", "scope"], keep="first")
    emissions = emissions.drop(columns="_o").reset_index(drop=True)
    dup = (~emissions["preferred"]).sum()
    both = emissions[emissions.duplicated(["ticker", "fy", "scope"], keep=False)]
    pivot = both.pivot_table(
        index=["ticker", "fy", "scope"], columns="source_table", values="tonnes_co2e"
    ).dropna()
    same = (pivot["emissions_timeseries"].round(0) == pivot["climate_profile"].round(0)).sum()
    diff = pivot[pivot["emissions_timeseries"].round(0) != pivot["climate_profile"].round(0)]
    higher = int((diff["climate_profile"] > diff["emissions_timeseries"]).sum())
    print(f"wba_emissions: {len(emissions)} rows, {n_ts} from the timeseries, "
          f"{len(emissions) - n_ts} from the climate profile")
    print(f"wba_emissions: {dup} rows are a second reading of a ticker-year-scope already covered; "
          f"of {len(pivot)} such pairs {same} agree to the tonne")
    print(f"wba_emissions: of the {len(diff)} that disagree the profile figure is the higher one "
          f"{higher} times, so the profile carries the wider accounting basis")
    print("wba_emissions: by scope " + str(dict(emissions["scope"].value_counts())))
    print("wba_emissions: tickers with scope 1 "
          f"{emissions.loc[emissions.scope == '1', 'ticker'].nunique()}, scope 2 "
          f"{emissions.loc[emissions.scope == '2', 'ticker'].nunique()}, scope 3 "
          f"{emissions.loc[emissions.scope == '3', 'ticker'].nunique()}, scope 1+2 "
          f"{emissions.loc[emissions.scope == '1+2', 'ticker'].nunique()}")
    print("wba_emissions: dq " + str(dict(emissions["dq"].value_counts().sort_index())))
    print(f"wba_emissions: unit null on {emissions['unit'].isna().sum()} rows")

    # -------------------------------------------------------------- wba_pathway
    prows = []
    for _, r in em.iterrows():
        t = id_to_ticker[r["company_id"]]
        year = scalar_num(r["emissions_year"], "emissions_year")
        for series, col in [
            ("s1x2_spcp", "emissions_s1x2_spcp"), ("s1x2_cpcp", "emissions_s1x2_cpcp"),
            ("s3_spcp", "emissions_s3_spcp"), ("s3_cpcp", "emissions_s3_cpcp"),
        ]:
            v = scalar_num(r[col], col)
            if v is None:
                continue
            prows.append(
                {
                    "ticker": t, "year": int(year), "series": series, "value": v,
                    "is_modelled": True, "provenance_class": "voluntary",
                }
            )
    pathway = pd.DataFrame(prows)
    reported = (
        emissions[emissions["source_table"] == "emissions_timeseries"]
        .groupby(["ticker", "scope"])["fy"].max()
    )
    last_rep = {}
    for (t, scope), y in reported.items():
        last_rep[(t, "s1x2" if scope == "1+2" else "s3")] = y
    pathway["is_projection"] = [
        y > last_rep.get((t, s.split("_")[0]), 0)
        for t, y, s in zip(pathway["ticker"], pathway["year"], pathway["series"])
    ]
    pathway = pathway.sort_values(["ticker", "series", "year"]).reset_index(drop=True)
    print(f"wba_pathway: {len(pathway)} rows, {pathway['ticker'].nunique()} tickers, "
          f"years {pathway['year'].min()}-{pathway['year'].max()}")
    print("wba_pathway: by series " + str(dict(pathway["series"].value_counts())))
    print(f"wba_pathway: {pathway['is_projection'].sum()} projected rows, "
          f"{(~pathway['is_projection']).sum()} covering years the company has already reported")

    # -------------------------------------------------------------- wba_targets
    tg = tg[tg["company_id"].isin(id_to_ticker)]
    trows = []
    for _, r in tg.iterrows():
        red = scalar_num(r["target_reduction"], "target_reduction")
        trows.append(
            {
                "ticker": id_to_ticker[r["company_id"]],
                "wba_target_id": r["target_id"],
                "scope": r["target_scope"],
                "horizon": r["target_time_horizon"],
                "target_type": scalar(r["target_type"], "target_type"),
                "base_year": scalar_num(r["target_base_year"], "target_base_year"),
                "reported_year": scalar_num(r["target_reported_year"], "target_reported_year"),
                "target_year": scalar_num(r["target_target_year"], "target_target_year"),
                "reduction_pct": None if red is None else red * 100.0,
                "base_absolute_tonnes": scalar_num(r["target_base_absolute_value"], "target_base_absolute_value"),
                "target_absolute_tonnes": scalar_num(r["target_target_absolute_value"], "target_target_absolute_value"),
                "base_intensity": scalar_num(r["target_base_intensity_value"], "target_base_intensity_value"),
                "target_intensity": scalar_num(r["target_target_intensity_value"], "target_target_intensity_value"),
                "intensity_unit": scalar(r["target_intensity_unit"], "target_intensity_unit"),
                "validation": scalar(r["target_validation"], "target_validation"),
                "sbti_classification": scalar(r["target_sbti_classification"], "target_sbti_classification"),
                "covered_categories": joined(r["target_covered_categories"]),
                "aligned_1_5": scalar_bool(r["target_1_5_aligned"], "target_1_5_aligned"),
                "alignment_score_1_5": scalar_num(r["target_1_5_alignment_score"], "target_1_5_alignment_score"),
                "wording": scalar(r["target_wording"], "target_wording"),
                "provenance_class": "voluntary",
            }
        )
    targets = pd.DataFrame(trows)
    targets["has_target"] = (
        targets["target_year"].notna() | targets["reduction_pct"].notna() | targets["wording"].notna()
    )
    targets = targets.sort_values(["ticker", "scope", "horizon"]).reset_index(drop=True)
    print(f"wba_targets: {len(targets)} rows, {targets['ticker'].nunique()} tickers, "
          f"{targets['has_target'].sum()} slots carry a target and "
          f"{(~targets['has_target']).sum()} record that there is none")
    print("wba_targets: sbti classification " + str(dict(targets["sbti_classification"].value_counts(dropna=False))))
    print("wba_targets: validation " + str(dict(targets["validation"].value_counts(dropna=False))))
    print(f"wba_targets: reduction_pct present on {targets['reduction_pct'].notna().sum()} rows")

    # -------------------------------------------------------------- wba_sources
    sr = sr[sr["company_id"].isin(id_to_ticker)].copy()
    sources = pd.DataFrame(
        {
            "ticker": sr["company_id"].map(id_to_ticker),
            "wba_source_id": sr["source_id"],
            "source_type": sr["source_type"],
            "source_name": sr["source_name"],
            "source_year": pd.to_numeric(sr["source_year"], errors="coerce"),
            "source_url": sr["source_url"],
            "provenance_class": "voluntary",
        }
    ).sort_values(["ticker", "source_year", "source_type"]).reset_index(drop=True)
    print(f"wba_sources: {len(sources)} rows, {sources['ticker'].nunique()} tickers, "
          f"{sources['source_url'].isna().sum()} rows with no URL")
    print("wba_sources: top types " + str(dict(sources["source_type"].value_counts().head(6))))

    # -------------------------------------------------------------- write
    for name, df in [
        ("wba_company", company), ("wba_emissions", emissions), ("wba_targets", targets),
        ("wba_pathway", pathway), ("wba_sources", sources),
    ]:
        path = INTERIM / f"{name}.parquet"
        df.to_parquet(path, index=False)
        print(f"wrote {path.relative_to(ROOT)}: {len(df)} rows, {path.stat().st_size} bytes")

    print(f"airtable: {MULTI['count']} cells held several values where one was expected, "
          f"nulled and counted: {MULTI['columns']}")

    prov = {
        "source": "World Benchmarking Alliance, Climate and Energy Benchmark (SDG2000)",
        "provenance_class": "voluntary",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "files": PROV_FILES,
        "licence": (
            "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International "
            "(CC BY-NC-ND 4.0), the terms WBA states on its fair-use-donation page for its "
            "methodologies, benchmarks, scorecards, rankings and underlying benchmark data. WBA "
            "also asks for a voluntary donation from anyone who derives financial benefit from the "
            "work. The export was supplied to us as a zip rather than downloaded."
        ),
        "redistribution": (
            "NonCommercial and NoDerivatives, so this is the most restrictive licence in the "
            "project. Cite WBA and link the benchmark; publish findings and charts, not a "
            "redistributed or adapted copy of the underlying tables. The derived parquet files "
            "here are an internal join, not a public release of WBA data."
        ),
        "method": (
            "Airtable CSV export of six tables, five of which are used; footprintattributes.csv, "
            "19,291 named company attributes with evidence text, is read by no lane yet. "
            "Brace-wrapped cells are parsed as lists; a cell "
            "holding several values where the schema expects one is nulled and counted rather than "
            "truncated. Companies are joined to S&P 500 tickers best key first: ISIN through the "
            "free OpenFIGI mapping API, then LEI through GLEIF to an ISIN and back through "
            "OpenFIGI, then an exact match on normalised company names against the universe lane's "
            "alias map, which carries former SEC registrant names. A name match is vetoed when the "
            "company's ISIN resolves to a US listing that is not in the index, which is what stops "
            "Toronto-Dominion landing on TransDigm and Merck KGaA on Merck & Co."
        ),
        "limitations": [
            "Voluntary. Every tonne here is a company-disclosed figure that WBA assessed. It is not "
            "comparable in standing to the EPA GHGRP and CAMD filings and must never be merged into "
            "a mandatory column.",
            "The climate profile and the emissions timeseries disagree on Scope 1+2 for a large "
            "minority of companies and the profile figure is the higher one in 128 of the 134 "
            "disagreements, median ratio 1.26. Apple is the clean illustration: the profile Scope 2 "
            "is its location-based 1,224,500 tCO2e while the timeseries total implies a "
            "market-based figure near 3,300. Scope 3 disagrees in both directions, so category "
            "coverage differs too and no single rule explains all of it. Both readings are kept in "
            "wba_emissions with a source_table column and the timeseries row is flagged preferred, "
            "because it is the one the pathways are anchored on.",
            "Scope 1 and Scope 2 separately exist only in the climate profile, for its single "
            "assessment year. The timeseries carries Scope 1+2 and Scope 3 only.",
            "The pathway columns are WBA's modelled trajectories, not disclosure. Every row of "
            "wba_pathway carries is_modelled = True for that reason. See pathway_columns below.",
            "247 of the 500 S&P 500 companies are in WBA at all. The gap is WBA's coverage, not "
            "the join: an exhaustive prefix scan of the 255 unmatched index members against the "
            "1,755 unmatched WBA companies returned three candidate pairs, two of which were real "
            "and are now matched, and one of which was Cooper Companies against a Brazilian dairy "
            "cooperative. Caterpillar, UnitedHealth, RTX, Thermo Fisher, Deere, Abbott, Union "
            "Pacific, Lockheed Martin, Medtronic and Altria are simply not in the SDG2000.",
        ],
        "pathway_columns": {
            "raw_names": ["emissions_s1x2_spcp", "emissions_s1x2_cpcp", "emissions_s3_spcp",
                          "emissions_s3_cpcp"],
            "confirmed": (
                "WBA publishes no field-level gloss for the spcp and cpcp suffixes that we could "
                "find, so the raw names are kept. What the two series are was established "
                "arithmetically from the data instead. The shape claim below holds without "
                "exception on every company whose two series diverge at all, 630 of 630 on Scope "
                "1+2 and 402 of 402 on Scope 3. The size claim reproduces the offset exactly for "
                "575 of those 630."
            ),
            "identity_shape": (
                "The two series are identical from the base year to the company's last reported "
                "year. From the year after that, cpcp = max(spcp - k, floor) for a constant k that "
                "does not vary with the year. Verified on every diverging company, 630 of 630 on "
                "Scope 1+2 and 402 of 402 on Scope 3. The floor is 9 per cent of the base-year "
                "value for 766 of 1,210 companies and 10.5 per cent for 273 more."
            ),
            "identity_size": (
                "k equals the company's cumulative reported emissions above spcp over its reported "
                "history, floored at zero, divided by the number of years from the last shared "
                "year to 2050. Exact for 575 of the 630 diverging companies on Scope 1+2; for the "
                "other 55 the reconstruction is within a few tenths of a per cent but not exact. "
                "Because the overshoot is floored at zero, underperformance is charged and "
                "outperformance is not credited."
            ),
            "reading": (
                "spcp is the pathway as allocated, and cpcp is the same pathway re-cut so that the "
                "company gives back the budget it has already overspent, subject to a residual "
                "floor of 9 per cent of the base year. cpcp is therefore never above spcp before "
                "the floor binds: at 2030 it is below spcp for 630 companies, equal for 576 and "
                "above for none. This is consistent with the ACT framework, which derives a company "
                "pathway from a sectoral pathway and assesses the company against the remaining "
                "budget, but the letters s-p and c-p have not been confirmed against a WBA "
                "document and no gloss has been invented for them."
            ),
        },
    }
    (INTERIM / "provenance" / "wba.json").write_text(json.dumps(prov, indent=2, sort_keys=True))
    print("wrote data/interim/provenance/wba.json")


if __name__ == "__main__":
    main()
