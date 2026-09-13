#!/usr/bin/env python3
"""Build jimmy-website/public/data/compare.json, the slider inputs for the comparison tab.

The browser prices four cost drivers with plain arithmetic:

    cost_musd = carbon_mt        * carbon_price
              + water_mt         * water_surcharge
              + conduct          * conduct_multiple
              + shortfall        * credibility_charge

Nothing is modelled here. Every coefficient is a column we already computed,
joined on ticker and rounded. Run:

    nix develop --command .venv/bin/python src/build_compare_json.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "jimmy-website/public/data/compare.json"
SIZE_LIMIT = 150 * 1024

MASTER = "data/master/master_company.parquet"
WATER = "data/interim/water_by_ticker.parquet"
VIOLATIONS = "data/interim/violations_summary.parquet"
SAYDO = "data/interim/say_do_gap.parquet"
EMISSIONS = "data/interim/emissions_by_ticker.parquet"
EAR = "data/interim/earnings_at_risk.parquet"
PARIS = "jimmy-website/public/data/paris.json"

DRIVER_IDS = ["carbon_price", "water_surcharge", "conduct_multiple", "credibility_charge"]
COEFFS = ["carbon_mt", "water_mt", "conduct", "shortfall"]
ROW_KEYS = ["name", "sec", "rev", "ebit", "evic", "mcap", "w_idx", "w_cap", "w_par",
            "in_par", "barred", "carbon_mt", "c_basis", "water_mt", "conduct", "shortfall", "cov"]


def r(x, nd):
    """Round to nd places, or return None for a missing value."""
    if x is None or pd.isna(x):
        return None
    v = round(float(x), nd)
    return int(v) if nd == 0 else v


def main() -> int:
    master = pd.read_parquet(ROOT / MASTER)
    water = pd.read_parquet(ROOT / WATER)
    viol = pd.read_parquet(ROOT / VIOLATIONS)
    saydo = pd.read_parquet(ROOT / SAYDO)
    emis = pd.read_parquet(ROOT / EMISSIONS)
    ear = pd.read_parquet(ROOT / EAR)
    paris = json.loads((ROOT / PARIS).read_text())

    # --- input invariants -------------------------------------------------
    for name, df in [("master", master), ("water", water), ("violations", viol), ("say_do_gap", saydo)]:
        assert not df.ticker.duplicated().any(), f"{name}: duplicate tickers"
    assert len(master) == 503, f"master has {len(master)} rows, expected 503"
    assert len(water) == 142, f"water has {len(water)} rows, expected 142"
    assert len(viol) == 503 and len(saydo) == 503
    assert master.revenue_musd.notna().all(), "revenue missing"
    assert set(water.scenario) == {"bau (SSP3 RCP7.0)"} and set(water.fleet_year) == {2023}

    # The gap we price is the one the rest of the site shows.
    both = master[["ticker", "gap_pct_yr"]].merge(saydo[["ticker", "gap_pct_yr"]], on="ticker", suffixes=("_m", "_s"))
    both = both.dropna()
    assert (both.gap_pct_yr_m - both.gap_pct_yr_s).abs().max() < 1e-6, "master and say_do_gap disagree"

    # The 35 companies with no violations record are the 35 with a null penalty.
    no_rec = viol.match_status.eq("no_records")
    assert (no_rec == viol.penalty_usd_environment_recent5.isna()).all(), "violations coverage flag mismatch"

    # Measured Scope 1 cross-check: where the basis is GHGRP, the master tonnage
    # is the measured US fleet for that year, and it never exceeds what the EPA
    # fleet reported. Companies with a facility dropped for the look ahead rule
    # sit below the fleet by more than rounding.
    ghgrp = emis.set_index(["ticker", "year"]).scope1_ghgrp_tonnes
    is_ghgrp = master.scope1_basis.fillna("").str.startswith("ghgrp")
    assert (master.loc[is_ghgrp, "scope1_t"] == master.loc[is_ghgrp, "scope1_measured_us_t"]).all()
    checked = 0
    for t, y, v, look in master.loc[is_ghgrp, ["ticker", "scope1_year", "scope1_t", "scope1_lookahead_excluded_t"]].itertuples(index=False):
        fleet = ghgrp.get((t, int(y)))
        assert fleet is not None and fleet > 0, f"{t} {y}: no GHGRP tonnage"
        assert v <= fleet * 1.0001, f"{t} {y}: master {v} above EPA fleet {fleet}"
        if not (look and look > 0):
            assert v >= fleet * 0.97, f"{t} {y}: master {v} far below EPA fleet {fleet}"
        checked += 1
    assert checked == 48, f"cross-checked {checked} GHGRP companies, expected 48"

    pc = paris["companies"]
    assert set(pc) <= set(master.ticker), "paris carries a ticker the master does not"
    assert abs(sum(c["w_cap_pct"] for c in pc.values()) - 100.0) < 0.05
    assert abs(sum(c["w_paris_pct"] for c in pc.values()) - 100.0) < 0.05
    head = paris["meta"]["headline"]
    assert sum(1 for c in pc.values() if c["in_paris"]) == head["n_held"]
    assert sum(1 for c in pc.values() if c["barred_by"]) == head["n_excluded"]

    # --- joins ------------------------------------------------------------
    df = master[[
        "ticker", "company_name", "gics_sector", "revenue_musd", "ebit_musd", "evic_musd",
        "market_cap_musd", "index_weight_pct", "scope1_t", "scope1_basis", "scope1_year", "gap_pct_yr",
    ]].copy()
    df = df.merge(water[["ticker", "share_co2e_high_water_stress", "share_facilities_high_water_stress"]], on="ticker", how="left")
    df = df.merge(viol[["ticker", "penalty_usd_environment_recent5", "match_status"]], on="ticker", how="left")

    df["carbon_mt"] = df.scope1_t / 1e6
    df["water_mt"] = df.carbon_mt * df.share_co2e_high_water_stress
    df["conduct"] = df.penalty_usd_environment_recent5 / 5.0 / 1e6
    df["shortfall"] = df.carbon_mt * df.gap_pct_yr.clip(lower=0)

    # --- coefficient invariants -------------------------------------------
    assert (df.carbon_mt.dropna() > 0).all(), "a carbon coefficient is not positive"
    assert (df.water_mt.dropna() >= 0).all() and (df.conduct.dropna() >= 0).all()
    assert (df.shortfall.dropna() >= 0).all()
    ok = df.water_mt.notna()
    assert (df.loc[ok, "water_mt"] <= df.loc[ok, "carbon_mt"] + 1e-9).all(), "stressed tonnes exceed total tonnes"
    assert df.loc[df.water_mt.notna(), "carbon_mt"].notna().all(), "water priced without carbon"
    assert df.loc[df.shortfall.notna(), "carbon_mt"].notna().all(), "shortfall priced without carbon"

    carbon_basis = {"self_reported": 0, "ghgrp_fossil": 1, "ghgrp_fossil_floor": 2, "climatetrace_equity": 3}
    assert set(df.scope1_basis.dropna()) <= set(carbon_basis), sorted(set(df.scope1_basis.dropna()))

    # --- companies --------------------------------------------------------
    # Keys are short because the file ships to the browser. meta.units names
    # every one of them.
    sectors = sorted(df.gics_sector.unique())
    sector_ix = {s: i for i, s in enumerate(sectors)}
    companies = {}
    for row in df.itertuples(index=False):
        p = pc.get(row.ticker)
        cov = [int(pd.notna(getattr(row, c))) for c in COEFFS]
        companies[row.ticker] = {
            "name": row.company_name,
            "sec": sector_ix[row.gics_sector],
            "rev": r(row.revenue_musd, 0),
            "ebit": r(row.ebit_musd, 0),
            "evic": r(row.evic_musd, 0),
            "mcap": r(row.market_cap_musd, 0),
            "w_idx": r(row.index_weight_pct, 4),
            "w_cap": r(p["w_cap_pct"], 4) if p else None,
            "w_par": r(p["w_paris_pct"], 4) if p else None,
            "in_par": bool(p["in_paris"]) if p else None,
            "barred": (p["barred_by"] if p else None),
            "carbon_mt": r(row.carbon_mt, 6),
            "c_basis": carbon_basis.get(row.scope1_basis) if pd.notna(row.scope1_basis) else None,
            "water_mt": r(row.water_mt, 6),
            "conduct": r(row.conduct, 4),
            "shortfall": r(row.shortfall, 4),
            "cov": cov,
        }

    assert len(companies) == 503
    assert len(sectors) == 11
    for t, c in companies.items():
        for i, key in enumerate(COEFFS):
            assert c["cov"][i] == int(c[key] is not None), f"{t}: cov flag disagrees with {key}"
        assert (c["c_basis"] is None) == (c["carbon_mt"] is None), f"{t}: basis and tonnes disagree"
        assert set(c) == set(ROW_KEYS), f"{t}: row keys drifted"
        assert sectors[c["sec"]] in sector_ix, f"{t}: sector index does not resolve"

    wsum = sum(c["w_idx"] for c in companies.values())
    assert abs(wsum - 100.0) < 0.05, wsum
    assert sum(1 for c in companies.values() if c["in_par"] is None) == 4, "expected 4 tickers outside paris.json"
    assert abs(sum(c["w_cap"] for c in companies.values() if c["w_cap"] is not None) - 100.0) < 0.05

    # --- coverage ---------------------------------------------------------
    def cover(i):
        held = [c for c in companies.values() if c["cov"][i]]
        return {
            "n_priced": len(held),
            "n_companies": len(companies),
            "pct_companies": round(100.0 * len(held) / len(companies), 1),
            "pct_index_weight": round(sum(c["w_idx"] for c in held), 1),
        }

    coverage = {DRIVER_IDS[i]: cover(i) for i in range(4)}
    coverage["carbon_price"]["note"] = (
        f"{int(df.scope1_basis.eq('self_reported').sum())} companies report the tonnage themselves, "
        f"{int(df.scope1_basis.str.startswith('ghgrp').fillna(False).sum())} are EPA measured, "
        f"{int(df.scope1_basis.eq('climatetrace_equity').sum())} is modelled. The rest have no Scope 1 number."
    )
    coverage["water_surcharge"]["note"] = (
        f"{len(water)} companies have a facility water stress share. "
        f"{int(water.share_co2e_high_water_stress.notna().sum())} of those also have the emissions weighted share this driver needs."
    )
    coverage["conduct_multiple"]["note"] = (
        f"{int(no_rec.sum())} companies have no record in the violations source and cannot be priced. "
        f"A priced zero is a measured zero: {int((df.conduct == 0).sum())} companies paid no environmental penalty in the last five years."
    )
    n_no_tonnes = int(df.gap_pct_yr.notna().sum() - df.shortfall.notna().sum())
    coverage["credibility_charge"]["note"] = (
        f"{int(saydo.gap_pct_yr.notna().sum())} companies have both a delivered trend and a promise. "
        f"{n_no_tonnes} of those {'has' if n_no_tonnes == 1 else 'have'} no Scope 1 tonnage to charge. "
        f"{int((df.gap_pct_yr < 0).sum())} are cutting faster than they promised and are charged zero."
    )

    ngfs_2030 = (
        ear[ear.year.eq(2030)].groupby("scenario").carbon_price_usd.first().round(0).astype(int).to_dict()
    )
    assert len(ngfs_2030) == 7, ngfs_2030

    per_musd = df.conduct * 1e6 / df.revenue_musd
    mmm_per_musd = float(per_musd[df.ticker.eq("MMM")].iloc[0])
    assert per_musd.median() == 0.0 and mmm_per_musd == per_musd.max()

    sliders = [
        {
            "id": "carbon_price",
            "label": "Carbon price",
            "unit": "US$ per tonne CO2e",
            "default": 100, "min": 0, "max": 500, "step": 5,
            "coefficient": "carbon_mt",
            "what": "Charges the company for every tonne of Scope 1 it emits.",
            "derivation": "scope1_t from the master table, divided by a million so that million tonnes times US$ per tonne gives US$ millions.",
            "reference_points": {
                "label": "NGFS Phase V price in 2030, US$2010 per tonne, from data/interim/earnings_at_risk.parquet",
                "prices": ngfs_2030,
            },
        },
        {
            "id": "water_surcharge",
            "label": "Water stress surcharge",
            "unit": "US$ per tonne CO2e emitted in a high water stress basin",
            "default": 0, "min": 0, "max": 100, "step": 5,
            "coefficient": "water_mt",
            "what": "Charges a second time for the part of the fleet that sits in a stressed basin.",
            "derivation": "carbon_mt times share_co2e_high_water_stress, the share of fleet CO2e in basins Aqueduct scores as high or extremely high baseline water stress, business as usual SSP3 RCP7.0 on the 2023 fleet.",
            "honesty": "We hold an exposure share and no water price. Any value on this slider is an assumption of yours, so the default is zero.",
        },
        {
            "id": "conduct_multiple",
            "label": "Conduct multiple",
            "unit": "multiples of the realised annual environmental penalty",
            "default": 1, "min": 0, "max": 5, "step": 0.25,
            "coefficient": "conduct",
            "what": "Repeats what the company already paid in environmental penalties.",
            "derivation": "penalty_usd_environment_recent5 over five years, in US$ millions per year. At the default of 1 the last five years repeat once.",
            "honesty": f"A few settlements dominate. 3M alone paid {mmm_per_musd:,.0f} US$ per US$ million of revenue per year over the last five years, while the median company paid nothing.",
        },
        {
            "id": "credibility_charge",
            "label": "Credibility charge",
            "unit": "US$ per tonne CO2e per percentage point of annual shortfall",
            "default": 0, "min": 0, "max": 10, "step": 0.5,
            "coefficient": "shortfall",
            "what": "Charges the distance between the cut a company promised each year and the cut it delivered.",
            "derivation": "carbon_mt times gap_pct_yr where the gap is positive. A positive gap is a company cutting slower than it promised. Companies ahead of their promise are charged zero rather than credited.",
        },
    ]
    assert [s["id"] for s in sliders] == DRIVER_IDS
    assert [s["coefficient"] for s in sliders] == COEFFS

    meta = {
        "what": "Per company cost coefficients for the comparison tab, so a slider can reprice the S&P 500 in the browser.",
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "built_by": "src/build_compare_json.py",
        "caveat": "Every coefficient here measures an exposure the company already carries. This file prices that exposure at a rate you choose. It forecasts nothing, and no slider position is a claim about any future price.",
        "cost_unit": "US$ millions per year",
        "join_key": "companies are keyed by ticker and join to the company rows of snapshot.json on that ticker.",
        "cost_formula": "cost_musd = carbon_mt * carbon_price + water_mt * water_surcharge + conduct * conduct_multiple + shortfall * credibility_charge",
        "how_to_use_coverage": "companies[ticker].cov is one flag per driver in the order [carbon_price, water_surcharge, conduct_multiple, credibility_charge]. A flag of 0 means we have no number and the coefficient is null. Grey the driver for that company. Do not read a null as a zero.",
        "units": {
            "name": "company name",
            "sec": "index into meta.sectors, the GICS sector",
            "rev": "revenue, US$ millions, latest fiscal year",
            "ebit": "operating income, US$ millions, latest fiscal year",
            "evic": "enterprise value including cash, US$ millions, market cap plus book total debt",
            "mcap": "market capitalisation, US$ millions",
            "w_idx": "weight in our cap weighted S&P 500, percent, 503 companies, sums to 100",
            "w_cap": "weight in the cap weighted index of paris.json, percent, 499 companies",
            "w_par": "weight in the Paris aligned index of paris.json, percent, 499 companies",
            "in_par": "true if the company survives the exclusion rules of EU 2020/1818",
            "barred": "the article that excluded it, null if held",
            "carbon_mt": "Scope 1, million tonnes CO2e",
            "c_basis": "index into meta.carbon_basis, where the Scope 1 tonnage comes from",
            "water_mt": "Scope 1 in high water stress basins, million tonnes CO2e",
            "conduct": "realised environmental penalty, US$ millions per year",
            "shortfall": "Scope 1 times the annual shortfall against the promise, million tonnes CO2e times percentage points per year",
            "cov": "one coverage flag per driver, in the order of meta.drivers",
        },
        "drivers": DRIVER_IDS,
        "coverage": coverage,
        "sectors": sectors,
        "carbon_basis": ["self reported", "EPA GHGRP measured", "EPA GHGRP floor", "Climate TRACE modelled"],
        "sources": [MASTER, WATER, VIOLATIONS, SAYDO, EMISSIONS, EAR, PARIS],
        "n_companies": len(companies),
    }

    payload = {"meta": meta, "sliders": sliders, "companies": companies}
    text = json.dumps(payload, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    size = len(text.encode("utf-8"))
    assert size < SIZE_LIMIT, f"{size} bytes over the {SIZE_LIMIT} limit"
    round_trip = json.loads(text)
    assert round_trip["companies"]["AAPL"]["name"] == "Apple Inc."
    OUT.write_text(text, encoding="utf-8")

    # --- report -----------------------------------------------------------
    print(f"wrote {OUT.relative_to(ROOT)}  {size:,} bytes  ({100*size/SIZE_LIMIT:.0f}% of the {SIZE_LIMIT//1024} KB limit)")
    print(f"{len(companies)} companies, {len(sliders)} drivers\n")
    print(f"{'driver':<20}{'coefficient':<18}{'priced':>8}{'of':>6}{'% cos':>8}{'% weight':>10}")
    print("-" * 70)
    for i, d in enumerate(DRIVER_IDS):
        c = coverage[d]
        print(f"{d:<20}{COEFFS[i]:<18}{c['n_priced']:>8}{c['n_companies']:>6}{c['pct_companies']:>8.1f}{c['pct_index_weight']:>10.1f}")
    print("-" * 70)
    for d in DRIVER_IDS:
        print(f"{d}: {coverage[d]['note']}")
    priceable = sum(1 for c in companies.values() if any(c["cov"]))
    print(f"\nat least one driver: {priceable} companies, "
          f"{sum(c['w_idx'] for c in companies.values() if any(c['cov'])):.1f}% of index weight")
    print(f"all four drivers: {sum(1 for c in companies.values() if all(c['cov']))} companies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
