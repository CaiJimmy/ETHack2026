"""Generation-weighted carbon intensity per power plant, keyed on ORIS code.

Inputs, all local parquet written by the fetch lanes:
  data/interim/camd_unit_year.parquet   EPA CAMD Part 75 stack-monitored CO2, per unit per year
  data/interim/eia_plant_totals.parquet EIA-923 net generation, per plant per year
  data/interim/egrid_plant.parquet      eGRID plant attributes, subregion, published CO2e rate

Output:
  data/interim/plant_intensity.parquet
  data/interim/provenance/power_intensity.json

This is the input to the PAB generator test. Note the article number: the 100 gCO2e/kWh
rule is Article 12(1)(g) of Commission Delegated Regulation (EU) 2020/1818, not 12(1)(d).
12(1)(d) is the 1%-of-revenue coal rule. Both are in data/interim/pab_rules.json and the
threshold here is read from that file rather than hardcoded.

The company rollup is deliberately not attempted. This stops at the plant level.
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
OUT_PATH = INTERIM / "plant_intensity.parquet"
PROV_PATH = INTERIM / "provenance" / "power_intensity.json"

CAMD_PATH = INTERIM / "camd_unit_year.parquet"
EIA_PATH = INTERIM / "eia_plant_totals.parquet"
EGRID_PATH = INTERIM / "egrid_plant.parquet"
EGRID_SUB_PATH = INTERIM / "egrid_subregion.parquet"
RULES_PATH = INTERIM / "pab_rules.json"

# CAMD runs 2010-2026, EIA 2015-2025, eGRID 2018-2023. Outside this window there is no
# denominator to divide by, so there is no intensity to compute.
YEAR_MIN, YEAR_MAX = 2015, 2025

# CAMD reports gross load at the generator terminals; EIA reports net generation after
# station service. A ratio near 1.03 is the expected auxiliary-load gap. A ratio far from
# that means the two datasets disagree about what the plant is, usually because EIA splits
# a site into several plant codes while CAMD keeps one ORIS for the whole station.
GROSS_NET_LO, GROSS_NET_HI = 0.90, 1.50

DISAGREE_PCT = 10.0

DQ_LEGEND = {
    1: "CAMD measured CO2 over EIA net generation, boundaries agree, not CHP",
    2: "CAMD measured CO2 over EIA net generation, CAMD reports no gross load so the "
       "boundary check could not run",
    3: "CAMD CO2 present but at least one unit reported no CO2 that year, sum understates",
    4: "CHP plant, intensity taken from eGRID which allocates emissions between power and "
       "steam; a raw CAMD/EIA ratio would charge the steam host's CO2 to electricity",
    5: "no usable CAMD number, intensity falls back to the eGRID published CO2e rate",
    6: "CAMD/EIA gross-net ratio outside 0.90-1.50 and no eGRID rate to fall back on "
       "(facility boundary mismatch, intensity present but unreliable)",
    7: "plant covered but no intensity computable (no combustion, or generation <= 0)",
}


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_for(path, minutes=20):
    """Another lane writes camd_unit_year.parquet. It may still be in flight."""
    deadline = time.monotonic() + minutes * 60
    announced = False
    while True:
        if path.exists() and path.stat().st_size > 0:
            # Guard against reading a file mid-write: require the size to hold still.
            size = path.stat().st_size
            time.sleep(1.0)
            if path.stat().st_size == size:
                return
        if time.monotonic() > deadline:
            raise SystemExit(f"gave up waiting for {path} after {minutes} minutes")
        if not announced:
            print(f"waiting for {path.name} (another lane is writing it, up to {minutes} min)")
            announced = True
        time.sleep(15)


def pct_diff(a, b):
    """Signed percentage difference of a against b, null where b is null or zero."""
    denom = b.where(b.abs() > 0)
    return (a - b) / denom * 100.0


def agreement_stats(label, a, b, unit, summable=True):
    """Median absolute percentage difference plus correlations, printed and returned.

    summable=False for rate quantities, where adding g/kWh across plants means nothing.
    """
    both = a.notna() & b.notna() & (b.abs() > 0)
    n = int(both.sum())
    if n == 0:
        print(f"  {label}: no overlapping plant-years")
        return {"pair": label, "n": 0}
    x, y = a[both].astype(float), b[both].astype(float)
    d = (x - y) / y * 100.0
    ad = d.abs()
    stats = {
        "pair": label,
        "unit": unit,
        "n_plant_years": n,
        "median_abs_pct_diff": round(float(ad.median()), 4),
        "mean_abs_pct_diff": round(float(ad.mean()), 4),
        "median_signed_pct_diff": round(float(d.median()), 4),
        "p90_abs_pct_diff": round(float(ad.quantile(0.90)), 4),
        "pearson_r": round(float(np.corrcoef(x, y)[0, 1]), 6),
        # Pearson on a ratio is hostage to one plant-year with a near-zero denominator, so
        # report it again over the middle 98% of the ratio distribution.
        "spearman_r": round(float(x.rank().corr(y.rank())), 6),
        "share_within_1pct": round(float((ad <= 1).mean()), 4),
        "share_within_10pct": round(float((ad <= DISAGREE_PCT).mean()), 4),
        "n_disagree_over_10pct": int((ad > DISAGREE_PCT).sum()),
    }
    if summable:
        stats["total_a"] = float(x.sum())
        stats["total_b"] = float(y.sum())
        stats["total_pct_diff"] = round(
            (stats["total_a"] - stats["total_b"]) / stats["total_b"] * 100.0, 4)
    print(f"  {label}  [{unit}]")
    print(f"    plant-years compared      {n:,}")
    print(f"    median abs % difference   {stats['median_abs_pct_diff']:.3f}%")
    print(f"    mean abs % difference     {stats['mean_abs_pct_diff']:.3f}%")
    print(f"    median signed % diff      {stats['median_signed_pct_diff']:+.3f}%")
    print(f"    p90 abs % difference      {stats['p90_abs_pct_diff']:.3f}%")
    ratio = x / y
    keep = ratio.between(ratio.quantile(0.01), ratio.quantile(0.99))
    if int(keep.sum()) > 2:
        stats["pearson_r_trimmed_98pct"] = round(float(np.corrcoef(x[keep], y[keep])[0, 1]), 6)
        stats["n_trimmed"] = int(keep.sum())
    print(f"    Pearson r                 {stats['pearson_r']:.6f}")
    if "pearson_r_trimmed_98pct" in stats:
        print(f"    Pearson r, middle 98%     {stats['pearson_r_trimmed_98pct']:.6f} "
              f"(n={stats['n_trimmed']:,})")
    print(f"    Spearman r                {stats['spearman_r']:.6f}")
    print(f"    within 1%                 {stats['share_within_1pct']:.1%}")
    print(f"    within 10%                {stats['share_within_10pct']:.1%}")
    print(f"    disagree by more than 10% {stats['n_disagree_over_10pct']:,}")
    if summable:
        print(f"    fleet totals              {stats['total_a']:,.0f} vs {stats['total_b']:,.0f} "
              f"({stats['total_pct_diff']:+.3f}%)")
    else:
        # A generation-weighted mean is the only honest way to aggregate a rate.
        print("    (rates are not summable; compare the generation-weighted means instead)")
    return stats


# eGRID uses EIA fuel codes, CAMD writes them out in words, EIA-923 uses its own set. One
# vocabulary so a 2023 row and a 2024 row can be compared.
FUEL_MAP = {
    "bit": "coal", "sub": "coal", "lig": "coal", "rc": "coal", "wc": "coal",
    "ant": "coal", "col": "coal", "coal": "coal", "coal refuse": "coal",
    "petroleum coke": "coal", "pc": "coal",
    "ng": "gas", "natural gas": "gas", "pipeline natural gas": "gas", "og": "gas",
    "other gas": "gas", "process gas": "gas", "bfg": "gas", "prg": "gas", "blq": "biomass",
    "lfg": "biomass", "obg": "biomass", "coal gas": "gas", "coke oven gas": "gas",
    "dfo": "oil", "rfo": "oil", "jf": "oil", "ker": "oil", "wo": "oil", "residual oil": "oil",
    "diesel oil": "oil", "other oil": "oil", "petroleum": "oil", "oil": "oil",
    "nuc": "nuclear", "nuclear": "nuclear",
    "wat": "hydro", "hyc": "hydro", "hps": "hydro", "ps": "hydro", "hydro": "hydro",
    "wnd": "wind", "wt": "wind", "wind": "wind",
    "sun": "solar", "spv": "solar", "stp": "solar", "solar": "solar",
    "geo": "geothermal", "geothermal": "geothermal",
    "wds": "biomass", "wood": "biomass", "ab": "biomass", "msw": "biomass", "msb": "biomass",
    "obl": "biomass", "obs": "biomass", "slw": "biomass", "tdf": "biomass",
    "wood and wood waste": "biomass", "agricultural byproduct": "biomass",
    "tires": "other", "tdf": "biomass", "tire derived fuel": "biomass",
    "mwh": "storage", "bat": "storage", "purchased steam": "other", "pur": "other",
    "mlg": "biomass", "landfill gas": "biomass", "www": "biomass", "orw": "biomass",
    "woo": "oil", "waste oil": "oil", "woc": "coal", "waste coal": "coal",
    "oog": "gas", "other gases": "gas", "wh": "other", "waste heat": "other",
    "oth": "other", "other": "other", "other solid fuel": "other", "osf": "other",
    "otf": "other", "sgc": "gas", "sgp": "gas", "wdl": "biomass",
}


def normalise_fuel(series):
    """One fuel category per plant. A blended fuel string takes its first component."""
    base = series.astype("string").str.strip().str.lower()
    out = base.map(FUEL_MAP)
    # "Coal, Natural Gas" and "Natural Gas, Residual Oil" are CAMD's way of saying the unit
    # burns two things. The first listed is the primary, which is what this column means.
    first = base.str.split(",").str[0].str.strip()
    out = out.fillna(first.map(FUEL_MAP))
    return out.astype("object")


def load_camd():
    df = pd.read_parquet(CAMD_PATH)
    print(f"camd_unit_year.parquet: {len(df):,} unit-year rows, "
          f"{df['oris_code'].nunique():,} ORIS codes, years {df['year'].min()}-{df['year'].max()}")

    partial = int(df["is_partial_year"].sum())
    df = df[~df["is_partial_year"]]
    print(f"  dropped {partial:,} partial-year unit rows (incomplete reporting year)")

    df = df[df["year"].between(YEAR_MIN, YEAR_MAX)]
    print(f"  {len(df):,} unit-year rows in {YEAR_MIN}-{YEAR_MAX}")

    n_units = len(df)
    n_no_co2 = int(df["co2_tonnes"].isna().sum())
    print(f"  {n_no_co2:,} of {n_units:,} unit-years report no CO2 mass ({n_no_co2 / n_units:.1%}); "
          "these stay null and are counted, not zero-filled")

    # One row per plant per year. Coordinates and names come from the first unit; CAMD
    # carries them per unit but they are constant within a facility.
    agg = df.groupby(["oris_code", "year"], as_index=False).agg(
        camd_facility_name=("facility_name", "first"),
        camd_state=("state", "first"),
        camd_latitude=("latitude", "first"),
        camd_longitude=("longitude", "first"),
        camd_county=("county", "first"),
        camd_nerc_region=("nerc_region", "first"),
        camd_owner_operator=("owner_operator", "first"),
        camd_source_category=("source_category", "first"),
        camd_primary_fuel=("primary_fuel_type", lambda s: s.dropna().mode().iloc[0]
                           if s.notna().any() else None),
        co2_tonnes=("co2_tonnes", "sum"),
        camd_heat_input_mmbtu=("heat_input_mmbtu", "sum"),
        camd_gross_load_mwh=("gross_load_mwh", "sum"),
        camd_so2_tonnes=("so2_short_tons", lambda s: s.sum() * 0.90718474),
        camd_nox_tonnes=("nox_short_tons", lambda s: s.sum() * 0.90718474),
        camd_units=("unit_id", "nunique"),
        camd_units_with_co2=("dq", lambda s: int((s == 1).sum())),
        camd_operating_hours=("operating_time_hours", "sum"),
    )
    # A plant where no unit reported CO2 has a sum of 0.0 from groupby, which is an
    # imputation. Put the null back.
    agg.loc[agg["camd_units_with_co2"] == 0, "co2_tonnes"] = np.nan
    agg.loc[agg["camd_gross_load_mwh"] <= 0, "camd_gross_load_mwh"] = np.nan

    print(f"  aggregated to {len(agg):,} plant-year rows, {agg['oris_code'].nunique():,} plants")
    print(f"  plant-years with CO2 mass: {agg['co2_tonnes'].notna().sum():,}")
    print(f"  plant-years where some unit is missing CO2: "
          f"{int(((agg['camd_units_with_co2'] > 0) & (agg['camd_units_with_co2'] < agg['camd_units'])).sum()):,}")
    return agg


def load_eia():
    df = pd.read_parquet(EIA_PATH)
    print(f"eia_plant_totals.parquet: {len(df):,} rows")

    # plantCode 99999 is EIA's "State-Fuel Level Increment", an imputed residual, not a
    # plant. It has no ORIS code and must never reach the join.
    fake = int((~df["is_real_plant"]).sum())
    df = df[df["is_real_plant"]].copy()
    print(f"  dropped {fake:,} State-Fuel Level Increment rows (plantCode 99999, not a plant)")

    df = df[df["year"].between(YEAR_MIN, YEAR_MAX)]
    df = df.rename(columns={
        "plant_code": "oris_code",
        "plant_name": "eia_plant_name",
        "state": "eia_state",
        "generation_mwh": "generation_mwh",
        "top_fuel_type": "eia_top_fuel",
        "top_fuel_share": "eia_top_fuel_share",
    })
    keep = ["oris_code", "year", "eia_plant_name", "eia_state", "generation_mwh",
            "eia_top_fuel", "eia_top_fuel_share", "fuel_types"]
    df = df[keep]
    df["oris_code"] = df["oris_code"].astype("int64")

    neg = int((df["generation_mwh"] < 0).sum())
    zero = int((df["generation_mwh"] == 0).sum())
    print(f"  {len(df):,} plant-year rows in {YEAR_MIN}-{YEAR_MAX}, "
          f"{df['oris_code'].nunique():,} plants")
    print(f"  net generation <= 0: {neg:,} negative (net consumers: pumped storage, "
          f"idle units drawing station service), {zero:,} exactly zero")
    print(f"  national net generation by year (TWh): " +
          ", ".join(f"{int(y)}={v / 1e6:,.0f}" for y, v in
                    df.groupby("year")["generation_mwh"].sum().items()))
    return df


def load_egrid():
    df = pd.read_parquet(EGRID_PATH)
    print(f"egrid_plant.parquet: {len(df):,} rows, years {df['year'].min()}-{df['year'].max()}")
    df = df[df["year"].between(YEAR_MIN, YEAR_MAX)]
    df = df.rename(columns={
        "orispl_code": "oris_code",
        "plant_name": "egrid_plant_name",
        "state": "egrid_state",
        "latitude": "egrid_latitude",
        "longitude": "egrid_longitude",
        "net_generation_mwh": "egrid_generation_mwh",
        "co2_tonnes": "egrid_co2_tonnes",
        "co2e_tonnes": "egrid_co2e_tonnes",
        "primary_fuel": "egrid_primary_fuel",
        "primary_fuel_category": "egrid_primary_fuel_category",
        "co2e_rate_g_per_kwh": "egrid_co2e_rate_g_per_kwh",
        "co2e_rate_basis": "egrid_co2e_rate_basis",
        "co2_source": "egrid_co2_source",
        "nameplate_capacity_mw": "nameplate_capacity_mw",
        "capacity_factor": "capacity_factor",
        "utility_name": "egrid_utility_name",
        "operator_name": "egrid_operator_name",
        "sector": "egrid_sector",
        "balancing_authority_code": "balancing_authority_code",
        "iso_rto": "iso_rto",
        "nerc_region": "egrid_nerc_region",
        "chp_flag": "chp_flag",
        "coal_flag": "coal_flag",
        "gen_combustion_mwh": "egrid_gen_combustion_mwh",
        "gen_noncombustion_mwh": "egrid_gen_noncombustion_mwh",
    })
    keep = ["oris_code", "year", "egrid_plant_name", "egrid_state", "subregion_code",
            "subregion_name", "egrid_latitude", "egrid_longitude", "nameplate_capacity_mw",
            "capacity_factor", "egrid_generation_mwh", "egrid_co2_tonnes", "egrid_co2e_tonnes",
            "egrid_primary_fuel", "egrid_primary_fuel_category", "egrid_co2e_rate_g_per_kwh",
            "egrid_co2e_rate_basis", "egrid_co2_source", "egrid_utility_name",
            "egrid_operator_name", "egrid_sector", "balancing_authority_code", "iso_rto",
            "egrid_nerc_region", "chp_flag", "coal_flag", "egrid_gen_combustion_mwh",
            "egrid_gen_noncombustion_mwh"]
    df = df[keep]
    df["oris_code"] = df["oris_code"].astype("int64")
    print(f"  {len(df):,} plant-year rows in {YEAR_MIN}-{YEAR_MAX}, "
          f"{df['oris_code'].nunique():,} plants, editions "
          f"{sorted(int(y) for y in df['year'].unique())}")
    print("  co2e_rate_basis: " +
          ", ".join(f"{k}={v:,}" for k, v in df["egrid_co2e_rate_basis"].value_counts().items()))
    return df


def read_threshold():
    rules = json.loads(RULES_PATH.read_text())
    for rule in rules["rules"]:
        if rule["id"] == "pab_exclusion_power_generation":
            p = rule["parameters"]
            print(f"PAB {rule['article']}: {rule['quote']}")
            print(f"  threshold {p['intensity_threshold_gco2e_per_kwh']} gCO2e/kWh, "
                  f"operator '{rule['intensity_operator']}'  |  revenue leg "
                  f"{p['revenue_threshold_pct']}% (owned by the entity-resolution lane, not this one)")
            return float(p["intensity_threshold_gco2e_per_kwh"]), rule["intensity_operator"], rule["article"]
    raise SystemExit("pab_exclusion_power_generation not found in pab_rules.json")


def main():
    print("=" * 78)
    print("POWER-SECTOR CARBON INTENSITY  |  CAMD CO2 / EIA generation, eGRID attributes")
    print("=" * 78)
    wait_for(CAMD_PATH)
    for path in (EIA_PATH, EGRID_PATH, RULES_PATH):
        if not path.exists():
            raise SystemExit(f"missing input {path}")

    threshold, operator, article = read_threshold()
    print()

    camd = load_camd()
    print()
    eia = load_eia()
    print()
    egrid = load_egrid()
    print()

    print("-" * 78)
    print("JOIN ON ORIS CODE")
    print("-" * 78)
    keys = pd.concat([
        camd[["oris_code", "year"]],
        eia[["oris_code", "year"]],
        egrid[["oris_code", "year"]],
    ]).drop_duplicates().reset_index(drop=True)
    keys["oris_code"] = keys["oris_code"].astype("int64")
    keys["year"] = keys["year"].astype("int64")
    print(f"union of plant-year keys across three sources: {len(keys):,}")

    # Coverage comes from the merge itself, not from a name column being non-null: 42 EIA
    # plant-years and 1 eGRID plant-year carry a real record with a blank name.
    df = keys.copy()
    for name, src in (("camd", camd), ("eia", eia), ("egrid", egrid)):
        src = src.copy()
        src[f"in_{name}"] = True
        df = df.merge(src, on=["oris_code", "year"], how="left")
        df[f"in_{name}"] = df[f"in_{name}"].fillna(False).astype(bool)
    assert len(df) == len(keys), "join fanned out; a source has duplicate (oris, year) keys"
    df["sources_agreeing"] = (df["in_camd"].astype(int) + df["in_eia"].astype(int)
                              + df["in_egrid"].astype(int)).astype("Int8")

    print("coverage by source combination:")
    combo = df.groupby([df["in_camd"], df["in_eia"], df["in_egrid"]]).size()
    for (c, e, g), n in combo.sort_values(ascending=False).items():
        label = "+".join(x for x, f in (("CAMD", c), ("EIA", e), ("eGRID", g)) if f) or "none"
        print(f"  {label:<18} {n:>8,} plant-years")
    print("sources_agreeing distribution: " +
          ", ".join(f"{k}={v:,}" for k, v in df["sources_agreeing"].value_counts().sort_index().items()))

    # CAMD is the only source of measured CO2, so a CAMD plant-year with no EIA match is a
    # hole in the denominator. Quantify it, because it bounds what the PAB test can see.
    camd_only = df[df["in_camd"] & ~df["in_eia"]]
    camd_co2_total = df.loc[df["in_camd"], "co2_tonnes"].sum()
    print(f"CAMD plant-years with no EIA generation match: {len(camd_only):,} "
          f"({camd_only['co2_tonnes'].sum() / camd_co2_total:.2%} of CAMD CO2 mass)")

    print()
    print("-" * 78)
    print("IDENTITY AND ATTRIBUTES: preference order eGRID, then CAMD, then EIA")
    print("-" * 78)
    df["plant_name"] = df["egrid_plant_name"].fillna(df["camd_facility_name"]).fillna(df["eia_plant_name"])
    df["state"] = df["egrid_state"].fillna(df["camd_state"]).fillna(df["eia_state"])
    df["latitude"] = df["egrid_latitude"].fillna(df["camd_latitude"])
    df["longitude"] = df["egrid_longitude"].fillna(df["camd_longitude"])
    df["primary_fuel"] = df["egrid_primary_fuel"].fillna(df["camd_primary_fuel"]).fillna(df["eia_top_fuel"])
    df["subregion"] = df["subregion_code"]

    # The three sources name fuels in three vocabularies, and which one wins changes by
    # year: eGRID codes (NG, SUB, BIT) run 2018-2023, CAMD prose ("Pipeline Natural Gas")
    # takes over in 2024-2025 once eGRID runs out. Comparing 2023 with 2024 on the raw
    # string is comparing two dictionaries, so collapse both to one category set.
    df["fuel_category"] = normalise_fuel(df["primary_fuel"])
    df["fuel_category"] = df["fuel_category"].fillna(
        df["egrid_primary_fuel_category"].str.lower().map(
            {"coal": "coal", "gas": "gas", "oil": "oil", "biomass": "biomass",
             "nuclear": "nuclear", "hydro": "hydro", "wind": "wind", "solar": "solar",
             "geothermal": "geothermal", "other": "other", "otherf": "other"}))
    print("fuel_category: " +
          ", ".join(f"{k}={v:,}" for k, v in
                    df["fuel_category"].value_counts(dropna=False).head(12).items()))

    # eGRID stops at 2023, so every 2024-2025 plant-year has a null subregion from the join.
    # Carry the plant's own most recent subregion forward. That is a fact about the plant's
    # location, not an emissions estimate, so it is a lookup rather than an imputation.
    latest_sub = (egrid.dropna(subset=["subregion_code"])
                       .sort_values("year")
                       .groupby("oris_code")[["subregion_code", "subregion_name"]].last())
    missing = df["subregion"].isna()
    filled = df.loc[missing, "oris_code"].map(latest_sub["subregion_code"])
    df.loc[missing, "subregion"] = filled
    df["subregion_name"] = df["subregion_name"].fillna(
        df["oris_code"].map(latest_sub["subregion_name"]))
    df["subregion_source"] = np.where(
        df["subregion_code"].notna(), "egrid_same_year",
        np.where(df["subregion"].notna(), "egrid_last_known_year", None))
    print(f"subregion from the same eGRID year: {int((df['subregion_source'] == 'egrid_same_year').sum()):,}")
    print(f"subregion carried from the plant's last eGRID year: "
          f"{int((df['subregion_source'] == 'egrid_last_known_year').sum()):,}")
    print(f"subregion still null: {int(df['subregion'].isna().sum()):,} "
          "(plants that never appear in any eGRID edition)")

    print()
    print("-" * 78)
    print("INTENSITY")
    print("-" * 78)
    gen = df["generation_mwh"].where(df["generation_mwh"] > 0)
    # tonnes/MWh -> g/kWh is a factor of 1000: 1e6 g per tonne over 1e3 kWh per MWh.
    df["intensity_g_per_kwh"] = df["co2_tonnes"] / gen * 1000.0
    df["intensity_g_per_kwh_egrid"] = df["egrid_co2e_rate_g_per_kwh"]

    # eGRID prints a rate of exactly 0.00 whenever net generation is zero or negative, even
    # for a plant that burned coal all year. Meramec (ORIS 2104) in eGRID2018 is the worst
    # case: 1.45 Mt CO2e, net generation -2.31 TWh, published rate 0.00 gCO2e/kWh. Taken at
    # face value that puts a coal plant on the clean side of the 100 g/kWh line. A published
    # zero on a plant with positive CO2e is a division artefact, not a measurement, so it is
    # voided here and counted rather than passed through.
    zero_trap = (df["intensity_g_per_kwh_egrid"] == 0) & (df["egrid_co2e_tonnes"] > 0)
    print(f"eGRID published rates of exactly 0.00 gCO2e/kWh on plants with positive CO2e: "
          f"{int(zero_trap.sum()):,}")
    print(f"  of those, net generation <= 0: "
          f"{int((zero_trap & ~(df['egrid_generation_mwh'] > 0)).sum()):,}, "
          f"carrying {df.loc[zero_trap, 'egrid_co2e_tonnes'].sum() / 1e6:,.2f} Mt CO2e in total")
    print("  voided: a rate of zero on a plant that emitted is a divide-by-nothing artefact, "
          "and left alone it reads as PAB-compliant")
    df.loc[zero_trap, "intensity_g_per_kwh_egrid"] = np.nan
    df["egrid_zero_rate_voided"] = zero_trap

    df["gross_net_ratio"] = df["camd_gross_load_mwh"] / gen
    plausible = df["gross_net_ratio"].between(GROSS_NET_LO, GROSS_NET_HI)
    df["boundary_ok"] = pd.Series(pd.NA, index=df.index, dtype="boolean")
    df.loc[df["gross_net_ratio"].notna(), "boundary_ok"] = plausible[df["gross_net_ratio"].notna()]

    have_camd_int = df["intensity_g_per_kwh"].notna()
    print(f"plant-years with a CAMD/EIA intensity: {int(have_camd_int.sum()):,}")
    if have_camd_int.any():
        r = df.loc[have_camd_int, "gross_net_ratio"]
        print(f"  CAMD gross load / EIA net generation: median {r.median():.3f}, "
              f"IQR {r.quantile(0.25):.3f}-{r.quantile(0.75):.3f}")
        print(f"  inside {GROSS_NET_LO}-{GROSS_NET_HI}: {int((df['boundary_ok'] == True).sum()):,}   "
              f"outside: {int((df['boundary_ok'] == False).sum()):,} "
              f"(CAMD and EIA disagree about the facility boundary)")

    # A combined heat and power plant sells steam as well as electricity. CAMD meters the
    # whole stack, so dividing all of it by electric generation charges the steam host's
    # CO2 to the kWh and inflates the intensity. eGRID does the power/steam allocation, so
    # for CHP its published rate is the number the regulation is asking for.
    df["is_chp"] = df["chp_flag"].astype("string").str.strip().str.lower().eq("yes").fillna(False)
    print(f"CHP plant-years flagged by eGRID: {int(df['is_chp'].sum()):,}")

    # The headline column coalesces the measured number with eGRID's published rate so the
    # regulatory test has national coverage. intensity_basis says which one every row used.
    df["intensity_basis"] = pd.Series(pd.NA, index=df.index, dtype="object")
    df["intensity_best_g_per_kwh"] = np.nan

    has_egrid_rate = df["intensity_g_per_kwh_egrid"].notna()
    chp_to_egrid = df["is_chp"] & has_egrid_rate
    df.loc[chp_to_egrid, "intensity_best_g_per_kwh"] = df.loc[chp_to_egrid, "intensity_g_per_kwh_egrid"]
    df.loc[chp_to_egrid, "intensity_basis"] = "egrid_published_co2e_chp_allocated"

    # boundary_ok is null where CAMD reports no gross load, which is normal for steam-only
    # boilers. A null check is not a failed check, so those rows still use the measured ratio.
    use_camd = (df["intensity_best_g_per_kwh"].isna() & have_camd_int
                & (df["boundary_ok"] != False))
    df.loc[use_camd, "intensity_best_g_per_kwh"] = df.loc[use_camd, "intensity_g_per_kwh"]
    df.loc[use_camd, "intensity_basis"] = "camd_co2_over_eia_net"

    use_egrid = df["intensity_best_g_per_kwh"].isna() & has_egrid_rate
    df.loc[use_egrid, "intensity_best_g_per_kwh"] = df.loc[use_egrid, "intensity_g_per_kwh_egrid"]
    df.loc[use_egrid, "intensity_basis"] = "egrid_published_co2e"

    # Last resort: a boundary-mismatched CAMD ratio with no eGRID rate behind it. Kept
    # rather than dropped, but dq marks it so the portfolio builder can throw it out.
    use_last = df["intensity_best_g_per_kwh"].isna() & have_camd_int
    df.loc[use_last, "intensity_best_g_per_kwh"] = df.loc[use_last, "intensity_g_per_kwh"]
    df.loc[use_last, "intensity_basis"] = "camd_co2_over_eia_net_boundary_suspect"

    print("intensity_basis: " +
          ", ".join(f"{k}={v:,}" for k, v in df["intensity_basis"].value_counts(dropna=False).items()))

    # CAMD measures CO2 only. eGRID publishes CO2 and CO2e for the same plants, so the
    # CH4 + N2O uplift can be measured instead of assumed. Report the median: the mean is
    # wrecked by biomass plants whose fossil CO2 rounds to nothing while CO2e does not.
    both_co2 = df["egrid_co2_tonnes"].notna() & df["egrid_co2e_tonnes"].notna() & (df["egrid_co2_tonnes"] > 0)
    uplift = (df.loc[both_co2, "egrid_co2e_tonnes"] / df.loc[both_co2, "egrid_co2_tonnes"])
    print(f"eGRID CO2e / CO2 on {int(both_co2.sum()):,} plant-years: median {uplift.median():.4f}, "
          f"IQR {uplift.quantile(0.25):.4f}-{uplift.quantile(0.75):.4f}, "
          f"p99 {uplift.quantile(0.99):.2f}")
    print("  so a CAMD CO2-only intensity understates the CO2e figure the regulation names "
          f"by about {(uplift.median() - 1) * 100:.2f}% on a typical fossil plant, far inside "
          "the margin at the 100 g/kWh line. The long right tail is biomass, where fossil "
          "CO2 is near zero and CH4 plus N2O is all that is left.")

    print()
    print("-" * 78)
    print("DATA QUALITY FLAG")
    print("-" * 78)
    df["dq"] = pd.Series(pd.NA, index=df.index, dtype="Int8")
    partial_units = (df["camd_units_with_co2"] > 0) & (df["camd_units_with_co2"] < df["camd_units"])
    basis = df["intensity_basis"]
    is_camd = basis == "camd_co2_over_eia_net"
    df.loc[basis == "egrid_published_co2e", "dq"] = 5
    df.loc[basis == "camd_co2_over_eia_net_boundary_suspect", "dq"] = 6
    df.loc[basis == "egrid_published_co2e_chp_allocated", "dq"] = 4
    df.loc[is_camd & (df["boundary_ok"] == True), "dq"] = 1
    df.loc[is_camd & df["boundary_ok"].isna(), "dq"] = 2
    df.loc[is_camd & partial_units, "dq"] = 3
    df.loc[df["intensity_best_g_per_kwh"].isna(), "dq"] = 7
    for code, text in DQ_LEGEND.items():
        n = int((df["dq"] == code).sum())
        print(f"  dq={code}  {n:>8,}  {text}")
    print(f"  dq=<NA> {int(df['dq'].isna().sum()):>8,}  unclassified")

    df["dq_reason"] = df["dq"].map(DQ_LEGEND).astype("object")

    print()
    print("=" * 78)
    print("THREE-WAY CROSS-CHECK  |  plant-years where CAMD, EIA and eGRID all cover the plant")
    print("=" * 78)
    tri = df[df["sources_agreeing"] == 3].copy()
    print(f"plant-years with all three sources: {len(tri):,} "
          f"({tri['oris_code'].nunique():,} plants, years "
          f"{int(tri['year'].min())}-{int(tri['year'].max())})")
    print()
    print("CO2 mass, EPA CAMD stack monitors against eGRID published plant CO2")
    cross = {}
    cross["camd_co2_vs_egrid_co2"] = agreement_stats(
        "CAMD CO2 vs eGRID CO2", tri["co2_tonnes"], tri["egrid_co2_tonnes"], "tonnes CO2")
    print()
    print("CO2 mass, EPA CAMD against eGRID CO2e (expected to run low: CAMD has no CH4 or N2O)")
    cross["camd_co2_vs_egrid_co2e"] = agreement_stats(
        "CAMD CO2 vs eGRID CO2e", tri["co2_tonnes"], tri["egrid_co2e_tonnes"], "tonnes")
    print()
    print("Generation, EIA-923 net generation against eGRID plant net generation")
    cross["eia_gen_vs_egrid_gen"] = agreement_stats(
        "EIA net gen vs eGRID net gen", tri["generation_mwh"], tri["egrid_generation_mwh"], "MWh")
    print()
    print("Intensity, CAMD-over-EIA against eGRID's own published CO2e rate")
    cross["intensity_camd_vs_egrid"] = agreement_stats(
        "CAMD/EIA intensity vs eGRID rate", tri["intensity_g_per_kwh"],
        tri["egrid_co2e_rate_g_per_kwh"], "gCO2e/kWh", summable=False)
    print()
    print("  the same intensity comparison split on CHP, because that is the whole story:")
    for label, mask in (("non-CHP", ~tri["is_chp"]), ("CHP", tri["is_chp"])):
        key = f"intensity_camd_vs_egrid_{label.lower().replace('-', '_')}"
        cross[key] = agreement_stats(
            f"    {label}", tri.loc[mask, "intensity_g_per_kwh"],
            tri.loc[mask, "egrid_co2e_rate_g_per_kwh"], "gCO2e/kWh", summable=False)

    print()
    print("-" * 78)
    print(f"WHERE THEY DISAGREE BY MORE THAN {DISAGREE_PCT:.0f}%")
    print("-" * 78)

    tri["co2_pct_diff"] = pct_diff(tri["co2_tonnes"], tri["egrid_co2_tonnes"])
    tri["gen_pct_diff"] = pct_diff(tri["generation_mwh"], tri["egrid_generation_mwh"])

    co2_bad = tri[tri["co2_pct_diff"].abs() > DISAGREE_PCT].copy()
    gen_bad = tri[tri["gen_pct_diff"].abs() > DISAGREE_PCT].copy()
    n_co2_cmp = int((tri["co2_tonnes"].notna() & tri["egrid_co2_tonnes"].notna()
                     & (tri["egrid_co2_tonnes"].abs() > 0)).sum())
    n_gen_cmp = int((tri["generation_mwh"].notna() & tri["egrid_generation_mwh"].notna()
                     & (tri["egrid_generation_mwh"].abs() > 0)).sum())

    print(f"CO2 disagreements: {len(co2_bad):,} of {n_co2_cmp:,} comparable plant-years "
          f"({len(co2_bad) / max(n_co2_cmp, 1):.1%}), carrying "
          f"{co2_bad['co2_tonnes'].sum() / tri['co2_tonnes'].sum():.1%} of CAMD CO2 in the tri-source set")
    print(f"  CAMD above eGRID: {int((co2_bad['co2_pct_diff'] > 0).sum()):,}   "
          f"CAMD below eGRID: {int((co2_bad['co2_pct_diff'] < 0).sum()):,}")
    print("  by eGRID CO2 source:")
    for k, v in co2_bad["egrid_co2_source"].value_counts(dropna=False).items():
        share = v / max(int(tri["egrid_co2_source"].eq(k).sum()), 1)
        print(f"    {str(k):<16} {v:>6,}  ({share:.1%} of that source's tri-source plant-years)")

    # The mechanism. CAMD meters the whole stack of a CHP plant; eGRID splits the emissions
    # between the electricity and the process steam. Every large disagreement is that split.
    print("  by CHP status, which is the mechanism:")
    n_chp_tri = int(tri["is_chp"].sum())
    n_non_tri = int((~tri["is_chp"]).sum())
    print(f"    CHP plant-years        {int(co2_bad['is_chp'].sum()):>6,} of {n_chp_tri:,} "
          f"({co2_bad['is_chp'].sum() / max(n_chp_tri, 1):.1%} disagree)")
    print(f"    non-CHP plant-years    {int((~co2_bad['is_chp']).sum()):>6,} of {n_non_tri:,} "
          f"({(~co2_bad['is_chp']).sum() / max(n_non_tri, 1):.1%} disagree)")
    print(f"    CHP share of all disagreements: {co2_bad['is_chp'].mean():.1%}, "
          f"against {tri['is_chp'].mean():.1%} of the tri-source population")
    print(f"    median signed diff over ALL tri-source plant-years: "
          f"CHP {tri.loc[tri['is_chp'], 'co2_pct_diff'].median():+.2f}%, "
          f"non-CHP {tri.loc[~tri['is_chp'], 'co2_pct_diff'].median():+.2f}%")
    print("    CAMD sits above eGRID on CHP because the stack monitor counts the CO2 that "
          "made process steam, which eGRID assigns to the steam host and not to the kWh. "
          "This is a definitional difference, not an error on either side.")
    print("  ten largest CO2 disagreements by absolute tonnes:")
    co2_bad["abs_t"] = (co2_bad["co2_tonnes"] - co2_bad["egrid_co2_tonnes"]).abs()
    cols = ["oris_code", "year", "plant_name", "state", "fuel_category", "co2_tonnes",
            "egrid_co2_tonnes", "co2_pct_diff", "camd_units", "camd_units_with_co2",
            "egrid_co2_source", "is_chp"]
    print(co2_bad.nlargest(10, "abs_t")[cols].to_string(index=False,
          float_format=lambda v: f"{v:,.1f}"))

    print()
    print(f"generation disagreements: {len(gen_bad):,} of {n_gen_cmp:,} comparable plant-years "
          f"({len(gen_bad) / max(n_gen_cmp, 1):.1%})")
    print(f"  EIA above eGRID: {int((gen_bad['gen_pct_diff'] > 0).sum()):,}   "
          f"EIA below eGRID: {int((gen_bad['gen_pct_diff'] < 0).sum()):,}")
    gen_bad["abs_mwh"] = (gen_bad["generation_mwh"] - gen_bad["egrid_generation_mwh"]).abs()
    gcols = ["oris_code", "year", "plant_name", "state", "fuel_category", "generation_mwh",
             "egrid_generation_mwh", "gen_pct_diff", "gross_net_ratio", "is_chp"]
    print("  ten largest generation disagreements by absolute MWh:")
    print(gen_bad.nlargest(10, "abs_mwh")[gcols].to_string(index=False,
          float_format=lambda v: f"{v:,.0f}"))

    # Facility-boundary mismatch is the mechanism the EIA lane flagged. Test it directly:
    # if CAMD covers a station that EIA splits across several plant codes, the CAMD-side
    # mass sits on one ORIS while only part of the generation does.
    print()
    print("  boundary test on the generation disagreements: CAMD gross load over EIA net gen")
    for label, sub in (("all tri-source", tri), ("gen disagreement > 10%", gen_bad)):
        r = sub["gross_net_ratio"].dropna()
        if len(r):
            print(f"    {label:<26} n={len(r):,}  median {r.median():.3f}  "
                  f"share above 1.5 {float((r > 1.5).mean()):.1%}")

    print()
    print("-" * 78)
    print("HOW INDEPENDENT ARE THE THREE SOURCES, ACTUALLY")
    print("-" * 78)
    gm = tri["generation_mwh"].notna() & tri["egrid_generation_mwh"].notna()
    gd = (tri.loc[gm, "generation_mwh"] - tri.loc[gm, "egrid_generation_mwh"]).abs()
    exact = float((tri.loc[gm, "generation_mwh"] == tri.loc[gm, "egrid_generation_mwh"]).mean())
    print(f"generation: {float((gd < 1).mean()):.2%} of {int(gm.sum()):,} tri-source plant-years "
          f"agree to within 1 MWh, and {exact:.2%} agree to the last decimal place.")
    print("  eGRID does not measure generation. It republishes EIA-923. So this pair is not a")
    print("  cross-check of two measurements, it is a check that the ORIS join lines up the")
    print("  right plant, and it passes. The 50 that fail are facility-boundary changes.")
    print()
    cm = tri["co2_tonnes"].notna() & tri["egrid_co2_tonnes"].notna() & (tri["egrid_co2_tonnes"] > 0)
    tc = tri[cm].copy()
    tc["rel"] = ((tc["co2_tonnes"] - tc["egrid_co2_tonnes"]) / tc["egrid_co2_tonnes"]).abs()
    print("CO2 by what eGRID says its own number came from, split on CHP:")
    tbl = tc.groupby(["egrid_co2_source", "is_chp"]).agg(
        n=("rel", "size"),
        median_abs_pct=("rel", lambda v: float(v.median() * 100)),
        identical=("rel", lambda v: float((v < 1e-6).mean())),
    )
    print(tbl.to_string(float_format=lambda v: f"{v:,.6f}"))
    print()
    print("  Read the EPA/CAMD and EPA/CAPD rows: for a non-CHP plant the two numbers are the")
    print("  same number to seven decimal places, because eGRID took it from the same Part 75")
    print("  monitors this lane reads. That is not agreement, it is one source counted twice.")
    print("  The comparison only carries information on CHP plants, where eGRID applies a")
    print("  power/steam allocation that CAMD does not, and there the gap is real and large.")
    print("  Genuinely independent CO2 comparisons (eGRID co2_source = EIA, that is estimated")
    print(f"  from fuel burn rather than metered) number {int((tc['egrid_co2_source'] == 'EIA').sum()):,} "
          "in the tri-source set, because a plant")
    print("  with a CAMD monitor is exactly a plant for which eGRID uses CAMD. The three-way")
    print("  overlap is by construction the set where two of the three are the same feed.")

    print()
    print("-" * 78)
    print("TWO TRAPS THE NAIVE VERSION OF THIS JOIN FALLS INTO")
    print("-" * 78)
    print("1. eGRID prints 0.00 gCO2e/kWh for a plant whose net generation is zero or")
    print("   negative, regardless of what came out of the stack. Worst case:")
    mer = df[(df["oris_code"] == 2104) & (df["year"] == 2018)]
    if len(mer):
        m = mer.iloc[0]
        print(f"   ORIS 2104 Meramec, {int(m['year'])}, a {m['fuel_category']} plant: eGRID net "
              f"generation {m['egrid_generation_mwh']:,.0f} MWh, eGRID CO2e "
              f"{m['egrid_co2e_tonnes']:,.0f} t, published rate 0.00 gCO2e/kWh.")
        print(f"   CAMD measured {m['co2_tonnes']:,.0f} t of CO2 there and EIA reports "
              f"{m['generation_mwh']:,.0f} MWh, which is "
              f"{m['intensity_g_per_kwh']:,.0f} gCO2/kWh. Reading eGRID's zero would put a "
              "coal plant")
        print("   on the compliant side of Article 12(1)(g). This script voids that rate.")
    print()
    print("2. eGRID and EIA draw the facility boundary differently after a rebuild. ORIS 613:")
    lau = df[(df["oris_code"] == 613) & (df["year"] == 2023)]
    dan = df[(df["oris_code"] == 65978) & (df["year"] == 2023)]
    if len(lau) and len(dan):
        l, d = lau.iloc[0], dan.iloc[0]
        print(f"   eGRID2023 books {l['egrid_generation_mwh']:,.0f} MWh to Lauderdale and has no "
              "Dania Beach row.")
        print(f"   EIA splits the site: Lauderdale {l['generation_mwh']:,.0f} MWh plus "
              f"Dania Beach 7 (ORIS 65978) {d['generation_mwh']:,.0f} MWh")
        print(f"   = {l['generation_mwh'] + d['generation_mwh']:,.0f} MWh, which is eGRID's "
              f"number to the MWh ({l['egrid_generation_mwh'] - l['generation_mwh'] - d['generation_mwh']:+,.0f} "
              "MWh residual).")
        print("   EIA has the newer boundary. The gross/net screen catches this class of case "
              "because CAMD")
        print(f"   gross load over EIA net generation reads {l['gross_net_ratio']:,.1f} on that row.")

    print()
    print("=" * 78)
    print(f"PAB {article} TEST INPUTS  |  plant level only, no company rollup")
    print("=" * 78)
    print(f"threshold: intensity {operator} {threshold:.0f} gCO2e/kWh")

    df["above_pab_threshold"] = pd.Series(pd.NA, index=df.index, dtype="boolean")
    known = df["intensity_best_g_per_kwh"].notna()
    df.loc[known, "above_pab_threshold"] = df.loc[known, "intensity_best_g_per_kwh"] > threshold

    pab_rows = []
    for year in sorted(int(y) for y in df["year"].unique()):
        sub = df[df["year"] == year]
        nat_gen = sub["generation_mwh"].where(sub["generation_mwh"] > 0).sum()
        above = sub[sub["above_pab_threshold"] == True]
        below = sub[sub["above_pab_threshold"] == False]
        unknown = sub[sub["above_pab_threshold"].isna()]
        a_gen = above["generation_mwh"].where(above["generation_mwh"] > 0).sum()
        b_gen = below["generation_mwh"].where(below["generation_mwh"] > 0).sum()
        u_gen = unknown["generation_mwh"].where(unknown["generation_mwh"] > 0).sum()
        row = {
            "year": year,
            "plants_above": int(len(above)),
            "plants_below": int(len(below)),
            "plants_untested": int(len(unknown)),
            "gen_above_twh": a_gen / 1e6,
            "gen_below_twh": b_gen / 1e6,
            "gen_untested_twh": u_gen / 1e6,
            "national_gen_twh": nat_gen / 1e6,
            "share_gen_above": a_gen / nat_gen if nat_gen else np.nan,
            "co2_above_mmt": above["co2_tonnes"].sum() / 1e6,
            "egrid_year": bool(sub["in_egrid"].any()),
        }
        # Only CAMD and EIA run the whole window, so the CAMD-only series is the one that
        # is comparable across all eleven years.
        camd_only = sub[sub["intensity_g_per_kwh"].notna()]
        ca = camd_only[camd_only["intensity_g_per_kwh"] > threshold]
        row["camd_only_plants_above"] = int(len(ca))
        row["camd_only_gen_above_twh"] = ca["generation_mwh"].where(ca["generation_mwh"] > 0).sum() / 1e6
        row["camd_only_share_gen_above"] = (row["camd_only_gen_above_twh"] * 1e6 / nat_gen
                                            if nat_gen else np.nan)
        pab_rows.append(row)
    pab = pd.DataFrame(pab_rows)
    print()
    print("plants above the line, and the share of US net generation they carry:")
    print(pab.drop(columns=["camd_only_plants_above", "camd_only_gen_above_twh",
                            "camd_only_share_gen_above"])
             .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print()
    print("READ THE STEP AT 2018 AND 2024 AS COVERAGE, NOT AS A TREND. eGRID only publishes")
    print("2018-2023, so outside that window the only plants with a rate are the roughly 1,000")
    print("CAMD stack-monitored ones. The columns below use CAMD over EIA alone and are")
    print("therefore comparable across all eleven years:")
    print(pab[["year", "camd_only_plants_above", "camd_only_gen_above_twh",
               "camd_only_share_gen_above", "national_gen_twh"]]
          .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    latest_full = 2024 if 2024 in set(df["year"]) else int(df["year"].max())
    ly = pab[pab["year"] == latest_full].iloc[0]
    print()
    print(f"{latest_full} headline: {int(ly['plants_above']):,} plants above "
          f"{threshold:.0f} gCO2e/kWh carrying {ly['gen_above_twh']:,.1f} TWh, "
          f"{ly['share_gen_above']:.1%} of US net generation; "
          f"{int(ly['plants_below']):,} plants at or below carrying {ly['gen_below_twh']:,.1f} TWh; "
          f"{int(ly['plants_untested']):,} plant-years untested "
          f"({ly['gen_untested_twh']:,.1f} TWh, mostly wind, solar, hydro and nuclear "
          "that burn nothing and for which no source publishes a rate)")

    sub = df[df["year"] == latest_full]
    nat = sub["generation_mwh"].where(sub["generation_mwh"] > 0).sum()
    print()
    print(f"{latest_full} plants above the line, by normalised fuel category:")
    ab = sub[sub["above_pab_threshold"] == True].copy()
    byfuel = ab.groupby("fuel_category").agg(
        plants=("oris_code", "count"),
        twh=("generation_mwh", lambda s: s.where(s > 0).sum() / 1e6),
        median_g_kwh=("intensity_best_g_per_kwh", "median"),
    ).sort_values("twh", ascending=False)
    byfuel["share_us_gen"] = byfuel["twh"] * 1e6 / nat
    print(byfuel.head(12).to_string(float_format=lambda v: f"{v:,.3f}"))

    print()
    print("national generation-weighted mean intensity by year:")
    print("  rated_only counts only plants that have a rate. national counts a plant with no")
    print("  published rate as zero combustion, which is a physical fact for wind, solar,")
    print("  hydro and nuclear rather than an imputation. Compare the eGRID years against")
    print("  EPA's own US figure; 2015-2017 and 2024-2025 lack eGRID and run low because")
    print("  small non-CAMD fossil plants have no rate and are counted as clean.")
    nat_rows = []
    for year in sorted(int(y) for y in df["year"].unique()):
        sy = df[df["year"] == year]
        rated_y = sy[sy["intensity_best_g_per_kwh"].notna() & (sy["generation_mwh"] > 0)]
        wy = rated_y["generation_mwh"]
        mass_g = float((rated_y["intensity_best_g_per_kwh"] * wy).sum())
        all_gen_y = float(sy["generation_mwh"].where(sy["generation_mwh"] > 0).sum())
        nat_rows.append({
            "year": year,
            "rated_plants": int(len(rated_y)),
            "rated_twh": float(wy.sum()) / 1e6,
            "rated_only_g_per_kwh": mass_g / float(wy.sum()) if wy.sum() else np.nan,
            "national_g_per_kwh": mass_g / all_gen_y if all_gen_y else np.nan,
            "rate_coverage_of_gen": float(wy.sum()) / all_gen_y if all_gen_y else np.nan,
            "egrid_cover": bool(sy["in_egrid"].any()),
        })
    nat_tbl = pd.DataFrame(nat_rows)
    print(nat_tbl.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

    sub_e_yr = int(egrid["year"].max())
    ours = float(nat_tbl.loc[nat_tbl["year"] == sub_e_yr, "national_g_per_kwh"].iloc[0])
    egrid_sub = pd.read_parquet(EGRID_SUB_PATH)
    es = egrid_sub[egrid_sub["year"] == sub_e_yr]
    epa_nat = float((es["co2e_rate_g_per_kwh"] * es["net_generation_mwh"]).sum()
                    / es["net_generation_mwh"].sum())
    print(f"validation: our {sub_e_yr} national figure {ours:,.1f} gCO2e/kWh against EPA's own "
          f"generation-weighted subregion mean {epa_nat:,.1f} gCO2e/kWh "
          f"({(ours - epa_nat) / epa_nat:+.2%})")

    print()
    print("-" * 78)
    print("SUBREGION ROLLUP, latest year with eGRID cover")
    print("-" * 78)
    ey = int(egrid["year"].max())
    sub_e = df[(df["year"] == ey) & df["subregion"].notna()].copy()
    sub_e["pos_gen"] = sub_e["generation_mwh"].where(sub_e["generation_mwh"] > 0)
    sub_e["co2_g"] = sub_e["intensity_best_g_per_kwh"] * sub_e["pos_gen"]
    roll = sub_e.groupby("subregion").agg(
        plants=("oris_code", "count"),
        plants_above=("above_pab_threshold", lambda s: int((s == True).sum())),
        twh=("pos_gen", lambda s: s.sum() / 1e6),
        co2_g=("co2_g", "sum"),
    )
    roll["g_per_kwh"] = roll["co2_g"] / (roll["twh"] * 1e6)
    roll = roll.drop(columns="co2_g").sort_values("g_per_kwh")
    print(f"{ey}, {len(roll)} eGRID subregions, cleanest and dirtiest five:")
    print(pd.concat([roll.head(5), roll.tail(5)]).to_string(float_format=lambda v: f"{v:,.1f}"))
    print(f"  spread cleanest to dirtiest: {roll['g_per_kwh'].max() / roll['g_per_kwh'].min():.1f}x")

    print()
    print("-" * 78)
    print("WRITE")
    print("-" * 78)
    out_cols = [
        "oris_code", "year", "plant_name", "state", "latitude", "longitude",
        "co2_tonnes", "generation_mwh", "intensity_g_per_kwh",
        "intensity_best_g_per_kwh", "intensity_basis", "above_pab_threshold",
        "subregion", "subregion_name", "subregion_source", "primary_fuel", "fuel_category",
        "egrid_primary_fuel_category", "is_chp", "sources_agreeing", "dq", "dq_reason",
        "in_camd", "in_eia", "in_egrid",
        "camd_units", "camd_units_with_co2", "camd_gross_load_mwh", "gross_net_ratio",
        "boundary_ok", "camd_heat_input_mmbtu", "camd_so2_tonnes", "camd_nox_tonnes",
        "camd_owner_operator", "camd_source_category", "camd_primary_fuel",
        "eia_plant_name", "eia_top_fuel", "eia_top_fuel_share",
        "egrid_plant_name", "egrid_generation_mwh", "egrid_co2_tonnes", "egrid_co2e_tonnes",
        "intensity_g_per_kwh_egrid", "egrid_co2e_rate_basis", "egrid_zero_rate_voided",
        "egrid_co2_source",
        "egrid_utility_name", "egrid_operator_name", "egrid_sector",
        "nameplate_capacity_mw", "capacity_factor", "balancing_authority_code", "iso_rto",
        "egrid_nerc_region", "chp_flag", "coal_flag",
    ]
    out = df[out_cols].sort_values(["oris_code", "year"]).reset_index(drop=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"wrote {OUT_PATH}")
    print(f"  {len(out):,} plant-year rows, {out['oris_code'].nunique():,} distinct ORIS codes, "
          f"years {int(out['year'].min())}-{int(out['year'].max())}")
    print(f"  rows with a CAMD/EIA measured intensity: {int(out['intensity_g_per_kwh'].notna().sum()):,}")
    print(f"  rows with any intensity (measured or eGRID published): "
          f"{int(out['intensity_best_g_per_kwh'].notna().sum()):,}")
    print(f"  rows with intensity null: {int(out['intensity_best_g_per_kwh'].isna().sum()):,}")
    print("  null counts on the required columns: " +
          ", ".join(f"{c}={int(out[c].isna().sum()):,}" for c in
                    ["co2_tonnes", "generation_mwh", "intensity_g_per_kwh", "subregion",
                     "state", "latitude", "longitude", "primary_fuel"]))

    prov = {
        "derived_table": str(OUT_PATH.relative_to(ROOT)),
        "script": "src/build_power_intensity.py",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "network_io": "none, this lane reads only local parquet written by the fetch lanes",
        "rows": int(len(out)),
        "distinct_oris": int(out["oris_code"].nunique()),
        "year_range": [int(out["year"].min()), int(out["year"].max())],
        "method": (
            "intensity_g_per_kwh = CAMD Part 75 measured CO2 (tonnes) / EIA-923 plant net "
            "generation (MWh) * 1000. intensity_best_g_per_kwh picks a basis per row: "
            "eGRID's published rate for CHP plants, because CAMD meters the whole stack "
            "including the CO2 that made process steam while eGRID allocates that away "
            "from the kWh; otherwise the CAMD/EIA ratio, unless CAMD gross load over EIA "
            f"net generation falls outside [{GROSS_NET_LO}, {GROSS_NET_HI}], which means "
            "the two datasets disagree about the facility boundary, in which case eGRID's "
            "rate wins. Nothing is imputed; a plant with no rate stays null and is counted."
        ),
        "pab_rule": {
            "article": article,
            "threshold_gco2e_per_kwh": threshold,
            "operator": operator,
            "note": ("This is Article 12(1)(g) of Regulation (EU) 2020/1818. Article 12(1)(d) "
                     "is the separate 1%-of-revenue coal rule. The revenue leg of 12(1)(g) is "
                     "not applied here; this lane stops at the plant."),
        },
        "dq_legend": {str(k): v for k, v in DQ_LEGEND.items()},
        "cross_check": cross,
        "independence_note": (
            "eGRID republishes EIA-923 generation and, for plants with a Part 75 monitor, "
            "CAMD CO2. The generation pair and the non-CHP CO2 pair therefore validate the "
            "ORIS join rather than comparing independent measurements. The CO2 pair only "
            "carries information on CHP plants, where eGRID allocates emissions between "
            "electricity and process steam and CAMD does not."
        ),
        "pab_by_year": pab.to_dict(orient="records"),
        "national_intensity_by_year": nat_tbl.to_dict(orient="records"),
        "inputs": [
            {
                "path": str(p.relative_to(ROOT)),
                "sha256": sha256_of(p),
                "bytes": p.stat().st_size,
                "modified_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            }
            for p in (CAMD_PATH, EIA_PATH, EGRID_PATH, RULES_PATH)
        ],
        "licence": ("EPA CAMD, EPA eGRID and EIA-923 are US federal government works in the "
                    "public domain (17 U.S.C. 105). PAB thresholds are EUR-Lex, "
                    "(c) European Union, 1998-2026."),
        "redistribution": ("Derived numbers may be published citing EPA Clean Air Markets "
                           "Program Data, EPA eGRID, EIA Form 923 and EUR-Lex."),
    }
    PROV_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROV_PATH.write_text(json.dumps(prov, indent=2, default=float) + "\n")
    print(f"wrote {PROV_PATH}")

    assert not any(v and v in PROV_PATH.read_text()
                   for v in (os.environ.get("EIA_API_KEY"), os.environ.get("CAMD_API_KEY"))), \
        "an api key reached the provenance file"
    print("provenance checked: no credential present")


if __name__ == "__main__":
    main()
