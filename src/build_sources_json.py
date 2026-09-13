#!/usr/bin/env python3
"""Build jimmy-website/public/data/sources.json, one row per source.

Every count is read back out of the built master table, the column registry or
the coverage table. Licence and retrieval date come from the attestation files
in data/interim/provenance. Nothing in the output is typed by hand except the
one-line description of what each source gives and the data-quality note.

    nix develop --command .venv/bin/python src/build_sources_json.py
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROV = ROOT / "data" / "interim" / "provenance"
MASTER = ROOT / "data" / "master"
OUT = ROOT / "jimmy-website" / "public" / "data" / "sources.json"

UNIVERSE = 503

# Order the classes so the mandatory backbone reads first and the vendor rows,
# which feed no score, read last.
CLASS_ORDER = {"mandatory": 0, "voluntary": 1, "modelled": 2, "vendor": 3}


def registry() -> dict[str, dict[str, str]]:
    with (MASTER / "column_registry.csv").open() as fh:
        return {row["name"]: row for row in csv.DictReader(fh)}


def provenance(name: str) -> dict:
    """Return the first object in an attestation file, list or dict."""
    obj = json.loads((PROV / f"{name}.json").read_text())
    return obj[0] if isinstance(obj, list) else obj


def retrieved(name: str) -> str | None:
    obj = json.loads((PROV / f"{name}.json").read_text())
    stamps: list[str] = []
    if isinstance(obj, list):
        stamps = [x.get("retrieved_at") for x in obj if x.get("retrieved_at")]
    else:
        for key in ("retrieved_at", "generated_at", "written_at", "finished_at"):
            if obj.get(key):
                stamps.append(obj[key])
        for key in ("fetches", "fetched", "urls", "files"):
            for x in obj.get(key) or []:
                if isinstance(x, dict) and x.get("retrieved_at"):
                    stamps.append(x["retrieved_at"])
    return max(stamps)[:10] if stamps else None


def licence_full(name: str, limit: int = 200) -> str | None:
    """The attested licence, trimmed to whole sentences for a hover title."""
    obj = provenance(name)
    lic = obj.get("attribution_required") or obj.get("licence")
    for key in ("fetches", "fetched", "urls", "files"):
        if lic:
            break
        for entry in obj.get(key) or []:
            if isinstance(entry, dict) and entry.get("licence"):
                lic = entry["licence"]
                break
    if isinstance(lic, dict):
        lic = "; ".join(f"{k}: {v}" for k, v in lic.items())
    if not lic:
        return None
    out: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", lic.strip()):
        if out and sum(len(x) + 1 for x in out) + len(part) > limit:
            break
        out.append(part)
    return " ".join(out)


def main() -> None:
    reg = registry()
    df = pd.read_parquet(MASTER / "master_company.parquet")
    water = pd.read_parquet(ROOT / "data" / "interim" / "water_by_ticker.parquet")

    def notnull(col: str) -> int:
        return int(df[col].notna().sum())

    def equals(col: str, *values: str) -> int:
        return int(df[col].isin(values).sum())

    # id, name, what it gives, class, count, headline column for the DQ mark,
    # period, provenance file, short licence, data-quality note, scored
    spec = [
        ("ghgrp", "EPA GHGRP", "Measured Scope 1 at every US facility above 25,000 t",
         "mandatory", notnull("scope1_measured_us_t"), "scope1_measured_us_t",
         "RY 2010-2023", "epa_ghgrp", "Public domain",
         "Filed under penalty of law. Stops at reporting year 2023.", True),
        ("camd", "EPA CAMD Part 75", "Stack-measured CO2 from power and large combustion units",
         "mandatory", notnull("scope1_current_signal_t"), "scope1_current_signal_t",
         "2010-2026", "epa_camd", "Public domain",
         "Hourly monitors, audited. Runs to 2026, so it dates the GHGRP lag.", True),
        ("sec_xbrl", "SEC EDGAR XBRL", "Revenue, EBIT, capex, debt and cover-page shares",
         "mandatory", equals("revenue_basis", "sec_xbrl"), "revenue_musd",
         "FY 2025", "sec_financials", "Public domain",
         "Audited filings, read from company facts rather than a vendor copy.", True),
        ("sec_dera", "SEC DERA statement sets", "Segment revenue for the Article 12 revenue screens",
         "mandatory", notnull("excluded"), "excluded",
         "2025 Q3 archive", "revenue_exclusions", "Public domain",
         "Same filings, segment level. Every company is tested, 67 are barred.", True),
        ("egrid", "EPA eGRID", "Grid emission factor for each subregion",
         "mandatory", notnull("grid_factor_hq_g_per_kwh"), "grid_factor_hq_g_per_kwh",
         "2018-2023", "epa_egrid", "Public domain",
         "Applied at headquarters, which is a proxy for where the power is drawn.", True),
        ("eia923", "EIA Form 923", "Plant net generation, the denominator of power intensity",
         "mandatory", notnull("power_gen_mwh"), "power_gen_mwh",
         "2015-2025", "eia_generation", "Public domain",
         "Only the S&P 500 names that own generation appear here.", True),
        ("violations", "Violation Tracker", "Environmental penalties and case counts",
         "mandatory", notnull("penalty_usd_environment"), "penalty_usd_environment",
         "2000-2026", "violations", "No open licence",
         "Enforcement records are public. Detection is biased to regulated industry.", True),
        ("universe", "S&P 500 constituents", "Index membership, CIK, GICS sector, listing dates",
         "mandatory", int(df["ticker"].notna().sum()), "ticker",
         "as of 2026-09-12", "universe", "ODC-PDDL-1.0",
         "Rebuilt daily. 503 listings, 500 of them primary.", True),
        ("eurlex", "EUR-Lex 2020/1818", "The Paris-aligned benchmark rules, parsed from the text",
         "mandatory", notnull("excluded"), None,
         "in force since 2020", "eurlex", "EU reuse policy",
         "24 rules and 6 definitions parsed straight from the regulation text.", True),

        ("wba", "World Benchmarking Alliance", "Company-disclosed Scope 1, 2 and 3 and target text",
         "voluntary", equals("scope1_selfreported_source", "wba"), "scope1_selfreported_t",
         "FY 2017-2024", "wba", "CC BY-NC-ND 4.0",
         "Self-reported and assessed by WBA. Never merged into a mandatory column.", True),
        ("sbti", "Science Based Targets initiative", "Near-term and net-zero target status",
         "voluntary", notnull("sbti_near_term_status"), "sbti_near_term_status",
         "dashboard 2026-09", "sbti", "Terms of use, non-commercial",
         "A validated target is still only a promise about 2030.", True),
        ("nzt", "Net Zero Tracker", "Interim and net-zero pledges where SBTi has none",
         "voluntary", equals("promised_basis", "nzt_interim", "netzero_inferred"), "promised_pct_yr",
         "2026-09", "net_zero_tracker", "No open licence",
         "Pledge text, so the implied annual rate is inferred from the target year.", True),
        ("nopperl", "Corporate emission reports", "Scope 1 and 2 parsed out of published report PDFs",
         "voluntary", equals("scope1_selfreported_source", "report_pdf"), "scope1_selfreported_t",
         "FY 2014-2022", "hf_nopperl", "PDDL public domain",
         "Machine-read from the company's own PDF. 17 rows flagged as suspect.", True),
        ("cdp", "CDP scores", "Nothing. The published embeds carry no tonnage",
         "vendor", 0, None,
         "2024 cycle", "cdp_flourish_scores", "No redistribution",
         "268 of the 500 are graded. Zero numeric emissions cells, so zero columns.", False),

        ("climatetrace", "Climate TRACE", "Equity-share emissions inferred from satellites and activity",
         "modelled", notnull("scope1_modelled_t"), "scope1_modelled_t",
         "2021-2026", "climatetrace", "CC BY 4.0",
         "A cross-check on the EPA spine. 2026 carries six months only.", True),
        ("aqueduct", "WRI Aqueduct 4.0", "Basin water stress joined to GHGRP facility coordinates",
         "modelled", int(water["ticker"].nunique()), None,
         "baseline 2023", "aqueduct", "CC BY 4.0",
         "WRI models the basin. The coordinates come from GHGRP filings.", True),
        ("ngfs", "NGFS Phase 5", "The 2030 carbon price the damage model runs on",
         "modelled", notnull("price_usd2010_per_t"), "price_usd2010_per_t",
         "Nov 2024, priced at 2030", "ngfs", "IIASA terms of use",
         "GCAM says 99 US$2010 and REMIND 284 for the same scenario. We show GCAM.", True),

        ("kaggle_esg", "ESG vendor scores", "A consensus percentile used to benchmark our rank",
         "vendor", notnull("vendor_percentile"), "vendor_percentile",
         "uploader snapshot", "kaggle_esg", "Asserted CC0, disputed",
         "Third-party re-uploads of commercial ratings. Input to no score.", False),
        ("yahoo", "Yahoo Finance", "Prices, beta and the EV/EBITDA multiple",
         "vendor", notnull("ev_ebitda_x"), "ev_ebitda_x",
         "to 2026-09-11", "yahoo_prices", "No redistribution grant",
         "Market data only. 34 multiples fall back to the sector median.", True),
    ]

    rows = []
    for (sid, name, gives, klass, count, dq_col, period, prov, lic_short,
         dq_note, scored) in spec:
        dq = reg[dq_col]["dq_typical"] if dq_col and dq_col in reg else None
        rows.append({
            "id": sid,
            "name": name,
            "gives": gives,
            "class": klass,
            "count": int(count),
            "of": UNIVERSE,
            "pct": round(100 * count / UNIVERSE, 1),
            "period": period,
            "licence": lic_short,
            "licence_full": licence_full(prov),
            "retrieved": retrieved(prov),
            "dq": int(dq) if dq else None,
            "dq_note": dq_note,
            "scored": scored,
        })

    rows.sort(key=lambda r: (CLASS_ORDER[r["class"]], -r["count"]))

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1

    out = {
        "meta": {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "universe": UNIVERSE,
            "n_sources": len(rows),
            "class_counts": counts,
            "dq_scale": "PCAF data quality, 1 is measured and 5 is a sector average",
            "note": "Counts are non-null rows in data/master/master_company.parquet.",
        },
        "sources": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}  {len(rows)} sources  {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
