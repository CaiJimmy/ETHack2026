"""EPA Clean Air Markets (CAMD) Part 75 unit emissions, 2010 through 2026 year to date.

Part 75 CO2 comes off certified stack monitors, is QA'd by EPA and publishes within weeks of the
quarter closing, so this is the only measured, company-attributable emissions series that reaches
2025 and 2026. GHGRP stops at reporting year 2023.

Outputs:
  data/interim/camd_unit_year.parquet        one row per (ORIS facility, unit, year)
  data/interim/camd_unit_quarter.parquet     same units by quarter, 2024 on, for like-for-like YTD
  data/interim/oris_ghgrp_crosswalk.parquet  ORIS code -> GHGRP facility id, one row per pair
  data/interim/provenance/epa_camd.json

The unit table carries no ticker, because CAMD knows nothing about listed parents. Its key is
oris_code; the crosswalk carries that to a GHGRP facility id, and the GHGRP lane carries the
facility id to a parent company and a ticker. Do not try to reach a ticker through CAMD's own
Owner/Operator field: it names the operating subsidiary (Alabama Power Company), not the listed
parent (Southern Company).

Needs a CAM API key in CAMD_API_KEY. The devshell sources .env, so a plain run picks it up. A free
personal key takes a minute at https://www.epa.gov/power-sector/cam-api-portal#/api-key-signup.
DEMO_KEY is the documented fallback but is shared across every anonymous caller on this IP and gets
throttled to a handful of calls a day, which is not enough for 27 requests.
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "epa_camd"
INTERIM = ROOT / "data" / "interim"
PROV_PATH = INTERIM / "provenance" / "epa_camd.json"

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
API_KEY = os.environ.get("CAMD_API_KEY", "DEMO_KEY")

FIRST_YEAR, LAST_YEAR = 2010, 2026
QUARTERLY_FROM = 2024

ANNUAL_URL = "https://api.epa.gov/easey/streaming-services/emissions/apportioned/annual"
QUARTERLY_URL = "https://api.epa.gov/easey/streaming-services/emissions/apportioned/quarterly"
FACILITY_URL = "https://api.epa.gov/easey/bulk-files/facility/facility-{year}.csv"
CROSSWALK_URL = (
    "https://www.epa.gov/system/files/documents/2022-04/"
    "ghgrp_oris_power_plant_crosswalk_12_13_21.xlsx"
)

LICENCE = "US federal government work, public domain (17 U.S.C. 105)."
REDISTRIBUTION = (
    "Public domain. We may publish derived numbers, tables and charts, citing EPA Clean Air Markets "
    "Division and the retrieval date."
)

SHORT_TON_IN_TONNES = 0.90718474

# The streaming service answers x-ratelimit-limit: 1 and starts returning 429 OVER_RATE_LIMIT after
# two or three calls in quick succession, even on a personal key. One call every two seconds with a
# backoff behind it gets all 27 files in a couple of minutes and stays well inside what EPA asks for.
PAUSE = 2.0
RETRY_STATUSES = (429, 500, 502, 503, 504)
BACKOFF = (10, 20, 40, 60, 90)
MAX_ATTEMPTS = len(BACKOFF) + 1

# Measured by the research scout on 2026-09-12 off this same endpoint. A large drift means the feed
# moved under us and the run needs a look rather than a slide.
EXPECTED_2025_MSHORT_TONS = 1635.1

# The annual and quarterly feeds carry "Unit ID" (the reported unit name, which is what the facility
# bulk file also uses) and "unit_id" (CAMD's internal surrogate). Both are kept, under names that do
# not collide.
EMISSION_COLS = {
    "State": "state",
    "Facility Name": "facility_name",
    "Facility ID": "oris_code",
    "Unit ID": "unit_id",
    "unit_id": "camd_unit_key",
    "Associated Stacks": "associated_stacks",
    "Year": "year",
    "Quarter": "quarter",
    "Operating Time Count": "operating_time_count",
    "Sum of the Operating Time": "operating_time_hours",
    "Gross Load (MWh)": "gross_load_mwh",
    "Steam Load (1000 lb)": "steam_load_1000lb",
    "SO2 Mass (short tons)": "so2_short_tons",
    "CO2 Mass (short tons)": "co2_short_tons",
    "NOx Mass (short tons)": "nox_short_tons",
    "Heat Input (mmBtu)": "heat_input_mmbtu",
    "Primary Fuel Type": "primary_fuel_type",
    "Secondary Fuel Type": "secondary_fuel_type",
    "Unit Type": "unit_type",
    "Program Code": "program_code",
}

FACILITY_COLS = {
    "Facility ID": "oris_code",
    "Unit ID": "unit_id",
    "Year": "year",
    "Owner/Operator": "owner_operator",
    "Source Category": "source_category",
    "Operating Status": "operating_status",
    "NERC Region": "nerc_region",
    "County": "county",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Commercial Operation Date": "commercial_operation_date",
    "Associated Generators & Nameplate Capacity (MWe)": "generators_nameplate_mwe",
}

CROSSWALK_SHEET = "ORIS Crosswalk"
ORIS_SLOT_COLS = ["ORIS CODE", "ORIS CODE 2", "ORIS CODE 3", "ORIS CODE 4", "ORIS CODE 5"]

UNIT_YEAR_ORDER = [
    "oris_code", "unit_id", "camd_unit_key", "facility_name", "state", "year",
    "co2_short_tons", "co2_tonnes", "heat_input_mmbtu",
    "operating_time_hours", "operating_time_count", "gross_load_mwh", "steam_load_1000lb",
    "so2_short_tons", "nox_short_tons",
    "primary_fuel_type", "secondary_fuel_type", "unit_type", "program_code", "associated_stacks",
    "owner_operator", "source_category", "operating_status", "nerc_region", "county",
    "latitude", "longitude", "commercial_operation_date", "generators_nameplate_mwe",
    "is_partial_year", "dq",
]

session = requests.Session()
session.headers.update({"User-Agent": UA})

provenance = {}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_existing_provenance():
    if not PROV_PATH.exists():
        return
    try:
        for rec in json.loads(PROV_PATH.read_text()):
            provenance[rec["url"]] = rec
    except (ValueError, KeyError):
        pass


def record(url, dest, http_status, from_cache):
    blob = dest.read_bytes()
    prior = provenance.get(url, {})
    provenance[url] = {
        "url": url,
        "retrieved_at": prior.get("retrieved_at") if from_cache and prior else now_iso(),
        "http_status": prior.get("http_status") if from_cache and prior else http_status,
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "local_path": str(dest.relative_to(ROOT)),
        "licence": LICENCE,
        "redistribution": REDISTRIBUTION,
        "served_from_cache_this_run": from_cache,
    }


def record_miss(url, http_status, note):
    provenance[url] = {
        "url": url,
        "retrieved_at": now_iso(),
        "http_status": http_status,
        "bytes": 0,
        "sha256": None,
        "local_path": None,
        "licence": LICENCE,
        "redistribution": REDISTRIBUTION,
        "served_from_cache_this_run": False,
        "note": note,
    }


def fetch(url, dest, params=None, accept=None, optional=False, pause=PAUSE):
    """Fetch to dest, or reuse dest if it already holds bytes. A second run touches no network.

    Returns True on a body, False when the URL is genuinely not published (400/404) and optional.
    """
    shown = url
    if params:
        # The key never reaches provenance; a personal key would leak into a reviewed file.
        masked = {k: ("<api_key>" if k == "api_key" else v) for k, v in params.items()}
        shown = url + "?" + "&".join(f"{k}={v}" for k, v in masked.items())

    # The cache counts only when provenance can say where the bytes came from. A file on disk with
    # no recorded status is refetched rather than passed off as attested.
    prior = provenance.get(shown, {})
    if dest.exists() and dest.stat().st_size > 0 and prior.get("http_status") == 200:
        record(shown, dest, None, from_cache=True)
        return True

    # A quarter that has not been published yet stays a recorded miss, so a second run does not go
    # back to the network to be told the same thing. A throttled call is not a miss and is retried.
    if optional and prior.get("http_status") in (400, 404):
        return False

    headers = {"Accept": accept} if accept else {}
    for attempt in range(MAX_ATTEMPTS):
        resp = session.get(url, params=params, headers=headers, timeout=600)
        time.sleep(pause)
        if resp.status_code == 200 and resp.content:
            break
        if resp.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
            wait = BACKOFF[attempt]
            print(f"  wait    {dest.name}: HTTP {resp.status_code}, retrying in {wait}s")
            time.sleep(wait)
            continue
        if optional and resp.status_code in (400, 404):
            print(f"  skip    {dest.name}: HTTP {resp.status_code} not published")
            record_miss(shown, resp.status_code, "not published at this URL")
            return False
        raise SystemExit(f"fetch failed {resp.status_code} {shown}\n{resp.text[:400]}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    print(f"  fetched {dest.name} ({len(resp.content):,} bytes)")
    record(shown, dest, resp.status_code, from_cache=False)
    return True


def read_emissions_csv(path):
    head = pd.read_csv(path, nrows=0)
    usecols = [c for c in EMISSION_COLS if c in head.columns]
    df = pd.read_csv(path, usecols=usecols, dtype={"Unit ID": str, "Facility ID": "Int64"})
    df = df.rename(columns={c: EMISSION_COLS[c] for c in usecols})
    df["unit_id"] = df["unit_id"].str.strip()
    return df


def fetch_annual():
    print(f"CAMD annual apportioned emissions, {FIRST_YEAR}-{LAST_YEAR}")
    frames = []
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        dest = RAW / f"annual_{year}.csv"
        if not fetch(ANNUAL_URL, dest, params={"api_key": API_KEY, "year": year},
                     accept="text/csv", optional=True):
            continue
        df = read_emissions_csv(dest)
        print(f"  {year}: {len(df):,} unit rows, {df['oris_code'].nunique():,} ORIS facilities")
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    print(f"  annual unit-year rows: {len(out):,}")
    return out


def fetch_quarterly():
    print(f"CAMD quarterly apportioned emissions, {QUARTERLY_FROM}-{LAST_YEAR}")
    frames = []
    partial_years = set()
    for year in range(QUARTERLY_FROM, LAST_YEAR + 1):
        for q in (1, 2, 3, 4):
            dest = RAW / f"quarterly_{year}q{q}.csv"
            if not fetch(QUARTERLY_URL, dest,
                         params={"api_key": API_KEY, "year": year, "quarter": q},
                         accept="text/csv", optional=True):
                partial_years.add(year)
                continue
            frames.append(read_emissions_csv(dest))
    out = pd.concat(frames, ignore_index=True)
    out["co2_tonnes"] = out["co2_short_tons"] * SHORT_TON_IN_TONNES
    for year, n in out.groupby("year")["quarter"].nunique().items():
        print(f"  {year}: {n} quarters published")
    print(f"  quarterly unit rows: {len(out):,}")
    return out, partial_years


def fetch_facility_attributes():
    """Owner/operator, location and status, from the keyless bulk facility files."""
    print(f"CAMD facility attributes, {FIRST_YEAR}-{LAST_YEAR}")
    frames = []
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        dest = RAW / f"facility_{year}.csv"
        if not fetch(FACILITY_URL.format(year=year), dest, optional=True, pause=0.5):
            continue
        head = pd.read_csv(dest, nrows=0)
        usecols = [c for c in FACILITY_COLS if c in head.columns]
        df = pd.read_csv(dest, usecols=usecols, dtype={"Unit ID": str, "Facility ID": "Int64"})
        frames.append(df.rename(columns={c: FACILITY_COLS[c] for c in usecols}))
    fac = pd.concat(frames, ignore_index=True)
    fac["unit_id"] = fac["unit_id"].astype(str).str.strip()
    print(f"  facility unit-year rows: {len(fac):,}")

    # One unit can appear once per program it is enrolled in (ARP, CSAPR, MATS), so the raw file has
    # the same key several times with identical attributes.
    dupes = fac.duplicated(["oris_code", "unit_id", "year"]).sum()
    if dupes:
        print(f"  dropping {dupes:,} repeated facility keys (same unit, several programs)")
        fac = fac.drop_duplicates(["oris_code", "unit_id", "year"])
    print(f"  distinct facility unit-years: {len(fac):,}")
    print(f"  null owner_operator: {fac['owner_operator'].isna().sum():,}")
    return fac


def build_unit_year(annual, fac, partial_years):
    dupes = annual.duplicated(["oris_code", "unit_id", "year"]).sum()
    if dupes:
        print(f"  WARNING: {dupes:,} duplicate (oris_code, unit_id, year) keys in the annual feed")

    df = annual.merge(fac, on=["oris_code", "unit_id", "year"], how="left", indicator=True)
    matched = (df["_merge"] == "both").sum()
    print(f"  emissions rows carrying facility attributes: {matched:,}/{len(df):,}")
    df = df.drop(columns="_merge")

    df["co2_tonnes"] = df["co2_short_tons"] * SHORT_TON_IN_TONNES

    # A year is partial when the quarterly feed refuses one of its quarters as not yet published.
    # Years before the quarterly pull window are historical and complete.
    df["is_partial_year"] = df["year"].isin(partial_years)
    print(f"  years flagged partial: {sorted(partial_years) or 'none'}")

    # Part 75 CO2 comes off a certified continuous monitor that EPA QA's, so it is PCAF 1 where
    # present. A minority of small units report Appendix G fuel-flow calculations instead, which
    # would be a 2, and the feed does not say which is which. Nothing is filled where CO2 is
    # missing: those rows keep a null dq and are counted in the report below.
    df["dq"] = pd.Series(pd.NA, index=df.index, dtype="Int8")
    df.loc[df["co2_short_tons"].notna(), "dq"] = 1

    df = df[UNIT_YEAR_ORDER].sort_values(["year", "oris_code", "unit_id"]).reset_index(drop=True)
    return df


def build_crosswalk():
    print("GHGRP-ORIS power plant crosswalk")
    dest = RAW / "ghgrp_oris_power_plant_crosswalk_12_13_21.xlsx"
    fetch(CROSSWALK_URL, dest)

    wb = load_workbook(dest, read_only=True, data_only=True)
    rows = wb[CROSSWALK_SHEET].iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    wide = pd.DataFrame(list(rows), columns=header).dropna(how="all")
    wb.close()
    print(f"  crosswalk facility rows: {len(wide):,}")

    # A GHGRP facility can host up to five ORIS plants, spread across five columns. Long form makes
    # the join from a CAMD unit one merge instead of five.
    long = wide.melt(
        id_vars=["GHGRP Facility ID", "FACILITY NAME", "GHGRP - City", "GHGRP - State",
                 "GHGRP - Power Plant Sector"],
        value_vars=ORIS_SLOT_COLS,
        var_name="oris_slot",
        value_name="oris_code",
    )
    kept = long.dropna(subset=["oris_code"])
    no_oris = wide["GHGRP Facility ID"].nunique() - kept["GHGRP Facility ID"].nunique()
    print(f"  crosswalk facilities carrying no ORIS code: {no_oris:,}")
    long = kept.rename(columns={
        "GHGRP Facility ID": "ghgrp_facility_id",
        "FACILITY NAME": "facility_name",
        "GHGRP - City": "city",
        "GHGRP - State": "state",
    })
    # The source column holds "Yes" or a blank, so it reads better as a flag.
    long["is_power_plant"] = (
        long["GHGRP - Power Plant Sector"].fillna("").astype(str).str.strip().str.lower().eq("yes")
    )
    long = long.drop(columns=["GHGRP - Power Plant Sector"])
    long["oris_code"] = pd.to_numeric(long["oris_code"], errors="coerce")
    long = long.dropna(subset=["oris_code"])
    long["oris_code"] = long["oris_code"].astype("int64")
    long["ghgrp_facility_id"] = pd.to_numeric(long["ghgrp_facility_id"]).astype("int64")
    long["oris_slot"] = (
        long["oris_slot"].str.replace("ORIS CODE", "", regex=False)
        .str.strip().replace("", "1").astype(int)
    )
    long = long.sort_values(["ghgrp_facility_id", "oris_slot"]).reset_index(drop=True)

    print(f"  facility-to-ORIS pairs: {len(long):,}")
    print(f"  pairs flagged power plant sector: {long['is_power_plant'].sum():,}")
    print(f"  distinct GHGRP facility ids: {long['ghgrp_facility_id'].nunique():,}")
    print(f"  distinct ORIS codes: {long['oris_code'].nunique():,}")
    per_fac = long.groupby("ghgrp_facility_id").size()
    print(f"  GHGRP facilities holding more than one ORIS code: {(per_fac > 1).sum():,}")
    per_oris = long.groupby("oris_code").size()
    print(f"  ORIS codes claimed by more than one GHGRP facility: {(per_oris > 1).sum():,}")
    return long


def report(df, quarterly, xwalk):
    print("\nunit-year table")
    print(f"  rows: {len(df):,}")
    print(f"  years: {df['year'].min()}-{df['year'].max()}")
    print(f"  distinct ORIS facilities: {df['oris_code'].nunique():,}")
    print(f"  distinct facility-units: {df.groupby(['oris_code', 'unit_id']).ngroups:,}")
    print(f"  null co2_short_tons: {df['co2_short_tons'].isna().sum():,}")
    print(f"  null heat_input_mmbtu: {df['heat_input_mmbtu'].isna().sum():,}")
    print(f"  null owner_operator: {df['owner_operator'].isna().sum():,}")
    print(f"  dq=1 (measured, reported): {(df['dq'] == 1).sum():,}")

    print("\n  year     rows  facilities  CO2 M short tons  CO2 MMT  heat input M mmBtu")
    for year, g in df.groupby("year"):
        mark = " (partial)" if bool(g["is_partial_year"].iloc[0]) else ""
        print(f"  {year}  {len(g):7,}  {g['oris_code'].nunique():9,}  "
              f"{g['co2_short_tons'].sum() / 1e6:15.1f}  {g['co2_tonnes'].sum() / 1e6:7.1f}  "
              f"{g['heat_input_mmbtu'].sum() / 1e6:17.1f}{mark}")

    y25 = df[df["year"] == 2025]
    if y25.empty:
        print("\n  WARNING: no 2025 rows, the sanity check against the verified total cannot run")
        return
    total25 = y25["co2_short_tons"].sum() / 1e6
    drift = 100 * (total25 - EXPECTED_2025_MSHORT_TONS) / EXPECTED_2025_MSHORT_TONS
    print(f"\n  2025 measured CO2: {total25:,.1f} M short tons = "
          f"{y25['co2_tonnes'].sum() / 1e6:,.1f} MMT")
    print(f"  research report said {EXPECTED_2025_MSHORT_TONS} M short tons, drift {drift:+.2f}%")
    if abs(drift) > 2:
        print("  WARNING: 2025 total is more than 2% off the verified figure")

    codes = set(xwalk["oris_code"])
    in_x = y25[y25["oris_code"].isin(codes)]
    print(f"\n  2025 ORIS facilities present in the crosswalk: "
          f"{in_x['oris_code'].nunique():,}/{y25['oris_code'].nunique():,}")
    print(f"  2025 CO2 reachable through the crosswalk: "
          f"{100 * in_x['co2_short_tons'].sum() / y25['co2_short_tons'].sum():.1f}%")

    # Like-for-like: compare only the quarters the newest year has actually published.
    latest = int(quarterly["year"].max())
    qs = sorted(quarterly.loc[quarterly["year"] == latest, "quarter"].unique())
    ytd = quarterly[quarterly["quarter"].isin(qs)]
    print(f"\n  same-period comparison, Q{qs[0]}-Q{qs[-1]} only")
    base = None
    for year, g in ytd.groupby("year"):
        mt = g["co2_short_tons"].sum() / 1e6
        chg = "" if base is None else f"  {100 * (mt - base) / base:+.1f}% vs {latest - 1}"
        if year == latest - 1:
            base = mt
        print(f"  {year}: {mt:,.1f} M short tons from {g['oris_code'].nunique():,} facilities{chg}")

    print("\n  top owner/operator strings by 2025 CO2 (operating subsidiaries, not parents)")
    top = (y25.groupby("owner_operator")["co2_short_tons"].sum()
           .sort_values(ascending=False).head(10))
    for name, tons in top.items():
        print(f"    {tons / 1e6:7.1f} M short tons  {str(name)[:80]}")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    PROV_PATH.parent.mkdir(parents=True, exist_ok=True)
    load_existing_provenance()
    if API_KEY == "DEMO_KEY":
        print("no CAMD_API_KEY in the environment, falling back to DEMO_KEY; expect throttling")

    annual = fetch_annual()
    quarterly, partial_years = fetch_quarterly()
    fac = fetch_facility_attributes()
    df = build_unit_year(annual, fac, partial_years)
    xwalk = build_crosswalk()
    report(df, quarterly, xwalk)

    unit_path = INTERIM / "camd_unit_year.parquet"
    quarter_path = INTERIM / "camd_unit_quarter.parquet"
    xwalk_path = INTERIM / "oris_ghgrp_crosswalk.parquet"
    df.to_parquet(unit_path, index=False)
    quarterly.to_parquet(quarter_path, index=False)
    xwalk.to_parquet(xwalk_path, index=False)

    PROV_PATH.write_text(json.dumps(list(provenance.values()), indent=2) + "\n")
    print(f"\nwrote {unit_path} ({len(df):,} rows)")
    print(f"wrote {quarter_path} ({len(quarterly):,} rows)")
    print(f"wrote {xwalk_path} ({len(xwalk):,} rows)")
    print(f"wrote {PROV_PATH} ({len(provenance)} urls)")


if __name__ == "__main__":
    sys.exit(main())
