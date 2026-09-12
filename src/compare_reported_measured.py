"""Self-reported Scope 1 against EPA-measured Scope 1, for the same companies and years.

EPA GHGRP is filed under legal penalty and covers US facilities above 25,000 tCO2e.
WBA's figure is what the company says about itself, globally. The measured number is
therefore a floor on the self-reported one: global cannot be smaller than domestic.
A company sitting below its own US measurement is the case worth naming, and the
asymmetry is what makes the test conservative.

Four things inflate the measured side relative to what a company calls Scope 1, and
each is stripped out here rather than waved at:

  biogenic CO2      EPA's published CO2e includes gas_id 8, biogenic CO2 from biomass
                    combustion. The GHG Protocol puts that outside Scope 1 and reports
                    it separately, so paper and waste companies look like they hide
                    three quarters of their emissions when they do not.
  consolidation     our rollup is ownership-weighted (equity share). A company on the
                    operational-control basis reports 100% of what it operates and
                    nothing of what it does not, so the floor is the tonnage from
                    facilities it holds outright.
  entity look-ahead the parent map applies today's ownership to historical facilities.
                    Calpine sits inside Constellation from 2010 in our tables and did
                    not in reality until January 2025.
  timing            GHGRP stops at reporting year 2023; most WBA climate profiles are
                    2024. A divestiture in between lowers the self-report honestly.

Writes data/interim/reported_vs_measured.parquet and the numbers behind
docs/reported_vs_measured.md.
"""

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
DOCS = ROOT / "docs"

# EPA GHGRP gas dimension. 8 is biogenic CO2, which 40 CFR 98 makes reportable and the
# GHG Protocol keeps out of Scope 1.
GAS_BIOGENIC, GAS_CH4, GAS_N2O = 8, 2, 3
# Fluorinated gases. A semiconductor fab reports these under 40 CFR 98 subpart I, which
# lets a facility use EPA default emission factors or its own measurements including
# abatement. The measured and the self-reported figure are then not the same calculation,
# so a company whose measured tonnage is mostly F-gas is not comparable on method.
GAS_FLUORINATED = (6, 7, 9, 10, 11, 12, 14, 16)

# 40 CFR 98 Table A-1 is on AR4. Companies increasingly publish on AR6. Used only to
# size the sensitivity, never to restate the measured figure.
AR4_CH4, AR6_CH4 = 25.0, 29.8
AR4_N2O, AR6_N2O = 298.0, 273.0

# Parent families whose facilities were not inside the ticker's perimeter for the whole
# of the reported year. Surfaced systematically (print_perimeter_candidates below lists
# every ticker where most measured tonnage comes from a parent family that did not match
# the index name directly) and then checked one by one against the deal date. Seven of
# the eleven candidates turned out to be renames and subsidiary spellings, not deals.
PERIMETER_CHANGES = {
    # Constellation agreed to buy Calpine in January 2025 and closed after the 2024
    # reporting period. None of this fleet was Constellation's in 2023 or 2024.
    ("CEG", "CPNMANAGEMENT"): "Calpine, agreed Jan 2025",
    ("CEG", "CALPINE"): "Calpine, agreed Jan 2025",
    ("CEG", "VOLTPARENT"): "Calpine holdco, agreed Jan 2025",
    # Smurfit Kappa combined with WestRock on 5 July 2024, so a 2023 self-report is
    # Smurfit Kappa alone and a 2024 one carries under half a year of the US mills.
    ("SW", "WESTROCK"): "WestRock, combined 5 Jul 2024",
    ("SW", "KAPSTONEPAPERPACKAGING"): "WestRock subsidiary, combined 5 Jul 2024",
    ("SW", "MEADWESTVACO"): "WestRock subsidiary, combined 5 Jul 2024",
    ("SW", "ROCKTENN"): "WestRock subsidiary, combined 5 Jul 2024",
    ("SW", "LONGVIEWFIBREPAPERPACKAGING"): "WestRock subsidiary, combined 5 Jul 2024",
    # Chesapeake and Southwestern became Expand Energy on 1 October 2024, so FY2024
    # carries one quarter of the Southwestern wells.
    ("EXE", "SOUTHWESTERNENERGY"): "Southwestern, combined 1 Oct 2024",
    # International Paper closed DS Smith in January 2025. Immaterial here (0.6 of 28 MMT)
    # but kept for the same reason.
    ("IP", "DSSMITH"): "DS Smith, acquired Jan 2025",
}

# Candidates the systematic rule surfaced and a hand check cleared, kept here so the
# reader can see what was looked at rather than only what survived.
PERIMETER_CLEARED = {
    "AMCR": "Berry Global, merged 30 Apr 2025, 0.067 MMT, immaterial",
    "DD": "DuPont de Nemours is DuPont's own SEC name",
    "UAL": "United Continental is United's former SEC name",
    "HON": "Honeywell and Honeywell UOP are Honeywell",
    "LLY": "Eli Lilly is Lilly",
    "SRE": "Sempra Energy is Sempra's former name",
    "PCG": "Pacific Gas & Electric is PG&E's operating utility",
    "HWM": "Arconic is Howmet's former SEC name",
}


def wilson(k, n, z=1.96):
    """Wilson score interval. Four out of ninety is not a rate you quote to two figures."""
    if n == 0:
        return float("nan"), float("nan")
    ph = k / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    h = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5)
    return (c - h) / d, (c + h) / d


def load_facility_gas():
    """Per facility-year CO2e split by gas, direct emitters only.

    PUB_FACTS_SECTOR_GHG_EMISSION is the same feed fetch_epa_ghgrp.py aggregates, read
    again here because that script drops the gas dimension and the gas dimension is the
    whole point.
    """
    sectors = pd.read_csv(RAW / "epa_ghgrp" / "pub_dim_sector.csv")[["sector_id", "sector_type"]]
    files = sorted(glob.glob(str(RAW / "epa_ghgrp" / "pub_facts_sector_ghg_emission_*_*.csv")))
    if not files:
        raise SystemExit("no GHGRP gas-level files in data/raw/epa_ghgrp; run src/fetch_epa_ghgrp.py")
    facts = pd.concat(
        [pd.read_csv(f, usecols=["facility_id", "year", "sector_id", "gas_id", "co2e_emission"])
         for f in files], ignore_index=True)
    print(f"GHGRP gas-level rows read                {len(facts):>12,}  from {len(files)} files")
    facts["sector_id"] = facts.sector_id.astype(float)
    facts = facts.merge(sectors, on="sector_id", how="left")
    direct = facts[facts.sector_type == "E"].copy()
    print(f"  direct emitters (sector_type E)        {len(direct):>12,}")
    direct["gas_id"] = direct.gas_id.astype(float)
    direct["year"] = direct.year.astype(int)

    piv = (direct.pivot_table(index=["facility_id", "year"], columns="gas_id",
                              values="co2e_emission", aggfunc="sum", fill_value=0.0)
           .reset_index())
    out = pd.DataFrame({"facility_id": piv.facility_id, "year": piv.year})
    gas_cols = [c for c in piv.columns if isinstance(c, float)]
    out["co2e_total"] = piv[gas_cols].sum(axis=1)
    out["co2e_biogenic"] = piv[GAS_BIOGENIC] if GAS_BIOGENIC in piv else 0.0
    out["co2e_ch4"] = piv[GAS_CH4] if GAS_CH4 in piv else 0.0
    out["co2e_n2o"] = piv[GAS_N2O] if GAS_N2O in piv else 0.0
    fcols = [g for g in GAS_FLUORINATED if g in piv]
    out["co2e_fgas"] = piv[fcols].sum(axis=1) if fcols else 0.0
    out["co2e_fossil"] = out.co2e_total - out.co2e_biogenic
    print(f"  facility-years                         {len(out):>12,}")
    for y in (2019, 2023):
        s = out[out.year == y]
        print(f"  {y}: {s.co2e_total.sum()/1e6:8.1f} MMT total, "
              f"{s.co2e_biogenic.sum()/1e6:6.1f} MMT biogenic "
              f"({100*s.co2e_biogenic.sum()/s.co2e_total.sum():.1f}%)")
    return out


def build_measured(gas):
    """One row per ticker-year with every defensible reading of the measured figure."""
    fac = pd.read_parquet(INTERIM / "ghgrp_facilities.parquet")
    pmap = pd.read_parquet(INTERIM / "parent_ticker_map.parquet")
    pmap = pmap[(pmap.source == "ghgrp_parent") & pmap.ticker.notna()]
    key_to_ticker = dict(zip(pmap.parent_name_clean, pmap.ticker))
    key_to_alias = dict(zip(pmap.parent_name_clean, pmap.alias_source))

    fac = fac.copy()
    fac["ticker"] = fac.parent_name_clean.map(key_to_ticker)
    fm = fac[fac.ticker.notna()].merge(gas, on=["facility_id", "year"], how="left")
    print(f"\nfacility-year-parent rows carrying a ticker   {len(fm):>10,}"
          f"   ({fm.ticker.nunique()} tickers)")
    missing = fm.co2e_total.isna() & fm.co2e_tonnes.notna()
    print(f"  rows whose gas split did not join            {int(missing.sum()):>10,}")

    # Same 100%-cap fix match_parents.py applies: EPA sometimes lists one parent twice on
    # one facility, each at a full share.
    own = fm.groupby(["facility_id", "year", "ticker"]).ownership_frac.sum().rename("own_sum")
    fm = fm.merge(own, on=["facility_id", "year", "ticker"], how="left")
    fm["frac"] = fm.ownership_frac / np.where(fm.own_sum > 1.01, fm.own_sum, 1.0)

    fm["eq_all"] = fm.co2e_total * fm.frac
    fm["eq_fossil"] = fm.co2e_fossil * fm.frac
    fm["eq_biogenic"] = fm.co2e_biogenic * fm.frac
    fm["eq_ch4"] = fm.co2e_ch4 * fm.frac
    fm["eq_n2o"] = fm.co2e_n2o * fm.frac
    fm["eq_fgas"] = fm.co2e_fgas * fm.frac
    # Under operational control a company books 100% of what it runs and none of what it
    # does not. The tonnage it holds outright is the floor no consolidation choice escapes.
    whole = fm.frac >= 0.9999
    fm["whole_fossil"] = np.where(whole, fm.co2e_fossil, 0.0)
    fm["partial_fossil"] = np.where(whole, 0.0, fm.eq_fossil)
    fm["alias_source"] = fm.parent_name_clean.map(key_to_alias)
    fm["offname_fossil"] = np.where(fm.alias_source.eq("index"), 0.0, fm.eq_fossil)
    fm["lookahead_fossil"] = [
        r.eq_fossil if (r.ticker, r.parent_name_clean) in PERIMETER_CHANGES else 0.0
        for r in fm.itertuples()]

    # Unapportioned: the whole facility once, however many parents EPA names.
    dedup = fm.drop_duplicates(["ticker", "facility_id", "year"])
    unapp = (dedup.groupby(["ticker", "year"]).co2e_fossil.sum()
             .rename("meas_fossil_unapportioned"))
    # The size of a company's biggest single site says how fragile a shortfall is: if one
    # asset sale would cover it, GHGRP stopping at 2023 is a live explanation.
    largest = (dedup.groupby(["ticker", "year"]).co2e_fossil.max()
               .rename("largest_site_fossil"))

    g = (fm.groupby(["ticker", "year"])
         .agg(meas_all_equity=("eq_all", "sum"),
              meas_fossil_equity=("eq_fossil", "sum"),
              meas_biogenic_equity=("eq_biogenic", "sum"),
              meas_fossil_whollyowned=("whole_fossil", "sum"),
              meas_fossil_partialowned=("partial_fossil", "sum"),
              meas_fossil_offname=("offname_fossil", "sum"),
              meas_fossil_lookahead=("lookahead_fossil", "sum"),
              eq_ch4=("eq_ch4", "sum"), eq_n2o=("eq_n2o", "sum"),
              eq_fgas=("eq_fgas", "sum"),
              facility_count=("facility_id", "nunique"),
              parent_families=("parent_name_clean", "nunique"))
         .reset_index().merge(unapp, on=["ticker", "year"], how="left")
         .merge(largest, on=["ticker", "year"], how="left"))

    # AR4 to AR6 restatement of the measured figure, as a band not a correction.
    g["meas_fossil_ar6"] = (g.meas_fossil_equity
                            + g.eq_ch4 * (AR6_CH4 / AR4_CH4 - 1)
                            + g.eq_n2o * (AR6_N2O / AR4_N2O - 1))
    g["biogenic_share"] = g.meas_biogenic_equity / g.meas_all_equity.replace(0, np.nan)
    g["fgas_share"] = g.eq_fgas / g.meas_fossil_equity.replace(0, np.nan)
    # Each company's own year-to-year swing in measured tonnage, which is the bar a
    # one-year reporting gap has to clear before a shortfall means anything.
    g = g.sort_values(["ticker", "year"])
    recent = g[g.year.between(2019, 2023)].copy()
    recent["yoy"] = (recent.groupby("ticker").meas_fossil_equity.pct_change().abs())
    vol = recent.groupby("ticker").yoy.median().rename("yoy_volatility")
    g = g.merge(vol, on="ticker", how="left")
    g["partial_owned_share"] = g.meas_fossil_partialowned / g.meas_fossil_equity.replace(0, np.nan)
    g["offname_share"] = g.meas_fossil_offname / g.meas_fossil_equity.replace(0, np.nan)
    g["lookahead_share"] = g.meas_fossil_lookahead / g.meas_fossil_equity.replace(0, np.nan)

    # The equity column has to reproduce what the rest of the repo already publishes.
    em = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    chk = g.merge(em[["ticker", "year", "scope1_ghgrp_tonnes"]], on=["ticker", "year"], how="inner")
    worst = float((chk.meas_all_equity - chk.scope1_ghgrp_tonnes).abs().max())
    print(f"  reconciliation against emissions_by_ticker: max abs diff {worst:.6f} t "
          f"over {len(chk):,} ticker-years")
    assert worst < 1.0, "measured rollup disagrees with emissions_by_ticker"

    print(f"  measured table                               {len(g):>10,} ticker-years, "
          f"{g.ticker.nunique()} tickers")
    return g, fm


def print_perimeter_candidates(meas, fm, tickers, year=2023):
    """The systematic rule behind PERIMETER_CHANGES, run in the open.

    A ticker whose measured tonnage comes mostly from a parent family that did not match
    the index name directly is a candidate for a fleet that entered the perimeter after
    the fact. The rule surfaces candidates; only a deal date can settle one.
    """
    print(f"\nperimeter candidates, reporting year {year}: tickers where more than half the "
          f"measured\ntonnage sits under a parent family that is not the index name")
    s = fm[(fm.year == year) & fm.ticker.isin(tickers)]
    g = s.groupby("ticker").apply(
        lambda d: pd.Series({"tot": d.eq_fossil.sum(),
                             "off": d.loc[d.alias_source.ne("index"), "eq_fossil"].sum()}),
        include_groups=False)
    g = g[(g.tot > 0) & (g.off / g.tot > 0.5)].sort_values("off", ascending=False)
    for tk, r in g.iterrows():
        fams = (s[s.ticker == tk].groupby("parent_name_clean").eq_fossil.sum()
                .sort_values(ascending=False))
        top = fams.index[0]
        verdict = PERIMETER_CHANGES.get((tk, top), PERIMETER_CLEARED.get(tk, "UNCHECKED"))
        mark = "DROP " if (tk, top) in PERIMETER_CHANGES else "keep "
        print(f"  {mark}{tk:<5} {100*r.off/r.tot:5.1f}% off-name of {r.tot/1e6:7.3f} MMT  "
              f"{top:<24} {verdict}")
    print(f"  {len(g)} candidates, {sum(1 for tk, rr in g.iterrows() if any(t == tk for t, f in PERIMETER_CHANGES))} "
          f"confirmed as perimeter changes")


def load_self_reported():
    """WBA figures, kept as two separate series because they mean different things."""
    we = pd.read_parquet(INTERIM / "wba_emissions.parquet")
    s1 = (we[(we.scope == "1") & we.preferred]
          [["ticker", "fy", "tonnes_co2e", "source_table", "estimated_flag"]]
          .rename(columns={"tonnes_co2e": "self_tonnes"}))
    s1["self_scope"] = "1"
    s12 = (we[(we.scope == "1+2") & we.preferred & (we.source_table == "emissions_timeseries")]
           [["ticker", "fy", "tonnes_co2e", "source_table", "estimated_flag"]]
           .rename(columns={"tonnes_co2e": "self_tonnes"}))
    s12["self_scope"] = "1+2"
    print(f"\nWBA self-reported Scope 1    {len(s1):>5} rows, {s1.ticker.nunique()} tickers, "
          f"years {sorted(s1.fy.unique())}")
    print(f"WBA self-reported Scope 1+2  {len(s12):>5} rows, {s12.ticker.nunique()} tickers, "
          f"years {sorted(s12.fy.unique())}")
    return s1, s12


def load_context():
    """Everything that might make a gap innocent, one row per ticker."""
    uni = pd.read_parquet(INTERIM / "universe.parquet")
    uni = uni[uni.is_primary_listing][["ticker", "company_name", "gics_sector"]]

    fp = pd.read_csv(RAW / "wba" / "WBA Data" / "footprintattributes.csv",
                     dtype=str, engine="python")
    ctry = fp[fp.attribute_description == "Number of countries of operations"].copy()
    ctry["countries_of_operation"] = pd.to_numeric(ctry.attribute_value, errors="coerce")
    wc = pd.read_parquet(INTERIM / "wba_company.parquet")
    ctx = (wc[["ticker", "wba_company_id", "hq_country_iso", "climate_profile_year",
               "disclosure_level", "independently_verified", "valid_accounting",
               "consistent_s1x2_data", "profile_scope_1", "profile_scope_2",
               "profile_scope_3", "required_emissions", "available_emissions"]]
           .merge(ctry[["company_id", "countries_of_operation"]],
                  left_on="wba_company_id", right_on="company_id", how="left")
           .drop(columns=["company_id"]))
    print(f"\ncountries-of-operation known for {int(ctx.countries_of_operation.notna().sum())} "
          f"of {len(ctx)} WBA-matched tickers; "
          f"{int((ctx.countries_of_operation == 1).sum())} operate in one country only")

    ct = pd.read_parquet(INTERIM / "climatetrace_nonus_share.parquet")
    ct = (ct[ct.is_primary_listing & ct.ct_nonus_share_balanced.notna()]
          .sort_values("year").groupby("ticker").tail(1)
          [["ticker", "ct_nonus_share_balanced", "year"]]
          .rename(columns={"year": "ct_year"}))
    print(f"Climate TRACE non-US asset share available for {len(ct)} tickers")

    fin = pd.read_parquet(INTERIM / "financials.parquet")
    fin = fin[fin.is_primary_listing & fin.period_end.notna()].copy()
    fin["period_end"] = pd.to_datetime(fin.period_end, errors="coerce")
    fy_end = (fin.sort_values("fy").groupby("ticker").tail(1)
              [["ticker", "period_end"]].copy())
    fy_end["fy_end_month"] = fy_end.period_end.dt.month
    fy_end["calendar_fy"] = fy_end.fy_end_month.isin([12, 1])
    print(f"fiscal year end known for {len(fy_end)} tickers; "
          f"{int((~fy_end.calendar_fy).sum())} do not close on a calendar year")

    # CAMD runs through 2025, so for anything with a stack monitor we can see what the
    # measured US power CO2 actually did in 2024, the year GHGRP has not published.
    camd = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    camd = camd[camd.is_primary_listing][["ticker", "year", "scope1_camd_tonnes"]]
    c23 = camd[camd.year == 2023].set_index("ticker").scope1_camd_tonnes
    c24 = camd[camd.year == 2024].set_index("ticker").scope1_camd_tonnes
    camd_delta = pd.DataFrame({"camd_2023": c23, "camd_2024": c24}).dropna()
    camd_delta = camd_delta[camd_delta.camd_2023 > 0]
    camd_delta["camd_2024_over_2023"] = camd_delta.camd_2024 / camd_delta.camd_2023
    camd_delta = camd_delta.reset_index()
    print(f"CAMD 2023 and 2024 both present for {len(camd_delta)} tickers, "
          f"median 2024/2023 ratio {camd_delta.camd_2024_over_2023.median():.3f}")

    return (uni.merge(ctx, on="ticker", how="right")
            .merge(ct, on="ticker", how="left")
            .merge(fy_end[["ticker", "fy_end_month", "calendar_fy"]], on="ticker", how="left")
            .merge(camd_delta, on="ticker", how="left"))


def assemble(self_df, meas, ctx, mode):
    """One row per ticker: a self-reported figure against the measured year we can use.

    mode 'exact' takes the latest year where both sides exist. mode 'nearest' takes the
    company's self-report and the most recent measured year at or before it, which is how
    a 2024 climate profile gets compared at all, and records the gap.
    """
    meas_nonzero = meas[meas.meas_fossil_equity > 0]
    if mode == "exact":
        j = self_df.merge(meas_nonzero, left_on=["ticker", "fy"], right_on=["ticker", "year"])
        j = j.sort_values("fy").groupby("ticker").tail(1).copy()
    else:
        j = self_df.merge(meas_nonzero, on="ticker")
        j = j[j.year <= j.fy]
        j = j.sort_values(["fy", "year"]).groupby("ticker").tail(1).copy()
    j["year_gap"] = j.fy - j.year
    j = j.merge(ctx, on="ticker", how="left")
    j["mode"] = mode

    # Where a stack monitor covers most of the measured tonnage, CAMD knows what happened
    # in 2024 even though GHGRP does not, so the floor can be rolled to the reported year.
    camd_dominant = (j.camd_2023.fillna(0) / j.meas_all_equity).fillna(0) >= 0.5
    roll = np.where(camd_dominant & j.camd_2024_over_2023.notna() & (j.year_gap == 1),
                    j.camd_2024_over_2023.fillna(1.0), 1.0)
    j["floor_roll_factor"] = roll
    j["meas_floor_rolled"] = j.meas_fossil_whollyowned * roll

    j["ratio_headline"] = j.self_tonnes / j.meas_all_equity
    j["ratio_fossil"] = j.self_tonnes / j.meas_fossil_equity
    j["ratio_floor"] = j.self_tonnes / j.meas_fossil_whollyowned.replace(0, np.nan)
    j["ratio_ar6"] = j.self_tonnes / j.meas_fossil_ar6
    # AR6 applied to the floor, so the GWP vintage and the consolidation floor stack.
    ar6_factor = (j.meas_fossil_ar6 / j.meas_fossil_equity.replace(0, np.nan)).fillna(1.0)
    j["ratio_floor_ar6"] = j.self_tonnes / (j.meas_floor_rolled * ar6_factor).replace(0, np.nan)
    j["shortfall_tonnes"] = (j.meas_floor_rolled * ar6_factor) - j.self_tonnes
    j["shortfall_pct"] = 1 - j.ratio_floor_ar6
    # A shortfall smaller than the company's own year-to-year swing in measured tonnage
    # cannot be told apart from the one-year reporting gap.
    j["beats_own_volatility"] = j.shortfall_pct > j.yoy_volatility.fillna(0)
    j["fgas_dominated"] = j.fgas_share.fillna(0) >= 0.5
    j["lookahead_flag"] = j.lookahead_share.fillna(0) >= 0.10
    j["shortfall_lt_largest_site"] = j.shortfall_tonnes < j.largest_site_fossil
    return j


def tier_table(j, label):
    """Walk the gap count down through every innocent explanation in turn."""
    print(f"\n{'='*100}\n{label}\n{'='*100}")
    n0 = len(j)
    b0 = int((j.ratio_headline < 1).sum())
    print(f"tier 0  both a measured and a self-reported figure            n = {n0:>3}   "
          f"below 1: {b0:>3}  ({100*b0/n0:.0f}%)")

    t1 = j[j.year_gap <= 1]
    b1 = int((t1.ratio_headline < 1).sum())
    stale = j[j.year_gap > 1].sort_values("year_gap", ascending=False)
    print(f"tier 1  drop measured years more than one year stale          n = {len(t1):>3}   "
          f"below 1: {b1:>3}   (-{n0-len(t1)} companies)")
    if len(stale):
        print("        " + ", ".join(f"{r.ticker} gap {int(r.year_gap)}y" for r in stale.itertuples()))

    b2 = int((t1.ratio_fossil < 1).sum())
    freed = t1[(t1.ratio_headline < 1) & (t1.ratio_fossil >= 1)]
    print(f"tier 2  biogenic CO2 out of Scope 1, fossil CO2e only         n = {len(t1):>3}   "
          f"below 1: {b2:>3}   (-{len(freed)} explained)")
    for r in freed.sort_values("biogenic_share", ascending=False).itertuples():
        print(f"        {r.ticker:<5} {str(r.company_name)[:28]:<28} biogenic "
              f"{100*r.biogenic_share:5.1f}% of measured   ratio {r.ratio_headline:.3f} "
              f"-> {r.ratio_fossil:.3f}")

    b3 = int((t1.ratio_floor < 1).sum())
    freed3 = t1[(t1.ratio_fossil < 1) & (t1.ratio_floor >= 1)]
    print(f"tier 3  consolidation floor: wholly owned facilities only     n = {len(t1):>3}   "
          f"below 1: {b3:>3}   (-{len(freed3)} explained)")
    for r in freed3.sort_values("partial_owned_share", ascending=False).itertuples():
        print(f"        {r.ticker:<5} {str(r.company_name)[:28]:<28} "
              f"{100*r.partial_owned_share:5.1f}% of measured is part-owned  ratio "
              f"{r.ratio_fossil:.3f} -> {r.ratio_floor:.3f}")

    b4 = int((t1.ratio_floor_ar6 < 1).sum())
    freed4 = t1[(t1.ratio_floor < 1) & (t1.ratio_floor_ar6 >= 1)]
    added4 = t1[(t1.ratio_floor >= 1) & (t1.ratio_floor_ar6 < 1)]
    print(f"tier 4  roll the floor to the reported year on CAMD, AR6 GWP  n = {len(t1):>3}   "
          f"below 1: {b4:>3}   (-{len(freed4)} explained, +{len(added4)} newly below)")
    for r in pd.concat([freed4, added4]).itertuples():
        print(f"        {r.ticker:<5} {str(r.company_name)[:28]:<28} CAMD 2024/2023 "
              f"{r.floor_roll_factor:.3f}  ratio {r.ratio_floor:.3f} -> {r.ratio_floor_ar6:.3f}")

    below = t1[t1.ratio_floor_ar6 < 1]
    drop_look = below[below.lookahead_flag]
    drop_fgas = below[~below.lookahead_flag & below.fgas_dominated]
    drop_vol = below[~below.lookahead_flag & ~below.fgas_dominated & ~below.beats_own_volatility]
    surv = below[~below.lookahead_flag & ~below.fgas_dominated & below.beats_own_volatility]
    print(f"tier 5  drop fleets our parent map attributes by today's owner            "
          f"(-{len(drop_look)})")
    for r in drop_look.itertuples():
        fams = [v for (t, f), v in PERIMETER_CHANGES.items() if t == r.ticker]
        print(f"        {r.ticker:<5} {str(r.company_name)[:28]:<28} "
              f"{100*r.lookahead_share:5.1f}% of measured is {fams[0] if fams else '?'}")
    print(f"tier 6  drop measured figures that are mostly fluorinated gas (subpart I) "
          f"(-{len(drop_fgas)})")
    for r in drop_fgas.itertuples():
        print(f"        {r.ticker:<5} {str(r.company_name)[:28]:<28} F-gas "
              f"{100*r.fgas_share:5.1f}% of measured, ratio {r.ratio_floor_ar6:.3f}")
    print(f"tier 7  drop shortfalls smaller than the company's own year-to-year swing "
          f"(-{len(drop_vol)})")
    for r in drop_vol.itertuples():
        print(f"        {r.ticker:<5} {str(r.company_name)[:28]:<28} shortfall "
              f"{100*r.shortfall_pct:4.1f}% vs own median year-on-year move "
              f"{100*r.yoy_volatility:4.1f}%")

    print(f"\n        survivors: {len(surv)} of {len(t1)} "
          f"({100*len(surv)/max(len(t1),1):.0f}%)")
    if len(surv):
        print(f"        {'tkr':<5} {'company':<24} {'fy':>4} {'meas':>5} {'self Mt':>9} "
              f"{'floor Mt':>9} {'ratio':>6} {'short%':>7} {'short Mt':>9} "
              f"{'top site':>9} {'ctry':>5}")
        for r in surv.sort_values("ratio_floor_ar6").itertuples():
            ctry = "" if pd.isna(r.countries_of_operation) else f"{int(r.countries_of_operation)}"
            print(f"        {r.ticker:<5} {str(r.company_name)[:24]:<24} {int(r.fy):>4} "
                  f"{int(r.year):>5} {r.self_tonnes/1e6:>9.3f} "
                  f"{r.meas_floor_rolled/1e6:>9.3f} {r.ratio_floor_ar6:>6.2f} "
                  f"{100*r.shortfall_pct:>6.1f}% {r.shortfall_tonnes/1e6:>9.3f} "
                  f"{r.largest_site_fossil/1e6:>9.3f} {ctry:>5}")
        n_frag = int(surv.shortfall_lt_largest_site.sum())
        print(f"        for {n_frag} of {len(surv)} the shortfall is smaller than the "
              f"company's single largest US site, so one 2024 asset sale would cover it "
              f"and GHGRP cannot yet say")
        print(f"        median shortfall among survivors {100*surv.shortfall_pct.median():.1f}%, "
              f"total {surv.shortfall_tonnes.sum()/1e6:.1f} MMT")
    return t1, surv


def main():
    pd.set_option("display.width", 200)
    print("=" * 100)
    print("self-reported against measured Scope 1")
    print("=" * 100)

    gas = load_facility_gas()
    meas, fm = build_measured(gas)
    s1, s12 = load_self_reported()
    ctx = load_context()

    print_perimeter_candidates(meas, fm, set(s1.ticker) | set(s12.ticker))

    j1 = assemble(s1, meas, ctx, "nearest")
    j12 = assemble(s12, meas, ctx, "exact")

    print(f"\ntest A  WBA Scope 1 (climate profile) against measured Scope 1        "
          f"n = {len(j1)}")
    print(f"        self-report years: {dict(j1.fy.value_counts().sort_index())}")
    print(f"        measured years:    {dict(j1.year.value_counts().sort_index())}")
    print(f"        year gaps:         {dict(j1.year_gap.value_counts().sort_index())}")
    print(f"test B  WBA Scope 1+2 against measured Scope 1, same calendar year     "
          f"n = {len(j12)}")
    print(f"        years: {dict(j12.fy.value_counts().sort_index())}")

    tA, survA = tier_table(j1, "TEST A  self-reported global Scope 1 vs "
                               "EPA-measured US Scope 1")
    tB, survB = tier_table(j12, "TEST B  self-reported global Scope 1+2 vs EPA-measured US "
                                "Scope 1 (strictly conservative: Scope 1+2 >= Scope 1)")

    # ---------------------------------------------------------------- the distribution
    print(f"\n{'='*100}\nDISTRIBUTION of self-reported / measured\n{'='*100}")
    for label, t in (("A Scope 1", tA), ("B Scope 1+2", tB)):
        for col, name in (("ratio_headline", "vs EPA published CO2e"),
                          ("ratio_fossil", "vs fossil CO2e only"),
                          ("ratio_floor", "vs wholly owned fossil"),
                          ("ratio_floor_ar6", "vs floor, rolled, AR6")):
            s = t[col].replace([np.inf, -np.inf], np.nan).dropna()
            q = s.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
            print(f"  {label:<12} {name:<24} n={len(s):>3}  "
                  f"p05 {q.iloc[0]:6.2f}  p25 {q.iloc[1]:6.2f}  median {q.iloc[2]:6.2f}  "
                  f"p75 {q.iloc[3]:6.2f}  p95 {q.iloc[4]:6.2f}  below 1: "
                  f"{100*(s<1).mean():4.0f}%")

    # ------------------------------------------------- how much of the self-report we measure
    print(f"\n{'='*100}\nHOW MUCH OF THE SELF-REPORTED FIGURE OUR MANDATORY SPINE ALREADY "
          f"COVERS\n{'='*100}")
    for label, t in (("A Scope 1", tA), ("B Scope 1+2", tB)):
        st, mt = t.self_tonnes.sum(), t.meas_fossil_equity.sum()
        print(f"  {label:<12} n={len(t):>3}  self-reported {st/1e6:8.1f} MMT, EPA-measured US "
              f"fossil {mt/1e6:8.1f} MMT = {100*mt/st:.0f}% of it")
        print(f"               at the median company the measured US part is "
              f"{100/t.ratio_fossil.median():.0f}% of the global self-report")
        heavy = t[t.gics_sector.isin(["Utilities", "Energy", "Materials"])]
        print(f"               tonnage-weighted and dominated by heavy sectors: "
              f"{len(heavy)} of {len(t)} companies carry "
              f"{100*heavy.self_tonnes.sum()/st:.0f}% of the self-reported tonnes")

    # ---------------------------------------------------------------- boundary, sized
    print(f"\n{'='*100}\nBOUNDARY: how much of the excess is explained by operating abroad\n{'='*100}")
    t = tA
    one = t[t.countries_of_operation == 1]
    many = t[t.countries_of_operation > 1]
    print(f"  companies WBA records as operating in one country only   n = {len(one)}")
    if len(one):
        print(f"    median self/measured (fossil)                        "
              f"{one.ratio_fossil.median():.2f}")
        print(f"    below 1 on the wholly owned floor                    "
              f"{int((one.ratio_floor < 1).sum())} of {len(one)}")
        print("    " + ", ".join(f"{r.ticker} {r.ratio_fossil:.2f}"
                                 for r in one.sort_values('ratio_fossil').itertuples()))
    print(f"  companies operating in more than one country             n = {len(many)}")
    if len(many):
        print(f"    median self/measured (fossil)                        "
              f"{many.ratio_fossil.median():.2f}")
        print(f"    median countries of operation                        "
              f"{many.countries_of_operation.median():.0f}")
    both = t[t.ct_nonus_share_balanced.notna()]
    if len(both):
        rho = both[["ct_nonus_share_balanced", "ratio_fossil"]].corr(method="spearman").iloc[0, 1]
        print(f"  Climate TRACE non-US asset share vs ratio, n = {len(both)}, "
              f"Spearman rho {rho:+.2f}")
    corr = t[t.countries_of_operation.notna()]
    if len(corr) > 5:
        rho = corr[["countries_of_operation", "ratio_fossil"]].corr(method="spearman").iloc[0, 1]
        print(f"  countries of operation vs ratio, n = {len(corr)}, Spearman rho {rho:+.2f}")

    # ---------------------------------------------------------------- other caveats sized
    print(f"\n{'='*100}\nTHE REMAINING CAVEATS, SIZED\n{'='*100}")
    print(f"  gases. GHGRP CO2e is AR4. Restating the measured figure to AR6 moves it by")
    d = (tA.meas_fossil_ar6 / tA.meas_fossil_equity - 1) * 100
    print(f"    median {d.median():+.2f}%, p95 {d.quantile(0.95):+.2f}%, max {d.max():+.2f}% "
          f"(CH4 up, N2O down). It never flips a verdict on its own:")
    flip = tA[(tA.ratio_floor >= 1) & (tA.ratio_floor_ar6 < 1)]
    unflip = tA[(tA.ratio_floor < 1) & (tA.ratio_floor_ar6 >= 1)]
    print(f"    it pushes {len(flip)} company below the floor that was not and lifts "
          f"{len(unflip)} above it")
    print(f"    F-gas heavy measured figures (subpart I, method not comparable): "
          f"{int(tA.fgas_dominated.sum())} of {len(tA)}")
    for r in tA[tA.fgas_dominated].sort_values('fgas_share', ascending=False).itertuples():
        print(f"      {r.ticker:<5} {str(r.company_name)[:26]:<26} F-gas "
              f"{100*r.fgas_share:5.1f}% of measured, ratio {r.ratio_floor_ar6:.2f}")
    nc = tA[~tA.calendar_fy.fillna(True)]
    print(f"  fiscal year. {len(nc)} of {len(tA)} compared companies close their books off "
          f"the calendar year")
    if len(nc):
        print("    " + ", ".join(f"{r.ticker}(m{int(r.fy_end_month)}, ratio {r.ratio_floor:.2f})"
                                 for r in nc.itertuples()))
    print(f"  timing. GHGRP's last year is 2023; {int((tA.year_gap == 1).sum())} of "
          f"{len(tA)} self-reports are FY2024.")
    print(f"    rolled forward on CAMD for {int((tA.floor_roll_factor != 1).sum())} companies "
          f"where a stack monitor covers at least half the measured tonnage")
    cd = tA[tA.camd_2024_over_2023.notna()]
    if len(cd):
        print(f"    CAMD does publish 2024. For the {len(cd)} compared companies with a stack "
              f"monitor, measured US power CO2 moved")
        print(f"    {100*(cd.camd_2024_over_2023.median()-1):+.1f}% at the median "
              f"({100*(cd.camd_2024_over_2023.quantile(.1)-1):+.0f}% to "
              f"{100*(cd.camd_2024_over_2023.quantile(.9)-1):+.0f}% p10-p90), so a one-year gap "
              f"is worth roughly that much either way.")

    # ---------------------------------------------------------------- trend divergence
    print(f"\n{'='*100}\nTREND TEST: does the self-reported series move with the measured one\n{'='*100}")
    print("  A fixed level bias (US-only boundary, biogenic share, consolidation basis, GWP")
    print("  vintage) cancels in a within-company change, so this is the one comparison the")
    print("  caveats above cannot touch.")
    panel = (s12.merge(meas[meas.meas_fossil_equity > 0], left_on=["ticker", "fy"],
                       right_on=["ticker", "year"]))
    panel["cover"] = panel.meas_fossil_equity / panel.self_tonnes
    base = panel[panel.fy == 2019].set_index("ticker")
    end = panel[panel.fy == 2023].set_index("ticker")
    tr = base[["self_tonnes", "meas_fossil_equity", "cover", "facility_count"]].join(
        end[["self_tonnes", "meas_fossil_equity", "cover", "facility_count"]],
        lsuffix="_19", rsuffix="_23", how="inner")
    print(f"  companies with both sides in 2019 and 2023                  n = {len(tr)}")
    # The measured series only tracks the company if the US measured part is a real chunk
    # of the global figure. Below that it is noise on a small base, and a parent-string
    # change in EPA's file swamps any real trend.
    keep = tr[(tr.cover_19 >= 0.2) & (tr.cover_23 >= 0.2)]
    print(f"  of those, US measured is at least 20% of the global self-report in both years: "
          f"n = {len(keep)}")
    keep = keep.copy()
    keep["self_chg"] = keep.self_tonnes_23 / keep.self_tonnes_19 - 1
    keep["meas_chg"] = keep.meas_fossil_equity_23 / keep.meas_fossil_equity_19 - 1
    keep["divergence"] = keep.self_chg - keep.meas_chg
    print(f"  2019-2023 change, self-reported   median {100*keep.self_chg.median():+.1f}%")
    print(f"  2019-2023 change, measured US     median {100*keep.meas_chg.median():+.1f}%")
    opp = keep[(keep.meas_chg > 0.05) & (keep.self_chg < -0.05)]
    print(f"  measured US rose >5% while the self-reported figure fell >5%: {len(opp)} of {len(keep)}")
    for r in opp.sort_values("divergence").itertuples():
        print(f"    {r.Index:<5} self {100*r.self_chg:+6.1f}%   measured {100*r.meas_chg:+6.1f}%")
    n_better = int((keep.divergence < 0).sum())
    from scipy import stats
    pv = stats.binomtest(n_better, len(keep), 0.5).pvalue
    print(f"  median divergence (self minus measured) {100*keep.divergence.median():+.1f} pp; "
          f"{n_better} of {len(keep)} report a better trend than measured "
          f"(binomial p = {pv:.3f} against a coin flip)")
    w = stats.wilcoxon(keep.self_chg, keep.meas_chg)
    print(f"  Wilcoxon signed rank on the paired changes: p = {w.pvalue:.3f}")

    # Where does the reported improvement actually sit: in the part EPA measures, or in
    # the part only the company can see? The remainder is everything outside the measured
    # US perimeter, which is what a reader has to take on trust.
    rem = keep[(keep.self_tonnes_19 > keep.meas_fossil_equity_19)
               & (keep.self_tonnes_23 > keep.meas_fossil_equity_23)].copy()
    rem["rem_19"] = rem.self_tonnes_19 - rem.meas_fossil_equity_19
    rem["rem_23"] = rem.self_tonnes_23 - rem.meas_fossil_equity_23
    rem["rem_chg"] = rem.rem_23 / rem.rem_19 - 1
    print(f"  splitting the reported figure into the EPA-measured US part and the rest, "
          f"n = {len(rem)}")
    print(f"    measured US part      median change {100*rem.meas_chg.median():+6.1f}%")
    print(f"    everything else       median change {100*rem.rem_chg.median():+6.1f}%")
    print(f"    reported total        median change {100*rem.self_chg.median():+6.1f}%")
    agg19 = rem.meas_fossil_equity_19.sum(); agg23 = rem.meas_fossil_equity_23.sum()
    s19 = rem.self_tonnes_19.sum(); s23 = rem.self_tonnes_23.sum()
    wr = stats.wilcoxon(rem.rem_chg, rem.meas_chg)
    print(f"    Wilcoxon, remainder change against measured change: p = {wr.pvalue:.3f}")
    print(f"    on aggregate tonnes: measured US {100*(agg23/agg19-1):+.1f}%, "
          f"reported total {100*(s23/s19-1):+.1f}%, "
          f"remainder {100*(((s23-agg23)/(s19-agg19))-1):+.1f}%")

    # ---------------------------------------------------------------- scope 2 and 3
    print(f"\n{'='*100}\nWHAT WBA DOES TO THE SCOPE 2 AND SCOPE 3 HOLE\n{'='*100}")
    uni = pd.read_parquet(INTERIM / "universe.parquet")
    uni = uni[uni.is_primary_listing]
    n_co = len(uni)
    sc = pd.read_parquet(INTERIM / "scope23.parquet")
    sc = sc[sc.is_primary_listing & sc.tonnes_co2e.notna()]
    old2 = set(sc[sc.scope.str.startswith("2_") & ~sc.scope.str.contains("factor_input")].ticker)
    old3 = set(sc[sc.scope.str.startswith("3")].ticker)
    old1 = set(sc[sc.scope == "1"].ticker)
    we = pd.read_parquet(INTERIM / "wba_emissions.parquet")
    new2 = set(we[(we.scope == "2") & we.tonnes_co2e.notna()].ticker)
    new3 = set(we[(we.scope == "3") & we.tonnes_co2e.notna()].ticker)
    em = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    em = em[em.is_primary_listing]
    meas1 = set(em[em.scope1_ghgrp_tonnes.fillna(0) > 0].ticker) | \
            set(em[em.scope1_camd_tonnes.fillna(0) > 0].ticker)
    rows = []
    for name, old, new in (("Scope 2", old2, new2), ("Scope 3", old3, new3)):
        both = old | new
        print(f"  {name:<8} before WBA {len(old):>4} / {n_co}   WBA {len(new):>4}   "
              f"union {len(both):>4}   WBA adds {len(new - old):>4} companies "
              f"({100*len(new-old)/n_co:.0f} pp of the index)")
        rows.append({"layer": name, "before": len(old), "wba": len(new),
                     "union": len(both), "added": len(new - old), "universe": n_co})
    print(f"  Scope 1  measured (GHGRP or CAMD) {len(meas1)}, voluntary before WBA {len(old1)}, "
          f"WBA {we[(we.scope=='1')].ticker.nunique()}")
    anyscope_before = old1 | old2 | old3 | meas1
    anyscope_after = anyscope_before | new2 | new3 | set(we.ticker)
    print(f"  any emissions number at all: {len(anyscope_before)} before, "
          f"{len(anyscope_after)} after, silence falls from {n_co-len(anyscope_before)} "
          f"to {n_co-len(anyscope_after)} companies")
    still = sorted(set(uni.ticker) - anyscope_after)
    print(f"  still no number of any kind: {len(still)} companies")

    # What WBA's Scope 2 and 3 cannot do.
    wc = pd.read_parquet(INTERIM / "wba_company.parquet")
    print(f"  WBA Scope 2 is one year per company, the climate profile year: "
          f"{dict(wc.climate_profile_year.value_counts().sort_index().astype(int))}")
    print(f"  it carries no location/market label of its own; the basis has to be read off "
          f"available_emissions (S2.LB / S2.MB) per company")
    lb = wc.available_emissions.fillna("").str.contains("S2.LB").sum()
    mb = wc.available_emissions.fillna("").str.contains("S2.MB").sum()
    both_b = int((wc.available_emissions.fillna("").str.contains("S2.LB", regex=False)
                  & wc.available_emissions.fillna("").str.contains("S2.MB", regex=False)).sum())
    print(f"    {lb} companies list a location-based figure as available, {mb} a market-based "
          f"one, {both_b} both, so for most the basis of the profile figure is unknowable")
    print(f"  WBA Scope 3 is a single total; no category split anywhere in the feed, so the "
          f"7-company category-level coverage does not improve")
    print(f"  WBA Scope 3 time series {we[(we.scope=='3')&(we.source_table=='emissions_timeseries')].ticker.nunique()} "
          f"tickers over {sorted(we[(we.scope=='3')&(we.source_table=='emissions_timeseries')].fy.unique())}")

    # ---------------------------------------------------------------- the sentence
    print(f"\n{'='*100}\nTHE SENTENCE, AT EVERY LEVEL OF RIGOUR\n{'='*100}")
    for label, t, surv in (("A  self-reported Scope 1", tA, survA),
                           ("B  self-reported Scope 1+2", tB, survB)):
        print(f"  {label}   n = {len(t)}")
        for col, name in (("ratio_headline", "EPA's published CO2e, biogenic included"),
                          ("ratio_fossil", "fossil CO2e only"),
                          ("ratio_floor", "fossil CO2e at wholly owned facilities"),
                          ("ratio_floor_ar6", "that floor rolled to the reported year, AR6")):
            b = t[t[col] < 1]
            med = (1 - b[col]).median() if len(b) else float("nan")
            print(f"    below {name:<46} {len(b):>3} of {len(t)} "
                  f"({100*len(b)/len(t):>3.0f}%), median shortfall "
                  f"{100*med:>5.1f}%" if len(b) else
                  f"    below {name:<46}   0 of {len(t)}")
        med = (100 * surv.shortfall_pct.median()) if len(surv) else float("nan")
        lo, hi = wilson(len(surv), len(t))
        print(f"    after also dropping perimeter changes, subpart I F-gas figures and "
              f"sub-volatility gaps: {len(surv)} of {len(t)} "
              f"({100*len(surv)/len(t):.0f}%, Wilson 95% CI {100*lo:.0f}-{100*hi:.0f}%), "
              f"median shortfall {med:.1f}%")

    # ---------------------------------------------------------------- write
    keepcols = ["ticker", "company_name", "gics_sector", "mode", "self_scope", "fy",
                "self_tonnes", "estimated_flag", "year", "year_gap",
                "meas_all_equity", "meas_fossil_equity", "meas_biogenic_equity",
                "meas_fossil_whollyowned", "meas_fossil_partialowned",
                "meas_fossil_unapportioned", "meas_fossil_ar6",
                "meas_floor_rolled", "floor_roll_factor",
                "biogenic_share", "fgas_share", "partial_owned_share", "offname_share",
                "lookahead_share", "yoy_volatility", "largest_site_fossil",
                "shortfall_lt_largest_site",
                "facility_count", "parent_families",
                "ratio_headline", "ratio_fossil", "ratio_floor", "ratio_ar6",
                "ratio_floor_ar6", "shortfall_tonnes", "shortfall_pct",
                "beats_own_volatility", "fgas_dominated", "lookahead_flag",
                "countries_of_operation", "ct_nonus_share_balanced", "hq_country_iso",
                "fy_end_month", "calendar_fy", "camd_2023", "camd_2024",
                "camd_2024_over_2023", "disclosure_level", "independently_verified",
                "consistent_s1x2_data", "climate_profile_year"]
    out = pd.concat([j1[keepcols], j12[keepcols]], ignore_index=True)
    out["understates_after_all_adjustments"] = (
        (out.ratio_floor_ar6 < 1) & (out.year_gap <= 1) & ~out.lookahead_flag
        & ~out.fgas_dominated & out.beats_own_volatility)
    out["self_provenance_class"] = "voluntary"
    out["measured_provenance_class"] = "mandatory"
    out["gwp_basis_measured"] = "AR4"
    out.to_parquet(INTERIM / "reported_vs_measured.parquet", index=False)
    print(f"\nwrote data/interim/reported_vs_measured.parquet  {len(out):,} rows x "
          f"{out.shape[1]} cols  ({out.ticker.nunique()} tickers)")
    print(f"  test A rows {int((out['mode']=='nearest').sum())}, "
          f"test B rows {int((out['mode']=='exact').sum())}, "
          f"flagged understating {int(out.understates_after_all_adjustments.sum())}")


if __name__ == "__main__":
    main()
