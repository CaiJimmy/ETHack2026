"""Earnings at risk: measured Scope 1 tonnes repriced as a share of operating income.

EaR = measured Scope 1 tonnes x carbon price / operating income, per company, per NGFS
scenario, per year, plus a scenario-free sweep at fixed shadow prices.

What this is NOT. It is an exposure measure, not a forecast of profit impact: it assumes no
abatement, no pass-through to customers, no free allocation and no change in output, and it
prices only the US Scope 1 tonnes a company reports to the EPA under legal penalty, so a
company with foreign facilities pays for tonnes this number cannot see.

Inputs, all mandatory-disclosure or public-model:
  emissions_by_ticker.parquet  EPA GHGRP Scope 1, mandatory, the measured tonnage
  financials.parquet           SEC XBRL operating income, mandatory, latest fiscal year
  ngfs_scenarios.parquet       NGFS Phase 5 Price|Carbon, United States, 7 scenarios

Nothing carrying provenance_class 'vendor' is read here.

Outputs:
  data/interim/earnings_at_risk.parquet   503 listings x 7 scenarios x 13 years
  site/data/ear.json                      what the static site renders
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
SITE = ROOT / "site" / "data"

# No stochastic step in this module. The seed is written to the output anyway so a rerun that
# later adds one is still reproducible.
SEED = 20260912

# The NGFS publishes one carbon price per model, and the models disagree by a factor of five.
# Pin one: REMIND-MAgPIE 3.3-4.8, its own United States region, the native (not downscaled) run,
# and not the IntegratedPhysicalDamages variant, which NGFS retracted.
PRICE_VARIABLE = "Price|Carbon"
PRICE_MODEL = "REMIND-MAgPIE 3.3-4.8"
PRICE_REGION_US = "REMIND-MAgPIE 3.3-4.8|United States of America"
PRICE_REGION_WORLD = "World"

# Shadow prices for the scenario-free sweep, US$/tCO2. 130 is roughly the US EPA 2023 social
# cost of carbon for 2030 emissions; 300 is a policy-relevant midpoint; 749 is the NGFS Net Zero
# 2050 world price in 2050.
SWEEP_PRICES = [25, 50, 100, 130, 200, 300, 500, 749, 1000]
HEADLINE_PRICES = [130, 300, 749]
NAMED_LIST_PRICE = 300
NAMED_LIST_THRESHOLD = 25.0

# A ratio with a denominator this thin is arithmetic, not information. Flag it, never hide it.
THIN_MARGIN_FRACTION = 0.01
EAR_CAP_PCT = 200.0

CAVEAT = (
    "Exposure, not a forecast of profit impact. It assumes no abatement, no pass-through to "
    "customers and no free allocation, and it prices only US Scope 1 tonnes reported to the EPA "
    "under legal penalty. A company pays for its foreign tonnes too; this number cannot see them."
)


def load_price_paths() -> tuple[pd.DataFrame, pd.DataFrame]:
    ngfs = pd.read_parquet(INTERIM / "ngfs_scenarios.parquet")
    base = ngfs[
        (ngfs.variable == PRICE_VARIABLE)
        & (ngfs.model == PRICE_MODEL)
        & (~ngfs.is_downscaled)
        & (~ngfs.retracted_damage_basis)
    ]
    us = base[base.region == PRICE_REGION_US].copy()
    world = base[base.region == PRICE_REGION_WORLD].copy()
    cols = ["scenario", "scenario_key", "year", "value", "unit"]
    us = us[cols].rename(columns={"value": "carbon_price_usd"}).sort_values(["scenario", "year"])
    world = world[cols].rename(columns={"value": "carbon_price_usd"}).sort_values(["scenario", "year"])
    return us.reset_index(drop=True), world.reset_index(drop=True)


def print_path(df: pd.DataFrame, label: str) -> None:
    wide = df.pivot_table(index="year", columns="scenario", values="carbon_price_usd")
    print(f"\n{label}  ({df.unit.iloc[0]})")
    print(wide.round(1).to_string())


def load_operating_income() -> pd.DataFrame:
    fin = pd.read_parquet(INTERIM / "financials.parquet")
    have = fin[fin.operating_income.notna()]
    latest = have.sort_values("fy").groupby("ticker", as_index=False).tail(1)
    latest = latest[["ticker", "fy", "period_end", "revenue", "operating_income", "dq",
                     "operating_income_method"]]
    latest = latest.rename(columns={
        "fy": "fy_operating_income",
        "operating_income": "operating_income_usd",
        "dq": "dq_financials",
        "operating_income_method": "oi_method",
    })

    # Cyclicals swing through zero. A three-year mean is the sensitivity that answers
    # "your denominator happened to be negative in one bad year".
    recent = have[have.fy >= have.fy.max() - 2]
    mean3 = recent.groupby("ticker").agg(
        operating_income_mean3_usd=("operating_income", "mean"),
        n_years_mean3=("operating_income", "size"),
    ).reset_index()
    return latest.merge(mean3, on="ticker", how="left")


def load_measured_scope1() -> pd.DataFrame:
    em = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    ghgrp = em[em.scope1_ghgrp_tonnes.notna()]
    latest = ghgrp.sort_values("year").groupby("ticker", as_index=False).tail(1)
    latest = latest[["ticker", "year", "scope1_ghgrp_tonnes", "dq_ghgrp", "facility_count"]]
    latest = latest.rename(columns={
        "year": "emissions_year",
        "scope1_ghgrp_tonnes": "scope1_tonnes",
        "dq_ghgrp": "dq_emissions",
    })
    latest["dq_emissions"] = latest["dq_emissions"].astype("float64")
    latest["emissions_source"] = "EPA GHGRP"
    latest["provenance_class"] = "mandatory"

    # CAMD is the only current feed, and every CAMD ticker is already a GHGRP ticker. Carried as
    # a currency check on the 2023 spine, never as the EaR numerator.
    camd = em[em.scope1_camd_tonnes.notna() & (em.year == 2025)]
    camd = camd[["ticker", "scope1_camd_tonnes"]].rename(
        columns={"scope1_camd_tonnes": "scope1_camd_2025_tonnes"})
    return latest.merge(camd, on="ticker", how="left")


def load_voluntary_scope1() -> set[str]:
    s23 = pd.read_parquet(INTERIM / "scope23.parquet")
    vol = s23[(s23.scope == "1") & s23.tonnes_co2e.notna()]
    return set(vol.ticker.unique())


def build_spine() -> pd.DataFrame:
    uni = pd.read_parquet(INTERIM / "universe.parquet")
    spine = uni[["ticker", "company_name", "gics_sector", "is_primary_listing"]].copy()

    spine = spine.merge(load_measured_scope1(), on="ticker", how="left")
    spine = spine.merge(load_operating_income(), on="ticker", how="left")

    voluntary = load_voluntary_scope1()
    measured = spine.scope1_tonnes.notna()
    reported = ~measured & spine.ticker.isin(voluntary)
    spine["coverage_tier"] = np.where(measured, "measured",
                              np.where(reported, "reported", "unmeasurable"))

    # PCAF convention, worst component wins. Only the measured tier gets a number at all.
    spine["dq"] = spine[["dq_emissions", "dq_financials"]].max(axis=1)
    spine.loc[~measured, "dq"] = np.nan

    oi = spine.operating_income_usd
    rev = spine.revenue
    spine["oi_flag"] = np.where(
        oi.isna(), "missing",
        np.where(oi <= 0, "non_positive",
                 np.where(oi < THIN_MARGIN_FRACTION * rev, "thin_margin", "ok")))

    # Not every 10-K carries an OperatingIncomeLoss line. Where the financials lane had to derive
    # one, the denominator is a proxy and the ratio inherits its error. Say so on the row.
    spine["oi_reported"] = spine.oi_method.eq("reported")
    return spine


def build_panel(spine: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    panel = spine.merge(prices, how="cross")
    panel["carbon_cost_usd"] = panel.scope1_tonnes * panel.carbon_price_usd

    usable = panel.operating_income_usd > 0
    panel["ear_pct"] = np.where(
        usable, panel.carbon_cost_usd / panel.operating_income_usd * 100.0, np.nan)
    panel["ear_capped"] = panel.ear_pct > EAR_CAP_PCT
    panel["ear_pct_capped"] = panel.ear_pct.clip(upper=EAR_CAP_PCT)

    usable3 = panel.operating_income_mean3_usd > 0
    panel["ear_pct_oi3"] = np.where(
        usable3, panel.carbon_cost_usd / panel.operating_income_mean3_usd * 100.0, np.nan)

    cols = [
        "ticker", "company_name", "gics_sector", "is_primary_listing",
        "scenario", "scenario_key", "year", "carbon_price_usd", "unit",
        "scope1_tonnes", "emissions_year", "emissions_source", "scope1_camd_2025_tonnes",
        "carbon_cost_usd", "operating_income_usd", "fy_operating_income",
        "operating_income_mean3_usd", "revenue", "oi_method", "oi_reported",
        "ear_pct", "ear_pct_capped", "ear_capped", "ear_pct_oi3",
        "oi_flag", "coverage_tier", "dq", "dq_emissions", "dq_financials", "provenance_class",
    ]
    return panel[cols].sort_values(["ticker", "scenario", "year"]).reset_index(drop=True)


def sweep(spine: pd.DataFrame, prices: list[int]) -> pd.DataFrame:
    m = spine[(spine.coverage_tier == "measured") & spine.is_primary_listing].copy()
    rows = []
    for p in prices:
        cost = m.scope1_tonnes * p
        ear = np.where(m.operating_income_usd > 0,
                       cost / m.operating_income_usd * 100.0, np.nan)
        ear3 = np.where(m.operating_income_mean3_usd > 0,
                        cost / m.operating_income_mean3_usd * 100.0, np.nan)
        rows.append(pd.DataFrame({
            "ticker": m.ticker.values, "company_name": m.company_name.values,
            "gics_sector": m.gics_sector.values, "carbon_price_usd": p,
            "scope1_tonnes": m.scope1_tonnes.values,
            "carbon_cost_usd": cost.values,
            "operating_income_usd": m.operating_income_usd.values,
            "operating_income_mean3_usd": m.operating_income_mean3_usd.values,
            "ear_pct": ear, "ear_pct_oi3": ear3, "oi_flag": m.oi_flag.values,
            "oi_method": m.oi_method.values, "oi_reported": m.oi_reported.values,
            "dq": m.dq.values,
        }))
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    us_prices, world_prices = load_price_paths()
    print(f"seed {SEED}")
    print(f"carbon price: variable '{PRICE_VARIABLE}', model '{PRICE_MODEL}', "
          f"region '{PRICE_REGION_US}', native run, damage-basis rows excluded")
    print(f"{us_prices.scenario.nunique()} scenarios x {us_prices.year.nunique()} years "
          f"= {len(us_prices)} price points")
    print_path(us_prices, "UNITED STATES carbon price path, the one used")
    print_path(world_prices, "WORLD carbon price path, same model, for reference only")

    nz_us = us_prices[us_prices.scenario_key == "net_zero_2050"].set_index("year").carbon_price_usd
    nz_w = world_prices[world_prices.scenario_key == "net_zero_2050"].set_index("year").carbon_price_usd
    cp_w = world_prices[world_prices.scenario_key == "current_policies"].set_index("year").carbon_price_usd
    print(f"\nBRIEF CHECK. The brief quotes Net Zero 2050 at ~$98 in 2025 rising to $749 by 2050 "
          f"against $11 under Current Policies.")
    print(f"  World  NZ2050: 2025 ${nz_w[2025]:.1f}  2050 ${nz_w[2050]:.1f};  "
          f"Current Policies 2050 ${cp_w[2050]:.1f}  -> this is the match")
    print(f"  US     NZ2050: 2025 ${nz_us[2025]:.1f}  2050 ${nz_us[2050]:.1f}")
    print("  Those quoted figures are the WORLD path, not the United States path. "
          "The US path is used below because the tonnes are US tonnes.")

    spine = build_spine()
    print(f"\nspine: {len(spine)} listings, {int(spine.is_primary_listing.sum())} primary")
    tiers = spine[spine.is_primary_listing].coverage_tier.value_counts()
    tiers_all = spine.coverage_tier.value_counts()
    print("coverage_tier over 503 listings:", tiers_all.to_dict())
    print("coverage_tier over 500 primary:", tiers.to_dict())
    print(f"operating income present: {int(spine.operating_income_usd.notna().sum())}/503, "
          f"missing: {sorted(spine[spine.operating_income_usd.isna()].ticker)}")
    fy_counts = spine.fy_operating_income.value_counts().sort_index()
    print("latest fiscal year used:", {int(k): int(v) for k, v in fy_counts.items()})

    meas = spine[spine.coverage_tier == "measured"]
    stale = meas[meas.emissions_year < 2023]
    print(f"\nmeasured tier: {len(meas)} listings, "
          f"{meas.scope1_tonnes.sum()/1e6:,.1f} MMT Scope 1 at the latest reported year")
    print(f"  emissions year 2023: {int((meas.emissions_year == 2023).sum())}, "
          f"older: {len(stale)} -> {sorted(zip(stale.ticker, stale.emissions_year.astype(int)))}")
    print("  operating income flags:", meas.oi_flag.value_counts().to_dict())
    nonpos = meas[meas.oi_flag == "non_positive"].sort_values("scope1_tonnes", ascending=False)
    print(f"  {len(nonpos)} measured companies have non-positive operating income at the latest "
          f"fiscal year, so EaR is undefined for them and is published as null, not as a ratio:")
    for r in nonpos.itertuples():
        m3 = r.operating_income_mean3_usd
        print(f"    {r.ticker:6s} {r.company_name[:34]:34s} FY{int(r.fy_operating_income)} "
              f"OI ${r.operating_income_usd/1e9:8.2f}bn  3y mean ${m3/1e9:7.2f}bn  "
              f"{r.scope1_tonnes/1e6:8.2f} MMT")
    thin = meas[meas.oi_flag == "thin_margin"].sort_values("scope1_tonnes", ascending=False)
    print(f"  {len(thin)} measured companies have a positive but thin operating margin "
          f"(< {THIN_MARGIN_FRACTION:.0%} of revenue), where the ratio is unstable:")
    for r in thin.itertuples():
        print(f"    {r.ticker:6s} {r.company_name[:34]:34s} OI ${r.operating_income_usd/1e9:6.2f}bn "
              f"on ${r.revenue/1e9:8.1f}bn revenue, {r.scope1_tonnes/1e6:8.2f} MMT, "
              f"tag method '{r.oi_method}'")
    proxy = meas[~meas.oi_reported]
    print(f"  {len(proxy)} of {len(meas)} measured companies have no OperatingIncomeLoss line in "
          f"their filing, so the denominator is a derived proxy and the ratio inherits its error: "
          f"{meas.oi_method.value_counts().to_dict()}")
    big_proxy = proxy.nlargest(8, "scope1_tonnes")
    for r in big_proxy.itertuples():
        print(f"    {r.ticker:6s} {r.company_name[:34]:34s} {r.oi_method:16s} "
              f"OI ${r.operating_income_usd/1e9:7.2f}bn  {r.scope1_tonnes/1e6:7.2f} MMT")

    panel = build_panel(spine, us_prices)
    print(f"\npanel: {len(panel):,} rows = {spine.ticker.nunique()} listings x "
          f"{us_prices.scenario.nunique()} scenarios x {us_prices.year.nunique()} years")
    print(f"  rows with an EaR number: {int(panel.ear_pct.notna().sum()):,}; "
          f"rows capped at {EAR_CAP_PCT:.0f}%: {int(panel.ear_capped.sum()):,}")

    sw = sweep(spine, SWEEP_PRICES)
    print("\nDISTRIBUTION OF EaR ACROSS THE 139 MEASURED COMPANIES, by shadow price")
    print("  (126 with positive operating income; the 13 with a loss are excluded from the "
          "percentiles and named above)")
    hdr = (f"{'price':>6} {'n':>4} {'median':>8} {'p75':>8} {'p90':>8} {'p95':>8} {'max':>9} "
           f"{'>5%':>5} {'>10%':>5} {'>25%':>5} {'>100%':>6}")
    print(hdr)
    for p in SWEEP_PRICES:
        s = sw[(sw.carbon_price_usd == p) & sw.ear_pct.notna()].ear_pct
        print(f"{p:>6} {len(s):>4} {s.median():>8.2f} {s.quantile(.75):>8.2f} "
              f"{s.quantile(.90):>8.2f} {s.quantile(.95):>8.2f} {s.max():>9.1f} "
              f"{int((s > 5).sum()):>5} {int((s > 10).sum()):>5} {int((s > 25).sum()):>5} "
              f"{int((s > 100).sum()):>6}")

    print("\nSame distribution on a three-year mean operating income, the cyclicality check")
    print(hdr)
    for p in SWEEP_PRICES:
        s = sw[(sw.carbon_price_usd == p) & sw.ear_pct_oi3.notna()].ear_pct_oi3
        print(f"{p:>6} {len(s):>4} {s.median():>8.2f} {s.quantile(.75):>8.2f} "
              f"{s.quantile(.90):>8.2f} {s.quantile(.95):>8.2f} {s.max():>9.1f} "
              f"{int((s > 5).sum()):>5} {int((s > 10).sum()):>5} {int((s > 25).sum()):>5} "
              f"{int((s > 100).sum()):>6}")

    named = sw[(sw.carbon_price_usd == NAMED_LIST_PRICE) &
               (sw.ear_pct > NAMED_LIST_THRESHOLD)].sort_values("ear_pct", ascending=False)
    print(f"\nAT ${NAMED_LIST_PRICE}/tCO2, CARBON COST EXCEEDS {NAMED_LIST_THRESHOLD:.0f}% OF "
          f"OPERATING INCOME. {len(named)} companies:")
    print(f"{'ticker':>6} {'company':34s} {'sector':22s} {'MMT':>7} {'cost $bn':>9} "
          f"{'OI $bn':>8} {'EaR %':>9} {'EaR3 %':>8} {'flag':12s} oi_tag")
    for r in named.itertuples():
        print(f"{r.ticker:>6} {r.company_name[:34]:34s} {r.gics_sector[:22]:22s} "
              f"{r.scope1_tonnes/1e6:>7.2f} {r.carbon_cost_usd/1e9:>9.2f} "
              f"{r.operating_income_usd/1e9:>8.2f} {r.ear_pct:>9.1f} {r.ear_pct_oi3:>8.1f} "
              f"{r.oi_flag:12s} {r.oi_method}")
    for p in HEADLINE_PRICES:
        s_ = sw[(sw.carbon_price_usd == p) & sw.ear_pct.notna()].ear_pct
        print(f"  at ${p}/t: {int((s_ > 25).sum())} of {len(s_)} measured companies with a positive "
              f"operating income are over 25%, {int((s_ > 100).sum())} over 100%, "
              f"median {s_.median():.2f}%")

    print(f"\nLARGEST ABSOLUTE EXPOSURE at ${NAMED_LIST_PRICE}/tCO2, dollars not ratios")
    top_cost = sw[sw.carbon_price_usd == NAMED_LIST_PRICE].nlargest(15, "carbon_cost_usd")
    for r in top_cost.itertuples():
        ear = "n/a (loss)" if pd.isna(r.ear_pct) else f"{r.ear_pct:.0f}%"
        print(f"  {r.ticker:>6} {r.company_name[:32]:32s} {r.scope1_tonnes/1e6:>7.2f} MMT  "
              f"${r.carbon_cost_usd/1e9:>6.2f}bn  EaR {ear}")

    # Index aggregate. Dedupe to primary listings first or Alphabet, Fox and News Corp each
    # contribute their operating income twice.
    prim = spine[spine.is_primary_listing]
    oi_index = prim.operating_income_usd.sum()
    oi_index_pos = prim.loc[prim.operating_income_usd > 0, "operating_income_usd"].sum()
    m = prim[prim.coverage_tier == "measured"]
    oi_meas = m.operating_income_usd.sum()
    oi_meas_pos = m.loc[m.operating_income_usd > 0, "operating_income_usd"].sum()
    tonnes_meas = m.scope1_tonnes.sum()
    print(f"\nINDEX AGGREGATE. Denominators, {len(prim)} primary listings, latest fiscal year:")
    print(f"  total S&P 500 operating income        ${oi_index/1e9:,.0f}bn "
          f"(positive-only ${oi_index_pos/1e9:,.0f}bn)")
    print(f"  operating income of the {len(m)} measured   ${oi_meas/1e9:,.0f}bn "
          f"(positive-only ${oi_meas_pos/1e9:,.0f}bn), "
          f"{oi_meas/oi_index*100:.1f}% of the index")
    print(f"  measured Scope 1                      {tonnes_meas/1e6:,.1f} MMT")
    print(f"\n{'price':>6} {'carbon cost $bn':>16} {'% of measured OI':>17} {'% of index OI':>14}")
    for p in SWEEP_PRICES:
        cost = tonnes_meas * p
        print(f"{p:>6} {cost/1e9:>16,.1f} {cost/oi_meas*100:>17.2f} {cost/oi_index*100:>14.2f}")
    print("  Read this as: the carbon cost of the 139 listings we can measure, against the "
          "operating income of those same 139, and against the whole index. It is NOT the "
          "index's exposure, because 364 listings carry no measured Scope 1 tonne.")

    print("\nBY SECTOR at $300/tCO2, measured companies, primary listings.")
    print("The ratio is taken over the profitable members only; loss-makers would otherwise put a "
          "negative number in the denominator, which is how Consumer Discretionary reads -43%.")
    s300 = sw[sw.carbon_price_usd == 300].copy()
    s300["profitable"] = s300.operating_income_usd > 0
    bysec = s300.groupby("gics_sector").apply(lambda g: pd.Series({
        "n": len(g),
        "n_loss": int((~g.profitable).sum()),
        "mmt": g.scope1_tonnes.sum() / 1e6,
        "cost_bn": g.carbon_cost_usd.sum() / 1e9,
        "oi_bn_profitable": g.loc[g.profitable, "operating_income_usd"].sum() / 1e9,
        "cost_bn_profitable": g.loc[g.profitable, "carbon_cost_usd"].sum() / 1e9,
    }), include_groups=False).reset_index()
    bysec["ear_pct_profitable"] = bysec.cost_bn_profitable / bysec.oi_bn_profitable * 100
    bysec[["n", "n_loss"]] = bysec[["n", "n_loss"]].astype(int)
    bysec = bysec.sort_values("cost_bn", ascending=False)
    print(bysec.round(2).to_string(index=False))

    print("\nSCENARIO AGGREGATE, share of the measured 139's operating income, by year")
    agg_rows = []
    for (scen, key), grp in us_prices.groupby(["scenario", "scenario_key"]):
        for r in grp.itertuples():
            cost = tonnes_meas * r.carbon_price_usd
            agg_rows.append({"scenario": scen, "scenario_key": key, "year": int(r.year),
                             "carbon_price_usd": float(r.carbon_price_usd),
                             "carbon_cost_usd": float(cost),
                             "pct_of_measured_operating_income": float(cost / oi_meas * 100),
                             "pct_of_index_operating_income": float(cost / oi_index * 100)})
    agg = pd.DataFrame(agg_rows)
    show = agg[agg.year.isin([2025, 2030, 2035, 2040, 2045, 2050])]
    print(show.pivot_table(index="year", columns="scenario",
                           values="pct_of_measured_operating_income").round(1).to_string())

    INTERIM.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(INTERIM / "earnings_at_risk.parquet", index=False)
    print(f"\nwrote {INTERIM / 'earnings_at_risk.parquet'}  {len(panel):,} rows")

    def company_block(row) -> dict:
        d = {
            "ticker": row.ticker,
            "company_name": row.company_name,
            "gics_sector": row.gics_sector,
            "coverage_tier": row.coverage_tier,
        }
        if row.coverage_tier == "measured":
            d.update({
                "scope1_tonnes": float(row.scope1_tonnes),
                "emissions_year": int(row.emissions_year),
                "emissions_source": row.emissions_source,
                "operating_income_usd": None if pd.isna(row.operating_income_usd) else float(row.operating_income_usd),
                "operating_income_mean3_usd": None if pd.isna(row.operating_income_mean3_usd) else float(row.operating_income_mean3_usd),
                "fy": None if pd.isna(row.fy_operating_income) else int(row.fy_operating_income),
                "oi_flag": row.oi_flag,
                "oi_method": row.oi_method,
                "oi_reported": bool(row.oi_reported),
                "dq": None if pd.isna(row.dq) else float(row.dq),
                "ear_pct_by_price": {
                    str(p): (None if pd.isna(row.operating_income_usd) or row.operating_income_usd <= 0
                             else round(row.scope1_tonnes * p / row.operating_income_usd * 100, 3))
                    for p in SWEEP_PRICES},
                "ear_pct_oi3_by_price": {
                    str(p): (None if pd.isna(row.operating_income_mean3_usd) or row.operating_income_mean3_usd <= 0
                             else round(row.scope1_tonnes * p / row.operating_income_mean3_usd * 100, 3))
                    for p in SWEEP_PRICES},
            })
        return d

    out = {
        "meta": {
            "seed": SEED,
            "what_this_is": "Measured Scope 1 tonnes repriced as a share of operating income.",
            "caveat": CAVEAT,
            "formula": "EaR = measured Scope 1 tonnes x carbon price / operating income",
            "emissions_source": "EPA GHGRP, mandatory reporting under 40 CFR Part 98",
            "financial_source": "SEC XBRL companyfacts, latest fiscal year with a reported operating income",
            "price_source": {
                "dataset": "NGFS Phase 5 (November 2024), IIASA NGFS Scenario Explorer",
                "variable": PRICE_VARIABLE,
                "model": PRICE_MODEL,
                "region": PRICE_REGION_US,
                "unit": us_prices.unit.iloc[0],
                "downscaled": False,
                "damage_basis_excluded": True,
            },
            "price_unit_note": (
                "NGFS publishes carbon prices in US$2010/tCO2 and SEC operating income is nominal. "
                "Deflating one to the other scales every figure here by a single constant."),
            "scope_note": "US Scope 1 only. Foreign facilities and Scope 2 and 3 are outside this number.",
            "coverage_note": (
                "139 of 503 listings carry a mandatory measured Scope 1 tonnage. 87 more carry only a "
                "voluntary one and are marked 'reported'. 277 carry no Scope 1 number from any source "
                "and are marked 'unmeasurable'. We never invent a tonne for them."),
            "cap_pct": EAR_CAP_PCT,
            "thin_margin_fraction": THIN_MARGIN_FRACTION,
        },
        "coverage": {
            "listings": int(len(spine)),
            "primary_listings": int(spine.is_primary_listing.sum()),
            "by_tier_all_listings": {k: int(v) for k, v in tiers_all.items()},
            "by_tier_primary": {k: int(v) for k, v in tiers.items()},
            "measured_with_positive_operating_income": int((meas.oi_flag == "ok").sum()),
            "measured_with_thin_margin": int((meas.oi_flag == "thin_margin").sum()),
            "measured_with_non_positive_operating_income": int((meas.oi_flag == "non_positive").sum()),
            "measured_with_proxy_operating_income": int((~meas.oi_reported).sum()),
            "measured_emissions_year_2023": int((meas.emissions_year == 2023).sum()),
            "measured_emissions_year_older": int(len(stale)),
            "measured_scope1_mmt": round(float(tonnes_meas) / 1e6, 2),
        },
        "price_paths_us": {
            key: [{"year": int(r.year), "carbon_price_usd": round(float(r.carbon_price_usd), 2)}
                  for r in grp.itertuples()]
            for key, grp in us_prices.groupby("scenario_key")},
        "price_paths_world_reference": {
            key: [{"year": int(r.year), "carbon_price_usd": round(float(r.carbon_price_usd), 2)}
                  for r in grp.itertuples()]
            for key, grp in world_prices.groupby("scenario_key")},
        "scenario_labels": dict(zip(us_prices.scenario_key, us_prices.scenario)),
        "sweep_prices": SWEEP_PRICES,
        "headline_prices": HEADLINE_PRICES,
        "distribution_by_price": [
            {
                "carbon_price_usd": p,
                "n": int(sw[(sw.carbon_price_usd == p) & sw.ear_pct.notna()].shape[0]),
                "median_pct": round(float(sw[(sw.carbon_price_usd == p)].ear_pct.median()), 3),
                "p75_pct": round(float(sw[(sw.carbon_price_usd == p)].ear_pct.quantile(.75)), 3),
                "p90_pct": round(float(sw[(sw.carbon_price_usd == p)].ear_pct.quantile(.90)), 3),
                "p95_pct": round(float(sw[(sw.carbon_price_usd == p)].ear_pct.quantile(.95)), 3),
                "max_pct": round(float(sw[(sw.carbon_price_usd == p)].ear_pct.max()), 3),
                "n_over_5pct": int((sw[(sw.carbon_price_usd == p)].ear_pct > 5).sum()),
                "n_over_10pct": int((sw[(sw.carbon_price_usd == p)].ear_pct > 10).sum()),
                "n_over_25pct": int((sw[(sw.carbon_price_usd == p)].ear_pct > 25).sum()),
                "n_over_100pct": int((sw[(sw.carbon_price_usd == p)].ear_pct > 100).sum()),
            } for p in SWEEP_PRICES],
        "index_aggregate": {
            "n_primary_listings": int(len(prim)),
            "n_measured": int(len(m)),
            "total_index_operating_income_usd": float(oi_index),
            "total_index_operating_income_positive_only_usd": float(oi_index_pos),
            "measured_operating_income_positive_only_usd": float(oi_meas_pos),
            "measured_operating_income_usd": float(oi_meas),
            "measured_scope1_tonnes": float(tonnes_meas),
            "note": ("Numerator is the carbon cost of the 139 listings with a measured tonnage. "
                     "Two denominators: those same 139, and the whole 500. Neither is the index's "
                     "true exposure, because 364 listings carry no measured tonne."),
            "by_price": [
                {"carbon_price_usd": p,
                 "carbon_cost_usd": float(tonnes_meas * p),
                 "pct_of_measured_operating_income": round(float(tonnes_meas * p / oi_meas * 100), 3),
                 "pct_of_index_operating_income": round(float(tonnes_meas * p / oi_index * 100), 3)}
                for p in SWEEP_PRICES],
        },
        "scenario_aggregate": agg.to_dict(orient="records"),
        "by_sector_at_300": bysec.round(4).to_dict(orient="records"),
        "largest_absolute_exposure_at_300": [
            {"ticker": r.ticker, "company_name": r.company_name,
             "scope1_tonnes": float(r.scope1_tonnes),
             "carbon_cost_usd": float(r.carbon_cost_usd),
             "ear_pct": None if pd.isna(r.ear_pct) else round(float(r.ear_pct), 2)}
            for r in top_cost.itertuples()],
        "over_threshold": {
            "carbon_price_usd": NAMED_LIST_PRICE,
            "threshold_pct": NAMED_LIST_THRESHOLD,
            "companies": [
                {"ticker": r.ticker, "company_name": r.company_name, "gics_sector": r.gics_sector,
                 "scope1_tonnes": float(r.scope1_tonnes),
                 "carbon_cost_usd": float(r.carbon_cost_usd),
                 "operating_income_usd": float(r.operating_income_usd),
                 "ear_pct": round(float(r.ear_pct), 2),
                 "ear_pct_oi3": None if pd.isna(r.ear_pct_oi3) else round(float(r.ear_pct_oi3), 2),
                 "oi_flag": r.oi_flag, "oi_method": r.oi_method,
                 "oi_reported": bool(r.oi_reported)}
                for r in named.itertuples()],
        },
        "operating_loss_at_latest_fy": {
            "note": ("EaR is undefined against a loss, so these carry a null ratio and a dollar "
                     "carbon cost instead."),
            "companies": [
                {"ticker": r.ticker, "company_name": r.company_name,
                 "fy": int(r.fy_operating_income),
                 "operating_income_usd": float(r.operating_income_usd),
                 "operating_income_mean3_usd": float(r.operating_income_mean3_usd),
                 "scope1_tonnes": float(r.scope1_tonnes),
                 "carbon_cost_usd_at_300": float(r.scope1_tonnes * 300),
                 "ear_pct_oi3_at_300": (None if r.operating_income_mean3_usd <= 0 else
                                        round(float(r.scope1_tonnes * 300 / r.operating_income_mean3_usd * 100), 2))}
                for r in nonpos.itertuples()],
        },
        "companies": [company_block(r) for r in spine.itertuples()],
    }

    path = SITE / "ear.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"wrote {path}  {path.stat().st_size/1024:.0f} KB, "
          f"{len(out['companies'])} company blocks")


if __name__ == "__main__":
    main()
