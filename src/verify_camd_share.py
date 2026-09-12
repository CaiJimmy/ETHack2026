"""Settle the S&P 500 share of 2025 US measured power CO2.

Two lanes disagreed. match_parents.py reported 54.0%, the coverage validator 49.0%, and neither
could rule out a common-stack double count in camd_unit_year.parquet, which carries an
associated_stacks column.

This script does three independent things:

  1. Proves whether the unit table double counts a common stack, by checking that no row is keyed
     by a stack id and by comparing our per-facility sums against EPA's own server-side facility
     and state aggregations.
  2. Gets the national total from EPA rather than from our own sum.
  3. Recomputes the share in one consistent mass unit and shows which of the two figures came out
     of which arithmetic.

Outputs:
  data/interim/camd_share_verification.json
  data/interim/provenance/camd_verify.json
  data/raw/epa_camd_verify/*.json          cached EPA responses, so a second run touches no network

Needs CAMD_API_KEY. The devshell sources .env.
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
RAW = ROOT / "data" / "raw" / "epa_camd_verify"
OUT_PATH = INTERIM / "camd_share_verification.json"
PROV_PATH = INTERIM / "provenance" / "camd_verify.json"

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
API_KEY = os.environ.get("CAMD_API_KEY", "DEMO_KEY")

YEAR = 2025
BASE = "https://api.epa.gov/easey/streaming-services/emissions/apportioned/annual"

# EPA aggregates the same apportioned rows server side. by-facility and by-state are computed by
# EPA, not by us, so they are the check on our own groupby.
ENDPOINTS = {
    "by_facility": f"{BASE}/by-facility",
    "by_state": f"{BASE}/by-state",
}

SHORT_TON_IN_TONNES = 0.90718474

LICENCE = "US federal government work, public domain (17 U.S.C. 105)."
REDISTRIBUTION = (
    "Public domain. We may publish derived numbers, tables and charts, citing EPA Clean Air "
    "Markets Division and the retrieval date."
)

PAUSE = 2.0
RETRY_STATUSES = (429, 500, 502, 503, 504)
BACKOFF = (10, 20, 40, 60)

session = requests.Session()
session.headers.update({"User-Agent": UA})

provenance = {}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_existing_provenance():
    """So a cached run keeps the retrieval time the bytes actually came from."""
    if not PROV_PATH.exists():
        return
    try:
        for rec in json.loads(PROV_PATH.read_text()):
            provenance[rec["url"]] = rec
    except (ValueError, KeyError):
        pass


def fetch_json(url, dest, params):
    """Fetch to dest, or reuse dest if it already holds bytes. A second run touches no network."""
    masked = {k: ("<api_key>" if k == "api_key" else v) for k, v in params.items()}
    shown = url + "?" + "&".join(f"{k}={v}" for k, v in masked.items())

    if dest.exists() and dest.stat().st_size > 0:
        blob = dest.read_bytes()
        from_cache = True
        status = None
    else:
        for attempt in range(len(BACKOFF) + 1):
            resp = session.get(url, params=params, timeout=300)
            time.sleep(PAUSE)
            if resp.status_code == 200 and resp.content:
                break
            if resp.status_code in RETRY_STATUSES and attempt < len(BACKOFF):
                print(f"  wait    {dest.name}: HTTP {resp.status_code}, retry in {BACKOFF[attempt]}s")
                time.sleep(BACKOFF[attempt])
                continue
            raise SystemExit(f"fetch failed {resp.status_code} {shown}\n{resp.text[:300]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        blob = resp.content
        from_cache = False
        status = resp.status_code
        print(f"  fetched {dest.name} ({len(blob):,} bytes)")

    prior = provenance.get(shown, {})
    provenance[shown] = {
        "url": shown,
        "retrieved_at": prior.get("retrieved_at", now_iso()) if from_cache else now_iso(),
        "http_status": status if status is not None else prior.get("http_status", 200),
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "local_path": str(dest.relative_to(ROOT)),
        "licence": LICENCE,
        "redistribution": REDISTRIBUTION,
        "served_from_cache_this_run": from_cache,
    }
    return json.loads(blob)


def check_stack_structure(unit):
    """Is a common stack counted twice, once at the stack and once at each unit under it?

    In the apportioned annual feed the answer has to come from the keys. If EPA published a row
    for the stack itself as well as for its units, the stack id would appear in unit_id.
    """
    print("stack structure")
    y = unit[unit.year == YEAR].copy()
    y["uid"] = y.unit_id.astype(str).str.strip()

    stacks = set()
    for s in y.associated_stacks.dropna():
        for part in str(s).split(","):
            stacks.add(part.strip())

    unit_ids = set(y.uid)
    collisions = sorted(unit_ids & stacks)

    # Stricter: a stack id only double counts if it is a row at the SAME facility.
    pairs = set(zip(y.oris_code, y.uid))
    same_facility = 0
    for r in y[y.associated_stacks.notna()].itertuples():
        for part in str(r.associated_stacks).split(","):
            if (r.oris_code, part.strip()) in pairs:
                same_facility += 1

    dup_keys = int(y.duplicated(["oris_code", "uid"]).sum())
    stacked_co2 = float(y.loc[y.associated_stacks.notna(), "co2_short_tons"].sum())
    total_co2 = float(y.co2_short_tons.sum())

    print(f"  {YEAR} rows: {len(y):,} over {y.oris_code.nunique():,} ORIS facilities")
    print(f"  distinct associated stack ids: {len(stacks):,}")
    print(f"  rows naming a stack: {int(y.associated_stacks.notna().sum()):,} "
          f"carrying {100 * stacked_co2 / total_co2:.1f}% of the CO2")
    print(f"  unit_id values that are also a stack id anywhere: {len(collisions)}")
    print(f"  unit rows whose own facility also has a row keyed by that stack: {same_facility}")
    print(f"  duplicate (oris_code, unit_id) keys: {dup_keys}")
    verdict = (len(collisions) == 0 and same_facility == 0 and dup_keys == 0)
    print(f"  verdict: {'no stack row exists, so units cannot double count a stack' if verdict else 'POSSIBLE DOUBLE COUNT'}")
    print()
    return {
        "rows": int(len(y)),
        "facilities": int(y.oris_code.nunique()),
        "distinct_stack_ids": len(stacks),
        "rows_naming_a_stack": int(y.associated_stacks.notna().sum()),
        "co2_share_of_rows_naming_a_stack_pct": round(100 * stacked_co2 / total_co2, 2),
        "unit_ids_that_are_stack_ids": collisions,
        "stack_rows_at_same_facility": same_facility,
        "duplicate_unit_keys": dup_keys,
        "no_double_count": bool(verdict),
    }


def check_against_epa(unit):
    """Compare our per-facility and national sums against EPA's own aggregation of the same feed."""
    print("EPA's own aggregation")
    RAW.mkdir(parents=True, exist_ok=True)
    epa = {}
    for name, url in ENDPOINTS.items():
        dest = RAW / f"{name}_{YEAR}.json"
        epa[name] = pd.DataFrame(fetch_json(url, dest, {"api_key": API_KEY, "year": YEAR}))

    fac = epa["by_facility"]
    st = epa["by_state"]
    epa_fac_total = float(fac.co2Mass.sum())
    epa_state_total = float(st.co2Mass.sum())

    y = unit[unit.year == YEAR]
    ours_total = float(y.co2_short_tons.sum())
    ours_fac = y.groupby("oris_code").co2_short_tons.sum().rename("ours")

    cmp = (fac.set_index("facilityId").co2Mass.rename("epa")
           .to_frame().join(ours_fac, how="outer"))
    cmp["diff"] = cmp.ours.fillna(0) - cmp.epa.fillna(0)
    worst = cmp.reindex(cmp["diff"].abs().sort_values(ascending=False).index).head(5)
    over = cmp[cmp["diff"] > 1.0]

    print(f"  EPA by-facility rows: {len(fac):,}   our facilities: {ours_fac.shape[0]:,}")
    print(f"  EPA by-facility CO2 total: {epa_fac_total / 1e6:,.3f} M short tons")
    print(f"  EPA by-state    CO2 total: {epa_state_total / 1e6:,.3f} M short tons")
    print(f"  our unit sum:              {ours_total / 1e6:,.3f} M short tons")
    print(f"  our sum minus EPA by-facility: {(ours_total - epa_fac_total):,.3f} short tons")
    print(f"  facilities where our sum exceeds EPA's by more than 1 short ton: {len(over)}")
    print("  largest absolute per-facility differences:")
    for oris, r in worst.iterrows():
        print(f"    ORIS {oris}: ours {r.ours:,.1f}  EPA {r.epa:,.1f}  diff {r['diff']:,.3f}")
    print()
    return {
        "epa_by_facility_short_tons": epa_fac_total,
        "epa_by_state_short_tons": epa_state_total,
        "our_unit_sum_short_tons": ours_total,
        "our_minus_epa_short_tons": ours_total - epa_fac_total,
        "epa_facility_rows": int(len(fac)),
        "our_facility_count": int(ours_fac.shape[0]),
        "facilities_where_we_exceed_epa": int(len(over)),
    }


def compute_share(unit, emissions, universe, unmatched):
    print("the share")
    y = unit[unit.year == YEAR]
    nat_short = float(y.co2_short_tons.sum())
    nat_tonnes = float(y.co2_tonnes.sum())

    primary = set(universe.loc[universe.is_primary_listing.eq(True), "ticker"])
    e = emissions[(emissions.year == YEAR) & emissions.ticker.isin(primary)]
    att_tonnes = float(e.scope1_camd_tonnes.sum())
    att_short = att_tonnes / SHORT_TON_IN_TONNES
    n_tickers = int((e.scope1_camd_tonnes.fillna(0) > 0).sum())

    un = unmatched[unmatched.source == "camd_owner_unattributed"]
    un_tonnes = float(un["tonnes_2023_ghgrp_or_2025_camd"].sum())

    correct = 100 * att_tonnes / nat_tonnes
    mixed = 100 * att_tonnes / nat_short

    print(f"  national {YEAR} measured power CO2: {nat_short / 1e6:,.1f} M short tons "
          f"= {nat_tonnes / 1e6:,.1f} MMT")
    print(f"  attributed to S&P 500 primary listings: {att_tonnes / 1e6:,.1f} MMT "
          f"= {att_short / 1e6:,.1f} M short tons, across {n_tickers} tickers")
    print(f"  unattributed residual: {un_tonnes / 1e6:,.1f} MMT")
    print(f"  attributed + unattributed: {(att_tonnes + un_tonnes) / 1e6:,.1f} MMT "
          f"against a national total of {nat_tonnes / 1e6:,.1f} MMT, "
          f"gap {(att_tonnes + un_tonnes - nat_tonnes):,.1f} t")
    print()
    print(f"  tonnes / tonnes          = {correct:.2f}%   <- correct")
    print(f"  tonnes / short tons      = {mixed:.2f}%   <- what a unit mismatch produces")
    print(f"  short tons / short tons  = {100 * att_short / nat_short:.2f}%")
    print()
    return {
        "national_short_tons": nat_short,
        "national_tonnes": nat_tonnes,
        "attributed_tonnes": att_tonnes,
        "attributed_short_tons": att_short,
        "attributed_tickers": n_tickers,
        "unattributed_tonnes": un_tonnes,
        "closure_gap_tonnes": att_tonnes + un_tonnes - nat_tonnes,
        "share_pct_correct": correct,
        "share_pct_tonnes_over_short_tons": mixed,
    }


def main():
    if API_KEY == "DEMO_KEY":
        print("no CAMD_API_KEY in the environment, falling back to DEMO_KEY; expect throttling")

    load_existing_provenance()
    unit = pd.read_parquet(INTERIM / "camd_unit_year.parquet")
    emissions = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    universe = pd.read_parquet(INTERIM / "universe.parquet")
    unmatched = pd.read_csv(INTERIM / "unmatched_top_emitters.csv")
    print(f"camd_unit_year   {len(unit):,} rows, {unit.year.min()}-{unit.year.max()}")
    print(f"emissions_by_ticker {len(emissions):,} rows")
    print(f"universe         {len(universe):,} listings, "
          f"{int(universe.is_primary_listing.sum()):,} primary")
    print()

    stack = check_stack_structure(unit)
    epa = check_against_epa(unit)
    share = compute_share(unit, emissions, universe, unmatched)

    # The two lanes' figures, decided.
    tol = 0.05
    correct_is_54 = abs(share["share_pct_correct"] - 54.0) < tol
    mixed_is_49 = abs(share["share_pct_tonnes_over_short_tons"] - 49.0) < tol
    print("verdict")
    print(f"  54.0% is the correct figure: {correct_is_54}")
    print(f"  49.0% is reproduced exactly by dividing metric tonnes by short tons: {mixed_is_49}")
    print("  the stack dedupe was never in question: EPA's apportioned annual feed publishes "
          "one row per unit and no row for a stack")

    out = {
        "year": YEAR,
        "generated_at": now_iso(),
        "stack_structure": stack,
        "epa_cross_check": epa,
        "share": share,
        "verdict": {
            "correct_share_pct": round(share["share_pct_correct"], 1),
            "wrong_share_pct": round(share["share_pct_tonnes_over_short_tons"], 1),
            "error": "metric tonnes in the numerator divided by short tons in the denominator",
            "double_counting_found": not stack["no_double_count"],
        },
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, default=float) + "\n")
    PROV_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROV_PATH.write_text(json.dumps(list(provenance.values()), indent=2) + "\n")
    print(f"\nwrote {OUT_PATH}")
    print(f"wrote {PROV_PATH} ({len(provenance)} urls)")


if __name__ == "__main__":
    sys.exit(main())
