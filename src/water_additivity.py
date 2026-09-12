"""Does water exposure tell us anything carbon does not?

Reads data/interim/water_by_ticker.parquet (from src/fetch_aqueduct.py) and tests it against the
carbon intensity, the composite rank and the vendor ESG consensus we already have. A new indicator
only earns a slide if it is not a restatement of one we already show.

Writes docs/water_risk.md and site/data/water.json.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
RAW = ROOT / "data" / "raw"
DOCS = ROOT / "docs"
SITE = ROOT / "site" / "data"

# The headline water metric. A share of facilities, not a mean of an index, because a share is the
# number a person can check: count the plants, count the ones in a stressed basin, divide.
WATER = "share_facilities_high_water_stress"

# Floor for anything that goes on a slide. Below this the denominator does the talking.
MIN_FAC = 5


def spearman(x, y):
    """Spearman with the pairwise-complete n, which is the n that has to be reported."""
    d = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(d) < 5:
        return {"rho": np.nan, "p": np.nan, "n": len(d)}
    rho, p = stats.spearmanr(d.x, d.y)
    return {"rho": float(rho), "p": float(p), "n": int(len(d))}


def fmt(r):
    return f"rho = {r['rho']:+.3f}, p = {r['p']:.3g}, n = {r['n']}"


def load():
    w = pd.read_parquet(INTERIM / "water_by_ticker.parquet")
    sc = pd.read_parquet(INTERIM / "scores.parquet")
    keep = ["ticker", "rank_median", "our_percentile", "vendor_percentile", "coverage_tier",
            "intensity_t_per_musd", "scope1_tonnes", "revenue_musd", "market_cap",
            "pillar_physical", "pillar_credibility", "pillar_exposure", "pillar_conduct",
            "gics_sub_industry"]
    d = w.merge(sc[keep], on="ticker", how="left")
    print(f"water_by_ticker: {len(w)} tickers, merged to scores: "
          f"{d.rank_median.notna().sum()} with a composite rank")

    # Everything is a percentile inside the 142 so the two axes are comparable. 100 is the worse
    # end on both, because a slide that says "top right is bad" is the one people read correctly.
    d["carbon_pct"] = d["intensity_t_per_musd"].rank(pct=True) * 100
    d["water_pct"] = d[WATER].rank(pct=True) * 100
    d["log_intensity"] = np.log10(d["intensity_t_per_musd"].clip(lower=1e-4))
    d["log_scope1"] = np.log10(d["scope1_tonnes"].clip(lower=1.0))
    return d, sc


def correlations(d):
    """Test 1. If water restates carbon these come back strong. If not, it is new information."""
    big = d[d.n_facilities_with_bws >= MIN_FAC]
    out = {}

    out["water_vs_carbon_intensity"] = spearman(d[WATER], d["log_intensity"])
    out["water_vs_carbon_intensity_min5"] = spearman(big[WATER], big["log_intensity"])
    out["water_vs_scope1_absolute"] = spearman(d[WATER], d["log_scope1"])
    out["water_vs_our_percentile"] = spearman(d[WATER], d["our_percentile"])
    out["water_vs_rank_median"] = spearman(d[WATER], d["rank_median"])
    out["water_vs_vendor_percentile"] = spearman(d[WATER], d["vendor_percentile"])
    out["water_vs_pillar_physical"] = spearman(d[WATER], d["pillar_physical"])
    out["water_vs_market_cap"] = spearman(d[WATER], np.log10(d["market_cap"]))

    # The alternative water metrics, to check the answer is not an artefact of picking a share.
    out["mean_bws_vs_carbon_intensity"] = spearman(d["mean_bws_score"], d["log_intensity"])
    out["co2w_bws_vs_carbon_intensity"] = spearman(d["co2w_bws_score"], d["log_intensity"])
    out["exhigh_vs_carbon_intensity"] = spearman(
        d["share_facilities_extremely_high_water_stress"], d["log_intensity"])
    out["groundwater_vs_carbon_intensity"] = spearman(
        d["share_facilities_groundwater_declining"], d["log_intensity"])

    # Within sector. If the only link between water and carbon is that both are concentrated in
    # utilities and energy, it disappears when we take the sector out.
    s = d.dropna(subset=[WATER, "log_intensity"]).copy()
    s["w_res"] = s.groupby("gics_sector")[WATER].transform(lambda x: x.rank(pct=True) - 0.5)
    s["c_res"] = s.groupby("gics_sector")["log_intensity"].transform(
        lambda x: x.rank(pct=True) - 0.5)
    out["water_vs_carbon_within_sector"] = spearman(s["w_res"], s["c_res"])

    # How much of the water ranking does carbon explain. Spearman squared is the honest version.
    r = out["water_vs_carbon_intensity"]
    out["variance_of_water_rank_explained_by_carbon_rank"] = float(r["rho"] ** 2)

    print("\ncorrelations")
    for k, v in out.items():
        if isinstance(v, dict):
            print(f"  {k:48s} {fmt(v)}")
        else:
            print(f"  {k:48s} {v:.4f}")
    return out


def sector_pattern(d):
    """Test 2. Same sectors, or different ones?"""
    g = d.groupby("gics_sector").agg(
        n_companies=("ticker", "size"),
        n_facilities=("n_facilities_with_bws", "sum"),
        median_share_high=(WATER, "median"),
        mean_share_high=(WATER, "mean"),
        median_share_exhigh=("share_facilities_extremely_high_water_stress", "median"),
        median_intensity=("intensity_t_per_musd", "median"),
        median_carbon_pct=("carbon_pct", "median"),
        median_water_pct=("water_pct", "median"),
    ).sort_values("median_share_high", ascending=False)
    g["water_minus_carbon_pct"] = g["median_water_pct"] - g["median_carbon_pct"]
    print("\nsector pattern (median percentile within the 142 scored companies)")
    print(g.round(3).to_string())

    # Sub-industry is where the interesting cases live. Semiconductors and beverages are inside
    # Information Technology and Consumer Staples and get averaged away at sector level.
    sub = d[d.gics_sub_industry.notna()].groupby("gics_sub_industry").agg(
        n=("ticker", "size"),
        n_fac=("n_facilities_with_bws", "sum"),
        share_high=(WATER, "mean"),
        med_intensity=("intensity_t_per_musd", "median"),
        med_carbon_pct=("carbon_pct", "median"),
        med_water_pct=("water_pct", "median"),
    )
    sub = sub[sub.n >= 2].sort_values("share_high", ascending=False)
    print("\nsub-industries with 2 or more scored companies, top 20 by water exposure")
    print(sub.head(20).round(3).to_string())
    return g, sub


def quadrants(d):
    """Test 3. The named examples. Clean on carbon and exposed on water, and the reverse."""
    q = d[(d.n_facilities_with_bws >= MIN_FAC)
          & d.carbon_pct.notna() & d.water_pct.notna()].copy()
    q["gap"] = q["water_pct"] - q["carbon_pct"]

    clean_carbon_dirty_water = q[(q.carbon_pct <= 50) & (q.water_pct >= 70)].sort_values(
        "gap", ascending=False)
    dirty_carbon_clean_water = q[(q.carbon_pct >= 70) & (q.water_pct <= 40)].sort_values("gap")

    cols = ["ticker", "company_name", "gics_sector", "n_facilities_with_bws",
            "intensity_t_per_musd", "carbon_pct", WATER,
            "share_facilities_extremely_high_water_stress", "water_pct", "gap"]
    print(f"\nclean on carbon, exposed on water (n = {len(clean_carbon_dirty_water)}, "
          f"floor {MIN_FAC} facilities)")
    print(clean_carbon_dirty_water[cols].round(3).to_string(index=False))
    print(f"\nheavy on carbon, unexposed on water (n = {len(dirty_carbon_clean_water)})")
    print(dirty_carbon_clean_water[cols].round(3).to_string(index=False))

    # Below the floor as well, flagged, because AVGO and QCOM are the sharpest examples in the
    # whole dataset and hiding them would be worse than showing the denominator.
    small = d[(d.n_facilities_with_bws < MIN_FAC) & (d.carbon_pct <= 50)
              & (d[WATER] >= 0.99)].sort_values("intensity_t_per_musd")
    print(f"\nsame pattern below the {MIN_FAC}-facility floor, quote with the denominator")
    print(small[cols[:-1]].round(3).to_string(index=False))
    return clean_carbon_dirty_water, dirty_carbon_clean_water, small, q


def facility_examples(d):
    """Where the named examples physically are. A slide claim needs a place name behind it."""
    wf = pd.read_parquet(INTERIM / "water_facility.parquet")
    fac = pd.read_parquet(INTERIM / "ghgrp_facilities.parquet")
    pmap = pd.read_parquet(INTERIM / "parent_ticker_map.parquet")[
        ["parent_name_clean", "ticker"]].dropna().drop_duplicates()
    fleet = fac[fac.year == 2023][["facility_id", "parent_name_clean", "co2e_tonnes_share"]]
    fleet = fleet.dropna(subset=["parent_name_clean"]).drop_duplicates(
        subset=["facility_id", "parent_name_clean"])
    link = fleet.merge(pmap, on="parent_name_clean", how="inner")
    link = link.merge(wf, on="facility_id", how="left", suffixes=("", "_wf"))
    print(f"\nfacility-ticker links rebuilt: {len(link):,} rows, "
          f"{link.ticker.nunique()} tickers, {link.facility_id.nunique():,} facilities")
    return link


def say_do(d):
    """Test 4. Do companies that talk about water actually sit in less stressed basins?

    Two independent sources for the talk, both weak in their own way, so both are reported.
    """
    res = {}

    # (a) What WBA collected. If the voluntary disclosure infrastructure carried water at all, it
    # would be here. Counting it is the point, even when the count is small.
    src = pd.read_parquet(INTERIM / "wba_sources.parquet")
    wmask = src.source_name.str.contains("water", case=False, na=False)
    res["wba_sources_total"] = int(len(src))
    res["wba_sources_water_named"] = int(wmask.sum())
    res["wba_water_source_names"] = (
        src.loc[wmask, "source_name"].value_counts().to_dict())
    res["wba_water_source_tickers"] = sorted(src.loc[wmask, "ticker"].unique().tolist())
    print(f"\nWBA voluntary sources: {len(src):,} documents, "
          f"{int(wmask.sum())} with water in the title")
    print("  ", res["wba_water_source_names"])

    # (b) The companies' own sustainability report text. Lemmatised and stopword-stripped, so
    # bigrams like "water stewardship" survive and can be counted.
    corp = pd.read_csv(RAW / "kaggle_esg" / "preprocessed_content.csv",
                       usecols=["ticker", "year", "preprocessed_content"])
    corp = corp.dropna(subset=["ticker", "preprocessed_content"])
    corp = corp.sort_values("year").groupby("ticker", as_index=False).last()
    terms = ["water stewardship", "water stress", "water scarcity", "water risk",
             "water security", "water conservation", "water management", "water withdrawal",
             "water recycle", "water reuse", "water intensity", "water efficiency",
             "water consumption", "water footprint", "watershed", "water neutral",
             "water positive", "water replenish", "water use"]
    pat = re.compile("|".join(re.escape(t) for t in terms))
    corp["n_tokens"] = corp.preprocessed_content.str.count(r"\S+")
    corp["water_tokens"] = corp.preprocessed_content.str.count(r"\bwater\b")
    corp["steward_hits"] = corp.preprocessed_content.apply(lambda s: len(pat.findall(s)))
    corp["water_per_10k"] = corp.water_tokens / corp.n_tokens * 1e4
    corp["steward_per_10k"] = corp.steward_hits / corp.n_tokens * 1e4

    t = d.merge(corp[["ticker", "year", "n_tokens", "water_tokens", "steward_hits",
                      "water_per_10k", "steward_per_10k"]], on="ticker", how="inner")
    t = t[t[WATER].notna()]
    res["report_corpus_n"] = int(len(t))
    res["report_corpus_years"] = [int(t.year.min()), int(t.year.max())]
    print(f"\nsustainability report corpus: {len(corp)} companies, "
          f"{len(t)} of them have a water score, report years "
          f"{int(t.year.min())} to {int(t.year.max())}")

    res["talk_vs_exposure"] = spearman(t["water_per_10k"], t[WATER])
    res["steward_vs_exposure"] = spearman(t["steward_per_10k"], t[WATER])
    res["talk_vs_carbon_intensity"] = spearman(t["water_per_10k"], t["log_intensity"])
    big = t[t.n_facilities_with_bws >= MIN_FAC]
    res["talk_vs_exposure_min5"] = spearman(big["water_per_10k"], big[WATER])
    res["n_min5"] = int(len(big))

    # Split at the median so the claim can be stated as two group means rather than a rho.
    med = t.water_per_10k.median()
    loud, quiet = t[t.water_per_10k > med], t[t.water_per_10k <= med]
    u, pu = stats.mannwhitneyu(loud[WATER], quiet[WATER], alternative="two-sided")
    res["talkers"] = {"n": int(len(loud)), "mean_share_high": float(loud[WATER].mean()),
                      "median_share_high": float(loud[WATER].median()),
                      "median_water_per_10k": float(loud.water_per_10k.median())}
    res["quiet"] = {"n": int(len(quiet)), "mean_share_high": float(quiet[WATER].mean()),
                    "median_share_high": float(quiet[WATER].median()),
                    "median_water_per_10k": float(quiet.water_per_10k.median())}
    res["mannwhitney_p"] = float(pu)
    print(f"  talk vs exposure            {fmt(res['talk_vs_exposure'])}")
    print(f"  stewardship bigrams vs exp  {fmt(res['steward_vs_exposure'])}")
    print(f"  talk vs carbon intensity    {fmt(res['talk_vs_carbon_intensity'])}")
    print(f"  above-median talkers: n={len(loud)} mean exposure "
          f"{loud[WATER].mean():.3f}; below-median: n={len(quiet)} mean "
          f"{quiet[WATER].mean():.3f}; Mann-Whitney p = {pu:.3g}")

    # (c) The vendor SDG 6 flag. Vendor-coded, not filed, so it is reported as a vendor opinion.
    g = pd.read_csv(RAW / "kaggle_esg" / "Global Corporate ESG and Financial Dataset.csv",
                    sep=";", low_memory=False)
    col = "sdg.Clean Water and Sanitation"
    sdg = g.loc[g[col].notna(), ["ticker", col]].drop_duplicates(subset="ticker")
    sdg["sdg6_aligned"] = sdg[col].isin(["Aligned", "Strongly Aligned"])
    v = d.merge(sdg[["ticker", col, "sdg6_aligned"]], on="ticker", how="inner")
    v = v[v[WATER].notna()]
    a, na = v[v.sdg6_aligned], v[~v.sdg6_aligned]
    ua, pa = stats.mannwhitneyu(a[WATER], na[WATER], alternative="two-sided")
    res["sdg6"] = {
        "n": int(len(v)),
        "aligned_n": int(len(a)), "aligned_mean_share_high": float(a[WATER].mean()),
        "not_aligned_n": int(len(na)), "not_aligned_mean_share_high": float(na[WATER].mean()),
        "mannwhitney_p": float(pa),
        "spearman_vs_exposure": spearman(v.sdg6_aligned.astype(float), v[WATER]),
    }
    print(f"  vendor SDG 6 flag: aligned n={len(a)} mean exposure {a[WATER].mean():.3f}; "
          f"not aligned n={len(na)} mean {na[WATER].mean():.3f}; p = {pa:.3g}")
    return res, t, v


def rank_impact(d, sc):
    """Test 5. What a fifth pillar would actually do to the ranking, and to the 361 no-data names."""
    pil = ["pillar_physical", "pillar_credibility", "pillar_exposure", "pillar_conduct"]
    s = sc[["ticker", "company_name", "gics_sector"] + pil].copy()

    # Water as a pillar on the same orientation as the others: 1 is good, 0 is bad.
    wp = d[["ticker", WATER, "n_facilities_with_bws"]].copy()
    wp["pillar_water"] = 1.0 - wp[WATER].rank(pct=True)
    s = s.merge(wp[["ticker", "pillar_water", "n_facilities_with_bws"]], on="ticker", how="left")

    s["score4"] = s[pil].mean(axis=1)
    s["rank4"] = s["score4"].rank(ascending=False)

    # (a) Missing water treated as the median, which is what a pillar quietly does to a company
    # with no US reporting facility.
    s["score5_median"] = s[pil + ["pillar_water"]].apply(
        lambda r: np.nanmean([r[p] for p in pil] + [r.pillar_water if pd.notna(r.pillar_water)
                                                    else 0.5]), axis=1)
    s["rank5_median"] = s["score5_median"].rank(ascending=False)

    # (b) Missing water renormalised away, the other defensible choice, which gives a different
    # answer for the same company. Showing both is the argument.
    s["score5_renorm"] = s[pil + ["pillar_water"]].mean(axis=1, skipna=True)
    s["rank5_renorm"] = s["score5_renorm"].rank(ascending=False)

    s["shift_median"] = s["rank5_median"] - s["rank4"]
    s["shift_renorm"] = s["rank5_renorm"] - s["rank4"]
    s["treatment_disagreement"] = (s["rank5_median"] - s["rank5_renorm"]).abs()

    has = s["pillar_water"].notna()
    cov = int(has.sum())
    out = {
        "tickers_total": int(len(s)),
        "tickers_with_water": int(cov),
        "coverage_pct": float(cov / len(s) * 100),
        "spearman_rank4_vs_rank5_median": spearman(s.rank4, s.rank5_median),
        "spearman_rank4_vs_rank5_renorm": spearman(s.rank4, s.rank5_renorm),
        "median_abs_shift_median_fill": float(s.shift_median.abs().median()),
        "p90_abs_shift_median_fill": float(s.shift_median.abs().quantile(0.9)),
        "max_abs_shift_median_fill": float(s.shift_median.abs().max()),
        "median_abs_shift_renorm": float(s.shift_renorm.abs().median()),
        "p90_abs_shift_renorm": float(s.shift_renorm.abs().quantile(0.9)),
        "median_treatment_disagreement": float(s.treatment_disagreement.median()),
        "p90_treatment_disagreement": float(s.treatment_disagreement.quantile(0.9)),
        "max_treatment_disagreement": float(s.treatment_disagreement.max()),
        "n_moving_more_than_50": int((s.shift_median.abs() > 50).sum()),
        "covered_median_abs_shift": float(s.loc[has, "shift_median"].abs().median()),
        "covered_p90_abs_shift": float(s.loc[has, "shift_median"].abs().quantile(0.9)),
        "covered_max_abs_shift": float(s.loc[has, "shift_median"].abs().max()),
        "uncovered_median_abs_shift": float(s.loc[~has, "shift_median"].abs().median()),
        "uncovered_p90_abs_shift": float(s.loc[~has, "shift_median"].abs().quantile(0.9)),
        "uncovered_max_abs_shift": float(s.loc[~has, "shift_median"].abs().max()),
        "uncovered_n_moving_more_than_50": int((s.loc[~has, "shift_median"].abs() > 50).sum()),
        "covered_n_moving_more_than_50": int((s.loc[has, "shift_median"].abs() > 50).sum()),
        "scores_identical_under_both_treatments_for_covered": bool(
            np.allclose(s.loc[has, "score5_median"], s.loc[has, "score5_renorm"])),
    }
    print(f"\nfifth-pillar simulation, {cov} of {len(s)} tickers have a water score "
          f"({cov / len(s) * 100:.1f}%)")
    print(f"  4-pillar vs 5-pillar (missing = median): {fmt(out['spearman_rank4_vs_rank5_median'])}")
    print(f"  4-pillar vs 5-pillar (missing renormalised): "
          f"{fmt(out['spearman_rank4_vs_rank5_renorm'])}")
    print(f"  median absolute rank shift {out['median_abs_shift_median_fill']:.0f}, "
          f"p90 {out['p90_abs_shift_median_fill']:.0f}, "
          f"max {out['max_abs_shift_median_fill']:.0f}")
    print(f"  the two missing-data treatments disagree by a median of "
          f"{out['median_treatment_disagreement']:.0f} rank places, p90 "
          f"{out['p90_treatment_disagreement']:.0f}, max {out['max_treatment_disagreement']:.0f}")
    print(f"  {out['n_moving_more_than_50']} companies move more than 50 places: "
          f"{out['covered_n_moving_more_than_50']} of the {cov} with a water score, "
          f"{out['uncovered_n_moving_more_than_50']} of the {len(s) - cov} without one")
    print(f"  covered companies: median shift {out['covered_median_abs_shift']:.0f}, "
          f"p90 {out['covered_p90_abs_shift']:.0f}, max {out['covered_max_abs_shift']:.0f}")
    print(f"  uncovered companies: median shift {out['uncovered_median_abs_shift']:.0f}, "
          f"p90 {out['uncovered_p90_abs_shift']:.0f}, max {out['uncovered_max_abs_shift']:.0f}")
    print(f"  the 5-pillar score is identical under both missing-data treatments for every "
          f"company that has a water score: {out['scores_identical_under_both_treatments_for_covered']}. "
          f"The rank gap is purely the 361 uncovered names moving past them.")
    biggest = s.reindex(s.treatment_disagreement.sort_values(ascending=False).index).head(8)
    print("\n  companies where the missing-data choice alone moves the rank most")
    print(biggest[["ticker", "company_name", "n_facilities_with_bws", "rank4",
                   "rank5_median", "rank5_renorm", "treatment_disagreement"]].round(0
          ).to_string(index=False))
    return out, s


def write_json(d, corr, sec, sub, sd, ri, link):
    SITE.mkdir(parents=True, exist_ok=True)
    cols = {
        "ticker": "ticker", "company_name": "name", "gics_sector": "sector",
        "n_facilities_with_bws": "n_fac",
        WATER: "share_high", "share_facilities_extremely_high_water_stress": "share_exhigh",
        "share_facilities_arid_low_water_use": "share_arid",
        "mean_bws_score": "mean_bws", "co2w_bws_score": "co2w_bws",
        "share_co2e_high_water_stress": "share_co2e_high",
        "share_facilities_groundwater_declining": "gw_decline",
        "share_facilities_high_water_stress_bau2030": "share_high_2030",
        "share_facilities_high_water_stress_bau2050": "share_high_2050",
        "delta_share_high_water_stress_bau2050": "delta_2050",
        "intensity_t_per_musd": "carbon_intensity",
        "carbon_pct": "carbon_pct", "water_pct": "water_pct",
        "scope1_tonnes": "scope1_t", "co2e_tonnes_equity": "co2e_equity",
        "rank_median": "rank_median", "vendor_percentile": "vendor_pct",
    }
    comp = d[list(cols)].rename(columns=cols)
    for c in comp.columns:
        if comp[c].dtype.kind == "f":
            comp[c] = comp[c].round(4)
    companies = json.loads(comp.to_json(orient="records"))

    # Facility points so the interface can draw the map. Coordinates to 4 decimals is about 11 m,
    # far finer than a basin, and it halves the file.
    f = link[link.bws_cat.notna() & link.lat.notna()].copy()
    f = f.drop_duplicates(subset=["facility_id", "ticker"])
    f["co2e_tonnes_share"] = f["co2e_tonnes_share"].fillna(0.0)
    pts = [{"t": r.ticker, "y": round(float(r.lat), 4), "x": round(float(r.lon), 4),
            "c": int(r.bws_cat), "e": int(round(float(r.co2e_tonnes_share)))}
           for r in f.itertuples()]

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "WRI Aqueduct 4.0 baseline annual, July 2023 release",
            "licence": "CC BY 4.0, attribution to World Resources Institute",
            "provenance_class": "modelled",
            "joined_to": "EPA GHGRP facility coordinates, fleet year 2023",
            "water_metric": "share of a company's GHGRP facilities in a basin WRI classes High "
                            "(40-80%) or Extremely High (>80%) baseline water stress",
            "bws_cat": {"-1": "Arid and Low Water Use", "0": "Low", "1": "Low-Medium",
                        "2": "Medium-High", "3": "High", "4": "Extremely High"},
            "coverage": {"tickers_scored": int(len(d)), "tickers_in_index": ri["tickers_total"],
                         "coverage_pct": round(ri["coverage_pct"], 1),
                         "note": "GHGRP is US-only. A company with no US reporting facility has "
                                 "no water score and must be shown as no data, never as low risk."},
        },
        "summary": {
            "correlations": corr,
            "say_do": sd,
            "fifth_pillar_simulation": ri,
            "sectors": json.loads(sec.reset_index().round(4).to_json(orient="records")),
            "sub_industries": json.loads(
                sub.reset_index().head(25).round(4).to_json(orient="records")),
        },
        "companies": companies,
        "facilities": pts,
    }
    p = SITE / "water.json"
    p.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"\nwrote {p} ({p.stat().st_size / 1024:.0f} KB), "
          f"{len(companies)} companies, {len(pts):,} facility points")
    return payload


def main():
    d, sc = load()
    corr = correlations(d)
    sec, sub = sector_pattern(d)
    clean, dirty, small, q = quadrants(d)
    link = facility_examples(d)
    sd, talk, sdgv = say_do(d)
    ri, ranks = rank_impact(d, sc)
    write_json(d, corr, sec, sub, sd, ri, link)

    # Everything the write-up quotes gets dumped so the markdown can be checked against the run.
    out = ROOT / "data" / "interim" / "water_additivity_dump.json"
    out.write_text(json.dumps({
        "clean_carbon_dirty_water": json.loads(clean.round(4).to_json(orient="records")),
        "dirty_carbon_clean_water": json.loads(dirty.round(4).to_json(orient="records")),
        "below_floor": json.loads(small.round(4).to_json(orient="records")),
    }, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
