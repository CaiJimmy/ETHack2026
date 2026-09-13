"""Does a vendor ESG score measure sustainability, or the size of the sustainability team?

The commercial raters award points for answering. LSEG's October 2024 ESG Scores methodology says a
score "of 0 is assigned for Boolean data points when no relevant data is found in the public
disclosure of companies", and Berg, Fabisik and Sautner (ECGI Finance WP 708/2020) record what
happened when Refinitiv moved non-reporters from 0.5 to 0 in April 2020: the median overall ESG score
in the rewritten history fell 18% and the E subscore 44%, with no company changing a single tonne.
A rule like that turns a rating into a measure of disclosure volume, and disclosure volume is bought
with staff.

This script tests that on our own universe. It builds a disclosure coverage index out of the
voluntary material we hold for each company, regresses the vendor consensus percentile on firm size
and on that index, then runs the same two regressions against the Scope 1 intensity we measure from
mandatory EPA filings. Five regressions, all printed with beta, t, R squared and n.

Inputs, all from data/interim plus the cached CDP score embed in data/raw:
  universe, market_cap, esg_vendor_consensus, scope23, targets_company, emissions_by_ticker,
  financials, wba_company (optional, skipped with a printed note when the WBA lane has not run)

Outputs:
  data/interim/disclosure_bias.parquet   one row per primary listing
  data/interim/disclosure_bias.png       the two-panel deck chart
  site/data/bias.json                    everything the site draws, including the chart points
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
RAW = ROOT / "data" / "raw"
SITE = ROOT / "site" / "data"

sys.path.insert(0, str(ROOT / "src"))
from fetch_universe import normalise_name  # noqa: E402

SEED = 20260912
N_BOOT = 2000

# The CDP climate grade is only recoverable from the icon filename; the embed carries no numeric
# cell at all. See the note in fetch_scope23.py, which fetched and cached this file.
CDP_EMBED = RAW / "cdp_flourish" / "flourish_28119771.html"
CDP_GRADE_RE = re.compile(r"/Climate-([A-Za-z]+(?:-minus)?)-Icon", re.I)

# hq_location is "City, State" for a US head office and "City, Country" otherwise, so anything that
# is not one of these is a US state or DC.
NON_US_HQ = {
    "Ireland": "Ireland",
    "Bermuda": "Bermuda",
    "Switzerland": "Switzerland",
    "United Kingdom": "United Kingdom",
    "Netherlands": "Netherlands",
    "Israel": "Israel",
    "Singapore": "Singapore",
    "Jersey": "Jersey",
    "Panama": "Panama",
    "Luxembourg": "Luxembourg",
    "Canada": "Canada",
}


def rule(title):
    print("\n" + "=" * 92)
    print(title)
    print("=" * 92)


# ----------------------------------------------------------------------------
# CDP climate grade, parsed out of the cached public score embed
# ----------------------------------------------------------------------------

def cdp_climate_grades(universe):
    """Ticker -> CDP climate letter grade, or the explicit non-answer CDP prints instead.

    CDP publishes its corporate scores as a Flourish table whose grade cell is an <svg> URL, so the
    letter is in the filename and nowhere else. Companies are matched on exact normalised name, which
    collides across countries (Domino's Pizza Group plc, CDW Holding Limited, Discovery Limited), so
    the head-office country decides and a ticker whose surviving rows disagree is dropped and counted.
    """
    if not CDP_EMBED.exists():
        print(f"  {CDP_EMBED} missing, CDP component skipped")
        return {}, {"available": False}

    text = CDP_EMBED.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"_Flourish_data\s*=\s*", text)
    rows = [r["columns"] for r in json.JSONDecoder().raw_decode(text, m.end())[0]["rows"]]

    aliases = json.loads((INTERIM / "ticker_aliases.json").read_text())["name_to_ticker"]
    tickers = set(universe.ticker)
    # plain dicts, not a DataFrame column: a missing value in a pandas 3 string column is truthy
    hq_country = {}
    own_name = {}
    for r in universe.itertuples():
        tail = r.hq_location.split(", ")[-1] if isinstance(r.hq_location, str) else ""
        hq_country[r.ticker] = NON_US_HQ.get(tail, "United States of America")
        own_name[r.ticker] = normalise_name(r.company_name)

    candidates = {}
    for name, country, climate in ((r[0], r[1], r[2]) for r in rows):
        t = aliases.get(normalise_name(name))
        if t in tickers:
            candidates.setdefault(t, []).append((name, country, climate))

    def grade_of(cell):
        g = CDP_GRADE_RE.search(cell) if isinstance(cell, str) else None
        if g:
            return g.group(1).replace("-minus", "-").upper()
        return str(cell).strip().lower().replace(" ", "_") or "no_entry"

    out = {}
    stats_ = {"available": True, "rows": len(rows), "matched_tickers": len(candidates),
              "multi_row_tickers": 0, "dropped_ambiguous": 0}
    for t, cands in candidates.items():
        if len(cands) > 1:
            stats_["multi_row_tickers"] += 1
            same_country = [c for c in cands if c[1] == hq_country[t]]
            if same_country:
                cands = same_country
            exact = [c for c in cands if normalise_name(c[0]) == own_name[t]]
            if exact:
                cands = exact
        graded = {grade_of(c[2]).isalpha() or "-" in grade_of(c[2]) for c in cands}
        letters = {grade_of(c[2]) for c in cands}
        if len(cands) > 1 and len(letters) > 1:
            stats_["dropped_ambiguous"] += 1
            continue
        out[t] = grade_of(sorted(cands)[0][2])
    print(f"  CDP embed {len(rows)} rows, {len(candidates)} matched to a primary listing, "
          f"{stats_['multi_row_tickers']} matched more than one row, "
          f"{stats_['dropped_ambiguous']} dropped as ambiguous, {len(out)} kept")
    counts = pd.Series(list(out.values())).value_counts()
    print("  grades: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    stats_["grade_counts"] = {str(k): int(v) for k, v in counts.items()}
    return out, stats_


def is_letter_grade(g):
    return bool(g) and bool(re.fullmatch(r"[A-D]-?", str(g)))


# ----------------------------------------------------------------------------
# the disclosure coverage index
# ----------------------------------------------------------------------------

def build_coverage(universe):
    scope23 = pd.read_parquet(INTERIM / "scope23.parquet")
    targets = pd.read_parquet(INTERIM / "targets_company.parquet")

    vol = scope23[scope23.tonnes_co2e.notna() & scope23.ticker.isin(set(universe.ticker))]
    s1 = set(vol[vol.scope == "1"].ticker)
    s2 = set(vol[vol.scope.str.startswith("2")].ticker)
    s3 = set(vol[vol.scope == "3_total"].ticker)
    s3cat = set(vol[vol.scope.str.startswith("3_cat")].ticker)
    any_report = set(vol.ticker)

    cdp, cdp_stats = cdp_climate_grades(universe)

    wba_path = INTERIM / "wba_company.parquet"
    if wba_path.exists():
        wba = set(pd.read_parquet(wba_path).ticker)
        print(f"  WBA profiles joined: {len(wba & set(universe.ticker))}")
    else:
        wba = set()
        print("  wba_company.parquet not present, WBA component left out of the index")

    t = targets.set_index("ticker")
    df = universe[["ticker", "company_name", "gics_sector"]].copy()

    def col(series, test):
        # pd.NA is truthy in a bare if and raises in bool(), so every test goes through pd.notna
        lookup = {k: bool(test(v)) if pd.notna(v) else False for k, v in series.items()}
        return [lookup.get(x, False) for x in df.ticker]

    df["has_voluntary_scope1"] = df.ticker.isin(s1)
    df["has_voluntary_scope2"] = df.ticker.isin(s2)
    df["has_voluntary_scope3_total"] = df.ticker.isin(s3)
    df["has_voluntary_scope3_categories"] = df.ticker.isin(s3cat)
    df["cdp_climate_grade"] = [cdp.get(x) for x in df.ticker]
    df["has_cdp_climate_score"] = [is_letter_grade(cdp.get(x)) for x in df.ticker]
    df["has_sbti_near_term_validated"] = col(t.sbti_near_term_status, lambda v: v == "Targets set")
    df["has_sbti_net_zero_validated"] = col(t.sbti_net_zero_status, lambda v: v == "Targets set")
    df["in_net_zero_tracker"] = col(t.in_nzt, bool)
    df["has_numeric_target"] = col(t.promised_annual_reduction_pct, lambda v: pd.notna(v))
    df["has_interim_target"] = col(t.nzt_has_interim, bool)
    df["has_transition_plan"] = col(t.nzt_has_plan, lambda v: v == "Yes")
    df["has_annual_reporting"] = col(t.nzt_reporting_mechanism, lambda v: v == "Annual reporting")
    if wba:
        df["has_wba_profile"] = df.ticker.isin(wba)

    components = [c for c in df.columns if c.startswith(("has_", "in_"))]
    df["n_disclosures"] = df[components].sum(axis=1)
    df["disclosure_coverage"] = df.n_disclosures / len(components)

    # A rater that reads CDP would make any index containing a CDP component partly circular, so
    # carry a second index with CDP removed and run the key regression on both.
    ex_cdp = [c for c in components if c != "has_cdp_climate_score"]
    df["disclosure_coverage_ex_cdp"] = df[ex_cdp].sum(axis=1) / len(ex_cdp)

    # the other reading of coverage: how many independent voluntary registers hold this company
    sources = pd.DataFrame({
        "report_corpus": df.ticker.isin(any_report),
        "cdp": [is_letter_grade(cdp.get(x)) for x in df.ticker],
        "sbti": col(t.in_sbti, bool),
        "net_zero_tracker": col(t.in_nzt, bool),
    })
    if wba:
        sources["wba"] = df.ticker.isin(wba).to_numpy()
    df["n_voluntary_sources"] = sources.sum(axis=1).to_numpy()

    print(f"\n  {len(components)} components, {len(sources.columns)} independent voluntary registers")
    for c in components:
        print(f"    {c:34s} {int(df[c].sum()):3d} / {len(df)}")
    print(f"\n  disclosure_coverage: mean {df.disclosure_coverage.mean():.3f}, "
          f"median {df.disclosure_coverage.median():.3f}, "
          f"min {df.disclosure_coverage.min():.3f}, max {df.disclosure_coverage.max():.3f}")
    print(f"  {int((df.n_disclosures == 0).sum())} companies disclose nothing we can find, "
          f"{int((df.n_disclosures >= len(components) - 1).sum())} disclose all or all but one")
    return df, components, list(sources.columns), cdp_stats


# ----------------------------------------------------------------------------
# what we measure, and who we refuse to score
# ----------------------------------------------------------------------------

def build_measured(df):
    emissions = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    financials = pd.read_parquet(INTERIM / "financials.parquet")
    mcap = pd.read_parquet(INTERIM / "market_cap.parquet")
    cons = pd.read_parquet(INTERIM / "esg_vendor_consensus.parquet")

    prim = emissions[emissions.is_primary_listing]
    mandatory = set(prim[prim.scope1_ghgrp_tonnes.notna()].ticker) | \
        set(prim[prim.scope1_camd_tonnes.notna()].ticker)
    e23 = prim[(prim.year == 2023) & prim.scope1_ghgrp_tonnes.notna()]
    s1_2023 = dict(zip(e23.ticker, e23.scope1_ghgrp_tonnes))

    f23 = financials[(financials.fy == 2023) & financials.is_primary_listing]
    rev_2023 = dict(zip(f23.ticker, f23.revenue))
    mc = mcap[mcap.is_primary_listing]
    mcap_by_ticker = dict(zip(mc.ticker, mc.market_cap_company))
    vend = dict(zip(cons.ticker, cons.vendor_percentile))
    vend_n = dict(zip(cons.ticker, cons.n_sources))

    df = df.copy()
    df["market_cap"] = [mcap_by_ticker.get(x) for x in df.ticker]
    df["log_market_cap"] = np.log10(df.market_cap)
    df["vendor_percentile"] = [vend.get(x) for x in df.ticker]
    df["n_vendor_sources"] = [vend_n.get(x) for x in df.ticker]
    df["scope1_ghgrp_2023_tonnes"] = [s1_2023.get(x) for x in df.ticker]
    df["revenue_2023_usd"] = [rev_2023.get(x) for x in df.ticker]

    ok = (df.scope1_ghgrp_2023_tonnes > 0) & (df.revenue_2023_usd > 0)
    df["measured_intensity_t_per_musd"] = np.where(
        ok, df.scope1_ghgrp_2023_tonnes / (df.revenue_2023_usd / 1e6), np.nan)
    df["log_measured_intensity"] = np.log10(df.measured_intensity_t_per_musd)

    df["has_mandatory_measurement"] = df.ticker.isin(mandatory)
    tier = []
    for r in df.itertuples():
        if r.has_mandatory_measurement:
            tier.append("measured")
        elif r.has_voluntary_scope1:
            tier.append("reported")
        else:
            tier.append("unmeasurable")
    df["coverage_tier"] = tier

    # our score on the measured tier: the percentile of low intensity, 100 is cleanest. This is the
    # physical core of the headline score, not the composite, and it exists only where a mandatory
    # tonnage does. The 273 companies with no mandatory number are not given one.
    scored = df.measured_intensity_t_per_musd.notna()
    pct = df.loc[scored, "measured_intensity_t_per_musd"].rank(pct=True, ascending=False) * 100
    df["measured_intensity_percentile"] = np.nan
    df.loc[scored, "measured_intensity_percentile"] = pct

    # and the counterfactual: what our score would look like if we did what LSEG does and scored a
    # company we cannot measure as if it were the worst in the index
    worst = df.measured_intensity_t_per_musd.max()
    zerofill = df.measured_intensity_t_per_musd.fillna(worst * 10)
    df["zerofilled_score_percentile"] = zerofill.rank(pct=True, ascending=False) * 100

    print(f"\n  coverage tiers over {len(df)} primary listings:")
    print(df.coverage_tier.value_counts().to_string())
    print(f"  2023 GHGRP Scope 1 and 2023 revenue both present: {int(scored.sum())}")
    print(f"  measured intensity t/$m revenue: median "
          f"{df.measured_intensity_t_per_musd.median():.1f}, "
          f"min {df.measured_intensity_t_per_musd.min():.2f}, "
          f"max {df.measured_intensity_t_per_musd.max():.0f}")
    print(f"  vendor consensus percentile present: {int(df.vendor_percentile.notna().sum())}")

    # sector-relative versions, which is how a rating is read in practice: nobody ranks a utility
    # against a software company
    for c in ("vendor_percentile", "measured_intensity_percentile"):
        df[c + "_vs_sector"] = df[c] - df.groupby("gics_sector")[c].transform("mean")
    return df


# ----------------------------------------------------------------------------
# regressions
# ----------------------------------------------------------------------------

def ols(y, x, rng=None):
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    X = np.column_stack([np.ones(len(x)), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    n, k = X.shape
    dof = n - k
    s2 = resid @ resid / dof
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * s2)
    t = beta / se
    p = 2 * stats.t.sf(np.abs(t), dof)
    r2 = 1 - (resid @ resid) / ((y - y.mean()) ** 2).sum()
    out = dict(n=int(n), beta=float(beta[1]), se=float(se[1]), t=float(t[1]), p=float(p[1]),
               r2=float(r2), intercept=float(beta[0]),
               beta_std=float(beta[1] * x.std(ddof=1) / y.std(ddof=1)),
               x_mean=float(x.mean()), x_min=float(x.min()), x_max=float(x.max()))
    if rng is not None:
        draws = np.empty(N_BOOT)
        idx = rng.integers(0, n, size=(N_BOOT, n))
        for i in range(N_BOOT):
            xs, ys = x[idx[i]], y[idx[i]]
            v = ((xs - xs.mean()) ** 2).sum()
            draws[i] = np.nan if v == 0 else ((xs - xs.mean()) * (ys - ys.mean())).sum() / v
        lo, hi = np.nanpercentile(draws, [2.5, 97.5])
        out["beta_ci95"] = [float(lo), float(hi)]
    rho = stats.spearmanr(x, y)
    out["spearman_rho"] = float(rho.statistic)
    out["spearman_p"] = float(rho.pvalue)
    return out


def run_regressions(df, rng):
    specs = [
        ("1", "vendor_percentile", "log_market_cap", None,
         "vendor ESG consensus percentile ~ log10 market cap"),
        ("2", "vendor_percentile", "disclosure_coverage", None,
         "vendor ESG consensus percentile ~ disclosure coverage"),
        ("3", "log_measured_intensity", "log_market_cap", None,
         "our measured Scope 1 intensity (log) ~ log10 market cap"),
        ("4", "log_measured_intensity", "disclosure_coverage", None,
         "our measured Scope 1 intensity (log) ~ disclosure coverage"),
        ("5", "vendor_percentile", "log_measured_intensity", None,
         "vendor ESG consensus percentile ~ our measured Scope 1 intensity (log)"),
        ("1m", "vendor_percentile", "log_market_cap", "measured",
         "regression 1 on the measured subsample only"),
        ("2m", "vendor_percentile", "disclosure_coverage", "measured",
         "regression 2 on the measured subsample only"),
        ("3p", "measured_intensity_percentile", "log_market_cap", None,
         "our score percentile ~ log10 market cap (the y axis of panel B)"),
        ("4p", "measured_intensity_percentile", "disclosure_coverage", None,
         "our score percentile ~ disclosure coverage"),
        ("6", "zerofilled_score_percentile", "log_market_cap", None,
         f"our score with the {int((df.coverage_tier == 'unmeasurable').sum())} unmeasurable "
         f"companies zero-filled at the bottom ~ log10 market cap"),
        ("7", "disclosure_coverage", "log_market_cap", None,
         "disclosure coverage ~ log10 market cap"),
        ("8", "n_voluntary_sources", "log_market_cap", None,
         "count of voluntary registers holding the company ~ log10 market cap"),
        ("9", "vendor_percentile", "disclosure_coverage_ex_cdp", None,
         "vendor ESG consensus percentile ~ disclosure coverage with CDP removed"),
        ("10", "n_vendor_sources", "disclosure_coverage", None,
         "how many vendor sources rate the company ~ disclosure coverage"),
        ("11", "vendor_percentile", "n_voluntary_sources", None,
         "vendor ESG consensus percentile ~ count of voluntary registers holding the company"),
        ("A", "vendor_percentile_vs_sector", "disclosure_coverage", None,
         "sector-relative vendor percentile ~ disclosure coverage (panel A of the chart)"),
        ("B", "measured_intensity_percentile_vs_sector", "disclosure_coverage", None,
         "sector-relative measured intensity percentile ~ disclosure coverage (panel B)"),
    ]
    results = []
    for rid, y, x, subset, label in specs:
        sub = df if subset is None else df[df.coverage_tier == subset]
        m = sub[[y, x]].replace([np.inf, -np.inf], np.nan).dropna()
        r = ols(m[y], m[x], rng=rng)
        r.update(id=rid, label=label, y=y, x=x, sample="all" if subset is None else subset)
        results.append(r)
        print(f"\n  [{rid}] {label}")
        print(f"      n={r['n']:3d}  beta={r['beta']:+.4f}  se={r['se']:.4f}  t={r['t']:+.2f}  "
              f"p={r['p']:.4f}  R2={r['r2']:.4f}  std_beta={r['beta_std']:+.3f}  "
              f"95% CI [{r['beta_ci95'][0]:+.4f}, {r['beta_ci95'][1]:+.4f}]")
        print(f"      Spearman rho={r['spearman_rho']:+.3f} (p={r['spearman_p']:.3f})")
    return results


def multivariate(df):
    """Size and disclosure enter together, standardised, so the betas are comparable."""
    m = df[["vendor_percentile", "log_market_cap", "disclosure_coverage"]].dropna()
    y = m.vendor_percentile.to_numpy(float)
    Z = np.column_stack([
        (m.log_market_cap - m.log_market_cap.mean()) / m.log_market_cap.std(ddof=1),
        (m.disclosure_coverage - m.disclosure_coverage.mean()) / m.disclosure_coverage.std(ddof=1),
    ])
    X = np.column_stack([np.ones(len(y)), Z])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    dof = len(y) - X.shape[1]
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * (resid @ resid / dof))
    t = beta / se
    p = 2 * stats.t.sf(np.abs(t), dof)
    r2 = 1 - (resid @ resid) / ((y - y.mean()) ** 2).sum()
    out = dict(n=int(len(y)), r2=float(r2),
               beta_log_market_cap=float(beta[1]), t_log_market_cap=float(t[1]),
               p_log_market_cap=float(p[1]),
               beta_disclosure_coverage=float(beta[2]), t_disclosure_coverage=float(t[2]),
               p_disclosure_coverage=float(p[2]),
               corr_x=float(np.corrcoef(Z[:, 0], Z[:, 1])[0, 1]))
    print(f"\n  vendor percentile ~ standardised size + standardised disclosure, n={out['n']}, "
          f"R2={r2:.4f}")
    print(f"      size       beta={out['beta_log_market_cap']:+.3f} pp per sd  "
          f"t={out['t_log_market_cap']:+.2f}  p={out['p_log_market_cap']:.4f}")
    print(f"      disclosure beta={out['beta_disclosure_coverage']:+.3f} pp per sd  "
          f"t={out['t_disclosure_coverage']:+.2f}  p={out['p_disclosure_coverage']:.4f}")
    print(f"      correlation between the two predictors {out['corr_x']:+.3f}")
    return out


def tier_by_size(df):
    """Who ends up in the tier a vendor would score zero."""
    d = df[df.log_market_cap.notna()].copy()
    d["size_quintile"] = pd.qcut(d.log_market_cap, 5, labels=[1, 2, 3, 4, 5]).astype(int)
    rows = []
    for q, grp in d.groupby("size_quintile"):
        rows.append(dict(
            quintile=int(q), n=int(len(grp)),
            median_market_cap_usd_bn=float(grp.market_cap.median() / 1e9),
            mean_disclosure_coverage=float(grp.disclosure_coverage.mean()),
            share_measured=float((grp.coverage_tier == "measured").mean()),
            share_unmeasurable=float((grp.coverage_tier == "unmeasurable").mean()),
            mean_vendor_percentile=float(grp.vendor_percentile.mean()),
            n_with_vendor_score=int(grp.vendor_percentile.notna().sum()),
        ))
    out = pd.DataFrame(rows)
    print("\n  by market-cap quintile:")
    print(out.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    return rows


def per_source(df):
    """The consensus is an average of six disagreeing sources. Ask each of them separately."""
    cons = pd.read_parquet(INTERIM / "esg_vendor_consensus.parquet")
    keys = dict(zip(df.ticker, zip(df.log_market_cap, df.disclosure_coverage)))
    rows = []
    for col in [c for c in cons.columns if c.startswith("pct_")]:
        src = col[4:]
        m = cons[["ticker", col]].dropna()
        m = m[m.ticker.isin(keys)]
        x1 = np.array([keys[t][0] for t in m.ticker], dtype=float)
        x2 = np.array([keys[t][1] for t in m.ticker], dtype=float)
        y = m[col].to_numpy(float)
        ok = np.isfinite(x1) & np.isfinite(y)
        a = ols(y[ok], x1[ok])
        b = ols(y, x2)
        rows.append(dict(source=src, n=int(len(y)),
                         beta_size=a["beta"], t_size=a["t"], r2_size=a["r2"],
                         beta_disclosure=b["beta"], t_disclosure=b["t"], r2_disclosure=b["r2"]))
        print(f"    {src:16s} n={len(y):3d}  size beta={a['beta']:+7.2f} t={a['t']:+5.2f} "
              f"R2={a['r2']:.3f}   disclosure beta={b['beta']:+7.2f} t={b['t']:+5.2f} "
              f"R2={b['r2']:.3f}")
    return rows


def within_sector(df):
    """Demean every variable inside its GICS sector, then rerun. What is left is not sector mix."""
    out = []
    pairs = [("vendor_percentile", "log_market_cap"),
             ("vendor_percentile", "disclosure_coverage"),
             ("vendor_percentile", "disclosure_coverage_ex_cdp"),
             ("log_measured_intensity", "log_market_cap"),
             ("log_measured_intensity", "disclosure_coverage"),
             ("measured_intensity_percentile", "log_market_cap"),
             ("measured_intensity_percentile", "disclosure_coverage"),
             ("measured_intensity_percentile", "disclosure_coverage_ex_cdp"),
             ("disclosure_coverage", "log_market_cap"),
             ("n_vendor_sources", "disclosure_coverage"),
             ("vendor_percentile", "n_voluntary_sources"),
             ("measured_intensity_percentile", "n_voluntary_sources")]
    for y, x in pairs:
        m = df[["gics_sector", y, x]].replace([np.inf, -np.inf], np.nan).dropna()
        d = m.copy()
        d[y] = m[y] - m.groupby("gics_sector")[y].transform("mean")
        d[x] = m[x] - m.groupby("gics_sector")[x].transform("mean")
        r = ols(d[y], d[x])
        r.update(y=y, x=x, spec="within_gics_sector")
        out.append(r)
        print(f"    {y:26s} ~ {x:20s} n={r['n']:3d}  beta={r['beta']:+8.4f}  t={r['t']:+5.2f}  "
              f"R2={r['r2']:.4f}")
    return out


def partial(df, y, xs):
    """Both predictors standardised and entered together, so the betas are comparable."""
    m = df[[y] + xs].replace([np.inf, -np.inf], np.nan).dropna()
    yv = m[y].to_numpy(float)
    Z = np.column_stack([(m[x] - m[x].mean()) / m[x].std(ddof=1) for x in xs])
    X = np.column_stack([np.ones(len(yv)), Z])
    beta = np.linalg.lstsq(X, yv, rcond=None)[0]
    resid = yv - X @ beta
    dof = len(yv) - X.shape[1]
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * (resid @ resid / dof))
    t = beta / se
    p = 2 * stats.t.sf(np.abs(t), dof)
    r2 = 1 - (resid @ resid) / ((yv - yv.mean()) ** 2).sum()
    out = dict(y=y, n=int(len(yv)), r2=float(r2),
               terms=[dict(x=xs[i], beta_per_sd=float(beta[i + 1]), t=float(t[i + 1]),
                           p=float(p[i + 1])) for i in range(len(xs))],
               corr_x=float(np.corrcoef(Z[:, 0], Z[:, 1])[0, 1]))
    print(f"    {y} ~ " + " + ".join(xs) + f"   n={out['n']}, R2={r2:.4f}")
    for term in out["terms"]:
        print(f"      {term['x']:22s} beta={term['beta_per_sd']:+8.4f} per sd  "
              f"t={term['t']:+5.2f}  p={term['p']:.4f}")
    return out


# ----------------------------------------------------------------------------
# the chart
# ----------------------------------------------------------------------------

BLUE, ORANGE, GREY, INK, GRID = "#2a78d6", "#eb6834", "#8d8c85", "#1a1a19", "#e6e5e0"
BOX = dict(facecolor="#fcfcfb", edgecolor="none", alpha=0.85, pad=2)


def _frame(ax, xlabel, ylabel=None):
    ax.set_xlabel(xlabel, fontsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")


def _fit_label(r):
    return f"beta {r['beta']:+.1f}   t {r['t']:+.2f}   R2 {r['r2']:.3f}   n {r['n']}"


def draw_disclosure_chart(df, regs, path):
    """The chart the evidence supports: what a company discloses against what it is scored."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_id = {r["id"]: r for r in regs}
    a, b = by_id["A"], by_id["B"]
    pa = df[df.vendor_percentile_vs_sector.notna()]
    pb = df[df.measured_intensity_percentile_vs_sector.notna()]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharex=True, sharey=True)
    xs = np.linspace(0, 1, 50)
    for ax, pts, ycol, colour, title, r in (
        (axes[0], pa, "vendor_percentile_vs_sector", ORANGE,
         f"Vendor ESG consensus  (n={a['n']})", a),
        (axes[1], pb, "measured_intensity_percentile_vs_sector", BLUE,
         f"Our measured Scope 1 intensity  (n={b['n']})", b),
    ):
        ax.axhline(0, color="#c3c2b7", lw=1)
        ax.scatter(pts.disclosure_coverage * 100, pts[ycol], s=18, c=colour, alpha=0.75,
                   linewidths=0.5, edgecolors="white")
        ax.plot(xs * 100, r["intercept"] + r["beta"] * xs, color=INK, lw=2)
        ax.set_title(title, loc="left", fontsize=11)
        ax.text(0.03, 0.04, _fit_label(r), transform=ax.transAxes, fontsize=9, va="bottom")
        _frame(ax, "share of the voluntary disclosure checklist filed (%)")
    axes[0].set_ylabel("percentile, points from the sector mean", fontsize=9)
    fig.suptitle("Their score pays for disclosure. Ours pays for filed tonnes.", x=0.008, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print(f"  wrote {path}")


def draw_size_chart(df, regs, path):
    """The same two scores against firm size. Reported because it came out the other way."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_id = {r["id"]: r for r in regs}
    a, b = by_id["1"], by_id["3p"]
    pa = df[df.vendor_percentile.notna() & df.log_market_cap.notna()]
    pb = df[df.measured_intensity_percentile.notna() & df.log_market_cap.notna()]
    un = df[(df.coverage_tier == "unmeasurable") & df.log_market_cap.notna()]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharex=True, sharey=True)
    xs = np.linspace(df.log_market_cap.min(), df.log_market_cap.max(), 50)

    axes[0].scatter(pa.log_market_cap, pa.vendor_percentile, s=18, c=ORANGE, alpha=0.75,
                    linewidths=0.5, edgecolors="white")
    axes[0].plot(xs, a["intercept"] + a["beta"] * xs, color=INK, lw=2)
    axes[0].set_title(f"Vendor ESG consensus  (n={a['n']})", loc="left", fontsize=11)
    axes[0].text(0.03, 0.96, _fit_label(a), transform=axes[0].transAxes, fontsize=9, va="top",
                 bbox=BOX)

    axes[1].scatter(un.log_market_cap, np.full(len(un), -10.0), s=16, c=GREY, alpha=0.8,
                    marker="|", linewidths=1.2)
    axes[1].scatter(pb.log_market_cap, pb.measured_intensity_percentile, s=18, c=BLUE, alpha=0.75,
                    linewidths=0.5, edgecolors="white")
    axes[1].plot(xs, b["intercept"] + b["beta"] * xs, color=INK, lw=2)
    axes[1].set_title(f"Our measured Scope 1 intensity  (n={b['n']})", loc="left", fontsize=11)
    axes[1].text(0.03, 0.96, _fit_label(b), transform=axes[1].transAxes, fontsize=9, va="top",
                 bbox=BOX)
    n_un = int((df.coverage_tier == "unmeasurable").sum())
    axes[1].text(df.log_market_cap.min(), -21,
                 f"{n_un} companies carry no mandatory tonnage and are left unscored",
                 fontsize=8, color="#52514e")

    for ax in axes:
        _frame(ax, "log10 market cap (USD)")
    axes[0].set_ylabel("percentile, 100 is best", fontsize=9)
    axes[0].set_ylim(-26, 104)
    fig.suptitle("Against size, neither score slopes the way the literature predicts",
                 x=0.008, ha="left", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print(f"  wrote {path}")


# ----------------------------------------------------------------------------

def main():
    rng = np.random.default_rng(SEED)
    universe = pd.read_parquet(INTERIM / "universe.parquet")
    universe = universe[universe.is_primary_listing].reset_index(drop=True)
    print(f"universe: {len(universe)} primary listings, seed {SEED}")

    rule("Q1  what each company has chosen to disclose")
    df, components, registers, cdp_stats = build_coverage(universe)

    rule("Q2  what we can measure from mandatory filings")
    df = build_measured(df)

    rule("Q3  the five regressions")
    regs = run_regressions(df, rng)
    multi = multivariate(df)
    print("\n  each vendor source on its own:")
    sources_reg = per_source(df)
    print("\n  the same relationships demeaned inside GICS sector:")
    within = within_sector(df)
    print("\n  size and disclosure entered together:")
    partials = [partial(df, "vendor_percentile", ["log_market_cap", "disclosure_coverage"]),
                partial(df, "log_measured_intensity", ["log_market_cap", "disclosure_coverage"]),
                partial(df, "measured_intensity_percentile",
                        ["log_market_cap", "disclosure_coverage"])]
    quintiles = tier_by_size(df)

    rule("Q4  outputs")
    cols = ["ticker", "company_name", "gics_sector", "coverage_tier", "market_cap",
            "log_market_cap", "vendor_percentile", "vendor_percentile_vs_sector",
            "n_vendor_sources", "cdp_climate_grade"] + \
        components + ["n_disclosures", "disclosure_coverage", "disclosure_coverage_ex_cdp",
                      "n_voluntary_sources", "scope1_ghgrp_2023_tonnes", "revenue_2023_usd",
                      "measured_intensity_t_per_musd", "log_measured_intensity",
                      "measured_intensity_percentile", "measured_intensity_percentile_vs_sector",
                      "zerofilled_score_percentile"]
    out = df[cols].copy()
    out["provenance_class"] = "voluntary"
    out["seed"] = SEED
    out.to_parquet(INTERIM / "disclosure_bias.parquet", index=False)
    print(f"  wrote data/interim/disclosure_bias.parquet, {len(out)} rows, "
          f"{len(out.columns)} columns")

    draw_disclosure_chart(df, regs, INTERIM / "disclosure_bias.png")
    draw_size_chart(df, regs, INTERIM / "disclosure_bias_size.png")

    SITE.mkdir(parents=True, exist_ok=True)
    points = []
    for r in df.itertuples():
        def num(v, nd=2):
            return None if pd.isna(v) else round(float(v), nd)
        points.append(dict(
            t=r.ticker,
            s=r.gics_sector,
            tier=r.coverage_tier,
            x=num(r.log_market_cap, 4),
            cov=num(r.disclosure_coverage, 4),
            nd=int(r.n_disclosures),
            vendor=num(r.vendor_percentile),
            vendor_rel=num(r.vendor_percentile_vs_sector),
            ours=num(r.measured_intensity_percentile),
            ours_rel=num(r.measured_intensity_percentile_vs_sector),
            intensity=num(r.measured_intensity_t_per_musd, 3),
            cdp=None if r.cdp_climate_grade is None or pd.isna(r.cdp_climate_grade)
            else str(r.cdp_climate_grade),
        ))
    by_id = {r["id"]: r for r in regs}

    def panel(key, label, yfield, ylabel, rid, colour, **extra):
        r = by_id[rid]
        return dict(key=key, label=label, y=dict(field=yfield, label=ylabel),
                    regression_id=rid,
                    fit=dict(intercept=r["intercept"], slope=r["beta"]),
                    annotation=dict(beta=r["beta"], t=r["t"], p=r["p"], r2=r["r2"], n=r["n"]),
                    colour=colour, **extra)

    n_unmeasurable = int((df.coverage_tier == "unmeasurable").sum())
    payload = dict(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        seed=SEED,
        bootstrap_draws=N_BOOT,
        provenance_class="voluntary",
        note=("The disclosure coverage index is built from voluntary material only and is never an "
              "input to the score. The vendor consensus percentile is provenance_class vendor and "
              "is a benchmark, never an input."),
        finding=(
            "Within a GICS sector, moving from filing none of the voluntary disclosure checklist to "
            "filing all of it is worth "
            f"{by_id['A']['beta']:.1f} percentile points of vendor ESG standing "
            f"(t={by_id['A']['t']:.2f}, p={by_id['A']['p']:.4f}, n={by_id['A']['n']}) and "
            f"{by_id['B']['beta']:+.1f} points of our measured Scope 1 intensity rank "
            f"(t={by_id['B']['t']:.2f}, p={by_id['B']['p']:.3f}, n={by_id['B']['n']}). "
            "The headline size regression came out the other way from the literature and is "
            "reported as it ran: the vendor consensus does not load on market cap directly "
            f"(t={by_id['1']['t']:.2f}, R2={by_id['1']['r2']:.4f}, n={by_id['1']['n']}). Size acts "
            "through disclosure instead: disclosure coverage rises "
            f"{by_id['7']['beta']:.3f} per decade of market cap (t={by_id['7']['t']:.2f}, "
            f"n={by_id['7']['n']}), and disclosure buys the rating."),
        components=components,
        registers=registers,
        cdp=cdp_stats,
        counts=dict(
            primary_listings=int(len(df)),
            with_vendor_score=int(df.vendor_percentile.notna().sum()),
            measured=int((df.coverage_tier == "measured").sum()),
            reported=int((df.coverage_tier == "reported").sum()),
            unmeasurable=n_unmeasurable,
            with_measured_intensity=int(df.measured_intensity_t_per_musd.notna().sum()),
            disclose_nothing=int((df.n_disclosures == 0).sum()),
        ),
        regressions=regs,
        multivariate=multi,
        per_vendor_source=sources_reg,
        within_gics_sector=within,
        partial_regressions=partials,
        size_quintiles=quintiles,
        chart=dict(
            id="disclosure",
            title="Their score pays for disclosure. Ours pays for filed tonnes.",
            subtitle=("Each point is one S&P 500 company. Percentiles are shown as points from the "
                      "company's own GICS sector mean, because that is how a rating is used."),
            points_field="points",
            x=dict(field="cov", label="share of the voluntary disclosure checklist filed",
                   unit="share 0 to 1", display="percent"),
            panels=[
                panel("vendor", "Vendor ESG consensus", "vendor_rel",
                      "percentile, points from the sector mean", "A", "#eb6834"),
                panel("ours", "Our measured Scope 1 intensity", "ours_rel",
                      "percentile, points from the sector mean", "B", "#2a78d6"),
            ],
        ),
        chart_size=dict(
            id="size",
            title="Against size, neither score slopes the way the literature predicts",
            subtitle=("The brief's version of the chart, reported as it ran. The vendor consensus "
                      "is flat in size; our measured intensity is not, and that slope is sector "
                      "mix, gone once sector is held fixed (t="
                      f"{[w for w in within if w['y'] == 'log_measured_intensity' and w['x'] == 'log_market_cap'][0]['t']:.2f})."),
            points_field="points",
            x=dict(field="x", label="log10 market cap (USD)"),
            panels=[
                panel("vendor", "Vendor ESG consensus", "vendor", "percentile, 100 is best",
                      "1", "#eb6834"),
                panel("ours", "Our measured Scope 1 intensity", "ours", "percentile, 100 is best",
                      "3p", "#2a78d6",
                      unscored_note=f"{n_unmeasurable} companies carry no mandatory tonnage and are "
                                    f"left unscored"),
            ],
        ),
        points=points,
        citations=[
            dict(key="lseg2024",
                 text="LSEG ESG Scores methodology, October 2024: a score \"of 0 is assigned for "
                      "Boolean data points when no relevant data is found in the public disclosure "
                      "of companies\"."),
            dict(key="berg_fabisik_sautner",
                 text="Berg, Fabisik and Sautner, Rewriting History II: The (Un)Predictable Past "
                      "of ESG Ratings, ECGI Finance Working Paper 708/2020. Refinitiv moved "
                      "non-reporters from 0.5 to 0 in April 2020; median overall ESG scores in the "
                      "rewritten data are 18% lower and the E subscore 44% lower."),
        ],
    )
    (SITE / "bias.json").write_text(json.dumps(payload, indent=1))
    size_kb = (SITE / "bias.json").stat().st_size / 1024
    print(f"  wrote site/data/bias.json, {size_kb:.0f} KB, {len(points)} chart points")


if __name__ == "__main__":
    main()
