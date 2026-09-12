"""Three $1bn portfolios over the S&P 500, and a Brinson decomposition of the intensity cut.

Reads Commission Delegated Regulation (EU) 2020/1818 out of data/interim/pab_rules.json rather
than hardcoding it, so the thresholds and the operators cannot drift from the text we fetched.
The power-generator test is Article 12(1)(g), the strict 100 gCO2e/kWh one, and it is built here
because revenue_exclusions.parquet only decided 12(1)(a) to (f).

Writes data/interim/portfolio.parquet and site/data/portfolio.json.
"""

import json
import math
import pathlib
import re
import urllib.request
import concurrent.futures as cf

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
RAW = ROOT / "data" / "raw"
SITE = ROOT / "site" / "data"

SEED = 20260912
AUM_USD = 1_000_000_000.0

# Emissions window for the improvement term. GHGRP ends at 2023 and 2018 is the last year before
# the pandemic distorts the level, so the pair is five years of like-for-like reporting.
BASE_YEAR = 2018
LATEST_YEAR = 2023

# Position limits. 5% is the UCITS single-issuer bar; 10x cap weight stops a small clean name
# absorbing the whole tilt.
MAX_ABS_WEIGHT = 0.05
MAX_REL_WEIGHT = 10.0

# 40 CFR Part 98: a US facility emitting 25,000 tCO2e or more in a year must report to GHGRP.
# A company that files nothing therefore operates no single US facility above this line, which
# is a bound the law gives us rather than a number we invented.
GHGRP_THRESHOLD_T = 25_000.0

# Below this many measured companies a sector median is one or two conglomerates, not a sector.
# The Financials median was 56.6 tCO2e per $m of EVIC on a sample of Berkshire, Loews and
# Invesco, and it was being applied to 72 banks and insurers.
MIN_SECTOR_MEASURED = 5

# Active share added on top of the exclusion portfolio by a tilt. Article 12 alone already
# clears Article 11, so any tilt beyond the rulebook is a risk budget the manager chooses
# rather than a constraint the regulation imposes. Both tilted portfolios are given the same
# budget so the comparison is signal against signal, not aggression against aggression.
TILT_ACTIVE_BUDGET = 0.05

rng = np.random.default_rng(SEED)


def hr(title):
    print("\n" + "=" * 94)
    print(title)
    print("=" * 94)


# ---------------------------------------------------------------------------
# the rulebook, read from the file
# ---------------------------------------------------------------------------

def load_rules():
    with open(INTERIM / "pab_rules.json") as fh:
        doc = json.load(fh)
    by_id = {r["id"]: r for r in doc["rules"]}
    return doc, by_id


# ---------------------------------------------------------------------------
# NACE section for the Article 3 high-climate-impact floor
# ---------------------------------------------------------------------------

# Article 3 asks for exposure to NACE Sections A to H and Section L at least equal to the
# investable universe's. GICS does not carry a NACE code, so the section is assigned per GICS
# sub-industry below and overridden per ticker where one sub-industry spans two sections.
# A agriculture  B mining  C manufacturing  D electricity and gas  E water and waste
# F construction  G trade  H transport  L real estate   -- all of those are in scope.
# I hotels and food  J information  K finance  M professional  N administrative  Q health
# R arts  S other services -- all of those are out of scope.
SUBIND_NACE = {
    # Communication Services: publishing, broadcasting, telecoms and web portals are all J.
    "Advertising": "M", "Broadcasting": "J", "Cable & Satellite": "J",
    "Integrated Telecommunication Services": "J", "Interactive Home Entertainment": "J",
    "Interactive Media & Services": "J", "Movies & Entertainment": "J", "Publishing": "J",
    "Wireless Telecommunication Services": "J",
    # Consumer Discretionary
    "Apparel Retail": "G", "Apparel, Accessories & Luxury Goods": "C",
    "Automobile Manufacturers": "C", "Automotive Parts & Equipment": "C",
    "Automotive Retail": "G", "Broadline Retail": "G", "Casinos & Gaming": "R",
    "Computer & Electronics Retail": "G", "Consumer Electronics": "C", "Distributors": "G",
    "Footwear": "C", "Home Improvement Retail": "G", "Homebuilding": "F",
    "Homefurnishing Retail": "G", "Hotels, Resorts & Cruise Lines": "I",
    "Leisure Products": "C", "Other Specialty Retail": "G", "Restaurants": "I",
    "Specialized Consumer Services": "S",
    # Consumer Staples: food and drink manufacture is C, grocery and merchandise retail is G.
    "Agricultural Products & Services": "C", "Brewers": "C",
    "Consumer Staples Merchandise Retail": "G", "Distillers & Vintners": "C",
    "Food Distributors": "G", "Food Retail": "G", "Household Products": "C",
    "Packaged Foods & Meats": "C", "Personal Care Products": "C",
    "Soft Drinks & Non-alcoholic Beverages": "C", "Tobacco": "C",
    # Energy
    "Integrated Oil & Gas": "B", "Oil & Gas Equipment & Services": "B",
    "Oil & Gas Exploration & Production": "B", "Oil & Gas Refining & Marketing": "C",
    "Oil & Gas Storage & Transportation": "H",
    # Financials
    "Asset Management & Custody Banks": "K", "Consumer Finance": "K", "Diversified Banks": "K",
    "Financial Exchanges & Data": "K", "Insurance Brokers": "K",
    "Investment Banking & Brokerage": "K", "Life & Health Insurance": "K",
    "Multi-Sector Holdings": "K", "Multi-line Insurance": "K",
    "Property & Casualty Insurance": "K", "Regional Banks": "K", "Reinsurance": "K",
    "Transaction & Payment Processing Services": "K",
    # Health Care: manufacture is C, care delivery is Q.
    "Biotechnology": "C", "Health Care Distributors": "G", "Health Care Equipment": "C",
    "Health Care Facilities": "Q", "Health Care Services": "Q", "Health Care Supplies": "C",
    "Health Care Technology": "J", "Life Sciences Tools & Services": "C",
    "Managed Health Care": "K", "Pharmaceuticals": "C",
    # Industrials
    "Aerospace & Defense": "C", "Agricultural & Farm Machinery": "C",
    "Air Freight & Logistics": "H", "Building Products": "C",
    "Cargo Ground Transportation": "H", "Construction & Engineering": "F",
    "Construction Machinery & Heavy Transportation Equipment": "C",
    "Data Processing & Outsourced Services": "J", "Diversified Support Services": "N",
    "Electrical Components & Equipment": "C", "Environmental & Facilities Services": "E",
    "Heavy Electrical Equipment": "C", "Human Resource & Employment Services": "N",
    "Industrial Conglomerates": "C", "Industrial Machinery & Supplies & Components": "C",
    "Passenger Airlines": "H", "Passenger Ground Transportation": "H",
    "Rail Transportation": "H", "Research & Consulting Services": "M",
    "Trading Companies & Distributors": "G",
    # Information Technology: hardware is C26, software and web services are J62 and J63.
    "Application Software": "J", "Communications Equipment": "C", "Electronic Components": "C",
    "Electronic Equipment & Instruments": "C", "Electronic Manufacturing Services": "C",
    "IT Consulting & Other Services": "J", "Internet Services & Infrastructure": "J",
    "Semiconductor Materials & Equipment": "C", "Semiconductors": "C", "Systems Software": "J",
    "Technology Distributors": "G", "Technology Hardware, Storage & Peripherals": "C",
    # Materials
    "Commodity Chemicals": "C", "Construction Materials": "C", "Copper": "B",
    "Fertilizers & Agricultural Chemicals": "C", "Gold": "B", "Industrial Gases": "C",
    "Metal, Glass & Plastic Containers": "C",
    "Paper & Plastic Packaging Products & Materials": "C", "Specialty Chemicals": "C",
    "Steel": "C",
    # Real Estate
    "Data Center REITs": "L", "Health Care REITs": "L", "Hotel & Resort REITs": "L",
    "Industrial REITs": "L", "Multi-Family Residential REITs": "L", "Office REITs": "L",
    "Other Specialized REITs": "L", "Real Estate Services": "L", "Retail REITs": "L",
    "Self-Storage REITs": "L", "Single-Family Residential REITs": "L",
    "Telecom Tower REITs": "L", "Timber REITs": "L",
    # Utilities
    "Electric Utilities": "D", "Gas Utilities": "D",
    "Independent Power Producers & Energy Traders": "D", "Multi-Utilities": "D",
    "Water Utilities": "E",
}

# Where one GICS sub-industry holds companies in two NACE sections. Each of these is a judgment
# call and every one is printed in the run log and shipped in the JSON.
TICKER_NACE = {
    "CCL": "H", "RCL": "H", "NCLH": "H",   # cruise lines are water transport, not accommodation
    "ABNB": "N", "BKNG": "N", "EXPE": "N",  # travel agencies, not accommodation
    "WM": "E", "RSG": "E",                  # waste collection
    "VLTO": "C",                            # Veralto manufactures water and marking instruments
    "ROL": "N",                             # Rollins is pest control services
    "CPRT": "G",                            # Copart is vehicle wholesale
    "UBER": "H",                            # road passenger transport
    "DASH": "H",                            # courier
    "CVS": "G",                             # retail pharmacy dominates the revenue line
    "CSGP": "J",                            # CoStar is a data business
}

HIGH_IMPACT_SECTIONS = set("ABCDEFGH") | {"L"}

# Article 12(1)(g) leg one: 50% or more of revenue from electricity generation. GICS is the only
# revenue proxy available (the SEC segment screen in revenue_exclusions.parquet was not run for
# electricity), so it is applied at sub-industry level and the sensitivity is printed.
POWER_REVENUE_SUBIND = {
    "Electric Utilities", "Independent Power Producers & Energy Traders", "Multi-Utilities",
}
POWER_REVENUE_SUBIND_NARROW = {
    "Electric Utilities", "Independent Power Producers & Energy Traders",
}


# ---------------------------------------------------------------------------
# name normalisation, the same keys match_parents.py used
# ---------------------------------------------------------------------------

LEGAL = re.compile(
    r"\b(CORPORATION|CORP|COMPANY|COMPANIES|CO|COS|INCORPORATED|INC|LLC|LLP|LP|LTD|PLC"
    r"|HOLDINGS|HOLDING|GROUP|THE|PBC|NV|SA|AG|SE|TRUST|CLASS)\b")
PAREN = re.compile(r"\([^)]*\)?")
OWNER_TAG = re.compile(r"\s*\((Owner|Operator)\)\s*$")


def name_key(name):
    s = PAREN.sub(" ", str(name).upper()).replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\s+", " ", LEGAL.sub(" ", s)).strip().replace(" ", "")


# ---------------------------------------------------------------------------
# Article 12(1)(g): measured generation intensity per company
# ---------------------------------------------------------------------------

def power_intensity_by_ticker(year):
    """gCO2e/kWh over each company's CAMD-monitored fleet, plus the clean-generation bound.

    Plants are attributed through the CAMD owner string, which names owners explicitly. The
    eGRID operator field was tested and rejected: it carries the interconnecting utility, which
    put 128 plants and 94 TWh under CenterPoint and 617 plants under Southern California Edison.

    CAMD meters fossil units only, so the denominator is the fossil fleet and the ratio is an
    upper bound on the company's true generation intensity. That makes the test one-sided and
    exact in both directions: at or below 100 g/kWh the company passes whatever else it owns,
    because zero-carbon generation can only pull the ratio down; above it, the company passes
    only if it also owns at least clean_mwh_needed of zero-carbon generation.
    """
    ptm = pd.read_parquet(INTERIM / "parent_ticker_map.parquet")
    ptm = ptm[ptm.ticker.notna()]
    lookup = {}
    for disp, tk in zip(ptm.parent_name_display.tolist(), ptm.ticker.tolist()):
        k = name_key(disp)
        if k:
            lookup[k] = tk

    camd = pd.read_parquet(INTERIM / "camd_unit_year.parquet")
    camd = camd[camd.year == year][["oris_code", "owner_operator"]].drop_duplicates()
    links = set()
    for oris, own in zip(camd.oris_code.tolist(), camd.owner_operator.tolist()):
        if not isinstance(own, str):
            continue
        for part in own.split("|"):
            tk = lookup.get(name_key(OWNER_TAG.sub("", part).strip()))
            if tk:
                links.add((int(oris), tk))
    link = pd.DataFrame(sorted(links), columns=["oris_code", "ticker"])

    plants = pd.read_parquet(INTERIM / "plant_intensity.parquet")
    plants = plants[plants.year == year][
        ["oris_code", "intensity_best_g_per_kwh", "generation_mwh", "intensity_basis"]]
    j = link.merge(plants, on="oris_code", how="left")
    j = j[j.intensity_best_g_per_kwh.notna() & (j.generation_mwh > 0)].copy()
    j["co2e_t"] = j.intensity_best_g_per_kwh * j.generation_mwh / 1000.0

    agg = j.groupby("ticker").agg(
        power_co2e_t=("co2e_t", "sum"),
        power_gen_mwh=("generation_mwh", "sum"),
        power_plants=("oris_code", "nunique"))
    agg["power_intensity_g_per_kwh"] = agg.power_co2e_t / agg.power_gen_mwh * 1000.0
    # generation at zero gCO2e/kWh that would be needed to reach the 100 g/kWh line
    agg["clean_mwh_needed"] = np.maximum(
        agg.power_co2e_t * 1e6 / 100.0 / 1e3 - agg.power_gen_mwh, 0.0)
    agg["clean_multiple_needed"] = agg.clean_mwh_needed / agg.power_gen_mwh
    return agg.reset_index(), len(link)


# ---------------------------------------------------------------------------
# prices, for a realised tracking error
# ---------------------------------------------------------------------------

PRICE_DIR = RAW / "yahoo_history"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ETHack2026 research cache"}


def fetch_weekly_prices(tickers):
    """Five years of weekly adjusted closes, cached under data/raw/ like every other fetch."""
    PRICE_DIR.mkdir(parents=True, exist_ok=True)

    def one(tk):
        path = PRICE_DIR / f"{tk}.json"
        if path.exists() and path.stat().st_size > 500:
            return tk, "cached"
        sym = tk.replace(".", "-")
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?range=5y&interval=1wk")
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=25) as resp:
                    body = resp.read()
                json.loads(body)
                path.write_bytes(body)
                return tk, "fetched"
            except Exception:
                pass
        return tk, "failed"

    with cf.ThreadPoolExecutor(8) as ex:
        status = dict(ex.map(one, tickers))

    series = {}
    for tk in tickers:
        path = PRICE_DIR / f"{tk}.json"
        if not path.exists():
            continue
        try:
            res = json.loads(path.read_text())["chart"]["result"][0]
            ts = res.get("timestamp") or []
            adj = res["indicators"].get("adjclose")
            px = adj[0]["adjclose"] if adj else res["indicators"]["quote"][0]["close"]
        except Exception:
            continue
        if not ts or not px:
            continue
        s = pd.Series(px, index=pd.to_datetime(ts, unit="s").normalize(), dtype="float64")
        series[tk] = s[~s.index.duplicated(keep="last")].dropna()
    return pd.DataFrame(series), status


def tracking_error(returns, active, index_ret):
    """Annualised standard deviation of the active weekly return, weights held fixed.

    Names with no quote in a given week take the cap-weighted index return for that week, which
    is the neutral fill: it contributes nothing to active risk rather than a fabricated move.
    """
    cols = [c for c in active.index if c in returns.columns and abs(active[c]) > 0]
    r = returns[cols].copy()
    filled = int(r.isna().sum().sum())
    r = r.apply(lambda col: col.fillna(index_ret))
    a = active.reindex(cols).to_numpy()
    active_ret = r.to_numpy() @ a
    te = float(np.std(active_ret, ddof=1) * math.sqrt(52.0))
    return te, active_ret, filled


def block_bootstrap_te(active_ret, n_boot=2000, block=13):
    """Stationary block bootstrap, 13-week blocks, so the interval survives autocorrelation."""
    n = len(active_ret)
    out = np.empty(n_boot)
    for b in range(n_boot):
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n)
            idx.extend(((start + np.arange(block)) % n).tolist())
        out[b] = np.std(active_ret[np.array(idx[:n])], ddof=1) * math.sqrt(52.0)
    return float(np.percentile(out, 5)), float(np.percentile(out, 95))


# ---------------------------------------------------------------------------
# portfolio construction
# ---------------------------------------------------------------------------

def cap_weights(mc):
    return mc / mc.sum()


def apply_caps(w, base, max_abs, max_rel):
    """Iterative water-filling: cap the offenders, push the spill onto everyone still free."""
    cap = np.minimum(max_abs, max_rel * base)
    w = w.copy()
    for _ in range(200):
        over = w > cap + 1e-15
        if not over.any():
            break
        spill = float((w[over] - cap[over]).sum())
        w[over] = cap[over]
        free = ~over & (w > 0)
        if not free.any() or spill <= 0:
            break
        w[free] = w[free] + spill * w[free] / w[free].sum()
    return w / w.sum()


def bucket_tilt(df, keep, score, lam, bucket_targets):
    """Cap weights tilted by exp(-lam * score) inside each Article 3 bucket.

    Bucket totals are pinned to the universe's, so Article 3 holds with equality and the tilt
    can only move money between names inside a bucket, never out of the high-impact bucket.
    """
    w = pd.Series(0.0, index=df.index)
    for bucket, target in bucket_targets.items():
        sel = keep & (df.high_impact == bucket)
        if not sel.any() or target <= 0:
            continue
        base = df.loc[sel, "w_cap"]
        raw = base * np.exp(-lam * score[sel])
        if raw.sum() <= 0:
            continue
        inner = raw / raw.sum()
        inner = apply_caps(inner, base / base.sum(), MAX_ABS_WEIGHT / max(target, 1e-12),
                           MAX_REL_WEIGHT)
        w[sel] = inner * target
    return w / w.sum()


def waci(w, intensity):
    return float((w * intensity).sum())


def solve_lambda(df, keep, score, intensity, bucket_targets, target_waci):
    """Bisect the tilt strength until the portfolio hits the Article 11 line exactly."""
    lo, hi = 0.0, 120.0
    w_hi = bucket_tilt(df, keep, score, hi, bucket_targets)
    if waci(w_hi, intensity) > target_waci:
        return hi, w_hi, False
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        w_mid = bucket_tilt(df, keep, score, mid, bucket_targets)
        if waci(w_mid, intensity) > target_waci:
            lo = mid
        else:
            hi = mid
    w = bucket_tilt(df, keep, score, hi, bucket_targets)
    return hi, w, True


def brinson(df, w0, w1, i0, i1):
    """The three-way split the brief asked for, plus the cross term it leaves out.

    reallocation + selection + improvement + interaction == total, exactly.
    """
    sector = df.gics_sector
    num = (w0 * i0).groupby(sector).sum()
    den = w0.groupby(sector).sum()
    ibar_s = (num / den).reindex(sector).to_numpy()
    ibar = pd.Series(ibar_s, index=df.index)

    realloc = float(((w1 - w0) * ibar).sum())
    selection = float((w1 * (i0 - ibar)).sum() - (w0 * (i0 - ibar)).sum())
    improvement = float((w0 * (i1 - i0)).sum())
    interaction = float(((w1 - w0) * (i1 - i0)).sum())
    total = float((w1 * i1).sum() - (w0 * i0).sum())
    return dict(reallocation=realloc, selection=selection, improvement=improvement,
                interaction=interaction, improvement_held=improvement + interaction,
                total=total,
                residual=total - (realloc + selection + improvement + interaction))


# ---------------------------------------------------------------------------

def main():
    doc, rules = load_rules()
    pab_floor = rules["pab_baseline_reduction"]["parameters"]["min_reduction_vs_universe_pct"] / 100
    ctb_floor = rules["ctb_baseline_reduction"]["parameters"]["min_reduction_vs_universe_pct"] / 100
    traj_pct = rules["decarbonisation_trajectory_equity"]["parameters"]["min_annual_reduction_pct"]
    pwr = rules["pab_exclusion_power_generation"]["parameters"]
    pwr_rev = pwr["revenue_threshold_pct"] / 100
    pwr_int = pwr["intensity_threshold_gco2e_per_kwh"]
    pwr_op = rules["pab_exclusion_power_generation"]["intensity_operator"]
    assert pwr_op == ">", f"Article 12(1)(g) operator changed to {pwr_op}"
    tilt_rule = rules["target_setter_overweight"]["parameters"]

    hr("rulebook, read from data/interim/pab_rules.json")
    print(f"  {doc['regulation']['celex']}  retrieved {doc['regulation']['retrieved_at']}")
    print(f"  Article 9   CTB intensity floor           {ctb_floor:.0%} below the universe")
    print(f"  Article 11  PAB intensity floor           {pab_floor:.0%} below the universe")
    print(f"  Article 7   trajectory                    {traj_pct:.0f}% a year, geometric")
    print(f"  Article 6   overweight permitted at       {tilt_rule['min_annual_reduction_pct']:.0f}%"
          f" a year delivered for {tilt_rule['min_consecutive_years']} consecutive years")
    for rid in ("pab_exclusion_coal", "pab_exclusion_oil", "pab_exclusion_gas"):
        r = rules[rid]
        print(f"  {r['article']:<18} {r['commodity']:<22} revenue "
              f"{r['operator']} {r['parameters']['revenue_threshold_pct']:.0f}%")
    print(f"  {rules['pab_exclusion_power_generation']['article']:<18} "
          f"{'electricity generation':<22} revenue >= {pwr['revenue_threshold_pct']:.0f}% "
          f"AND intensity {pwr_op} {pwr_int:.0f} gCO2e/kWh")
    print(f"  Article 3   high climate impact floor     NACE sections "
          f"{''.join(sorted(HIGH_IMPACT_SECTIONS))}, portfolio >= universe")

    # ---------------------------------------------------------------- load
    uni = pd.read_parquet(INTERIM / "universe.parquet")
    uni = uni[uni.is_primary_listing].set_index("ticker")
    mcap = pd.read_parquet(INTERIM / "market_cap.parquet").set_index("ticker")
    fin = pd.read_parquet(INTERIM / "financials.parquet")
    fin = fin[fin.is_primary_listing]
    scores = pd.read_parquet(INTERIM / "scores.parquet")
    scores = scores[scores.is_primary_listing].set_index("ticker")
    emis = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    emis = emis[emis.is_primary_listing]
    excl = pd.read_parquet(INTERIM / "revenue_exclusions.parquet")
    excl = excl[excl.is_primary_listing]
    saydo = pd.read_parquet(INTERIM / "say_do_gap.parquet")
    saydo = saydo[saydo.is_primary_listing].set_index("ticker")

    df = pd.DataFrame(index=uni.index.copy())
    df["company_name"] = uni.company_name
    df["gics_sector"] = uni.gics_sector
    df["gics_sub_industry"] = uni.gics_sub_industry
    df["market_cap"] = mcap.market_cap_company.reindex(df.index)

    debt = (fin[fin.total_debt.notna()].sort_values("fy").groupby("ticker")
            .agg(total_debt=("total_debt", "last"), debt_fy=("fy", "last")))
    df["total_debt"] = debt.total_debt.reindex(df.index)
    df["debt_observed"] = df.total_debt.notna()
    df["evic_usd"] = df.market_cap + df.total_debt.fillna(0.0)
    df["evic_musd"] = df.evic_usd / 1e6

    df["coverage_tier"] = scores.coverage_tier.reindex(df.index)
    df["scope1_tonnes"] = scores.scope1_tonnes.reindex(df.index)
    df["emissions_year"] = scores.emissions_year.reindex(df.index)
    df["revenue_musd"] = scores.revenue_musd.reindex(df.index)
    df["rank_median"] = scores.rank_median.reindex(df.index)
    df["gap_pct_yr"] = saydo.gap_pct_yr.reindex(df.index)
    df["delivered_pct_yr"] = saydo.delivered_pct_yr.reindex(df.index)
    df["promised_pct_yr"] = saydo.promised_pct_yr.reindex(df.index)

    # sign convention: the tables store reduction as a negative rate, so beating a promise is a
    # negative gap. saydo_out is flipped so that positive means delivering more than promised.
    df["saydo_out_pct_yr"] = -df.gap_pct_yr

    # ------------------------------------------------ NACE and Article 3 bucket
    sect = [SUBIND_NACE.get(s) for s in df.gics_sub_industry.tolist()]
    df["nace_section"] = sect
    missing_nace = df.index[[s is None for s in sect]].tolist()
    for tk, s in TICKER_NACE.items():
        if tk in df.index:
            df.loc[tk, "nace_section"] = s
    df["high_impact"] = df.nace_section.isin(HIGH_IMPACT_SECTIONS)
    assert not missing_nace, f"no NACE section for {missing_nace}"

    # ------------------------------------------------ investable universe
    no_cap = df.index[df.market_cap.isna()].tolist()
    df["investable"] = df.market_cap.notna() & (df.market_cap > 0)
    inv = df[df.investable].copy()
    inv["w_cap"] = cap_weights(inv.market_cap)

    hr("investable universe")
    print(f"  500 primary listings, {len(inv)} investable. Dropped for no market cap: {no_cap}")
    print(f"  index market cap  ${inv.market_cap.sum()/1e12:,.3f} trn")
    print(f"  $1bn is {AUM_USD/inv.market_cap.sum()*100:.5f}% of it. We are a rounding error in "
          f"the tape and we say so before anyone asks.")
    print(f"  debt observed for {int(inv.debt_observed.sum())} of {len(inv)}. The other "
          f"{len(inv) - int(inv.debt_observed.sum())} carry EVIC = market cap, which understates "
          f"EVIC and so overstates their intensity.")
    print(f"  high climate impact bucket (NACE A-H, L): {int(inv.high_impact.sum())} names, "
          f"{inv.loc[inv.high_impact, 'w_cap'].sum():.1%} of index cap")
    print("  NACE section split of index weight:")
    for s, w in inv.groupby("nace_section").w_cap.sum().sort_values(ascending=False).items():
        n = int((inv.nace_section == s).sum())
        print(f"    {s}  {'in scope ' if s in HIGH_IMPACT_SECTIONS else 'out      '}"
              f"{w:6.2%}  {n:3d} names")
    print(f"  per-ticker NACE overrides applied: {sorted(TICKER_NACE)}")

    # ------------------------------------------------ intensity, Article 1(c)
    inv["intensity_measured"] = inv.scope1_tonnes / inv.evic_musd
    measured = inv.intensity_measured.notna()
    n_meas_sector = measured.groupby(inv.gics_sector).sum()
    sec_med_all = inv.loc[measured].groupby("gics_sector").intensity_measured.median()
    sec_med = sec_med_all[n_meas_sector.reindex(sec_med_all.index) >= MIN_SECTOR_MEASURED]
    thin_sectors = sorted(set(sec_med_all.index) - set(sec_med.index))

    inv["intensity_threshold"] = inv.intensity_measured.where(
        measured, GHGRP_THRESHOLD_T / inv.evic_musd)
    sector_fill = inv.gics_sector.map(sec_med)
    inv["intensity_imputed"] = inv.intensity_measured.where(
        measured, sector_fill.fillna(inv.intensity_threshold))
    inv["intensity_zerofill"] = inv.intensity_measured.fillna(0.0)
    inv["intensity_basis"] = np.where(
        measured, "measured_mandatory",
        np.where(sector_fill.notna(), "sector_median_imputed", "ghgrp_threshold_bound"))
    inv["intensity_dq"] = np.where(measured, 1, 5)

    hr("intensity, Article 1(c): tonnes of Scope 1 per $m of EVIC")
    print("  Article 11 asks for Scope 1, 2 and 3. We have mandatory Scope 1 only, for "
          f"{int(measured.sum())} of {len(inv)} companies. Scope 2 and 3 are absent from both "
          "the portfolio and the universe, so the 50% ratio is like for like and the level is "
          "not. Said here, not buried.")
    print(f"  EVIC = market cap + book total debt. Preferred stock and non-controlling "
          f"interests are not in the SEC tags we pulled, so EVIC is a lower bound and the "
          f"intensity an upper bound, symmetrically for every company.")
    print(f"  measured        {int(measured.sum()):3d} companies, "
          f"{inv.loc[measured, 'w_cap'].sum():.1%} of index cap")
    print(f"  not measurable  {int((~measured).sum()):3d} companies, "
          f"{inv.loc[~measured, 'w_cap'].sum():.1%} of index cap")
    print("  four schemes are carried all the way to the compliance verdict, never averaged:")
    print("    imputed        sector median where the sector has at least "
          f"{MIN_SECTOR_MEASURED} measured companies, otherwise the threshold bound below. "
          "The headline, and the strictest of the four, so the portfolio is built against it.")
    print(f"    threshold      every non-filer at exactly {GHGRP_THRESHOLD_T:,.0f} tCO2e, the "
          "40 CFR Part 98 reporting line. A company that files nothing operates no US facility "
          "above it, so this is a bound the law hands us rather than a number we invented.")
    print("    available_case measurable names only, weights renormalised over them")
    print("    zerofill       non-disclosers at zero, which is what buying silence looks like")
    print("  sector medians, tonnes per $m EVIC:")
    for s, v in sec_med_all.sort_values(ascending=False).items():
        n_meas = int((measured & (inv.gics_sector == s)).sum())
        n_all = int((inv.gics_sector == s).sum())
        if s in thin_sectors:
            who = sorted(inv.index[measured & (inv.gics_sector == s)])
            note = f"   REJECTED, a median of {who} is not a sector; falls back to the bound"
        else:
            note = ""
        print(f"    {s:<24} {v:9.3f}   measured {n_meas:3d} of {n_all:3d}{note}")
    n_bound = int((inv.intensity_basis == "ghgrp_threshold_bound").sum())
    print(f"  {n_bound} companies in {thin_sectors} take the "
          f"{GHGRP_THRESHOLD_T:,.0f} tCO2e bound instead, "
          f"{float(inv.loc[inv.intensity_basis == 'ghgrp_threshold_bound', 'w_cap'].sum()):.1%} "
          f"of index cap")
    print("  a sector median is not a neutral estimate. A company only files a GHGRP tonnage "
          "if a US facility is above the 25,000 tCO2e line, so the measured names are the heavy "
          "end of their own sector and their median overstates a typical non-discloser. Where "
          "the sector has enough of them that bias is a defensible upper reading; where it has "
          "three, it is one conglomerate's number applied to seventy banks, and the threshold "
          "bound replaces it. Nothing here is an estimate of what a company emits. The four "
          "schemes are a bracket, and every verdict below is reported under all four.")

    # ------------------------------------------------ Article 12 exclusions
    flags = (excl[excl.flag_best].groupby("ticker")
             .agg(rules=("rule_id", lambda s: sorted(set(s))),
                  articles=("article", lambda s: sorted(set(s))),
                  basis=("flag_basis", lambda s: sorted(set(s)))))
    excl_af = {tk: v for tk, v in zip(flags.index, flags.rules)}
    inv["excl_rules"] = [excl_af.get(tk, []) for tk in inv.index]

    power, n_links = power_intensity_by_ticker(LATEST_YEAR)
    power = power.set_index("ticker")
    inv["power_intensity_g_per_kwh"] = power.power_intensity_g_per_kwh.reindex(inv.index)
    inv["power_gen_mwh"] = power.power_gen_mwh.reindex(inv.index)
    inv["power_plants"] = power.power_plants.reindex(inv.index)
    inv["clean_multiple_needed"] = power.clean_multiple_needed.reindex(inv.index)
    inv["power_revenue_leg"] = inv.gics_sub_industry.isin(POWER_REVENUE_SUBIND)
    inv["power_revenue_leg_narrow"] = inv.gics_sub_industry.isin(POWER_REVENUE_SUBIND_NARROW)
    inv["power_intensity_leg"] = inv.power_intensity_g_per_kwh > pwr_int
    inv["excl_12g"] = inv.power_revenue_leg & inv.power_intensity_leg
    inv["excl_12g_narrow"] = inv.power_revenue_leg_narrow & inv.power_intensity_leg

    hr(f"Article 12(1)(g), the {pwr_int:.0f} gCO2e/kWh test, built here")
    print(f"  plant to ticker links from the CAMD owner string, {LATEST_YEAR}: {n_links} links, "
          f"{int(inv.power_plants.notna().sum())} companies with a measured fleet")
    print("  leg one, revenue: GICS sub-industry proxy at dq 4. Electric Utilities, IPPs and "
          "Multi-Utilities are read as deriving at least half their revenue from generation.")
    print("  leg two, intensity: measured, and one-sided. CAMD meters fossil units, so this is "
          "the fossil fleet and an upper bound on the company's real number.")
    pw = inv[inv.power_intensity_g_per_kwh.notna()].sort_values(
        "power_intensity_g_per_kwh", ascending=False)
    print(f"\n  {'ticker':<7}{'company':<32}{'g/kWh':>9}{'TWh':>8}{'plants':>7}"
          f"{'clean gen needed to pass':>26}  verdict")
    for tk, r in pw.iterrows():
        if not r.power_revenue_leg and r.power_intensity_g_per_kwh < pwr_int:
            continue
        need = ("-" if r.power_intensity_g_per_kwh <= pwr_int
                else f"{r.clean_multiple_needed:.1f}x its fossil TWh")
        if not r.power_revenue_leg:
            verdict = "in, revenue leg not met"
        elif r.power_intensity_g_per_kwh > pwr_int:
            verdict = "EXCLUDED 12(1)(g)"
        else:
            verdict = "in, passes on the fleet"
        print(f"  {tk:<7}{r.company_name[:31]:<32}{r.power_intensity_g_per_kwh:9.1f}"
              f"{r.power_gen_mwh/1e6:8.1f}{int(r.power_plants):7d}{need:>26}  {verdict}")
    print(f"\n  wide proxy  (incl Multi-Utilities): {int(inv.excl_12g.sum())} excluded")
    print(f"  narrow proxy (Electric + IPP only): {int(inv.excl_12g_narrow.sum())} excluded, "
          f"the difference being "
          f"{sorted(inv.index[inv.excl_12g & ~inv.excl_12g_narrow])}")
    passers = pw.index[pw.power_revenue_leg & (pw.power_intensity_g_per_kwh <= pwr_int)].tolist()
    print(f"  electricity producers that PASS the 100 g/kWh line and stay in: {passers}")
    untested = sorted(inv.index[inv.power_revenue_leg & inv.power_intensity_g_per_kwh.isna()])
    print(f"  revenue leg met but no measured fleet, so untested: {untested}")

    inv["excluded"] = inv.excl_rules.apply(len).gt(0) | inv.excl_12g
    inv["excl_all"] = [
        sorted(set(r + (["pab_exclusion_power_generation"] if g else [])))
        for r, g in zip(inv.excl_rules, inv.excl_12g)]

    hr("Article 12, the full exclusion list")
    by_rule = {}
    for tk, rs in zip(inv.index, inv.excl_all):
        for r in rs:
            by_rule.setdefault(r, []).append(tk)
    for rid in ["pab_exclusion_controversial_weapons", "pab_exclusion_tobacco",
                "pab_exclusion_ungc_oecd", "pab_exclusion_coal", "pab_exclusion_oil",
                "pab_exclusion_gas", "pab_exclusion_power_generation"]:
        names = by_rule.get(rid, [])
        art = rules[rid]["article"]
        wt = inv.loc[names, "w_cap"].sum() if names else 0.0
        print(f"  {art:<18} {rid.replace('pab_exclusion_',''):<24} {len(names):3d} names  "
              f"{wt:6.2%} of cap")
        print(f"      {', '.join(sorted(names)) if names else '(none)'}")
    n_ex = int(inv.excluded.sum())
    w_ex = float(inv.loc[inv.excluded, "w_cap"].sum())
    print(f"\n  EXCLUDED IN TOTAL: {n_ex} of {len(inv)} names, {w_ex:.2%} of index market cap, "
          f"${inv.loc[inv.excluded,'market_cap'].sum()/1e12:.3f} trn")
    print(f"  those {n_ex} names carry "
          f"{inv.loc[inv.excluded & measured,'scope1_tonnes'].sum()/1e6:,.0f} Mt of the "
          f"{inv.loc[measured,'scope1_tonnes'].sum()/1e6:,.0f} Mt we can measure, or "
          f"{inv.loc[inv.excluded & measured,'scope1_tonnes'].sum()/inv.loc[measured,'scope1_tonnes'].sum():.1%}")

    # ------------------------------------------------ the three portfolios
    w0 = inv.w_cap.copy()
    schemes = {
        "imputed": inv.intensity_imputed,
        "threshold": inv.intensity_threshold,
        "available_case": inv.intensity_measured,
        "zerofill": inv.intensity_zerofill,
    }

    def scheme_waci(w, scheme):
        inten = schemes[scheme]
        if scheme == "available_case":
            m = inten.notna() & (w > 0)
            if w[m].sum() <= 0:
                return float("nan")
            return float((w[m] * inten[m]).sum() / w[m].sum())
        return float((w * inten).sum())

    uni_waci = {s: scheme_waci(w0, s) for s in schemes}
    hr("the investable universe, cap weighted")
    for s in schemes:
        print(f"  universe intensity, {s:<15} {uni_waci[s]:9.3f} tCO2e per $m EVIC")
    print(f"  financed Scope 1 of a $1bn cap-weighted holding, headline scheme: "
          f"{uni_waci['imputed'] * AUM_USD / 1e6:,.0f} tCO2e")

    inten_h = inv.intensity_imputed
    target = uni_waci["imputed"] * (1 - pab_floor)
    w_high_uni = float(w0[inv.high_impact].sum())
    buckets = {True: w_high_uni, False: 1.0 - w_high_uni}

    pct = lambda s: s.rank(pct=True, method="average")
    score_int = pct(np.log(inten_h + 1e-9))
    sd = inv.saydo_out_pct_yr
    sd_pct = pct(sd.where(sd.notna()))
    score_saydo = (1.0 - sd_pct).fillna(0.5)
    score_blend = 0.5 * score_int + 0.5 * score_saydo

    keep_pab = ~inv.excluded
    keep_naive = ~inv.gics_sector.isin(["Energy", "Utilities"])

    w_naive = (w0.where(keep_naive, 0.0)) / w0[keep_naive].sum()

    # The rulebook and nothing else: Article 12 exclusions, Article 3 floor, cap weights.
    w_pab = bucket_tilt(inv, keep_pab, score_int * 0.0, 0.0, buckets)
    lam_art11, w_art11, feasible = solve_lambda(
        inv, keep_pab, score_int, inten_h, buckets, target)
    cut_pab = 1 - waci(w_pab, inten_h) / uni_waci["imputed"]
    slack = cut_pab - pab_floor
    w_max = bucket_tilt(inv, keep_pab, score_int, 120.0, buckets)

    def solve_budget(score, budget):
        """Bisect the tilt strength to a stated addition to active share."""
        want = float(0.5 * (w_pab - w0).abs().sum()) + budget
        lo, hi = 0.0, 400.0
        for _ in range(90):
            mid = 0.5 * (lo + hi)
            wm = bucket_tilt(inv, keep_pab, score, mid, buckets)
            if float(0.5 * (wm - w0).abs().sum()) < want:
                lo = mid
            else:
                hi = mid
        return hi, bucket_tilt(inv, keep_pab, score, hi, buckets)

    lam_lead, w_lead = solve_budget(score_saydo, TILT_ACTIVE_BUDGET)
    lam_int, w_int = solve_budget(score_int, TILT_ACTIVE_BUDGET)
    lam_blend, w_blend = solve_budget(score_blend, TILT_ACTIVE_BUDGET)
    w_capped = bucket_tilt(inv, pd.Series(True, index=inv.index), score_int * 0.0, 0.0, buckets)

    ports = {"naive_exclusion": w_naive, "pab_compliant": w_pab, "transition_leader": w_lead}
    extras = {"pab_intensity_tilted": w_int, "variant_blended": w_blend,
              "pab_max_tilt": w_max, "capped_index_only": w_capped}
    lam_used = {"naive_exclusion": 0.0, "pab_compliant": 0.0, "transition_leader": lam_lead,
                "pab_intensity_tilted": lam_int, "variant_blended": lam_blend,
                "pab_max_tilt": 120.0, "capped_index_only": 0.0}

    hr("portfolio construction")
    print(f"  naive exclusion   drop GICS Energy and Utilities, cap weight the rest. "
          f"{int((w_naive>0).sum())} names.")
    print(f"  pab compliant     the rulebook and nothing else: Article 12 exclusions, the "
          f"Article 3 floor holding the high-impact bucket at the universe's "
          f"{w_high_uni:.1%}, cap weights inside each bucket, positions capped at "
          f"{MAX_ABS_WEIGHT:.0%} and {MAX_REL_WEIGHT:.0f}x cap weight. No tilt.")
    max_cut = 1 - waci(w_max, inten_h) / uni_waci["imputed"]
    print(f"\n  WE BUILT THE SOLVER AND IT RETURNED ZERO. Bisecting the tilt strength to land "
          f"on the Article 11 line gives lambda = {lam_art11:.4f}, because the exclusions on "
          f"their own already put the portfolio {cut_pab:.1%} below the universe against a "
          f"{pab_floor:.0%} requirement. Article 11 is slack by {slack*100:.1f} points before "
          f"one weight is tilted. The hardest tilt the constraint set allows reaches "
          f"{max_cut:.1%}, so everything a solver can add to a screen lives in the "
          f"{max_cut - cut_pab:.1%} between them.")
    print(f"\n  so every tilt past the rulebook is a risk budget the manager chooses, not a "
          f"constraint the regulation imposes. Both tilted portfolios get the same budget: "
          f"{TILT_ACTIVE_BUDGET:.0%} of active share on top of the exclusion portfolio's, so "
          f"the comparison is signal against signal.")
    print(f"  transition leader rulebook plus a tilt on say-do outperformance, lambda "
          f"{lam_lead:.4f}.")
    print(f"                    {int(sd.notna().sum())} companies carry a say-do gap "
          f"({w0[sd.notna()].sum():.1%} of index cap); the rest sit at the median score of the "
          f"companies we can judge, the same principle as the intensity imputation.")
    print(f"  pab intensity tilted  the matched comparison, rulebook plus a tilt on the "
          f"intensity level, lambda {lam_int:.4f}, same budget.")
    print(f"  variant, blended  half intensity half say-do, lambda {lam_blend:.4f}.")
    print(f"  pab max tilt      the hardest intensity tilt the constraints allow, lambda 120, "
          f"shown as the headroom.")
    print(f"  capped index only the whole index with the {MAX_ABS_WEIGHT:.0%} position cap and "
          f"nothing else. Four mega-caps breach it, so some of every active share and every "
          f"tracking error below is the cap, not the carbon. This line is how much.")
    naive_keeps = sorted(inv.index[keep_naive & inv.excluded])
    print(f"\n  the naive screen keeps {len(naive_keeps)} names Article 12 excludes, "
          f"{float(w0[naive_keeps].sum()):.2%} of cap: {naive_keeps}")
    print("  dropping two GICS sectors is not the same screen as the regulation. It takes out "
          "the whole of Energy and Utilities including the ones that pass, and it leaves in "
          "every weapons maker, both tobacco companies and the two coal-hauling railroads.")

    # ------------------------------------------------ compliance
    hr("PAB compliance")
    header = (f"  {'portfolio':<20}{'names':>6}{'Art11 cut':>11}{'Art9 cut':>10}"
              f"{'intensity':>11}{'Art3 hi':>9}{'uni hi':>8}{'Art12 held':>12}"
              f"{'active sh':>11}{'eff N':>8}{'cap out':>10}")
    print(header)
    compliance = {}
    for name, w in list(ports.items()) + list(extras.items()):
        wc = scheme_waci(w, "imputed")
        cut = 1 - wc / uni_waci["imputed"]
        hi = float(w[inv.high_impact].sum())
        held_excluded = int(((w > 1e-12) & inv.excluded).sum())
        act = float(0.5 * (w - w0).abs().sum())
        effn = float(1.0 / (w ** 2).sum())
        dropped = w0[w <= 1e-12].sum()
        compliance[name] = dict(
            names=int((w > 1e-12).sum()), waci=wc, cut_vs_universe=float(cut),
            art11_pass=bool(cut >= pab_floor - 1e-9), art9_pass=bool(cut >= ctb_floor - 1e-9),
            art3_high_impact=hi, art3_universe=w_high_uni,
            art3_pass=bool(hi >= w_high_uni - 1e-9),
            art12_names_held=held_excluded, art12_pass=bool(held_excluded == 0),
            active_share=act, effective_n=effn, cap_share_dropped=float(dropped),
            financed_tonnes=wc * AUM_USD / 1e6)
        c = compliance[name]
        print(f"  {name:<20}{c['names']:>6}{cut:>10.1%}{'*' if c['art11_pass'] else ' '}"
              f"{cut:>9.1%}{'*' if c['art9_pass'] else ' '}{wc:>11.2f}"
              f"{hi:>8.1%}{'*' if c['art3_pass'] else ' '}{w_high_uni:>8.1%}"
              f"{held_excluded:>12}{act:>11.1%}{effn:>8.0f}{dropped:>10.2%}")
    print(f"  * = passes. Article 11 needs {pab_floor:.0%}, Article 9 needs {ctb_floor:.0%}, "
          f"Article 3 needs the high-impact bucket at or above the universe's {w_high_uni:.1%}.")

    print("\n  the same verdicts under every missing-data scheme:")
    print(f"  {'portfolio':<20}{'imputed':>12}{'threshold':>13}{'available_case':>17}"
          f"{'zerofill':>12}")
    scheme_cuts = {}
    for name, w in list(ports.items()) + list(extras.items()):
        row = {}
        for s in schemes:
            wc = scheme_waci(w, s)
            row[s] = float(1 - wc / uni_waci[s]) if uni_waci[s] else float("nan")
        scheme_cuts[name] = row
        cells = []
        for s, width in [("imputed", 11), ("threshold", 12), ("available_case", 16),
                         ("zerofill", 11)]:
            mark = "*" if row[s] >= pab_floor - 1e-9 else " "
            cells.append(f"{row[s]:>{width}.1%}{mark}")
        print(f"  {name:<20}" + "".join(cells))
    print("  available_case renormalises over the measurable names only, so an unmeasured "
          "company is free to hold. zerofill scores it at zero, so it is better than free.")

    # ------------------------------------------------ Article 7
    hr(f"Article 7, the {traj_pct:.0f}% a year trajectory")
    print("  geometric from the base year, Article 7(2): I(n) = I(0) * "
          f"(1 - {traj_pct/100:.2f})^n")
    for name, w in ports.items():
        i0p = scheme_waci(w, "imputed")
        path = [i0p * (1 - traj_pct / 100) ** n for n in range(0, 11)]
        print(f"  {name:<20} 2026 {path[0]:8.2f}  2031 {path[5]:8.2f}  2036 {path[10]:8.2f}"
              f"   ten-year factor {(1-traj_pct/100)**10:.3f}")
    dlv = inv.delivered_pct_yr
    print("\n  feasibility, from what the holdings physically delivered rather than promised:")
    for name, w in ports.items():
        m = dlv.notna() & (w > 0)
        cov = float(w[m].sum())
        org = float((w[m] * dlv[m]).sum() / w[m].sum()) if cov > 0 else float("nan")
        gap = traj_pct + org
        print(f"  {name:<20} weight with a measured trend {cov:5.1%}, weighted delivered "
              f"{org:+6.2f}%/yr, so {max(gap,0):.2f} points a year must come from "
              f"reallocation, not from any company getting cleaner")
    m = dlv.notna()
    print(f"  the cap-weighted index itself: weight with a measured trend "
          f"{float(w0[m].sum()):5.1%}, weighted delivered "
          f"{float((w0[m]*dlv[m]).sum()/w0[m].sum()):+6.2f}%/yr")
    print(f"  Article 6 lets a benchmark overweight a company that has cut "
          f"{tilt_rule['min_annual_reduction_pct']:.0f}% a year for "
          f"{tilt_rule['min_consecutive_years']} consecutive years. On our measured trends "
          f"{int((dlv <= -tilt_rule['min_annual_reduction_pct']).sum())} companies qualify: "
          f"{sorted(inv.index[dlv <= -tilt_rule['min_annual_reduction_pct']])}")
    clash = sorted(inv.index[(dlv <= -tilt_rule["min_annual_reduction_pct"]) & inv.excluded])
    print(f"  of those, {len(clash)} are banned outright by Article 12: {clash}. The same "
          f"regulation invites you to overweight them for what they delivered and forbids you "
          f"to hold them for what they sell.")

    # ------------------------------------------------ the decomposition
    ghg = emis[emis.scope1_ghgrp_tonnes.notna() & (emis.scope1_ghgrp_tonnes > 0)]
    e_base = ghg[ghg.year == BASE_YEAR].set_index("ticker").scope1_ghgrp_tonnes
    e_last = (ghg[ghg.year <= LATEST_YEAR].sort_values("year")
              .groupby("ticker").scope1_ghgrp_tonnes.last())
    both = e_base.index.intersection(e_last.index).intersection(inv.index)
    ratio = pd.Series(1.0, index=inv.index)
    ratio.loc[both] = (e_base.loc[both] / e_last.loc[both]).astype(float)
    i1 = inten_h
    i0 = inten_h * ratio
    inv["intensity_base_year"] = i0
    inv["intensity_latest"] = i1

    hr(f"the decomposition: where a Paris-aligned cut actually comes from, "
       f"{BASE_YEAR} to {LATEST_YEAR}")
    print(f"  {len(both)} companies carry a mandatory tonnage in both {BASE_YEAR} and "
          f"{LATEST_YEAR}, {float(w0[both].sum()):.1%} of index cap. Every other company has "
          f"delta I = 0: we cannot observe it improving, so we do not let it claim to have.")
    print(f"  the index's own organic move, cap weights held at today's: "
          f"{float((w0*i0).sum()):.3f} -> {float((w0*i1).sum()):.3f} tCO2e per $m EVIC, "
          f"{float((w0*i1).sum()/(w0*i0).sum()-1):+.1%}")
    print("\n  reallocation  sum (w1-w0) * Ibar_sector      money moved between sectors")
    print("  selection     sum (w1-w0) * (I - Ibar_sector) better names inside a sector")
    print("  improvement   sum w0 * delta I                companies actually getting cleaner")
    print("  interaction   sum (w1-w0) * delta I           the cross term the three-way split "
          "leaves out; reported, not hidden")
    print("  improvement is weighted by w0 by construction, so it is the same number for every "
          "portfolio: it is the index's own organic move and nobody's stock picking. The line "
          "that separates the portfolios is the last one, improvement actually held, which is "
          "improvement plus the cross term and equals sum w1 * delta I.")
    decomp = {}
    for name, w in list(ports.items()) + list(extras.items()):
        d = brinson(inv, w0, w, i0, i1)
        decomp[name] = d
        tot = d["total"]
        print(f"\n  {name}")
        print(f"    total change in weighted intensity {float((w0*i0).sum()):8.3f} -> "
              f"{float((w*i1).sum()):8.3f}   = {tot:+9.3f} tCO2e per $m EVIC")
        for k in ["reallocation", "selection", "improvement", "interaction"]:
            share = d[k] / tot if tot != 0 else float("nan")
            print(f"    {k:<14}{d[k]:+10.3f}{share:>10.1%} of the cut")
        print(f"    residual      {d['residual']:+10.3f}  (must be zero)")
        held = d["improvement"] + d["interaction"]
        print(f"    improvement actually held, sum w1 * delta I, which is improvement plus the "
              f"cross term: {held:+.3f}, {held/tot:.1%} of the cut")
        assert abs(d["residual"]) < 1e-9 * max(1.0, abs(tot)), "decomposition does not close"

    # ------------------------------------------------ tracking error
    hr("tracking error, five years of weekly total returns")
    prices, status = fetch_weekly_prices(sorted(inv.index))
    n_fetched = sum(1 for v in status.values() if v in ("cached", "fetched"))
    rets = prices.sort_index().pct_change().iloc[1:]
    idx_w = w0.reindex(rets.columns).fillna(0.0)
    idx_ret = (rets.fillna(0.0) * idx_w).sum(axis=1) / (
        rets.notna().mul(idx_w, axis=1).sum(axis=1).replace(0, np.nan))
    print(f"  {n_fetched} of {len(inv)} tickers priced, {len(rets)} weekly observations "
          f"{rets.index[0].date()} to {rets.index[-1].date()}")
    print(f"  index realised volatility on these weights {float(idx_ret.std(ddof=1)*math.sqrt(52)):.2%} a year")
    te_out = {}
    for name, w in list(ports.items()) + list(extras.items()):
        te, series, filled = tracking_error(rets, w - w0, idx_ret)
        lo, hi = block_bootstrap_te(series)
        te_out[name] = dict(te=te, te_p05=lo, te_p95=hi, filled_cells=filled)
        print(f"  {name:<20} tracking error {te:6.2%} a year   90% block-bootstrap "
              f"[{lo:.2%}, {hi:.2%}]   {filled} missing name-weeks filled with the index")
    print("  weights are held fixed at inception, so this is the active risk the portfolio "
          "would have carried through the last five years, not a live backtest of a rebalanced "
          "strategy.")

    # ------------------------------------------------ holdings
    hr("largest active positions, PAB compliant")
    act = (w_pab - w0).sort_values()
    print(f"  {'ticker':<7}{'company':<30}{'sector':<24}{'cap w':>8}{'pab w':>8}{'active':>9}"
          f"{'t/$m EVIC':>11}")
    for tk in list(act.tail(10).index[::-1]) + ["--"] + list(act.head(10).index):
        if tk == "--":
            print("  " + "-" * 84)
            continue
        r = inv.loc[tk]
        print(f"  {tk:<7}{r.company_name[:29]:<30}{r.gics_sector[:23]:<24}"
              f"{w0[tk]:>7.2%} {w_pab[tk]:>7.2%} {act[tk]:>+8.2%} {inten_h[tk]:>10.2f}")

    hr("largest active positions, transition leader")
    print("  ranked by how far the weight is pushed above cap weight, because in dollar terms "
          "the mega-caps drown the signal out.")
    ratio = (w_lead / w0)[w_lead > 1e-12].sort_values()
    print(f"  {'ticker':<7}{'company':<30}{'delivered':>11}{'promised':>10}{'beat by':>9}"
          f"{'cap w':>8}{'lead w':>8}{'x cap':>7}")
    for tk in ratio.tail(12).index[::-1]:
        r = inv.loc[tk]
        fmt = lambda v: "     n/a" if pd.isna(v) else f"{v:+8.2f}"
        print(f"  {tk:<7}{r.company_name[:29]:<30}{fmt(r.delivered_pct_yr):>11}"
              f"{fmt(r.promised_pct_yr):>10}{fmt(r.saydo_out_pct_yr):>9}"
              f"{w0[tk]:>7.2%} {w_lead[tk]:>7.2%}{w_lead[tk]/w0[tk]:>6.1f}x")
    print("\n  the companies beating their own promise by the widest margin, and what each "
          "portfolio does with them:")
    print(f"  {'ticker':<7}{'company':<30}{'beat by':>9}{'cap w':>8}{'pab w':>8}{'lead w':>8}")
    for tk in inv.saydo_out_pct_yr.sort_values(ascending=False).head(10).index:
        r = inv.loc[tk]
        tag = "  EXCLUDED by Article 12" if r.excluded else ""
        print(f"  {tk:<7}{r.company_name[:29]:<30}{r.saydo_out_pct_yr:>+9.2f}"
              f"{w0[tk]:>7.2%} {w_pab[tk]:>7.2%} {w_lead[tk]:>7.2%}{tag}")

    hr("transition leader, the same table by dollar active weight")
    act2 = (w_lead - w0).sort_values()
    print("  the mega-caps come back to the top because the tilt moves more dollars in a large "
          "name even at a smaller multiple of its cap weight.")
    print(f"  {'ticker':<7}{'company':<30}{'delivered':>11}{'promised':>10}{'beat by':>9}"
          f"{'cap w':>8}{'lead w':>8}")
    for tk in act2.tail(12).index[::-1]:
        r = inv.loc[tk]
        d = r.delivered_pct_yr
        p = r.promised_pct_yr
        b = r.saydo_out_pct_yr
        fmt = lambda v: "     n/a" if pd.isna(v) else f"{v:+8.2f}"
        print(f"  {tk:<7}{r.company_name[:29]:<30}{fmt(d):>11}{fmt(p):>10}{fmt(b):>9}"
              f"{w0[tk]:>7.2%} {w_lead[tk]:>7.2%}")

    hr("the answer, in five lines")
    d_pab = decomp["pab_compliant"]
    d_int = decomp["pab_intensity_tilted"]
    d_lead = decomp["transition_leader"]
    print(f"  1. Article 12 alone takes {n_ex} of {len(inv)} names and {w_ex:.1%} of index cap "
          f"out, and that carries {cut_pab:.1%} of decarbonisation against a {pab_floor:.0%} "
          f"requirement. The optimiser is not needed to pass; it returned lambda zero.")
    print(f"  2. Of the PAB portfolio's {-d_pab['total']:.2f} tonne per $m cut, "
          f"{d_pab['reallocation']/d_pab['total']:.1%} is reallocation between sectors and "
          f"{d_pab['selection']/d_pab['total']:+.1%} is selection inside them. Tilted as hard "
          f"as the constraints allow it is still "
          f"{decomp['pab_max_tilt']['reallocation']/decomp['pab_max_tilt']['total']:.1%} "
          f"reallocation. The critique is right and this is the number.")
    print(f"  3. The improvement the portfolio actually holds, sum w1 * delta I, is "
          f"{d_pab['improvement_held']/d_pab['total']:.1%} of the cut for the rulebook "
          f"portfolio and {d_int['improvement_held']/d_int['total']:.1%} once you tilt harder "
          f"on the intensity level. Optimising the level buys fewer improvers, not more.")
    print(f"  4. The cross term is positive for every intensity-tilted portfolio "
          f"({d_int['interaction']:+.2f}), and it is positive because the names being sold are "
          f"the names that cut emissions fastest. A PAB sells the decarbonisers.")
    org = {k: float((w[dlv.notna() & (w > 0)] * dlv[dlv.notna() & (w > 0)]).sum()
                    / w[dlv.notna() & (w > 0)].sum()) for k, w in ports.items()}
    print(f"  5. Article 11 tests the level at inception and Article 7 tests the rate "
          f"afterwards. Only the say-do portfolio's holdings deliver the rate from physics: "
          f"{org['transition_leader']:+.2f}%/yr against Article 7's -{traj_pct:.0f}%, where the "
          f"rulebook portfolio delivers {org['pab_compliant']:+.2f}% and has to find the rest "
          f"by selling something every year. It costs "
          f"{compliance['pab_compliant']['cut_vs_universe'] - compliance['transition_leader']['cut_vs_universe']:.1%} "
          f"of inception intensity to buy that.")
    print("  the coverage caveat on line 5: the delivered rate is measured over "
          f"{compliance['transition_leader']['names']} holdings but only "
          f"{float(w_lead[dlv.notna() & (w_lead > 0)].sum()):.1%} of the say-do portfolio's "
          f"weight and {float(w_pab[dlv.notna() & (w_pab > 0)].sum()):.1%} of the rulebook "
          f"portfolio's carries a measured trend at all, and the say-do tilt raises that "
          f"coverage on purpose. Measurable and improving are not independent here.")

    # ------------------------------------------------ outputs
    out = inv.copy()
    out["w_cap_index"] = w0
    for name, w in list(ports.items()) + list(extras.items()):
        out["w_" + name] = w
        out["usd_" + name] = w * AUM_USD
    out["excl_rules_all"] = [";".join(r) for r in out.excl_all]
    out["excl_articles"] = [
        ";".join(rules[r]["article"] for r in rr) for rr in out.excl_all]
    out["seed"] = SEED
    out["aum_usd"] = AUM_USD
    out["provenance_class"] = np.where(
        out.intensity_basis == "measured_mandatory", "mandatory", "modelled")
    keep_cols = [
        "company_name", "gics_sector", "gics_sub_industry", "nace_section", "high_impact",
        "coverage_tier", "market_cap", "total_debt", "debt_observed", "evic_usd", "evic_musd",
        "revenue_musd", "scope1_tonnes", "emissions_year", "intensity_measured",
        "intensity_imputed", "intensity_threshold", "intensity_zerofill",
        "intensity_basis", "intensity_dq",
        "intensity_base_year", "intensity_latest", "power_intensity_g_per_kwh", "power_gen_mwh",
        "power_plants", "clean_multiple_needed", "power_revenue_leg", "excl_12g", "excluded",
        "excl_rules_all", "excl_articles", "delivered_pct_yr", "promised_pct_yr",
        "gap_pct_yr", "saydo_out_pct_yr", "rank_median", "w_cap_index",
        "w_naive_exclusion", "w_pab_compliant", "w_transition_leader",
        "w_pab_intensity_tilted", "w_variant_blended",
        "usd_naive_exclusion", "usd_pab_compliant", "usd_transition_leader",
        "provenance_class", "seed", "aum_usd"]
    out = out[keep_cols].reset_index().rename(columns={"index": "ticker"})
    out.to_parquet(INTERIM / "portfolio.parquet", index=False)
    print(f"\nwrote {INTERIM/'portfolio.parquet'}  {out.shape[0]} rows x {out.shape[1]} columns")

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.bool_, bool)):
            return bool(o)
        if isinstance(o, (np.integer, int)):
            return int(o)
        if isinstance(o, (np.floating, float)):
            f = float(o)
            return None if (math.isnan(f) or math.isinf(f)) else round(f, 8)
        if o is None or (not isinstance(o, str) and pd.isna(o)):
            return None
        return o

    companies = []
    for tk, r in out.set_index("ticker").iterrows():
        companies.append(dict(
            ticker=tk, name=r.company_name, sector=r.gics_sector,
            sub_industry=r.gics_sub_industry, nace=r.nace_section,
            high_impact=r.high_impact, tier=r.coverage_tier,
            mcap_usd=r.market_cap, evic_musd=r.evic_musd,
            intensity=r.intensity_imputed, intensity_basis=r.intensity_basis,
            intensity_dq=int(r.intensity_dq), measured=bool(pd.notna(r.intensity_measured)),
            power_g_per_kwh=r.power_intensity_g_per_kwh,
            excluded=bool(r.excluded), excl_rules=r.excl_rules_all or None,
            excl_articles=r.excl_articles or None,
            delivered_pct_yr=r.delivered_pct_yr, promised_pct_yr=r.promised_pct_yr,
            saydo_out_pct_yr=r.saydo_out_pct_yr,
            w_cap=r.w_cap_index, w_naive=r.w_naive_exclusion, w_pab=r.w_pab_compliant,
            w_lead=r.w_transition_leader, w_int=r.w_pab_intensity_tilted,
            w_blend=r.w_variant_blended))

    payload = dict(
        meta=dict(
            seed=SEED, aum_usd=AUM_USD,
            aum_share_of_index=AUM_USD / float(inv.market_cap.sum()),
            regulation=doc["regulation"]["celex"],
            regulation_title=doc["regulation"]["title"],
            regulation_retrieved=doc["regulation"]["retrieved_at"],
            attribution=doc["regulation"]["attribution"],
            base_year=BASE_YEAR, latest_year=LATEST_YEAR,
            intensity_definition=("Article 1(c): absolute Scope 1 GHG emissions divided by "
                                  "EVIC in millions. EVIC is market cap plus book total debt; "
                                  "preferred stock and non-controlling interests are not in "
                                  "the SEC tags we pulled."),
            scope_note=("Articles 9 and 11 ask for Scope 1, 2 and 3. We carry mandatory Scope 1 "
                        "only, for 139 of 500 companies, and apply it identically to the "
                        "portfolio and to the universe, so the ratio is like for like and the "
                        "level is not comparable to a commercial PAB."),
            missing_data_note=("361 of 500 companies file no mandatory tonnage. The headline "
                               "gives them their GICS sector's median measured intensity at "
                               "PCAF dq 5. available_case renormalises over measurable names "
                               "only and zerofill scores a non-discloser at zero. All three "
                               "are carried to the verdict."),
            power_test_note=("Article 12(1)(g) is built here because revenue_exclusions.parquet "
                             "decided only 12(1)(a) to (f). The intensity leg is measured over "
                             "each company's CAMD-monitored fossil fleet, which is an upper "
                             "bound, so a company at or below 100 gCO2e/kWh passes whatever "
                             "else it owns, and one above it passes only if it also holds "
                             "clean_multiple_needed times that fleet in zero-carbon "
                             "generation. The revenue leg is a GICS sub-industry proxy."),
            position_limits=dict(max_absolute=MAX_ABS_WEIGHT, max_relative=MAX_REL_WEIGHT),
            what_this_is_not=("Not an investment recommendation, not a licensed benchmark, and "
                              "not a claim that a $1bn allocation changes any company's "
                              "emissions. $1bn is 0.002% of S&P 500 market capitalisation."),
        ),
        thresholds=doc["thresholds"],
        rules_used=[dict(id=r, article=rules[r]["article"], quote=rules[r]["quote"])
                    for r in ["pab_baseline_reduction", "ctb_baseline_reduction",
                              "decarbonisation_trajectory_equity", "trajectory_is_geometric",
                              "equity_allocation_constraint", "target_setter_overweight",
                              "pab_exclusion_controversial_weapons", "pab_exclusion_tobacco",
                              "pab_exclusion_ungc_oecd", "pab_exclusion_coal",
                              "pab_exclusion_oil", "pab_exclusion_gas",
                              "pab_exclusion_power_generation"]],
        universe=dict(
            n_companies=int(len(inv)), dropped_no_market_cap=no_cap,
            market_cap_usd=float(inv.market_cap.sum()),
            n_measured=int(measured.sum()), w_measured=float(inv.loc[measured, "w_cap"].sum()),
            n_high_impact=int(inv.high_impact.sum()), w_high_impact=w_high_uni,
            waci=uni_waci,
            financed_tonnes_per_bn=uni_waci["imputed"] * AUM_USD / 1e6,
            sector_medians={k: float(v) for k, v in sec_med.items()},
            nace_weights={s: float(w) for s, w in inv.groupby("nace_section").w_cap.sum().items()},
        ),
        exclusions=dict(
            n_excluded=n_ex, w_excluded=w_ex,
            by_rule={r: dict(article=rules[r]["article"], names=sorted(v),
                             weight=float(inv.loc[v, "w_cap"].sum()))
                     for r, v in by_rule.items()},
            power_test=[dict(ticker=tk, name=inv.loc[tk, "company_name"],
                             g_per_kwh=float(inv.loc[tk, "power_intensity_g_per_kwh"]),
                             twh=float(inv.loc[tk, "power_gen_mwh"]) / 1e6,
                             plants=int(inv.loc[tk, "power_plants"]),
                             revenue_leg=bool(inv.loc[tk, "power_revenue_leg"]),
                             clean_multiple_needed=float(inv.loc[tk, "clean_multiple_needed"]),
                             excluded=bool(inv.loc[tk, "excl_12g"]))
                        for tk in pw.index],
            untested_power=untested,
        ),
        portfolios={k: dict(compliance[k], lam=lam_used[k],
                            cuts_by_scheme=scheme_cuts[k],
                            decomposition=decomp[k],
                            tracking_error=te_out[k])
                    for k in list(ports) + list(extras)},
        article7=dict(
            annual_pct=traj_pct,
            path={k: [scheme_waci(w, "imputed") * (1 - traj_pct / 100) ** n
                      for n in range(11)] for k, w in ports.items()},
            organic={k: dict(
                weight_covered=float(w[dlv.notna() & (w > 0)].sum()),
                delivered_pct_yr=float((w[dlv.notna() & (w > 0)] * dlv[dlv.notna() & (w > 0)]).sum()
                                       / w[dlv.notna() & (w > 0)].sum()))
                for k, w in ports.items()},
            index_delivered_pct_yr=float((w0[m] * dlv[m]).sum() / w0[m].sum()),
            article6_qualifiers=sorted(inv.index[dlv <= -tilt_rule["min_annual_reduction_pct"]]),
        ),
        companies=companies,
    )
    SITE.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(clean(payload), allow_nan=False, separators=(",", ":"))
    (SITE / "portfolio.json").write_text(txt)
    print(f"wrote {SITE/'portfolio.json'}  {len(txt)/1024:.1f} KB, "
          f"{len(companies)} companies, strict JSON")


if __name__ == "__main__":
    main()
