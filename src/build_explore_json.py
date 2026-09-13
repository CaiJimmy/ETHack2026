#!/usr/bin/env python3
"""Build jimmy-website/public/data/explore.json for the Explore tab.

Source of truth is the vanilla app's dataset on origin/main:

    git show origin/main:web/data/master.json

The old page (web/app.js) held three things the React app never got: the pillar
weight sliders, the logo scatter, and the per-metric score card. Its METRICS
table and its PILLARS map are the definition of what the site calls "our index",
so they are copied here rather than restated.

Nothing that app computed at run time is computed here. The sector percentile
ranking stays in the view, because it depends on which companies are on screen.

Every metric carries a provenance class from the same four-word vocabulary the
Sources tab uses: mandatory, voluntary, modelled, vendor.

Run:
    nix develop --command .venv/bin/python src/build_explore_json.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "jimmy-website" / "public" / "data" / "explore.json"

# --- sources, copied from SRC in web/app.js -------------------------------
# class: mandatory | voluntary | modelled | vendor, the vocabulary of the
# Sources tab. It is per metric, not per file, because one file can carry a
# reported number and a vendor's model of it.
SOURCES = {
    "epa": {
        "short": "US EPA GHGRP",
        "name": "US EPA Greenhouse Gas Reporting Program, direct emissions 2019 to 2023, matched to parent companies by ownership share",
        "url": "https://www.epa.gov/ghgreporting/data-sets",
    },
    "sust": {
        "short": "Sustainalytics",
        "name": "Sustainalytics ESG Risk Ratings for the S&P 500, 2024 copy on Kaggle",
        "url": "https://www.kaggle.com/datasets/pritish509/s-and-p-500-esg-risk-ratings",
    },
    "yf": {
        "short": "Yahoo Finance",
        "name": "Yahoo Finance company snapshot (EBITDA, employees), 2025, bundled in the open-source climate-credit-risk-analyzer",
        "url": "https://huggingface.co/spaces/SubramaniMokkala/climate-credit-risk-analyzer",
    },
    "corp": {
        "short": "Global Corporate ESG dataset",
        "name": "Global Corporate ESG and Financial Dataset (Kaggle, mrbossjaysrb): Altman Z, Piotroski F, decarbonisation targets, controversy flags",
        "url": "https://www.kaggle.com/datasets/mrbossjaysrb/global-corporate-esg-and-financial-dataset",
    },
    "list": {
        "short": "Market screener, Sep 2026",
        "name": "S&P 500 member list with market value, price and revenue: market screener screenshot, September 2026 (OCR)",
        "url": None,
    },
}

# --- METRICS, copied from web/app.js --------------------------------------
# key, pillar, label, good (which direction is better), src, fmt, class.
# "fmt" names a formatter the view implements; the old app carried a JS closure.
METRICS = [
    {"key": "ghg_intensity_t_per_musd", "pillar": "E", "label": "CO2 per $1M revenue (US sites)",
     "good": "low", "src": "epa", "fmt": "t0", "class": "mandatory"},
    {"key": "ghgrp_trend_5y_pct", "pillar": "E", "label": "Change in US site emissions 2019 to 2023",
     "good": "low", "src": "epa", "fmt": "pct", "class": "mandatory"},
    {"key": "esg_risk_env", "pillar": "E", "label": "Environment risk score",
     "good": "low", "src": "sust", "fmt": "n1", "class": "vendor"},
    {"key": "temp_goal_c", "pillar": "E", "label": "Implied temperature of the emission plan",
     "good": "low", "src": "corp", "fmt": "degc", "class": "modelled"},
    {"key": "decarb_target_year", "pillar": "E", "label": "Decarbonisation target year",
     "good": "low", "src": "corp", "fmt": "year", "class": "voluntary"},
    {"key": "esg_risk_social", "pillar": "S", "label": "Social risk score",
     "good": "low", "src": "sust", "fmt": "n1", "class": "vendor"},
    {"key": "controversy_score", "pillar": "S", "label": "Controversy level (0 none to 5 severe)",
     "good": "low", "src": "sust", "fmt": "n0", "class": "vendor"},
    {"key": "controversy_flags", "pillar": "S", "label": "Controversy flags (0 to 6 topics)",
     "good": "low", "src": "corp", "fmt": "of6", "class": "vendor"},
    {"key": "esg_risk_gov", "pillar": "G", "label": "Governance risk score",
     "good": "low", "src": "sust", "fmt": "n1", "class": "vendor"},
    {"key": "altman_z", "pillar": "F", "label": "Altman Z-score (bankruptcy risk)",
     "good": "high", "src": "corp", "fmt": "n2", "class": "modelled"},
    {"key": "piotroski_f", "pillar": "F", "label": "Piotroski F-score (financial strength)",
     "good": "high", "src": "corp", "fmt": "of9", "class": "modelled"},
]

PILLARS = {"E": "Environment", "S": "Social", "G": "Governance", "F": "Financial resilience"}

# Axis choices for the scatter, and where each axis number comes from.
AXES = [
    {"key": "market_cap_b", "label": "Market value ($ billion)", "src": "list", "fmt": "usdb"},
    {"key": "revenue_b", "label": "Revenue ($ billion)", "src": "list", "fmt": "usdb"},
    {"key": "ebitda_b", "label": "EBITDA ($ billion)", "src": "yf", "fmt": "usdb"},
    {"key": "employees", "label": "Employees", "src": "yf", "fmt": "n0"},
    {"key": "ghgrp_scope1_mt", "label": "Direct CO2 from US sites (million tonnes)", "src": "epa", "fmt": "n2"},
    {"key": "ghg_intensity_t_per_musd", "label": "CO2 per $1M revenue (tonnes)", "src": "epa", "fmt": "t0"},
]

# Context rows on the card that are shown but never scored.
EXTRA = [
    {"key": "market_cap_b", "label": "Market value", "src": "list", "fmt": "usdb", "class": "mandatory"},
    {"key": "revenue_b", "label": "Revenue", "src": "list", "fmt": "usdb", "class": "mandatory"},
    {"key": "ghgrp_scope1_mt", "label": "Direct CO2, US sites 2023", "src": "epa", "fmt": "mt", "class": "mandatory"},
    {"key": "employees", "label": "Employees", "src": "yf", "fmt": "n0", "class": "vendor"},
]

IDENT = ["ticker", "name", "sector", "industry"]
# Rounding keeps the file small without moving any company across a tie.
NUMERIC = {
    "market_cap_b": 1, "revenue_b": 2, "ebitda_b": 3, "employees": 0,
    "ghgrp_scope1_mt": 3, "ghg_intensity_t_per_musd": 2, "ghgrp_trend_5y_pct": 1,
    "esg_risk_env": 1, "temp_goal_c": 1, "decarb_target_year": 0,
    "esg_risk_social": 1, "controversy_score": 1, "controversy_flags": 0,
    "esg_risk_gov": 1, "altman_z": 2, "piotroski_f": 0,
}
COLUMNS = IDENT + list(NUMERIC) + ["dual_class_duplicate"]


def load_master() -> dict:
    raw = subprocess.run(
        ["git", "show", "origin/main:web/data/master.json"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    return json.loads(raw)


def cell(company: dict, col: str):
    if col in IDENT:
        return company.get(col) or None
    if col == "dual_class_duplicate":
        return 1 if company.get("dual_class_duplicate") else 0
    v = company.get(col)
    if v is None:
        return None
    digits = NUMERIC[col]
    r = round(float(v), digits)
    return int(r) if digits == 0 else r


def main() -> int:
    master = load_master()
    companies = master["companies"]
    assert len(companies) == 503, f"expected 503 companies, got {len(companies)}"

    rows = [[cell(c, col) for col in COLUMNS] for c in companies]

    doc = {
        "meta": {
            "universe": len(rows),
            "built_from": "origin/main:web/data/master.json",
            "note": "Percentiles stay out of this file. The browser computes them against the sector on screen.",
        },
        "sources": SOURCES,
        "pillars": PILLARS,
        "metrics": METRICS,
        "axes": AXES,
        "extra": EXTRA,
        "columns": COLUMNS,
        "rows": rows,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    size = OUT.stat().st_size
    assert size < 250_000, f"{size} bytes is over the 250 KB budget"

    idx = {c: i for i, c in enumerate(COLUMNS)}
    scored = [r for r in rows if r[idx["dual_class_duplicate"]] == 0 and r[idx["market_cap_b"]] is not None]
    ranked = [r for r in scored if r[idx["sector"]]]

    print(f"{OUT.relative_to(ROOT)}  {size:,} bytes  {len(rows)} rows")
    print(f"{len(scored)} in the universe after dual-class and market-value filters, {len(ranked)} carry a sector and can be ranked")
    print("non-null per metric, out of the ranked set:")
    for m in METRICS:
        n = sum(1 for r in ranked if r[idx[m["key"]]] is not None)
        print(f"  {m['key']:<26} {n:>4}  {100*n/len(ranked):5.1f}%  {m['class']}")
    print("non-null per axis and context field:")
    for k in ["market_cap_b", "revenue_b", "ebitda_b", "employees", "ghgrp_scope1_mt"]:
        n = sum(1 for r in ranked if r[idx[k]] is not None)
        print(f"  {k:<26} {n:>4}  {100*n/len(ranked):5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
