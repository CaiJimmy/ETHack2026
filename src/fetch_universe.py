"""Build the S&P 500 universe spine that every other lane joins to.

Outputs
    data/interim/universe.parquet        one row per index listing (503), keyed on `ticker`
    data/interim/cik_ticker.parquet      every SEC registrant with a ticker (~10.4k), not just the index
    data/interim/ticker_aliases.json     spelling variants -> canonical ticker, plus name and CIK maps
    data/interim/universe_turnover.json  index membership churn, for the survivorship-bias disclosure
    data/interim/provenance/universe.json

Every raw response is cached under data/raw/. A second run makes no network calls.
"""

import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
SLEEP = 0.15  # SEC asks for under 10 req/s; we make a handful of requests anyway
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
TODAY = date.today()

# The frame is only used to ask an identity question: does this CIK actually publish XBRL, and is
# there a second CIK publishing the same facts? Assets is the best-covered tag in the taxonomy.
ASSETS_FRAME = "https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY2025Q4I.json"

SOURCES = [
    dict(
        key="constituents",
        source="datahub",
        url="https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
        cache=RAW / "datahub" / "constituents.csv",
        licence="ODC-PDDL-1.0 (public domain dedication), declared in the package's datapackage.json",
        redistribution=(
            "We may publish derived numbers freely. The GICS Sector and GICS Sub-Industry columns "
            "inside this file are a proprietary S&P Global/MSCI classification: we use them for "
            "display and peer grouping but do not ship the full 500-row GICS mapping as a data file."
        ),
    ),
    dict(
        key="company_tickers",
        source="sec",
        url="https://www.sec.gov/files/company_tickers.json",
        cache=RAW / "sec" / "company_tickers.json",
        licence="US government work, public domain (17 U.S.C. 105)",
        redistribution="We may republish this and anything derived from it freely; cite SEC EDGAR.",
    ),
    dict(
        key="company_tickers_exchange",
        source="sec",
        url="https://www.sec.gov/files/company_tickers_exchange.json",
        cache=RAW / "sec" / "company_tickers_exchange.json",
        licence="US government work, public domain (17 U.S.C. 105)",
        redistribution="We may republish this and anything derived from it freely; cite SEC EDGAR.",
    ),
    dict(
        key="assets_frame",
        source="sec",
        url=ASSETS_FRAME,
        cache=RAW / "sec" / "frames_us-gaap_Assets_USD_CY2025Q4I.json",
        licence="US government work, public domain (17 U.S.C. 105)",
        redistribution="We may republish this and anything derived from it freely; cite SEC EDGAR.",
    ),
    dict(
        key="fsds",
        source="sec",
        url="https://www.sec.gov/files/dera/data/financial-statement-data-sets/2026q2.zip",
        cache=RAW / "sec" / "financial-statement-data-sets" / "2026q2.zip",
        licence="US government work, public domain (17 U.S.C. 105)",
        redistribution="We may republish this and anything derived from it freely; cite SEC EDGAR.",
    ),
    dict(
        key="history",
        source="fja05680",
        url=(
            "https://raw.githubusercontent.com/fja05680/sp500/master/"
            "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
        ),
        cache=RAW / "sp500_history" / "historical_components.csv",
        licence="MIT, Copyright (c) 2019-2020 Farrell J. Aultman",
        redistribution="Derived numbers may be published with attribution to the fja05680/sp500 repo.",
    ),
]


def _http_get(url, ua):
    """Four attempts with linear backoff, the pacing that SEC has been happy with all day."""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                status = resp.status
            time.sleep(SLEEP)
            return body, status
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last = exc
            time.sleep(0.5 * (attempt + 1))
        except Exception as exc:  # network flake
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}: {last}")


def fetch(url, cache, ua=UA):
    """Return (bytes, provenance dict). A non-empty cache file is always the value we return.

    Fetch metadata lives in a sidecar so that provenance survives a cache hit truthfully rather than
    being reconstructed with a fresh timestamp on every run. The only case that touches the network
    on a cache hit is a cache file with no sidecar, which is verified once and then has one.
    """
    meta_path = cache.with_suffix(cache.suffix + ".meta.json")
    if cache.exists() and cache.stat().st_size > 0:
        body = cache.read_bytes()
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta.setdefault("note", None)
        else:
            # data/raw is shared with the other lanes, so this file may have been fetched by one of
            # them and carries no provenance. Verify it once against the live URL rather than
            # publishing a record with an unknown status. The cached bytes win either way: all
            # lanes have to be looking at the same input, so a mid-run upstream edit is recorded,
            # not applied. The sidecar we write here makes every later run offline again.
            fresh, status = _http_get(url, ua)
            digest = hashlib.sha256(body).hexdigest()
            matched = hashlib.sha256(fresh).hexdigest() == digest
            meta = dict(
                url=url,
                retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                http_status=status,
                note=("cached by another lane, bytes verified against a fresh fetch" if matched else
                      "cached by another lane and upstream has since changed; kept the cached bytes"),
            )
            meta_path.write_text(json.dumps(meta, indent=1))
        meta["bytes"] = len(body)
        meta["sha256"] = hashlib.sha256(body).hexdigest()
        meta["from_cache"] = True
        return body, meta

    cache.parent.mkdir(parents=True, exist_ok=True)
    body, status = _http_get(url, ua)
    tmp = cache.with_suffix(cache.suffix + ".tmp")
    tmp.write_bytes(body)
    os.replace(tmp, cache)  # atomic, so a lane sharing data/raw/sec never sees a torn file
    meta = dict(
        url=url,
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        http_status=status,
        note=None,
    )
    meta_path.write_text(json.dumps(meta, indent=1))
    meta = dict(meta, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), from_cache=False)
    return body, meta


# Canonical ticker spelling for the whole project: uppercase, share class after a dot (BRK.B).
# SEC and Yahoo both write BRK-B, Bloomberg writes BRK/B, some vendors write BRKB.
_EXCHANGE_SUFFIX = re.compile(r"(\.US|-US|:US|\sUS)$")


def canonical_ticker(raw):
    if raw is None:
        return None
    t = str(raw).strip().upper()
    if t.startswith("US:"):
        t = t[3:]
    t = _EXCHANGE_SUFFIX.sub("", t).strip()
    t = re.sub(r"[-/_ ]", ".", t)
    return t or None


def sec_ticker(canonical):
    return canonical.replace(".", "-")


_NAME_SUFFIX = re.compile(
    r"(CORPORATION|CORP|COMPANY|COMPANIES|INCORPORATED|INC|PLC|LTD|LIMITED|LLC|LP|"
    r"HOLDINGS|HOLDING|GROUP|TRUST|THE|SA|NV|AG|CO)$"
)


def normalise_name(raw):
    """Uppercase, drop everything that is not alphanumeric, strip corporate suffixes repeatedly.

    Used only for exact-equality matching. Prefix or fuzzy matching on this string is unsafe:
    'Sea Limited' normalises to SEA, which prefix-matches SEAGATETECHNOLOGY.
    """
    if raw is None or raw != raw:  # None, or a pandas/numpy NaN, which is truthy
        return ""
    s = re.sub(r"[^A-Za-z0-9]", "", str(raw).upper())
    prev = None
    while s != prev:
        prev = s
        s = _NAME_SUFFIX.sub("", s)
    return s


def main():
    INTERIM.mkdir(parents=True, exist_ok=True)
    (INTERIM / "provenance").mkdir(parents=True, exist_ok=True)

    provenance = []
    blobs = {}
    for spec in SOURCES:
        body, meta = fetch(spec["url"], spec["cache"])
        blobs[spec["key"]] = body
        provenance.append(
            dict(
                source=spec["source"],
                key=spec["key"],
                url=meta["url"],
                retrieved_at=meta.get("retrieved_at"),
                http_status=meta.get("http_status"),
                bytes=meta["bytes"],
                sha256=meta["sha256"],
                licence=spec["licence"],
                redistribution=spec["redistribution"],
                cache_path=str(spec["cache"].relative_to(ROOT)),
                served_from_cache=meta["from_cache"],
                note=meta.get("note"),
            )
        )
        print(f"fetched {spec['key']:26s} {meta['bytes']:>10,} B  cache_hit={meta['from_cache']}")

    # ---- constituents -------------------------------------------------------------------------
    rows = list(csv.DictReader(io.StringIO(blobs["constituents"].decode())))
    print(f"\nconstituents.csv: {len(rows)} listings, {len({r['CIK'] for r in rows})} distinct CIKs")

    # ---- SEC ticker map -----------------------------------------------------------------------
    ct = json.loads(blobs["company_tickers"].decode())
    sec_rows = []
    for v in ct.values():
        sec_rows.append(
            dict(
                cik=f"{int(v['cik_str']):010d}",
                ticker=canonical_ticker(v["ticker"]),
                sec_ticker=str(v["ticker"]).strip().upper(),
                sec_entity_name=v["title"],
            )
        )
    sec = pd.DataFrame(sec_rows)
    exch = json.loads(blobs["company_tickers_exchange"].decode())
    fields = exch["fields"]
    ex = pd.DataFrame(exch["data"], columns=fields)
    ex["cik"] = ex["cik"].astype(int).map(lambda c: f"{c:010d}")
    ex["sec_ticker"] = ex["ticker"].astype(str).str.strip().str.upper()
    sec = sec.merge(ex[["cik", "sec_ticker", "exchange"]], on=["cik", "sec_ticker"], how="left")
    sec["name_norm"] = sec["sec_entity_name"].map(normalise_name)
    print(f"company_tickers.json: {len(sec)} registrant listings, {sec['cik'].nunique()} distinct CIKs, "
          f"exchange present for {sec['exchange'].notna().sum()}")

    by_sec_ticker = dict(zip(sec["sec_ticker"], sec["cik"]))
    sec_name_by_cik = dict(zip(sec["cik"], sec["sec_entity_name"]))

    # sub.txt is one row per filing and carries the registrant's name on that filing plus the last
    # name it changed away from. Emissions and enforcement data lag corporate renames by years, so
    # these are the strings an EPA or CDP join will actually be holding.
    with zipfile.ZipFile(io.BytesIO(blobs["fsds"])) as zf:
        sub = list(csv.DictReader(
            io.StringIO(zf.read("sub.txt").decode("utf-8", "replace")), delimiter="\t"))
    filing_name, former_name = {}, {}
    for r in sub:
        cik = f"{int(r['cik']):010d}"
        filing_name.setdefault(cik, r["name"])
        if r.get("former") and cik not in former_name:
            former_name[cik] = (r["former"], r.get("changed") or None)
    print(f"sub.txt 2026q2: {len(sub)} filings, {len(filing_name)} distinct CIKs, "
          f"{len(former_name)} of them with a former name")

    # ---- the agreement check ------------------------------------------------------------------
    # Two independent authorities on "which CIK is this ticker". They have to agree or the whole
    # join is built on sand, so this number goes on a slide.
    cik_found = ticker_found = agree = 0
    disagreements = []
    for r in rows:
        tk = canonical_ticker(r["Symbol"])
        cik = f"{int(r['CIK']):010d}"
        if cik in sec_name_by_cik:
            cik_found += 1
        sec_cik = by_sec_ticker.get(sec_ticker(tk))
        if sec_cik is not None:
            ticker_found += 1
            if sec_cik == cik:
                agree += 1
            else:
                disagreements.append((tk, cik, sec_cik))
    all_ciks = {f"{int(r['CIK']):010d}" for r in rows}
    n_cik_found = len(all_ciks & set(sec_name_by_cik))
    print("\nreconciliation of the constituent list against SEC company_tickers.json")
    print(f"  listings whose CIK is in the SEC map {cik_found}/{len(rows)}  "
          f"({n_cik_found}/{len(all_ciks)} distinct CIKs)")
    print(f"  listings whose ticker is in the map  {ticker_found}/{len(rows)}  (after BRK.B -> BRK-B)")
    print(f"  ticker -> CIK AGREEMENTS             {agree}/{len(rows)}")
    print(f"  ticker -> CIK disagreements          {len(disagreements)} {disagreements}")
    raw_ticker_hits = sum(1 for r in rows if r["Symbol"].upper() in by_sec_ticker)
    print(f"  without the punctuation fix it would be {raw_ticker_hits}/{len(rows)}: "
          f"{sorted({r['Symbol'] for r in rows if r['Symbol'].upper() not in by_sec_ticker})}")

    # ---- XBRL identity check ------------------------------------------------------------------
    frame = json.loads(blobs["assets_frame"].decode())
    frame_by_cik = {f"{d['cik']:010d}": d for d in frame["data"]}
    frame_by_name = {}
    for d in frame["data"]:
        frame_by_name.setdefault(normalise_name(d["entityName"]), []).append(d)

    index_ciks = {f"{int(r['CIK']):010d}" for r in rows}
    no_xbrl = sorted(c for c in index_ciks if c not in frame_by_cik)
    cofilers = {}
    for cik in index_ciks:
        mine = frame_by_cik.get(cik)
        if not mine:
            continue
        # Same normalised entity name and identical reported value means EDGAR attributed one
        # filing's facts to several co-registrant CIKs. Requiring equal values keeps unrelated
        # namesakes (a securitisation trust called TARGET CORPORATION) out.
        others = [
            d for d in frame_by_name.get(normalise_name(mine["entityName"]), [])
            if f"{d['cik']:010d}" != cik and d["val"] == mine["val"]
        ]
        if others:
            cofilers[cik] = sorted(f"{d['cik']:010d}" for d in others)

    no_xbrl_tickers = sorted(canonical_ticker(r["Symbol"]) for r in rows
                             if f"{int(r['CIK']):010d}" in no_xbrl)
    print(f"\nXBRL identity check against us-gaap:Assets CY2025Q4I ({frame['pts']} filers)")
    print(f"  index CIKs with no CY2025 balance sheet   {len(no_xbrl)} {no_xbrl_tickers}")
    print(f"  index CIKs sharing facts with another CIK {len(cofilers)}")

    # ---- assemble the universe ----------------------------------------------------------------
    cik_tickers = {}
    for r in rows:
        cik_tickers.setdefault(f"{int(r['CIK']):010d}", []).append(canonical_ticker(r["Symbol"]))

    name_by_ticker = {canonical_ticker(r["Symbol"]): r["Security"] for r in rows}
    recs = []
    for r in rows:
        tk = canonical_ticker(r["Symbol"])
        cik = f"{int(r['CIK']):010d}"
        siblings = [s for s in cik_tickers[cik] if s != tk]
        # One company, two listed share classes. Pick Class A where the name says so, otherwise the
        # alphabetically first ticker, so that company-level work has a deterministic single row.
        if siblings:
            classed = [s for s in sorted(cik_tickers[cik])
                       if "class a" in name_by_ticker[s].lower()]
            primary = classed[0] if classed else sorted(cik_tickers[cik])[0]
        else:
            primary = tk
        recs.append(
            dict(
                ticker=tk,
                company_name=r["Security"],
                cik=cik,
                gics_sector=r["GICS Sector"],
                gics_sub_industry=r["GICS Sub-Industry"],
                date_added=r["Date added"] or None,
                sec_entity_name=sec_name_by_cik.get(cik),
                sec_filing_name=filing_name.get(cik),
                sec_former_name=(former_name.get(cik) or (None, None))[0],
                sec_former_name_changed=(former_name.get(cik) or (None, None))[1],
                sec_ticker=sec_ticker(tk),
                exchange=None,
                hq_location=r["Headquarters Location"] or None,
                founded=r["Founded"] or None,
                is_primary_listing=(tk == primary),
                share_class_siblings=",".join(sorted(siblings)) or None,
                cik_in_sec_map=cik in sec_name_by_cik,
                ticker_in_sec_map=sec_ticker(tk) in by_sec_ticker,
                cik_agrees_with_sec=by_sec_ticker.get(sec_ticker(tk)) == cik,
                has_xbrl_cy2025=cik in frame_by_cik,
                cik_cofilers=",".join(cofilers.get(cik, [])) or None,
            )
        )

    uni = pd.DataFrame(recs)
    ex_by_ticker = dict(zip(sec["sec_ticker"], sec["exchange"]))
    uni["exchange"] = uni["sec_ticker"].map(ex_by_ticker)
    uni["date_added"] = pd.to_datetime(uni["date_added"], format="%Y-%m-%d")
    uni = uni.sort_values("ticker").reset_index(drop=True)

    assert uni["ticker"].is_unique, "ticker is the join key and must be unique"
    assert uni["is_primary_listing"].sum() == uni["cik"].nunique()

    # ---- churn, for the survivorship-bias disclosure -------------------------------------------
    hist = list(csv.DictReader(io.StringIO(blobs["history"].decode())))
    today_set = set(uni["ticker"])
    turnover = {"as_of": TODAY.isoformat(), "n_today": len(today_set),
                "history_source": "fja05680/sp500", "history_last_snapshot": hist[-1]["date"],
                "windows": []}
    print("\nindex churn (today's membership vs a historical snapshot)")
    for yrs in (1, 3, 5, 10):
        target = TODAY.replace(year=TODAY.year - yrs).isoformat()
        snap = max((h for h in hist if h["date"] <= target), key=lambda h: h["date"])
        then = {canonical_ticker(t) for t in snap["tickers"].split(",")}
        left = sorted(then - today_set)
        joined = sorted(today_set - then)
        still_registered = [t for t in left if sec_ticker(t) in by_sec_ticker]
        turnover["windows"].append(
            dict(years=yrs, snapshot_date=snap["date"], n_then=len(then),
                 left_index=len(left), joined_index=len(joined),
                 left_but_still_an_sec_registrant=len(still_registered),
                 left_tickers=left, joined_tickers=joined)
        )
        print(f"  {yrs:2d}y  snapshot {snap['date']}  n={len(then)}  left={len(left):3d}  "
              f"joined={len(joined):3d}  (of those that left, {len(still_registered)} are still SEC registrants)")

    added = uni.dropna(subset=["date_added"])
    for yrs in (1, 3, 5):
        cut = pd.Timestamp(TODAY.replace(year=TODAY.year - yrs))
        n = int((added["date_added"] >= cut).sum())
        print(f"  date_added within {yrs}y: {n}/{len(uni)} listings")
        turnover[f"added_within_{yrs}y"] = n

    # ---- ticker aliases -----------------------------------------------------------------------
    aliases = {}
    collisions = []
    for tk in sorted(today_set):
        for variant in {tk, tk.replace(".", "-"), tk.replace(".", "/"),
                        tk.replace(".", " "), tk.replace(".", "")}:
            if variant in aliases and aliases[variant] != tk:
                collisions.append((variant, aliases[variant], tk))
                continue
            aliases[variant] = tk

    # Primary listings first, so that a name shared by two share classes resolves to the primary
    # one, and current names before former ones, so a name still in use is never overwritten by
    # some other company's discarded name.
    name_to_ticker = {}
    name_source = {}
    name_collisions = []
    ordered = uni.sort_values(["is_primary_listing", "ticker"], ascending=[False, True])
    for field, label in [("company_name", "index"), ("sec_entity_name", "sec"),
                         ("sec_filing_name", "sec_filing"), ("sec_former_name", "sec_former")]:
        for _, row in ordered.iterrows():
            candidate = normalise_name(row[field])
            if not candidate:
                continue
            if candidate in name_to_ticker:
                if name_to_ticker[candidate] != row["ticker"]:
                    name_collisions.append(
                        [candidate, name_to_ticker[candidate], row["ticker"], label])
                continue
            name_to_ticker[candidate] = row["ticker"]
            name_source[candidate] = label
    by_source = pd.Series(list(name_source.values())).value_counts().to_dict()
    print(f"\nname_to_ticker keys by source: {by_source}")

    alias_doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "canonical_spelling": "uppercase, share class after a dot, e.g. BRK.B",
        "lookup_rule": (
            "Uppercase and strip the input, drop a US exchange suffix (.US -US :US ' US' or a US: "
            "prefix), then look it up in `aliases`. Keys are uppercase. If it is absent the symbol "
            "is not an S&P 500 constituent under any spelling we generated."
        ),
        "name_rule": (
            "`name_to_ticker` keys are uppercase alphanumerics with corporate suffixes stripped "
            "(CORP, INC, PLC, HOLDINGS, GROUP, THE, ...). Match on exact equality only; prefix or "
            "fuzzy matching on these strings produces false positives such as SEA vs SEAGATE. "
            "`name_source` says where each key came from: the index list, SEC company_tickers, the "
            "name on the latest EDGAR filing, or the name the registrant last changed away from. "
            "Former names are here because emissions and enforcement data lag corporate renames."
        ),
        "n_canonical": len(today_set),
        "n_aliases": len(aliases),
        "collisions": collisions,
        "name_collisions": name_collisions,
        "aliases": dict(sorted(aliases.items())),
        "name_to_ticker": dict(sorted(name_to_ticker.items())),
        "name_source": dict(sorted(name_source.items())),
        "ticker_to_cik": dict(zip(uni["ticker"], uni["cik"])),
        "cik_to_tickers": {c: sorted(v) for c, v in sorted(cik_tickers.items())},
        "primary_ticker_by_cik": dict(
            zip(uni.loc[uni["is_primary_listing"], "cik"], uni.loc[uni["is_primary_listing"], "ticker"])
        ),
        "cik_cofilers": {
            "note": (
                "Other CIKs that report an identical us-gaap:Assets CY2025Q4I value under the same "
                "normalised entity name. EDGAR attributes a combined filing's facts to every "
                "co-registrant CIK, so a reverse join from XBRL to company double counts unless "
                "these are collapsed. For XOM the index CIK is the 2026 holdco and the annual "
                "history sits on the other CIK."
            ),
            "map": {c: v for c, v in sorted(cofilers.items())},
        },
    }

    # ---- write ---------------------------------------------------------------------------------
    sec_out = sec.copy()
    sec_out["in_sp500"] = sec_out["cik"].isin(index_ciks)
    sec_out = sec_out[["cik", "ticker", "sec_ticker", "sec_entity_name", "name_norm",
                       "exchange", "in_sp500"]].sort_values(["ticker", "cik"]).reset_index(drop=True)

    uni.to_parquet(INTERIM / "universe.parquet", index=False)
    sec_out.to_parquet(INTERIM / "cik_ticker.parquet", index=False)
    (INTERIM / "ticker_aliases.json").write_text(json.dumps(alias_doc, indent=1))
    (INTERIM / "universe_turnover.json").write_text(json.dumps(turnover, indent=1))
    (INTERIM / "provenance" / "universe.json").write_text(
        json.dumps({"lane": "universe", "script": "src/fetch_universe.py",
                    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "fetches": provenance}, indent=1)
    )

    print("\nwrote")
    print(f"  data/interim/universe.parquet        {len(uni)} rows  "
          f"({int(uni['is_primary_listing'].sum())} companies, {len(uni) - int(uni['is_primary_listing'].sum())} extra share classes)")
    print(f"  data/interim/cik_ticker.parquet      {len(sec_out)} rows over {sec_out['cik'].nunique()} CIKs  "
          f"({int(sec_out['in_sp500'].sum())} listings on the {sec_out.loc[sec_out['in_sp500'], 'cik'].nunique()} index CIKs, "
          f"so {int(sec_out['in_sp500'].sum()) - len(uni)} extra share classes and preferreds)")
    print(f"  data/interim/ticker_aliases.json     {len(aliases)} ticker aliases, "
          f"{len(name_to_ticker)} name keys, {len(collisions)} ticker collisions, "
          f"{len(name_collisions)} name collisions")
    print(f"  data/interim/universe_turnover.json  {len(turnover['windows'])} windows")
    print(f"  data/interim/provenance/universe.json {len(provenance)} fetches")

    print("\nnull counts in universe.parquet")
    for col in uni.columns:
        n = int(uni[col].isna().sum())
        if n:
            print(f"  {col:24s} {n}")

    print("\nsector mix")
    for sector, n in uni.loc[uni["is_primary_listing"], "gics_sector"].value_counts().items():
        print(f"  {sector:24s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
