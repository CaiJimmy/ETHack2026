"""Good Jobs First Violation Tracker -> regulatory penalty history for the S&P 500.

Violation Tracker resolves federal, state and private-litigation penalties to the
corporate parent that owns the offending entity today, and each parent page prints the
ticker in plain text ("Ownership Structure : publicly traded (ticker symbol XOM)").
That self-declared ticker is what makes this join exact rather than fuzzy: we generate
candidate parents by name similarity, fetch each candidate page, and keep a candidate
only if the page declares the ticker we were looking for. Wrong-company matches like
NXP Semiconductors -> ON Semiconductor die on their own.

Outputs
  data/interim/violations.parquet            ticker x year x offence group
  data/interim/violations_by_agency.parquet  ticker x enforcing agency
  data/interim/violations_summary.parquet    one row per index member
  data/interim/violations_aliases.json       subsidiary names per ticker, for the OSHA
                                             and ECHO lanes to join on
  data/interim/provenance/violations.json

Every page is cached under data/raw/violations/. A second run touches the network only
for pages that are not already on disk.
"""

import hashlib
import html as htmllib
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "violations"
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance"

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
BASE = "https://violationtracker.goodjobsfirst.org"
CONSTITUENTS = ("https://raw.githubusercontent.com/datasets/s-and-p-500-companies"
                "/main/data/constituents.csv")

# Good Jobs First serves parent pages in 2-5 seconds and their terms of service ban
# request rates that burden their systems. One request at a time with a pause.
SLEEP = 1.1

# Violation Tracker still carries a pre-rename or pre-merger ticker for these parents.
# Checked by hand: the parent name on the page is the same company as the index member.
STALE_TICKERS = {
    "BALL": "BLL",    # Ball Corporation switched ticker in 2024
    "FISV": "FI",     # Fiserv
    "MRSH": "MMC",    # Marsh McLennan
    "WTW": "WLTW",    # Willis Towers Watson
    "DELL": "DVMT",   # Dell, from the VMware tracking-stock era
    "ECHO": "SATS",   # EchoStar
    "VRT": "VTRV",    # Vertiv
    "BNY": "BK",      # BNY Mellon, which traded as BK until 2024
}

# Name similarity cannot reach these. Each is the same legal entity under a new name.
MANUAL_SLUGS = {
    "GE": "general-electric",   # GE Aerospace is General Electric renamed, same CIK 40545
}

# Share-class pairs: the index lists one class, Violation Tracker declares the other.
CLASS_PAIRS = [{"GOOG", "GOOGL"}, {"FOX", "FOXA"}, {"NWS", "NWSA"},
               {"BRK.A", "BRK.B"}, {"BF.A", "BF.B"}, {"LEN", "LEN.B"}]

# The only offence type in the record tables that the published offence-groups page
# leaves out, 151 records of it. Assigned here rather than dropped into miscellaneous.
EXTRA_OFFENCE_TYPES = {"solid waste violation": "environment-related offenses"}

PAGE_MIN_BYTES = 5000
URL_OF = {}          # cache path -> the URL it came from
FETCHED = {}         # cache path -> what the network actually returned this run


def fetch(url, path, min_bytes=PAGE_MIN_BYTES):
    """Return the body at url, reading the on-disk cache when we already have it."""
    URL_OF[str(path)] = url
    if path.exists() and path.stat().st_size >= min_bytes:
        return path.read_text(encoding="utf8", errors="replace")

    path.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    body, status = None, None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=90) as resp:
                body, status = resp.read(), resp.status
            break
        except (HTTPError, URLError, TimeoutError) as exc:
            status = getattr(exc, "code", None)
            if attempt == 2:
                print(f"  fetch failed {url}: {exc}", file=sys.stderr)
                return None
            time.sleep(3 * (attempt + 1))
    if body is None or len(body) < min_bytes:
        return None
    path.write_bytes(body)
    FETCHED[str(path)] = {"http_status": status,
                          "retrieved_at": datetime.now(timezone.utc).isoformat()}
    time.sleep(SLEEP)
    return body.decode("utf8", errors="replace")


NORMALISE_DROP = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|llc|lp|llp|plc|ltd|limited|"
    r"holdings?|holding|group|the|and|usa|us|na|intl|international|worldwide|america|"
    r"american|sa|nv|ag|se|gmbh|pte|pty|bv|trust|reit|cos|enterprises?|industries|"
    r"systems|technologies|tech|services|solutions|partners|associates|brands|"
    r"laboratories|laboratory|labs|lab|motor|motors|stores|store|financial|bancorp|"
    r"bancshares|airlines|railroad|railway|communications|pharmaceuticals|"
    r"pharmaceutical|companies)\b")


def ascii_fold(name):
    """Estee Lauder and Brown-Forman carry accents and an en dash in the index listing."""
    return "".join(c for c in unicodedata.normalize("NFKD", name)
                   if not unicodedata.combining(c))


def alias_key(name):
    """Aggressive normalisation for the OSHA / ECHO name joins downstream."""
    value = re.sub(r"[^a-z0-9 ]", " ", ascii_fold(name).lower().replace("&", " and "))
    value = re.sub(r"\s+", " ", value).strip()
    previous = None
    while previous != value:
        previous = value
        value = re.sub(r"\s+", " ", NORMALISE_DROP.sub(" ", value)).strip()
    return value


CELL = re.compile(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>")
ROW = re.compile(r"(?is)<tr[^>]*>(.*?)</tr>")
TABLE = re.compile(r'(?is)<table[^>]*class="views-table"[^>]*>(.*?)</table>')
RECORD_HEADER = ["Company", "Primary Offense Type", "Year", "Agency", "Penalty Amount"]


def text(fragment):
    stripped = re.sub(r"(?s)<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", htmllib.unescape(stripped).replace("\xa0", " ")).strip()


def flatten(page):
    body = re.sub(r"(?is)<script.*?</script>", " ", page)
    body = re.sub(r"(?is)<style.*?</style>", " ", body)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"(?s)<[^>]*>", " ", body)))


MONEY = re.compile(r"\$ ?([\d,]+)")
MULTI_AGENCY_NOTE = "marked by an asterisk"


def money(cell):
    """Cells for penalties announced by several agencies carry the footnote text inline
    ahead of the figure, so read the last dollar amount in the cell."""
    found = MONEY.findall(cell)
    return int(found[-1].replace(",", "")) if found else None


def parse_parent(page):
    """Pull the summary fields, the published group totals and the record rows."""
    out = {"published_groups": {}, "records": [], "bad_penalty_cells": 0}
    for table in TABLE.findall(page):
        rows = ROW.findall(table)
        if not rows:
            continue
        header = [text(c) for c in CELL.findall(rows[0])]
        body = [cells for cells in ([text(c) for c in CELL.findall(r)] for r in rows[1:]) if cells]
        if header and header[0].startswith("Top 5 Offense Groups"):
            for cells in body:
                if len(cells) >= 3:
                    out["published_groups"][cells[0].strip().lower()] = (
                        money(cells[1]), int(cells[2].replace(",", "")))
        elif header[:5] == RECORD_HEADER:
            for cells in body:
                if len(cells) < 5:
                    continue
                penalty = money(cells[4])
                if penalty is None:
                    out["bad_penalty_cells"] += 1
                # Good Jobs First lists a penalty announced by several agencies once per
                # agency and leaves those dollars out of the parent total so the case is
                # not counted twice. We follow their accounting, which is what makes our
                # totals reconcile to the figure printed on the page.
                multi = MULTI_AGENCY_NOTE in cells[4]
                out["records"].append({"company": cells[0], "offense": cells[1],
                                       "year": cells[2], "agency": cells[3],
                                       "penalty": 0 if multi else (penalty or 0),
                                       "penalty_multi_agency": (penalty or 0) if multi else 0,
                                       "multi_agency": multi})

    flat = flatten(page)
    def grab(pattern):
        m = re.search(pattern, flat)
        return m.group(1).strip() if m else None

    # No space before the closing paren: "ticker symbol XOM)".
    out["ticker"] = grab(r"ticker symbol\s*([A-Z0-9.\- ]{1,20}?)\s*\)")
    out["parent_name"] = grab(r"Current Parent Company Name : (.+?) Ownership Structure")
    out["ownership"] = grab(r"Ownership Structure : ([^:]+?) (?:Headquartered|Major Industry)")
    out["hq"] = grab(r"Headquartered in : ([A-Za-z .]+?) Major Industry")
    out["industry"] = grab(r"Major Industry : ([^:]+?) Specific Industry")
    total = grab(r"Penalty total since 2000[^$]*\$ ?([\d,]+)")
    out["published_total"] = int(total.replace(",", "")) if total else None
    n = grab(r"Number of records : ?([\d,]+)")
    out["published_n"] = int(n.replace(",", "")) if n else None
    pages = [int(p) for p in re.findall(r"[?&]page=(\d+)", page)]
    out["last_page"] = max(pages) if pages else 1
    return out


def load_universe():
    path = RAW / "sp500_constituents.csv"
    fetch(CONSTITUENTS, path, min_bytes=1000)
    frame = pd.read_csv(path)
    frame = frame.rename(columns={"Symbol": "ticker", "Security": "company",
                                  "GICS Sector": "sector", "CIK": "cik"})
    frame["ticker"] = frame["ticker"].str.upper().str.replace("-", ".", regex=False)
    frame["cik"] = frame["cik"].astype("int64").astype(str).str.zfill(10)
    return frame[["ticker", "company", "sector", "cik"]]


def parent_directory():
    """The /summary page carries every parent as an <option> in a select box."""
    page = fetch(BASE + "/summary", RAW / "summary.html", min_bytes=50_000)
    block = re.search(r'(?is)<select[^>]*name="parent".*?</select>', page).group(0)
    options = re.findall(r'(?is)<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', block)
    return {text(name): slug for slug, name in options if slug}


def offence_groups():
    """Violation Tracker publishes its offence type -> group mapping as a plain page."""
    page = fetch(BASE + "/pages/offense-groups", RAW / "offense_groups.html",
                 min_bytes=20_000)
    mapping, group = {}, None
    for chunk in re.split(r'(?i)<div class="mt-3">', page)[1:]:
        chunk = chunk.split("<!-- ")[0]
        label = text(chunk)
        if not label:
            continue
        if re.search(r"(?i)<b>", chunk) and label.lower().endswith("offenses"):
            group = label.lower()
            continue
        if group:
            for offence in label.split(","):
                offence = offence.strip().strip(".").lower()
                if offence:
                    mapping[offence] = group
    return mapping


def parent_index(parents):
    """Corporate suffixes swamp string similarity - "Ball Corporation" scores as well
    against "APA Corporation" as against "Ball Corp." Match on the stripped name."""
    index = defaultdict(list)
    for name, slug in parents.items():
        index[alias_key(name)].append(slug)
    return index


def candidate_slugs(company, index, keys):
    key = alias_key(company)
    slugs = list(index.get(key, []))
    for scorer in (fuzz.token_set_ratio, fuzz.WRatio):
        for name, score, _ in process.extract(key, keys, scorer=scorer, limit=3):
            if score >= 70:
                slugs += [s for s in index[name] if s not in slugs]
    return slugs[:5]


def ticker_matches(want, declared):
    if not declared:
        return False
    declared = declared.strip().upper().replace("-", ".")
    if declared == want:
        return True
    if declared.split(".")[0] == want.split(".")[0]:
        return True
    if any({want, declared} <= pair for pair in CLASS_PAIRS):
        return True
    return declared == STALE_TICKERS.get(want)


def resolve(universe, parents):
    """Map each index member to a Violation Tracker parent slug, or to nothing.

    First pass: candidate parents by name, accepted only on the declared ticker. Second
    pass: for whatever is left, follow the parent links printed by the free search, which
    reaches parents that the summary page's dropdown does not list."""
    index = parent_index(parents)
    keys = list(index)
    resolved, rejected, searches = {}, defaultdict(list), {}

    def consider(ticker, slug):
        page = fetch(f"{BASE}/parent/{slug}", RAW / "parent" / f"{slug}_p1.html")
        if page is None:
            return None
        parsed = parse_parent(page)
        if ticker_matches(ticker, parsed["ticker"]):
            parsed["slug"] = slug
            return parsed
        rejected[ticker].append((slug, parsed["ticker"], parsed["parent_name"]))
        return None

    for row in universe.itertuples():
        tries = []
        if row.ticker in MANUAL_SLUGS:
            tries.append(MANUAL_SLUGS[row.ticker])
        tries += [s for s in candidate_slugs(row.company, index, keys) if s not in tries]
        for slug in tries:
            parsed = consider(row.ticker, slug)
            if parsed:
                parsed["manual"] = row.ticker in MANUAL_SLUGS
                parsed["via"] = "name"
                resolved[row.ticker] = parsed
                break

    for row in universe.itertuples():
        if row.ticker in resolved:
            continue
        probe = search_company(row.company)
        searches[row.ticker] = probe
        for slug in probe["parent_slugs"]:
            parsed = consider(row.ticker, slug)
            if parsed:
                parsed["manual"] = False
                parsed["via"] = "search"
                resolved[row.ticker] = parsed
                probe["matched_parent"] = slug
                break
    return resolved, rejected, searches


def fetch_records(parsed):
    """Page 1 is /parent/<slug>; pages 2..n are /?parent=<slug>&page=n. 1-indexed, and
    page=1 duplicates page 1, so never request it."""
    slug = parsed["slug"]
    records = list(parsed["records"])
    bad_cells = parsed["bad_penalty_cells"]
    for page_no in range(2, parsed["last_page"] + 1):
        page = fetch(f"{BASE}/?parent={slug}&page={page_no}",
                     RAW / "parent" / f"{slug}_p{page_no}.html")
        if page is None:
            break
        more = parse_parent(page)
        records += more["records"]
        bad_cells += more["bad_penalty_cells"]
    return records, bad_cells


def search_company(company, max_pages=3):
    """Free company-name search. Used for index members that no parent page claims: it
    tells apart "no records" from "records exist but we did not find the parent", and
    the results table links each record to its current parent, which is a second way in.
    The search is a case-insensitive starts-with, so it also returns unrelated firms
    whose name happens to share the prefix - only the parent links are evidence."""
    query = alias_key(company) or re.sub(r"[^A-Za-z0-9 ]", " ", ascii_fold(company)).strip()
    stem = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")
    out = {"query": query, "total": None, "rows_read": 0, "parent_slugs": [],
           "truncated": False}
    for page_no in range(1, max_pages + 1):
        url = (f"{BASE}/summary?company={query.replace(' ', '+')}&company_op=starts"
               + (f"&page={page_no}" if page_no > 1 else ""))
        page = fetch(url, RAW / "search" / f"{stem}_p{page_no}.html", min_bytes=50_000)
        if page is None:
            return out
        if page_no == 1:
            if "No Violation Tracker results found" in flatten(page):
                out["total"] = 0
                return out
            found = re.search(r"num_recs=(\d+)", page)
            out["total"] = int(found.group(1)) if found else None
        tables = TABLE.findall(page)
        if not tables:
            break
        rows = ROW.findall(tables[0])
        out["rows_read"] += max(len(rows) - 1, 0)
        for slug in re.findall(r'href="[^"]*/parent/([a-z0-9\-]+)', tables[0]):
            if slug not in out["parent_slugs"]:
                out["parent_slugs"].append(slug)
        if out["total"] is None or out["rows_read"] >= out["total"]:
            break
    out["truncated"] = bool(out["total"] and out["rows_read"] < out["total"])
    return out


def match_status(ticker, parsed, probe):
    if parsed is None:
        if probe is None or probe["total"] is None:
            return "unresolved"
        # Rows whose company name merely shares our prefix are other firms. Only a
        # parent that declares our ticker would count, and the search found none.
        return "no_records" if not probe["truncated"] else "unresolved"
    if parsed["via"] == "search":
        return "ticker_verified_via_search"
    if parsed["manual"]:
        return "manual_slug"
    declared = (parsed["ticker"] or "").upper()
    if declared == ticker:
        return "ticker_verified"
    if any({ticker, declared} <= pair for pair in CLASS_PAIRS):
        return "ticker_verified_share_class"
    return "ticker_verified_stale"


def write_provenance(sources):
    PROV.mkdir(parents=True, exist_ok=True)
    urls = []
    for path_str, url in sorted(URL_OF.items()):
        path = Path(path_str)
        if not path.exists():
            continue
        blob = path.read_bytes()
        live = FETCHED.get(path_str)
        urls.append({
            "url": url,
            "source": ("datasets/s-and-p-500-companies" if "githubusercontent" in url
                       else "Violation Tracker, Good Jobs First"),
            "cache_path": str(path.relative_to(ROOT)),
            "retrieved_at": (live["retrieved_at"] if live else
                             datetime.fromtimestamp(path.stat().st_mtime,
                                                    timezone.utc).isoformat()),
            "retrieved_this_run": bool(live),
            "http_status": live["http_status"] if live else 200,
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        })
    record = dict(sources)
    record["cache_note"] = (
        "retrieved_at for entries with retrieved_this_run false is the cache file's "
        "modification time. Those pages were fetched by this project's research pass on "
        "2026-09-12 with the same user agent and the same one-request-at-a-time pacing.")
    record["generated_at"] = datetime.now(timezone.utc).isoformat()
    record["n_urls"] = len(urls)
    record["urls"] = urls
    out = PROV / "violations.json"
    out.write_text(json.dumps(record, indent=1))
    print(f"provenance: {len(urls)} urls -> {out.relative_to(ROOT)} "
          f"({out.stat().st_size / 1e6:.2f} MB)")


LICENCE = {
    "name": "Violation Tracker, Good Jobs First",
    "home": BASE,
    "terms_read": "https://goodjobsfirst.org/terms-of-service/ (revised 2024-08-27), "
                  "read 2026-09-12",
    "access": "No login and no API key for parent summary pages or their record tables. "
              "Spreadsheet download (&detail=csv_results) is behind a paid subscriber "
              "login at $25 / $45 / $150 per month, and we did not use it.",
    "robots_txt": "Disallows /resource/, /gen/ and /devel/ only. /parent/ and /?parent= "
                  "are allowed and no Crawl-delay is set.",
    "terms_verbatim": "The acceptable-use section bars users who 'attempt to disrupt or "
                      "overwhelm our infrastructure by intentionally imposing "
                      "unreasonable requests or burdens on our resources (e.g. by using "
                      "\"bots,\" scraping, or other automated processing activities that "
                      "send requests to our servers at a rate that either imposes "
                      "burdens on our systems or circumvents any technological blockers "
                      "to such activities that we have put in place)'. The bar is on the "
                      "rate and on circumvention, not on automated reading as such. The "
                      "terms name goodjobsfirst.org, violationtrackeruk.goodjobsfirst.org, "
                      "covidstimuluswatch.org and corp-research.org; the US Violation "
                      "Tracker subdomain is not listed by name but the list is prefaced "
                      "'including', so we treat the terms as applying.",
    "our_compliance": "One request at a time, 1.1 s apart, every page cached on disk, "
                      "one pass. No login was created and no paywall was circumvented.",
    "licence": "No open licence is offered. Page footers carry '© 2026 Good Jobs First'. "
               "The underlying penalties are US federal and state government enforcement "
               "records and are not copyrightable, but the parent-subsidiary mapping is "
               "Good Jobs First's own work product and is the part we depend on.",
    "redistribution": "We may publish derived aggregates - totals, counts, offence-group "
                      "and year splits, and scores built from them - with the credit line "
                      "'Violation Tracker, Good Jobs First "
                      "(violationtracker.goodjobsfirst.org)' and a link back. We must not "
                      "republish the record-level penalty table, which is their "
                      "compilation. violations_aliases.json is derived from that table "
                      "and is an internal join key, not a publication artefact.",
    "coverage_caveats": "US penalties only, from 2000 onward. Parent-subsidiary links "
                        "reflect ownership today, not ownership when the violation "
                        "happened. Penalties are detection-biased toward physically "
                        "present, heavily regulated industries, so absolute dollars are "
                        "not comparable across sectors.",
}

CONSTITUENTS_LICENCE = {
    "name": "S&P 500 constituents, datasets/s-and-p-500-companies on GitHub",
    "licence": "Open Data Commons Public Domain Dedication and License v1.0, declared in "
               "the repository's datapackage.json. Sourced from the Wikipedia list of "
               "S&P 500 companies and rebuilt daily.",
    "redistribution": "Public domain dedication, so derived numbers may be published "
                      "freely. A link back to the Open Knowledge Foundation is requested "
                      "but not required.",
}


def main():
    started = time.time()
    INTERIM.mkdir(parents=True, exist_ok=True)

    universe = load_universe()
    print(f"universe: {len(universe)} index members")

    parents = parent_directory()
    print(f"violation tracker parent directory: {len(parents)} parents")

    groups = offence_groups()
    groups.update(EXTRA_OFFENCE_TYPES)
    print(f"offence type -> group map: {len(groups)} types, "
          f"{len(set(groups.values()))} groups")

    resolved, rejected, searches = resolve(universe, parents)
    statuses = defaultdict(int)
    for ticker, parsed in resolved.items():
        statuses[match_status(ticker, parsed, None)] += 1
    print(f"resolved parents: {len(resolved)}/{len(universe)} "
          f"({len(resolved) / len(universe):.1%}); "
          + ", ".join(f"{n} {k}" for k, n in sorted(statuses.items())))
    print(f"unresolved: {len(universe) - len(resolved)}; "
          f"{sum(1 for t in rejected if t not in resolved)} of them had candidates "
          f"rejected on a ticker mismatch")

    per_record, aliases, bad_cells, unmapped = [], {}, 0, defaultdict(int)
    multi_agency_records = 0
    group_check = {"exact": 0, "off": 0}
    for ticker, parsed in resolved.items():
        records, bad = fetch_records(parsed)
        bad_cells += bad
        parsed["records_scraped"] = len(records)
        if parsed["published_n"] and len(records) != parsed["published_n"]:
            print(f"  count mismatch {ticker} {parsed['slug']}: "
                  f"scraped {len(records)} vs page says {parsed['published_n']}")
        mine = defaultdict(lambda: [0, 0])
        for rec in records:
            offence = rec["offense"].strip().lower()
            group = groups.get(offence)
            if group is None:
                unmapped[offence] += 1
                group = "unclassified offenses"
            year = int(rec["year"]) if re.fullmatch(r"\d{4}", rec["year"].strip()) else None
            per_record.append((ticker, year, group, rec["penalty"],
                               rec["penalty_multi_agency"], rec["agency"]))
            mine[group][0] += rec["penalty"]
            mine[group][1] += 1
            multi_agency_records += int(rec["multi_agency"])
        for group, (penalty, count) in parsed["published_groups"].items():
            if group in mine and mine[group] == [penalty, count]:
                group_check["exact"] += 1
            elif group in mine or penalty:
                group_check["off"] += 1
        aliases[ticker] = sorted({alias_key(r["company"]) for r in records
                                  if len(alias_key(r["company"]).split()) >= 2})

    print(f"records parsed: {len(per_record):,} across {len(resolved)} parents")
    print(f"penalty cells we could not read: {bad_cells}")
    print(f"offence types missing from the published map: {len(unmapped)} "
          f"({sum(unmapped.values())} records)")
    for offence, count in sorted(unmapped.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {offence}: {count}")
    checked = group_check["exact"] + group_check["off"]
    print(f"offence-group cross-check against the page's own top-5 table: "
          f"{group_check['exact']}/{checked} exact "
          f"({group_check['exact'] / max(checked, 1):.1%})")

    print(f"records whose penalty several agencies announced together: "
          f"{multi_agency_records} (dollars excluded from totals, cases still counted)")

    frame = pd.DataFrame(per_record,
                         columns=["ticker", "year", "offence_group", "penalty_usd",
                                  "penalty_usd_multi_agency", "agency"])

    by_group = (frame.groupby(["ticker", "year", "offence_group"], dropna=False)
                .agg(penalty_usd=("penalty_usd", "sum"),
                     penalty_usd_multi_agency=("penalty_usd_multi_agency", "sum"),
                     case_count=("penalty_usd", "size"))
                .reset_index())
    by_group["year"] = by_group["year"].astype("Int64")
    by_group.to_parquet(INTERIM / "violations.parquet", index=False)
    print(f"violations.parquet: {len(by_group):,} rows "
          f"(ticker x year x offence group), {by_group['ticker'].nunique()} tickers, "
          f"${by_group['penalty_usd'].sum():,.0f}")

    by_agency = (frame.groupby(["ticker", "agency"])
                 .agg(penalty_usd=("penalty_usd", "sum"), case_count=("penalty_usd", "size"))
                 .reset_index())
    by_agency.to_parquet(INTERIM / "violations_by_agency.parquet", index=False)
    print(f"violations_by_agency.parquet: {len(by_agency):,} rows, "
          f"{by_agency['agency'].nunique()} agencies")

    recent_to = datetime.now(timezone.utc).year - 1
    recent_from = recent_to - 4
    env = "environment-related offenses"
    recent = frame[frame["year"].between(recent_from, recent_to)]
    print(f"recent5 columns cover {recent_from}-{recent_to}, the last five complete years")

    def totals(subset, suffix):
        grouped = subset.groupby("ticker").agg(**{
            f"penalty_usd{suffix}": ("penalty_usd", "sum"),
            f"case_count{suffix}": ("penalty_usd", "size")})
        return grouped

    summary = universe.set_index("ticker").copy()
    summary = summary.join(totals(frame, "_total"))
    summary = summary.join(totals(frame[frame["offence_group"] == env], "_environment"))
    summary = summary.join(totals(recent, "_total_recent5"))
    summary = summary.join(totals(recent[recent["offence_group"] == env], "_environment_recent5"))

    meta = []
    for ticker in summary.index:
        parsed = resolved.get(ticker)
        probe = searches.get(ticker)
        meta.append({
            "ticker": ticker,
            "gjf_slug": parsed["slug"] if parsed else None,
            "gjf_parent": parsed["parent_name"] if parsed else None,
            "gjf_ticker": parsed["ticker"] if parsed else None,
            "gjf_industry": parsed["industry"] if parsed else None,
            "gjf_hq_state": parsed["hq"] if parsed else None,
            "published_total_usd": parsed["published_total"] if parsed else None,
            "published_case_count": parsed["published_n"] if parsed else None,
            "name_search_query": probe["query"] if probe else None,
            "name_search_hits": probe["total"] if probe else None,
            "match_status": match_status(ticker, parsed, probe),
        })
    summary = summary.join(pd.DataFrame(meta).set_index("ticker"))

    counts = ["penalty_usd_total", "case_count_total", "penalty_usd_environment",
              "case_count_environment", "penalty_usd_total_recent5",
              "case_count_total_recent5", "penalty_usd_environment_recent5",
              "case_count_environment_recent5"]
    matched = summary["gjf_slug"].notna()
    for column in counts:
        # A resolved parent with no records in a bucket really has zero there. A company
        # with no parent at all stays null: we did not measure it.
        summary.loc[matched, column] = summary.loc[matched, column].fillna(0)
        summary[column] = summary[column].astype("Int64")

    published = pd.to_numeric(summary["published_total_usd"], errors="coerce").astype("Int64")
    summary["reconciles"] = summary["penalty_usd_total"] == published
    # Where one penalty was announced by several agencies, the record table prints the
    # gross figure and Violation Tracker's own parent total nets out the overlap. We
    # cannot see the netted figure per record, so the residual is carried here rather
    # than spread over years and offence groups.
    summary["penalty_usd_unallocated"] = (published - summary["penalty_usd_total"]).fillna(0)
    shared = (summary.reset_index().dropna(subset=["gjf_slug"])
              .groupby("gjf_slug")["ticker"].apply(list))
    summary["parent_shared_with"] = summary.apply(
        lambda row: ",".join(t for t in shared.get(row["gjf_slug"], [])
                             if t != row.name) or None, axis=1)
    summary = summary.reset_index()
    summary.to_parquet(INTERIM / "violations_summary.parquet", index=False)

    matched_n = int(matched.sum())
    clean = int((summary["match_status"] == "no_records").sum())
    unresolved = int((summary["match_status"] == "unresolved").sum())
    print(f"violations_summary.parquet: {len(summary)} rows; "
          f"{matched_n} with a parent, {clean} searched with no record under "
          f"their own name, "
          f"{unresolved} unresolved")
    print(f"  penalty total across matched parents: "
          f"${int(summary['penalty_usd_total'].sum()):,}")
    print(f"  environment-related subtotal: "
          f"${int(summary['penalty_usd_environment'].sum()):,}")
    print(f"  reconciles to the page's own headline total: "
          f"{int(summary['reconciles'].sum())}/{matched_n}; the rest sit "
          f"${int(summary['penalty_usd_unallocated'].sum()):,} below it because "
          f"multi-agency penalties are netted by Violation Tracker, not by us")
    shared_n = int(summary['parent_shared_with'].notna().sum())
    print(f"  {shared_n} tickers share a parent with another ticker (share classes) "
          f"and must be deduplicated before any index-level sum")

    alias_path = INTERIM / "violations_aliases.json"
    alias_path.write_text(json.dumps(aliases, separators=(",", ":")))
    print(f"violations_aliases.json: {sum(len(v) for v in aliases.values()):,} aliases "
          f"over {len(aliases)} tickers ({alias_path.stat().st_size / 1e6:.2f} MB)")

    write_provenance({"source": "Good Jobs First Violation Tracker", **LICENCE,
                      "constituents_source": CONSTITUENTS_LICENCE,
                      "recent5_window": f"{recent_from}-{recent_to}",
                      "network_requests_this_run": len(FETCHED)})
    print(f"network requests this run: {len(FETCHED)}")
    print(f"elapsed {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
