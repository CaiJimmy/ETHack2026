"""Validation of the derived layers against each other, and the coverage table.

Four questions, all answered from tables already on disk:
  1 how far apart the ESG vendors are on our own universe, by rank correlation
  2 how well the GICS exclusion proxy reproduces the vendor and filing screens
  3 how much a US-only emissions spine understates the index
  4 what every layer actually covers out of 503 listings

Writes three small tables the slides read, plus a JSON of every number quoted in
docs/coverage_and_validation.md so no figure in that document is typed by hand.
"""

import json
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
OUT = {}


def load(name):
    df = pd.read_parquet(INTERIM / f"{name}.parquet")
    print(f"  read {name:34s} {len(df):>7,} rows")
    return df


def kappa(a, b):
    """Cohen's kappa for two boolean labellings. Returns nan when it is undefined,
    which happens when one rater flags nothing and agreement is trivially perfect."""
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    n = len(a)
    if n == 0:
        return np.nan
    po = (a == b).mean()
    pe = (a.mean() * b.mean()) + ((1 - a.mean()) * (1 - b.mean()))
    if np.isclose(pe, 1.0):
        return np.nan
    return (po - pe) / (1 - pe)


def confusion(gics, other):
    g = np.asarray(gics, dtype=bool)
    o = np.asarray(other, dtype=bool)
    tp = int((g & o).sum())
    fp = int((g & ~o).sum())
    fn = int((~g & o).sum())
    tn = int((~g & ~o).sum())
    prec = tp / (tp + fp) if (tp + fp) else np.nan
    rec = tp / (tp + fn) if (tp + fn) else np.nan
    f1 = 2 * prec * rec / (prec + rec) if (tp + fp) and (tp + fn) and (prec + rec) else np.nan
    return dict(n=len(g), tp=tp, fp=fp, fn=fn, tn=tn, precision=prec, recall=rec,
                f1=f1, kappa=kappa(g, o))


# ----------------------------------------------------------------------------
# question 1: how much do the vendors disagree
# ----------------------------------------------------------------------------

def question1(vendor, consensus, universe, emissions, financials):
    print("\n" + "=" * 92)
    print("Q1  vendor rank correlation on the S&P 500")
    print("=" * 92)

    primary = set(universe.loc[universe.is_primary_listing, "ticker"])
    res = {}
    matrices = []

    for metric in ["esg_total", "esg_e"]:
        sub = vendor[(vendor.metric == metric) & (vendor.ticker.isin(primary))].copy()
        # direction is +1 when a high number means good and -1 for a risk scale,
        # so multiplying puts every source on one axis before ranking
        sub["oriented"] = sub["value"] * sub["direction"]
        wide = sub.pivot_table(index="ticker", columns="source_dataset", values="oriented")
        sources = sorted(wide.columns)
        print(f"\n{metric}: {len(wide)} companies, {len(sources)} sources")
        print("  per-source n: " + ", ".join(f"{s} {wide[s].notna().sum()}" for s in sources))

        rho = pd.DataFrame(np.nan, index=sources, columns=sources)
        npair = pd.DataFrame(0, index=sources, columns=sources)
        rows = []
        for a, b in combinations(sources, 2):
            both = wide[[a, b]].dropna()
            n = len(both)
            npair.loc[a, b] = npair.loc[b, a] = n
            if n >= 20:
                r = spearmanr(both[a], both[b]).statistic
                rho.loc[a, b] = rho.loc[b, a] = r
            else:
                r = np.nan
            rows.append(dict(metric=metric, source_a=a, source_b=b, n=n, spearman_rho=r,
                             ai_in_pair=bool(vendor.loc[vendor.source_dataset.isin([a, b]),
                                                        "ai_generated"].any())))
        for s in sources:
            rho.loc[s, s] = 1.0
            npair.loc[s, s] = int(wide[s].notna().sum())
        matrices.append(pd.DataFrame(rows))

        print("\n  Spearman rho (n below the diagonal)")
        disp = rho.round(3).astype(object)
        for a in sources:
            for b in sources:
                if sources.index(a) > sources.index(b):
                    disp.loc[a, b] = f"n={npair.loc[a, b]}"
        print(disp.to_string())

        pairs = pd.DataFrame(rows).dropna(subset=["spearman_rho"])
        res[metric] = dict(
            n_companies=int(len(wide)),
            n_sources=len(sources),
            n_pairs=int(len(pairs)),
            rho_min=float(pairs.spearman_rho.min()),
            rho_max=float(pairs.spearman_rho.max()),
            rho_median=float(pairs.spearman_rho.median()),
            n_min=int(pairs.n.min()),
            n_max=int(pairs.n.max()),
        )
        print(f"\n  {len(pairs)} pairs, rho from {pairs.spearman_rho.min():.3f} to "
              f"{pairs.spearman_rho.max():.3f}, median {pairs.spearman_rho.median():.3f}, "
              f"n from {pairs.n.min()} to {pairs.n.max()}")

    corr = pd.concat(matrices, ignore_index=True)

    # three of the six sources are re-uploads of one dead Yahoo pull, so the raw
    # matrix is not six independent raters. Split the pairs on that.
    tot = corr[corr.metric == "esg_total"].copy()
    LINEAGE = {"pritish509": "yahoo_sustainalytics", "rikinzala": "yahoo_sustainalytics",
               "flamingmasamune": "yahoo_sustainalytics", "alistairking": "esg_enterprise",
               "mrbossjaysrb": "refinitiv_like", "mashinii": "llm_generated"}
    tot["lineage_a"] = tot.source_a.map(LINEAGE)
    tot["lineage_b"] = tot.source_b.map(LINEAGE)
    tot["same_lineage"] = tot.lineage_a == tot.lineage_b
    corr["lineage_a"] = corr.source_a.map(LINEAGE)
    corr["lineage_b"] = corr.source_b.map(LINEAGE)
    corr["same_lineage"] = corr.lineage_a == corr.lineage_b

    same = tot[tot.same_lineage]
    cross = tot[~tot.same_lineage]
    cross_real = cross[~cross.ai_in_pair]
    print("\n  same-lineage pairs (re-uploads of one source, not independent raters):")
    print(same[["source_a", "source_b", "n", "spearman_rho"]].to_string(index=False))
    print("\n  cross-lineage pairs, the only ones that test rater disagreement:")
    print(cross[["source_a", "source_b", "n", "spearman_rho", "ai_in_pair"]].to_string(index=False))

    res["lineage"] = dict(
        same_lineage_min=float(same.spearman_rho.min()),
        same_lineage_max=float(same.spearman_rho.max()),
        n_same=int(len(same)),
        cross_lineage_min=float(cross.spearman_rho.min()),
        cross_lineage_max=float(cross.spearman_rho.max()),
        n_cross=int(len(cross)),
        cross_excl_ai_min=float(cross_real.spearman_rho.min()),
        cross_excl_ai_max=float(cross_real.spearman_rho.max()),
        n_cross_excl_ai=int(len(cross_real)),
    )
    print(f"\n  same lineage  {len(same)} pairs, rho {same.spearman_rho.min():.3f} to "
          f"{same.spearman_rho.max():.3f}")
    print(f"  cross lineage {len(cross)} pairs, rho {cross.spearman_rho.min():.3f} to "
          f"{cross.spearman_rho.max():.3f}")
    print(f"  cross lineage without the AI-generated source, {len(cross_real)} pairs, rho "
          f"{cross_real.spearman_rho.min():.3f} to {cross_real.spearman_rho.max():.3f}")

    # alistairking measures something else entirely (see the write-up), so report the
    # range with and without it rather than letting one source set the headline
    no_ak = cross[(cross.source_a != "alistairking") & (cross.source_b != "alistairking")]
    print(f"\n  cross lineage without alistairking, {len(no_ak)} pairs, rho "
          f"{no_ak.spearman_rho.min():.3f} to {no_ak.spearman_rho.max():.3f}, median "
          f"{no_ak.spearman_rho.median():.3f}")
    res["lineage"].update(cross_excl_alistairking_min=float(no_ak.spearman_rho.min()),
                          cross_excl_alistairking_max=float(no_ak.spearman_rho.max()),
                          cross_excl_alistairking_median=float(no_ak.spearman_rho.median()),
                          n_cross_excl_alistairking=int(len(no_ak)))

    # Berg, Koelbel and Rigobon report 0.38 to 0.71 across six commercial raters
    bkr_lo, bkr_hi = 0.38, 0.71
    inside = cross[(cross.spearman_rho >= bkr_lo) & (cross.spearman_rho <= bkr_hi)]
    res["bkr"] = dict(
        band_lo=bkr_lo, band_hi=bkr_hi,
        cross_pairs_inside=int(len(inside)),
        cross_pairs_total=int(len(cross)),
        cross_pairs_below=int((cross.spearman_rho < bkr_lo).sum()),
        cross_pairs_above=int((cross.spearman_rho > bkr_hi).sum()),
    )
    print(f"\n  against Berg, Koelbel and Rigobon's 0.38 to 0.71: {len(inside)} of {len(cross)} "
          f"cross-lineage pairs fall inside, {(cross.spearman_rho < bkr_lo).sum()} below, "
          f"{(cross.spearman_rho > bkr_hi).sum()} above")

    # the practical consequence: how far apart do the sources put one company
    cons = consensus.copy()
    pct_cols = [c for c in cons.columns if c.startswith("pct_")]
    cons["spread_pp"] = cons[pct_cols].max(axis=1) - cons[pct_cols].min(axis=1)
    cons["n_pct"] = cons[pct_cols].notna().sum(axis=1)
    wide3 = cons[cons.n_pct >= 3].copy()
    res["spread"] = dict(
        n=int(len(wide3)),
        median_pp=float(wide3.spread_pp.median()),
        p90_pp=float(wide3.spread_pp.quantile(0.90)),
        n_over_50pp=int((wide3.spread_pp > 50).sum()),
        share_over_50pp=float((wide3.spread_pp > 50).mean()),
    )
    print(f"\n  percentile spread across sources, {len(wide3)} companies rated by at least 3: "
          f"median {wide3.spread_pp.median():.1f} pp, 90th percentile "
          f"{wide3.spread_pp.quantile(0.90):.1f} pp, {(wide3.spread_pp > 50).sum()} companies "
          f"({(wide3.spread_pp > 50).mean() * 100:.0f}%) span more than 50 percentile points")
    worst = wide3.nlargest(10, "spread_pp")[["ticker", "spread_pp", "n_pct", "vendor_percentile"]]
    print("\n  widest disagreements:")
    print(worst.to_string(index=False))
    res["spread"]["worst"] = [
        dict(ticker=r.ticker, spread_pp=round(float(r.spread_pp), 1), n_sources=int(r.n_pct))
        for r in worst.itertuples()]

    # the version a portfolio manager feels: one source calls it a leader, another a laggard
    flip = wide3[(wide3[pct_cols].max(axis=1) >= 75) & (wide3[pct_cols].min(axis=1) <= 25)]
    print(f"\n  {len(flip)} of {len(wide3)} companies ({len(flip) / len(wide3) * 100:.0f}%) sit in "
          f"the top quartile on one source and the bottom quartile on another")
    res["spread"]["n_quartile_flip"] = int(len(flip))
    res["spread"]["share_quartile_flip"] = float(len(flip) / len(wide3))

    # and the question that matters for us: does the vendor consensus track the
    # emissions we can actually measure
    e23 = emissions[(emissions.year == 2023) & emissions.scope1_ghgrp_tonnes.notna()
                    & emissions.is_primary_listing]
    f23 = financials[(financials.fy == 2023) & financials.is_primary_listing][["ticker", "revenue"]]
    m = (e23[["ticker", "scope1_ghgrp_tonnes"]].merge(f23, on="ticker")
         .merge(cons[["ticker", "vendor_percentile"]], on="ticker"))
    # a nan anywhere makes spearmanr return nan for the whole vector, so drop first
    m = m.dropna(subset=["revenue", "scope1_ghgrp_tonnes", "vendor_percentile"])
    m = m[(m.revenue > 0) & (m.scope1_ghgrp_tonnes > 0)]
    m["intensity"] = m.scope1_ghgrp_tonnes / (m.revenue / 1e6)
    r_int = spearmanr(m.vendor_percentile, m.intensity)
    r_abs = spearmanr(m.vendor_percentile, m.scope1_ghgrp_tonnes)
    print(f"\n  vendor consensus percentile against our measured 2023 Scope 1, n={len(m)}: "
          f"intensity rho {r_int.statistic:+.3f} (p={r_int.pvalue:.3f}), "
          f"absolute tonnes rho {r_abs.statistic:+.3f} (p={r_abs.pvalue:.3f})")
    res["vs_measured"] = dict(n=int(len(m)),
                              rho_intensity=float(r_int.statistic),
                              p_intensity=float(r_int.pvalue),
                              rho_absolute=float(r_abs.statistic),
                              p_absolute=float(r_abs.pvalue))
    return corr, res


# ----------------------------------------------------------------------------
# question 2: how good is the GICS exclusion proxy
# ----------------------------------------------------------------------------

def question2(rev, universe):
    print("\n" + "=" * 92)
    print("Q2  GICS exclusion proxy against every independent screen")
    print("=" * 92)

    p = rev[rev.is_primary_listing].copy()
    comparators = [("flag_vendor", "vendor"), ("flag_sec", "sec_segment"), ("flag_nbim", "nbim")]
    rows, res = [], {}

    for rule_id, grp in p.groupby("rule_id"):
        article = grp.article.iloc[0]
        print(f"\n{article}  {rule_id}   threshold "
              f"{grp.threshold_pct.iloc[0] if pd.notna(grp.threshold_pct.iloc[0]) else 'n/a'}")
        res[rule_id] = dict(article=article, comparators={})
        for col, label in comparators:
            both = grp[grp.flag_gics.notna() & grp[col].notna()]
            if len(both) == 0:
                print(f"  vs {label:11s} no overlap, {label} covers "
                      f"{int(grp[col].notna().sum())} of 500 and GICS covers "
                      f"{int(grp.flag_gics.notna().sum())}")
                res[rule_id]["comparators"][label] = dict(n=0)
                rows.append(dict(rule_id=rule_id, article=article, comparator=label, n=0))
                continue
            c = confusion(both.flag_gics.astype(bool), both[col].astype(bool))
            fp_names = sorted(both.loc[both.flag_gics.astype(bool) & ~both[col].astype(bool),
                                       "ticker"])
            fn_names = sorted(both.loc[~both.flag_gics.astype(bool) & both[col].astype(bool),
                                       "ticker"])
            print(f"  vs {label:11s} n={c['n']:3d}  tp={c['tp']:2d} fp={c['fp']:2d} "
                  f"fn={c['fn']:2d} tn={c['tn']:3d}  precision="
                  f"{c['precision'] if pd.notna(c['precision']) else float('nan'):.3f}  recall="
                  f"{c['recall'] if pd.notna(c['recall']) else float('nan'):.3f}  kappa="
                  f"{c['kappa'] if pd.notna(c['kappa']) else float('nan'):.3f}")
            if fp_names:
                print(f"     GICS flags, {label} does not: {', '.join(fp_names)}")
            if fn_names:
                print(f"     {label} flags, GICS does not: {', '.join(fn_names)}")
            agree_names = sorted(both.loc[both.flag_gics.astype(bool) & both[col].astype(bool),
                                          "ticker"])
            if agree_names:
                print(f"     both flag: {', '.join(agree_names)}")
            rec = dict(rule_id=rule_id, article=article, comparator=label, **c,
                       both_flag=",".join(agree_names),
                       gics_only=",".join(fp_names), comparator_only=",".join(fn_names))
            rows.append(rec)
            res[rule_id]["comparators"][label] = dict(
                {k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in c.items()},
                both_flag=agree_names, gics_only=fp_names, comparator_only=fn_names)

    val = pd.DataFrame(rows)

    # the overall picture, pooling every rule where two screens both spoke
    pooled = []
    for col, label in comparators:
        both = p[p.flag_gics.notna() & p[col].notna()]
        if len(both):
            c = confusion(both.flag_gics.astype(bool), both[col].astype(bool))
            pooled.append(dict(comparator=label, **c))
            print(f"\npooled over all rules, GICS vs {label}: n={c['n']}, precision="
                  f"{c['precision']:.3f}, recall={c['recall']:.3f}, kappa={c['kappa']:.3f}")
    res["pooled"] = pooled

    # the screens other than GICS, checked against each other, so the reader can
    # tell a bad proxy from a rule three sources genuinely read differently
    print("\nthe non-GICS screens against each other, where both spoke:")
    for (ca, la), (cb, lb) in [(("flag_sec", "sec_segment"), ("flag_nbim", "nbim")),
                               (("flag_sec", "sec_segment"), ("flag_vendor", "vendor")),
                               (("flag_nbim", "nbim"), ("flag_vendor", "vendor"))]:
        for rule_id, grp in p.groupby("rule_id"):
            both = grp[grp[ca].notna() & grp[cb].notna()]
            if len(both) == 0:
                continue
            c = confusion(both[ca].astype(bool), both[cb].astype(bool))
            print(f"  {rule_id:36s} {la:11s} vs {lb:11s} n={c['n']:3d} "
                  f"kappa={c['kappa'] if pd.notna(c['kappa']) else float('nan'):.3f} "
                  f"({la} flags {int(both[ca].sum())}, {lb} flags {int(both[cb].sum())})")
            res.setdefault("cross_screen", []).append(
                dict(rule_id=rule_id, a=la, b=lb, n=c["n"],
                     kappa=None if pd.isna(c["kappa"]) else float(c["kappa"]),
                     a_flags=int(both[ca].sum()), b_flags=int(both[cb].sum())))

    # what the proxy decides on its own, which is where the risk sits
    decided = p.groupby("flag_basis").size().to_dict()
    gics_decides = p[(p.flag_basis == "gics_proxy") & p.flag_best]
    print(f"\nrows decided by each source: {decided}")
    print(f"exclusions the GICS proxy decides alone, with nothing to check it: {len(gics_decides)}")
    print(gics_decides[["ticker", "company_name", "rule_id", "gics_sub_industry"]].to_string(index=False))
    res["decided_by"] = {k: int(v) for k, v in decided.items()}
    res["gics_only_exclusions"] = [
        dict(ticker=r.ticker, rule=r.rule_id, sub_industry=r.gics_sub_industry)
        for r in gics_decides.itertuples()]

    # how many companies change status if we drop the proxy and use filings only
    n_excl_best = p.loc[p.flag_best, "ticker"].nunique()
    gics_only = p[p.flag_best & (p.flag_basis == "gics_proxy")].ticker.nunique()
    print(f"\ncompanies excluded on flag_best: {n_excl_best}; of those, "
          f"{gics_only} rest on the GICS proxy for at least one rule")
    res["n_excluded_best"] = int(n_excl_best)
    res["n_excluded_resting_on_gics"] = int(gics_only)
    return val, res


# ----------------------------------------------------------------------------
# question 3: how badly does US-only measurement bias us
# ----------------------------------------------------------------------------

def question3(nonus, ct, emissions, scope23):
    print("\n" + "=" * 92)
    print("Q3  US-only emissions bias, measured against Climate TRACE ownership")
    print("=" * 92)

    YEAR = 2023  # the last year GHGRP has published, so the only clean comparison
    y = nonus[(nonus.year == YEAR) & nonus.is_primary_listing].copy()
    print(f"{len(y)} tickers carry Climate TRACE assets in {YEAR}")

    MATERIAL = 250_000
    mat = y[y.ct_nonus_tonnes >= MATERIAL].copy()
    us_sum = mat.epa_us_scope1_tonnes.sum()
    nonus_sum = mat.ct_nonus_tonnes.sum()
    print(f"\n{len(mat)} companies hold at least {MATERIAL:,} t of Climate TRACE emissions abroad")
    print(f"  measured US Scope 1 over that set   {us_sum / 1e6:9.1f} MMT")
    print(f"  Climate TRACE non-US over that set  {nonus_sum / 1e6:9.1f} MMT")
    print(f"  our spine therefore sees {us_sum / (us_sum + nonus_sum) * 100:.0f}% of their "
          f"implied global Scope 1")

    res = dict(year=YEAR, n_with_assets=int(len(y)), material_threshold_t=MATERIAL,
               n_material=int(len(mat)),
               measured_us_mmt=float(us_sum / 1e6),
               ct_nonus_mmt=float(nonus_sum / 1e6),
               visible_share=float(us_sum / (us_sum + nonus_sum)))

    idx_2023 = emissions.loc[(emissions.year == 2023) & emissions.is_primary_listing,
                             "scope1_ghgrp_tonnes"].sum()
    print(f"\n  for scale: our mandatory spine measures {idx_2023 / 1e6:,.0f} MMT across the whole "
          f"index in {YEAR}. The foreign tonnes Climate TRACE attributes to these "
          f"{len(mat)} companies alone are {nonus_sum / idx_2023 * 100:.0f}% of that.")
    res["index_measured_mmt"] = float(idx_2023 / 1e6)
    res["nonus_as_share_of_index_measured"] = float(nonus_sum / idx_2023)

    # the oil and gas ownership layer names no US owner at all, so those non-US
    # shares are inflated by construction. Report the subset where it is honest.
    clean = mat[mat.ct_nonus_share_balanced.notna()].copy()
    blind = mat[mat.ct_nonus_share_balanced.isna()].copy()
    print(f"\n  of those {len(mat)}, {len(blind)} sit entirely in the subsectors where Climate "
          f"TRACE names no US owner ({', '.join(sorted(blind.ticker))})")
    bal_us = clean.epa_us_scope1_tonnes.sum()
    bal_nonus = clean.ct_nonus_tonnes_balanced.sum()
    print(f"  on the {len(clean)} where the ownership layer sees both sides: measured US "
          f"{bal_us / 1e6:.1f} MMT, non-US {bal_nonus / 1e6:.1f} MMT, "
          f"visible share {bal_us / (bal_us + bal_nonus) * 100:.0f}%")
    res.update(n_ownership_blind=int(len(blind)), blind_tickers=sorted(blind.ticker),
               n_balanced=int(len(clean)),
               balanced_us_mmt=float(bal_us / 1e6),
               balanced_nonus_mmt=float(bal_nonus / 1e6),
               balanced_visible_share=float(bal_us / (bal_us + bal_nonus)))

    cols = ["ticker", "company_name", "gics_sector", "epa_us_scope1_tonnes", "ct_nonus_tonnes",
            "nonus_multiple_of_epa_us", "ct_nonus_share", "ct_nonus_share_balanced",
            "nonus_country_count", "ct_us_vs_epa_us"]
    top = mat.sort_values("ct_nonus_tonnes", ascending=False)[cols]
    print("\n  every company with material foreign assets, largest first:")
    show = top.copy()
    show["epa_us_scope1_tonnes"] /= 1e6
    show["ct_nonus_tonnes"] /= 1e6
    print(show.rename(columns={"epa_us_scope1_tonnes": "us_mmt", "ct_nonus_tonnes": "nonus_mmt"})
          .round(3).to_string(index=False))
    res["table"] = [
        dict(ticker=r.ticker, name=r.company_name, sector=r.gics_sector,
             us_mmt=round(float(r.epa_us_scope1_tonnes) / 1e6, 2) if pd.notna(r.epa_us_scope1_tonnes) else None,
             nonus_mmt=round(float(r.ct_nonus_tonnes) / 1e6, 2),
             multiple=round(float(r.nonus_multiple_of_epa_us), 1) if pd.notna(r.nonus_multiple_of_epa_us) else None,
             nonus_share=round(float(r.ct_nonus_share), 3) if pd.notna(r.ct_nonus_share) else None,
             ownership_blind=bool(pd.isna(r.ct_nonus_share_balanced)))
        for r in top.itertuples()]

    # the headline list: names that look light on our spine only because the
    # plant is not in the United States
    LOOKS_CLEAN = 3.0
    hidden = mat[(mat.nonus_multiple_of_epa_us >= LOOKS_CLEAN)
                 | mat.epa_us_scope1_tonnes.isna()].copy()
    hidden["ownership_blind"] = hidden.ct_nonus_share_balanced.isna()
    hidden = hidden.sort_values("ct_nonus_tonnes", ascending=False)
    print(f"\n  looks clean in our data only because the assets are abroad "
          f"(non-US at least {LOOKS_CLEAN:.0f}x measured US, or no US filing at all):")
    h = hidden[["ticker", "company_name", "epa_us_scope1_tonnes", "ct_nonus_tonnes",
                "nonus_multiple_of_epa_us", "ownership_blind"]].copy()
    h["epa_us_scope1_tonnes"] /= 1e6
    h["ct_nonus_tonnes"] /= 1e6
    print(h.round(3).to_string(index=False))
    res["hidden"] = [
        dict(ticker=r.ticker, name=r.company_name,
             us_mmt=round(float(r.epa_us_scope1_tonnes) / 1e6, 3) if pd.notna(r.epa_us_scope1_tonnes) else None,
             nonus_mmt=round(float(r.ct_nonus_tonnes) / 1e6, 3),
             multiple=round(float(r.nonus_multiple_of_epa_us), 1) if pd.notna(r.nonus_multiple_of_epa_us) else None,
             ownership_blind=bool(r.ownership_blind))
        for r in hidden.itertuples()]

    # Climate TRACE's asset boundary is not the corporate Scope 1 boundary. Check it
    # wherever a company has also published a global figure of its own.
    s1 = scope23[(scope23.scope == "1") & scope23.tonnes_co2e.notna()
                 & ~scope23.magnitude_suspect]
    s1 = s1.sort_values("fy").groupby("ticker").tail(1)[["ticker", "fy", "tonnes_co2e"]]
    b = s1.merge(y[["ticker", "company_name", "ct_tonnes", "epa_us_scope1_tonnes"]], on="ticker")
    b["ct_over_reported"] = b.ct_tonnes / b.tonnes_co2e
    b = b.sort_values("ct_tonnes", ascending=False)
    print(f"\n  Climate TRACE total against the company's own published global Scope 1, "
          f"n={len(b)} overlaps:")
    bb = b.copy()
    bb["tonnes_co2e"] /= 1e6
    bb["ct_tonnes"] /= 1e6
    print(bb[["ticker", "company_name", "fy", "tonnes_co2e", "ct_tonnes",
              "ct_over_reported"]].round(2).to_string(index=False))
    res["boundary_check"] = dict(
        n=int(len(b)), median_ratio=float(b.ct_over_reported.median()),
        rows=[dict(ticker=r.ticker, fy=int(r.fy),
                   reported_mmt=round(float(r.tonnes_co2e) / 1e6, 2),
                   ct_mmt=round(float(r.ct_tonnes) / 1e6, 2),
                   ratio=round(float(r.ct_over_reported), 2)) for r in b.itertuples()])

    # and the validation that comes free: where Climate TRACE and EPA both see
    # the same US assets, do they agree
    v = y[(y.ct_us_tonnes > 1e6) & y.epa_us_scope1_tonnes.notna()].copy()
    ratio = v.ct_us_vs_epa_us.dropna()
    print(f"\n  Climate TRACE US over EPA measured US, n={len(ratio)} companies above 1 MMT: "
          f"median {ratio.median():.2f}, quartiles {ratio.quantile(0.25):.2f} to "
          f"{ratio.quantile(0.75):.2f}")
    res["us_agreement"] = dict(n=int(len(ratio)), median=float(ratio.median()),
                               q1=float(ratio.quantile(0.25)), q3=float(ratio.quantile(0.75)))

    # what fraction of the index this can say anything about at all
    idx_total = 503
    res["reach"] = dict(tickers_with_ct_assets=int(nonus.ticker.nunique()),
                        of_listings=idx_total,
                        share=float(nonus.ticker.nunique() / idx_total))
    print(f"\n  reach: Climate TRACE ownership names only {nonus.ticker.nunique()} of {idx_total} "
          f"listings, so for the rest the non-US question is untested, not answered")
    return res


# ----------------------------------------------------------------------------
# question 4: the honest coverage table
# ----------------------------------------------------------------------------

def question4(universe, emissions, scope23, rev, vendor, consensus, nonus, targets,
              violations, financials, market_cap, plant_ticker):
    print("\n" + "=" * 92)
    print("Q4  coverage by layer, out of 503 listings and 500 companies")
    print("=" * 92)

    N = len(universe)
    all_t = set(universe.ticker)
    primary = universe[universe.is_primary_listing]
    NP = len(primary)
    pset = set(primary.ticker)
    rows = []

    def add(layer, tickers, klass, can, cannot):
        t = set(tickers) & all_t
        rows.append(dict(layer=layer, n_listings=len(t), n_companies=len(t & pset),
                         of_listings=N, of_companies=NP,
                         pct_listings=round(100 * len(t) / N, 1),
                         provenance_class=klass, supports=can, does_not_support=cannot))

    add("Universe and identity", universe.ticker, "mandatory",
        "every join in the project, GICS logic, index weights",
        "nothing; all 503 agree with SEC on CIK")
    add("Financials, revenue any year", financials.loc[financials.revenue.notna(), "ticker"],
        "mandatory", "intensity denominators and earnings at risk",
        "segment revenue, which the companyfacts API drops entirely")
    add("Financials, operating income", financials.loc[financials.operating_income.notna(), "ticker"],
        "mandatory", "the earnings-at-risk numerator",
        "the 1 listing with no reported operating income line")
    add("Market cap and float", market_cap.loc[market_cap.market_cap.notna(), "ticker"],
        "mandatory", "portfolio weights and the PAB benchmark", "forward valuation")

    ghgrp_any = emissions.loc[emissions.scope1_ghgrp_tonnes.notna(), "ticker"]
    ghgrp_23 = emissions.loc[(emissions.year == 2023)
                             & (emissions.scope1_ghgrp_tonnes.fillna(0) > 0), "ticker"]
    matched = emissions.loc[emissions.covered, "ticker"]
    camd_any = emissions.loc[emissions.scope1_camd_tonnes.notna(), "ticker"]
    camd_25 = emissions.loc[(emissions.year == 2025)
                            & (emissions.scope1_camd_tonnes.fillna(0) > 0), "ticker"]
    add("Matched to a GHGRP facility", matched, "mandatory",
        "proof the entity resolution reached the company",
        "a tonnage on its own; 7 of these report none")
    add("Measured Scope 1, GHGRP, any year 2010-2023", ghgrp_any, "mandatory",
        "the headline score, promised versus delivered, facility attribution",
        "non-US emissions, sub-threshold facilities, 2024 onward")
    add("Measured Scope 1, GHGRP, 2023", ghgrp_23, "mandatory",
        "the current-year score", "the same limits, one year narrower")
    add("Measured power CO2, CAMD, any year", camd_any, "mandatory",
        "stack-monitored power CO2 and Article 12(1)(g) intensity", "anything outside power")
    add("Measured power CO2, CAMD, 2025", camd_25, "mandatory",
        "the only feed that is current", "non-power sectors, and 2026 is part-year")
    add("Plant-level intensity, gCO2e/kWh", plant_ticker, "mandatory",
        "the PAB 100 g/kWh electricity-producer test at plant resolution",
        "utilities whose generation sits in unconsolidated joint ventures")

    s1v = scope23[(scope23.scope == "1") & scope23.tonnes_co2e.notna()]
    s2 = scope23[scope23.scope.str.startswith("2_") & scope23.tonnes_co2e.notna()]
    s2loc = scope23[(scope23.scope == "2_location") & scope23.tonnes_co2e.notna()]
    s3 = scope23[(scope23.scope == "3_total") & scope23.tonnes_co2e.notna()]
    s3cat = scope23[scope23.scope.str.startswith("3_cat") & scope23.tonnes_co2e.notna()]
    fac = scope23[scope23.scope2_factor_g_per_kwh_hq_region.notna()]
    add("Voluntary Scope 1, extracted from reports", s1v.ticker, "voluntary",
        "a global cross-check on the US-only spine, to FY2022",
        "anything current or audited; 17 rows are order-of-magnitude suspect")
    add("Voluntary Scope 2, either basis", s2.ticker, "voluntary",
        "benchmarking the asset-light names GHGRP never sees",
        "index-wide Scope 2, or any year after 2022")
    add("Voluntary Scope 2, location basis", s2loc.ticker, "voluntary",
        "the grid comparison a market-based figure hides", "almost the whole index")
    add("Voluntary Scope 3 total", s3.ticker, "voluntary",
        "an order of magnitude for the value chain",
        "ranking; every filer draws the boundary differently")
    add("Voluntary Scope 3 by category", s3cat.ticker, "voluntary",
        "category structure on a handful of worked examples", "anything at index scale")
    add("Grid factor for HQ region, eGRID", fac.ticker, "modelled",
        "a Scope 2 estimate the moment a kWh number exists",
        "a tonnage by itself; per-company kWh is not free anywhere")

    add("PAB exclusions, Article 12(1)(a) to (f)", rev.ticker, "mandatory",
        "a decided flag for every company on every activity rule, with its basis",
        "12(1)(c) conduct, which no sector code can see")
    add("  decided on measured segment revenue", rev.loc[rev.flag_sec.notna(), "ticker"],
        "mandatory", "an actual revenue share against the article's own threshold",
        "filers whose 10-K carries no product or segment axis")
    add("  conduct rule 12(1)(c)", rev.loc[rev.rule_id == "pab_exclusion_ungc_oecd", "ticker"],
        "voluntary", "3 exclusions from one published institutional list",
        "a systematic norms review; absence here is untested, not clean")

    add("Climate targets, in NZT or SBTi", targets.loc[targets.in_nzt | targets.in_sbti, "ticker"],
        "voluntary", "whether a company has promised anything at all",
        "whether the promise is being kept")
    add("  with a numeric annual reduction rate",
        targets.loc[targets.promised_annual_reduction_pct.notna(), "ticker"], "voluntary",
        "promised versus delivered as a number", "companies whose target has no arithmetic in it")
    add("Regulatory penalties, non-zero", violations.loc[violations.penalty_usd_total > 0, "ticker"],
        "mandatory", "conduct evidence with a dollar figure; the other 35 are measured zero",
        "conduct outside the United States")

    add("Vendor ESG, any source", vendor.ticker, "vendor",
        "benchmarking our score, and the disagreement slide",
        "any input to our score; the schema forbids it")
    add("Vendor ESG, excluding the AI-generated source",
        vendor.loc[~vendor.ai_generated, "ticker"], "vendor",
        "the same benchmark without a language model in the loop", "the same limit")
    add("Vendor ESG consensus percentile", consensus.ticker, "vendor",
        "one comparable number per company", "a defensible ranking; its inputs disagree")

    add("Climate TRACE asset ownership", nonus.ticker, "modelled",
        "sizing the non-US gap for heavy industry, and validating EPA company by company",
        "the 430 listings with no heavy physical asset")

    cov = pd.DataFrame(rows)
    print(cov[["layer", "n_listings", "n_companies", "pct_listings", "provenance_class"]]
          .to_string(index=False))

    # the union question: how many listings carry a tonnage of any kind, from any source
    measured = set(ghgrp_any) | set(camd_any)
    voluntary = set(s1v.ticker) | set(s2.ticker) | set(s3.ticker)
    print(f"\nlistings with a measured mandatory tonnage: {len(measured & all_t)}")
    print(f"listings with a voluntary tonnage: {len(voluntary & all_t)}")
    print(f"listings with either: {len((measured | voluntary) & all_t)}")
    print(f"listings with neither, and no Climate TRACE asset either: "
          f"{len(all_t - measured - voluntary - set(nonus.ticker))}")
    extra = dict(n_mandatory=len(measured & all_t), n_voluntary=len(voluntary & all_t),
                 n_either=len((measured | voluntary) & all_t),
                 n_no_tonnage_anywhere=len(all_t - measured - voluntary - set(nonus.ticker)))
    return cov, extra


def main():
    print("loading")
    universe = load("universe")
    emissions = load("emissions_by_ticker")
    vendor = load("vendor_scores")
    consensus = load("esg_vendor_consensus")
    rev = load("revenue_exclusions")
    scope23 = load("scope23")
    ct = load("climatetrace_company")
    nonus = load("climatetrace_nonus_share")
    targets = load("targets_company")
    violations = load("violations_summary")
    financials = load("financials")
    market_cap = load("market_cap")

    corr, r1 = question1(vendor, consensus, universe, emissions, financials)
    val, r2 = question2(rev, universe)
    r3 = question3(nonus, ct, emissions, scope23)
    plant_ticker = emissions.loc[emissions.camd_facility_count > 0, "ticker"]
    cov, cov_extra = question4(universe, emissions, scope23, rev, vendor, consensus, nonus,
                               targets, violations, financials, market_cap, plant_ticker)

    corr["provenance_class"] = "vendor"
    corr.to_parquet(INTERIM / "vendor_rank_correlation.parquet", index=False)
    val.to_parquet(INTERIM / "gics_proxy_validation.parquet", index=False)
    cov.to_parquet(INTERIM / "coverage_summary.parquet", index=False)
    summary = dict(generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   vendor_disagreement=r1, gics_proxy=r2, nonus_bias=r3,
                   coverage=cov.to_dict(orient="records"), coverage_extra=cov_extra)
    (INTERIM / "validation_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nwrote vendor_rank_correlation.parquet {len(corr)} rows, "
          f"gics_proxy_validation.parquet {len(val)} rows, "
          f"coverage_summary.parquet {len(cov)} rows, validation_summary.json")


if __name__ == "__main__":
    main()
