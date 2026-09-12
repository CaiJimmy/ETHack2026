"""The say-do gap: what a company promised against what its stacks actually did.

Two numbers per company on one axis, percent per year.

  PROMISED  targets_company.promised_annual_reduction_pct, the compound annual rate of decline in
            absolute scope 1+2 emissions that a company's own strongest target commits it to. Built
            by src/fetch_targets.py; read its docstring before touching anything here. It is not
            redefined in this file, only sign-flipped onto the chart axis.
  DELIVERED the compound annual rate of change fitted to measured EPA GHGRP scope 1 tonnage,
            log-linear in year over the longest clean window a company has, minimum four years.

WHAT "CLEAN WINDOW" MEANS, because the first run of this script got it wrong and it mattered.

  A window is a run of consecutive years, each carrying a positive mandatory tonnage, over which the
  reported perimeter does not step. Two breaks end a window:

    the facility count changes by more than half year on year
    the tonnage changes by more than 2.5x year on year

  Neither is an operating trend. They are acquisitions, spin-offs, divestitures and part-years of
  ownership. Molson Coors goes from one facility at 30 ktCO2e to six at 415 kt in 2020; Phillips 66
  goes from 6 facilities to 127 across the 2012 spin-off; Delta buys the Trainer refinery mid-2012
  and its two facilities jump 3.5x. Fitting straight through those steps read as 71, 26 and 21
  percent a year of emissions growth, which is not what any of those companies did. The break rule
  is written on the perimeter, not on the emissions, so it cannot be accused of trimming inconvenient
  observations: the tonnage rule only fires at a factor of 2.5, which no continuing operation does.

  Gradual perimeter drift survives the rule and is flagged instead. trend_flags names every one:
  perimeter_drift when the facility count moved more than 20 percent end to end, stale when the
  window ends before the last GHGRP year, large_rate when the fitted rate exceeds 25 percent a year.
  headline_clean is the flag-free subset and every headline number is printed both ways.

SIGN CONVENTION, and it is the one thing to get right when reading these columns.

  Columns ending _pct_yr are the ANNUAL CHANGE IN EMISSIONS. Negative is falling emissions.
  Columns ending _reduction_pct_yr are the annual RATE OF CUT. Positive is falling emissions, which
  is the convention targets_company already uses.

      promised_pct_yr = -promised_reduction_pct_yr
      delivered_pct_yr = -delivered_reduction_pct_yr
      gap_pct_yr = delivered_pct_yr - promised_pct_yr = promised_reduction - delivered_reduction

  So on the chart both axes run "more negative is better", the 45 degree line is the promise kept,
  and every point ABOVE the line is a company emitting more than its own promised path. gap_pct_yr
  is positive for exactly those companies, in percentage points per year.

ABSOLUTE AND INTENSITY, both, in parallel columns.

  delivered_*        absolute scope 1 tonnes. This is the basis the promise is on: fetch_targets.py
                     drops intensity targets from the rate on purpose, because an intensity target
                     can fall while absolute emissions rise. So the headline gap is absolute against
                     absolute, and it is the only same-basis comparison available here.
  delivered_int_*    tCO2e per $M of the company's own revenue, nominal USD, from SEC XBRL. This is
                     the company-level term inside PCAF's weighted average carbon intensity, not
                     PCAF's economic emissions intensity, which divides by the investor's capital
                     rather than by revenue. PCAF names absolute emissions, economic intensity,
                     physical intensity and WACI as four different metrics and says absolute
                     emissions do not benchmark companies of different size against each other. The
                     ranking really does move between the two columns and that difference is a
                     finding, not an error. gap_intensity_pct_yr mixes bases by construction: an
                     absolute promise against an intensity path. It is emitted because it is what an
                     index provider would compute, and it is labelled so nobody quotes it as the gap.
  Revenue is nominal. We do not deflate, so several points a year of price inflation sit inside every
  intensity decline and flatter it against the absolute column.

WHAT THE MEASURED SERIES IS, AND WHAT IT IS NOT

  GHGRP is US facilities emitting above 25,000 tCO2e a year, filed under legal penalty. A climate
  target is normally global and covers scope 1+2. The trend here is therefore the trend of the US
  mandatory perimeter, not of the promise's own boundary, and a company can shrink one while growing
  the other. Nothing in this file pretends otherwise: perimeter is the first caveat on the slide.
  CAMD Part 75 stack monitors are fitted separately into delivered_camd_* because they run to 2026
  while GHGRP stops at 2023. They add no company that GHGRP does not already carry, so they never
  feed the headline.

COVERAGE TIERS, never crossed silently
  measured      a mandatory measured tonnage exists (GHGRP or CAMD), whatever its length
  reported      no mandatory number, but a voluntary or Climate TRACE tonnage exists
  unmeasurable  no emissions number from any source. We do not invent one, we rank it as unscorable

Outputs
  data/interim/say_do_gap.parquet   503 listings, every column above
  site/data/say_do.json             the chart, its axes, its labels and one compact row per listing
"""

import json
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
SITE = ROOT / "site" / "data"

SEED = 20260912
N_BOOT = 2000
MIN_YEARS = 4  # a two-point difference is not a trend, and three points cannot show a residual

FACILITY_STEP = 1.5   # a facility count that moves by half in one year is a deal, not a trend
TONNAGE_STEP = 2.5    # nor does a continuing operation change its stack emissions by 2.5x in a year
DRIFT_FLAG = 0.2      # end-to-end facility drift worth naming on the row


def clean_windows(pairs, fac=None):
    """Split a company's series into runs of consecutive years with a stable reported perimeter.

    pairs is (year, value): tonnes for the absolute series, tonnes per $M revenue for the intensity
    one. fac maps year to the facility count behind that value and is what the perimeter rule reads.
    A run ends at a missing year, a non-positive value, a facility count that moves by more than
    FACILITY_STEP, or a value that moves by more than TONNAGE_STEP. See the module docstring for why.
    """
    clean = [(int(y), float(v)) for y, v in pairs
             if v is not None and np.isfinite(v) and float(v) > 0]
    clean.sort(key=lambda p: p[0])
    runs, run = [], []
    for item in clean:
        if run:
            py, pv = run[-1]
            cy, cv = item
            gap = cy != py + 1
            jump = not (1 / TONNAGE_STEP <= cv / pv <= TONNAGE_STEP)
            step = False
            if fac:
                f0, f1 = fac.get(py), fac.get(cy)
                if f0 and f1:
                    step = not (1 / FACILITY_STEP <= f1 / f0 <= FACILITY_STEP)
            if gap or jump or step:
                runs.append(run)
                run = []
        run.append(item)
    if run:
        runs.append(run)
    return runs


def longest_clean_window(pairs, fac=None):
    """The longest stable run. Ties go to the later one, because recency beats length on a tie."""
    best = []
    for run in clean_windows(pairs, fac):
        if len(run) >= len(best):
            best = run
    return best


def loglinear_fit(window, boot_key=None):
    """OLS of ln(value) on year. Returns the compound annual change in percent, with its SE, R2 and n.

    The percent is (exp(slope) - 1) * 100, so it composes the same way the promised rate does. The
    SE moves to the percent scale by the delta method. boot_key, when given, adds a seeded residual
    bootstrap of the same statistic as a second opinion on the SE: n is small enough and emissions
    autocorrelated enough that the OLS SE is optimistic, and it costs nothing to say so.
    """
    n = len(window)
    if n < MIN_YEARS:
        return None
    x = np.array([p[0] for p in window], dtype=float)
    y = np.log(np.array([p[1] for p in window], dtype=float))
    xc = x - x.mean()
    sxx = float((xc ** 2).sum())
    slope = float((xc * (y - y.mean())).sum() / sxx)
    intercept = float(y.mean() - slope * x.mean())
    resid = y - (intercept + slope * x)
    sse = float((resid ** 2).sum())
    sst = float(((y - y.mean()) ** 2).sum())
    s2 = sse / (n - 2)
    se_slope = float(np.sqrt(s2 / sxx))
    pct = (np.exp(slope) - 1.0) * 100.0
    se_pct = 100.0 * np.exp(slope) * se_slope
    r2 = 1.0 - sse / sst if sst > 0 else np.nan

    se_boot = np.nan
    if boot_key is not None and sse > 0:
        rng = np.random.default_rng(SEED + zlib.crc32(boot_key.encode()))
        draws = rng.choice(resid, size=(N_BOOT, n), replace=True)
        yb = (intercept + slope * x) + draws
        slopes = ((xc * (yb - yb.mean(axis=1, keepdims=True))).sum(axis=1)) / sxx
        se_boot = float(np.std((np.exp(slopes) - 1.0) * 100.0, ddof=1))

    return {
        "pct_yr": pct,
        "se": se_pct,
        "se_boot": se_boot,
        "r2": r2,
        "n_years": n,
        "year_start": int(x[0]),
        "year_end": int(x[-1]),
        "first": window[0][1],
        "last": window[-1][1],
    }


def fit_for(series_by_ticker, ticker, tag, fac=None):
    w = longest_clean_window(series_by_ticker.get(ticker, []), fac)
    if not w:
        return None, []
    return loglinear_fit(w, boot_key=f"{tag}:{ticker}"), w


def main():
    uni = pd.read_parquet(INTERIM / "universe.parquet")
    emi = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    tgt = pd.read_parquet(INTERIM / "targets_company.parquet")
    fin = pd.read_parquet(INTERIM / "financials.parquet")
    s23 = pd.read_parquet(INTERIM / "scope23.parquet")
    mcap = pd.read_parquet(INTERIM / "market_cap.parquet")
    ctr = pd.read_parquet(INTERIM / "climatetrace_company.parquet")

    print(f"universe {len(uni)} listings, {int(uni.is_primary_listing.sum())} primary")
    print(f"emissions_by_ticker {len(emi)} rows, years {emi.year.min()}-{emi.year.max()}")
    print(f"targets_company {len(tgt)} rows, "
          f"{int(tgt.promised_annual_reduction_pct.notna().sum())} carry a numeric promise")

    # ---------------------------------------------------------------- coverage tiers
    mandatory = set(emi.loc[emi.scope1_ghgrp_tonnes.notna() | emi.scope1_camd_tonnes.notna(), "ticker"])
    voluntary = set(s23.loc[s23.tonnes_co2e.notna(), "ticker"])
    trace = set(ctr.ticker)
    tiers = {}
    for t in uni.ticker:
        if t in mandatory:
            tiers[t] = "measured"
        elif t in voluntary or t in trace:
            tiers[t] = "reported"
        else:
            tiers[t] = "unmeasurable"
    tier_counts = pd.Series(tiers).value_counts()
    print(f"coverage tiers over 503 listings: measured {tier_counts.get('measured', 0)}, "
          f"reported {tier_counts.get('reported', 0)}, "
          f"unmeasurable {tier_counts.get('unmeasurable', 0)}")
    print(f"  mandatory {len(mandatory)}, voluntary {len(voluntary)}, climate trace {len(trace)}, "
          f"union {len(mandatory | voluntary | trace)}")

    # ---------------------------------------------------------------- the three measured series
    ghgrp = {}
    camd = {}
    facilities = {}
    camd_facilities = {}
    for t, sub in emi.groupby("ticker", sort=False):
        ghgrp[t] = list(zip(sub.year, sub.scope1_ghgrp_tonnes))
        camd[t] = list(zip(sub.year, sub.scope1_camd_tonnes))
        facilities[t] = dict(zip(sub.year.astype(int), sub.facility_count.astype(int)))
        camd_facilities[t] = dict(zip(sub.year.astype(int), sub.camd_facility_count.astype(int)))
    last_ghgrp_year = int(emi.loc[emi.scope1_ghgrp_tonnes.notna(), "year"].max())

    rev = (fin.loc[fin.revenue.notna() & (fin.revenue > 0), ["ticker", "fy", "revenue"]]
              .sort_values(["ticker", "fy"]).drop_duplicates(["ticker", "fy"], keep="last"))
    rev_by = {}
    for t, sub in rev.groupby("ticker", sort=False):
        rev_by[t] = dict(zip(sub.fy.astype(int), sub.revenue.astype(float)))
    print(f"financials: revenue on {len(rev_by)} tickers, fiscal years {int(rev.fy.min())}-{int(rev.fy.max())}")

    intensity = {}
    for t, pairs in ghgrp.items():
        r = rev_by.get(t, {})
        intensity[t] = [(y, (v / (r[int(y)] / 1e6)) if (int(y) in r and v is not None
                                                        and np.isfinite(v) and v > 0) else np.nan)
                        for y, v in pairs]

    # ---------------------------------------------------------------- optional second promise source
    wba_path = INTERIM / "wba_targets.parquet"
    wba_rate, wba_src, wba_class = {}, {}, {}
    if wba_path.exists():
        wba = pd.read_parquet(wba_path)
        need = {"ticker", "reduction_pct", "base_year", "target_year", "scope", "target_type"}
        if need.issubset(wba.columns):
            ok = wba[wba.reduction_pct.notna() & wba.base_year.notna() & wba.target_year.notna()].copy()
            ok = ok[ok.target_year.astype(float) - ok.base_year.astype(float) >= 3]
            ok = ok[ok.scope.astype(str).str.contains("1", na=False)]
            ok = ok[~ok.target_type.astype(str).str.lower().str.contains("intensity", na=False)]
            ok["rate"] = [
                (1.0 - (1.0 - min(float(r), 90.0) / 100.0) ** (1.0 / (float(ty) - float(by)))) * 100.0
                for r, by, ty in zip(ok.reduction_pct, ok.base_year, ok.target_year)]
            ok = ok.sort_values(["ticker", "rate"], ascending=[True, False])
            best = ok.drop_duplicates("ticker", keep="first")
            wba_rate = dict(zip(best.ticker, best.rate))
            wba_src = dict(zip(best.ticker, best.scope.astype(str)))
            if "sbti_classification" in best.columns:
                wba_class = {t: (c if pd.notna(c) else None)
                             for t, c in zip(best.ticker, best.sbti_classification)}
            print(f"wba_targets: second-source promised rate on {len(wba_rate)} tickers")
        else:
            print(f"wba_targets exists but lacks {sorted(need - set(wba.columns))}, skipped")
    else:
        print("wba_targets.parquet absent, second promise source skipped")

    # ---------------------------------------------------------------- per listing
    tg = tgt.set_index("ticker")
    mc = mcap.set_index("ticker")["market_cap"].to_dict()
    rows = []
    for t, name, sector, primary in zip(uni.ticker, uni.company_name, uni.gics_sector,
                                        uni.is_primary_listing):
        row = {
            "ticker": t, "company": name, "gics_sector": sector,
            "is_primary_listing": bool(primary), "coverage_tier": tiers[t],
            "has_mandatory": t in mandatory, "has_voluntary": t in voluntary,
            "has_climatetrace": t in trace,
        }

        # the promise, exactly as the targets lane derived it, flipped onto the change axis
        promised_red = np.nan
        if t in tg.index:
            g = tg.loc[t]
            promised_red = float(g.promised_annual_reduction_pct) \
                if pd.notna(g.promised_annual_reduction_pct) else np.nan
            row["promised_source"] = g.promised_basis if pd.notna(g.promised_basis) else None
            row["promised_dq"] = int(g.dq) if pd.notna(g.dq) else None
            row["promised_baseline_year"] = int(g.promised_baseline_year) \
                if pd.notna(g.promised_baseline_year) else None
            row["promised_target_year"] = int(g.promised_target_year) \
                if pd.notna(g.promised_target_year) else None
            row["promised_scopes"] = g.promised_scopes if pd.notna(g.promised_scopes) else None
            row["promised_capped_at_netzero"] = bool(g.promised_capped_at_netzero) \
                if pd.notna(g.promised_capped_at_netzero) else False
        row["promised_reduction_pct_yr"] = promised_red
        row["promised_pct_yr"] = -promised_red if np.isfinite(promised_red) else np.nan
        row["wba_promised_reduction_pct_yr"] = wba_rate.get(t, np.nan)
        row["wba_promised_pct_yr"] = -wba_rate[t] if t in wba_rate else np.nan
        row["wba_promised_scope"] = wba_src.get(t)
        row["wba_sbti_classification"] = wba_class.get(t)

        # delivered, absolute, GHGRP
        fit, win = fit_for(ghgrp, t, "abs", facilities.get(t))
        row["emissions_source"] = "ghgrp" if fit else None
        row["delivered_basis"] = "absolute" if fit else None
        if fit:
            row.update({
                "delivered_pct_yr": fit["pct_yr"],
                "delivered_reduction_pct_yr": -fit["pct_yr"],
                "delivered_se": fit["se"], "delivered_se_boot": fit["se_boot"],
                "delivered_r2": fit["r2"], "delivered_n_years": fit["n_years"],
                "delivered_year_start": fit["year_start"], "delivered_year_end": fit["year_end"],
                "tonnes_first": fit["first"], "tonnes_last": fit["last"],
                "facility_count_start": facilities[t].get(fit["year_start"]),
                "facility_count_end": facilities[t].get(fit["year_end"]),
            })
            f0, f1 = row["facility_count_start"], row["facility_count_end"]
            drift = bool(f0 and f1 and abs(f1 - f0) / f0 > DRIFT_FLAG)
            stale = fit["year_end"] < last_ghgrp_year
            large = abs(fit["pct_yr"]) > 25
            flags = ([("perimeter_drift" if drift else None), ("stale" if stale else None),
                      ("large_rate" if large else None)])
            row["facility_set_changed"] = drift
            row["window_stale"] = stale
            row["trend_flags"] = "|".join(f for f in flags if f) or None
            row["headline_clean"] = not (drift or stale or large)
            # the most recent stable run, which is the headline window for most companies and a
            # later, shorter one for a company whose perimeter stepped partway through
            runs = [r for r in clean_windows(ghgrp[t], facilities.get(t)) if len(r) >= MIN_YEARS]
            rfit = loglinear_fit(runs[-1]) if runs else None
            if rfit:
                row["delivered_recent_pct_yr"] = rfit["pct_yr"]
                row["delivered_recent_n_years"] = rfit["n_years"]
                row["delivered_recent_year_start"] = rfit["year_start"]
                row["delivered_recent_year_end"] = rfit["year_end"]
            # and from the company's own target baseline forward, which is the like-for-like window
            by = row.get("promised_baseline_year")
            if by:
                sub = [pt for pt in win if pt[0] >= by]
                bfit = loglinear_fit(sub)
                if bfit:
                    row["delivered_from_baseline_pct_yr"] = bfit["pct_yr"]
                    row["delivered_from_baseline_n_years"] = bfit["n_years"]
                    row["delivered_from_baseline_year_start"] = bfit["year_start"]
        elif t in ghgrp and any(pd.notna(v) and v > 0 for _, v in ghgrp[t]):
            row["delivered_short_n_years"] = len(longest_clean_window(ghgrp[t], facilities.get(t)))

        # delivered, intensity, tonnes per $M revenue
        ifit, _ = fit_for(intensity, t, "int", facilities.get(t))
        if ifit:
            row.update({
                "delivered_int_pct_yr": ifit["pct_yr"],
                "delivered_int_reduction_pct_yr": -ifit["pct_yr"],
                "delivered_int_se": ifit["se"], "delivered_int_r2": ifit["r2"],
                "delivered_int_n_years": ifit["n_years"],
                "delivered_int_year_start": ifit["year_start"],
                "delivered_int_year_end": ifit["year_end"],
                "intensity_first_t_per_musd": ifit["first"],
                "intensity_last_t_per_musd": ifit["last"],
            })

        # delivered, CAMD stack monitors, the only feed that runs past 2023
        cfit, _ = fit_for(camd, t, "camd", camd_facilities.get(t))
        if cfit:
            row.update({
                "delivered_camd_pct_yr": cfit["pct_yr"], "delivered_camd_se": cfit["se"],
                "delivered_camd_r2": cfit["r2"], "delivered_camd_n_years": cfit["n_years"],
                "delivered_camd_year_start": cfit["year_start"],
                "delivered_camd_year_end": cfit["year_end"],
            })

        # the gap
        d = row.get("delivered_pct_yr", np.nan)
        p = row["promised_pct_yr"]
        row["gap_pct_yr"] = (d - p) if (np.isfinite(d if d is not None else np.nan)
                                        and np.isfinite(p)) else np.nan
        di = row.get("delivered_int_pct_yr", np.nan)
        row["gap_intensity_pct_yr"] = (di - p) if (np.isfinite(di if di is not None else np.nan)
                                                   and np.isfinite(p)) else np.nan
        row["has_both"] = bool(np.isfinite(row["gap_pct_yr"]))
        row["gap_status"] = None if not row["has_both"] else (
            "missing" if row["gap_pct_yr"] > 0 else "beating")
        pw = row["wba_promised_pct_yr"]
        row["gap_wba_pct_yr"] = (d - pw) if (np.isfinite(d if d is not None else np.nan)
                                             and np.isfinite(pw)) else np.nan
        db = row.get("delivered_from_baseline_pct_yr", np.nan)
        row["gap_from_baseline_pct_yr"] = (db - p) if (
            db is not None and np.isfinite(db if db is not None else np.nan)
            and np.isfinite(p)) else np.nan
        row["chart_state"] = (
            "plotted" if row["has_both"]
            else "promise_only" if np.isfinite(p)
            else "trend_only" if fit else "neither")

        pdq = row.get("promised_dq")
        ddq = 1 if fit else None  # GHGRP tonnage carries dq 1 in emissions_by_ticker
        dqs = [v for v in (pdq, ddq) if v is not None]
        row["dq"] = max(dqs) if dqs else 5
        # the subset that goes on a slide: a same-basis comparison, an explicit numeric target and a
        # trend nobody can wave away as an acquisition
        row["slide_safe"] = bool(row["has_both"] and row.get("headline_clean")
                                 and (pdq is not None and pdq <= 2))
        row["scope1_tonnes_latest"] = row.get("tonnes_last", np.nan)
        r = rev_by.get(t, {})
        row["revenue_latest_musd"] = (r[max(r)] / 1e6) if r else np.nan
        row["market_cap_usd"] = mc.get(t, np.nan)
        row["seed"] = SEED
        rows.append(row)

    out = pd.DataFrame(rows)
    for c in ["promised_dq", "promised_baseline_year", "promised_target_year",
              "delivered_n_years", "delivered_year_start", "delivered_year_end",
              "facility_count_start", "facility_count_end", "delivered_recent_n_years",
              "delivered_recent_year_start", "delivered_int_n_years", "delivered_int_year_start",
              "delivered_int_year_end", "delivered_camd_n_years", "delivered_camd_year_start",
              "delivered_camd_year_end", "delivered_short_n_years", "dq",
              "delivered_from_baseline_n_years", "delivered_from_baseline_year_start",
              "delivered_recent_year_end"]:
        if c in out.columns:
            out[c] = out[c].astype("Int64")
    for c in ["facility_set_changed", "promised_capped_at_netzero", "window_stale",
              "headline_clean"]:
        if c in out.columns:
            out[c] = out[c].fillna(False).astype(bool)

    # ---------------------------------------------------------------- what it says
    prim = out[out.is_primary_listing]
    n_prom = int(prim.promised_pct_yr.notna().sum())
    n_trend = int(prim.delivered_pct_yr.notna().sum())
    n_both = int(prim.has_both.sum())
    print()
    print(f"promise, numeric: {n_prom}/500 companies")
    print(f"measured trend, GHGRP scope 1, >= {MIN_YEARS} clean consecutive years: {n_trend}/500")
    print(f"BOTH, the size of the headline: {n_both}/500 companies")
    short = prim.delivered_short_n_years.dropna() if "delivered_short_n_years" in prim else pd.Series(dtype=float)
    print(f"dropped for a window under {MIN_YEARS} years: {len(short)} "
          f"({dict(short.value_counts().sort_index()) if len(short) else 'none'})")
    print(f"listings with a mandatory tonnage but no usable trend: "
          f"{int((prim.has_mandatory & prim.delivered_pct_yr.isna()).sum())}")
    print("chart states (primary listings): " + str(dict(prim.chart_state.value_counts())))

    both = prim[prim.has_both]
    miss = both[both.gap_pct_yr > 0]
    beat = both[both.gap_pct_yr <= 0]
    print()
    print(f"missing their promise: {len(miss)} of {len(both)} ({100*len(miss)/len(both):.1f}%)")
    print(f"beating it:           {len(beat)} of {len(both)} ({100*len(beat)/len(both):.1f}%)")
    print(f"median gap {both.gap_pct_yr.median():+.2f} pp/yr, "
          f"mean {both.gap_pct_yr.mean():+.2f}, "
          f"IQR {both.gap_pct_yr.quantile(.25):+.2f} to {both.gap_pct_yr.quantile(.75):+.2f}")
    print(f"median promised cut {both.promised_reduction_pct_yr.median():.2f}%/yr, "
          f"median delivered cut {both.delivered_reduction_pct_yr.median():.2f}%/yr")
    print(f"emissions actually rising over the window: "
          f"{int((both.delivered_pct_yr > 0).sum())} of {len(both)}")
    sig = both[(both.delivered_se.notna()) & (both.gap_pct_yr.abs() > 2 * both.delivered_se)]
    print(f"gap larger than twice the trend SE: {len(sig)} of {len(both)}")
    print(f"median R2 of the fitted trend {both.delivered_r2.median():.3f}, "
          f"median n_years {both.delivered_n_years.median()}, "
          f"median OLS SE {both.delivered_se.median():.2f} vs bootstrap "
          f"{both.delivered_se_boot.median():.2f}")

    print()
    print("trend flags on the plotted set: " + str(dict(both.trend_flags.fillna("none").value_counts())))
    clean = both[both.headline_clean]
    print(f"flag-free plotted companies: {len(clean)} of {len(both)}, "
          f"median gap {clean.gap_pct_yr.median():+.2f} pp/yr, "
          f"{int((clean.gap_pct_yr > 0).sum())} missing "
          f"({100 * (clean.gap_pct_yr > 0).mean():.1f}%), "
          f"{int((clean.delivered_pct_yr > 0).sum())} with rising emissions")
    fb = both[both.delivered_from_baseline_pct_yr.notna()]
    if len(fb):
        print(f"refitted from each company's own target baseline year ({len(fb)} companies have "
              f"{MIN_YEARS}+ measured years since theirs): median gap "
              f"{fb.gap_from_baseline_pct_yr.median():+.2f} pp/yr against "
              f"{fb.gap_pct_yr.median():+.2f} on the full window, "
              f"{int((fb.gap_from_baseline_pct_yr > 0).sum())} of {len(fb)} missing")
    print(f"refitted on each company's most recent stable window: median gap "
          f"{(both.delivered_recent_pct_yr - both.promised_pct_yr).median():+.2f} pp/yr, "
          f"{int(((both.delivered_recent_pct_yr - both.promised_pct_yr) > 0).sum())} of "
          f"{len(both)} missing, median window length "
          f"{both.delivered_recent_n_years.median()} years")
    safe = both[both.slide_safe]
    print(f"slide-safe subset, flag-free trend and an explicit numeric target: {len(safe)} "
          f"companies, {int((safe.gap_pct_yr > 0).sum())} missing "
          f"({100 * (safe.gap_pct_yr > 0).mean():.1f}%), median gap "
          f"{safe.gap_pct_yr.median():+.2f} pp/yr, median promised cut "
          f"{safe.promised_reduction_pct_yr.median():.2f}%/yr against delivered "
          f"{safe.delivered_reduction_pct_yr.median():.2f}%/yr")

    print()
    print("worst 12 by gap (delivered minus promised, pp/yr, positive is worse):")
    print("  (flag-free companies only are quoted on the slide; trend_flags says why)")
    cols = ["ticker", "company", "gics_sector", "promised_reduction_pct_yr",
            "delivered_reduction_pct_yr", "gap_pct_yr", "delivered_r2", "delivered_n_years",
            "delivered_year_start", "delivered_year_end", "delivered_int_reduction_pct_yr",
            "trend_flags"]
    print(both.sort_values("gap_pct_yr", ascending=False).head(12)[cols].to_string(index=False))
    print()
    print("best 8 by gap:")
    print(both.sort_values("gap_pct_yr").head(8)[cols].to_string(index=False))
    print()
    print("slide-safe worst 12, the list to actually put on the slide:")
    print(safe.sort_values("gap_pct_yr", ascending=False).head(12)[cols].to_string(index=False))
    print()
    print("slide-safe best 6:")
    print(safe.sort_values("gap_pct_yr").head(6)[cols].to_string(index=False))

    # absolute against intensity: the ranking moves, and by how much
    bi = both[both.delivered_int_pct_yr.notna()]
    if len(bi) > 3:
        rho = bi[["delivered_pct_yr", "delivered_int_pct_yr"]].corr(method="spearman").iloc[0, 1]
        flip = bi[(bi.delivered_pct_yr > 0) & (bi.delivered_int_pct_yr < 0)]
        print()
        print(f"absolute vs intensity on {len(bi)} companies: Spearman rho {rho:.3f}")
        print(f"  absolute emissions RISING while intensity FALLS: {len(flip)} companies "
              f"({', '.join(sorted(flip.ticker)[:12])})")
        print(f"  median intensity cut {bi.delivered_int_reduction_pct_yr.median():.2f}%/yr against "
              f"median absolute cut {bi.delivered_reduction_pct_yr.median():.2f}%/yr")
        print(f"  companies whose gap changes sign between the two bases: "
              f"{int(((bi.gap_pct_yr > 0) != (bi.gap_intensity_pct_yr > 0)).sum())}")

    # promise quality, because an inferred net-zero rate is not a disclosure
    print()
    print("promise basis on the plotted set: " + str(dict(both.promised_source.value_counts())))
    print("promise dq on the plotted set: " + str(dict(both.promised_dq.value_counts().sort_index())))
    strict = both[both.promised_dq <= 2]
    print(f"plotted on an explicit numeric target only (dq <= 2): {len(strict)}, "
          f"median gap {strict.gap_pct_yr.median():+.2f} pp/yr, "
          f"{int((strict.gap_pct_yr > 0).sum())} missing")

    # the second source of the promise, kept in its own columns and never merged into the headline
    ws = prim[prim.promised_pct_yr.notna() & prim.wba_promised_pct_yr.notna()]
    if len(ws) > 3:
        rho = ws[["promised_reduction_pct_yr", "wba_promised_reduction_pct_yr"]].corr("spearman").iloc[0, 1]
        diff = (ws.wba_promised_reduction_pct_yr - ws.promised_reduction_pct_yr).abs()
        print()
        print(f"second promise source, WBA, on {len(ws)} companies that also carry ours: "
              f"Spearman {rho:.3f}, {int((diff <= 1).sum())} agree within 1 pp/yr, "
              f"median absolute difference {diff.median():.3f} pp/yr")
        extra = prim[prim.promised_pct_yr.isna() & prim.wba_promised_pct_yr.notna()]
        print(f"  WBA carries a rate for {len(extra)} companies ours does not, "
              f"{int(extra.delivered_pct_yr.notna().sum())} of them with a measured trend. "
              f"Not merged: the headline stays at {n_both}, and gap_wba_pct_yr is a separate column")

    print()
    print("by sector, plotted companies, median gap pp/yr:")
    bysec = both.groupby("gics_sector").agg(n=("ticker", "size"),
                                            median_gap=("gap_pct_yr", "median"),
                                            missing=("gap_status", lambda s: (s == "missing").sum()))
    print(bysec.sort_values("median_gap", ascending=False).to_string())

    # perimeter, the first caveat: how much of a company's own global scope 1 the EPA stack sees
    cross = s23[(s23.scope == "1") & s23.ghgrp_crosscheck_ratio.notna() & (~s23.magnitude_suspect)]
    if len(cross):
        per = cross.groupby("ticker").ghgrp_crosscheck_ratio.median()
        print()
        print(f"perimeter check on {len(per)} companies that also publish a global scope 1: "
              f"median GHGRP / self-reported ratio {per.median():.2f} "
              f"(IQR {per.quantile(.25):.2f} to {per.quantile(.75):.2f}). "
              f"The spread is wide and the voluntary side is unaudited, so this sizes the perimeter "
              f"question rather than answering it.")

    # ---------------------------------------------------------------- the chart
    # labels come from the slide-safe set: a name nobody can dispute beats a famous name whose
    # trend carries a flag
    plotted = both.copy()
    pool = safe if len(safe) >= 10 else plotted
    by_cap = pool.sort_values("market_cap_usd", ascending=False).ticker.tolist()[:8]
    by_tonnes = pool.sort_values("scope1_tonnes_latest", ascending=False).ticker.tolist()[:4]
    labels, seen = [], set()
    for t in by_cap + by_tonnes:
        if t not in seen:
            seen.add(t)
            labels.append(t)
    labels = labels[:10]
    print()
    print(f"labelled on the chart: {', '.join(labels)} "
          f"(drawn from the {'slide-safe' if len(safe) >= 10 else 'plotted'} set)")

    def drop_nulls(d):
        # the 273 unmeasurable listings carry mostly nulls and the site has to ship this file. A
        # NaN left in here is not valid JSON and JSON.parse would reject the whole file, so string
        # columns get the same treatment as numeric ones.
        keep = {}
        for k, v in d.items():
            if k == "t":
                keep[k] = v
                continue
            if v is None or v is False:
                continue
            if isinstance(v, float) and not np.isfinite(v):
                continue
            if not isinstance(v, (str, bool, int, list, dict)) and pd.isna(v):
                continue
            keep[k] = v
        return keep

    def jnum(v, nd=3):
        if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
            return None
        return round(float(v), nd)

    companies = []
    for _, r in out.iterrows():
        companies.append(drop_nulls({
            "t": r.ticker, "n": r.company, "s": r.gics_sector,
            "tier": r.coverage_tier, "state": r.chart_state,
            "primary": bool(r.is_primary_listing),
            "promised": jnum(r.promised_pct_yr), "promised_src": r.promised_source,
            "delivered": jnum(r.delivered_pct_yr), "se": jnum(r.delivered_se),
            "r2": jnum(r.delivered_r2),
            "n_years": None if pd.isna(r.delivered_n_years) else int(r.delivered_n_years),
            "y0": None if pd.isna(r.delivered_year_start) else int(r.delivered_year_start),
            "y1": None if pd.isna(r.delivered_year_end) else int(r.delivered_year_end),
            "gap": jnum(r.gap_pct_yr), "gap_wba": jnum(r.gap_wba_pct_yr),
            "promised_wba": jnum(r.wba_promised_pct_yr),
            "delivered_int": jnum(r.delivered_int_pct_yr),
            "gap_int": jnum(r.gap_intensity_pct_yr),
            "recent": jnum(r.get("delivered_recent_pct_yr")),
            "from_baseline": jnum(r.get("delivered_from_baseline_pct_yr")),
            "flags": r.get("trend_flags"),
            "clean": bool(r.get("headline_clean")) if pd.notna(r.get("headline_clean")) else False,
            "safe": bool(r.slide_safe),
            "tonnes": None if pd.isna(r.scope1_tonnes_latest) else int(round(r.scope1_tonnes_latest)),
            "mcap_busd": jnum(r.market_cap_usd / 1e9 if pd.notna(r.market_cap_usd) else None, 1),
            "dq": None if pd.isna(r.dq) else int(r.dq),
            "label": r.ticker in labels,
        }))

    pad = 1.0
    xs = plotted.promised_pct_yr
    ys = plotted.delivered_pct_yr
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seed": SEED,
            "n_listings": len(out),
            "n_companies": int(out.is_primary_listing.sum()),
            "n_promise": n_prom, "n_trend": n_trend, "n_both": n_both,
            "row_encoding": "keys that are null or false are omitted from a company row",
            "min_years": MIN_YEARS,
            "promised_source": "targets_company.parquet, provenance_class voluntary "
                               "(the company's own target), strongest scope 1+2 absolute target",
            "delivered_source": "emissions_by_ticker.parquet, EPA GHGRP scope 1, provenance_class "
                                "mandatory, log-linear fit over the longest clean window",
            "sign_convention": "percent per year CHANGE in emissions. Negative is falling. "
                               "gap = delivered - promised, so positive means emitting more than "
                               "the promised path.",
            "intensity_basis": "tCO2e per $M of company revenue, nominal USD (the company term in "
                               "PCAF WACI). Absolute scope 1 tonnes is not a cross-company "
                               "benchmarking metric under PCAF, which is why both are shown.",
            "caveats": [
                "GHGRP covers US facilities above 25,000 tCO2e. A target is usually global and "
                "covers scope 1+2, so the measured trend and the promise do not share a boundary.",
                "GHGRP has no 2024 or 2025 data; reporting year 2025 is due 30 October 2026.",
                "Revenue is nominal, so the intensity trend carries price inflation.",
                "Index membership is today's, applied to history, which skews the trend energy-light.",
                "A window breaks on a perimeter step; gradual drift survives and is named in flags. "
                "Quote the flag-free subset.",
            ],
        },
        "chart": {
            "x": "promised", "y": "delivered",
            "unit": "% per year change in scope 1 emissions",
            "x_label": "Promised: implied annual change from the company's own target",
            "y_label": "Delivered: fitted annual change in measured EPA scope 1",
            "reference_line": {"type": "identity", "label": "kept the promise"},
            "above_line": "emitting more than promised",
            "below_line": "cutting faster than promised",
            "domain": {
                "x": [jnum(xs.min() - pad, 1), jnum(xs.max() + pad, 1)],
                "y": [jnum(ys.min() - pad, 1), jnum(ys.max() + pad, 1)],
            },
            "size_by": "tonnes", "color_by": "tier",
            "grey_states": ["promise_only", "trend_only", "neither"],
            "label_tickers": labels,
        },
        "stats": {
            "n_plotted": len(both),
            "missing": int(len(miss)), "beating": int(len(beat)),
            "median_gap_pct_yr": jnum(both.gap_pct_yr.median(), 2),
            "median_promised_cut_pct_yr": jnum(both.promised_reduction_pct_yr.median(), 2),
            "median_delivered_cut_pct_yr": jnum(both.delivered_reduction_pct_yr.median(), 2),
            "rising_absolute": int((both.delivered_pct_yr > 0).sum()),
            "n_plotted_clean": int(len(clean)),
            "missing_clean": int((clean.gap_pct_yr > 0).sum()),
            "median_gap_pct_yr_clean": jnum(clean.gap_pct_yr.median(), 2),
            "n_slide_safe": int(len(safe)),
            "missing_slide_safe": int((safe.gap_pct_yr > 0).sum()),
            "median_gap_pct_yr_slide_safe": jnum(safe.gap_pct_yr.median(), 2),
            "tier_counts": {k: int(v) for k, v in
                            out[out.is_primary_listing].coverage_tier.value_counts().items()},
        },
        "companies": companies,
    }

    SITE.mkdir(parents=True, exist_ok=True)
    out_parquet = INTERIM / "say_do_gap.parquet"
    out.to_parquet(out_parquet, index=False)
    out_json = SITE / "say_do.json"
    out_json.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False))
    print()
    print(f"wrote {out_parquet} {len(out)} rows x {len(out.columns)} columns")
    print(f"wrote {out_json} {out_json.stat().st_size / 1024:.1f} KB, seed {SEED}")


if __name__ == "__main__":
    main()
