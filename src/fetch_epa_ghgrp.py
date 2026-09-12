"""EPA Greenhouse Gas Reporting Program (GHGRP) via the Envirofacts REST API.

Pulls every reporting year that exists, keeps only direct-emitter sectors, and rolls facility
emissions up to the parent companies named on each facility record. Output is two tables:

    data/interim/ghgrp_facilities.parquet    one row per facility-year-parent
    data/interim/ghgrp_parent_year.parquet   one row per parent-year

No ticker join happens here. The entity-resolution lane owns that and works off the raw
parent strings this script preserves.

What matters about Envirofacts here:

  * PUB_FACTS_SECTOR_GHG_EMISSION mixes direct emitters (sector_type E), fuel and gas suppliers
    (S, whose numbers are the downstream CO2 of product sold, double-counting the emitters) and
    CO2 injection (I). A naive sum of 2023 gives ~7,364 MMT, near 3x US emissions. Only E is
    Scope 1.
  * /ROWS/a:b/ is inclusive at both ends and zero-indexed, so a page of 10,000 is 0:9999.
  * We page at 10,000 rows even though larger spans work today (26,272 rows came back in one
    request on 2026-09-12, and so did the same query as /JSON, so neither the 10,000-row
    pagination cap nor the 5,000-row /JSON cap reproduces). Paged CSV is the shape that has
    always worked, the pages are small enough to cache and diff, and a cap that appears later
    costs us nothing.
"""

import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "epa_ghgrp"
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance" / "epa_ghgrp.json"

BASE = "https://data.epa.gov/efservice"
UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
PAGE = 10000
PROBE_YEARS = range(2010, 2027)

LICENCE = "US federal government work, public domain (17 U.S.C. 105); EPA requests attribution."
REDISTRIBUTION = (
    "Derived numbers, tables and charts may be published. Cite as: U.S. EPA Greenhouse Gas "
    "Reporting Program, accessed via the Envirofacts REST API."
)

# EPA is explicit that it wants under 10 requests a second. This whole run is ~120 requests, so
# a third of a second between them costs us nothing and keeps us far inside that.
POLITE_DELAY = 0.3

SESSION = requests.Session()
SESSION.headers["User-Agent"] = UA

PROVENANCE = {}
LIVE_FETCHES = 0


def fetch(url, cache_name):
    """GET a URL once, ever. Cached responses are reused byte for byte on later runs."""
    global LIVE_FETCHES
    path = RAW / cache_name
    if path.exists() and path.stat().st_size > 0:
        body = path.read_bytes()
        PROVENANCE.setdefault(url, _record(url, body, 200, path.stat().st_mtime, from_cache=True))
        return body

    if LIVE_FETCHES:
        time.sleep(POLITE_DELAY)
    resp = SESSION.get(url, timeout=300)
    LIVE_FETCHES += 1
    PROVENANCE[url] = _record(url, resp.content, resp.status_code, None)
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return resp.content


def _record(url, body, status, mtime, from_cache=False):
    when = datetime.fromtimestamp(mtime, timezone.utc) if mtime else datetime.now(timezone.utc)
    rec = {
        "url": url,
        "retrieved_at": when.isoformat().replace("+00:00", "Z"),
        "http_status": status,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "licence": LICENCE,
        "redistribution": REDISTRIBUTION,
    }
    if from_cache:
        # The timestamp is the cache file's mtime, not the moment of the original response.
        rec["retrieved_at_source"] = "cache file mtime"
    return rec


def count_rows(table, year=None):
    if year is None:
        url = f"{BASE}/{table}/COUNT/JSON"
        name = f"count_{table.lower()}.json"
    else:
        url = f"{BASE}/{table}/YEAR/{year}/COUNT/JSON"
        name = f"count_{table.lower()}_{year}.json"
    return int(json.loads(fetch(url, name))[0]["TOTALQUERYRESULTS"])


def read_csv(body):
    return pd.read_csv(io.BytesIO(body), dtype=str, keep_default_na=False, encoding_errors="replace")


def pull_year(table, year, total):
    """Page one reporting year of a table out as CSV and concatenate it."""
    frames = []
    for start in range(0, total, PAGE):
        stop = min(start + PAGE, total) - 1
        url = f"{BASE}/{table}/YEAR/{year}/ROWS/{start}:{stop}/CSV"
        frames.append(read_csv(fetch(url, f"{table.lower()}_{year}_{start}_{stop}.csv")))
    df = pd.concat(frames, ignore_index=True)
    if len(df) != total:
        raise SystemExit(f"{table} {year}: paged {len(df)} rows but COUNT said {total}")
    return df


def num(series):
    return pd.to_numeric(series.replace("", pd.NA), errors="coerce")


SUFFIX = re.compile(
    r"\b(CORPORATION|CORP|COMPANY|COMPANIES|CO|COS|INCORPORATED|INC|LLC|LLP|LP|LTD|PLC|HOLDINGS"
    r"|HOLDING|GROUP|THE|USA|US|AMERICA|AMERICAN|AMERICAS|INTERNATIONAL|INTL|PARTNERS|ENTERPRISES"
    r"|SERVICES|INDUSTRIES|PBC|NV|SA|AG|SE|CLASS|AND|CHEMICALS)\b"
)


def normalise(name):
    """Readable matching form: upper case, no punctuation, no legal-form words."""
    s = name.upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def parent_key(name):
    """Aggregation key. Whitespace goes too, because EPA files both EXXON MOBIL CORP and
    EXXONMOBIL CORP in the same year and they are one company."""
    k = normalise(name).replace(" ", "")
    if not k:
        k = re.sub(r"[^A-Z0-9]", "", name.upper())
    return k


PCT = re.compile(r"^(?P<name>.*?)\s*\(\s*(?P<pct>[0-9]+(?:\.[0-9]+)?)\s*%\s*\)\s*$")


def split_parents(raw):
    """EPA writes 'NAME (PCT%); NAME (PCT%)'. Percentages are missing on some rows."""
    out = []
    for part in (p.strip() for p in raw.split(";")):
        if not part:
            continue
        m = PCT.match(part)
        out.append((m.group("name").strip(), float(m.group("pct"))) if m else (part, None))
    return out


def allocate(parsed):
    """Turn parsed parents into (name, stated_pct, fraction_used, imputed) tuples.

    Where a percentage is absent we give that parent an even share of whatever the stated
    percentages leave unclaimed, and flag it. We never rescale a stated percentage.
    """
    missing = [p for _, p in parsed if p is None]
    if not missing:
        return [(n, p, p / 100.0, False) for n, p in parsed]
    residual = max(0.0, 100.0 - sum(p for _, p in parsed if p is not None))
    fill = residual / len(missing)
    return [(n, p, (fill if p is None else p) / 100.0, p is None) for n, p in parsed]


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    PROV.parent.mkdir(parents=True, exist_ok=True)
    if PROV.exists():
        PROVENANCE.update({r["url"]: r for r in json.loads(PROV.read_text())["fetches"]})

    sectors = read_csv(fetch(f"{BASE}/PUB_DIM_SECTOR/CSV", "pub_dim_sector.csv"))
    sectors["sector_id"] = num(sectors["sector_id"]).astype("Int64")
    print(f"PUB_DIM_SECTOR: {len(sectors)} sectors")
    for t, n in sectors["sector_type"].value_counts().items():
        names = ", ".join(sectors.loc[sectors["sector_type"] == t, "sector_code"])
        print(f"  sector_type {t}: {n}  ({names})")
    stype = dict(zip(sectors["sector_id"], sectors["sector_type"]))
    sname = dict(zip(sectors["sector_id"], sectors["sector_name"]))
    scode = dict(zip(sectors["sector_id"], sectors["sector_code"]))

    print("\nreporting years offered by PUB_DIM_FACILITY:")
    years = []
    for y in PROBE_YEARS:
        n = count_rows("PUB_DIM_FACILITY", y)
        print(f"  {y}: {n:>6} facilities" + ("" if n else "   <- no data published"))
        if n:
            years.append((y, n))
    if not years:
        raise SystemExit("Envirofacts returned no facility years at all")
    print(f"years with data: {years[0][0]}-{years[-1][0]}")

    fac_frames, fact_frames = [], []
    for y, n_fac in years:
        n_fact = count_rows("PUB_FACTS_SECTOR_GHG_EMISSION", y)
        fac_frames.append(pull_year("PUB_DIM_FACILITY", y, n_fac))
        fact_frames.append(pull_year("PUB_FACTS_SECTOR_GHG_EMISSION", y, n_fact))
        print(f"  {y}: {n_fac:>6} facility rows, {n_fact:>6} sector-gas emission rows")

    fac = pd.concat(fac_frames, ignore_index=True)
    facts = pd.concat(fact_frames, ignore_index=True)
    print(f"\nPUB_DIM_FACILITY total rows: {len(fac)}")
    print(f"PUB_FACTS_SECTOR_GHG_EMISSION total rows: {len(facts)}")

    fac["facility_id"] = num(fac["facility_id"]).astype("Int64")
    fac["year"] = num(fac["year"]).astype("Int16")
    dupes = fac.duplicated(["facility_id", "year"]).sum()
    print(f"duplicate (facility_id, year) rows in PUB_DIM_FACILITY: {dupes}")
    if dupes:
        fac = fac.drop_duplicates(["facility_id", "year"])
        print(f"  dropped, {len(fac)} facility-years remain")

    facts["facility_id"] = num(facts["facility_id"]).astype("Int64")
    facts["year"] = num(facts["year"]).astype("Int16")
    facts["sector_id"] = num(facts["sector_id"]).astype("Int64")
    facts["co2e_emission"] = num(facts["co2e_emission"])
    facts["sector_type"] = facts["sector_id"].map(stype)
    unmapped = facts["sector_type"].isna().sum()
    print(f"emission rows whose sector_id is not in PUB_DIM_SECTOR: {unmapped}")
    print(f"emission rows with a null co2e_emission: {int(facts['co2e_emission'].isna().sum())}")

    per_year_set = set(facts["year"].dropna().astype(int))
    naive_2023 = facts.loc[facts["year"] == 2023, "co2e_emission"].sum() / 1e6
    direct = facts[facts["sector_type"] == "E"].copy()
    filtered_2023 = direct.loc[direct["year"] == 2023, "co2e_emission"].sum() / 1e6
    print("\nthe supplier double-count, reporting year 2023")
    print(f"  every sector_type summed naively : {naive_2023:8.1f} MMT CO2e  <- roughly 3x US emissions")
    print(f"  direct emitters only (type E)    : {filtered_2023:8.1f} MMT CO2e  <- Scope 1")
    for t in ("S", "I"):
        part = facts[(facts["year"] == 2023) & (facts["sector_type"] == t)]["co2e_emission"].sum() / 1e6
        print(f"  type {t} excluded                  : {part:8.1f} MMT CO2e")
    if 2023 in per_year_set:
        # Regression test. EPA's own published headline for RY2023 is 2,697 MMT; if this trips,
        # either the sector filter broke or EPA restated the year.
        assert 2600 <= filtered_2023 <= 2800, f"2023 direct-emitter total {filtered_2023:.1f} MMT is off"
        print(f"  assertion passed: 2600 <= {filtered_2023:.1f} <= 2800 MMT")
    else:
        print("  reporting year 2023 absent from this pull, assertion skipped")

    print("\ndirect-emitter (Scope 1) totals by reporting year")
    per_year = direct.groupby("year", observed=True)["co2e_emission"].sum() / 1e6
    for y, v in per_year.items():
        print(f"  {y}: {v:8.1f} MMT CO2e")

    # min_count=1 so a facility whose only type-E rows are null stays null instead of becoming a
    # zero we never measured.
    fy = (direct.groupby(["facility_id", "year"], observed=True)["co2e_emission"]
          .sum(min_count=1).rename("co2e_tonnes"))
    print(f"\nfacility-years with type-E rows: {len(fy)}, of which a usable number: {int(fy.notna().sum())}")

    # A facility can report under several sectors; call the largest one its sector.
    by_sector = (direct.groupby(["facility_id", "year", "sector_id"], observed=True)["co2e_emission"]
                 .sum(min_count=1))
    top = by_sector.reset_index().sort_values("co2e_emission", ascending=False)
    top = top.drop_duplicates(["facility_id", "year"])
    top["sector"] = top["sector_id"].map(sname)
    top["sector_code"] = top["sector_id"].map(scode)

    cols = [
        "facility_id", "year", "facility_name", "parent_company", "latitude", "longitude",
        "state", "county", "naics_code", "facility_types",
    ]
    out = fac[cols].copy()
    out["latitude"] = num(out["latitude"])
    out["longitude"] = num(out["longitude"])
    out = out.merge(fy, on=["facility_id", "year"], how="left")
    out = out.merge(top[["facility_id", "year", "sector", "sector_code"]], on=["facility_id", "year"], how="left")
    no_direct = int(out["co2e_tonnes"].isna().sum())
    print(f"facility-years with no direct-emitter rows (suppliers, injectors): {no_direct} "
          f"-> co2e_tonnes left null, never zero-filled")

    # Independent corroboration of the sector_type filter: EPA also labels the facility itself.
    y23 = out[out["year"] == 2023]
    labelled = y23["facility_types"].fillna("").str.contains("Direct Emitter")
    has_e = y23["co2e_tonnes"].notna()
    print(f"2023 cross-check of the type-E filter against the facility_types label")
    print(f"  labelled Direct Emitter and has type-E rows : {int((labelled & has_e).sum())}")
    print(f"  labelled Direct Emitter, no type-E rows     : {int((labelled & ~has_e).sum())}")
    print(f"  not so labelled but has type-E rows         : {int((~labelled & has_e).sum())}")
    print(f"  neither                                     : {int((~labelled & ~has_e).sum())}")

    blank_parent = out["parent_company"].str.strip().eq("")
    print(f"facility-years with a blank parent_company: {int(blank_parent.sum())} "
          f"({out.loc[blank_parent, 'co2e_tonnes'].sum() / 1e6:.1f} MMT unattributable)")

    rows = []
    stats = {"sole_stated": 0, "sole_imputed": 0, "multi_all_stated": 0, "multi_part_imputed": 0}
    pct_sum_off = 0
    for r in out.itertuples(index=False):
        raw = (r.parent_company or "").strip()
        base = {
            "facility_id": r.facility_id, "year": r.year, "facility_name": r.facility_name,
            "parent_company": raw or None, "latitude": r.latitude, "longitude": r.longitude,
            "state": r.state or None, "county": r.county or None,
            "naics_code": r.naics_code or None, "facility_types": r.facility_types or None,
            "sector": r.sector, "sector_code": r.sector_code, "co2e_tonnes": r.co2e_tonnes,
        }
        if not raw:
            rows.append({**base, "parent_name_raw": None, "parent_name_clean": None,
                         "parent_name_norm": None, "ownership_pct": None, "ownership_frac": None,
                         "ownership_imputed": None, "n_parents": 0,
                         "co2e_tonnes_share": None, "dq": None})
            continue
        parsed = split_parents(raw)
        stated = [p for _, p in parsed if p is not None]
        if len(parsed) == 1:
            stats["sole_stated" if stated else "sole_imputed"] += 1
        else:
            stats["multi_all_stated" if len(stated) == len(parsed) else "multi_part_imputed"] += 1
        if stated and not (99.0 <= sum(stated) <= 101.0) and len(stated) == len(parsed):
            pct_sum_off += 1
        for name, pct, frac, imputed in allocate(parsed):
            share = None if pd.isna(r.co2e_tonnes) else r.co2e_tonnes * frac
            rows.append({
                **base,
                "parent_name_raw": name,
                "parent_name_clean": parent_key(name),
                "parent_name_norm": normalise(name) or None,
                "ownership_pct": pct,
                "ownership_frac": frac,
                "ownership_imputed": imputed,
                "n_parents": len(parsed),
                "co2e_tonnes_share": share,
                # PCAF-style: EPA-verified mandatory filing is 1; an apportionment we had to
                # invent because EPA left the percentage blank drops it to 2.
                "dq": None if pd.isna(r.co2e_tonnes) else (2 if imputed else 1),
            })

    facilities = pd.DataFrame(rows)
    facilities["n_parents"] = facilities["n_parents"].astype("int16")
    facilities["dq"] = facilities["dq"].astype("Int8")
    facilities["ownership_imputed"] = facilities["ownership_imputed"].astype("boolean")
    print(f"\nfacility-year-parent rows: {len(facilities)}")
    print(f"  one parent, percentage stated      : {stats['sole_stated']}")
    print(f"  one parent, percentage absent      : {stats['sole_imputed']}")
    print(f"  several parents, all stated        : {stats['multi_all_stated']}")
    print(f"  several parents, some absent       : {stats['multi_part_imputed']}")
    print(f"  stated percentages not summing to 100 +/- 1: {pct_sum_off}")
    print(f"  distinct raw parent strings        : {facilities['parent_name_raw'].nunique()}")
    print(f"  distinct parent_name_clean keys    : {facilities['parent_name_clean'].nunique()}")

    attributed = facilities["co2e_tonnes_share"].sum()
    total_direct = fy.sum()
    print(f"  emissions apportioned to a parent  : {attributed / 1e6:.1f} of {total_direct / 1e6:.1f} MMT "
          f"({100 * attributed / total_direct:.2f}%)")

    # One row per parent-year. co2e_tonnes is ownership-weighted; the unapportioned column is
    # what you would get by summing whole facilities, which double-counts jointly owned sites.
    grp = facilities.dropna(subset=["parent_name_clean"]).groupby(["parent_name_clean", "year"], observed=True)
    parent_year = grp.agg(
        co2e_tonnes=("co2e_tonnes_share", lambda s: s.sum(min_count=1)),
        co2e_tonnes_unapportioned=("co2e_tonnes", lambda s: s.sum(min_count=1)),
        facility_count=("facility_id", "nunique"),
        n_raw_spellings=("parent_name_raw", "nunique"),
        dq=("dq", "max"),
    ).reset_index()
    direct_fac = (facilities.dropna(subset=["parent_name_clean", "co2e_tonnes"])
                  .groupby(["parent_name_clean", "year"], observed=True)["facility_id"].nunique()
                  .rename("facility_count_direct").reset_index())
    parent_year = parent_year.merge(direct_fac, on=["parent_name_clean", "year"], how="left")
    parent_year["facility_count_direct"] = parent_year["facility_count_direct"].fillna(0).astype("int32")

    imputed_share = (facilities[facilities["ownership_imputed"] == True]
                     .groupby(["parent_name_clean", "year"], observed=True)["co2e_tonnes_share"].sum()
                     .rename("co2e_tonnes_imputed_ownership").reset_index())
    parent_year = parent_year.merge(imputed_share, on=["parent_name_clean", "year"], how="left")
    parent_year["co2e_tonnes_imputed_ownership"] = parent_year["co2e_tonnes_imputed_ownership"].fillna(0.0)

    display = (facilities.dropna(subset=["parent_name_clean"])
               .groupby(["parent_name_clean", "parent_name_raw"], observed=True).size()
               .rename("n").reset_index().sort_values("n", ascending=False)
               .drop_duplicates("parent_name_clean"))
    norm = (facilities.dropna(subset=["parent_name_clean"])
            .drop_duplicates("parent_name_clean")[["parent_name_clean", "parent_name_norm"]])
    parent_year = parent_year.merge(
        display[["parent_name_clean", "parent_name_raw"]].rename(columns={"parent_name_raw": "parent_name_display"}),
        on="parent_name_clean", how="left")
    parent_year = parent_year.merge(norm, on="parent_name_clean", how="left")
    parent_year = parent_year[[
        "parent_name_clean", "parent_name_display", "parent_name_norm", "year", "co2e_tonnes",
        "co2e_tonnes_unapportioned", "co2e_tonnes_imputed_ownership", "facility_count",
        "facility_count_direct", "n_raw_spellings", "dq",
    ]].sort_values(["year", "co2e_tonnes"], ascending=[True, False])

    print(f"\nparent-year rows: {len(parent_year)}")
    print(f"  distinct parents across all years: {parent_year['parent_name_clean'].nunique()}")
    print(f"  parents in 2023: {int((parent_year['year'] == 2023).sum())}")

    p23 = parent_year[parent_year["year"] == 2023].head(20)
    print("\ntop 20 parents by ownership-weighted direct CO2e, reporting year 2023")
    for r in p23.itertuples(index=False):
        print(f"  {r.parent_name_clean[:28]:<28} {r.co2e_tonnes:>12,.0f} t  "
              f"{r.facility_count:>4} fac  {r.parent_name_display[:34]}")

    # Squashing whitespace out of the key is what merges EXXON MOBIL with EXXONMOBIL, and it
    # occasionally merges two firms that only look alike. Surface the candidates rather than
    # pretend the key is exact: a human settles each one in seconds.
    latest = int(parent_year["year"].max())
    recent = facilities[facilities["year"] == latest].dropna(subset=["parent_name_clean"])
    squash = recent["parent_name_raw"].str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    fams = squash.groupby(recent["parent_name_clean"]).agg(lambda s: {x[:6] for x in s})
    suspect = fams[fams.map(len) > 1].index
    emis = recent.groupby("parent_name_clean")["co2e_tonnes_share"].sum().reindex(suspect).dropna()
    print(f"\nkeys in {latest} merging raw names with different first six characters "
          f"({len(suspect)} keys, most are spelling variants, a few are different companies)")
    for k in emis.sort_values(ascending=False).index[:12]:
        names = sorted(set(recent.loc[recent["parent_name_clean"] == k, "parent_name_raw"]))
        print(f"  {k[:20]:<20} {emis[k] / 1e6:6.2f} MMT  " + " | ".join(n[:26] for n in names[:4]))

    fac_path = INTERIM / "ghgrp_facilities.parquet"
    par_path = INTERIM / "ghgrp_parent_year.parquet"
    facilities.to_parquet(fac_path, index=False)
    parent_year.to_parquet(par_path, index=False)
    print(f"\nwrote {fac_path} ({len(facilities)} rows)")
    print(f"wrote {par_path} ({len(parent_year)} rows)")
    print("\nnotes for whoever reads these tables")
    print("  ghgrp_facilities is exploded to one row per facility-year-parent. co2e_tonnes is the")
    print("  whole facility; co2e_tonnes_share is that parent's slice. Summing co2e_tonnes by parent")
    print("  double-counts jointly owned sites, so group on co2e_tonnes_share.")
    print("  parent_name_clean is a match key with all whitespace removed, because EPA files both")
    print("  EXXON MOBIL CORP and EXXONMOBIL CORP. Show parent_name_display to humans and fuzzy-match")
    print("  on parent_name_norm, which keeps word boundaries.")
    print("  No ticker column here by design. The entity-resolution lane joins these names to tickers.")

    PROV.write_text(json.dumps({
        "source": "epa_ghgrp",
        "description": "EPA Greenhouse Gas Reporting Program, Envirofacts REST API",
        "tables": ["PUB_DIM_FACILITY", "PUB_FACTS_SECTOR_GHG_EMISSION", "PUB_DIM_SECTOR"],
        "reporting_years": [y for y, _ in years],
        "licence": LICENCE,
        "redistribution": REDISTRIBUTION,
        "outputs": [os.path.relpath(fac_path, ROOT), os.path.relpath(par_path, ROOT)],
        "fetches": sorted(PROVENANCE.values(), key=lambda r: r["url"]),
    }, indent=2))
    print(f"wrote {PROV} ({len(PROVENANCE)} urls, {LIVE_FETCHES} fetched live this run)")


if __name__ == "__main__":
    sys.exit(main())
