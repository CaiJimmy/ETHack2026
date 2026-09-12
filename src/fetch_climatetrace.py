#!/usr/bin/env python3
"""Climate TRACE asset emissions rolled up to S&P 500 parents, to size the non-US blind spot.

EPA GHGRP and CAMD only see facilities on US soil. A company whose plants are mostly abroad
therefore looks clean in our spine for a reason that has nothing to do with its carbon. This
lane measures how large that hole is per company.

Climate TRACE publishes global, facility-level modelled emissions plus an ownership layer that
resolves each asset up a named corporate chain. The bulk sector packages carry that ownership
layer as its own CSV (the country packages do not, which is what earlier scouting reported),
and it is global, so it gives the one thing GHGRP structurally cannot: the foreign assets of
US-listed parents.

Two things about the ownership layer decide the whole design:

  * Rows exist for every ancestor in the chain, so the same asset appears under the operating
    subsidiary AND under the listed parent. Dedupe on (ticker, source_id) or Duke Energy's
    fleet counts three times.
  * The chain traces equity, so passive index stakes propagate down it and State Street ends
    up "owning" 1,399 power assets in 69 countries. Any intermediate hop below 50% is a
    portfolio holding, not consolidation, and is dropped. The final hop is company-to-asset
    partial ownership and is legitimate.

The bulk packages are used rather than the v6 /assets API. The API pages fine and carries the
same ownership layer, but it returns one unlabelled emissions figure per asset with no year axis,
while the bulk files are monthly from 2021 to mid-2026. There is no company-rollup endpoint on
either route, so the roll-up is ours.

This is modelled data and it is tagged as such. It never enters the headline score; it is a
cross-check on the measured spine and a quantified caveat on its geography.
"""

import collections
import csv
import hashlib
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "climatetrace"
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance" / "climatetrace.json"

sys.path.insert(0, str(ROOT / "src"))
from fetch_epa_ghgrp import parent_key as ghgrp_parent_key  # noqa: E402
from overrides_parent_ticker import BLOCKED, FUND_OWNER_TICKERS, OVERRIDES  # noqa: E402

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
BASE = "https://downloads.climatetrace.org/latest/sector_packages/co2e_100yr"

# The four packages whose subsectors carry an ownership CSV. transportation, waste and
# buildings were checked and are not worth the gigabyte: waste and buildings ship no ownership
# file at all, and transportation's two aviation ownership files have an empty parent_name on
# all 33,637 rows. Checked by reading their zip central directories over HTTP range requests
# rather than downloading 1.35 GB to find out.
PACKAGES = ["power", "manufacturing", "fossil_fuel_operations", "mineral_extraction"]

# Climate TRACE publishes a per-asset per-month confidence rating for emissions_quantity.
# Mapped onto the PCAF data-quality scale the rest of the repo uses. Nothing here is company
# reported, so nothing scores better than 3 (physical-activity estimate).
DQ_FROM_CONFIDENCE = {"very high": 3, "high": 3, "medium": 4, "low": 5, "very low": 5}
DQ_DEFAULT = 4

# Climate TRACE parent strings that the shared alias map resolves to the wrong S&P 500 company.
# Each was read back to the asset it claims before being blocked. They are kept here rather than
# in src/overrides_parent_ticker.py because they are Climate TRACE spellings that the EPA lane
# never sees, and that file belongs to the entity-resolution lane.
CT_BLOCKED = {
    "Zimmer Partners LP": "New York hedge fund holding 8.7% of Hawaiian Electric. Collides with "
                          "ZBH because Zimmer Biomet's SEC former name is Zimmer Holdings Inc",
    "APA Group": "Australian gas-infrastructure trust (ASX: APA) owning Diamantina, Leichhardt "
                 "and Newman power stations in Queensland and WA. Not APA Corporation, the "
                 "Houston oil and gas producer",
    "Vistra Group Holdings SA": "Luxembourg corporate-services firm; the chain runs through "
                                "Vistra ITCL (India) into JSW steel plants. Not Vistra Corp",
    "Vulcan Materials LLC": "owns 99.99% of Sohar Steel in Oman. Not Vulcan Materials Company, "
                            "the US aggregates producer",
    "SCG Group": "Siam Cement Group, Thailand, named on two Southeast Asian steam crackers. "
                 "Collides with ON Semiconductor, whose SEC former name is SCG Holding Corp",
}

# Climate TRACE spellings that belong to a different index member than the alias map picks.
CT_OVERRIDES = {
    # Philip Morris USA is Altria's domestic operating company. Philip Morris International (PM)
    # was spun out of it in 2008 and owns no US plant, so the Park 500 facility is Altria's.
    "Philip Morris USA Inc": "MO",
}

PAREN = re.compile(r"\([^)]*\)?")
LEGAL = re.compile(
    r"\b(CORPORATION|CORP|COMPANY|COMPANIES|CO|COS|INCORPORATED|INC|LLC|LLP|LP|LTD|PLC"
    r"|HOLDINGS|HOLDING|GROUP|THE|PBC|NV|SA|AG|SE|TRUST|CLASS)\b"
)
HOP = re.compile(r"\[(?:([0-9.]+)%|unknown %)\]")


def words(name):
    s = PAREN.sub(" ", str(name).upper()).replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\s+", " ", LEGAL.sub(" ", s)).strip()


def key_med(name):
    return words(name).replace(" ", "")


def key_raw(name):
    return re.sub(r"[^A-Z0-9]", "", PAREN.sub(" ", str(name).upper()).replace("&", " AND "))


def key_strict(name):
    return ghgrp_parent_key(PAREN.sub(" ", str(name)))


def hops(path):
    """Ownership fractions along the chain. None where Climate TRACE writes 'unknown %'."""
    return [(float(m.group(1)) / 100 if m.group(1) else None) for m in HOP.finditer(path or "")]


def is_portfolio_stake(path):
    """True when a company-to-company hop is a minority holding rather than consolidation."""
    inter = hops(path)[:-1]
    return any(x is not None and x < 0.5 for x in inter)


def path_share(path):
    """Product of the chain. An unknown hop is treated as 1.0, which overstates, so it is counted."""
    f = 1.0
    for x in hops(path):
        if x is not None:
            f *= x
    return f


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name, records):
    """Download one sector package if it is not already on disk. Idempotent by file presence."""
    url = f"{BASE}/{name}.zip"
    dest = RAW / f"{name}.zip"
    cached = dest.exists()
    if not cached:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as out:
            status = resp.status
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        secs = time.time() - t0
    else:
        status, secs = None, 0.0
    size = dest.stat().st_size
    records.append({
        "url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "http_status": status,
        "bytes": size,
        "sha256": sha256_of(dest),
        "cached": cached,
    })
    print(f"  {name:<24} {size/1e6:>7.1f} MB  {'cached' if cached else f'{secs:.1f}s'}")
    return dest


def build_resolver():
    """parent_name -> ticker, reusing the alias map and the override table the EPA lane built.

    Tiers, most trustworthy first. The EPA tier matters because Climate TRACE names assets
    under operating subsidiaries (Florida Power & Light Co, Luminant Generation Company LLC)
    and those exact strings already carry a hand-audited ticker in parent_ticker_map.
    """
    uni = pd.read_parquet(INTERIM / "universe.parquet")
    aliases = json.loads((INTERIM / "ticker_aliases.json").read_text())
    pmap = pd.read_parquet(INTERIM / "parent_ticker_map.parquet")

    ticker_to_cik = aliases["ticker_to_cik"]
    primary_by_cik = aliases["primary_ticker_by_cik"]

    strict = collections.defaultdict(set)
    med = collections.defaultdict(set)
    epa = collections.defaultdict(set)

    for row in uni.itertuples():
        for col in ("company_name", "sec_entity_name", "sec_filing_name", "sec_former_name"):
            v = getattr(row, col)
            if not (isinstance(v, str) and v.strip()):
                continue
            if len(key_strict(v)) >= 2:
                strict[key_strict(v)].add(row.ticker)
            if len(key_med(v)) >= 2:
                med[key_med(v)].add(row.ticker)
    for k, t in aliases["name_to_ticker"].items():
        if len(k) >= 3:
            med[k].add(t)
    n_epa = 0
    for row in pmap[pmap.ticker.notna()].itertuples():
        k = key_med(row.parent_name_display)
        if len(k) >= 4:
            epa[k].add(row.ticker)
            n_epa += 1

    index_tickers = set(uni.ticker)
    override_raw = {}
    override_strict = {}
    for name, t in OVERRIDES.items():
        if t not in index_tickers:
            raise SystemExit(f"override target {t} is not an index constituent ({name})")
        override_raw[key_raw(name)] = t
        ks = key_strict(name)
        if len(ks) >= 4:
            override_strict[ks] = t
    blocked = {key_med(n) for n in BLOCKED}
    ct_blocked = {key_raw(n) for n in CT_BLOCKED}
    ct_override = {key_raw(n): t for n, t in CT_OVERRIDES.items()}

    def collapse(hits):
        hits = sorted(hits)
        if len(hits) == 1:
            return hits[0]
        ciks = {ticker_to_cik.get(t) for t in hits}
        if len(ciks) == 1 and None not in ciks:
            return primary_by_cik.get(ciks.pop())
        return None

    def resolve(name):
        if key_raw(name) in ct_blocked:
            return None, "blocked"
        if key_raw(name) in ct_override:
            return ct_override[key_raw(name)], "manual"
        if key_med(name) in blocked:
            return None, "blocked"
        if key_raw(name) in override_raw:
            return override_raw[key_raw(name)], "manual"
        if key_strict(name) in override_strict:
            return override_strict[key_strict(name)], "manual"
        for table, keyfn, tag in ((strict, key_strict, "exact_index"),
                                  (med, key_med, "exact_alias"),
                                  (epa, key_med, "exact_epa_parent")):
            hits = table.get(keyfn(name))
            if not hits:
                continue
            t = collapse(hits)
            if t is None:
                return None, "ambiguous"
            if t in FUND_OWNER_TICKERS:
                return None, "fund_holding"
            return t, tag
        return None, "unmatched"

    print(f"alias index: {len(strict):,} strict keys and {len(med):,} medium keys from the "
          f"universe and alias map, {len(epa):,} keys from {n_epa:,} EPA parent strings already "
          f"resolved by match_parents.py")
    print(f"overrides {len(override_raw)} shared plus {len(ct_override)} Climate TRACE only, "
          f"blocked {len(blocked)} shared plus {len(ct_blocked)} Climate TRACE only, "
          f"fund-owner tickers excluded {len(FUND_OWNER_TICKERS)}")
    return resolve, uni


def read_ownership(paths):
    """Every ownership row from every package, tagged with the file it came from."""
    rows = []
    subsectors = collections.defaultdict(set)
    for p in paths:
        z = zipfile.ZipFile(p)
        for n in z.namelist():
            if "_emissions_sources_ownership_" not in n:
                continue
            sub = n.split("/")[-1].split("_emissions_sources_ownership")[0]
            subsectors[p.stem].add(sub)
            with z.open(n) as fh:
                rows.extend(csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace")))
    return rows, subsectors


def read_emissions(paths, subsectors, wanted):
    """Sum co2e_100yr per source per year for the assets we attributed, plus their metadata.

    Only the subsectors that have an ownership file are read; the others cannot reach a ticker
    and one of them (food-beverage-tobacco) is 378 MB on its own.
    """
    emis = collections.defaultdict(lambda: collections.defaultdict(float))
    months = collections.defaultdict(lambda: collections.defaultdict(int))
    meta = {}
    for p in paths:
        z = zipfile.ZipFile(p)
        for n in z.namelist():
            if "_emissions_sources_v" not in n:
                continue
            sub = n.split("/")[-1].split("_emissions_sources_v")[0]
            if sub not in subsectors[p.stem]:
                continue
            with z.open(n) as fh:
                r = csv.reader(io.TextIOWrapper(fh, "utf-8", errors="replace"))
                head = next(r)
                i = {c: j for j, c in enumerate(head)}
                sid, st, eq = i["source_id"], i["start_time"], i["emissions_quantity"]
                iso, sec, sub_i, nm = i["iso3_country"], i["sector"], i["subsector"], i["source_name"]
                for row in r:
                    s = row[sid]
                    if s not in wanted:
                        continue
                    y = row[st][:4]
                    emis[s][y] += float(row[eq] or 0)
                    months[s][y] += 1
                    if s not in meta:
                        meta[s] = (row[iso], row[sec], row[sub_i], row[nm])
    return emis, months, meta


def read_confidence(paths, subsectors, wanted):
    """Worst monthly emissions-confidence per source-year, mapped to a PCAF dq score."""
    dq = collections.defaultdict(dict)
    for p in paths:
        z = zipfile.ZipFile(p)
        for n in z.namelist():
            if "_emissions_sources_confidence_" not in n:
                continue
            sub = n.split("/")[-1].split("_emissions_sources_confidence")[0]
            if sub not in subsectors[p.stem]:
                continue
            with z.open(n) as fh:
                r = csv.reader(io.TextIOWrapper(fh, "utf-8", errors="replace"))
                head = next(r)
                i = {c: j for j, c in enumerate(head)}
                sid, st, eq = i["source_id"], i["start_time"], i["emissions_quantity"]
                for row in r:
                    s = row[sid]
                    if s not in wanted:
                        continue
                    y = row[st][:4]
                    v = DQ_FROM_CONFIDENCE.get(row[eq].strip().lower(), DQ_DEFAULT)
                    if v > dq[s].get(y, 0):
                        dq[s][y] = v
    return dq


def main():
    t_start = datetime.now(timezone.utc)
    RAW.mkdir(parents=True, exist_ok=True)
    PROV.parent.mkdir(parents=True, exist_ok=True)

    print("Climate TRACE v5.10.0 sector packages -> S&P 500 parents")
    print(f"started {t_start.isoformat()}")
    print()

    records = []
    print("sector packages")
    paths = [fetch(name, records) for name in PACKAGES]
    print()

    own, subsectors = read_ownership(paths)
    n_sub = sum(len(v) for v in subsectors.values())
    print(f"ownership rows {len(own):,} over {n_sub} subsectors, "
          f"{len({r['parent_name'].strip() for r in own}):,} distinct parent names, "
          f"{len({r['source_id'] for r in own}):,} distinct assets")

    resolve, uni = build_resolver()
    names = sorted({r["parent_name"].strip() for r in own})
    resolved = {n: resolve(n) for n in names}
    by_method = collections.Counter(m for _, m in resolved.values())
    print(f"name resolution over {len(names):,} distinct parent names: "
          + "  ".join(f"{k} {v:,}" for k, v in by_method.most_common()))
    print()

    # ---------------------------------------------------------------- attribution
    # (ticker, source_id) -> best equity share, its method, and the chain that produced it.
    link = {}
    n_portfolio = 0
    n_rows_matched = 0
    for r in own:
        name = r["parent_name"].strip()
        ticker, method = resolved[name]
        if ticker is None:
            continue
        n_rows_matched += 1
        if is_portfolio_stake(r["ownership_path"]):
            n_portfolio += 1
            continue
        try:
            share = float(r["overall_share_percent"]) / 100
            share_src = "reported"
        except (TypeError, ValueError):
            share = path_share(r["ownership_path"])
            share_src = "path_product"
        share = min(max(share, 0.0), 1.0)
        k = (ticker, r["source_id"])
        prev = link.get(k)
        if prev is None or share > prev[0]:
            link[k] = (share, method, share_src, name)

    dropped_tickers = sorted({resolved[r["parent_name"].strip()][0] for r in own
                              if resolved[r["parent_name"].strip()][0]
                              and is_portfolio_stake(r["ownership_path"])}
                             - {t for t, _ in link})
    print(f"ownership rows resolving to an S&P 500 ticker: {n_rows_matched:,}")
    print(f"  dropped as a minority-stake chain (an intermediate hop under 50%): {n_portfolio:,}")
    print(f"  kept as consolidated or direct asset ownership: {len(link):,} ticker-asset pairs")
    if dropped_tickers:
        print(f"  tickers that survive only as portfolio holders and are therefore now absent: "
              f"{', '.join(dropped_tickers)}")
    print()

    wanted = {sid for _, sid in link}
    emis, months, meta = read_emissions(paths, subsectors, wanted)
    dq_by_source = read_confidence(paths, subsectors, wanted)
    missing = wanted - set(emis)
    print(f"assets attributed {len(wanted):,}, with an emissions record {len(emis):,}, "
          f"absent from the emissions files {len(missing):,}")
    years = sorted({y for v in emis.values() for y in v})
    print(f"years present {years[0]}-{years[-1]}")
    print()

    # Which subsectors can the non-US split be trusted in. Climate TRACE names an owner on every
    # US refinery and cement kiln but on none of its 352 US oil-and-gas-production assets and none
    # of its 352 US oil-and-gas-transport assets, while it does name owners on the equivalent
    # assets abroad. In those subsectors a company's non-US share is 100% by construction, which
    # is a property of the ownership layer and not a fact about the company.
    us_owned, any_owned = collections.defaultdict(int), collections.defaultdict(int)
    for r in own:
        any_owned[r["source_subsector"]] += 1
        if r["iso3_country"] == "USA":
            us_owned[r["source_subsector"]] += 1
    balanced = {k for k in any_owned if us_owned[k] > 0}
    unbalanced = sorted(set(any_owned) - balanced)
    print(f"subsectors whose ownership layer names a US asset: {len(balanced)} of {len(any_owned)}")
    print(f"  US-blind subsectors, where a non-US share of 100% is an artefact: "
          f"{', '.join(unbalanced)}")
    print()

    # ---------------------------------------------------------------- long table
    rows = []
    for (ticker, sid), (share, method, share_src, _) in link.items():
        if sid not in emis:
            continue
        iso, sector, subsector, _ = meta[sid]
        for year, tonnes in emis[sid].items():
            rows.append({
                "ticker": ticker,
                "year": int(year),
                "sector": sector,
                "subsector": subsector,
                "iso3_country": iso,
                "source_id": sid,
                "tonnes": tonnes,
                "equity_tonnes": tonnes * share,
                "months": months[sid][year],
                "dq": dq_by_source.get(sid, {}).get(year, DQ_DEFAULT),
                "match_method": method,
                "share_source": share_src,
            })
    asset = pd.DataFrame(rows)
    print(f"asset-year rows attributed {len(asset):,}")

    method_rank = {"manual": 0, "exact_index": 1, "exact_alias": 2, "exact_epa_parent": 3}
    grp = ["ticker", "year", "sector", "subsector", "iso3_country"]
    out = (asset.groupby(grp, as_index=False)
                .agg(emissions_tonnes_co2e=("tonnes", "sum"),
                     equity_share_tonnes_co2e=("equity_tonnes", "sum"),
                     asset_count=("source_id", "nunique"),
                     months_covered=("months", "max"),
                     dq_raw=("dq", "mean"),
                     match_method=("match_method", lambda s: min(s, key=lambda m: method_rank[m])),
                     match_methods_all=("match_method", lambda s: ",".join(sorted(set(s))))))
    out["dq"] = out.dq_raw.round().clip(3, 5).astype("int8")
    out = out.drop(columns=["dq_raw"])
    out["is_us"] = out.iso3_country == "USA"
    out["subsector_us_ownership"] = out.subsector.isin(balanced)
    out["provenance_class"] = "modelled"
    out["source_release"] = "climate_trace_v5.10.0"

    uni_small = uni[["ticker", "company_name", "gics_sector", "is_primary_listing"]]
    out = out.merge(uni_small, on="ticker", how="left")
    out = out[["ticker", "company_name", "gics_sector", "is_primary_listing", "year", "sector",
               "subsector", "iso3_country", "is_us", "subsector_us_ownership",
               "emissions_tonnes_co2e", "equity_share_tonnes_co2e", "asset_count",
               "months_covered", "dq", "match_method", "match_methods_all", "provenance_class",
               "source_release"]]
    out = out.sort_values(["ticker", "year", "sector", "subsector", "iso3_country"])
    out.to_parquet(INTERIM / "climatetrace_company.parquet", index=False)
    print(f"wrote climatetrace_company.parquet  {len(out):,} rows x {out.shape[1]} cols  "
          f"{out.ticker.nunique()} tickers, {out.iso3_country.nunique()} countries, "
          f"{out.subsector.nunique()} subsectors")
    print()

    # ---------------------------------------------------------------- the non-US share
    # Equity share is the basis, not the gross asset total. Gross counts a whole Qatari LNG train
    # against every partner in it, so ConocoPhillips and ExxonMobil each carry the same 29.2 MMT
    # and the 75 attributed tickers sum to four times US national emissions. Gross stays in the
    # table because it is what Climate TRACE publishes per asset; every ratio below uses equity.
    def agg(d):
        bal = d[d.subsector_us_ownership]
        return pd.Series({
            "ct_gross_tonnes": d.emissions_tonnes_co2e.sum(),
            "ct_tonnes": d.equity_share_tonnes_co2e.sum(),
            "ct_us_tonnes": d.loc[d.is_us, "equity_share_tonnes_co2e"].sum(),
            "ct_nonus_tonnes": d.loc[~d.is_us, "equity_share_tonnes_co2e"].sum(),
            "ct_tonnes_balanced": bal.equity_share_tonnes_co2e.sum(),
            "ct_us_tonnes_balanced": bal.loc[bal.is_us, "equity_share_tonnes_co2e"].sum(),
            "ct_nonus_tonnes_balanced": bal.loc[~bal.is_us, "equity_share_tonnes_co2e"].sum(),
            "asset_count": d.asset_count.sum(),
            "country_count": d.iso3_country.nunique(),
            "nonus_country_count": d.loc[~d.is_us, "iso3_country"].nunique(),
            "months_covered": d.months_covered.max(),
            "dq": d.dq.max(),
        })

    per = out.groupby(["ticker", "year"], as_index=False).apply(agg, include_groups=False)
    per["ct_nonus_share"] = (per.ct_nonus_tonnes / per.ct_tonnes).where(per.ct_tonnes > 0)
    per["ct_nonus_share_balanced"] = (per.ct_nonus_tonnes_balanced / per.ct_tonnes_balanced
                                      ).where(per.ct_tonnes_balanced > 0)

    epa = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    epa = epa[["ticker", "year", "scope1_ghgrp_tonnes", "scope1_camd_tonnes", "covered"]]
    per = per.merge(epa, on=["ticker", "year"], how="left")
    per = per.rename(columns={"scope1_ghgrp_tonnes": "epa_us_scope1_tonnes",
                              "scope1_camd_tonnes": "camd_us_co2_tonnes"})
    per["has_epa_scope1"] = per.epa_us_scope1_tonnes.notna() & (per.epa_us_scope1_tonnes > 0)

    # The cross-source answer, and the one that does not depend on Climate TRACE's US inventory:
    # EPA measures the United States, Climate TRACE supplies everywhere else, and the two do not
    # overlap geographically.
    per["nonus_multiple_of_epa_us"] = (per.ct_nonus_tonnes / per.epa_us_scope1_tonnes
                                       ).where(per.has_epa_scope1)
    per["implied_global_scope1_tonnes"] = (per.epa_us_scope1_tonnes + per.ct_nonus_tonnes
                                           ).where(per.has_epa_scope1)
    # Calibration: how much of the company's measured US Scope 1 Climate TRACE itself sees.
    per["ct_us_vs_epa_us"] = (per.ct_us_tonnes / per.epa_us_scope1_tonnes).where(per.has_epa_scope1)
    per["provenance_class"] = "modelled"
    per = per.merge(uni_small, on="ticker", how="left")
    per = per.sort_values(["ticker", "year"])
    per.to_parquet(INTERIM / "climatetrace_nonus_share.parquet", index=False)
    print(f"wrote climatetrace_nonus_share.parquet  {len(per):,} rows x {per.shape[1]} cols")
    print()

    # A quarter of a megatonne, ten times the GHGRP reporting threshold. Without it the ranking
    # is topped by companies whose entire Climate TRACE presence is one small foreign asset.
    FLOOR = 250_000
    YEAR = 2023  # the last year with both GHGRP Scope 1 and Climate TRACE

    sel = per[per.year == YEAR]
    both = sel[sel.has_epa_scope1]
    print(f"=== {YEAR}, the last year carrying both measured GHGRP Scope 1 and Climate TRACE ===")
    print(f"tickers with Climate TRACE assets {len(sel)}, of which {len(both)} also carry a "
          f"measured EPA Scope 1 number")
    print(f"equity-share Climate TRACE emissions {sel.ct_tonnes.sum()/1e6:,.1f} MMT "
          f"(gross asset totals would be {sel.ct_gross_tonnes.sum()/1e6:,.1f} MMT, which "
          f"double-counts joint ventures), of which "
          f"{sel.ct_nonus_tonnes.sum()/1e6:,.1f} MMT "
          f"({100*sel.ct_nonus_tonnes.sum()/sel.ct_tonnes.sum():.1f}%) sits outside the US")
    dom = both[both.ct_nonus_tonnes == 0]
    print(f"of the {len(both)} with both, {len(both)-len(dom)} have foreign assets in Climate "
          f"TRACE and {len(dom)} are entirely domestic in its view")
    print()

    rank = both[both.ct_nonus_tonnes >= FLOOR].sort_values("ct_nonus_share", ascending=False)
    print(f"ten S&P 500 names with the largest non-US share of their Climate TRACE emissions, "
          f"{YEAR}")
    print(f"(equity share basis, at least {FLOOR:,} t abroad, EPA Scope 1 present)")
    print(f"{'ticker':<7}{'company':<24}{'non-US':>8}{'bal':>7}{'CT tot':>9}{'CT nonUS':>10}"
          f"{'EPA US':>9}{'CT/EPA US':>11}{'assets':>8}{'countries':>10}")
    for r in rank.head(10).itertuples():
        bal = "n/a" if pd.isna(r.ct_nonus_share_balanced) else f"{100*r.ct_nonus_share_balanced:.0f}%"
        seen = "n/a" if pd.isna(r.ct_us_vs_epa_us) else f"{100*r.ct_us_vs_epa_us:.0f}%"
        print(f"{r.ticker:<7}{str(r.company_name)[:22]:<24}{100*r.ct_nonus_share:>7.1f}%{bal:>7}"
              f"{r.ct_tonnes/1e6:>8.2f}M{r.ct_nonus_tonnes/1e6:>9.2f}M"
              f"{r.epa_us_scope1_tonnes/1e6:>8.2f}M{seen:>11}{int(r.asset_count):>8}"
              f"{int(r.country_count):>10}")
    print("bal is the same share over subsectors where Climate TRACE names US owners; CT/EPA US "
          "is how much of the company's")
    print("measured US Scope 1 Climate TRACE itself sees, so a low value means the non-US share "
          "is inflated by a US inventory gap.")
    print()

    print(f"the same set ranked by what it costs our measure: Climate TRACE tonnes abroad for "
          f"every tonne EPA measures at home, {YEAR}")
    print(f"{'ticker':<7}{'company':<24}{'x EPA':>8}{'EPA US':>9}{'CT nonUS':>10}"
          f"{'implied global':>16}{'CT sees of EPA US':>19}")
    mult = both[both.ct_nonus_tonnes >= FLOOR].sort_values("nonus_multiple_of_epa_us",
                                                           ascending=False)
    for r in mult.head(10).itertuples():
        seen = "n/a" if pd.isna(r.ct_us_vs_epa_us) else f"{100*r.ct_us_vs_epa_us:.0f}%"
        print(f"{r.ticker:<7}{str(r.company_name)[:22]:<24}{r.nonus_multiple_of_epa_us:>7.1f}x"
              f"{r.epa_us_scope1_tonnes/1e6:>8.2f}M{r.ct_nonus_tonnes/1e6:>9.2f}M"
              f"{r.implied_global_scope1_tonnes/1e6:>15.2f}M{seen:>19}")
    print()

    material = both[both.ct_nonus_tonnes >= FLOOR]
    print(f"{len(material)} S&P 500 companies carry at least {FLOOR:,} t of Climate TRACE "
          f"emissions outside the United States.")
    print(f"Summed over them our measured US Scope 1 is "
          f"{material.epa_us_scope1_tonnes.sum()/1e6:,.1f} MMT, while Climate TRACE puts a "
          f"further {material.ct_nonus_tonnes.sum()/1e6:,.1f} MMT abroad: the US-only spine sees "
          f"{100*material.epa_us_scope1_tonnes.sum()/(material.epa_us_scope1_tonnes.sum()+material.ct_nonus_tonnes.sum()):.0f}%"
          f" of their implied global Scope 1.")
    print()

    # Sanity check on the ownership roll-up, on ground where both sources are strong.
    chk = both[(both.ct_us_tonnes > 1e6) & both.ct_us_vs_epa_us.notna()]
    chk = chk.sort_values("epa_us_scope1_tonnes", ascending=False)
    print(f"cross-check on the {len(chk)} companies where Climate TRACE attributes over 1 MMT "
          f"inside the US: median CT US / EPA US ratio {chk.ct_us_vs_epa_us.median():.2f}, "
          f"quartiles {chk.ct_us_vs_epa_us.quantile(0.25):.2f} to "
          f"{chk.ct_us_vs_epa_us.quantile(0.75):.2f}")
    print(f"{'ticker':<7}{'EPA US S1':>11}{'CT US':>11}{'ratio':>8}")
    for r in chk.head(12).itertuples():
        print(f"{r.ticker:<7}{r.epa_us_scope1_tonnes/1e6:>10.2f}M{r.ct_us_tonnes/1e6:>10.2f}M"
              f"{r.ct_us_vs_epa_us:>8.2f}")
    print()

    fresh = per[per.year == 2025]
    print(f"2025, the freshest complete Climate TRACE year and three years past GHGRP's last: "
          f"{len(fresh)} tickers, {fresh.ct_tonnes.sum()/1e6:,.1f} MMT equity share, "
          f"{100*fresh.ct_nonus_tonnes.sum()/fresh.ct_tonnes.sum():.1f}% of it outside the US. "
          f"No measured GHGRP number exists to pair with it.")
    print()

    abroad = out[(~out.is_us) & (out.year == YEAR)]
    top_c = abroad.groupby("iso3_country").equity_share_tonnes_co2e.sum().nlargest(10) / 1e6
    print(f"where those foreign tonnes sit, {YEAR}, equity share, MMT")
    print("  " + "  ".join(f"{k} {v:,.0f}" for k, v in top_c.items()))
    print()

    covered = set(out[out.is_primary_listing.fillna(False)].ticker)
    epa_covered = set(epa[epa.covered.fillna(False)].ticker)
    print(f"S&P 500 coverage: {len(covered)} of 503 listings carry a Climate TRACE asset "
          f"({100*len(covered)/503:.1f}%); {len(covered & epa_covered)} of those also have "
          f"measured EPA emissions and {len(covered - epa_covered)} are new to our data "
          f"({', '.join(sorted(covered - epa_covered))})")
    nonus_tickers = set(out[(~out.is_us) & out.is_primary_listing.fillna(False)].ticker)
    print(f"{len(nonus_tickers)} of them hold at least one asset outside the United States, "
          f"which is where the EPA spine is blind by construction")
    print()

    prov = {
        "source": "Climate TRACE",
        "release": "v5.10.0",
        "provenance_class": "modelled",
        "retrieved_at": t_start.isoformat(),
        "files": records,
        "licence": "Creative Commons Attribution 4.0 International (CC BY 4.0), per climatetrace.org/data",
        "redistribution": "Derived numbers and charts may be published with attribution to Climate TRACE.",
        "method": (
            "Bulk sector packages for power, manufacturing, fossil fuel operations and mineral "
            "extraction. Their *_emissions_sources_ownership_*.csv files resolve each asset up a "
            "named corporate chain; the country packages carry no such column. Parent names were "
            "matched to tickers with the same alias map, override table and blocklist the EPA "
            "entity-resolution lane uses. Chains with an intermediate hop below 50% were dropped "
            "as portfolio holdings rather than consolidation. Asset-ticker pairs were deduped "
            "because the ownership file carries one row per ancestor. Monthly co2e_100yr rows were "
            "summed to calendar years."
        ),
        "limitations": [
            "Modelled, not measured. Climate TRACE infers emissions from satellite observation and "
            "activity data. It is a cross-check on the EPA spine and a bias estimate, never an "
            "input to the headline score.",
            "Gross asset emissions double-count joint ventures: the same Qatari LNG train is "
            "carried in full against both ConocoPhillips and ExxonMobil. Every ratio published "
            "here uses equity_share_tonnes_co2e instead.",
            "The ownership layer names a US owner on every US refinery, cement kiln and power "
            "plant but on none of Climate TRACE's 352 US oil-and-gas-production assets and none "
            "of its 352 US oil-and-gas-transport assets, while naming owners on the same asset "
            "types abroad. In those two subsectors a non-US share of 100% is an artefact of the "
            "ownership layer, not a fact about the company. subsector_us_ownership flags them and "
            "ct_nonus_share_balanced excludes them.",
            "2026 is a partial year: the release carries six months. months_covered records it.",
            "Ownership exists only for 14 subsectors. Waste and buildings ship no ownership file "
            "at all and transportation's two aviation ownership files have an empty parent_name "
            "on every one of their 33,637 rows, so airline fleets cannot be attributed here.",
            "An 'unknown %' hop in an ownership chain is treated as 100% when the equity share "
            "has to be computed from the path, which overstates it. share_source on the asset "
            "level records which rows used Climate TRACE's own overall_share_percent instead.",
            "Climate TRACE's asset boundary is not EPA's fenceline, so per-facility levels are "
            "not directly comparable. The non-US share and the ratio to measured US Scope 1 are "
            "the defensible outputs; a single facility's level is not.",
        ],
        "outputs": {
            "climatetrace_company.parquet": {"rows": int(len(out)), "cols": int(out.shape[1])},
            "climatetrace_nonus_share.parquet": {"rows": int(len(per)), "cols": int(per.shape[1])},
        },
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    for name in ("climatetrace_company.parquet", "climatetrace_nonus_share.parquet"):
        prov["outputs"][name]["sha256"] = sha256_of(INTERIM / name)
    PROV.write_text(json.dumps(prov, indent=2))
    print(f"wrote {PROV.relative_to(ROOT)}")
    print(f"elapsed {(datetime.now(timezone.utc)-t_start).total_seconds():.1f}s")


if __name__ == "__main__":
    main()
