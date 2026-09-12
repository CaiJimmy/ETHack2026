#!/usr/bin/env python3
"""Resolve EPA GHGRP parent-company strings and EPA CAMD owner strings to S&P 500 tickers.

EPA files emissions against whatever legal entity owns the stack, which is almost never the
listed parent: FLORIDA POWER & LIGHT CO is NEE, Luminant Generation is VST, CPN MANAGEMENT LP
is the Calpine fleet. This lane builds that bridge and then publishes measured Scope 1 per
ticker per year.

Matching runs in priority tiers, most trustworthy first, and every match records which tier
produced it:

  manual  hand-verified override table (src/overrides_parent_ticker.py)
  exact   normalised-key equality against index, SEC registrant, SEC former and
          Violation Tracker subsidiary names
  fuzzy   rapidfuzz token_set_ratio with a head-token guard, for spellings the keys miss

No network access: every input is an artifact another lane already cached and attested.
"""

import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance" / "entity_resolution.json"

sys.path.insert(0, str(ROOT / "src"))
from fetch_epa_ghgrp import parent_key as ghgrp_parent_key  # noqa: E402
from overrides_parent_ticker import (  # noqa: E402
    BLOCKED,
    FUND_OWNER_TICKERS,
    OVERRIDES,
    UNMATCHED_NOTES,
)

# Rapidfuzz thresholds. Justified in the header printout and in the return value: on this data
# token_set_ratio alone is worthless, because a subset scores 100 (ENERGY vs ENTERGY,
# OLD DOMINION vs OLD DOMINION ELECTRIC COOPERATIVE, PORTLAND GENERAL ELECTRIC vs GENERAL
# ELECTRIC). The head-token guard is what makes the stage safe.
FUZZY_MIN_SET = 90
FUZZY_MIN_HEAD_LEN = 4

# Words that may differ between two spellings of the same company without changing identity.
# COOPERATIVE, AUTHORITY, DISTRICT and friends are deliberately absent: they mark a public or
# member-owned entity and are exactly what separates OLD DOMINION ELECTRIC COOPERATIVE from
# Old Dominion Freight Line.
GENERIC_TAIL = {
    "ENERGY", "RESOURCES", "PETROLEUM", "OIL", "GAS", "MATERIALS", "TECHNOLOGY", "TECHNOLOGIES",
    "PRODUCTS", "BRANDS", "FOODS", "STORES", "PROPERTIES", "FINANCIAL", "PHARMACEUTICALS",
    "PHARMACEUTICAL", "MOTOR", "MOTORS", "STEEL", "PAPER", "MINING", "REFINING", "MIDSTREAM",
    "COMMUNICATIONS", "ELECTRONICS", "SEMICONDUCTOR", "LABORATORIES", "STORES", "AIRLINES",
}

# A single shared token this generic does not identify a company, so fuzzy will not accept a
# match that rests on it alone.
NON_IDENTIFYING = {
    "INTERNATIONAL", "AMERICAN", "GENERAL", "NATIONAL", "UNITED", "GLOBAL", "PACIFIC",
    "ATLANTIC", "CONTINENTAL", "ENERGY", "POWER", "ELECTRIC", "STANDARD", "UNIVERSAL",
    "PREMIER", "SUMMIT", "LIBERTY", "PIONEER", "FRONTIER", "EMPIRE", "CAPITAL", "CENTRAL",
    "FIRST", "NORTH", "SOUTH", "EAST", "WEST", "GULF", "LONE", "STAR",
}

LEGAL = re.compile(
    r"\b(CORPORATION|CORP|COMPANY|COMPANIES|CO|COS|INCORPORATED|INC|LLC|LLP|LP|LTD|PLC"
    r"|HOLDINGS|HOLDING|GROUP|THE|PBC|NV|SA|AG|SE|TRUST|CLASS)\b"
)
PAREN = re.compile(r"\([^)]*\)?")


def words(name):
    """Word form: parentheticals dropped, punctuation dropped, legal-form words dropped.

    EPA hangs annotations off the parent string itself ("The AES Corporation (Ownership
    interest reported is per unit)"), so the parenthetical has to go before anything else.
    """
    s = PAREN.sub(" ", str(name).upper()).replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\s+", " ", LEGAL.sub(" ", s)).strip()


def key_med(name):
    """Whitespace-free key with only legal-form words removed."""
    return words(name).replace(" ", "")


def key_raw(name):
    """Upper-case alphanumerics only. Drops nothing, so it cannot collide across companies."""
    return re.sub(r"[^A-Z0-9]", "", PAREN.sub(" ", str(name).upper()).replace("&", " AND "))


def key_strict(name):
    """The GHGRP lane's own aggregation key, so both sides of the join are squashed identically.

    It also strips AMERICAN, INTERNATIONAL, US, AND and CHEMICALS anywhere in the string, which
    is lossy (AMERICAN ELECTRIC POWER -> ELECTRICPOWER) but symmetric.
    """
    return ghgrp_parent_key(PAREN.sub(" ", str(name)))


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    t_start = datetime.now(timezone.utc)
    print("entity resolution: EPA parent strings -> S&P 500 tickers")
    print()

    inputs = {
        "universe": INTERIM / "universe.parquet",
        "ticker_aliases": INTERIM / "ticker_aliases.json",
        "violations_aliases": INTERIM / "violations_aliases.json",
        "ghgrp_facilities": INTERIM / "ghgrp_facilities.parquet",
        "ghgrp_parent_year": INTERIM / "ghgrp_parent_year.parquet",
        "camd_unit_year": INTERIM / "camd_unit_year.parquet",
        "oris_crosswalk": INTERIM / "oris_ghgrp_crosswalk.parquet",
    }
    missing = [k for k, p in inputs.items() if not p.exists()]
    if missing:
        raise SystemExit(f"missing upstream artifacts: {missing}")

    uni = pd.read_parquet(inputs["universe"])
    aliases = json.loads(inputs["ticker_aliases"].read_text())
    viol = json.loads(inputs["violations_aliases"].read_text())
    fac = pd.read_parquet(inputs["ghgrp_facilities"])
    par = pd.read_parquet(inputs["ghgrp_parent_year"])
    camd = pd.read_parquet(inputs["camd_unit_year"])
    xwalk = pd.read_parquet(inputs["oris_crosswalk"])

    print(f"universe            {len(uni):>7,} listings, {uni.ticker.nunique():,} tickers, "
          f"{int(uni.is_primary_listing.sum()):,} primary")
    print(f"ghgrp_facilities    {len(fac):>7,} facility-year-parent rows, "
          f"{fac.facility_id.nunique():,} facilities, {fac.year.min()}-{fac.year.max()}")
    print(f"ghgrp_parent_year   {len(par):>7,} parent-year rows, "
          f"{par.parent_name_clean.nunique():,} distinct parent keys")
    print(f"camd_unit_year      {len(camd):>7,} unit-year rows, {camd.oris_code.nunique():,} ORIS, "
          f"{camd.year.min()}-{camd.year.max()}")
    print(f"oris_crosswalk      {len(xwalk):>7,} rows, {xwalk.oris_code.nunique():,} ORIS codes")
    print(f"violations_aliases  {sum(len(v) for v in viol.values()):>7,} subsidiary strings over "
          f"{len(viol):,} tickers")
    print()

    # ---------------------------------------------------------------- alias index, in tiers
    primary_by_cik = aliases["primary_ticker_by_cik"]
    ticker_to_cik = aliases["ticker_to_cik"]

    tiers = [
        ("index", defaultdict(set), defaultdict(set)),          # index / SEC registrant names
        ("universe_names", defaultdict(set), defaultdict(set)),  # universe lane's name_to_ticker
        ("violations", defaultdict(set), defaultdict(set)),      # GJF subsidiary names
    ]
    tier_of = {name: (s, m) for name, s, m in tiers}
    key_origin = {}

    def register(tier, name, ticker, origin, minlen):
        strict, med = tier_of[tier]
        for d, kf in ((strict, key_strict), (med, key_med)):
            k = kf(name)
            if len(k) < minlen:
                continue
            d[k].add(ticker)
            key_origin.setdefault((tier, k), origin)

    for row in uni.itertuples():
        for col, origin in (("company_name", "index"), ("sec_entity_name", "sec"),
                            ("sec_filing_name", "sec_filing"), ("sec_former_name", "sec_former")):
            v = getattr(row, col)
            if isinstance(v, str) and v.strip():
                register("index", v, row.ticker, origin, 2)

    for k, t in aliases["name_to_ticker"].items():
        if len(k) >= 3:
            tier_of["universe_names"][1][k].add(t)
            key_origin.setdefault(("universe_names", k), "universe_name_to_ticker")

    n_viol_used = 0
    for t, names in viol.items():
        if t in FUND_OWNER_TICKERS:
            continue
        for n in names:
            register("violations", n, t, "violations_subsidiary", 7)
            n_viol_used += 1

    # Overrides are indexed twice. key_raw keeps every word, so it only fires on a genuine
    # spelling of the name. key_strict is the tolerant route that lets one entry cover EPA's
    # suffix variants, but it is refused where it collapses to a single non-identifying word:
    # key_strict("NV ENERGY") is "ENERGY", which would hand Berkshire every CAMD owner string
    # that ends in the word Energy, and two of them exist.
    override_keys = {}
    override_raw = {}
    for name, t in OVERRIDES.items():
        if t not in set(uni.ticker):
            raise SystemExit(f"override target {t} is not an index constituent ({name})")
        override_raw[key_raw(name)] = (t, name)
        ks = key_strict(name)
        if ks in NON_IDENTIFYING or len(ks) < 4:
            continue
        override_keys[ks] = (t, name)
    # Blocked on the medium key, which keeps PARTNERS and AMERICA: those words are what
    # separate Ohio Power Partners LLC from AEP's Ohio Power Company.
    blocked_keys = {key_med(n): why for n, why in BLOCKED.items()}
    note_keys = {key_strict(n): why for n, why in UNMATCHED_NOTES.items()}

    print(f"alias index: index/SEC {len(tier_of['index'][0]):,} strict keys, "
          f"universe name map {len(tier_of['universe_names'][1]):,} keys, "
          f"Violation Tracker {len(tier_of['violations'][0]):,} strict keys "
          f"({n_viol_used:,} strings kept, {len(FUND_OWNER_TICKERS)} fund-owner tickers excluded)")
    print(f"overrides {len(override_raw)} ({len(override_keys)} also on the tolerant key), "
          f"blocked {len(blocked_keys)}, "
          f"unmatched notes {len(note_keys)}")
    print()

    # fuzzy candidate pool: word forms of index company names
    pool = defaultdict(set)
    for row in uni.itertuples():
        for col in ("company_name", "sec_entity_name", "sec_filing_name", "sec_former_name"):
            v = getattr(row, col)
            if isinstance(v, str) and v.strip():
                w = words(v)
                if len(w) >= 4:
                    pool[w].add(row.ticker)
    pool_items = list(pool.items())

    def collapse(hits):
        """One ticker, or the primary listing when the hits are share classes of one company."""
        hits = sorted(hits)
        if len(hits) == 1:
            return hits[0]
        ciks = {ticker_to_cik.get(t) for t in hits}
        if len(ciks) == 1 and None not in ciks:
            return primary_by_cik.get(ciks.pop())
        return None

    def fuzzy_match(name):
        q = words(name)
        if not q:
            return None, None, None
        qt = q.split()
        head = qt[0]
        if len(head) < FUZZY_MIN_HEAD_LEN:
            return None, None, None
        best = None
        for cand, tks in pool_items:
            ct = cand.split()
            if ct[0] != head:
                continue
            extra = set(qt) ^ set(ct)
            if extra - GENERIC_TAIL:
                continue
            # One shared generic token is not identity: THE KRAFT GROUP (Rand-Whitney
            # containerboard) collapses to KRAFT and would otherwise take Kraft Foods.
            if len(set(qt) & set(ct)) < 2 and (len(head) < 6 or head in NON_IDENTIFYING):
                continue
            score = fuzz.token_set_ratio(q, cand)
            if score < FUZZY_MIN_SET:
                continue
            t = collapse(tks)
            if t is None:
                continue
            if best is None or score > best[1]:
                best = (t, score, cand)
        return best if best else (None, None, None)

    def resolve(name):
        """-> (ticker, method, alias_source, matched_key, score)."""
        km = key_med(name)
        if km in blocked_keys:
            return None, "blocked", "override_blocklist", km, None
        kr = key_raw(name)
        if kr in override_raw:
            t, src_name = override_raw[kr]
            return t, "manual", "override", kr, None
        ks = key_strict(name)
        if ks in override_keys:
            t, src_name = override_keys[ks]
            return t, "manual", "override", ks, None
        for tier, strict, med in tiers:
            for d, kf in ((strict, key_strict), (med, key_med)):
                k = kf(name)
                hits = d.get(k)
                if not hits:
                    continue
                t = collapse(hits)
                if t is None:
                    return None, "ambiguous", key_origin.get((tier, k), tier), k, None
                if t in FUND_OWNER_TICKERS:
                    return None, "fund_holding", key_origin.get((tier, k), tier), k, None
                return t, "exact", key_origin.get((tier, k), tier), k, None
        t, score, cand = fuzzy_match(name)
        if t:
            if t in FUND_OWNER_TICKERS:
                return None, "fund_holding", "fuzzy_index_name", cand, float(score)
            return t, "fuzzy", "fuzzy_index_name", cand, float(score)
        return None, "unmatched", None, None, None

    # ---------------------------------------------------------------- GHGRP parent strings
    ghgrp_keys = (par.groupby("parent_name_clean")
                     .agg(parent_name_display=("parent_name_display", "first"),
                          parent_name_norm=("parent_name_norm", "first"),
                          tonnes_max=("co2e_tonnes", "max"),
                          years_present=("year", "nunique"))
                     .reset_index())
    t23 = par[par.year == 2023].set_index("parent_name_clean").co2e_tonnes
    ghgrp_keys["tonnes_recent"] = ghgrp_keys.parent_name_clean.map(t23)
    total_2023 = float(t23.sum())
    ghgrp_keys = ghgrp_keys.sort_values("tonnes_recent", ascending=False, na_position="last")

    res = [resolve(r.parent_name_display) for r in ghgrp_keys.itertuples()]
    ghgrp_keys["ticker"] = [a for a, *_ in res]
    ghgrp_keys["match_method"] = [b for _, b, *_ in res]
    ghgrp_keys["alias_source"] = [c for _, _, c, *_ in res]
    ghgrp_keys["matched_key"] = [d for *_, d, _ in res]
    ghgrp_keys["fuzzy_score"] = [e for *_, e in res]
    ghgrp_keys["source"] = "ghgrp_parent"

    print(f"GHGRP: {len(ghgrp_keys):,} distinct parent keys, RY2023 direct-emitter total "
          f"{total_2023/1e6:,.1f} MMT CO2e")
    run = 0.0
    for method in ("manual", "exact", "fuzzy"):
        sel = ghgrp_keys[ghgrp_keys.match_method == method]
        tonnes = float(sel.tonnes_recent.fillna(0).sum())
        run += tonnes
        print(f"  {method:<12} {len(sel):>5,} parent keys {sel.ticker.nunique():>4} tickers  "
              f"{tonnes/1e6:>8,.1f} MMT  cumulative {100*run/total_2023:>5.2f}% of RY2023")
    for method in ("ambiguous", "blocked", "fund_holding", "unmatched"):
        sel = ghgrp_keys[ghgrp_keys.match_method == method]
        print(f"  {method:<12} {len(sel):>5,} parent keys {'':>4}          "
              f"{float(sel.tonnes_recent.fillna(0).sum())/1e6:>8,.1f} MMT")
    print()

    # ---------------------------------------------------------------- CAMD owner strings
    role_tail = re.compile(r"\s*\(([^)]*)\)\s*$")

    def owner_names(raw):
        """CAMD writes 'Name (Owner)|Name (Operator)', sometimes with several owners.

        Roles can carry a date annotation behind them, e.g.
        'Ohio Power Company (Owner/Operator) (Started Aug 20, 2012)', so every trailing
        parenthetical has to come off, not just the last one.
        """
        out = []
        for part in str(raw).split("|"):
            part = part.strip()
            roles = []
            while True:
                m = role_tail.search(part)
                if not m:
                    break
                roles.append(m.group(1).strip().lower())
                part = part[: m.start()].strip()
            if roles and not any("owner" in r for r in roles) and any("operator" in r for r in roles):
                continue
            if part and part not in out:
                out.append(part)
        return out

    camd_owner_rows = []
    for raw, grp in camd.groupby("owner_operator"):
        for nm in owner_names(raw):
            camd_owner_rows.append((nm, raw, grp))
    # Tonnes are booked against an owner string only where CAMD names it as the sole owner.
    # CAMD publishes no ownership percentages, so a jointly owned unit cannot be apportioned
    # from this field; those tonnes are carried separately as an upper bound, never summed in.
    owner_sole_2025 = defaultdict(float)
    owner_joint_2025 = defaultdict(float)
    owner_tonnes_max = defaultdict(float)
    owner_years = defaultdict(set)
    for nm, raw, grp in camd_owner_rows:
        sole = len(owner_names(raw)) == 1
        g = grp.groupby("year").co2_tonnes.sum()
        v25 = float(g.get(2025, 0.0))
        if sole:
            owner_sole_2025[nm] += v25
            owner_tonnes_max[nm] = max(owner_tonnes_max[nm], float(g.max()) if len(g) else 0.0)
        else:
            owner_joint_2025[nm] += v25
        owner_years[nm].update(int(y) for y in g.index)
        owner_sole_2025.setdefault(nm, 0.0)

    names_all = list(owner_sole_2025)
    camd_keys = pd.DataFrame({
        "parent_name_clean": [key_strict(n) for n in names_all],
        "parent_name_display": names_all,
        "parent_name_norm": [words(n) for n in names_all],
        "tonnes_recent": [owner_sole_2025[n] for n in names_all],
        "tonnes_recent_joint": [owner_joint_2025.get(n, 0.0) for n in names_all],
        "tonnes_max": [owner_tonnes_max.get(n, 0.0) for n in names_all],
        "years_present": [len(owner_years[n]) for n in names_all],
    }).sort_values("tonnes_recent", ascending=False)

    res = [resolve(r.parent_name_display) for r in camd_keys.itertuples()]
    camd_keys["ticker"] = [a for a, *_ in res]
    camd_keys["match_method"] = [b for _, b, *_ in res]
    camd_keys["alias_source"] = [c for _, _, c, *_ in res]
    camd_keys["matched_key"] = [d for *_, d, _ in res]
    camd_keys["fuzzy_score"] = [e for *_, e in res]
    camd_keys["source"] = "camd_owner"

    camd_2025 = float(camd[camd.year == 2025].co2_tonnes.sum())
    print(f"CAMD: {len(camd_keys):,} distinct owner strings, 2025 measured total "
          f"{camd_2025/1e6:,.1f} MMT CO2 (CEMS). Tonnes below are sole-owner units only, "
          f"since CAMD publishes no ownership percentages.")
    for method in ("manual", "exact", "fuzzy", "ambiguous", "blocked", "fund_holding",
                   "unmatched"):
        sel = camd_keys[camd_keys.match_method == method]
        if not len(sel):
            continue
        print(f"  {method:<12} {len(sel):>5,} owner strings {sel.ticker.nunique():>4} tickers  "
              f"{sel.tonnes_recent.sum()/1e6:>8,.1f} MMT of 2025 owner-string tonnes")
    print()

    pmap = pd.concat([ghgrp_keys, camd_keys], ignore_index=True)
    pmap["unmatched_note"] = pmap.parent_name_clean.map(note_keys)
    pmap.loc[pmap.match_method == "blocked", "unmatched_note"] = (
        pmap.loc[pmap.match_method == "blocked", "matched_key"].map(blocked_keys))
    pmap.loc[pmap.match_method == "fund_holding", "unmatched_note"] = (
        "named by EPA as the parent but held through managed funds, not consolidated by the "
        "listed manager; a carbon price lands on the portfolio company")
    cols = ["source", "parent_name_display", "parent_name_clean", "parent_name_norm", "ticker",
            "match_method", "alias_source", "matched_key", "fuzzy_score", "tonnes_recent",
            "tonnes_recent_joint", "tonnes_max", "years_present", "unmatched_note"]
    pmap = pmap[[c for c in cols if c in pmap.columns]]
    pmap.to_parquet(INTERIM / "parent_ticker_map.parquet", index=False)
    print(f"wrote parent_ticker_map.parquet  {len(pmap):,} rows x {pmap.shape[1]} cols  "
          f"({int(pmap.ticker.notna().sum()):,} carry a ticker, "
          f"{pmap[pmap.ticker.notna()].ticker.nunique()} distinct tickers)")
    print()

    key_to_ticker = dict(zip(ghgrp_keys.parent_name_clean, ghgrp_keys.ticker))
    key_to_method = dict(zip(ghgrp_keys.parent_name_clean, ghgrp_keys.match_method))
    owner_to_ticker = {r.parent_name_display: r.ticker for r in camd_keys.itertuples()
                       if r.ticker is not None}
    owner_to_method = {r.parent_name_display: r.match_method for r in camd_keys.itertuples()}

    # ---------------------------------------------------------------- GHGRP tonnes per ticker
    f = fac.copy()
    f["ticker"] = f.parent_name_clean.map(key_to_ticker)
    f["match_method"] = f.parent_name_clean.map(key_to_method)
    fm = f[f.ticker.notna()].copy()

    # EPA occasionally lists the same parent twice on one facility, each at 100%. Nobody owns a
    # facility twice, so where one ticker's stakes in one facility-year exceed 100% we scale
    # them back to 100% rather than carry the duplicate through.
    own = fm.groupby(["facility_id", "year", "ticker"]).ownership_frac.sum().rename("own_sum")
    fm = fm.merge(own, on=["facility_id", "year", "ticker"], how="left")
    over = fm.own_sum > 1.01
    before = float(fm.co2e_tonnes_share.fillna(0).sum())
    fm.loc[over, "co2e_tonnes_share"] = (
        fm.loc[over, "co2e_tonnes_share"] / fm.loc[over, "own_sum"])
    dropped = before - float(fm.co2e_tonnes_share.fillna(0).sum())
    print(f"ownership sanity: {int(over.sum())} facility-year-parent rows where one ticker's "
          f"stated stakes exceeded 100%, scaled back to 100% ({dropped/1e6:,.2f} MMT removed "
          f"across all years)")
    print()
    ghgrp_ty = (fm.groupby(["ticker", "year"])
                  .agg(scope1_ghgrp_tonnes=("co2e_tonnes_share", lambda s: s.sum(min_count=1)),
                       facility_count=("facility_id", "nunique"),
                       dq_ghgrp=("dq", "max"))
                  .reset_index())
    ghgrp_method = fm.assign(w=fm.co2e_tonnes_share.fillna(0))[
        ["ticker", "year", "match_method", "w"]]
    ghgrp_top = (ghgrp_method.groupby(["ticker", "year", "match_method"]).w.sum().reset_index()
                 .sort_values("w", ascending=False).drop_duplicates(["ticker", "year"])
                 .rename(columns={"match_method": "ghgrp_match_method"}))
    ghgrp_ty = ghgrp_ty.merge(ghgrp_top[["ticker", "year", "ghgrp_match_method"]],
                              on=["ticker", "year"], how="left")

    cov23 = ghgrp_ty[(ghgrp_ty.year == 2023)]
    nonzero = cov23[cov23.scope1_ghgrp_tonnes.fillna(0) > 0]
    print("GHGRP attribution, reporting year 2023")
    print(f"  tickers with a matched parent            {cov23.ticker.nunique():>4} / 503")
    print(f"  tickers with measured Scope 1 above zero {nonzero.ticker.nunique():>4} / 503")
    print(f"  tonnes on those tickers                  {nonzero.scope1_ghgrp_tonnes.sum()/1e6:>8,.1f} MMT")
    print(f"  share of all US GHGRP direct emissions   {100*nonzero.scope1_ghgrp_tonnes.sum()/total_2023:>8.2f}%")
    print()
    print("  top 25 by RY2023 measured Scope 1, with running coverage")
    run = 0.0
    for i, r in enumerate(nonzero.sort_values("scope1_ghgrp_tonnes", ascending=False)
                                 .head(25).itertuples(), 1):
        run += r.scope1_ghgrp_tonnes
        name = uni.loc[uni.ticker == r.ticker, "company_name"].iloc[0]
        print(f"  {i:>2}. {r.ticker:<6} {name[:26]:<26} {r.scope1_ghgrp_tonnes/1e6:>7.2f} MMT  "
              f"{r.facility_count:>3} fac  {r.ghgrp_match_method:<6} cum {100*run/total_2023:>5.2f}%")
    print()

    # ---------------------------------------------------------------- CAMD tonnes per ticker
    # ORIS -> one GHGRP facility. The crosswalk is many-to-many in both directions; where an
    # ORIS claims several GHGRP facilities we keep the one with the most reported CO2e, because
    # the others are nearly always a co-located non-power unit.
    fac_size = fac.groupby("facility_id").co2e_tonnes.max().rename("fsize")
    xw = xwalk.merge(fac_size, left_on="ghgrp_facility_id", right_index=True, how="left")
    xw = (xw.sort_values("fsize", ascending=False, na_position="last")
            .drop_duplicates("oris_code")[["oris_code", "ghgrp_facility_id"]])
    print(f"crosswalk reduced to one GHGRP facility per ORIS: {len(xw):,} ORIS codes")

    cu = camd[["oris_code", "unit_id", "year", "co2_tonnes", "owner_operator"]].copy()
    cu = cu.merge(xw, on="oris_code", how="left")

    # ownership snapshot: for a CAMD year take the latest GHGRP year for that facility that is
    # not in the future, else the earliest one available.
    fy = fac[["facility_id", "year"]].drop_duplicates().rename(columns={"year": "ghgrp_year"})
    fy["ghgrp_year"] = fy.ghgrp_year.astype("int64")
    fy["facility_id"] = fy.facility_id.astype("int64")
    left = (cu[["ghgrp_facility_id", "year"]].dropna().drop_duplicates()
              .rename(columns={"ghgrp_facility_id": "facility_id"}))
    left["facility_id"] = left.facility_id.astype("int64")
    left["year"] = left.year.astype("int64")
    left = left.sort_values("year")
    snap = pd.merge_asof(left, fy.sort_values("ghgrp_year"), left_on="year",
                         right_on="ghgrp_year", by="facility_id", direction="backward")
    first_year = fy.groupby("facility_id").ghgrp_year.min()
    snap["ghgrp_year"] = snap.ghgrp_year.fillna(snap.facility_id.map(first_year))
    snap = snap.dropna(subset=["ghgrp_year"])
    snap["ghgrp_year"] = snap.ghgrp_year.astype("int64")

    owners = fac[["facility_id", "year", "parent_name_clean", "ownership_frac"]].rename(
        columns={"year": "ghgrp_year"})
    owners["ticker"] = owners.parent_name_clean.map(key_to_ticker)
    owners["match_method"] = owners.parent_name_clean.map(key_to_method)
    owners = owners[owners.ticker.notna()]
    snap_owners = snap.merge(owners, on=["facility_id", "ghgrp_year"], how="inner")

    cu["facility_id"] = cu.ghgrp_facility_id
    cu["year"] = cu.year.astype("int64")
    via_ghgrp = cu.dropna(subset=["facility_id"]).copy()
    via_ghgrp["facility_id"] = via_ghgrp.facility_id.astype("int64")
    via_ghgrp = via_ghgrp.merge(snap_owners, on=["facility_id", "year"], how="inner")
    via_ghgrp["tonnes"] = via_ghgrp.co2_tonnes * via_ghgrp.ownership_frac
    via_ghgrp["frac"] = via_ghgrp.ownership_frac
    via_ghgrp["route"] = "ghgrp_ownership"

    # fallback: units whose ORIS never reached a ticker that way, attributed on the CAMD owner
    # string but only where CAMD names a single owner, because CAMD publishes no percentages.
    done = set(map(tuple, via_ghgrp[["oris_code", "unit_id", "year"]].drop_duplicates().values))
    rest = cu[~cu.set_index(["oris_code", "unit_id", "year"]).index.isin(done)].copy()
    rest_rows = []
    for r in rest.itertuples():
        names = owner_names(r.owner_operator)
        if len(names) != 1:
            continue
        t = owner_to_ticker.get(names[0])
        if t is None or (isinstance(t, float) and np.isnan(t)):
            continue
        rest_rows.append((r.oris_code, r.unit_id, r.year, t, r.co2_tonnes, 1.0,
                          owner_to_method.get(names[0], "exact")))
    via_owner = pd.DataFrame(rest_rows, columns=["oris_code", "unit_id", "year", "ticker",
                                                 "tonnes", "ownership_frac", "match_method"])
    via_owner["frac"] = 1.0
    via_owner["route"] = "camd_owner_string"

    keep_att = ["oris_code", "unit_id", "year", "ticker", "tonnes", "frac", "match_method", "route"]
    camd_att = pd.concat([via_ghgrp[keep_att], via_owner[keep_att]], ignore_index=True)

    camd_tot = camd.groupby("year").co2_tonnes.sum()
    att25 = float(camd_att[camd_att.year == 2025].tonnes.sum())
    print("CAMD attribution")
    print(f"  2025 measured CO2 total                  {camd_tot.get(2025, 0)/1e6:>8,.1f} MMT")
    print(f"  attributed to an S&P 500 ticker          {att25/1e6:>8,.1f} MMT  "
          f"({100*att25/camd_tot.get(2025, 1):.1f}%)")
    for route, grp in camd_att[camd_att.year == 2025].groupby("route"):
        print(f"    via {route:<18} {grp.tonnes.sum()/1e6:>8,.1f} MMT  "
              f"{grp.ticker.nunique():>3} tickers")
    print(f"  2026 H1 attributed                       "
          f"{camd_att[camd_att.year == 2026].tonnes.sum()/1e6:>8,.1f} MMT of "
          f"{camd_tot.get(2026, 0)/1e6:,.1f} MMT")
    print()

    camd_ty = (camd_att.groupby(["ticker", "year"])
               .agg(scope1_camd_tonnes=("tonnes", lambda s: s.sum(min_count=1)),
                    camd_unit_count=("unit_id", "size"))
               .reset_index())
    camd_fac = (camd_att.groupby(["ticker", "year"]).oris_code.nunique()
                .rename("camd_facility_count").reset_index())
    camd_ty = camd_ty.merge(camd_fac, on=["ticker", "year"], how="left")

    # match_method is the route that carries the most tonnes for that ticker-year, across both
    # programmes; match_methods_all lists every route that contributed.
    method_tonnes = (pd.concat([ghgrp_method,
                                camd_att.assign(w=camd_att.tonnes.fillna(0))[
                                    ["ticker", "year", "match_method", "w"]]], ignore_index=True)
                     .groupby(["ticker", "year", "match_method"]).w.sum().reset_index())
    top_method = (method_tonnes.sort_values("w", ascending=False)
                  .drop_duplicates(["ticker", "year"])
                  .rename(columns={"match_method": "match_method"})[
                      ["ticker", "year", "match_method"]])
    all_methods = (method_tonnes.groupby(["ticker", "year"]).match_method
                   .apply(lambda s: "+".join(sorted(set(s)))).reset_index()
                   .rename(columns={"match_method": "match_methods_all"}))

    # ---------------------------------------------------------------- emissions_by_ticker
    years = list(range(int(min(fac.year.min(), camd.year.min())),
                       int(max(fac.year.max(), camd.year.max())) + 1))
    grid = pd.MultiIndex.from_product([sorted(uni.ticker.unique()), years],
                                      names=["ticker", "year"]).to_frame(index=False)
    out = grid.merge(ghgrp_ty, on=["ticker", "year"], how="left")
    out = out.merge(camd_ty, on=["ticker", "year"], how="left")
    out = out.merge(top_method, on=["ticker", "year"], how="left")
    out = out.merge(all_methods, on=["ticker", "year"], how="left")

    covered = set(ghgrp_ty.ticker) | set(camd_ty.ticker)
    out["covered"] = out.ticker.isin(covered)
    out["facility_count"] = out.facility_count.fillna(0).astype("int32")
    out["camd_unit_count"] = out.camd_unit_count.fillna(0).astype("int32")
    out["camd_facility_count"] = out.camd_facility_count.fillna(0).astype("int32")

    # dq, PCAF style. GHGRP carries the reporting lane's own score (1 stated ownership,
    # 2 apportioned because EPA left the percentage blank). CAMD is instrument-measured, so the
    # uncertainty is in the ownership we carry forward from the latest GHGRP year, not in the
    # tonnes: a CAMD year past the last GHGRP year is a 2 for that reason alone.
    max_ghgrp_year = int(fac.year.max())
    dq_camd = np.where(out.scope1_camd_tonnes.notna(),
                       np.where(out.year > max_ghgrp_year, 2, 1), np.nan)
    out["dq_camd"] = dq_camd
    out["dq"] = out[["dq_ghgrp", "dq_camd"]].max(axis=1)
    out.loc[out.scope1_ghgrp_tonnes.isna() & out.scope1_camd_tonnes.isna(),
            ["match_method", "match_methods_all"]] = None
    out = out[["ticker", "year", "scope1_ghgrp_tonnes", "scope1_camd_tonnes", "facility_count",
               "camd_facility_count", "camd_unit_count", "dq", "dq_ghgrp", "dq_camd",
               "match_method", "match_methods_all", "covered"]]
    out = out.merge(uni[["ticker", "company_name", "gics_sector", "is_primary_listing"]],
                    on="ticker", how="left")
    out.to_parquet(INTERIM / "emissions_by_ticker.parquet", index=False)

    have_any = out[out.scope1_ghgrp_tonnes.notna() | out.scope1_camd_tonnes.notna()]
    print(f"wrote emissions_by_ticker.parquet  {len(out):,} rows x {out.shape[1]} cols "
          f"({len(years)} years x {out.ticker.nunique()} tickers)")
    print(f"  rows carrying a measured value           {len(have_any):,}")
    print(f"  tickers covered by GHGRP or CAMD         {len(covered):>4} / 503 "
          f"({100*len(covered)/503:.1f}%)")
    print(f"  tickers with no US reporting facility    {503-len(covered):>4} / 503 "
          f"(null, not zero)")
    print(f"  dq distribution                          "
          f"{dict(out.dq.value_counts(dropna=True).sort_index().astype(int))}")
    print()
    sector = (out[(out.year == 2023) & (out.scope1_ghgrp_tonnes.fillna(0) > 0)]
              .groupby("gics_sector").agg(n=("ticker", "nunique"),
                                          mmt=("scope1_ghgrp_tonnes", "sum")))
    print("  RY2023 measured Scope 1 by GICS sector")
    for r in sector.sort_values("mmt", ascending=False).itertuples():
        print(f"    {r.Index:<24} {r.n:>3} companies {r.mmt/1e6:>8,.1f} MMT")
    print()

    # a few numbers that must hold, so a silent regression fails loudly
    assert 2600e6 <= total_2023 <= 2800e6, f"RY2023 direct-emitter total off: {total_2023}"
    assert float(nonzero.scope1_ghgrp_tonnes.sum()) <= total_2023, "matched exceeds the US total"
    assert set(out.ticker) <= set(uni.ticker), "a ticker outside the index reached the output"
    assert out.groupby(["ticker", "year"]).size().max() == 1, "duplicate ticker-year row"

    # ------------------------------------------------ GHGRP vs CAMD, the same companies twice
    both = out[(out.year == 2023) & (out.scope1_ghgrp_tonnes.fillna(0) > 0)
               & (out.scope1_camd_tonnes.fillna(0) > 0)].copy()
    both["ratio"] = both.scope1_camd_tonnes / both.scope1_ghgrp_tonnes
    power = both[both.ratio > 0.8]
    print("cross-check, RY2023: two independent EPA programmes on the same companies")
    print(f"  companies with both a GHGRP and a CAMD figure   {len(both):>4}")
    print(f"  of those, CAMD covers over 80% of GHGRP         {len(power):>4} "
          f"(power generators, where the stack monitors see nearly everything)")
    print(f"  aggregate CAMD / GHGRP on those companies       "
          f"{power.scope1_camd_tonnes.sum()/power.scope1_ghgrp_tonnes.sum():>7.3f}")
    print(f"  median company-level ratio                      {power.ratio.median():>7.3f}")
    print()

    # ---------------------------------------------------------------- unmatched worklist
    # GHGRP side: parent strings that reached no ticker, weighted by RY2023 tonnes.
    g_un = pmap[(pmap.source == "ghgrp_parent")
                & pmap.match_method.isin(["unmatched", "ambiguous", "blocked",
                                          "fund_holding"])].copy()
    g_un["tonnes_recent"] = g_un.tonnes_recent.fillna(0.0)
    g_un = g_un[(g_un.tonnes_recent > 0) | (g_un.tonnes_max.fillna(0) > 0)]
    g_un = g_un.sort_values("tonnes_recent", ascending=False)
    g_un["share_of_source_total_pct"] = 100 * g_un.tonnes_recent / total_2023

    # CAMD side: tonnes that neither route reached, which is not the same as an owner string
    # that failed the name match. La Frontera Holdings never matches by name, but its three
    # plants are attributed to VST through EPA's own parent field, so it is not a miss.
    att_frac = (camd_att.groupby(["oris_code", "unit_id", "year"]).frac.sum()
                .clip(upper=1.0).rename("att_frac").reset_index())
    c25 = camd[(camd.year == 2025) & camd.co2_tonnes.notna()].copy()
    c25 = c25.merge(att_frac, on=["oris_code", "unit_id", "year"], how="left")
    c25["att_frac"] = c25.att_frac.fillna(0.0)
    c25["lost_tonnes"] = c25.co2_tonnes * (1 - c25.att_frac)
    lost = c25[c25.lost_tonnes > 0]
    c_un = (lost.groupby("owner_operator")
                .agg(tonnes_recent=("lost_tonnes", "sum"), units=("unit_id", "size"),
                     oris=("oris_code", "nunique"))
                .reset_index().sort_values("tonnes_recent", ascending=False))
    names_first = [owner_names(r) for r in c_un.owner_operator]
    c_un["parent_name_display"] = [
        n[0] if len(n) == 1 else (f"{n[0]} (+{len(n)-1} co-owners)" if n else raw)
        for n, raw in zip(names_first, c_un.owner_operator)]
    c_un["parent_name_clean"] = [key_strict(n[0]) if n else "" for n in names_first]
    c_un["source"] = "camd_owner_unattributed"
    c_un["match_method"] = "unattributed"
    c_un["tonnes_max"] = np.nan
    c_un["years_present"] = np.nan
    c_un["unmatched_note"] = c_un.parent_name_clean.map(note_keys)
    c_un["share_of_source_total_pct"] = 100 * c_un.tonnes_recent / camd_2025

    keep = ["source", "parent_name_display", "parent_name_clean", "tonnes_recent", "tonnes_max",
            "share_of_source_total_pct", "years_present", "match_method", "unmatched_note"]
    un_out = pd.concat([g_un[keep], c_un[keep]], ignore_index=True).rename(columns={
        "tonnes_recent": "tonnes_2023_ghgrp_or_2025_camd", "tonnes_max": "tonnes_largest_year"})
    un_out.to_csv(INTERIM / "unmatched_top_emitters.csv", index=False)
    print(f"wrote unmatched_top_emitters.csv  {len(un_out):,} rows "
          f"({len(g_un):,} GHGRP parent strings, {len(c_un):,} CAMD owner groups)")
    print(f"  unmatched GHGRP RY2023 tonnes            "
          f"{g_un.tonnes_recent.sum()/1e6:>8,.1f} MMT = "
          f"{100*g_un.tonnes_recent.sum()/total_2023:.1f}% of the US regulated total")
    print(f"  unattributed CAMD 2025 tonnes            "
          f"{c_un.tonnes_recent.sum()/1e6:>8,.1f} MMT = "
          f"{100*c_un.tonnes_recent.sum()/camd_2025:.1f}% of measured US power CO2")
    print()
    print("  top 20 unmatched GHGRP parents (the honesty slide)")
    for r in g_un.head(20).itertuples():
        note = r.unmatched_note or "unclassified"
        print(f"    {r.tonnes_recent/1e6:>7.2f} MMT  {r.parent_name_display[:44]:<44} {note}")
    print()
    print("  top 12 unattributed CAMD owners, 2025")
    for r in c_un.head(12).itertuples():
        note = r.unmatched_note or "unclassified"
        print(f"    {r.tonnes_recent/1e6:>7.2f} MMT  {r.parent_name_display[:44]:<44} {note}")
    print()

    # ---------------------------------------------------------------- provenance
    prov = {
        "lane": "entity_resolution",
        "script": "src/match_parents.py",
        "generated_at": t_start.isoformat(),
        "network_io": "none; every input is an artifact another lane fetched and attested",
        "method": {
            "normalisation": [
                "parenthetical annotations dropped before keying",
                "key_strict = the GHGRP lane's parent_key (upper, & -> AND, punctuation dropped, "
                "legal-form and geography words dropped, whitespace removed)",
                "key_med = same but only legal-form words dropped, so it lines up with the "
                "universe lane's name_to_ticker keys",
            ],
            "tiers": ["manual override", "index/SEC registrant and former names",
                      "universe name_to_ticker (includes 218 SEC former registrant names)",
                      "Violation Tracker subsidiary names", "rapidfuzz fuzzy"],
            "fuzzy": {
                "scorer": "rapidfuzz token_set_ratio",
                "threshold": FUZZY_MIN_SET,
                "guards": [
                    "first significant token must match exactly",
                    "every differing token must be a generic corporate tail word",
                    "candidate must resolve to exactly one company",
                ],
                "why": "token_set_ratio alone returns 100 for any subset, which on this data "
                       "means OLD DOMINION ELECTRIC COOPERATIVE matches Old Dominion Freight "
                       "Line and PORTLAND GENERAL ELECTRIC matches General Electric",
            },
            "share_classes": "hits that differ only by share class collapse to the primary "
                             "listing; anything else ambiguous is left unmatched and counted",
            "fund_owners": {
                "tickers": sorted(FUND_OWNER_TICKERS),
                "rule": "excluded from every automatic route. Where EPA names one of these as a "
                        "facility parent the tonnes are left unattributed, because the asset sits "
                        "in a managed fund rather than on the manager's own income statement. "
                        "Berkshire Hathaway is deliberately not on the list: Berkshire Hathaway "
                        "Energy is consolidated in its 10-K.",
            },
            "camd": "ORIS -> GHGRP facility (crosswalk, one facility per ORIS) -> GHGRP parent "
                    "ownership from the latest reporting year not in the future; fallback to "
                    "the CAMD owner string only where CAMD names a single owner",
        },
        "inputs": [],
        "outputs": {},
        "licence": {
            "epa_ghgrp_camd": "US federal government work, public domain (17 U.S.C. 105). "
                              "Derived numbers may be published with attribution to EPA.",
            "sec_and_index": "SEC data is public domain; the constituents list is ODC-PDDL-1.0. "
                             "Derived numbers may be published.",
            "violation_tracker": "Subsidiary-name aliases are derived from Violation Tracker "
                                 "(Good Jobs First) record-level pages and are used here only as "
                                 "an internal join key. We may publish per-company aggregates "
                                 "with the credit line 'Violation Tracker, Good Jobs First' but "
                                 "must not republish the record-level table.",
        },
        "redistribution": "Every number this lane emits is derived from public-domain EPA and "
                          "SEC filings and may be published. The alias strings borrowed from "
                          "Violation Tracker are an internal join key and are not republished; "
                          "only the ticker they resolve to is carried forward.",
    }
    for name, path in inputs.items():
        prov["inputs"].append({
            "name": name,
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": sha256_of(path),
        })
    for name in ("parent_ticker_map.parquet", "emissions_by_ticker.parquet",
                 "unmatched_top_emitters.csv"):
        p = INTERIM / name
        prov["outputs"][name] = {"bytes": p.stat().st_size, "sha256": sha256_of(p)}
    prov["coverage"] = {
        "ghgrp_ry2023_total_tonnes": total_2023,
        "tickers_matched_any_parent": int(pmap[pmap.ticker.notna()].ticker.nunique()),
        "tickers_ghgrp_2023_nonzero": int(nonzero.ticker.nunique()),
        "ghgrp_2023_tonnes_matched": float(nonzero.scope1_ghgrp_tonnes.sum()),
        "ghgrp_2023_share_matched_pct": float(100 * nonzero.scope1_ghgrp_tonnes.sum() / total_2023),
        "camd_2025_total_tonnes": camd_2025,
        "camd_2025_tonnes_attributed": att25,
        "camd_2025_share_attributed_pct": float(100 * att25 / camd_2025),
        "tickers_covered": len(covered),
    }
    PROV.parent.mkdir(parents=True, exist_ok=True)
    PROV.write_text(json.dumps(prov, indent=2))
    print(f"wrote provenance/entity_resolution.json  {len(prov['inputs'])} inputs, "
          f"{len(prov['outputs'])} outputs")
    print(f"runtime {(datetime.now(timezone.utc)-t_start).total_seconds():.1f}s, no network I/O")


if __name__ == "__main__":
    main()
