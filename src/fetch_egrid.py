"""EPA eGRID, the US grid emission factors, editions 2018 through 2023.

eGRID is EPA's authoritative electricity emission rate set. It is what turns "company X bought
N MWh" into a defensible location-based Scope 2 number, and it is the only part of this pipeline
that applies to all 503 index members rather than to the ~130 that own reporting facilities.

Outputs:
  data/interim/egrid_subregion.parquet   one row per (eGRID subregion, data year). 27 subregions
                                         from 2019 on, 26 in 2018.
  data/interim/egrid_plant.parquet       one row per (ORIS plant, data year). ORISPL is the same
                                         code CAMD calls Facility ID and EIA calls plantCode, so
                                         this table is the third opinion on any plant where CAMD
                                         has measured CO2 and EIA has generation.
  data/interim/provenance/epa_egrid.json

eGRID2023 rev2, published 2025-06, is the newest edition. There is no eGRID2024 as of 2026-09-12,
so the grid factors run a year and a half behind the CAMD emissions feed.

UNITS. The workbook EPA links first is in US customary units and says "tons" where it means short
tons. Every rate is lb/MWh and every mass is short tons, except CH4 and Hg which are pounds. This
script keeps each published figure under a name that carries its own unit and adds a converted
column beside it:

  lb/MWh    x 0.45359237  = g/kWh        (identical to kg/MWh, which is how EPA's own metric
                                          workbook publishes the same number)
  short ton x 0.90718474  = tonne
  lb        x 0.45359237  = kg

The conversion is checked at runtime against egrid2023_data_metric_rev2.xlsx, EPA's own metric
edition of the same data, so the factor above is verified rather than asserted.

WHICH RATE TO USE. eGRID publishes four families of rate and they are not interchangeable:
  total output    (SRC2ERTA)  all generation in the denominator, including nuclear and renewables.
                              This is the location-based Scope 2 factor. Use this one.
  combustion output (SRC2ECRT) only combusting plants in the denominator. Much higher.
  input           (SRC2ERA)   per MMBtu of fuel burned, not per MWh delivered.
  non-baseload    (SRNBC2E)   the marginal fleet that follows load. Use for avoided emissions from
                              efficiency or demand response, never for an annual Scope 2 total.

The subregion rates are at the generator busbar and exclude transmission and distribution losses,
so a consumption-basis Scope 2 figure needs a grid gross loss factor on top of them.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "epa_egrid"
INTERIM = ROOT / "data" / "interim"
PROV_PATH = INTERIM / "provenance" / "epa_egrid.json"

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"

LB_IN_G = 453.59237
LB_PER_MWH_TO_G_PER_KWH = LB_IN_G / 1000.0
SHORT_TON_IN_TONNES = 0.90718474
LB_IN_KG = LB_IN_G / 1000.0

# PAB Article 12(1)(d) excludes electricity generators above this line. The plant table is where
# the threshold can be read directly off measured data.
PAB_GENERATOR_THRESHOLD_G_PER_KWH = 100.0

# eGRID's own plant fuel categories for plants that burn nothing.
NONCOMBUSTING_FUEL_CATEGORIES = {"SOLAR", "WIND", "HYDRO", "NUCLEAR", "GEOTHERMAL"}

# Every edition is its own workbook and its own URL. Sheet names carry the two-digit data year, so
# SRL23 in egrid2023 and SRL18 in egrid2018. URLs harvested from /egrid/download-data and
# /egrid/historical-egrid-data on 2026-09-12; eGRID2023 rev2 is the newest published edition and
# there is no eGRID2024 yet.
EDITIONS = {
    2018: "https://www.epa.gov/sites/default/files/2020-03/egrid2018_data_v2.xlsx",
    2019: "https://www.epa.gov/sites/default/files/2021-02/egrid2019_data.xlsx",
    2020: "https://www.epa.gov/system/files/documents/2022-09/eGRID2020_Data_v2.xlsx",
    2021: "https://www.epa.gov/system/files/documents/2023-01/eGRID2021_data.xlsx",
    2022: "https://www.epa.gov/system/files/documents/2024-01/egrid2022_data.xlsx",
    2023: "https://www.epa.gov/system/files/documents/2025-06/egrid2023_data_rev2.xlsx",
}
LATEST_YEAR = max(EDITIONS)
METRIC_URL = "https://www.epa.gov/system/files/documents/2025-06/egrid2023_data_metric_rev2.xlsx"

LICENCE = "US federal government work, public domain (17 U.S.C. 105)."
REDISTRIBUTION = (
    "Public domain. We may publish derived numbers, tables and charts, citing EPA Emissions & "
    "Generation Resource Integrated Database (eGRID) and the retrieval date."
)

# eGRID writes "--" where a figure does not exist, most often Hg at plants with no coal. It has to
# stay null; read as a number it would become a zero nobody measured.
NULL_TOKENS = {"--", "", "NA", "N/A", "n/a", "None"}

# eGRID short name -> our column name. Anything absent from an older edition stays null and gets
# counted in the report.
SUBREGION_COLS = {
    "SUBRGN": "subregion_code",
    "SRNAME": "subregion_name",
    "SRNAMEPCAP": "nameplate_capacity_mw",
    "SRNGENAN": "net_generation_mwh",
    "SRNGENNB": "nonbaseload_generation_mwh",
    "SRHTIAN": "heat_input_mmbtu",
    "SRNOXAN": "nox_tons",
    "SRSO2AN": "so2_tons",
    "SRCO2AN": "co2_tons",
    "SRCH4AN": "ch4_lbs",
    "SRN2OAN": "n2o_lbs",
    "SRCO2EQA": "co2e_tons",
    "SRCO2RTA": "co2_rate_lb_per_mwh",
    "SRC2ERTA": "co2e_rate_lb_per_mwh",
    "SRCO2CRT": "co2_combustion_rate_lb_per_mwh",
    "SRC2ECRT": "co2e_combustion_rate_lb_per_mwh",
    "SRCO2RA": "co2_input_rate_lb_per_mmbtu",
    "SRC2ERA": "co2e_input_rate_lb_per_mmbtu",
    "SRNBCO2": "nonbaseload_co2_rate_lb_per_mwh",
    "SRNBC2E": "nonbaseload_co2e_rate_lb_per_mwh",
    "SRCC2ERT": "coal_co2e_rate_lb_per_mwh",
    "SROC2ERT": "oil_co2e_rate_lb_per_mwh",
    "SRGC2ERT": "gas_co2e_rate_lb_per_mwh",
    "SRFSC2ERT": "fossil_co2e_rate_lb_per_mwh",
}

FUELS = {
    "CL": "coal", "OL": "oil", "GS": "gas", "NC": "nuclear", "HY": "hydro", "BM": "biomass",
    "WI": "wind", "SO": "solar", "GT": "geothermal", "OF": "other_fossil", "OP": "other_unknown",
}
MIX_TOTALS = {
    "TN": "nonrenewable", "TR": "renewable", "TH": "nonhydro_renewable",
    "CY": "combustion", "CN": "noncombustion",
}
for _code, _name in FUELS.items():
    SUBREGION_COLS[f"SRGENA{_code}"] = f"gen_{_name}_mwh"
    SUBREGION_COLS[f"SR{_code}PR"] = f"share_{_name}"
for _code, _name in MIX_TOTALS.items():
    SUBREGION_COLS[f"SRGENA{_code}"] = f"gen_{_name}_mwh"
    SUBREGION_COLS[f"SR{_code}PR"] = f"share_{_name}"

PLANT_COLS = {
    "ORISPL": "orispl_code",
    "PNAME": "plant_name",
    "PSTATABB": "state",
    "SUBRGN": "subregion_code",
    "SRNAME": "subregion_name",
    "LAT": "latitude",
    "LON": "longitude",
    "NAMEPCAP": "nameplate_capacity_mw",
    "PLNGENAN": "net_generation_mwh",
    "PLNGENNB": "nonbaseload_generation_mwh",
    "PLCO2AN": "co2_tons",
    "PLCO2EQA": "co2e_tons",
    "PLPRMFL": "primary_fuel",
    "PLFUELCT": "primary_fuel_category",
    "OPRNAME": "operator_name",
    "UTLSRVNM": "utility_name",
    "SECTOR": "sector",
    "BACODE": "balancing_authority_code",
    "BANAME": "balancing_authority_name",
    "NERC": "nerc_region",
    "ISORTO": "iso_rto",
    "CNTYNAME": "county",
    "FIPSST": "fips_state",
    "FIPSCNTY": "fips_county",
    "NUMUNT": "num_units",
    "NUMGEN": "num_generators",
    "COALFLAG": "coal_flag",
    "CHPFLAG": "chp_flag",
    "CAPFAC": "capacity_factor",
    "PLHTIAN": "heat_input_mmbtu",
    "PLHTRT": "heat_rate_btu_per_kwh",
    "PLNOXAN": "nox_tons",
    "PLSO2AN": "so2_tons",
    "PLCH4AN": "ch4_lbs",
    "PLN2OAN": "n2o_lbs",
    "PLCO2RTA": "co2_rate_lb_per_mwh",
    "PLC2ERTA": "co2e_rate_lb_per_mwh",
    "UNCO2SRC": "co2_source",
    "UNC2ESRC": "co2e_source",
}
for _code, _name in FUELS.items():
    PLANT_COLS[f"PLGENA{_code}"] = f"gen_{_name}_mwh"
for _code, _name in MIX_TOTALS.items():
    PLANT_COLS[f"PLGENA{_code}"] = f"gen_{_name}_mwh"

# Columns to convert, as (source, converted, factor).
RATE_CONVERSIONS = [
    ("co2_rate_lb_per_mwh", "co2_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("co2e_rate_lb_per_mwh", "co2e_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("co2_combustion_rate_lb_per_mwh", "co2_combustion_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("co2e_combustion_rate_lb_per_mwh", "co2e_combustion_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("nonbaseload_co2_rate_lb_per_mwh", "nonbaseload_co2_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("nonbaseload_co2e_rate_lb_per_mwh", "nonbaseload_co2e_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("coal_co2e_rate_lb_per_mwh", "coal_co2e_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("oil_co2e_rate_lb_per_mwh", "oil_co2e_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("gas_co2e_rate_lb_per_mwh", "gas_co2e_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("fossil_co2e_rate_lb_per_mwh", "fossil_co2e_rate_g_per_kwh", LB_PER_MWH_TO_G_PER_KWH),
    ("co2_tons", "co2_tonnes", SHORT_TON_IN_TONNES),
    ("co2e_tons", "co2e_tonnes", SHORT_TON_IN_TONNES),
    ("nox_tons", "nox_tonnes", SHORT_TON_IN_TONNES),
    ("so2_tons", "so2_tonnes", SHORT_TON_IN_TONNES),
    ("ch4_lbs", "ch4_kg", LB_IN_KG),
    ("n2o_lbs", "n2o_kg", LB_IN_KG),
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


def fetch(url, dest):
    """Fetch to dest, or reuse dest if it already holds bytes. A second run touches no network."""
    if dest.exists() and dest.stat().st_size > 0:
        record(url, dest, None, from_cache=True)
        return True
    resp = session.get(url, timeout=600)
    if resp.status_code != 200 or not resp.content:
        raise SystemExit(f"fetch failed {resp.status_code} {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    print(f"  fetched {dest.name} ({len(resp.content):,} bytes)")
    record(url, dest, resp.status_code, from_cache=False)
    return True


def download_all():
    jobs = [(url, RAW / f"egrid{year}_data.xlsx") for year, url in sorted(EDITIONS.items())]
    jobs.append((METRIC_URL, RAW / f"egrid{LATEST_YEAR}_data_metric.xlsx"))
    cached = sum(1 for _, d in jobs if d.exists() and d.stat().st_size > 0)
    print(f"raw workbooks: {len(jobs)} wanted, {cached} already cached")
    for url, dest in jobs:
        fetch(url, dest)
    print(f"raw workbooks on disk: {len(jobs)}")


def read_sheet(path, prefix, year):
    """Read one eGRID sheet. The header is on row 2; row 1 holds the long descriptions."""
    wb = load_workbook(path, read_only=True, data_only=True)
    names = [s for s in wb.sheetnames if s.upper().startswith(prefix)]
    if not names:
        wb.close()
        raise SystemExit(f"{path.name} has no {prefix} sheet, only {wb.sheetnames}")
    rows = wb[names[0]].iter_rows(values_only=True)
    next(rows)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    df = pd.DataFrame(list(rows), columns=header).dropna(how="all")
    wb.close()
    df["_data_year"] = year
    return df


def first(df, col):
    """A sheet can carry the same short name twice; the leftmost is the documented one."""
    got = df[col]
    return got.iloc[:, 0] if got.ndim > 1 else got


def check_data_year(df, year, label):
    """The edition year is taken from the file name, so confirm the sheet agrees."""
    if "YEAR" not in df.columns:
        return
    seen = set(pd.to_numeric(df["YEAR"], errors="coerce").dropna().astype(int))
    if seen != {year}:
        print(f"  WARNING: {label} in the {year} workbook carries data years {sorted(seen)}")


def select(df, mapping, year, label):
    """Pull the wanted columns out of a raw eGRID sheet, nulling the sentinels as we go."""
    missing = [src for src in mapping if src not in df.columns]
    if missing:
        print(f"  {label} {year}: {len(missing)} columns absent from this edition: "
              f"{', '.join(sorted(missing))}")
    out = pd.DataFrame(index=df.index)
    for src, dest in mapping.items():
        if src not in df.columns:
            out[dest] = pd.NA
            continue
        out[dest] = first(df, src)
    out["year"] = year
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].where(~out[col].astype(str).str.strip().isin(NULL_TOKENS))
    return out


def to_numeric(df, cols, label):
    """Coerce to float and say how much was lost, so a format change cannot pass unnoticed."""
    for col in cols:
        if col not in df.columns:
            continue
        before = df[col].notna().sum()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        lost = before - df[col].notna().sum()
        if lost:
            print(f"  {label}: {lost:,} values in {col} were not numeric and are now null")
    return df


def add_conversions(df):
    for src, dest, factor in RATE_CONVERSIONS:
        if src in df.columns:
            df[dest] = df[src] * factor
    return df


def build_subregion():
    print("\neGRID subregion table")
    frames = []
    for year, _ in sorted(EDITIONS.items()):
        raw = read_sheet(RAW / f"egrid{year}_data.xlsx", "SRL", year)
        check_data_year(raw, year, "SRL")
        part = select(raw, SUBREGION_COLS, year, "SRL")
        print(f"  SRL {year}: {len(part)} subregions")
        frames.append(part)
    df = pd.concat(frames, ignore_index=True)

    text = {"subregion_code", "subregion_name", "year"}
    df = to_numeric(df, [c for c in df.columns if c not in text], "subregion")
    df = add_conversions(df)

    lead = ["subregion_code", "subregion_name", "year", "co2e_rate_lb_per_mwh",
            "co2e_rate_g_per_kwh", "co2_rate_lb_per_mwh", "co2_rate_g_per_kwh",
            "nonbaseload_co2e_rate_lb_per_mwh", "nonbaseload_co2e_rate_g_per_kwh",
            "net_generation_mwh", "nameplate_capacity_mw"]
    df = df[lead + [c for c in df.columns if c not in lead]]
    df = df.sort_values(["year", "subregion_code"]).reset_index(drop=True)
    print(f"  subregion rows: {len(df):,}")
    return df


def build_plant():
    print("\neGRID plant table")
    frames = []
    for year, _ in sorted(EDITIONS.items()):
        raw = read_sheet(RAW / f"egrid{year}_data.xlsx", "PLNT", year)
        check_data_year(raw, year, "PLNT")
        part = select(raw, PLANT_COLS, year, "PLNT")
        print(f"  PLNT {year}: {len(part):,} plants")
        frames.append(part)
    df = pd.concat(frames, ignore_index=True)

    text = {"plant_name", "state", "subregion_code", "subregion_name", "primary_fuel",
            "primary_fuel_category", "operator_name", "utility_name", "sector",
            "balancing_authority_code", "balancing_authority_name", "nerc_region", "iso_rto",
            "county", "fips_state", "fips_county", "coal_flag", "chp_flag", "co2_source",
            "co2e_source", "year"}
    df = to_numeric(df, [c for c in df.columns if c not in text], "plant")
    df = add_conversions(df)

    df = df.dropna(subset=["orispl_code"])
    df["orispl_code"] = df["orispl_code"].astype("int64")
    dupes = df.duplicated(["orispl_code", "year"]).sum()
    if dupes:
        print(f"  WARNING: {dupes:,} duplicate (orispl_code, year) keys")

    # The regulatory test the whole lane exists for. Null generation stays null rather than
    # defaulting a plant to the clean side of the line.
    df["co2e_rate_g_per_kwh_recomputed"] = (
        df["co2e_tonnes"] * 1e6 / df["net_generation_mwh"].where(df["net_generation_mwh"] > 0) / 1000
    )
    df["above_pab_generator_threshold"] = pd.Series(pd.NA, index=df.index, dtype="boolean")
    known = df["co2e_rate_g_per_kwh"].notna()
    df.loc[known, "above_pab_generator_threshold"] = (
        df.loc[known, "co2e_rate_g_per_kwh"] > PAB_GENERATOR_THRESHOLD_G_PER_KWH
    )

    # eGRID publishes no emission rate for a plant that burns nothing, and it leaves the figure
    # blank rather than writing a zero. Solar, wind, hydro, nuclear and geothermal plants therefore
    # arrive with a null rate that means "no combustion" rather than "unknown". The distinction is
    # recorded here and left for the caller to act on; nothing is filled in.
    df["co2e_rate_basis"] = "not rated"
    df.loc[known, "co2e_rate_basis"] = "published"
    noncombusting = (
        ~known
        & df["primary_fuel_category"].isin(NONCOMBUSTING_FUEL_CATEGORIES)
        & (df["net_generation_mwh"] > 0)
    )
    df.loc[noncombusting, "co2e_rate_basis"] = "no combustion, emissions not reported"

    lead = ["orispl_code", "plant_name", "state", "subregion_code", "latitude", "longitude",
            "nameplate_capacity_mw", "net_generation_mwh", "co2_tons", "co2e_tons", "primary_fuel",
            "year", "co2e_rate_lb_per_mwh", "co2e_rate_g_per_kwh", "co2e_rate_basis",
            "above_pab_generator_threshold"]
    df = df[lead + [c for c in df.columns if c not in lead]]
    df = df.sort_values(["year", "orispl_code"]).reset_index(drop=True)
    print(f"  plant rows: {len(df):,}")
    return df


def verify_units():
    """Check lb/MWh -> g/kWh against EPA's own metric edition of the same numbers."""
    print("\nunit check against EPA's metric workbook")
    us = read_sheet(RAW / f"egrid{LATEST_YEAR}_data.xlsx", "SRL", LATEST_YEAR)
    me = read_sheet(RAW / f"egrid{LATEST_YEAR}_data_metric.xlsx", "SRL", LATEST_YEAR)
    # The two workbooks hold the same figures, so converting one has to land on the other. They
    # differ only by publication rounding: the customary sheet gives six significant figures, so a
    # large subregion rate such as PRMS 1548.53 lb/MWh carries about 2e-5 of relative slack. The
    # check is therefore relative, and 1e-4 is two rounding widths.
    tol = 1e-4
    checks = [("SRC2ERTA", "co2e total output rate", LB_PER_MWH_TO_G_PER_KWH, "g/kWh"),
              ("SRCO2RTA", "co2 total output rate", LB_PER_MWH_TO_G_PER_KWH, "g/kWh"),
              ("SRNBC2E", "co2e non-baseload rate", LB_PER_MWH_TO_G_PER_KWH, "g/kWh"),
              ("SRCO2AN", "co2 mass", SHORT_TON_IN_TONNES, "tonnes"),
              ("SRCH4AN", "ch4 mass", LB_IN_KG, "kg")]
    for col, label, factor, unit in checks:
        # The metric workbook repeats the non-baseload rate in kg/GJ further right; the first
        # column carrying the short name is the one the dictionary describes.
        ours = pd.to_numeric(first(us, col), errors="coerce") * factor
        theirs = pd.to_numeric(first(me, col), errors="coerce")
        gap = (ours - theirs).abs()
        rel = (gap / theirs.where(theirs != 0)).max()
        print(f"  {label:24s} max gap {gap.max():12.6f} {unit:6s} relative {rel:.2e} "
              f"over {ours.notna().sum()} subregions")
        if rel > tol:
            print("  WARNING: conversion does not reproduce EPA's own metric figures")


def national_average():
    """EPA's own US totals sheet, which is the figure to quote rather than a mean of subregions."""
    print("\nUS national totals, from the US sheet of each edition")
    rows = []
    for year in sorted(EDITIONS):
        us = read_sheet(RAW / f"egrid{year}_data.xlsx", "US", year)
        get = lambda c: pd.to_numeric(us[c], errors="coerce").iloc[0] if c in us.columns else float("nan")
        rows.append({
            "year": year,
            "net_generation_mwh": get("USNGENAN"),
            "co2e_rate_lb_per_mwh": get("USC2ERTA"),
            "co2e_rate_g_per_kwh": get("USC2ERTA") * LB_PER_MWH_TO_G_PER_KWH,
            "co2_rate_g_per_kwh": get("USCO2RTA") * LB_PER_MWH_TO_G_PER_KWH,
            "co2e_combustion_rate_g_per_kwh": get("USC2ECRT") * LB_PER_MWH_TO_G_PER_KWH,
        })
    nat = pd.DataFrame(rows)
    print("  year   net gen TWh   CO2e g/kWh   CO2 g/kWh   combustion-only CO2e g/kWh")
    for r in nat.itertuples():
        print(f"  {r.year}   {r.net_generation_mwh / 1e6:10.1f}   {r.co2e_rate_g_per_kwh:10.1f}   "
              f"{r.co2_rate_g_per_kwh:9.1f}   {r.co2e_combustion_rate_g_per_kwh:26.1f}")
    return nat


def report(sub, plant, nat):
    latest_sub = sub[sub["year"] == LATEST_YEAR]
    latest_plant = plant[plant["year"] == LATEST_YEAR]
    nat_latest = nat[nat["year"] == LATEST_YEAR].iloc[0]

    print(f"\neGRID {LATEST_YEAR} sanity checks")
    weighted = (latest_sub["co2e_rate_g_per_kwh"] * latest_sub["net_generation_mwh"]).sum() \
        / latest_sub["net_generation_mwh"].sum()
    print(f"  national average CO2e, EPA US sheet:            "
          f"{nat_latest['co2e_rate_g_per_kwh']:.1f} g/kWh")
    print(f"  same, rebuilt as a generation-weighted mean of the 27 subregions: "
          f"{weighted:.1f} g/kWh")
    print(f"  the two agree to {abs(weighted - nat_latest['co2e_rate_g_per_kwh']):.2f} g/kWh")
    print(f"  brief expected roughly 370 g/kWh; drift "
          f"{100 * (nat_latest['co2e_rate_g_per_kwh'] - 370) / 370:+.1f}%")

    sub_gen = latest_sub["net_generation_mwh"].sum()
    plant_gen = latest_plant["net_generation_mwh"].sum()
    print(f"\n  subregion net generation total: {sub_gen / 1e6:,.1f} TWh")
    print(f"  plant net generation total:     {plant_gen / 1e6:,.1f} TWh "
          f"({100 * plant_gen / sub_gen:.1f}% of the subregion total)")
    print(f"  subregion CO2e: {latest_sub['co2e_tonnes'].sum() / 1e6:,.1f} MMT; "
          f"plant CO2e: {latest_plant['co2e_tonnes'].sum() / 1e6:,.1f} MMT")

    print(f"\n  cleanest and dirtiest subregions, {LATEST_YEAR}")
    ranked = latest_sub.sort_values("co2e_rate_g_per_kwh")
    for r in list(ranked.head(3).itertuples()) + list(ranked.tail(3).itertuples()):
        print(f"    {r.subregion_code:6s} {r.subregion_name[:26]:28s} "
              f"{r.co2e_rate_g_per_kwh:7.1f} g/kWh   {r.net_generation_mwh / 1e6:7.1f} TWh")
    lo = ranked["co2e_rate_g_per_kwh"].min()
    hi = ranked["co2e_rate_g_per_kwh"].max()
    if lo > 0:
        print(f"    spread dirtiest / cleanest: {hi / lo:.1f}x")

    print(f"\n  nulls in the subregion table ({len(sub):,} rows)")
    for col in ["co2e_rate_lb_per_mwh", "nonbaseload_co2e_rate_lb_per_mwh",
                "nonbaseload_generation_mwh", "nameplate_capacity_mw", "share_coal"]:
        print(f"    {col:36s} {sub[col].isna().sum():5,}")

    print(f"\n  nulls in the plant table ({len(plant):,} rows)")
    for col in ["latitude", "net_generation_mwh", "co2e_tons", "co2e_rate_lb_per_mwh",
                "primary_fuel", "subregion_code", "nonbaseload_generation_mwh"]:
        print(f"    {col:36s} {plant[col].isna().sum():5,}")

    print(f"\n  PAB Article 12(1)(d) line at {PAB_GENERATOR_THRESHOLD_G_PER_KWH:.0f} gCO2e/kWh, "
          f"{LATEST_YEAR} plants")
    total_gen = latest_plant["net_generation_mwh"].sum()
    buckets = [
        ("rated above the line",
         latest_plant["above_pab_generator_threshold"].eq(True).fillna(False)),
        ("rated at or below the line",
         latest_plant["above_pab_generator_threshold"].eq(False).fillna(False)),
        ("no combustion, no rate published",
         latest_plant["co2e_rate_basis"] == "no combustion, emissions not reported"),
        ("no rate and no reason to assume one",
         (latest_plant["co2e_rate_basis"] == "not rated")),
    ]
    for label, mask in buckets:
        g = latest_plant.loc[mask, "net_generation_mwh"].sum()
        print(f"    {label:36s} {mask.sum():6,} plants  {g / 1e6:8,.1f} TWh  "
              f"{100 * g / total_gen:5.1f}% of US generation")
    print("    the last bucket is mostly plants with no generation at all, so it carries almost "
          "no MWh")

    # The published rate and the one rebuilt from mass over generation should agree; where they do
    # not, eGRID has applied a CHP or biomass adjustment we would otherwise miss.
    both = latest_plant.dropna(subset=["co2e_rate_g_per_kwh", "co2e_rate_g_per_kwh_recomputed"])
    rel = ((both["co2e_rate_g_per_kwh_recomputed"] - both["co2e_rate_g_per_kwh"]).abs()
           / both["co2e_rate_g_per_kwh"].where(both["co2e_rate_g_per_kwh"] > 0))
    print(f"\n  published plant rate vs CO2e/generation rebuilt here: {len(both):,} plants, "
          f"median relative gap {rel.median():.2%}, {(rel > 0.01).sum():,} above 1%")

    # EPA/CAPD means the CO2 came off a Part 75 stack monitor, the same instrument feed the CAMD
    # lane reads. Those plants are where eGRID, CAMD and EIA can be checked against each other.
    print("\n  where the plant CO2 came from, eGRID's own flag")
    for k, v in latest_plant["co2_source"].value_counts(dropna=False).items():
        g = latest_plant.loc[latest_plant["co2_source"].eq(k)
                             if pd.notna(k) else latest_plant["co2_source"].isna(),
                             "net_generation_mwh"].sum()
        print(f"    {str(k):16s} {v:6,} plants  {g / 1e6:8,.1f} TWh")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    PROV_PATH.parent.mkdir(parents=True, exist_ok=True)
    load_existing_provenance()

    download_all()
    sub = build_subregion()
    plant = build_plant()
    verify_units()
    nat = national_average()
    report(sub, plant, nat)

    sub_path = INTERIM / "egrid_subregion.parquet"
    plant_path = INTERIM / "egrid_plant.parquet"
    sub.to_parquet(sub_path, index=False)
    plant.to_parquet(plant_path, index=False)
    PROV_PATH.write_text(json.dumps(list(provenance.values()), indent=2) + "\n")

    print(f"\nwrote {sub_path} ({len(sub):,} rows, {len(sub.columns)} cols)")
    print(f"wrote {plant_path} ({len(plant):,} rows, {len(plant.columns)} cols)")
    print(f"wrote {PROV_PATH} ({len(provenance)} urls)")


if __name__ == "__main__":
    sys.exit(main())
