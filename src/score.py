"""The composite score: four pillars from mandatory filings, published as a rank interval.

Method is the OECD/JRC Handbook on Constructing Composite Indicators (Nardo et al. 2008),
Step 7: one Monte Carlo over every modelling choice at once, reported as a median rank with
a 5th-95th percentile band. Sensitivity comes free from the same sample as the Pearson
correlation ratio. The effective-weight audit is Paruolo, Saisana & Saltelli (2013).
"""

import json
import math
import time

import numpy as np
import pandas as pd
from scipy import stats

SEED = 20260912
L_DRAWS = 10_000
INTERIM = "data/interim"
SITE = "site/data"

# Higher is better for every indicator after orientation. Pillar membership is fixed here
# because the leave-one-out arm of the Monte Carlo drops whole pillars, not indicators.
INDICATORS = [
    ("intensity", 0, "Scope 1 tonnes per $m revenue, GHGRP measured", "mandatory"),
    ("trend", 0, "annual %/yr change in measured Scope 1, log-linear fit", "mandatory"),
    ("saydo", 1, "delivered minus promised %/yr, positive is missing the promise", "mandatory"),
    ("ear", 2, "carbon cost as % of operating income at the 2030 Net Zero 2050 US price", "mandatory"),
    ("penalty", 3, "environmental enforcement penalties per $m revenue, 2000-2026", "mandatory"),
]
PILLARS = [
    ("physical", "Physical intensity and trajectory"),
    ("credibility", "Credibility: the say-do gap"),
    ("exposure", "Carbon price exposure: earnings at risk"),
    ("conduct", "Compliance record: environmental penalties"),
]
N_IND = len(INDICATORS)
N_PILLAR = len(PILLARS)

NORMS = ["minmax", "zscore", "pct_global", "pct_sector"]
WINSOR = [False, True]
MISSING = ["available_case", "sector_median", "nmar_p25"]
AGGREG = ["linear", "geometric", "copeland"]
SECTOR_REL = [False, True]
# f3: 0 = keep all four pillars, 1..4 = drop that pillar
INCLUSION = list(range(N_PILLAR + 1))


def banner(s):
    print()
    print(s)
    print("-" * len(s))


def build_indicators():
    """One row per primary listing, five oriented indicators, mandatory provenance only."""
    uni = pd.read_parquet(f"{INTERIM}/universe.parquet")
    uni = uni[uni.is_primary_listing].copy()
    fin = pd.read_parquet(f"{INTERIM}/financials.parquet")[["ticker", "fy", "revenue"]]

    rev_latest = (
        fin[fin.revenue.notna()].sort_values("fy").groupby("ticker").tail(1)
        .set_index("ticker")[["fy", "revenue"]]
        .rename(columns={"fy": "revenue_fy", "revenue": "revenue_usd"})
    )

    # Pillar 1a, physical intensity. Mandatory GHGRP tonnage at the latest year the company
    # reported, divided by revenue of that same fiscal year where it exists.
    em = pd.read_parquet(f"{INTERIM}/emissions_by_ticker.parquet")
    ghg = em[em.scope1_ghgrp_tonnes.notna()].sort_values("year").groupby("ticker").tail(1)
    ghg = ghg[["ticker", "year", "scope1_ghgrp_tonnes", "dq_ghgrp"]].rename(
        columns={"year": "emissions_year", "scope1_ghgrp_tonnes": "scope1_tonnes"}
    )
    ghg = ghg.merge(fin.rename(columns={"fy": "emissions_year", "revenue": "revenue_matched"}),
                    on=["ticker", "emissions_year"], how="left")
    n_same_year = int(ghg.revenue_matched.notna().sum())
    ghg = ghg.merge(rev_latest, left_on="ticker", right_index=True, how="left")
    # 3 tickers last reported before the SEC XBRL window opens; fall back to latest revenue.
    ghg["revenue_for_intensity"] = ghg.revenue_matched.fillna(ghg.revenue_usd)
    ghg["intensity_dq"] = np.where(ghg.revenue_matched.notna(), 2, 4)
    ghg["intensity_t_per_musd"] = ghg.scope1_tonnes / (ghg.revenue_for_intensity / 1e6)

    # Pillar 1b, trajectory, and pillar 2, the say-do gap. Both from the say-do lane, which
    # already broke the fit window on perimeter steps so acquisitions do not read as growth.
    sd = pd.read_parquet(f"{INTERIM}/say_do_gap.parquet")
    sd = sd[["ticker", "coverage_tier", "delivered_pct_yr", "delivered_se", "delivered_n_years",
             "trend_flags", "gap_pct_yr", "promised_dq", "slide_safe", "dq",
             "promised_reduction_pct_yr", "delivered_reduction_pct_yr"]].rename(
        columns={"dq": "saydo_dq"})

    # Pillar 3, earnings at risk, at the price the US Net Zero 2050 path reaches in 2030.
    ear = pd.read_parquet(f"{INTERIM}/earnings_at_risk.parquet")
    ear = ear[(ear.scenario_key == "net_zero_2050") & (ear.year == 2030)].copy()
    ear_price = float(ear.carbon_price_usd.iloc[0])
    ear = ear[["ticker", "ear_pct", "ear_pct_oi3", "oi_method", "oi_reported", "oi_flag",
               "carbon_cost_usd", "operating_income_usd", "dq_emissions"]]
    ear["ear_used"] = ear.ear_pct
    ear["ear_basis"] = np.where(ear.ear_pct.notna(), "fy_operating_income", None)
    fallback = ear.ear_pct.isna() & ear.ear_pct_oi3.notna()
    ear.loc[fallback, "ear_used"] = ear.loc[fallback, "ear_pct_oi3"]
    ear.loc[fallback, "ear_basis"] = "3yr_mean_operating_income"
    n_ear_fallback = int(fallback.sum())

    # Pillar 4, conduct. Violation Tracker aggregates government enforcement records, so it is
    # a regulatory record and not a self-report. 35 companies were searched and have no case,
    # which is a measured zero and is filled as one.
    vio = pd.read_parquet(f"{INTERIM}/violations_summary.parquet")
    vio = vio[["ticker", "penalty_usd_environment", "case_count_environment",
               "penalty_usd_environment_recent5", "match_status"]].copy()
    measured_zero = vio.match_status == "no_records"
    vio.loc[measured_zero, "penalty_usd_environment"] = 0
    vio.loc[measured_zero, "penalty_usd_environment_recent5"] = 0
    vio.loc[measured_zero, "case_count_environment"] = 0
    n_measured_zero = int(measured_zero.sum())

    d = uni[["ticker", "company_name", "gics_sector", "gics_sub_industry", "is_primary_listing"]]
    d = d.merge(rev_latest, left_on="ticker", right_index=True, how="left")
    d = d.merge(ghg[["ticker", "emissions_year", "scope1_tonnes", "intensity_t_per_musd",
                     "intensity_dq"]], on="ticker", how="left")
    d = d.merge(sd, on="ticker", how="left")
    d = d.merge(ear, on="ticker", how="left")
    d = d.merge(vio, on="ticker", how="left")
    d = d.reset_index(drop=True)

    d["revenue_musd"] = d.revenue_usd / 1e6
    d["env_penalty_per_musd"] = d.penalty_usd_environment / d.revenue_musd
    d["env_penalty_per_musd_recent5"] = d.penalty_usd_environment_recent5 / d.revenue_musd

    # Orientation: higher is better on every column below. Heavy tails are logged first, which
    # the Handbook asks for at Step 5, or a handful of utilities own the whole variance.
    d["x_intensity"] = -np.log10(d.intensity_t_per_musd.clip(lower=1e-4))
    d["x_trend"] = -d.delivered_pct_yr
    d["x_saydo"] = -d.gap_pct_yr
    d["x_ear"] = -np.log10(1.0 + d.ear_used.clip(lower=0))
    d["x_penalty"] = -np.log10(1.0 + d.env_penalty_per_musd)
    d["x_penalty_recent5"] = -np.log10(1.0 + d.env_penalty_per_musd_recent5)

    meta = dict(n_same_year_revenue=n_same_year, ear_price=ear_price,
                n_ear_fallback=n_ear_fallback, n_penalty_measured_zero=n_measured_zero)
    return d, meta


def guard_provenance(frame, cols):
    """Nothing tagged vendor may reach the indicator matrix. Enforced, not remembered."""
    vendor_cols = set()
    for f in ["vendor_scores", "esg_vendor_consensus"]:
        try:
            vendor_cols |= set(pd.read_parquet(f"{INTERIM}/{f}.parquet").columns)
        except FileNotFoundError:
            pass
    vendor_cols -= {"ticker", "dq", "provenance_class"}
    bad = [c for c in cols if c in vendor_cols]
    if bad:
        raise RuntimeError(f"vendor columns reached the score inputs: {bad}")
    for name, _, _, prov in INDICATORS:
        if prov != "mandatory":
            raise RuntimeError(f"indicator {name} is {prov}, the headline score is mandatory only")
    return sorted(vendor_cols)


def normalise(x, kind, sector_codes, n_sectors):
    """x is (N,) oriented so higher is better, with NaN for missing. Returns (N,) normalised."""
    out = np.full(x.shape, np.nan)
    obs = np.isfinite(x)
    if obs.sum() == 0:
        return out
    if kind == "minmax":
        lo, hi = np.nanmin(x), np.nanmax(x)
        out[obs] = 0.5 if hi <= lo else (x[obs] - lo) / (hi - lo)
    elif kind == "zscore":
        mu, sd = np.nanmean(x), np.nanstd(x)
        out[obs] = 0.0 if sd == 0 else (x[obs] - mu) / sd
    elif kind == "pct_global":
        out[obs] = stats.rankdata(x[obs], method="average") / obs.sum()
    elif kind == "pct_sector":
        for s in range(n_sectors):
            m = obs & (sector_codes == s)
            if m.sum() == 0:
                continue
            if m.sum() == 1:
                out[m] = 0.5
            else:
                out[m] = stats.rankdata(x[m], method="average") / m.sum()
    else:
        raise ValueError(kind)
    return out


def fill_missing(z, scheme, sector_codes, n_sectors):
    """Imputation happens after normalisation so the imputed mass cannot move the scale."""
    if scheme == "available_case":
        return z.copy(), np.isfinite(z)
    q = 0.5 if scheme == "sector_median" else 0.25
    out = z.copy()
    obs = np.isfinite(z)
    if obs.sum() == 0:
        return out, obs
    global_fill = float(np.nanquantile(z[obs], q))
    n_global = 0
    for s in range(n_sectors):
        in_s = sector_codes == s
        have = in_s & obs
        miss = in_s & ~obs
        if miss.sum() == 0:
            continue
        if have.sum() == 0:
            out[miss] = global_fill
            n_global += int(miss.sum())
        else:
            out[miss] = float(np.quantile(z[have], q))
    return out, np.ones_like(obs, dtype=bool)


def build_scenarios(d, sector_codes, n_sectors):
    """One normalised pillar matrix per (normalisation, winsorisation, missing, sector-relative)."""
    raw = np.column_stack([d[f"x_{name}"].to_numpy(dtype=float) for name, _, _, _ in INDICATORS])
    n = raw.shape[0]
    scen = {}
    fallback_counts = {}
    for i1, norm in enumerate(NORMS):
        for i2, wins in enumerate(WINSOR):
            x = raw.copy()
            if wins:
                for j in range(N_IND):
                    col = x[:, j]
                    obs = np.isfinite(col)
                    if obs.sum() > 10:
                        lo, hi = np.quantile(col[obs], [0.01, 0.99])
                        x[obs, j] = np.clip(col[obs], lo, hi)
            z = np.column_stack([normalise(x[:, j], norm, sector_codes, n_sectors)
                                 for j in range(N_IND)])
            for i4, scheme in enumerate(MISSING):
                zf = np.empty_like(z)
                obsf = np.empty(z.shape, dtype=bool)
                for j in range(N_IND):
                    zf[:, j], obsf[:, j] = fill_missing(z[:, j], scheme, sector_codes, n_sectors)
                for i7, secrel in enumerate(SECTOR_REL):
                    zz = zf.copy()
                    if secrel:
                        for j in range(N_IND):
                            col = zz[:, j]
                            ok = np.isfinite(col)
                            for s in range(n_sectors):
                                m = ok & (sector_codes == s)
                                if m.sum() > 0:
                                    col[m] = col[m] - col[m].mean()
                            zz[:, j] = col
                    # Pillar 1 averages its two sub-indicators over whichever are observed.
                    p = np.full((n, N_PILLAR), np.nan)
                    obs_p = np.zeros((n, N_PILLAR), dtype=bool)
                    sub = zz[:, :2]
                    sub_obs = obsf[:, :2] & np.isfinite(sub)
                    cnt = sub_obs.sum(axis=1)
                    with np.errstate(invalid="ignore"):
                        p[:, 0] = np.where(cnt > 0, np.nansum(np.where(sub_obs, sub, 0), axis=1)
                                           / np.maximum(cnt, 1), np.nan)
                    obs_p[:, 0] = cnt > 0
                    for k in range(1, N_PILLAR):
                        p[:, k] = zz[:, k + 1]
                        obs_p[:, k] = obsf[:, k + 1] & np.isfinite(zz[:, k + 1])
                    p[~obs_p] = np.nan
                    key = (i1, i2, i4, i7)
                    scen[key] = dict(p=p, obs=obs_p)
    # pillar values rescaled into (0,1] once, for the geometric arm only
    for key, s in scen.items():
        p, obs = s["p"], s["obs"]
        pg = np.full_like(p, np.nan)
        for k in range(N_PILLAR):
            col = p[:, k]
            m = obs[:, k]
            if m.sum() == 0:
                continue
            lo, hi = col[m].min(), col[m].max()
            pg[m, k] = 0.01 if hi <= lo else 0.01 + 0.99 * (col[m] - lo) / (hi - lo)
        s["logpg"] = np.where(obs, np.log(np.where(obs, pg, 1.0)), 0.0)
        # Copeland needs only the ordering, so the sign tensor is fixed per scenario.
        c = np.zeros((N_PILLAR, p.shape[0], p.shape[0]), dtype=np.int8)
        for k in range(N_PILLAR):
            col = np.where(obs[:, k], p[:, k], np.nan)
            diff = col[:, None] - col[None, :]
            c[k] = np.sign(np.nan_to_num(diff, nan=0.0)).astype(np.int8)
        s["c"] = c
        s["p0"] = np.where(obs, p, 0.0)
        s["obsf"] = obs.astype(np.float64)
    return scen, raw, fallback_counts


def ranks_from_scores(scores):
    """rank 1 is best. Ties get the average rank. Unscorable rows come back as NaN."""
    out = np.full(scores.shape, np.nan)
    for b in range(scores.shape[0]):
        row = scores[b]
        ok = np.isfinite(row)
        if ok.sum() == 0:
            continue
        r = stats.rankdata(-row[ok], method="average")
        out[b, ok] = r * (scores.shape[1] / ok.sum())
    return out


def run_monte_carlo(scen, n, rng, sector_codes):
    f1 = rng.integers(0, len(NORMS), L_DRAWS)
    f2 = rng.integers(0, len(WINSOR), L_DRAWS)
    f3 = rng.integers(0, len(INCLUSION), L_DRAWS)
    f4 = rng.integers(0, len(MISSING), L_DRAWS)
    f5 = rng.integers(0, len(AGGREG), L_DRAWS)
    f7 = rng.integers(0, len(SECTOR_REL), L_DRAWS)
    w = rng.dirichlet(np.ones(N_PILLAR), L_DRAWS)

    incl = np.ones((L_DRAWS, N_PILLAR))
    drop = f3 > 0
    incl[drop, f3[drop] - 1] = 0.0
    weff = w * incl
    weff = weff / weff.sum(axis=1, keepdims=True)

    ranks = np.full((L_DRAWS, n), np.nan, dtype=np.float32)
    key_of = np.stack([f1, f2, f4, f7], axis=1)
    keys = {}
    for i in range(L_DRAWS):
        keys.setdefault(tuple(key_of[i]), []).append(i)

    t0 = time.time()
    for key, idx in keys.items():
        s = scen[key]
        idx = np.asarray(idx)
        for agg_i, agg in enumerate(AGGREG):
            sel = idx[f5[idx] == agg_i]
            if sel.size == 0:
                continue
            W = weff[sel]
            den = W @ s["obsf"].T
            if agg == "linear":
                num = W @ s["p0"].T
                sc = np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)
                ranks[sel] = ranks_from_scores(sc)
            elif agg == "geometric":
                num = W @ s["logpg"].T
                sc = np.where(den > 0, np.exp(num / np.maximum(den, 1e-12)), np.nan)
                ranks[sel] = ranks_from_scores(sc)
            else:
                # Copeland, a polynomial Condorcet-consistent surrogate for the Kemeny median
                # order, which is NP-hard and impossible at N=500 inside one night.
                cf = s["c"].astype(np.float32)
                unscorable = ~(s["obs"].any(axis=1))
                for j, b in enumerate(sel):
                    m = np.tensordot(W[j].astype(np.float32), cf, axes=(0, 0))
                    outrank = m > 1e-9
                    cop = outrank.sum(axis=1).astype(np.float32) - outrank.sum(axis=0)
                    # a company with no observed included pillar votes in no pair and is
                    # not scorable under available-case; it is left out of that draw
                    dead = unscorable | (den[j] <= 0)
                    cop[dead] = np.nan
                    ranks[b] = ranks_from_scores(cop[None, :])[0]
    print(f"  monte carlo {L_DRAWS} draws in {time.time() - t0:.1f}s")
    return ranks, dict(f1=f1, f2=f2, f3=f3, f4=f4, f5=f5, f7=f7, w=w, weff=weff)


def omega2(y, labels, n_labels):
    """Correlation ratio with the standard bias correction. y is (L,N), labels is (L,)."""
    ell, n = y.shape
    counts = np.bincount(labels, minlength=n_labels).astype(float)
    live = counts > 0
    grand = y.mean(axis=0)
    sst = ((y - grand) ** 2).sum(axis=0)
    ssb = np.zeros(n)
    for k in np.flatnonzero(live):
        m = labels == k
        mu = y[m].mean(axis=0)
        ssb += counts[k] * (mu - grand) ** 2
    kk = int(live.sum())
    dfw = ell - kk
    if dfw <= 0:
        return np.zeros(n)
    msw = np.maximum(sst - ssb, 0) / dfw
    om = (ssb - (kk - 1) * msw) / np.maximum(sst + msw, 1e-12)
    return np.clip(om, 0.0, 1.0)


def weight_bins(w, per_dim=3):
    """A coarse deterministic partition of the simplex so the weight draw is one factor."""
    edges = [np.quantile(w[:, k], np.linspace(0, 1, per_dim + 1)[1:-1]) for k in range(w.shape[1])]
    lab = np.zeros(w.shape[0], dtype=int)
    mult = 1
    for k in range(w.shape[1]):
        b = np.digitize(w[:, k], edges[k])
        lab += b * mult
        mult *= per_dim
    return lab, mult


def main_effects(y, x, n_bins):
    """Paruolo/Saisana/Saltelli main effect S_i: the correlation ratio of the composite on
    indicator i, estimated by quantile binning instead of a kernel smoother."""
    out = []
    for k in range(x.shape[1]):
        col = x[:, k]
        ok = np.isfinite(col)
        if ok.sum() < n_bins * 2:
            out.append(np.nan)
            continue
        q = np.quantile(col[ok], np.linspace(0, 1, n_bins + 1)[1:-1])
        lab = np.digitize(col[ok], q)
        yy = y[ok]
        grand = yy.mean()
        sst = ((yy - grand) ** 2).sum()
        counts = np.bincount(lab, minlength=n_bins).astype(float)
        ssb = 0.0
        for b in range(n_bins):
            m = lab == b
            if m.sum() == 0:
                continue
            ssb += counts[b] * (yy[m].mean() - grand) ** 2
        kk = int((counts > 0).sum())
        dfw = ok.sum() - kk
        msw = max(sst - ssb, 0) / max(dfw, 1)
        out.append(float(np.clip((ssb - (kk - 1) * msw) / max(sst + msw, 1e-12), 0.0, 1.0)))
    return np.array(out)


def pareto_fronts(vals):
    """Front number per row over the columns, all oriented higher-is-better. O(N^2 d)."""
    n = vals.shape[0]
    front = np.zeros(n, dtype=int)
    remaining = np.arange(n)
    f = 1
    while remaining.size:
        v = vals[remaining]
        ge = (v[:, None, :] >= v[None, :, :]).all(axis=2)
        gt = (v[:, None, :] > v[None, :, :]).any(axis=2)
        dominated_by = (ge & gt).any(axis=0)
        cur = remaining[~dominated_by]
        if cur.size == 0:
            front[remaining] = f
            break
        front[cur] = f
        remaining = remaining[dominated_by]
        f += 1
    return front


def reference_score(scen, key, weights, agg):
    s = scen[key]
    den = s["obsf"] @ weights
    if agg == "linear":
        num = s["p0"] @ weights
        return np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)
    if agg == "geometric":
        num = s["logpg"] @ weights
        return np.where(den > 0, np.exp(num / np.maximum(den, 1e-12)), np.nan)
    if agg == "copeland":
        m = np.tensordot(weights, s["c"].astype(np.float64), axes=(0, 0))
        outrank = m > 1e-9
        cop = outrank.sum(axis=1).astype(float) - outrank.sum(axis=0)
        cop[den <= 0] = np.nan
        return cop
    if agg == "borda":
        # Borda, the comparison arm the Handbook warns about: fully dependent on irrelevant
        # alternatives. Weighted sum of within-pillar rank positions.
        p, obs = s["p"], s["obs"]
        b = np.zeros(p.shape[0])
        wsum = np.zeros(p.shape[0])
        for k in range(N_PILLAR):
            m = obs[:, k]
            if m.sum() == 0:
                continue
            r = stats.rankdata(p[m, k], method="average") / m.sum()
            b[m] += weights[k] * r
            wsum[m] += weights[k]
        return np.where(wsum > 0, b / np.maximum(wsum, 1e-12), np.nan)
    raise ValueError(agg)


def to_rank(score):
    out = np.full(score.shape, np.nan)
    ok = np.isfinite(score)
    out[ok] = stats.rankdata(-score[ok], method="average")
    return out


def jsonable(o):
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if o is None or isinstance(o, str):
        return o
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if pd.isna(o):
        return None
    return o


def main():
    rng = np.random.default_rng(SEED)
    banner("inputs")
    d, meta = build_indicators()
    guard_provenance(d, list(d.columns))
    n = len(d)
    sectors = sorted(d.gics_sector.dropna().unique())
    sector_codes = d.gics_sector.map({s: i for i, s in enumerate(sectors)}).fillna(-1).to_numpy(int)
    n_sectors = len(sectors)
    print(f"  {n} primary listings, {n_sectors} GICS sectors, seed {SEED}, L = {L_DRAWS}")
    print(f"  earnings at risk priced at ${meta['ear_price']:.2f}/t, the 2030 point of the "
          f"NGFS Net Zero 2050 United States path")
    print(f"  intensity: {meta['n_same_year_revenue']} of 139 matched revenue in the same "
          f"fiscal year as the tonnage")
    print(f"  earnings at risk: {meta['n_ear_fallback']} loss-makers fell back to the "
          f"3-year mean operating income")
    print(f"  penalties: {meta['n_penalty_measured_zero']} companies searched with no case, "
          f"filled as a measured zero")

    banner("indicator coverage, out of 500")
    cov = {}
    for name, pill, desc, prov in INDICATORS:
        c = int(d[f"x_{name}"].notna().sum())
        cov[name] = c
        print(f"  {name:10s} {c:3d}  {c / n * 100:5.1f}%  pillar {PILLARS[pill][0]:12s} {desc}")
    d["coverage_tier"] = d.coverage_tier.fillna("unmeasurable")
    print("  coverage_tier:", d.coverage_tier.value_counts().to_dict())

    n_obs_pillar = pd.DataFrame({
        "physical": d.x_intensity.notna() | d.x_trend.notna(),
        "credibility": d.x_saydo.notna(),
        "exposure": d.x_ear.notna(),
        "conduct": d.x_penalty.notna(),
    })
    n_zero_pen = int((d.penalty_usd_environment.fillna(-1) == 0).sum())
    print(f"  {n_zero_pen} companies carry exactly zero environmental penalties, so the conduct "
          f"pillar cannot separate them from each other")
    print("  coverage_tier counts are over 500 primary listings; the brief's 91 'reported' "
          "becomes 88 here because GOOG, FOX and NWS are secondary listings")
    print("  pillars observed:", n_obs_pillar.sum().to_dict())
    print("  companies with all four pillars:", int(n_obs_pillar.all(axis=1).sum()))
    print("  companies with exactly one pillar:", int((n_obs_pillar.sum(axis=1) == 1).sum()))

    banner("scenarios")
    t0 = time.time()
    scen, raw, _ = build_scenarios(d, sector_codes, n_sectors)
    print(f"  {len(scen)} normalised scenarios built in {time.time() - t0:.1f}s "
          f"({len(NORMS)} normalisations x {len(WINSOR)} winsorisation x {len(MISSING)} "
          f"missing schemes x {len(SECTOR_REL)} sector-relative)")

    banner("monte carlo")
    ranks, factors = run_monte_carlo(scen, n, rng, sector_codes)
    n_ranked = np.isfinite(ranks).sum(axis=0)
    print(f"  rank samples per company: min {n_ranked.min()}, median "
          f"{int(np.median(n_ranked))}, max {n_ranked.max()}")
    print(f"  draws where a company had no observed included pillar: "
          f"{int((L_DRAWS - n_ranked).sum())} company-draws of {L_DRAWS * n}")

    med = np.nanmedian(ranks, axis=0)
    p05 = np.nanpercentile(ranks, 5, axis=0)
    p95 = np.nanpercentile(ranks, 95, axis=0)
    width = p95 - p05
    d["rank_median"] = med
    d["rank_p05"] = p05
    d["rank_p95"] = p95
    d["rank_width"] = width
    d["rank_samples"] = n_ranked

    banner("rank intervals")
    print(f"  median width of the 5th-95th percentile rank band: {np.median(width):.1f} ranks "
          f"of {n}")
    print(f"  mean width {np.mean(width):.1f}, min {np.min(width):.1f}, max {np.max(width):.1f}")
    for thr in (100, 200, 300):
        print(f"  companies whose band spans more than {thr} ranks: "
              f"{int((width > thr).sum())} of {n} ({(width > thr).mean() * 100:.1f}%)")
    for tier in ["measured", "reported", "unmeasurable"]:
        m = (d.coverage_tier == tier).to_numpy()
        if m.sum():
            print(f"  {tier:12s} n={m.sum():3d}  median band {np.median(width[m]):6.1f}  "
                  f"median rank {np.median(med[m]):6.1f}")

    tiers_code = pd.Categorical(d.coverage_tier).codes
    grand = med.mean()
    ssb = sum(((med[tiers_code == k].mean() - grand) ** 2) * (tiers_code == k).sum()
              for k in range(tiers_code.max() + 1))
    print(f"  share of the variance of the median rank explained by coverage tier alone: "
          f"{ssb / ((med - grand) ** 2).sum() * 100:.1f}%")
    unm = (d.coverage_tier == "unmeasurable").to_numpy()
    tied = unm & (d.penalty_usd_environment.fillna(-1) == 0).to_numpy()
    print(f"  {int(tied.sum())} of the {int(unm.sum())} unmeasurable companies also carry zero "
          f"environmental penalties, so nothing in the mandatory record separates them at all")

    banner("where the width comes from: bands conditional on one trigger being fixed")
    conds = {
        "all triggers live": np.ones(L_DRAWS, dtype=bool),
        "absolute lens only": factors["f7"] == 0,
        "sector-relative only": factors["f7"] == 1,
        "all four pillars kept": factors["f3"] == 0,
        "available-case only": factors["f4"] == 0,
        "sector-median only": factors["f4"] == 1,
        "NMAR-pessimistic only": factors["f4"] == 2,
        "linear only": factors["f5"] == 0,
        "copeland only": factors["f5"] == 2,
        "global percentile only": factors["f1"] == 2,
        "absolute + sector-median + all four pillars":
            (factors["f7"] == 0) & (factors["f4"] == 1) & (factors["f3"] == 0),
        "absolute + available-case + all four pillars":
            (factors["f7"] == 0) & (factors["f4"] == 0) & (factors["f3"] == 0),
    }
    cond_out = {}
    for label, mask in conds.items():
        sub = ranks[mask]
        w5 = np.nanpercentile(sub, 5, axis=0)
        w95 = np.nanpercentile(sub, 95, axis=0)
        ww = w95 - w5
        mm_meas = (d.coverage_tier == "measured").to_numpy()
        cond_out[label] = dict(n_draws=int(mask.sum()), median_width=float(np.median(ww)),
                               median_width_measured=float(np.median(ww[mm_meas])))
        print(f"  {label:24s} n={int(mask.sum()):5d}  median band {np.median(ww):6.1f}  "
              f"measured only {np.median(ww[mm_meas]):6.1f}")

    prob_top = (ranks <= 50).sum(axis=0) / np.maximum(n_ranked, 1)
    prob_bottom = (ranks >= n - 49).sum(axis=0) / np.maximum(n_ranked, 1)
    prob_first = (ranks <= 1.5).sum(axis=0) / np.maximum(n_ranked, 1)
    d["p_top_decile"] = prob_top
    d["p_bottom_decile"] = prob_bottom
    d["p_rank_one"] = prob_first

    central = np.full((n, N_PILLAR), np.nan)
    for i in range(n):
        m = np.isfinite(ranks[:, i]) & (ranks[:, i] <= 50)
        if m.sum() >= 20:
            central[i] = factors["w"][m].mean(axis=0)
    for k, (pk, _) in enumerate(PILLARS):
        d[f"central_w_{pk}"] = central[:, k]

    banner("sobol first-order indices on each company's rank")
    labels = {
        "normalisation": (factors["f1"], len(NORMS)),
        "winsorisation": (factors["f2"], len(WINSOR)),
        "pillar_inclusion": (factors["f3"], len(INCLUSION)),
        "missing_data": (factors["f4"], len(MISSING)),
        "aggregation": (factors["f5"], len(AGGREG)),
        "sector_relative": (factors["f7"], len(SECTOR_REL)),
    }
    wl, wk = weight_bins(factors["w"], per_dim=3)
    labels["weights"] = (wl, wk)
    # A company is unrankable only when available-case meets the loss of its one observed
    # pillar, so there are exactly two draw masks. Each group gets its own exact sample.
    always = np.isfinite(ranks).all(axis=0)
    part_draws = np.isfinite(ranks[:, ~always]).all(axis=1) if (~always).any() else None
    sobol = {k: np.zeros(n) for k in labels}
    y_all = ranks[:, always].astype(np.float64)
    for fname, (lab, nk) in labels.items():
        sobol[fname][always] = omega2(y_all, lab.astype(int), nk)
    if (~always).any():
        y_part = ranks[np.ix_(part_draws, ~always)].astype(np.float64)
        for fname, (lab, nk) in labels.items():
            sobol[fname][~always] = omega2(y_part, lab[part_draws].astype(int), nk)
    print(f"  {int(always.sum())} companies rankable in every draw, "
          f"{int((~always).sum())} rankable in {int(part_draws.sum())} of {L_DRAWS}")
    tot = np.sum([v for v in sobol.values()], axis=0)
    sobol_mean = {k: float(np.mean(v)) for k, v in sobol.items()}
    order = sorted(sobol_mean, key=sobol_mean.get, reverse=True)
    print(f"  mean first-order share of the variance of a company's rank, over {n} companies")
    for k in order:
        print(f"    {k:17s} {sobol_mean[k] * 100:5.1f}%")
    print(f"    {'sum of first-order':17s} {np.mean(tot) * 100:5.1f}%")
    print(f"    {'interactions+resid':17s} {(1 - np.mean(tot)) * 100:5.1f}%")
    sobol_by_tier = {}
    for tier in ["measured", "reported", "unmeasurable"]:
        mt = (d.coverage_tier == tier).to_numpy()
        sobol_by_tier[tier] = {k: float(np.mean(v[mt])) for k, v in sobol.items()}
        bits = "  ".join(f"{k[:9]} {sobol_by_tier[tier][k] * 100:4.1f}%" for k in order)
        print(f"  {tier:12s} n={int(mt.sum()):3d}  {bits}")

    banner("the two lenses: absolute against sector-relative")
    abs_med = np.nanmedian(ranks[factors["f7"] == 0], axis=0)
    rel_med = np.nanmedian(ranks[factors["f7"] == 1], axis=0)
    d["rank_median_absolute"] = abs_med
    d["rank_median_sector_relative"] = rel_med
    lens_rho = stats.spearmanr(abs_med, rel_med).statistic
    print(f"  Spearman between the two lenses across {n} companies: {lens_rho:+.3f}")
    print(f"  median absolute rank shift when the lens flips: "
          f"{np.median(np.abs(abs_med - rel_med)):.1f} ranks")
    mv = pd.DataFrame({"ticker": d.ticker, "company": d.company_name, "sector": d.gics_sector,
                       "absolute": abs_med, "relative": rel_med, "move": rel_med - abs_med})
    up = mv.reindex(mv.move.sort_values().index).head(10)
    print("  the 10 companies the sector-relative lens most rescues")
    for r in up.itertuples():
        print(f"    {r.ticker:6s} {r.company[:26]:26s} {r.sector[:22]:22s} absolute "
              f"{r.absolute:5.0f} -> sector-relative {r.relative:5.0f}")
    down = mv.reindex(mv.move.sort_values(ascending=False).index).head(10)
    print("  the 10 the sector-relative lens most punishes")
    for r in down.itertuples():
        print(f"    {r.ticker:6s} {r.company[:26]:26s} {r.sector[:22]:22s} absolute "
              f"{r.absolute:5.0f} -> sector-relative {r.relative:5.0f}")

    banner("what the missing-data assumption does to the companies that disclose nothing")
    scheme_table = {}
    for i4, scheme in enumerate(MISSING):
        sub = ranks[factors["f4"] == i4]
        mm = np.nanmedian(sub, axis=0)
        row = {t: float(np.median(mm[(d.coverage_tier == t).to_numpy()]))
               for t in ["measured", "reported", "unmeasurable"]}
        scheme_table[scheme] = row
        print(f"  {scheme:16s} median rank: measured {row['measured']:5.1f}  "
              f"reported {row['reported']:5.1f}  unmeasurable {row['unmeasurable']:5.1f}")
    print("  available-case rewards silence: a company that filed no tonnage and has no "
          "environmental penalty is ranked on a clean sheet it never had to earn. "
          "NMAR-pessimistic is the opposite prior. We never choose between them.")

    banner("effective weight audit, Paruolo, Saisana and Saltelli 2013")
    ref_key = (NORMS.index("pct_global"), 0, MISSING.index("sector_median"), 0)
    w_eq = np.full(N_PILLAR, 1.0 / N_PILLAR)
    ref_score = reference_score(scen, ref_key, w_eq, "linear")
    ref_rank = to_rank(ref_score)
    pillars_ref = scen[ref_key]["p"]
    audit = {}
    for nb in (10, 20, 25):
        s_i = main_effects(ref_score, pillars_ref, nb)
        audit[nb] = s_i
    s_main = audit[20]
    s_norm = s_main / s_main.sum()
    # d_m from equation (6): the reference pillar is the one with the largest nominal weight,
    # broken to the largest main effect since our nominal weights are equal.
    ref_i = int(np.argmax(s_main))
    dm = float(np.max([abs(1.0 - s_main[i] / s_main[ref_i])
                       for i in range(N_PILLAR) if i != ref_i]))
    dm_bounds = []
    for nb, s in audit.items():
        r = int(np.argmax(s))
        dm_bounds.append(float(np.max([abs(1.0 - s[i] / s[r]) for i in range(N_PILLAR) if i != r])))
    print("  reference specification: equal weights, linear, global percentile, no "
          "winsorisation, sector-median imputation, absolute")
    print(f"  {'pillar':14s} {'nominal':>8s} {'main effect':>12s} {'normalised':>11s}")
    for k, (pk, label) in enumerate(PILLARS):
        print(f"  {pk:14s} {0.25:8.3f} {s_main[k]:12.3f} {s_norm[k]:11.3f}   {label}")
    print(f"  d_m = {dm:.3f}  (bin-count bounds {min(dm_bounds):.3f} to {max(dm_bounds):.3f})")
    alt_key = (NORMS.index("pct_global"), 0, MISSING.index("available_case"), 0)
    alt_score = reference_score(scen, alt_key, w_eq, "linear")
    alt_s = main_effects(alt_score, scen[alt_key]["p"], 20)
    alt_r = int(np.nanargmax(alt_s))
    alt_dm = float(np.nanmax([abs(1.0 - alt_s[i] / alt_s[alt_r])
                              for i in range(N_PILLAR) if i != alt_r]))
    print(f"  under available-case instead of sector-median imputation the main effects are "
          + ", ".join(f"{p}: {alt_s[k]:.3f}" for k, (p, _) in enumerate(PILLARS))
          + f", d_m = {alt_dm:.3f}")
    print("  which pillar actually drives the index depends on the imputation, not on the "
          "declared weights: conduct runs 0.337 under sector-median and 0.828 under "
          "available-case, and credibility goes the other way")
    print("  conduct is weak under sector-median because 196 of 500 companies carry exactly "
          "zero environmental penalties and cannot be separated from each other")
    print("  published benchmarks: 2010 HDI 0.07, Index of African Governance 0.34, ARWU 0.36, "
          "THES 0.42, 2009 HDI 0.63, Sustainable Society Index 0.91")

    banner("pareto fronts, free of every weighting assumption")
    full = n_obs_pillar.all(axis=1).to_numpy()
    pv = scen[(NORMS.index("pct_global"), 0, MISSING.index("available_case"), 0)]["p"]
    fr = np.full(n, np.nan)
    fr[full] = pareto_fronts(pv[full])
    d["pareto_front"] = fr
    nf = int(np.nanmax(fr))
    print(f"  computed over the {int(full.sum())} companies with all four pillars observed")
    print(f"  {nf} fronts; front 1 holds {int((fr == 1).sum())} companies, the last front "
          f"{int((fr == nf).sum())}")
    f1_names = d.loc[fr == 1, ["ticker", "company_name"]]
    print("  front 1 (dominated by nobody, better than someone under every non-negative "
          "weighting):")
    print("   ", ", ".join(f"{r.ticker}" for r in f1_names.itertuples()))
    last_names = d.loc[fr == nf, ["ticker", "company_name"]]
    print(f"  last front (dominated on every pillar, worse under every non-negative weighting):")
    print("   ", ", ".join(f"{r.ticker}" for r in last_names.itertuples()))

    banner("aggregation rules compared, and rank reversal")
    ref_ranks = {}
    for agg in ("linear", "geometric", "copeland", "borda"):
        sc = reference_score(scen, ref_key, w_eq, agg)
        ref_ranks[agg] = to_rank(sc)
    aggs = list(ref_ranks)
    print("  Kendall tau between aggregation rules at the reference specification")
    for i in range(len(aggs)):
        for j in range(i + 1, len(aggs)):
            a, b = ref_ranks[aggs[i]], ref_ranks[aggs[j]]
            m = np.isfinite(a) & np.isfinite(b)
            t = stats.kendalltau(a[m], b[m]).statistic
            print(f"    {aggs[i]:10s} vs {aggs[j]:10s}  tau {t:+.3f}")

    rr_rng = np.random.default_rng(SEED + 1)
    reps = 20
    rr = {arm: {a: {"tau": [], "maxshift": []} for a in aggs}
          for arm in ("fixed_normalisation", "renormalised")}
    for _ in range(reps):
        keep = rr_rng.permutation(n)[: int(round(n * 0.9))]
        keep.sort()
        sfix = scen[ref_key]
        sub_fixed = {ref_key: dict(p=sfix["p"][keep], obs=sfix["obs"][keep],
                                   p0=sfix["p0"][keep], obsf=sfix["obsf"][keep],
                                   logpg=sfix["logpg"][keep],
                                   c=sfix["c"][:, keep][:, :, keep])}
        # the arm that renormalises: rebuild the whole scenario from the raw indicators over
        # the survivors only, which is what a rater actually does when the index changes
        sub_scen, _, _ = build_scenarios(d.iloc[keep].reset_index(drop=True),
                                         sector_codes[keep], n_sectors)
        for arm, sub in (("fixed_normalisation", sub_fixed), ("renormalised", sub_scen)):
            for agg in aggs:
                sc = reference_score(sub, ref_key, w_eq, agg)
                r_sub = to_rank(sc)
                r_full = ref_ranks[agg][keep]
                m = np.isfinite(r_sub) & np.isfinite(r_full)
                r_full_sub = stats.rankdata(r_full[m], method="average")
                rr[arm][agg]["tau"].append(stats.kendalltau(r_sub[m], r_full_sub).statistic)
                rr[arm][agg]["maxshift"].append(float(np.max(np.abs(r_sub[m] - r_full_sub))))
    print(f"  drop a random 10% of companies, {reps} replications, recompute and compare")
    rr_out = {}
    for arm in ("fixed_normalisation", "renormalised"):
        print(f"    arm: {arm}")
        rr_out[arm] = {}
        for agg in aggs:
            t = np.array(rr[arm][agg]["tau"])
            sh = np.array(rr[arm][agg]["maxshift"])
            rr_out[arm][agg] = dict(tau_mean=float(t.mean()), tau_min=float(t.min()),
                                    maxshift_mean=float(sh.mean()), maxshift_max=float(sh.max()))
            print(f"      {agg:10s} tau mean {t.mean():.4f} min {t.min():.4f}   "
                  f"max rank displacement mean {sh.mean():5.1f} worst {sh.max():5.1f}")

    banner("naive baselines")
    naive_rank = ref_ranks["linear"]
    shift = np.nanmean(np.abs(naive_rank - med))
    print(f"  average shift in rank between the naive equal-weight linear baseline and the "
          f"Monte Carlo median: R_S = {shift:.1f} ranks")
    # the vendor rule, applied to our own data: score a non-discloser worst in index
    zf_key = (NORMS.index("pct_global"), 0, MISSING.index("available_case"), 0)
    zs = scen[zf_key]
    pz = zs["p"].copy()
    for k in range(N_PILLAR):
        col = pz[:, k]
        miss = ~zs["obs"][:, k]
        col[miss] = np.nanmin(col) if np.isfinite(col).any() else 0.0
        pz[:, k] = col
    zf_score = pz @ w_eq
    zf_rank = to_rank(zf_score)
    d["rank_zerofilled"] = zf_rank
    d["rank_naive"] = naive_rank
    print(f"  zero-filling the non-disclosers instead shifts the ranking by "
          f"{np.nanmean(np.abs(zf_rank - naive_rank)):.1f} ranks on average, and by "
          f"{np.nanmean(np.abs(zf_rank - naive_rank)[(d.coverage_tier == 'unmeasurable').to_numpy()]):.1f} "
          f"ranks for the unmeasurable companies")
    mc = pd.read_parquet(f"{INTERIM}/market_cap.parquet")[["ticker", "market_cap"]]
    d = d.merge(mc, on="ticker", how="left")
    lm = np.log10(d.market_cap.to_numpy(dtype=float))
    for label, r in (("ours (median rank)", med), ("zero-filled naive", zf_rank)):
        m = np.isfinite(lm) & np.isfinite(r)
        pct = 100.0 * (1.0 - (r[m] - 1) / (n - 1))
        res = stats.linregress(lm[m], pct)
        print(f"  score percentile on log10 market cap, {label:20s}: beta {res.slope:+6.2f} "
              f"points per 10x, t {res.slope / res.stderr:+5.2f}, p {res.pvalue:.4f}, "
              f"R2 {res.rvalue ** 2:.4f}, n {m.sum()}")

    banner("our score against the vendor consensus")
    ven = pd.read_parquet(f"{INTERIM}/esg_vendor_consensus.parquet")[
        ["ticker", "vendor_percentile", "n_sources"]]
    d = d.merge(ven, on="ticker", how="left")
    our_pct = 100.0 * (1.0 - (d.rank_median.to_numpy() - 1) / (n - 1))
    d["our_percentile"] = our_pct
    m = d.vendor_percentile.notna().to_numpy() & np.isfinite(our_pct)
    rho, pval = stats.spearmanr(our_pct[m], d.vendor_percentile.to_numpy()[m])
    print(f"  Spearman rho {rho:+.3f}, p {pval:.4f}, n {int(m.sum())}")
    for tier in ["measured", "reported", "unmeasurable"]:
        mm = m & (d.coverage_tier == tier).to_numpy()
        if mm.sum() > 5:
            r2, p2 = stats.spearmanr(our_pct[mm], d.vendor_percentile.to_numpy()[mm])
            print(f"    within {tier:12s} rho {r2:+.3f}, p {p2:.4f}, n {int(mm.sum())}")
    disagree = d[m].copy()
    disagree["gap"] = disagree.our_percentile - disagree.vendor_percentile
    disagree = disagree.reindex(disagree.gap.abs().sort_values(ascending=False).index).head(10)
    print("  the 10 largest disagreements")
    rows_dis = []
    for r in disagree.itertuples():
        bits = []
        if pd.notna(r.intensity_t_per_musd):
            bits.append(f"{r.intensity_t_per_musd:,.0f} t/$m measured")
        if pd.notna(r.ear_used):
            bits.append(f"{r.ear_used:.0f}% of operating income at risk")
        if pd.notna(r.gap_pct_yr):
            bits.append(f"say-do {r.gap_pct_yr:+.1f} pp/yr")
        if pd.notna(r.env_penalty_per_musd) and r.env_penalty_per_musd > 0:
            bits.append(f"${r.env_penalty_per_musd:,.0f} of environmental penalties per $m revenue")
        if r.coverage_tier != "measured":
            bits.append(f"no mandatory tonnage ({r.coverage_tier})")
        reason = "; ".join(bits) if bits else "no measured carbon indicator"
        print(f"    {r.ticker:6s} {r.company_name[:28]:28s} ours {r.our_percentile:5.1f} "
              f"vendor {r.vendor_percentile:5.1f}  {reason}")
        rows_dis.append(dict(ticker=r.ticker, company=r.company_name,
                             ours=r.our_percentile, vendor=r.vendor_percentile,
                             gap=r.gap, tier=r.coverage_tier, reason=reason))
    meas_dis = d[m & (d.coverage_tier == "measured").to_numpy()].copy()
    meas_dis["gap"] = meas_dis.our_percentile - meas_dis.vendor_percentile
    meas_dis = meas_dis.reindex(meas_dis.gap.abs().sort_values(ascending=False).index).head(10)
    print("  the 10 largest disagreements restricted to the 139 companies we can measure")
    rows_dis_meas = []
    for r in meas_dis.itertuples():
        reason = (f"{r.intensity_t_per_musd:,.0f} t/$m, "
                  f"{r.ear_used:.0f}% of operating income at risk"
                  if pd.notna(r.ear_used) else f"{r.intensity_t_per_musd:,.0f} t/$m")
        print(f"    {r.ticker:6s} {r.company_name[:28]:28s} ours {r.our_percentile:5.1f} "
              f"vendor {r.vendor_percentile:5.1f}  {reason}")
        rows_dis_meas.append(dict(ticker=r.ticker, company=r.company_name,
                                  ours=r.our_percentile, vendor=r.vendor_percentile,
                                  gap=r.gap, reason=reason))

    banner("top and bottom of the index")
    d_sorted = d.sort_values("rank_median")
    print("  best 15 by median rank")
    for r in d_sorted.head(15).itertuples():
        print(f"    {int(round(r.rank_median)):3d} [{int(round(r.rank_p05)):3d}-"
              f"{int(round(r.rank_p95)):3d}] {r.ticker:6s} {r.company_name[:32]:32s} "
              f"{r.coverage_tier:12s} P(top decile) {r.p_top_decile:.2f}")
    print("  worst 15 by median rank")
    for r in d_sorted.tail(15).itertuples():
        print(f"    {int(round(r.rank_median)):3d} [{int(round(r.rank_p05)):3d}-"
              f"{int(round(r.rank_p95)):3d}] {r.ticker:6s} {r.company_name[:32]:32s} "
              f"{r.coverage_tier:12s} P(bottom decile) {r.p_bottom_decile:.2f}")
    meas = d[d.coverage_tier == "measured"].sort_values("rank_median")
    print("  best 10 among the 139 with a mandatory tonnage")
    for r in meas.head(10).itertuples():
        print(f"    {int(round(r.rank_median)):3d} [{int(round(r.rank_p05)):3d}-"
              f"{int(round(r.rank_p95)):3d}] {r.ticker:6s} {r.company_name[:32]:32s}")
    print("  worst 10 among the 139 with a mandatory tonnage")
    for r in meas.tail(10).itertuples():
        print(f"    {int(round(r.rank_median)):3d} [{int(round(r.rank_p05)):3d}-"
              f"{int(round(r.rank_p95)):3d}] {r.ticker:6s} {r.company_name[:32]:32s}")

    banner("how much of the world our mandatory numbers can see")
    try:
        ct = pd.read_parquet(f"{INTERIM}/climatetrace_nonus_share.parquet")
        ct = ct[ct.is_primary_listing].sort_values("year").groupby("ticker").tail(1)
        ct = ct[["ticker", "ct_nonus_share_balanced"]].dropna()
        j = d[["ticker", "coverage_tier", "rank_median"]].merge(ct, on="ticker", how="inner")
        jm = j[j.coverage_tier == "measured"]
        print(f"  Climate TRACE sizes a non-US asset share for {len(j)} of 500 companies, "
              f"{len(jm)} of them in our measured set")
        print(f"  median non-US share of those {len(jm)}: "
              f"{jm.ct_nonus_share_balanced.median() * 100:.1f}%, "
              f"{int((jm.ct_nonus_share_balanced > 0.5).sum())} over half")
        worst = jm.sort_values("ct_nonus_share_balanced", ascending=False).head(6)
        print("  the measured companies GHGRP sees least of: " + ", ".join(
            f"{r.ticker} {r.ct_nonus_share_balanced * 100:.0f}% abroad (rank {r.rank_median:.0f})"
            for r in worst.itertuples()))
        us_only = dict(n_tested=len(jm),
                       median_nonus_share=float(jm.ct_nonus_share_balanced.median()),
                       n_over_half=int((jm.ct_nonus_share_balanced > 0.5).sum()))
    except FileNotFoundError:
        us_only = {}
    print("  the other 427 companies are untested on non-US operations, so a company whose "
          "emissions sit abroad ranks well here for a reason that is not decarbonisation")

    banner("sensitivity of the conduct pillar to the lookback window")
    rp = -np.log10(1.0 + d.env_penalty_per_musd_recent5.to_numpy(dtype=float))
    mm = np.isfinite(rp) & np.isfinite(d.x_penalty.to_numpy(dtype=float))
    r5, p5v = stats.spearmanr(rp[mm], d.x_penalty.to_numpy(dtype=float)[mm])
    print(f"  Spearman between the 2000-2026 penalty indicator and the last-5-years version: "
          f"{r5:.3f}, n {int(mm.sum())}")

    banner("writing outputs")
    hist_bins = 25
    edges = np.linspace(0.5, n + 0.5, hist_bins + 1)
    hists = np.zeros((n, hist_bins), dtype=int)
    for i in range(n):
        col = ranks[:, i]
        col = col[np.isfinite(col)]
        hists[i] = np.histogram(col, bins=edges)[0]

    for k, (pk, _) in enumerate(PILLARS):
        d[f"pillar_{pk}"] = scen[ref_key]["p"][:, k]
        d[f"pillar_{pk}_observed"] = scen[ref_key]["obs"][:, k]
    for fname, v in sobol.items():
        d[f"sobol_{fname}"] = v
    d["seed"] = SEED
    d["n_draws"] = L_DRAWS

    keep_cols = [
        "ticker", "company_name", "gics_sector", "gics_sub_industry", "coverage_tier",
        "rank_median", "rank_p05", "rank_p95", "rank_width", "rank_samples", "our_percentile",
        "p_top_decile", "p_bottom_decile", "p_rank_one", "pareto_front",
        "rank_naive", "rank_zerofilled", "rank_median_absolute", "rank_median_sector_relative",
        "pillar_physical", "pillar_credibility", "pillar_exposure", "pillar_conduct",
        "pillar_physical_observed", "pillar_credibility_observed", "pillar_exposure_observed",
        "pillar_conduct_observed",
        "x_intensity", "x_trend", "x_saydo", "x_ear", "x_penalty",
        "intensity_t_per_musd", "scope1_tonnes", "emissions_year", "delivered_pct_yr",
        "gap_pct_yr", "ear_used", "ear_basis", "env_penalty_per_musd",
        "penalty_usd_environment", "case_count_environment", "revenue_musd", "market_cap",
        "vendor_percentile", "n_sources",
        "central_w_physical", "central_w_credibility", "central_w_exposure", "central_w_conduct",
        "sobol_normalisation", "sobol_winsorisation", "sobol_pillar_inclusion",
        "sobol_missing_data", "sobol_aggregation", "sobol_sector_relative", "sobol_weights",
        "seed", "n_draws",
    ]
    out = d[keep_cols].copy()
    out["dq"] = np.where(out.coverage_tier == "measured", 2,
                         np.where(out.coverage_tier == "reported", 4, 5))
    out["provenance_class"] = "mandatory"
    # the three secondary listings mirror their primary sibling and are marked as such
    uni_all = pd.read_parquet(f"{INTERIM}/universe.parquet")
    sec = uni_all[~uni_all.is_primary_listing][["ticker", "company_name", "share_class_siblings"]]
    sib = out.set_index("ticker")
    mirror = sec.join(sib.drop(columns=["company_name"]), on="share_class_siblings")
    mirror = mirror.rename(columns={"share_class_siblings": "mirrored_from"})
    out["mirrored_from"] = None
    out["is_primary_listing"] = True
    mirror["is_primary_listing"] = False
    full_out = pd.concat([out, mirror], ignore_index=True)
    full_out.to_parquet(f"{INTERIM}/scores.parquet", index=False)
    print(f"  data/interim/scores.parquet  {len(full_out)} rows x {full_out.shape[1]} columns "
          f"({len(out)} ranked primary listings + {len(mirror)} mirrored secondary listings)")

    payload = {
        "meta": {
            "seed": SEED,
            "n_draws": L_DRAWS,
            "n_companies": n,
            "built": pd.Timestamp.now("UTC").isoformat(),
            "method": ("OECD/JRC Handbook on Constructing Composite Indicators, Step 7: a single "
                       "Monte Carlo over every modelling choice at once. We publish a median rank "
                       "and a 5th to 95th percentile rank band, never a rank."),
            "rank_convention": "rank 1 is best; our_percentile 100 is best",
            "pillars": [{"key": k, "label": lab, "nominal_weight": 0.25} for k, lab in PILLARS],
            "indicators": [{"key": k, "pillar": PILLARS[p][0], "description": desc,
                            "provenance_class": prov} for k, p, desc, prov in INDICATORS],
            "trigger_factors": {
                "normalisation": NORMS, "winsorisation": ["off", "on"],
                "pillar_inclusion": ["all four"] + [f"drop {p}" for p, _ in PILLARS],
                "missing_data": MISSING, "aggregation": AGGREG,
                "weights": "Dirichlet(1,1,1,1) over the four pillars",
                "sector_relative": ["absolute", "sector-relative"],
            },
            "carbon_price_usd": meta["ear_price"],
            "carbon_price_note": ("NGFS Net Zero 2050, United States region, year 2030, "
                                  "US$2010 per tCO2"),
            "copeland_note": ("Copeland is used as a polynomial Condorcet-consistent surrogate "
                              "for the Kemeny median order, which is NP-hard at N=500. Borda is "
                              "computed only as a comparison arm to show rank reversal."),
            "coverage_note": ("The 273 companies with no mandatory tonnage are never imputed a "
                              "carbon number. They carry coverage_tier unmeasurable, a rank band "
                              "that spans the honest uncertainty, and an explicit reason."),
            "provenance_note": "Every indicator is mandatory. No vendor number is an input.",
            "what_this_is_not": ("This is a carbon and conduct score built on US mandatory "
                                 "filings. It is not a judgement on what a company sells. "
                                 "Altria ranks near the top because tobacco is not "
                                 "carbon-intensive. The product-level exclusions live in "
                                 "revenue_exclusions.parquet and are applied by the portfolio, "
                                 "not by the score."),
            "us_only_note": ("GHGRP sees US facilities above 25,000 tCO2e. A company whose "
                             "emissions sit abroad looks clean here. Climate TRACE sizes that "
                             "gap for 73 companies and the rest of the index is untested."),
        },
        "coverage": {
            "by_tier": d.coverage_tier.value_counts().to_dict(),
            "by_indicator": cov,
            "by_pillar": {k: int(v) for k, v in n_obs_pillar.sum().to_dict().items()},
            "all_four_pillars": int(n_obs_pillar.all(axis=1).sum()),
            "one_pillar_only": int((n_obs_pillar.sum(axis=1) == 1).sum()),
        },
        "rank_interval_summary": {
            "median_width": float(np.median(width)),
            "mean_width": float(np.mean(width)),
            "min_width": float(np.min(width)),
            "max_width": float(np.max(width)),
            "n_wider_than_100": int((width > 100).sum()),
            "n_wider_than_200": int((width > 200).sum()),
            "n_wider_than_300": int((width > 300).sum()),
            "by_tier": {t: {"n": int((d.coverage_tier == t).sum()),
                            "median_width": float(np.median(width[(d.coverage_tier == t).to_numpy()])),
                            "median_rank": float(np.median(med[(d.coverage_tier == t).to_numpy()]))}
                        for t in ["measured", "reported", "unmeasurable"]},
        },
        "sobol_first_order": {
            "mean_share": sobol_mean,
            "sum_first_order": float(np.mean(tot)),
            "interactions_and_residual": float(1 - np.mean(tot)),
            "estimator": ("Pearson correlation ratio eta^2 with the standard bias correction, "
                          "read off the same Monte Carlo sample. No Saltelli design, no extra runs."),
            "weights_binning": f"the Dirichlet draw binned into {wk} simplex cells, 3 per pillar",
        },
        "weight_audit": {
            "nominal": {p: 0.25 for p, _ in PILLARS},
            "main_effect": {p: float(s_main[k]) for k, (p, _) in enumerate(PILLARS)},
            "main_effect_normalised": {p: float(s_norm[k]) for k, (p, _) in enumerate(PILLARS)},
            "d_m": dm,
            "d_m_bounds": [min(dm_bounds), max(dm_bounds)],
            "d_m_available_case": alt_dm,
            "main_effect_available_case": {p: float(alt_s[k]) for k, (p, _) in enumerate(PILLARS)},
            "reference_specification": ("equal weights, linear aggregation, global percentile "
                                        "normalisation, no winsorisation, sector-median "
                                        "imputation, absolute"),
            "definition": ("Paruolo, Saisana and Saltelli 2013 equation 6: d_m = max_i "
                           "|w_i/w_1 - S_i/S_1| with pillar 1 the one carrying the largest "
                           "nominal weight. Our nominal weights are equal, so w_i/w_1 = 1 and "
                           "d_m = 1 - min_i(S_i)/max_i(S_i)."),
            "benchmarks": {"2010 HDI": 0.07, "Index of African Governance": 0.34, "ARWU": 0.36,
                           "THES": 0.42, "2009 HDI": 0.63, "Sustainable Society Index": 0.91},
        },
        "pareto": {
            "n_scored": int(full.sum()),
            "n_fronts": nf,
            "front_1": [dict(ticker=r.ticker, company=r.company_name)
                        for r in d.loc[fr == 1].itertuples()],
            "last_front": [dict(ticker=r.ticker, company=r.company_name)
                           for r in d.loc[fr == nf].itertuples()],
            "note": ("The Pareto front is invariant to any monotone per-pillar transform, so it "
                     "carries no normalisation, weighting or aggregation assumption at all."),
        },
        "aggregation_comparison": {
            "kendall_tau": {f"{aggs[i]}|{aggs[j]}": float(
                stats.kendalltau(*[x[np.isfinite(ref_ranks[aggs[i]]) & np.isfinite(ref_ranks[aggs[j]])]
                                   for x in (ref_ranks[aggs[i]], ref_ranks[aggs[j]])]).statistic)
                for i in range(len(aggs)) for j in range(i + 1, len(aggs))},
            "rank_reversal": rr_out,
            "reversal_design": "drop a random 10% of companies, 20 replications, seed 20260913",
        },
        "baselines": {
            "average_shift_in_rank_vs_naive": float(shift),
            "zerofill_mean_shift": float(np.nanmean(np.abs(zf_rank - naive_rank))),
            "zerofill_mean_shift_unmeasurable": float(
                np.nanmean(np.abs(zf_rank - naive_rank)[(d.coverage_tier == 'unmeasurable').to_numpy()])),
        },
        "vendor_comparison": {
            "spearman_rho": float(rho), "p_value": float(pval), "n": int(m.sum()),
            "largest_disagreements": rows_dis,
            "largest_disagreements_measured": rows_dis_meas,
            "note": ("A low correlation is the expected result, not a bug. Berg, Koelbel and "
                     "Rigobon put the average pairwise correlation between professional raters at "
                     "0.61, and at 0.36 in the seven-rater sample."),
        },
        "conditional_bands": cond_out,
        "lenses": {
            "spearman_absolute_vs_sector_relative": float(lens_rho),
            "median_abs_rank_shift": float(np.median(np.abs(abs_med - rel_med))),
            "most_rescued": [dict(ticker=r.ticker, company=r.company, sector=r.sector,
                                  absolute=float(r.absolute), relative=float(r.relative))
                             for r in up.itertuples()],
            "most_punished": [dict(ticker=r.ticker, company=r.company, sector=r.sector,
                                   absolute=float(r.absolute), relative=float(r.relative))
                              for r in down.itertuples()],
        },
        "missing_scheme_by_tier": scheme_table,
        "us_only_bias": us_only,
        "sobol_by_tier": sobol_by_tier,
        "headline": {
            "median_rank_band_width": float(np.median(width)),
            "n_wider_than_100": int((width > 100).sum()),
            "top_sobol_factor": order[0],
            "top_sobol_share": sobol_mean[order[0]],
            "weights_sobol_share": sobol_mean["weights"],
            "aggregation_sobol_share": sobol_mean["aggregation"],
            "d_m": dm,
            "vendor_spearman": float(rho),
            "vendor_n": int(m.sum()),
            "average_shift_vs_naive": float(shift),
            "pareto_front_1": int((fr == 1).sum()),
            "variance_of_rank_explained_by_tier": float(ssb / ((med - grand) ** 2).sum()),
            "n_unmeasurable_and_unfined": int(tied.sum()),
            "lens_spearman": float(lens_rho),
        },
        "rank_histogram": {"bin_edges": edges.round(2).tolist(), "n_bins": hist_bins},
        "companies": [],
    }
    for i, r in enumerate(d.itertuples()):
        rec = {
            "t": r.ticker, "n": r.company_name, "s": r.gics_sector,
            "tier": r.coverage_tier,
            "med": round(float(med[i]), 1), "p05": round(float(p05[i]), 1),
            "p95": round(float(p95[i]), 1),
            "pct": round(float(our_pct[i]), 1),
            "ptop": round(float(prob_top[i]), 3), "pbot": round(float(prob_bottom[i]), 3),
            "hist": hists[i].tolist(),
            "naive": None if not np.isfinite(naive_rank[i]) else round(float(naive_rank[i]), 1),
            "pareto": None if not np.isfinite(fr[i]) else int(fr[i]),
            "pillars": {p: (round(float(scen[ref_key]["p"][i, k]), 4)
                            if scen[ref_key]["obs"][i, k] else None)
                        for k, (p, _) in enumerate(PILLARS)},
            "obs": [bool(scen[ref_key]["obs"][i, k]) for k in range(N_PILLAR)],
            "vendor": None if pd.isna(r.vendor_percentile) else round(float(r.vendor_percentile), 1),
            "intensity": None if pd.isna(r.intensity_t_per_musd) else round(float(r.intensity_t_per_musd), 2),
            "trend": None if pd.isna(r.delivered_pct_yr) else round(float(r.delivered_pct_yr), 2),
            "saydo": None if pd.isna(r.gap_pct_yr) else round(float(r.gap_pct_yr), 2),
            "ear": None if pd.isna(r.ear_used) else round(float(r.ear_used), 2),
            "penalty": None if pd.isna(r.env_penalty_per_musd) else round(float(r.env_penalty_per_musd), 2),
            "sobol": {k: round(float(v[i]), 3) for k, v in sobol.items()},
            "cw": [None if not np.isfinite(central[i, k]) else round(float(central[i, k]), 3)
                   for k in range(N_PILLAR)],
        }
        payload["companies"].append({k: v for k, v in rec.items() if v is not None})

    top20 = np.argsort(med)[:20]
    dom = np.zeros((20, 20))
    for a in range(20):
        for b in range(20):
            ia, ib = top20[a], top20[b]
            mm2 = np.isfinite(ranks[:, ia]) & np.isfinite(ranks[:, ib])
            dom[a, b] = float((ranks[mm2, ia] < ranks[mm2, ib]).mean()) if mm2.sum() else np.nan
    payload["pairwise_dominance_top20"] = {
        "tickers": [d.ticker.iloc[i] for i in top20],
        "p_row_above_column": np.round(dom, 3).tolist(),
    }

    with open(f"{SITE}/scores.json", "w") as fh:
        json.dump(jsonable(payload), fh, separators=(",", ":"), allow_nan=False)
    import os
    kb = os.path.getsize(f"{SITE}/scores.json") / 1024
    print(f"  site/data/scores.json  {kb:.1f} KB")
    print(f"  seed {SEED} written into meta.seed and the parquet")


if __name__ == "__main__":
    main()
