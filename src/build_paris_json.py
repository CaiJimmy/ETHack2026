"""Build jimmy-website/public/data/paris.json.

The site fetches this alongside snapshot.json. It carries the Paris index: the exclusion
and intensity rules of EU Regulation 2020/1818 applied to the S&P 500.

Inputs, both already on disk:
  data/interim/pab_rules.json   the rules, parsed from EUR-Lex CELEX 32020R1818
  site/data/portfolio.json      the index, computed by src/portfolio.py

Nothing here recomputes the index. This script selects, renames and rounds, then checks the
numbers the site quotes against the file they came from and prints the result.

Standard library only, so it runs without the devshell.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_IN = os.path.join(ROOT, "data", "interim", "pab_rules.json")
PORT_IN = os.path.join(ROOT, "site", "data", "portfolio.json")
OUT = os.path.join(ROOT, "jimmy-website", "public", "data", "paris.json")

# The compliant variant is the Paris index. It is the only one that passes Articles 3, 9, 11
# and 12 at once; naive_exclusion drops the barred names but fails the Article 3 sector floor.
VARIANT = "pab_compliant"
AUM_USD = 1e9

# Article 12(1) in plain English. Every threshold number comes from pab_rules.json
# below, so none of them can drift from the regulation.
LABELS = {
    "Article 12(1)(a)": "Makers of cluster munitions, landmines and other banned weapons.",
    "Article 12(1)(b)": "Tobacco growers and manufacturers.",
    "Article 12(1)(c)": "Companies found in breach of the UN Global Compact or the OECD guidelines for multinationals.",
    "Article 12(1)(d)": "Coal. Barred at 1% of revenue.",
    "Article 12(1)(e)": "Oil fuels. Barred at 10% of revenue.",
    "Article 12(1)(f)": "Gaseous fuels. Barred at 50% of revenue.",
    "Article 12(1)(g)": "Power generation above 100 gCO2e per kWh, at 50% of revenue. Both legs have to hold.",
    "Article 12(2)": "Companies that do significant harm to an EU Taxonomy environmental objective.",
}

# Basis values that count as a number we can rank. sector_median_imputed is the sector median
# standing in for a company that files nothing, so it carries no information about that company.
SCORABLE_BASES = ("measured_mandatory", "ghgrp_threshold_bound")

SCORE_DEFINITION = (
    "Rank of a company's Scope 1 intensity inside its own GICS sector. 100 is the lowest "
    "intensity in the sector, 1 the highest. A company barred by Article 12 scores 0. A company "
    "that files no tonnage and carries its sector's median scores null."
)
SCORE_BOUND_NOTE = (
    "A company under the US mandatory reporting threshold is ranked on that threshold over its "
    "enterprise value, so the figure is a ceiling on its intensity."
)
SCORE_REFERENCE_NOTE = (
    "The ranking runs against every company in the sector that has a number, barred ones included, "
    "so the scale is the full spread of the sector."
)


def pct(x, nd=2):
    """Fraction to percent, rounded. None survives."""
    return None if x is None else round(x * 100.0, nd)


def rank_scores(companies):
    """paris_score per ticker. See SCORE_DEFINITION."""
    by_sector = {}
    for c in companies:
        if c["intensity_basis"] in SCORABLE_BASES and c["intensity"] is not None:
            by_sector.setdefault(c["sector"], []).append(c["intensity"])

    ranks = {}
    for sector, values in by_sector.items():
        values.sort()
        n = len(values)
        if n < 3:
            continue  # a rank with fewer than three names says nothing
        # Average rank for ties, so two identical intensities score the same.
        pos = {}
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[j + 1] == values[i]:
                j += 1
            pos[values[i]] = (i + j) / 2.0 + 1.0
            i = j + 1
        ranks[sector] = (pos, n)

    out = {}
    for c in companies:
        tk = c["ticker"]
        if c["excluded"]:
            out[tk] = 0
            continue
        if c["intensity_basis"] not in SCORABLE_BASES or c["intensity"] is None:
            out[tk] = None
            continue
        got = ranks.get(c["sector"])
        if got is None:
            out[tk] = None
            continue
        pos, n = got
        r = pos[c["intensity"]]
        score = 100.0 * (1.0 - (r - 1.0) / (n - 1.0))
        out[tk] = max(1, min(100, int(round(score))))  # 0 stays reserved for barred
    return out


def build():
    with open(RULES_IN) as fh:
        rules_src = json.load(fh)
    with open(PORT_IN) as fh:
        port = json.load(fh)

    reg = rules_src["regulation"]
    uni = port["universe"]
    exc = port["exclusions"]
    pf = port["portfolios"][VARIANT]
    companies = port["companies"]

    # ---------------------------------------------------------------- rules
    by_rule = exc["by_rule"]
    rules_out = []
    for r in rules_src["rules"]:
        art = r["article"]
        if not art.startswith("Article 12"):
            continue
        hit = next((v for v in by_rule.values() if v["article"] == art), None)
        p = r.get("parameters") or {}
        threshold = {}
        if "revenue_threshold_pct" in p:
            threshold["revenue_pct"] = p["revenue_threshold_pct"]
        if "intensity_threshold_gco2e_per_kwh" in p:
            threshold["g_per_kwh"] = p["intensity_threshold_gco2e_per_kwh"]
        rules_out.append({
            "article": art,
            "label": LABELS[art],
            "threshold": threshold or None,
            "tested": hit is not None,
            "n_barred": len(hit["names"]) if hit else 0,
            "cap_weight_pct": pct(hit["weight"]) if hit else 0.0,
            "tickers": sorted(hit["names"]) if hit else [],
            "quote": r["quote"],
        })
    rules_out.sort(key=lambda x: x["article"])

    n_rule_hits = sum(x["n_barred"] for x in rules_out)
    n_multi = n_rule_hits - exc["n_excluded"]

    # ---------------------------------------------------------------- moves
    active = sorted(companies, key=lambda c: c["w_pab"] - c["w_cap"])
    def move(c):
        return {
            "ticker": c["ticker"],
            "name": c["name"],
            "musd": round((c["w_pab"] - c["w_cap"]) * AUM_USD / 1e6, 1),
        }
    cuts = [move(c) for c in active[:8]]
    adds = [move(c) for c in active[::-1][:8]]

    # ------------------------------------------------------------ companies
    scores = rank_scores(companies)
    comp_out = {}
    for c in companies:
        tk = c["ticker"]
        arts = c["excl_articles"]
        comp_out[tk] = {
            "in_paris": not c["excluded"],
            "barred_by": arts.split(";")[0] if arts else None,
            "paris_score": scores[tk],
            "w_cap_pct": pct(c["w_cap"], 4),
            "w_paris_pct": pct(c["w_pab"], 4),
        }
    n_scored = sum(1 for v in comp_out.values() if v["paris_score"] is not None)

    # ----------------------------------------------------------------- meta
    te = pf["tracking_error"]
    dec = pf["decomposition"]
    realloc = abs(dec["reallocation"]) / abs(dec["total"])
    required = port["thresholds"]["pab_baseline_reduction"]["min_reduction_vs_universe_pct"]

    meta = {
        "what": ("The exclusion and intensity rules of EU Regulation 2020/1818 for Paris-aligned "
                 "Benchmarks, applied by us to the S&P 500."),
        "celex": reg["celex"],
        "regulation_title": reg["title"],
        "regulation_retrieved": reg["retrieved_at"],
        "rules_read_from": "data/interim/pab_rules.json, parsed from EUR-Lex",
        "index_computed_by": "src/portfolio.py",
        "attribution": reg["attribution"],
        "not_a_registered_benchmark": True,
        "not_a_registered_benchmark_reason": (
            "No administrator, no authorisation, no annual review, and our intensity is Scope 1 "
            "only where the regulation asks for Scope 1, 2 and 3."),
        "universe": {
            "name": "S&P 500",
            "n_companies": uni["n_companies"],
            "market_cap_usd": round(uni["market_cap_usd"]),
        },
        "headline": {
            "n_excluded": exc["n_excluded"],
            "n_universe": uni["n_companies"],
            "n_held": pf["names"],
            "cap_share_excluded_pct": pct(exc["w_excluded"]),
            "intensity_cut_achieved_pct": pct(pf["cut_vs_universe"]),
            "intensity_cut_required_pct": required,
            "intensity_cut_required_article": "Article 11",
            "tracking_error_pct": pct(te["te"]),
            "tracking_error_p05_pct": pct(te["te_p05"]),
            "tracking_error_p95_pct": pct(te["te_p95"]),
            "tracking_error_note": ("90% block bootstrap on five years of weekly returns, "
                                    "weights held fixed at inception."),
            "reallocation_share_pct": pct(realloc, 1),
            "reallocation_note": ("Share of the intensity cut that comes from moving weight "
                                  "between sectors rather than from companies cutting emissions."),
            "aum_usd": AUM_USD,
        },
        "intensity_definition": port["meta"]["intensity_definition"],
        "scope_note": ("Articles 9 and 11 ask for Scope 1, 2 and 3. We carry mandatory Scope 1 "
                       "only, for 139 of the 499, and apply it identically to the index and to the "
                       "universe, so the ratio is like for like and the level is not comparable to "
                       "a commercial PAB."),
        "cut_note": ("The cut is measured against the same universe on the same Scope 1 numbers. "
                     "Exclusions on their own give %s%%; the figure above is after the Article 3 "
                     "sector floor puts the weight back into high impact sectors."
                     % pct(port["portfolios"]["naive_exclusion"]["cut_vs_universe"], 1)),
        "overlap_note": ("%d companies are barred by more than one article, so the per article "
                         "counts add to %d while %d companies are barred."
                         % (n_multi, n_rule_hits, exc["n_excluded"])),
        "paris_score": {
            "definition": SCORE_DEFINITION,
            "bound_note": SCORE_BOUND_NOTE,
            "reference_note": SCORE_REFERENCE_NOTE,
            "barred_value": 0,
            "range": [1, 100],
            "n_scored": n_scored,
            "n_null": len(comp_out) - n_scored,
        },
    }

    return {"meta": meta, "rules": rules_out,
            "moves": {"cuts": cuts, "adds": adds}, "companies": comp_out}


def check(doc):
    """Every number the brief quotes, against the file it came from."""
    h = doc["meta"]["headline"]
    arts = {r["article"]: r["n_barred"] for r in doc["rules"]}
    claims = [
        ("67 barred", h["n_excluded"], 67),
        ("of 499", h["n_universe"], 499),
        ("8.57% of index market cap", h["cap_share_excluded_pct"], 8.57),
        ("(a) weapons 14", arts["Article 12(1)(a)"], 14),
        ("(b) tobacco 2", arts["Article 12(1)(b)"], 2),
        ("(c) UNGC 3", arts["Article 12(1)(c)"], 3),
        ("(d) coal 2", arts["Article 12(1)(d)"], 2),
        ("(e) oil 17", arts["Article 12(1)(e)"], 17),
        ("(f) gas 7", arts["Article 12(1)(f)"], 7),
        ("(g) power 28", arts["Article 12(1)(g)"], 28),
        ("Article 11 asks 50%", h["intensity_cut_required_pct"], 50.0),
        ("cut achieved 63.1%", round(h["intensity_cut_achieved_pct"], 1), 63.1),
        ("tracking error 1.50%", h["tracking_error_pct"], 1.50),
        ("reallocation 97.4%", h["reallocation_share_pct"], 97.4),
    ]
    moves = {m["ticker"]: m["musd"] for m in doc["moves"]["cuts"]}
    moves.update({m["ticker"]: m["musd"] for m in doc["moves"]["adds"]})
    for tk, want in [("NVDA", -25.4), ("AAPL", -19.5), ("GOOGL", -15.0), ("XOM", -9.8),
                     ("MSFT", -9.6), ("AVGO", 25.2), ("AMD", 13.7), ("LLY", 12.3),
                     ("TSLA", 11.7), ("JNJ", 5.5)]:
        claims.append(("move %s %+.1f" % (tk, want), moves.get(tk), want))

    ok = True
    for label, got, want in claims:
        held = got is not None and abs(got - want) < 0.051
        ok = ok and held
        print("  %-28s %-8s got %s  brief %s" % (label, "HELD" if held else "FAILED", got, want))
    return ok


def main():
    doc = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    size = os.path.getsize(OUT)
    print("wrote %s  %.1f KB  %d companies  %d rules"
          % (OUT, size / 1024.0, len(doc["companies"]), len(doc["rules"])))
    if size > 120 * 1024:
        print("  OVER the 120 KB budget")
    print("checking the numbers the site quotes:")
    ok = check(doc)
    print("all held" if ok else "some did not hold, see above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
