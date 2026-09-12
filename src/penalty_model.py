"""The per-sector carbon penalty model that drives the interface.

One control: a carbon price per GICS sector. Everything else on the page is an input to the
chain below, and every step of it is settable.

    cost      = sum over scopes of  tonnes x price_sector x coverage_scope
    abatement = the company's OBSERVED annual reduction rate, run to the horizon year
    dEBIT     = cost x (1 - passthrough_sector), after abatement
    dEV       = dEBIT x the company's own EV/EBITDA multiple
    advice    = reweight $1bn by value at risk under Regulation (EU) 2020/1818

The browser recomputes all of it on every slider move, so this script ships coefficients, not
data: per company the tonnes, the observed rate, the multiple and the cap weight, and per
sector the medians and the defaults. The arithmetic in site/js is the five lines above.

The Article 12 exclusion list, the Article 3 bucket and the position caps are not rebuilt here.
They are read from the master table (which carries portfolio.py's verdicts) and the tilt itself
calls portfolio.py's own bucket_tilt and apply_caps, so the rulebook has exactly one
implementation in this repo.

Writes site/data/penalty.json.
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portfolio import (  # noqa: E402  the rulebook has one implementation and this is it
    AUM_USD,
    MAX_ABS_WEIGHT,
    MAX_REL_WEIGHT,
    TILT_ACTIVE_BUDGET,
    apply_caps,
    bucket_tilt,
    cap_weights,
    load_rules,
)

INTERIM = ROOT / "data" / "interim"
MASTER = ROOT / "data" / "master"
SITE = ROOT / "site" / "data"

SEED = 20260912
GENERATED_AT = datetime.now(timezone.utc).replace(microsecond=0)

SECTORS = [
    "Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy",
    "Financials", "Health Care", "Industrials", "Information Technology", "Materials",
    "Real Estate", "Utilities",
]

# ---------------------------------------------------------------------------------- 1. price
# NGFS Phase 5, Price|Carbon, the UNITED STATES path. The World path is the wrong one for US
# tonnes: it starts at $98 in 2025 and reaches $749 by 2050, which is a different curve from a
# different set of marginal abaters. Model is named, never averaged: for Net Zero 2050 at 2030
# REMIND says 283.7 and GCAM says 98.6 for the same scenario and the same country, so a mean of
# the two is a number no model produced.
NGFS_MODEL = "REMIND-MAgPIE 3.3-4.8"
NGFS_REGION = "REMIND-MAgPIE 3.3-4.8|United States of America"
NGFS_SCENARIO = "Net Zero 2050"
NGFS_YEAR = 2030

# The alternative models, offered as presets on the same scenario so the user can see the
# model spread, which is wider than the scenario spread.
NGFS_ALT_MODELS = {
    "REMIND-MAgPIE 3.3-4.8": "REMIND-MAgPIE 3.3-4.8|United States of America",
    "GCAM 6.0 NGFS": "GCAM 6.0 NGFS|USA",
    "MESSAGEix-GLOBIOM 2.0-M-R12-NGFS": "MESSAGEix-GLOBIOM 2.0-R12|North America",
}

# NGFS publishes in US$2010/tCO2 and SEC operating income is nominal. The two are not the same
# unit and nothing here silently reconciles them: the price slider is in US$2010, the deflator
# is its own visible parameter, and the applied price is the product of the two. BEA's GDP
# implicit price deflator, 2010 to 2026, is 1.44.
DEFLATOR_DEFAULT = 1.44

# ------------------------------------------------------------------------------- 2. coverage
# Scope 1 at 100%: an NGFS net-zero price is an economy-wide price, not the EU ETS.
# Scope 2 at 80%, and that number is not a guess. A carbon price is paid by the generator and
# reaches the buyer only through the electricity tariff, so the right coverage for Scope 2 is
# the electricity pass-through rate, which is the same 80% measured by Fabra and Reguant. Set
# both this and the utility pass-through to 100% and the portfolio pays for the same tonne
# twice, once at the power station and once at the meter.
# Scope 3 at 0%. No carbon price in the world taxes a company for its customers' emissions, and
# the GHG Protocol Scope 3 Standard says in terms that one company's Scope 3 is another's
# Scope 1, so summing Scope 3 over a 500-company index prices the same molecule several times.
COVERAGE_DEFAULT = {"scope1": 1.00, "scope2": 0.80, "scope3": 0.00}

# --------------------------------------------------------------------------- 3. pass-through
# Two of these eleven numbers are measured and cited. The other nine are one flat assumption
# applied equally, because we could not find a per-sector estimate we are willing to defend,
# and inventing a sector table would be worse than saying so.
PASSTHROUGH_FLAT = 0.50
PASSTHROUGH_SOURCE = {
    "Utilities": (
        0.80,
        "Fabra and Reguant (2014), 'Pass-Through of Emissions Costs in Electricity Markets', "
        "American Economic Review 104(9) 2872-2899: average pass-through of emissions costs "
        "into wholesale electricity prices is over 80 percent, because electricity clears in "
        "high-frequency auctions against inelastic demand. Measured on the Spanish wholesale "
        "market, not on US regulated utilities, where cost recovery through tariffs would if "
        "anything be higher.",
    ),
    "Materials": (
        0.70,
        "Ganapati, Shapiro and Walker (2020), 'Energy Cost Pass-Through in US Manufacturing: "
        "Estimates and Implications for Carbon Taxes', American Economic Journal: Applied "
        "Economics 12(2) 303-342: about 70 percent of energy-price-driven input cost changes "
        "reach consumers in the short to medium run, estimated on energy-intensive US "
        "manufacturing. Materials is the GICS sector closest to the industries they study.",
    ),
}

# The sector table src/build_master.py stores in master_company.parquet. Carried here as a
# named preset, labelled ungrounded, so the master table's passthrough_pct column stays
# explainable and nothing silently disagrees with it.
PASSTHROUGH_REPO = {
    "Utilities": 0.80, "Consumer Staples": 0.70, "Health Care": 0.70, "Energy": 0.60,
    "Information Technology": 0.60, "Communication Services": 0.60, "Real Estate": 0.60,
    "Industrials": 0.50, "Financials": 0.50, "Consumer Discretionary": 0.40, "Materials": 0.35,
}

# ------------------------------------------------------------------------------ 4. abatement
HORIZON_DEFAULT = NGFS_YEAR          # the price year and the abatement horizon are the same year
ABATE_SCOPES_DEFAULT = {"scope1": True, "scope2": False, "scope3": False}
# delivered_pct_yr is an OLS on measured Scope 1 tonnage. Extending a Scope 1 trend to Scope 2
# would credit a company for moving a boiler onto the grid, so it is off by default.
# DuPont's fitted trend is -38.2%/yr. Compounded to 2050 that is a 99.99% cut, which is not a
# forecast, it is an extrapolation falling off a cliff. The factor is clipped and the binds are
# counted and printed.
ABATE_FLOOR, ABATE_CEILING = 0.05, 3.00

# --------------------------------------------------------------------- 5. missing-data policy
# 181 of the 500 primary listings carry no Scope 1 tonnage from any source. A carbon price
# model that gives them a zero cost makes silence the single safest thing a company can do,
# so zerofill is shipped only as the thing to point at.
GHGRP_THRESHOLD_T = 25_000.0    # 40 CFR Part 98: a US facility at or above this must report
MIN_SECTOR_MEASURABLE = 5
TREATMENTS = ["sector_median", "threshold_bound", "neutral_rank", "zerofill"]
TREATMENT_DEFAULT = "sector_median"

# The EV/EBITDA multiple already carries portfolio-side guards in the master table
# (floor 4x, cap 40x). Value at risk is dEV over EVIC, Article 1(d)'s denominator, which we
# compute ourselves for all 500. Yahoo's enterprise value is shipped alongside and is null on 3.
VAR_DENOMINATOR_DEFAULT = "evic"

rng = np.random.default_rng(SEED)


def hr(title):
    print("\n" + "=" * 94)
    print(title)
    print("=" * 94)


# ---------------------------------------------------------------------------------- load

def ngfs_price_paths(ngfs):
    """Every US carbon price path in the file, by scenario and model, US$2010/tCO2."""
    p = ngfs[(ngfs.variable == "Price|Carbon") & (~ngfs.is_downscaled)
             & (~ngfs.retracted_damage_basis)]
    assert set(p.unit.unique()) == {"US$2010/t CO2"}, p.unit.unique()
    out = {}
    for model, region in NGFS_ALT_MODELS.items():
        q = p[(p.model == model) & (p.region == region)]
        for scen, g in q.groupby("scenario"):
            g = g.sort_values("year")
            out.setdefault(scen, {})[model] = {
                int(y): round(float(v), 2) for y, v in zip(g.year, g.value)}
    world = {}
    for model in NGFS_ALT_MODELS:
        q = p[(p.model == model) & (p.region == "World") & (p.scenario == NGFS_SCENARIO)]
        q = q.sort_values("year")
        world[model] = {int(y): round(float(v), 2) for y, v in zip(q.year, q.value)}
    return out, world


def load_frame():
    m = pd.read_parquet(MASTER / "master_company.parquet")
    assert len(m) == 503, len(m)
    p = m[m.is_primary_listing].copy().set_index("ticker")
    assert len(p) == 500, len(p)
    assert p.index.is_unique

    d = pd.DataFrame(index=p.index)
    d["company_name"] = p.company_name
    d["gics_sector"] = p.gics_sector
    d["s1"] = p.scope1_t
    d["s2"] = p.scope2_market_t
    d["s3"] = p.scope3_total_t
    d["s1_basis"] = p.scope1_basis
    d["s1_year"] = p.scope1_year
    d["s1_dq"] = p.scope1_dq
    d["s1_prov"] = p.provenance_class
    d["s1_floor_flag"] = p.scope1_below_measured_floor
    d["delivered"] = p.delivered_pct_yr
    d["delivered_n"] = p.delivered_n_years
    d["delivered_r2"] = p.delivered_r2
    d["promised"] = p.promised_pct_yr
    d["ebit"] = p.ebit_musd
    d["ebitda"] = p.ebitda_musd
    d["evx"] = p.ev_ebitda_x
    d["evx_basis"] = p.ev_ebitda_basis
    d["ev"] = p.ev_musd
    d["evic"] = p.evic_musd
    d["mcap"] = p.market_cap_musd
    d["revenue"] = p.revenue_musd
    d["excluded"] = p.excluded.astype(bool)
    d["excl_articles"] = p.excl_articles
    d["high_impact"] = p.high_impact_nace.astype(bool)
    d["tier"] = p.coverage_tier
    d["model_dq"] = p.model_dq

    assert d.mcap.notna().all() and (d.mcap > 0).all()
    assert d.evic.notna().all() and (d.evic > 0).all()
    assert d.evx.notna().all()
    d["w_cap"] = cap_weights(d.mcap)
    d["measurable"] = d.s1.notna()
    return d


# ------------------------------------------------------------------- the missing-data schemes

def sector_medians(d, col):
    """Median tonnes per $m of EVIC among the companies of that sector that report."""
    med, n = {}, {}
    for s, g in d.groupby("gics_sector"):
        obs = g[col].notna()
        n[s] = int(obs.sum())
        med[s] = float((g[col] / g.evic)[obs].median()) if obs.any() else float("nan")
    return med, n


def imputations(d):
    """Per-company imputed tonnes for each scheme. Invariant of every slider, so precomputed."""
    m1, n1 = sector_medians(d, "s1")
    m2, n2 = sector_medians(d, "s2")
    thin1 = sorted(s for s in m1 if n1[s] < MIN_SECTOR_MEASURABLE)
    thin2 = sorted(s for s in m2 if n2[s] < MIN_SECTOR_MEASURABLE)

    s1_med = np.array([m1[s] * e if n1[s] >= MIN_SECTOR_MEASURABLE else GHGRP_THRESHOLD_T
                       for s, e in zip(d.gics_sector, d.evic)])
    s2_med = np.array([m2[s] * e if n2[s] >= MIN_SECTOR_MEASURABLE else 0.0
                       for s, e in zip(d.gics_sector, d.evic)])
    return dict(s1_sector_median=s1_med, s2_sector_median=s2_med,
                s1_medians=m1, s2_medians=m2, n1=n1, n2=n2, thin1=thin1, thin2=thin2)


def effective_tonnes(d, imp, treatment):
    """Tonnes actually priced, per scope, under one missing-data treatment.

    neutral_rank invents nothing: the company has no cost at all and is handled downstream by
    giving it the median tilt score rather than a zero one.
    """
    s1 = d.s1.to_numpy(dtype=float)
    s2 = d.s2.to_numpy(dtype=float)
    s3 = d.s3.to_numpy(dtype=float)
    miss1, miss2, miss3 = np.isnan(s1), np.isnan(s2), np.isnan(s3)

    if treatment == "sector_median":
        s1 = np.where(miss1, imp["s1_sector_median"], s1)
        s2 = np.where(miss2, imp["s2_sector_median"], s2)
        s3 = np.where(miss3, 0.0, s3)
    elif treatment == "threshold_bound":
        s1 = np.where(miss1, GHGRP_THRESHOLD_T, s1)
        s2 = np.where(miss2, 0.0, s2)
        s3 = np.where(miss3, 0.0, s3)
    elif treatment == "zerofill":
        s1, s2, s3 = np.nan_to_num(s1), np.nan_to_num(s2), np.nan_to_num(s3)
    elif treatment == "neutral_rank":
        s1 = np.where(miss1, np.nan, s1)
        s2 = np.where(miss1, np.nan, np.nan_to_num(s2))
        s3 = np.where(miss1, np.nan, np.nan_to_num(s3))
    else:
        raise ValueError(treatment)
    return s1, s2, s3


# --------------------------------------------------------------------------------- the chain

def abatement_factor(d, horizon, floor=ABATE_FLOOR, ceiling=ABATE_CEILING):
    """(1 + delivered/100) ^ (horizon - the year the tonnage was measured), clipped.

    1.0 where no observed rate exists. That is the conservative reading and the whole point of
    having measured delivery: a company gets credit for a cut we watched it make, never for one
    it promised.
    """
    dl = d.delivered.to_numpy(dtype=float)
    base = d.s1_year.to_numpy(dtype=float)
    base = np.where(np.isnan(base), horizon, base)
    years = np.clip(horizon - base, 0, None)
    f = np.where(np.isfinite(dl), np.power(1.0 + dl / 100.0, years), 1.0)
    return np.clip(f, floor, ceiling)


def defaults():
    return dict(
        price_usd2010=dict.fromkeys(SECTORS, None),   # filled by main from the NGFS path
        deflator=DEFLATOR_DEFAULT,
        coverage=dict(COVERAGE_DEFAULT),
        passthrough={s: PASSTHROUGH_SOURCE.get(s, (PASSTHROUGH_FLAT,))[0] for s in SECTORS},
        horizon=HORIZON_DEFAULT,
        abate_scopes=dict(ABATE_SCOPES_DEFAULT),
        abate_floor=ABATE_FLOOR, abate_ceiling=ABATE_CEILING,
        treatment=TREATMENT_DEFAULT,
        var_denominator=VAR_DENOMINATOR_DEFAULT,
        tilt_budget=TILT_ACTIVE_BUDGET,
    )


def run_chain(d, imp, par):
    """Cost, dEBIT and dEV per company. Pure arithmetic; this is what the browser reproduces."""
    sec = d.gics_sector.to_numpy()
    price = np.array([par["price_usd2010"][s] for s in sec]) * par["deflator"]
    pt = np.array([par["passthrough"][s] for s in sec])
    cov = par["coverage"]

    s1, s2, s3 = effective_tonnes(d, imp, par["treatment"])
    fac = abatement_factor(d, par["horizon"], par["abate_floor"], par["abate_ceiling"])
    f1 = fac if par["abate_scopes"]["scope1"] else np.ones_like(fac)
    f2 = fac if par["abate_scopes"]["scope2"] else np.ones_like(fac)
    f3 = fac if par["abate_scopes"]["scope3"] else np.ones_like(fac)

    known = np.isfinite(s1) | np.isfinite(s2) | np.isfinite(s3)
    priced = (np.nan_to_num(s1) * cov["scope1"] * f1
              + np.nan_to_num(s2) * cov["scope2"] * f2
              + np.nan_to_num(s3) * cov["scope3"] * f3)
    priced = np.where(known, priced, np.nan)

    cost = priced * price / 1e6                       # USD millions
    debit = cost * (1.0 - pt)
    dev = debit * d.evx.to_numpy(dtype=float)
    den = d.evic.to_numpy(dtype=float) if par["var_denominator"] == "evic" \
        else d.ev.to_numpy(dtype=float)
    var_pct = np.where(np.isfinite(den) & (den > 0), 100.0 * dev / den, np.nan)

    ebit = d.ebit.to_numpy(dtype=float)
    ear_pct = np.where(ebit > 0, 100.0 * debit / ebit, np.nan)
    return dict(price=price, passthrough=pt, factor=fac, s1=s1, s2=s2, s3=s3,
                priced_t=priced, cost=cost, debit=debit, dev=dev, var_pct=var_pct,
                ear_pct=ear_pct)


# ----------------------------------------------------------------------------------- advice

def tilt_score(d, var_pct, treatment):
    """Percentile rank of value at risk. 1.0 is the most exposed name in the index.

    Under neutral_rank a company with no tonnage scores 0.5, the median of the companies we can
    judge: it is neither rewarded nor punished for not being measurable. Under every other
    treatment it carries the value at risk its imputed tonnes produce.
    """
    v = pd.Series(var_pct, index=d.index)
    # Rank the value at risk relative to the largest in the index, rounded, so that a change of
    # price UNITS cannot manufacture an ordering. Under the sector-median treatment an imputed
    # company's value at risk collapses to sector median x price x (1 - passthrough) x its own
    # multiple, the EVIC cancels, and the 31 Financials carrying the sector-median multiple are
    # genuinely tied. Ranking the raw float let a reprice from 283.70 to 1000 break those ties
    # in the last bits and move $36 of the $1bn. Ties are ties.
    mx = float(np.nanmax(np.abs(v.to_numpy()))) if v.notna().any() else 0.0
    vn = (v / mx).round(9) if mx > 0 else v
    s = vn.rank(pct=True, method="average")
    if treatment == "neutral_rank":
        s = s.fillna(0.5)
    else:
        s = s.fillna(float(s.median()) if s.notna().any() else 0.5)
    return s


def fast_caps(w, base, max_abs, max_rel):
    """apply_caps in numpy. Asserted equal to src/portfolio.py's pandas original at run time."""
    cap = np.minimum(max_abs, max_rel * base)
    w = w.copy()
    for _ in range(200):
        over = w > cap + 1e-15
        if not over.any():
            break
        spill = float((w[over] - cap[over]).sum())
        w[over] = cap[over]
        free = (~over) & (w > 0)
        if not free.any() or spill <= 0:
            break
        w[free] = w[free] + spill * w[free] / w[free].sum()
    return w / w.sum()


def fast_tilt(w_cap, hi, keep, score, lam, buckets):
    """bucket_tilt in numpy, for the 3,000-draw sensitivity loop only.

    The shipped defaults and every number in the JSON go through portfolio.py's own
    bucket_tilt. This exists because the pandas original costs 25 to 120 ms a call and the
    sensitivity needs 3,000 of them, and main() asserts the two agree to 1e-12 before using it.
    """
    w = np.zeros_like(w_cap)
    for bucket, target in buckets.items():
        sel = keep & (hi == bucket)
        if not sel.any() or target <= 0:
            continue
        base = w_cap[sel]
        raw = base * np.exp(-lam * score[sel])
        if raw.sum() <= 0:
            continue
        inner = raw / raw.sum()
        inner = fast_caps(inner, base / base.sum(), MAX_ABS_WEIGHT / max(target, 1e-12),
                          MAX_REL_WEIGHT)
        w[sel] = inner * target
    return w / w.sum()


def solve_budget(d, keep, score, buckets, w0, w_base, budget):
    """Bisect the tilt strength to a stated addition to active share over the screen-only book.

    Same device, same budget and the same bucket_tilt as src/portfolio.py's transition_leader,
    so the two books are comparable rather than two different aggressions.
    """
    want = float(0.5 * (w_base - w0).abs().sum()) + budget
    lo, hi = 0.0, 400.0
    for _ in range(90):
        mid = 0.5 * (lo + hi)
        wm = bucket_tilt(d, keep, score, mid, buckets)
        if float(0.5 * (wm - w0).abs().sum()) < want:
            lo = mid
        else:
            hi = mid
    return hi, bucket_tilt(d, keep, score, hi, buckets)


def advise(d, chain, par, w0, buckets, w_base, lam=None):
    """lam given: one tilt. lam None: bisect it to the active-share budget in par."""
    keep = ~d.excluded
    score = tilt_score(d, chain["var_pct"], par["treatment"])
    if lam is None:
        lam, w = solve_budget(d, keep, score, buckets, w0, w_base, par["tilt_budget"])
    else:
        w = bucket_tilt(d, keep, score, lam, buckets)
    return dict(lam=lam, w=w, score=score, keep=keep)


# ------------------------------------------------------------------------------ sensitivity

from score import omega2  # noqa: E402  the same correlation ratio the score lane reports

SENS_DRAWS = 3000
SENS_BINS = 8


def sample_params(base, rng_):
    """One draw over every modelling choice in the chain at once."""
    treatment = TREATMENTS[int(rng_.integers(len(TREATMENTS)))]
    level = float(np.exp(rng_.uniform(np.log(20.0), np.log(900.0))))
    disp = float(rng_.uniform(0.0, 0.8))
    mult = np.exp(rng_.normal(0.0, disp, len(SECTORS)))
    mult = mult / np.exp(np.mean(np.log(mult)))
    # Real carbon pricing exempts sectors outright far more often than it reprices them by a
    # factor of two: free allocation, carbon leakage carve-outs, agriculture and aviation. So
    # the sector price is tested two ways, a smooth dispersion and a hard exemption.
    p_ex = float(rng_.uniform(0.0, 0.4))
    exempt = rng_.random(len(SECTORS)) < p_ex
    mult = np.where(exempt, 0.0, mult)
    pt_mean = float(rng_.uniform(0.0, 0.95))
    pt_disp = float(rng_.uniform(0.0, 0.35))
    pt = np.clip(pt_mean + rng_.normal(0.0, pt_disp, len(SECTORS)), 0.0, 0.98)
    par = dict(base)
    par["price_usd2010"] = {s: level * m for s, m in zip(SECTORS, mult)}
    par["passthrough"] = {s: float(v) for s, v in zip(SECTORS, pt)}
    par["deflator"] = float(rng_.uniform(1.0, 1.6))
    par["coverage"] = dict(scope1=float(rng_.uniform(0.5, 1.0)),
                           scope2=float(rng_.uniform(0.0, 1.0)),
                           scope3=float(rng_.uniform(0.0, 0.5)))
    par["horizon"] = int(rng_.integers(2026, 2051))
    par["treatment"] = treatment
    par["var_denominator"] = "evic" if rng_.random() < 0.5 else "ev"
    lam = float(rng_.uniform(0.0, 8.0))
    x = dict(treatment=TREATMENTS.index(treatment), price_level=level,
             price_dispersion=disp, sectors_exempt=float(exempt.sum()),
             passthrough_level=pt_mean,
             passthrough_dispersion=pt_disp, deflator=par["deflator"],
             coverage_scope1=par["coverage"]["scope1"],
             coverage_scope2=par["coverage"]["scope2"],
             coverage_scope3=par["coverage"]["scope3"],
             horizon=par["horizon"],
             var_denominator=0 if par["var_denominator"] == "evic" else 1,
             tilt_strength=lam)
    return par, x, lam


def bin_labels(v, name, n_bins):
    v = np.asarray(v, dtype=float)
    if name in ("treatment", "var_denominator", "sectors_exempt"):
        lab = v.astype(int)
        return lab, int(lab.max()) + 1
    q = np.quantile(v, np.linspace(0, 1, n_bins + 1)[1:-1])
    return np.digitize(v, q), n_bins


def jsonable(o):
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, float):
        return None if not np.isfinite(o) else o
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return [jsonable(v) for v in o.tolist()]
    if o is None or isinstance(o, (str, int, bool)):
        return o
    if pd.isna(o):
        return None
    return o


def r(x, nd=4):
    """Round for the wire, and turn every flavour of missing into null."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return round(f, nd)


# ---------------------------------------------------------------------------------- main

def main():
    doc, rules = load_rules()
    d = load_frame()
    imp = imputations(d)
    ngfs = pd.read_parquet(INTERIM / "ngfs_scenarios.parquet")
    paths, world = ngfs_price_paths(ngfs)

    price_default = paths[NGFS_SCENARIO][NGFS_MODEL][NGFS_YEAR]
    par = defaults()
    par["price_usd2010"] = dict.fromkeys(SECTORS, price_default)

    hr("the price, and which path it is")
    print(f"  NGFS Phase 5   {NGFS_SCENARIO}, {NGFS_MODEL}, {NGFS_REGION}, {NGFS_YEAR}")
    print(f"  default penalty  {price_default:,.2f} US$2010/tCO2, the same figure the earnings "
          f"lane priced with")
    print(f"  deflator         {DEFLATOR_DEFAULT} (BEA GDP implicit price deflator 2010 to "
          f"2026), a visible parameter, so the applied price is "
          f"{price_default * DEFLATOR_DEFAULT:,.2f} nominal $/t")
    print("  NGFS publishes US$2010 and SEC operating income is nominal. The two are different "
          "units. The slider is in US$2010 and the deflator is its own control, so nothing is "
          "scaled behind the user's back.")
    for model in NGFS_ALT_MODELS:
        v = paths[NGFS_SCENARIO].get(model, {})
        print(f"  same scenario, same country, {model:34s} 2030 = {v.get(NGFS_YEAR, float('nan')):8,.1f}")
    print(f"  the WORLD path of the same scenario and model: 2025 = "
          f"{world[NGFS_MODEL].get(2025):.1f}, 2050 = {world[NGFS_MODEL].get(2050):.1f}. That "
          f"is a different curve for a different set of abaters and it is not the one to price "
          f"US tonnes with.")
    print("  src/build_master.py stored GCAM's 98.6 as its default and this lane uses REMIND's "
          "283.70. Same file, same scenario, same year, same country, 2.9x apart. The model "
          "choice is now a preset in the UI rather than a constant in one script.")

    hr("coverage per scope")
    for k, v in COVERAGE_DEFAULT.items():
        print(f"  {k:8s} {v:5.0%}")
    print("  Scope 2 defaults to the electricity pass-through rate, not to 100%. A carbon "
          "price is paid at the power station; it reaches the buyer only through the tariff. "
          "Setting Scope 2 coverage and the utility pass-through both to 100% charges the "
          "same tonne twice inside one portfolio.")
    print("  Scope 3 defaults to zero. No carbon price taxes a company for its customers' "
          "emissions, and one company's Scope 3 is another's Scope 1, which the GHG Protocol "
          "Scope 3 Standard states in terms. Summing it across 500 companies triple counts.")

    hr("pass-through, and where each number came from")
    for s in SECTORS:
        v, src = PASSTHROUGH_SOURCE.get(s, (PASSTHROUGH_FLAT, None))
        tag = "measured" if src else "FLAT ASSUMPTION, no source"
        print(f"  {s:24s} {v:5.0%}   {tag}")
    print("  Two of eleven are cited. The other nine are one number applied equally, because "
          "we could not find a per-sector estimate we would defend in front of a judge, and a "
          "made-up sector table is worse than an honest flat one. All eleven are sliders.")

    # ------------------------------------------------------------------ the chain at defaults
    chain = run_chain(d, imp, par)
    w0 = d.w_cap.copy()
    buckets = {True: float(w0[d.high_impact].sum()), False: 1.0 - float(w0[d.high_impact].sum())}
    keep = ~d.excluded
    w_screen = bucket_tilt(d, keep, pd.Series(0.0, index=d.index), 0.0, buckets)
    adv = advise(d, chain, par, w0, buckets, w_screen)
    w = adv["w"]

    hr("the chain at the defaults")
    n_meas = int(d.measurable.sum())
    print(f"  500 primary listings. {n_meas} carry a Scope 1 tonnage in the master table, "
          f"{500 - n_meas} carry none.")
    print(f"  of the {n_meas}, mandatory basis {int((d.s1_prov == 'mandatory').sum())}, "
          f"voluntary {int((d.s1_prov == 'voluntary').sum())}, modelled "
          f"{int((d.s1_prov == 'modelled').sum())}.")
    print(f"  139 listings carry a MANDATORY measured tonnage somewhere in the data; only "
          f"{int((d.s1_prov == 'mandatory').sum())} of them win the precedence and become the "
          f"headline Scope 1, because a self-report that clears the EPA floor is preferred.")
    n_tier_gap = int(((d.tier == "unmeasurable") & d.measurable).sum())
    print(f"  the scores lane calls 273 listings unmeasurable and this table carries a Scope 1 "
          f"for {n_tier_gap} of them, because the master table added WBA self-reports the "
          f"score lane never saw. Both counts are shipped: they answer different questions.")
    tot_cost = float(np.nansum(chain["cost"]))
    tot_debit = float(np.nansum(chain["debit"]))
    tot_dev = float(np.nansum(chain["dev"]))
    print(f"\n  index totals, all 500, treatment {par['treatment']}:")
    print(f"    priced tonnes        {np.nansum(chain['priced_t'])/1e6:12,.1f} MtCO2e")
    print(f"    gross carbon cost    {tot_cost/1e3:12,.1f} $bn a year")
    print(f"    dEBIT after {par['passthrough']['Utilities']:.0%}/{PASSTHROUGH_FLAT:.0%} "
          f"pass-through {tot_debit/1e3:9,.1f} $bn")
    print(f"    dEV                  {tot_dev/1e3:12,.1f} $bn of enterprise value")
    print(f"    that is {100*tot_dev/float(d.evic.sum()):.2f}% of the index's "
          f"${float(d.evic.sum())/1e6:,.2f} trn of EVIC")

    ear = chain["ear_pct"]
    n_loss = int((d.ebit <= 0).sum())
    n_loss_meas = int(((d.ebit <= 0) & d.measurable).sum())
    over100 = d.index[(ear > 100)].tolist()
    print(f"\n  operating income: {n_loss} of 500 primary listings lost money last fiscal year, "
          f"{n_loss_meas} of them carry a tonnage. dEBIT as a share of EBIT is null for every "
          f"one of them, never a ratio against a negative denominator.")
    print(f"  {len(over100)} companies show dEBIT above 100% of operating income at the "
          f"default price: {sorted(over100)[:12]}{' ...' if len(over100) > 12 else ''}")
    print("  those are flagged, not published bare. A 6,000% figure is a statement about a "
          "thin margin, not about carbon.")

    # ------------------------------------------------------- price is a scale, not a ranking
    par_hi = dict(par)
    par_hi["price_usd2010"] = dict.fromkeys(SECTORS, 1000.0)
    chain_hi = run_chain(d, imp, par_hi)
    adv_hi = advise(d, chain_hi, par_hi, w0, buckets, w_screen)
    wdiff = float(np.max(np.abs(adv_hi["w"] - w)))
    ratio = np.nanmedian(chain_hi["dev"] / chain["dev"])

    hr("the first finding, and it is analytic")
    print(f"  raise every sector's price from {price_default:.2f} to 1000.00 US$2010 and every "
          f"company's dEV multiplies by {ratio:.4f} = 1000/{price_default:.2f}.")
    print(f"  the allocation does not move at all. Largest weight change across 500 names: "
          f"{wdiff:.2e}.")
    print("  a uniform carbon price is a scalar on every company's cost, so it cannot reorder "
          "them, so it cannot change one dollar of the advice. The price sets how much money "
          "is at risk. What sets where the money goes is, in the measured order below, the "
          "treatment of the companies we cannot measure, then whether a sector is EXEMPTED "
          "outright, and then whether Scope 3 is switched on.")

    # ---------------------------------------------------------------------------- the advice
    var = pd.Series(chain["var_pct"], index=d.index)
    port_var = float((w * var.fillna(var.median())).sum())
    idx_var = float((w0 * var.fillna(var.median())).sum())
    hr("the advice: $1bn under the default penalty")
    print(f"  Article 12 excludes {int(d.excluded.sum())} of 500 names, "
          f"{float(w0[d.excluded].sum()):.2%} of index cap. Read from the master table, which "
          f"carries src/portfolio.py's verdicts. Not reimplemented here.")
    print(f"  Article 3 high-impact bucket pinned at the universe's {buckets[True]:.2%}.")
    print(f"  position caps {MAX_ABS_WEIGHT:.0%} absolute and {MAX_REL_WEIGHT:.0f}x cap weight, "
          f"src/portfolio.py's apply_caps.")
    print(f"  tilt on the percentile rank of value at risk, strength solved to "
          f"{par['tilt_budget']:.0%} of active share on top of the screen-only book: "
          f"lambda = {adv['lam']:.4f}")
    print(f"  names held {int((w > 1e-12).sum())}, active share "
          f"{float(0.5*(w-w0).abs().sum()):.2%}, effective N {1.0/float((w**2).sum()):.0f}")
    print(f"  value at risk of a $1bn cap-weighted index holding: ${idx_var*AUM_USD/100/1e6:,.1f}m")
    print(f"  value at risk of the advised $1bn book:             "
          f"${port_var*AUM_USD/100/1e6:,.1f}m, {1-port_var/idx_var:.1%} lower")
    top_add = (w - w0).sort_values(ascending=False).head(10)
    top_cut = (w - w0).sort_values().head(10)
    print("\n  biggest additions            biggest reductions")
    for (a, av), (b, bv) in zip(top_add.items(), top_cut.items()):
        print(f"    {a:6s} {av*AUM_USD/1e6:+8.2f} $m          {b:6s} {bv*AUM_USD/1e6:+8.2f} $m")

    # -------------------------------------------------------- what happens to the unmeasured
    hr("the 181 companies we cannot measure, and the four things you can do about them")
    treat_out = {}
    for t in TREATMENTS:
        pt_ = dict(par)
        pt_["treatment"] = t
        ch = run_chain(d, imp, pt_)
        ad = advise(d, ch, pt_, w0, buckets, w_screen)
        wt = ad["w"]
        miss = ~d.measurable
        treat_out[t] = dict(
            imputed_mt=float(np.nansum(np.where(miss, np.nan_to_num(ch["priced_t"]), 0.0)) / 1e6),
            share_of_priced=float(np.nansum(np.where(miss, np.nan_to_num(ch["priced_t"]), 0.0))
                                  / np.nansum(ch["priced_t"])),
            weight_unmeasurable=float(wt[miss].sum()),
            weight_unmeasurable_index=float(w0[miss].sum()),
            dollars_unmeasurable=float(wt[miss].sum() * AUM_USD / 1e6),
            turnover_vs_default=float(0.5 * (wt - w).abs().sum()),
            lam=float(ad["lam"]),
            portfolio_var=float((wt * pd.Series(ch["var_pct"], index=d.index)
                                 .fillna(pd.Series(ch["var_pct"], index=d.index).median())).sum()),
            w=wt)
    print(f"  {'treatment':18s}{'tonnes invented':>17}{'of all priced':>15}"
          f"{'weight on them':>16}{'$m of the bn':>14}{'turnover vs default':>21}")
    for t in TREATMENTS:
        o = treat_out[t]
        print(f"  {t:18s}{o['imputed_mt']:14,.1f} Mt{o['share_of_priced']:15.1%}"
              f"{o['weight_unmeasurable']:16.2%}{o['dollars_unmeasurable']:14,.1f}"
              f"{o['turnover_vs_default']:21.2%}")
    print(f"  the cap-weighted index puts {float(w0[~d.measurable].sum()):.2%} on those 181 "
          f"names, ${float(w0[~d.measurable].sum())*AUM_USD/1e6:,.0f}m of a $1bn book.")
    print("  sector_median   the sector's median tonnes per $m of EVIC times this company's "
          "own EVIC. Biased HIGH and we say so: a company only files a GHGRP tonnage if a US "
          "facility crosses 25,000 tCO2e, so the reporters are the heavy end of their own "
          "sector. It is the default because being wrong in the direction of caution is the "
          "only defensible way to be wrong here.")
    print(f"  threshold_bound every non-filer at exactly {GHGRP_THRESHOLD_T:,.0f} tCO2e, the 40 "
          "CFR Part 98 line. This is the one number the law lets us infer, and it is a "
          "statement about a FACILITY, not a company: a firm with forty small sites clears it "
          "on every one and still emits.")
    print("  neutral_rank    no tonnage is invented at all. The company has no cost, and in "
          "the tilt it takes the median score of the companies we can judge, so silence is "
          "neither rewarded nor punished. The honest abstention.")
    print("  zerofill        a zero cost, which makes a company that discloses nothing the "
          "single safest holding in the index. Shipped so the UI can show what it does, never "
          "as a default.")
    print(f"  the spread between the best and worst of those on how much of the $1bn lands on "
          f"unmeasurable companies is "
          f"{(max(treat_out[t]['weight_unmeasurable'] for t in TREATMENTS) - min(treat_out[t]['weight_unmeasurable'] for t in TREATMENTS)):.2%} "
          f"of the fund. That is the single biggest lever on this page.")

    # ------------------------------------------------------------------------------- the trace
    TRACE = "NUE"
    i = d.index.get_loc(TRACE)
    row = d.loc[TRACE]
    trace = dict(
        ticker=TRACE, company_name=row.company_name, sector=row.gics_sector,
        scope1_t=float(row.s1), scope1_basis=row.s1_basis, scope1_year=int(row.s1_year),
        scope1_below_measured_floor=bool(row.s1_floor_flag),
        scope2_t=float(row.s2), scope3_t=None if pd.isna(row.s3) else float(row.s3),
        price_usd2010=price_default, deflator=par["deflator"],
        price_applied=price_default * par["deflator"],
        coverage=dict(COVERAGE_DEFAULT),
        delivered_pct_yr=float(row.delivered), delivered_n_years=int(row.delivered_n),
        promised_pct_yr=None if pd.isna(row.promised) else float(row.promised),
        horizon=par["horizon"], abatement_years=par["horizon"] - int(row.s1_year),
        abatement_factor=float(chain["factor"][i]),
        priced_tonnes=float(chain["priced_t"][i]),
        cost_musd=float(chain["cost"][i]),
        passthrough=float(chain["passthrough"][i]),
        d_ebit_musd=float(chain["debit"][i]),
        ebit_musd=float(row.ebit), d_ebit_pct_of_ebit=float(chain["ear_pct"][i]),
        ev_ebitda_x=float(row.evx), ev_ebitda_basis=row.evx_basis,
        d_ev_musd=float(chain["dev"][i]), evic_musd=float(row.evic),
        var_pct=float(chain["var_pct"][i]),
        var_rank_pct=float(adv["score"][TRACE]),
        excluded=bool(row.excluded), high_impact=bool(row.high_impact),
        w_index=float(w0[TRACE]), w_advised=float(w[TRACE]),
        usd_index=float(w0[TRACE]) * AUM_USD, usd_advised=float(w[TRACE]) * AUM_USD)

    hr(f"the trace: {TRACE}, {row.company_name}, every step with real numbers")
    print(f"  1 tonnes      Scope 1 {trace['scope1_t']:>14,.0f} t   basis {trace['scope1_basis']}"
          f" ({trace['scope1_year']}), below the EPA floor flag "
          f"{trace['scope1_below_measured_floor']}")
    print(f"                Scope 2 {trace['scope2_t']:>14,.0f} t   Scope 3 "
          f"{trace['scope3_t'] if trace['scope3_t'] else 0:>14,.0f} t")
    print(f"  2 price       {trace['price_usd2010']:.2f} US$2010 x deflator "
          f"{trace['deflator']} = {trace['price_applied']:.2f} $/t")
    print(f"  3 coverage    Scope 1 x {COVERAGE_DEFAULT['scope1']:.0%}, Scope 2 x "
          f"{COVERAGE_DEFAULT['scope2']:.0%}, Scope 3 x {COVERAGE_DEFAULT['scope3']:.0%}")
    print(f"  4 abatement   delivered {trace['delivered_pct_yr']:+.3f}%/yr over "
          f"{trace['delivered_n_years']} years of EPA tonnage "
          f"(promised {trace['promised_pct_yr']:+.2f}%/yr), "
          f"run {trace['horizon']} - {trace['scope1_year']} = {trace['abatement_years']} years: "
          f"(1{trace['delivered_pct_yr']/100:+.5f})^{trace['abatement_years']} = "
          f"{trace['abatement_factor']:.5f}")
    print(f"                priced tonnes = {trace['scope1_t']:,.0f} x "
          f"{COVERAGE_DEFAULT['scope1']:.2f} x {trace['abatement_factor']:.5f} + "
          f"{trace['scope2_t']:,.0f} x {COVERAGE_DEFAULT['scope2']:.2f} = "
          f"{trace['priced_tonnes']:,.0f} t")
    print(f"  5 cost        {trace['priced_tonnes']:,.0f} t x ${trace['price_applied']:.2f} = "
          f"${trace['cost_musd']:,.1f}m a year")
    print(f"  6 dEBIT       ${trace['cost_musd']:,.1f}m x (1 - {trace['passthrough']:.2f}) = "
          f"${trace['d_ebit_musd']:,.1f}m, which is "
          f"{trace['d_ebit_pct_of_ebit']:.1f}% of ${trace['ebit_musd']:,.0f}m of operating income")
    print(f"  7 dEV         ${trace['d_ebit_musd']:,.1f}m x {trace['ev_ebitda_x']:.3f}x "
          f"({trace['ev_ebitda_basis']}) = ${trace['d_ev_musd']:,.0f}m")
    print(f"  8 value at risk ${trace['d_ev_musd']:,.0f}m / ${trace['evic_musd']:,.0f}m EVIC = "
          f"{trace['var_pct']:.2f}%, which is the "
          f"{trace['var_rank_pct']*100:.1f}th percentile of the index")
    print(f"  9 allocation  not excluded, high climate impact {trace['high_impact']}. "
          f"index weight {trace['w_index']*100:.4f}% = ${trace['usd_index']/1e6:,.3f}m of $1bn")
    print(f"                advised weight {trace['w_advised']*100:.4f}% = "
          f"${trace['usd_advised']/1e6:,.3f}m, a cut of "
          f"${(trace['usd_index']-trace['usd_advised'])/1e6:,.3f}m")

    # ---------------------------------------------------------------------------- sensitivity
    hr(f"sensitivity: {SENS_DRAWS} draws over every modelling choice in the chain at once")
    import time
    t0 = time.time()
    rng_s = np.random.default_rng(SEED)
    names = ["treatment", "price_level", "price_dispersion", "sectors_exempt",
             "passthrough_level", "passthrough_dispersion", "deflator", "coverage_scope1",
             "coverage_scope2", "coverage_scope3", "horizon", "var_denominator",
             "tilt_strength"]
    X = {k: np.zeros(SENS_DRAWS) for k in names}
    W = np.zeros((SENS_DRAWS, len(d)))
    R = np.zeros((SENS_DRAWS, len(d)))
    wc_a = d.w_cap.to_numpy()
    hi_a = d.high_impact.to_numpy()
    keep_a = (~d.excluded).to_numpy()
    chk = fast_tilt(wc_a, hi_a, keep_a, adv["score"].to_numpy(), adv["lam"], buckets)
    assert np.max(np.abs(chk - w.to_numpy())) < 1e-12, "fast_tilt disagrees with bucket_tilt"
    print(f"  numpy tilt agrees with src/portfolio.py's bucket_tilt to "
          f"{np.max(np.abs(chk - w.to_numpy())):.1e}")

    W_fix = np.zeros((SENS_DRAWS, len(d)))
    for j in range(SENS_DRAWS):
        pj, xj, lam_j = sample_params(par, rng_s)
        cj = run_chain(d, imp, pj)
        sj = tilt_score(d, cj["var_pct"], pj["treatment"]).to_numpy()
        for k in names:
            X[k][j] = xj[k]
        W[j] = fast_tilt(wc_a, hi_a, keep_a, sj, lam_j, buckets)
        W_fix[j] = fast_tilt(wc_a, hi_a, keep_a, sj, adv["lam"], buckets)
        R[j] = sj
    print(f"  {SENS_DRAWS} draws in {time.time()-t0:.1f}s")

    turnover = 0.5 * np.abs(W_fix - w.to_numpy()[None, :]).sum(axis=1)
    sens = {}
    for k in names:
        lab, nl = bin_labels(X[k], k, SENS_BINS)
        sens[k] = dict(allocation=float(np.mean(omega2(W, lab, nl))),
                       allocation_fixed_lambda=float(np.mean(omega2(W_fix, lab, nl))),
                       var_rank=float(np.mean(omega2(R, lab, nl))),
                       turnover=float(omega2(turnover[:, None], lab, nl)[0]))
    model_inputs = [k for k in names if k != "tilt_strength"]
    order = sorted(model_inputs, key=lambda k: -sens[k]["allocation_fixed_lambda"])
    order = order + ["tilt_strength"]
    print(f"  correlation ratio eta^2, the estimator src/score.py reports, {SENS_BINS} "
          f"quantile bins per input")
    print(f"  {'input':26s}{'allocation':>13}{'at fixed tilt':>15}{'VaR rank':>11}"
          f"{'turnover':>11}")
    for k in order:
        tag = "   <- the manager's own risk budget, not a carbon input" \
            if k == "tilt_strength" else ""
        print(f"  {k:26s}{sens[k]['allocation']:13.3f}"
              f"{sens[k]['allocation_fixed_lambda']:15.3f}{sens[k]['var_rank']:11.3f}"
              f"{sens[k]['turnover']:11.3f}{tag}")
    print(f"  sum of first-order shares on the allocation: "
          f"{sum(sens[k]['allocation'] for k in names):.3f}, the rest is interactions.")
    print(f"  'at fixed tilt' holds lambda at the default {adv['lam']:.4f} and varies only the "
          f"carbon model, which is the column that answers the question.")
    print(f"  the score lane put missing_data at 0.201 of first-order rank variance and it was "
          f"the largest single share there too. Same finding, a different model, and here it "
          f"is not close.")

    # ------------------------------------------------------------------------------- the JSON
    sec_idx = {s: i for i, s in enumerate(SECTORS)}
    var_arr = chain["var_pct"]
    companies = []
    for k, tk in enumerate(d.index):
        row = d.loc[tk]
        companies.append({
            "t": tk,
            "n": row.company_name,
            "sec": sec_idx[row.gics_sector],
            "s1": r(row.s1, 1), "s2": r(row.s2, 1), "s3": r(row.s3, 1),
            "s1i": r(imp["s1_sector_median"][k], 3),
            "s2i": r(imp["s2_sector_median"][k], 3),
            "s1y": None if pd.isna(row.s1_year) else int(row.s1_year),
            "s1b": None if pd.isna(row.s1_basis) else row.s1_basis,
            "s1p": None if pd.isna(row.s1_prov) else row.s1_prov,
            "flr": bool(row.s1_floor_flag),
            "dlv": r(row.delivered, 4), "dlvn": None if pd.isna(row.delivered_n) else int(row.delivered_n),
            "pro": r(row.promised, 4),
            "ebit": r(row.ebit, 1), "ebitda": r(row.ebitda, 1),
            "evx": r(row.evx, 6), "evxb": row.evx_basis,
            "ev": r(row.ev, 3), "evic": r(row.evic, 3), "mc": r(row.mcap, 3),
            "rev": r(row.revenue, 1),
            "w0": r(row.w_cap, 10),
            "hi": bool(row.high_impact), "ex": bool(row.excluded),
            "exa": None if pd.isna(row.excl_articles) else row.excl_articles,
            "meas": bool(row.measurable), "tier": row.tier,
            "dq": None if pd.isna(row.model_dq) else int(row.model_dq),
            "wdef": r(float(w[tk]), 10), "vardef": r(var_arr[k], 8),
            "earflag": ("loss" if (pd.notna(row.ebit) and row.ebit <= 0)
                        else ("none" if pd.isna(row.ebit)
                              else ("thin" if np.isfinite(chain["ear_pct"][k])
                                    and chain["ear_pct"][k] > 100 else "ok"))),
        })

    out = {
        "meta": {
            "generated_at": GENERATED_AT.isoformat(),
            "seed": SEED,
            "script": "src/penalty_model.py",
            "what_this_is": (
                "Set a carbon penalty per GICS sector and this returns the investment advice "
                "for a $1bn fund under that assumption."),
            "not_a_forecast": (
                "This is an EXPOSURE model, not a forecast. There is no pass-through "
                "elasticity, no demand response, no free allocation, no abatement capital "
                "spending and no competitor reaction. It answers one question only: if this "
                "penalty were levied tomorrow on the tonnes we can see, whose earnings and "
                "whose enterprise value would it land on."),
            "units_note": (
                "NGFS publishes carbon prices in US$2010 per tonne and SEC operating income is "
                "nominal dollars of the filing year. They are different units. The price "
                "control is in US$2010 and the deflator is its own visible parameter, so "
                "nothing is scaled behind the user's back. Set the deflator to 1.0 to price in "
                "raw NGFS units and accept the mismatch knowingly."),
            "aum_usd": AUM_USD,
            "n_listings": 503, "n_primary": 500,
            "n_with_scope1": int(d.measurable.sum()),
            "n_without_scope1": int((~d.measurable).sum()),
            "n_mandatory_basis": int((d.s1_prov == "mandatory").sum()),
            "n_voluntary_basis": int((d.s1_prov == "voluntary").sum()),
            "n_modelled_basis": int((d.s1_prov == "modelled").sum()),
            "n_mandatory_tonnage_anywhere": 139,
            "coverage_conflict": (
                f"The score lane tiers 273 listings as unmeasurable; the master table carries a "
                f"Scope 1 for {int(((d.tier == 'unmeasurable') & d.measurable).sum())} of them "
                f"because it added WBA self-reports the score lane never saw. Both counts are "
                f"in this file. 139 listings carry a MANDATORY measured tonnage somewhere; only "
                f"{int((d.s1_prov == 'mandatory').sum())} of them survive the precedence into "
                f"the headline Scope 1, because a self-report that clears the EPA floor wins."),
            "provenance_class": "modelled",
            "dq": 5,
        },
        "sectors": SECTORS,
    }

    out["chain"] = {
        "steps": [
            {"n": 1, "name": "price",
             "formula": "price_applied[sector] = price_usd2010[sector] * deflator",
             "settable": "price_usd2010 (11 sliders, one per GICS sector), deflator"},
            {"n": 2, "name": "cost",
             "formula": ("cost_musd = price_applied[sector] * ( s1_eff * coverage.scope1 * f1 "
                         "+ s2_eff * coverage.scope2 * f2 + s3_eff * coverage.scope3 * f3 ) "
                         "/ 1e6"),
             "settable": "coverage.scope1, coverage.scope2, coverage.scope3"},
            {"n": 3, "name": "abatement",
             "formula": ("f = clip( (1 + dlv/100) ^ max(horizon - s1y, 0), abate_floor, "
                         "abate_ceiling ); f = 1 where dlv is null. f1 = f if "
                         "abate_scopes.scope1 else 1, and the same for f2 and f3"),
             "settable": "horizon, abate_scopes, abate_floor, abate_ceiling",
             "note": ("dlv is the OBSERVED annual rate from say_do_gap.parquet, an OLS on "
                      "measured tonnage, never the promised rate. Applied to Scope 1 only by "
                      "default: the fit is a Scope 1 fit, and extending it to Scope 2 would "
                      "credit a company for moving a boiler onto the grid.")},
            {"n": 4, "name": "dEBIT",
             "formula": "d_ebit_musd = cost_musd * (1 - passthrough[sector])",
             "settable": "passthrough (11 sliders)"},
            {"n": 5, "name": "dEV",
             "formula": "d_ev_musd = d_ebit_musd * evx",
             "note": "evx is the company's own EV/EBITDA multiple, floored at 4x and capped at 40x in the master table"},
            {"n": 6, "name": "value at risk",
             "formula": "var_pct = 100 * d_ev_musd / evic   (or / ev, switchable)",
             "settable": "var_denominator"},
            {"n": 7, "name": "advice",
             "formula": "see advice_algorithm",
             "settable": "treatment, tilt_strength or tilt_budget"},
        ],
        "browser_note": (
            "Every step above is arithmetic on the fields in companies[]. Nothing needs the "
            "server. s1_eff, s2_eff and s3_eff come from the treatment: see missing_treatments."),
    }

    out["price"] = {
        "source": {
            "dataset": "NGFS Phase 5 (November 2024), IIASA NGFS Scenario Explorer",
            "variable": "Price|Carbon", "unit": "US$2010/t CO2",
            "model": NGFS_MODEL, "region": NGFS_REGION,
            "scenario": NGFS_SCENARIO, "year": NGFS_YEAR,
            "damage_basis_excluded": True, "downscaled": False,
            "file": "data/interim/ngfs_scenarios.parquet",
        },
        "default_usd2010_per_t": price_default,
        "default_per_sector": {s: price_default for s in SECTORS},
        "sector_dimension_note": (
            "NGFS publishes one economy-wide price per region. It has no sector dimension, so "
            "every sector starts at the same number and any difference between them is the "
            "user's assumption, not NGFS's. That is the whole point of the control."),
        "deflator": {
            "default": DEFLATOR_DEFAULT,
            "what": "BEA GDP implicit price deflator, 2010 to 2026",
            "note": "A hard constant, not a fetched series. Set it to 1.0 to work in raw NGFS units.",
        },
        "us_vs_world": {
            "why_us": ("These are US tonnes from US filings, so the US path is the right one. "
                       "The World path of the same scenario and model runs "
                       f"{world[NGFS_MODEL].get(2025)} in 2025 to {world[NGFS_MODEL].get(2050)} "
                       "by 2050, a different curve for a different set of marginal abaters."),
            "world_path_same_scenario": world[NGFS_MODEL],
        },
        "model_spread_note": (
            "At Net Zero 2050, 2030, United States, REMIND says 283.70 and GCAM says 98.60. "
            "2.9x apart in the same file for the same question. The model is a preset, never "
            "an average: a mean of the two is a number no model produced. "
            "src/build_master.py's stored defaults use GCAM's 98.60 and this lane uses "
            "REMIND's 283.70; the master table's price_sector_usd_per_t column is therefore "
            "2.9x lower than this page's default and that is a deliberate, stated divergence."),
        "paths": {scen: {m: {str(y): v for y, v in path.items()} for m, path in models.items()}
                  for scen, models in paths.items()},
        "presets": [
            {"key": scen, "label": scen,
             "usd2010_2030": paths[scen].get(NGFS_MODEL, {}).get(2030),
             "usd2010_2050": paths[scen].get(NGFS_MODEL, {}).get(2050)}
            for scen in sorted(paths)],
    }

    out["coverage"] = {
        "default": COVERAGE_DEFAULT,
        "scope1_note": ("An NGFS net-zero price is economy-wide, not the EU ETS, so Scope 1 "
                        "starts at 100%."),
        "scope2_note": (
            "80%, and that is not a guess. A carbon price is paid at the power station and "
            "reaches the buyer only through the electricity tariff, so the right coverage for "
            "Scope 2 is the electricity pass-through rate, which is the 80%+ Fabra and Reguant "
            "(2014) measure. Setting Scope 2 coverage AND the Utilities pass-through both to "
            "100% charges the same tonne twice inside one portfolio."),
        "scope3_note": (
            "ZERO by default. No carbon price in the world taxes a company for its customers' "
            "emissions. And one company's Scope 3 is another company's Scope 1, which the GHG "
            "Protocol Corporate Value Chain (Scope 3) Standard states explicitly, so summing "
            "Scope 3 across a 500-company index prices the same molecules several times. The "
            "slider exists; the default is off and the reason is on the page."),
        "scope_coverage_counts": {
            "scope1": int(d.s1.notna().sum()), "scope2": int(d.s2.notna().sum()),
            "scope3": int(d.s3.notna().sum())},
    }

    pt_block = {}
    for s in SECTORS:
        if s in PASSTHROUGH_SOURCE:
            v, src = PASSTHROUGH_SOURCE[s]
            pt_block[s] = {"value": v, "grounded": True, "source": src}
        else:
            pt_block[s] = {"value": PASSTHROUGH_FLAT, "grounded": False,
                           "source": ("No per-sector estimate we are willing to defend. This is "
                                      "the flat assumption applied equally to all nine "
                                      "ungrounded sectors. It is a slider, not a finding.")}
    out["passthrough"] = {
        "default": pt_block,
        "flat_value": PASSTHROUGH_FLAT,
        "honesty": (
            "Two of eleven numbers are measured and cited. The other nine are one flat number "
            "applied equally, because we could not find a per-sector estimate we would defend "
            "and a made-up sector table is worse than an honest flat one."),
        "citations": [
            {"sector": "Utilities", "value": 0.80,
             "cite": "Fabra, N. and Reguant, M. (2014). Pass-Through of Emissions Costs in "
                     "Electricity Markets. American Economic Review 104(9), 2872-2899.",
             "url": "https://www.aeaweb.org/articles?id=10.1257/aer.104.9.2872",
             "finding": "Average pass-through of emissions costs into wholesale electricity "
                        "prices is over 80 percent.",
             "caveat": "Measured on the Spanish wholesale market, not on US regulated "
                       "utilities, where tariff cost recovery would if anything be higher."},
            {"sector": "Materials", "value": 0.70,
             "cite": "Ganapati, S., Shapiro, J.S. and Walker, R. (2020). Energy Cost "
                     "Pass-Through in US Manufacturing: Estimates and Implications for Carbon "
                     "Taxes. American Economic Journal: Applied Economics 12(2), 303-342.",
             "url": "https://www.aeaweb.org/articles?id=10.1257/app.20180474",
             "finding": "About 70 percent of energy-price-driven input cost changes reach "
                        "consumers in the short to medium run.",
             "caveat": "Estimated on energy-intensive US manufacturing industries. Materials "
                       "is the GICS sector closest to the ones they study; we do not extend it "
                       "to Industrials, which is far more heterogeneous."},
        ],
        "presets": {
            "default_two_grounded": {s: pt_block[s]["value"] for s in SECTORS},
            "flat_0": dict.fromkeys(SECTORS, 0.0),
            "flat_50": dict.fromkeys(SECTORS, 0.50),
            "flat_100": dict.fromkeys(SECTORS, 1.00),
            "repo_sector_table": {s: PASSTHROUGH_REPO[s] for s in SECTORS},
        },
        "preset_notes": {
            "flat_0": "Nobody passes anything on. The strict exposure reading and the upper bound on dEBIT.",
            "flat_100": "Everybody passes everything on. dEBIT is zero everywhere and the advice is flat. A control, not a scenario.",
            "repo_sector_table": ("The sector table src/build_master.py stores in "
                                  "master_company.parquet's passthrough_pct column. Carried "
                                  "here so that column stays explainable. It has NO empirical "
                                  "source and build_master.py says so in its own comment."),
        },
    }

    n_clip_lo = int((abatement_factor(d, par["horizon"]) <= ABATE_FLOOR + 1e-12).sum())
    n_clip_hi = int((abatement_factor(d, par["horizon"]) >= ABATE_CEILING - 1e-12).sum())
    n_clip_lo_50 = int((abatement_factor(d, 2050) <= ABATE_FLOOR + 1e-12).sum())
    out["abatement"] = {
        "source": "say_do_gap.parquet delivered_pct_yr, carried in the master table",
        "what": ("The company's OBSERVED annual change in measured tonnage, an OLS on the "
                 "longest clean window of EPA GHGRP data. Negative is falling. This is never "
                 "the promised rate, which is the entire point of having measured delivery."),
        "n_with_observed_rate": int(d.delivered.notna().sum()),
        "n_with_observed_rate_and_tonnage": int((d.delivered.notna() & d.measurable).sum()),
        "n_without": int(d.delivered.isna().sum()),
        "no_rate_policy": ("factor 1.0, no credit. A cut we did not watch is a cut that did "
                           "not happen, for this model's purposes."),
        "n_with_promised_rate": int(d.promised.notna().sum()),
        "promised_never_used": True,
        "horizon_default": HORIZON_DEFAULT,
        "horizon_note": ("The horizon defaults to the price year. Move one and you should move "
                         "the other: pricing 2030 tonnes at a 2050 price is a year mismatch, "
                         "not a scenario."),
        "scopes_default": ABATE_SCOPES_DEFAULT,
        "clip": {"floor": ABATE_FLOOR, "ceiling": ABATE_CEILING,
                 "why": ("DuPont's fitted trend is -38.2%/yr. Compounded to 2050 that is a "
                         "99.99% cut, which is an extrapolation falling off a cliff, not a "
                         "forecast. The clip binds and the binds are counted."),
                 "n_at_floor_default_horizon": n_clip_lo,
                 "n_at_ceiling_default_horizon": n_clip_hi,
                 "n_at_floor_2050_horizon": n_clip_lo_50},
    }

    out["missing_treatments"] = {
        "default": TREATMENT_DEFAULT,
        "why_this_matters": (
            f"{int((~d.measurable).sum())} of 500 primary listings carry no Scope 1 tonnage "
            f"from any source. They are {float(w0[~d.measurable].sum()):.1%} of index market "
            f"cap. How you treat them is not a detail: it is the single largest driver of the "
            f"allocation on this page, larger than the price."),
        "ghgrp_threshold_t": GHGRP_THRESHOLD_T,
        "min_sector_measurable": MIN_SECTOR_MEASURABLE,
        "sector_medians_t_per_musd_evic": {
            "scope1": {s: r(imp["s1_medians"][s], 4) for s in SECTORS},
            "scope2": {s: r(imp["s2_medians"][s], 4) for s in SECTORS},
            "n_reporting_scope1": {s: imp["n1"][s] for s in SECTORS},
            "n_reporting_scope2": {s: imp["n2"][s] for s in SECTORS},
            "thin_sectors_scope1": imp["thin1"],
            "thin_sectors_scope2": imp["thin2"],
        },
        "options": [
            {"key": "sector_median", "label": "Sector median intensity",
             "rule": ("s1_eff = s1i = the sector's median tonnes per $m of EVIC among its "
                      "reporters, times this company's own EVIC. Same for Scope 2 with s2i. "
                      "Sectors with fewer than 5 reporters fall back to the threshold bound; "
                      f"on this data that is {len(imp['thin1'])} sectors for Scope 1."),
             "in_the_optimisation": ("The company carries a real, positive value at risk and "
                                     "competes for weight on it like everyone else."),
             "bias": ("Biased HIGH, and we say so. A company files a GHGRP tonnage only if a "
                      "US facility crosses 25,000 tCO2e, so the reporters are the heavy end of "
                      "their own sector and their median overstates a typical non-discloser. "
                      "It is the default because if you must be wrong, be wrong towards "
                      "charging for carbon you cannot see.")},
            {"key": "threshold_bound", "label": "40 CFR Part 98 threshold",
             "rule": f"s1_eff = {GHGRP_THRESHOLD_T:,.0f} tCO2e for every non-filer, Scope 2 = 0.",
             "in_the_optimisation": ("A small but non-zero value at risk, so it is still "
                                     "ranked, just near the clean end."),
             "bias": ("The one number the law lets us infer, and read carefully it is a "
                      "statement about a FACILITY, not a company: a firm with forty sites just "
                      "under the line clears it on every one and still emits. A floor, not a "
                      "bound on the company.")},
            {"key": "neutral_rank", "label": "Abstain",
             "rule": "No tonnage is invented. Cost, dEBIT and dEV are null, not zero.",
             "in_the_optimisation": ("The company takes the MEDIAN tilt score of the companies "
                                     "we can judge (0.5), so the tilt neither rewards nor "
                                     "punishes it for being unmeasurable. It keeps roughly its "
                                     "cap weight inside its Article 3 bucket."),
             "bias": "The honest abstention. It refuses to guess and refuses to reward silence."},
            {"key": "zerofill", "label": "Zero (what buying silence looks like)",
             "rule": "s1_eff = s2_eff = s3_eff = 0.",
             "in_the_optimisation": ("Value at risk of exactly zero, which makes a company that "
                                     "discloses nothing the single SAFEST holding in the index "
                                     "and hands it the largest overweight the caps allow."),
             "bias": ("Wrong, and shipped only so the UI can show what it does. This is the "
                      "default behaviour of most naive carbon screens.")},
        ],
        "measured_effect": {
            t: {k: r(v, 6) for k, v in treat_out[t].items() if k != "w"} for t in TREATMENTS},
    }

    thr = {}
    for rid in ["pab_baseline_reduction", "ctb_baseline_reduction",
                "decarbonisation_trajectory_equity"]:
        thr[rid] = rules[rid]["parameters"]
    out["constraints"] = {
        "regulation": {k: doc["regulation"][k] for k in
                       ["celex", "title", "eli", "source_url", "retrieved_at", "sha256",
                        "attribution"]},
        "source_file": "data/interim/pab_rules.json",
        "reused_from": ("src/portfolio.py. The exclusion list, the NACE bucket and the "
                        "position caps are read from the master table and the tilt calls "
                        "portfolio.py's own bucket_tilt and apply_caps. The rulebook has one "
                        "implementation in this repo and this is not it."),
        "article_12_excluded": int(d.excluded.sum()),
        "article_12_excluded_cap_share": r(float(w0[d.excluded].sum()), 6),
        "article_3_high_impact_universe_weight": r(buckets[True], 6),
        "article_3_rule": ("The high-climate-impact bucket (NACE A to H and L) is pinned to the "
                           "universe's weight, so the tilt moves money inside a bucket and "
                           "never out of it."),
        "max_abs_weight": MAX_ABS_WEIGHT,
        "max_rel_weight": MAX_REL_WEIGHT,
        "thresholds": thr,
        "article_11_note": ("The Article 12 exclusions alone already put the book far below the "
                            "Article 11 line before one weight is tilted, which src/portfolio.py "
                            "measures. Everything the value-at-risk tilt adds is a risk budget "
                            "the manager chooses, not a constraint the regulation imposes."),
    }

    out["advice_algorithm"] = {
        "aum_usd": AUM_USD,
        "steps": [
            "w0 = market cap / sum(market cap) over the 500 primary listings",
            "keep = not ex  (Article 12)",
            "buckets = {true: sum(w0 where hi), false: 1 - that}",
            "score = percentile rank of var_pct across all 500; under treatment "
            "neutral_rank a null var_pct scores 0.5, otherwise it takes the median rank",
            "for each bucket b: raw = w0 * exp(-lambda * score) over keep & hi==b; "
            "normalise; apply_caps(min(max_abs/target, max_rel * w0_share)); scale to the "
            "bucket's universe weight",
            "w = concat of the buckets, renormalised to 1",
            "allocation_usd = w * 1e9",
        ],
        "apply_caps": ("iterative water filling: cap the offenders at "
                       "min(max_abs_weight/bucket_target, max_rel_weight * base share), push "
                       "the spill onto everyone still under the cap, repeat until nothing is "
                       "over. src/portfolio.py apply_caps, 200 iterations maximum."),
        "lambda_default": r(adv["lam"], 6),
        "lambda_how": (f"bisected so the book adds {TILT_ACTIVE_BUDGET:.0%} of active share on "
                       f"top of the screen-only portfolio, the same budget src/portfolio.py "
                       f"gives its transition_leader book, so the two are comparable."),
        "lambda_range_for_ui": [0.0, 8.0],
        "note": ("The browser can either use lambda_default, expose lambda directly as a "
                 "conviction slider, or re-bisect to a chosen active-share budget. All three "
                 "are the same knob."),
    }

    out["defaults"] = {
        "price_usd2010": {s: price_default for s in SECTORS},
        "deflator": DEFLATOR_DEFAULT,
        "coverage": COVERAGE_DEFAULT,
        "passthrough": {s: pt_block[s]["value"] for s in SECTORS},
        "horizon": HORIZON_DEFAULT,
        "abate_scopes": ABATE_SCOPES_DEFAULT,
        "abate_floor": ABATE_FLOOR, "abate_ceiling": ABATE_CEILING,
        "treatment": TREATMENT_DEFAULT,
        "var_denominator": VAR_DENOMINATOR_DEFAULT,
        "tilt_budget": TILT_ACTIVE_BUDGET,
        "tilt_lambda": r(adv["lam"], 6),
    }

    out["reference"] = {
        "purpose": ("Computed in Python at the defaults in this file. The browser should "
                    "reproduce every number here before it is trusted with a slider."),
        "index_priced_mt": r(float(np.nansum(chain["priced_t"])) / 1e6, 2),
        "index_cost_musd": r(tot_cost, 1),
        "index_d_ebit_musd": r(tot_debit, 1),
        "index_d_ev_musd": r(tot_dev, 1),
        "index_evic_musd": r(float(d.evic.sum()), 1),
        "index_d_ev_pct_of_evic": r(100 * tot_dev / float(d.evic.sum()), 4),
        "n_held": int((w > 1e-12).sum()),
        "active_share": r(float(0.5 * (w - w0).abs().sum()), 6),
        "effective_n": r(1.0 / float((w ** 2).sum()), 2),
        "portfolio_var_pct": r(port_var, 5),
        "index_var_pct": r(idx_var, 5),
        "portfolio_var_usd_of_1bn": r(port_var * AUM_USD / 100, 0),
        "index_var_usd_of_1bn": r(idx_var * AUM_USD / 100, 0),
        "var_cut_vs_index": r(1 - port_var / idx_var, 5),
        "position_cap_note": (
            "Read the biggest dollar moves with the position cap in mind. Four names sit above "
            "the 5% UCITS single-issuer bar on cap weight (AAPL 6.95%, GOOGL 5.94%, MSFT 5.28%, "
            "NVDA 7.54%), so part of every large cut and every large addition is the cap "
            "redistributing mega-cap weight, not the carbon penalty. NVDA and AAPL are capped "
            "to exactly 5.00% and AVGO is pushed UP to exactly 5.00% by the spill. "
            "src/portfolio.py ships a capped_index_only book that measures this on its own."),
        "names_above_cap_weight": sorted(d.index[d.w_cap > MAX_ABS_WEIGHT].tolist()),
        "top_additions": [{"t": t, "usd_m": r(v * AUM_USD / 1e6, 3)}
                          for t, v in (w - w0).sort_values(ascending=False).head(15).items()],
        "top_reductions": [{"t": t, "usd_m": r(v * AUM_USD / 1e6, 3)}
                           for t, v in (w - w0).sort_values().head(15).items()],
        "largest_d_ev": [{"t": t, "d_ev_musd": r(chain["dev"][d.index.get_loc(t)], 0)}
                         for t in pd.Series(chain["dev"], index=d.index)
                         .sort_values(ascending=False).head(15).index],
        "unit_test": [
            {"t": t,
             "cost_musd": r(chain["cost"][d.index.get_loc(t)], 3),
             "d_ebit_musd": r(chain["debit"][d.index.get_loc(t)], 3),
             "d_ev_musd": r(chain["dev"][d.index.get_loc(t)], 3),
             "var_pct": r(chain["var_pct"][d.index.get_loc(t)], 6),
             "w_default": r(float(w[t]), 10)}
            for t in ["NUE", "XOM", "DUK", "AAPL", "JPM", "VST"] if t in d.index],
        "unit_test_note": ("Six companies at the defaults, computed here. A browser "
                           "implementation that reproduces these six reproduces all 500."),
        "browser_tolerance": (
            "The coefficients in companies[] are rounded for the wire. A reference "
            "implementation reading only this file reproduces vardef to 3.6e-6 relative and "
            "wdef to 1.9e-6 of a weight, which is $1.85 on a $1bn book. The residual is "
            "tie-breaking: under "
            "the sector-median treatment an imputed company's value at risk collapses to "
            "sector median x price x (1 - passthrough) x its own multiple, the EVIC cancels, "
            "and the 31 Financials carrying the sector-median EV/EBITDA are exactly tied. "
            "Rank the normalised value at risk rounded to 9 decimals, as the reference "
            "implementation does, and the ties stay ties."),
        "price_invariance": {
            "claim": ("A uniform price across all 11 sectors is a scalar on every company's "
                      "cost, so it cannot reorder the index, so it cannot move one dollar of "
                      "the allocation. Verified, not asserted."),
            "test": "every sector repriced from the default to 1000 US$2010/t",
            "d_ev_ratio": r(float(ratio), 6),
            "max_abs_weight_change": r(float(wdiff), 12),
        },
    }

    out["ebit_guard"] = {
        "rule": ("d_ebit_pct_of_ebit is computed only where operating income is positive. A "
                 "ratio against a negative denominator is not a small number, it is a wrong "
                 "one."),
        "n_operating_loss_primary": n_loss,
        "n_operating_loss_with_tonnage": n_loss_meas,
        "operating_loss_names": sorted(d.index[(d.ebit <= 0) & d.measurable].tolist()),
        "n_over_100pct_of_ebit_at_default": len(over100),
        "over_100pct_names": sorted(over100),
        "display_rule": ("Flag these, never publish the bare percentage. A dEBIT of 6,000% of "
                         "operating income is a statement about a thin margin, not about "
                         "carbon. The earnings lane caps its display at 200% for the same "
                         "reason."),
        "earflag_values": {"ok": "positive operating income, dEBIT under 100% of it",
                           "thin": "positive operating income, dEBIT over 100% of it",
                           "loss": "operating income zero or negative, ratio is null",
                           "none": "no operating income in the filings (HONA)"},
    }

    out["sensitivity"] = {
        "inputs_sampled": {
            "treatment": "the four missing-data schemes, uniformly",
            "price_level": "20 to 900 US$2010/t, log-uniform, the span of NGFS US 2030 prices",
            "price_dispersion": "per-sector lognormal multiplier, sigma uniform on 0 to 0.8",
            "sectors_exempt": ("each sector's price set to zero independently with probability "
                               "uniform on 0 to 0.4, because real carbon pricing exempts "
                               "sectors far more often than it reprices them by a factor of two"),
            "passthrough_level": "0 to 0.95, flat across sectors",
            "passthrough_dispersion": "per-sector normal deviation, sigma uniform on 0 to 0.35",
            "deflator": "1.0 to 1.6",
            "coverage_scope1": "0.5 to 1.0", "coverage_scope2": "0 to 1",
            "coverage_scope3": "0 to 0.5",
            "horizon": "2026 to 2050",
            "var_denominator": "EVIC or vendor enterprise value",
            "tilt_strength": "lambda uniform on 0 to 8",
        },
        "estimator": ("Pearson correlation ratio eta^2 with the standard bias correction, "
                      "imported from src/score.py's omega2 so the two lanes report the same "
                      "statistic. Continuous inputs binned into 8 quantile bins."),
        "draws": SENS_DRAWS,
        "outputs": {
            "allocation": "the 500 portfolio weights, averaged over companies",
            "var_rank": "the 500 value-at-risk percentile ranks, averaged over companies",
            "turnover": "0.5 * sum |w - w_default|, one number per draw",
        },
        "shares": {k: {kk: r(vv, 4) for kk, vv in sens[k].items()} for k in names},
        "ranked_on_allocation_at_fixed_tilt": order,
        "model_inputs": model_inputs,
        "tilt_strength_note": ("tilt_strength is how hard the manager tilts, not an input to "
                               "the carbon model. It is reported alongside so nobody has to "
                               "wonder, and excluded from the ranking of model inputs."),
        "sum_first_order_allocation": r(sum(sens[k]["allocation"] for k in names), 4),
        "finding": (
            f"{order[0]} is the largest single driver of the advice at "
            f"{sens[order[0]]['allocation_fixed_lambda']:.3f} of allocation variance at a fixed "
            f"tilt strength, against {sens['price_level']['allocation_fixed_lambda']:.3f} for "
            f"the price level. The price level's "
            "share is zero by construction and not by luck: a uniform price is a scalar on "
            "every cost, so it changes how much money is at risk and nothing about where the "
            "money goes. In measured order the advice moves with the missing-data treatment, "
            "then with how many sectors are EXEMPTED outright, then with whether Scope 3 is "
            "switched on. Repricing a sector smoothly does almost nothing, because emissions "
            "intensity spans four orders of magnitude across sectors (Utilities 349 tCO2e per "
            "$m of EVIC against Information Technology 0.14) and a 2x sector price cannot "
            "reorder that. The sector control earns its place by letting a sector go to zero, "
            "which is also how real carbon pricing works: exemptions and free allocation, not "
            "a different price per sector."),
        "matches_score_lane": ("src/score.py puts missing_data at 0.201 of first-order rank "
                              "variance, the largest single share there too. Two different "
                              "models, same answer: the biggest number on the page is the one "
                              "nobody measured."),
    }

    out["caveats"] = [
        "This is an exposure model, not a forecast. No pass-through elasticity, no demand "
        "response, no free allocation, no abatement capital spending, no competitor reaction.",
        "NGFS prices are US$2010 and SEC operating income is nominal. The deflator is a visible "
        "parameter, not a silent scaling.",
        f"{int((~d.measurable).sum())} of 500 companies carry no Scope 1 tonnage. Their "
        "treatment is a switch on this page because it is the largest single driver of the "
        "answer, and none of the four options is neutral.",
        "Scope 1 mixes boundaries. Where a self-report clears the EPA-measured floor it wins, "
        "so some companies carry a global self-reported figure and others a US-only mandatory "
        "one. The two are not the same tonne and the basis is on every row.",
        "Scope 3 is off by default and should stay off for any portfolio total: one company's "
        "Scope 3 is another's Scope 1.",
        "Nine of eleven pass-through rates have no empirical source and are one flat number.",
        "The EV/EBITDA multiple is vendor data, floored at 4x and capped at 40x, and 34 "
        "companies carry a sector median instead of their own. It never feeds the headline "
        "score; here it only capitalises the earnings hit.",
        "Emissions are US-biased. The mandatory spine is EPA GHGRP, which sees no foreign "
        "facility. On the 25 companies with material foreign assets we see about 39% of their "
        "implied global Scope 1.",
        "The advice is a tilt inside a rulebook, not an optimisation of returns. There is no "
        "expected return, no covariance matrix and no alpha claim anywhere in it.",
    ]

    out["trace"] = {k: (r(v, 6) if isinstance(v, float) else v) for k, v in trace.items()}
    out["companies"] = companies

    SITE.mkdir(parents=True, exist_ok=True)
    path = SITE / "penalty.json"
    path.write_text(json.dumps(jsonable(out), separators=(",", ":")))
    kb = path.stat().st_size / 1024

    hr("written")
    print(f"  {path}  {kb:,.1f} KB, {len(companies)} companies, "
          f"{len(json.dumps(jsonable(out)))/1024:,.0f} KB unminified")
    top = sorted(((len(json.dumps(jsonable(v))), k) for k, v in out.items()), reverse=True)
    for n_, k in top[:6]:
        print(f"    {k:22s} {n_/1024:8,.1f} KB")
    assert kb < 400, f"penalty.json is {kb:.0f} KB, over the 400 KB budget"
    print(f"  seed {SEED}, generated {GENERATED_AT.isoformat()}")


if __name__ == "__main__":
    main()
