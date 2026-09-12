"""Forward-looking climate targets for the S&P 500: the "say" half of the say-do gap.

Three sources, all free and keyless:

  Net Zero Tracker REST API   what a company claims: net-zero and interim targets, target and
                              baseline years, scope coverage, plan and accountability flags, and a
                              Wayback-archived link to the page of the report the target came from.
  SBTi targets-excel.xlsx     what an independent body has validated: one row per target with
                              scope, absolute-vs-intensity type, numeric value, base and target year.
  SBTi companies-excel.xlsx   the per-company validation status and 1.5C classification.

Outputs
  data/interim/targets.parquet          one row per company per target (the long table)
  data/interim/targets_company.parquet  one row per company, carrying promised_annual_reduction_pct

promised_annual_reduction_pct
  The implied geometric rate of decline in absolute emissions, in percent per year, that a company's
  own strongest scope 1+2 target commits it to. Positive means falling emissions. For a target of R
  percent by year T from base year B,

      rate = (1 - (1 - R/100) ** (1 / (T - B))) * 100

  It is a compound rate, not R/(T-B), because it is compared against a log-linear trend fitted to
  observed EPA facility emissions. The two have to be the same kind of number.

  Which target feeds it, in strict order of preference, so that an explicit interim number always
  beats an inferred one:

    1  sbti_s12_absolute   an SBTi-validated scope 1+2 absolute reduction target. Independently
                           checked against a 1.5C pathway, and the only source here with numbers
                           somebody else has audited.
    2  nzt_interim         the company's own interim target, where Net Zero Tracker recorded an
                           explicit percentage with a baseline and a target year.
    3  sbti_combined       an SBTi-validated combined scope 1+2+3 absolute reduction target. Used
                           only when the company filed no separate scope 1+2 row, which is how
                           Apple and Alphabet file. Scope 3 dilutes it, so it ranks below the two
                           above.
    4  netzero_inferred    a net-zero or carbon-neutral pledge with a target year and no interim
                           number at all. A pledge with no milestone carries no explicit rate, so
                           we read it as the 90 percent absolute cut the SBTi Corporate Net-Zero
                           Standard requires before residual emissions may be neutralised, and take
                           the geometric rate to the pledge year. This is an interpretation, not a
                           disclosure: it is flagged as dq 3 or 4, promised_capped_at_netzero is
                           true, and the basis is named in promised_basis. Only pledges whose year
                           is still in the future are read this way.
    5  none                no usable numbers. promised_annual_reduction_pct stays null and the
                           company is counted in the missing tally. Nothing is filled in.

  The same 90 percent floor caps any explicit target of 100 percent or more, because "reduce
  absolute scope 1+2 emissions 100% by 2030" is the same physical claim as net zero and taken
  literally it makes the geometric rate diverge. Aptiv files exactly that.

  Intensity, engagement and renewable-electricity targets are excluded from the rate entirely. An
  intensity target can fall while absolute emissions rise, and SBTi "engagement" targets count the
  share of suppliers with their own targets, so averaging them with reduction percentages is wrong.
  They stay in the long table with their type recorded. So are targets covering only scope 2 or
  only scope 3, which say nothing about the stacks the EPA measures.

  Two horizon guards, both because the annual rate is a ratio and short or absurd horizons blow it
  up. Any basis needs at least 3 years between baseline and target. The inferred net-zero path also
  refuses a horizon over 45 years and falls back to the year of the assessed disclosure: Microsoft's
  Net Zero Tracker baseline is 1975, the year it promises to have removed its historical emissions
  back to, which is not an emissions-reduction baseline.

dq, PCAF-style, 1 = best
  1  validated absolute reduction target with a numeric value and both years (SBTi Target row)
  2  company-reported numeric target with an explicit percentage and both years, or a validated
     target whose value is not a cross-comparable absolute reduction
  3  target year present but the percentage had to be inferred from the target type (net zero)
  4  target year present, baseline year borrowed from the company's other target on the same record
     or from the year of the disclosure Net Zero Tracker assessed
  5  a target exists but carries no usable numbers

  Nothing is imputed silently. Every borrowed baseline sets baseline_year_imputed and is named in
  promised_baseline_source, and a company with no usable target keeps a null rate and is counted.

Ticker join, four exact routes and no fuzzy matching
  1  ISIN through OpenFIGI
  2  exact match on normalised company names, taken only when it is unambiguous
  3  the universe lane's name_to_ticker map, which carries SEC entity and former names. This is
     what reaches Exxon Mobil, United Parcel Service, Boston Properties, Westinghouse Air Brake
     Technologies and salesforce.com
  4  a short hand-reviewed alias list for the rest

  Fuzzy matching is not used at all. At a 0.88 cutoff on this data it attached Polish "NUCO" to
  Nucor, UK "Mintel Group" to Intel and UK "Chevron Traffic Management" to Chevron. An ISIN match
  whose source company name shares no token with the S&P 500 security name is held back and printed
  rather than accepted, because the reverse ISIN lookup returns roughly one bad row in a hundred;
  the later routes usually recover the genuine ones, and the log says which were dropped.
"""

import csv
import hashlib
import io
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance"

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = UA

NZT_LIST = "https://zerotracker.net/api/v1/companies"
SBTI_COMPANIES = "https://files.sciencebasedtargets.org/production/files/companies-excel.xlsx"
SBTI_TARGETS = "https://files.sciencebasedtargets.org/production/files/targets-excel.xlsx"
OPENFIGI = "https://api.openfigi.com/v3/mapping"
SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"

# Net-zero pledges carry no interim number. The SBTi Corporate Net-Zero Standard requires at least
# a 90% absolute cut before residual emissions may be neutralised, so that is what we read a bare
# "net zero by 2050" as promising. 100% would make the geometric rate diverge.
NET_ZERO_ABATEMENT_PCT = 90.0

# Net Zero Tracker's end_target vocabulary. These all describe a state of no net emissions by the
# target year rather than a numeric cut, so they get the abatement floor above.
NET_ZERO_LABELS = {
    "Net zero",
    "Carbon neutral(ity)",
    "Climate neutral",
    "GHG neutral(ity)",
    "Zero emissions",
    "Zero carbon",
    "Net negative",
    "Carbon negative",
}

LICENCES = {
    "net_zero_tracker": {
        "licence": (
            "No explicit open licence. The API is published free and without a key and the "
            "methodology page asks to be cited as: Net Zero Tracker. Energy and Climate "
            "Intelligence Unit, Data-Driven EnviroLab, NewClimate Institute, Oxford Net Zero. 2026."
        ),
        "redistribution": (
            "We may publish scores derived from this data with visible attribution and a link back "
            "to zerotracker.net. We do not republish their raw table as a downloadable file."
        ),
    },
    "sbti": {
        "licence": (
            "Website terms of use permit retrieving and storing content for research and other "
            "non-commercial use, provided the Science Based Targets initiative is credited as the "
            "source with a link to the relevant page."
        ),
        "redistribution": (
            "Derived numbers may be published for non-commercial research with attribution to the "
            "Science Based Targets initiative and a link to sciencebasedtargets.org/target-dashboard. "
            "The raw targets-excel.xlsx is not rehosted."
        ),
    },
    "openfigi": {
        "licence": "OpenFIGI mapping API, free and usable without an API key.",
        "redistribution": (
            "We publish only the ISIN-to-ticker mapping needed for the join, attributed to OpenFIGI."
        ),
    },
    "sp500_constituents": {
        "licence": (
            "datasets/s-and-p-500-companies on GitHub, built from the Wikipedia S&P 500 component "
            "list (CC BY-SA 4.0)."
        ),
        "redistribution": "The constituent list may be republished with attribution.",
    },
}

# One fetch log per source, kept beside the cached bytes, so that provenance keeps reporting when
# each URL was actually first retrieved rather than when the script was last rerun.
FETCHLOG = {}


def fetchlog_path(source):
    return RAW / source / "_fetchlog.json"


def load_fetchlog(source):
    if source not in FETCHLOG:
        p = fetchlog_path(source)
        FETCHLOG[source] = json.loads(p.read_text()) if p.exists() else {}
    return FETCHLOG[source]


def record(source, url, status, payload, note=None, refresh=False):
    log = load_fetchlog(source)
    if url in log and not refresh:
        return log[url]
    rec = {
        "url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "http_status": status,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "licence": LICENCES[source]["licence"],
        "redistribution": LICENCES[source]["redistribution"],
    }
    if note:
        rec["note"] = note
    log[url] = rec
    return rec


def get(source, url, dest, note=None, timeout=300):
    """Fetch url once. A non-empty cache file is reused and no request is made."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        payload = dest.read_bytes()
        record(source, url, 200, payload, note=note)
        return payload
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    dest.write_bytes(r.content)
    record(source, url, r.status_code, r.content, note, refresh=True)
    return r.content


# ---------------------------------------------------------------- name normalisation

SUFFIX = (
    r"\b(incorporated|inc|corporation|corp|company|companies|co|limited|ltd|llc|lp|plc|nv|n v|sa|ag"
    r"|se|holdings|holding|group|the|international|intl|worldwide|global|class [abc]|usa|com)\b"
)


def norm(s):
    s = (s or "").lower()
    # SBTi writes Domino’s with a curly apostrophe and the index writes it straight
    for ch in "’‘ʼ`´":
        s = s.replace(ch, "'")
    for ch in "–—−":
        s = s.replace(ch, "-")
    for a, b in (("&", " and "), (".", " "), (",", " "), ("'", ""), ("-", " "), ("/", " ")):
        s = s.replace(a, b)
    for _ in range(4):
        s = re.sub(SUFFIX, " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def alnum_key(s):
    """The universe lane's name key: uppercase, alphanumerics only."""
    s = (s or "").upper().replace("&", " AND ")
    for ch in "’‘ʼ`´":
        s = s.replace(ch, "'")
    return re.sub(r"[^A-Z0-9]", "", s)


def load_name_map():
    """The universe lane's name_to_ticker, which carries SEC entity and former names.

    It is what resolves Exxon Mobil, United Parcel Service, Boston Properties, Westinghouse Air
    Brake Technologies and salesforce.com to their tickers. Optional: the lane still runs without it.
    """
    p = INTERIM / "ticker_aliases.json"
    if not p.exists():
        print("universe: no ticker_aliases.json, falling back to local name matching only")
        return {}
    m = json.loads(p.read_text()).get("name_to_ticker", {})
    print(f"universe: {len(m)} names in the universe lane's name_to_ticker map")
    return m


def shares_token(a, b):
    ta, tb = set(norm(a).split()), set(norm(b).split())
    return bool(ta & tb)


# Hand-reviewed leftovers, for source names that neither ISIN nor the universe lane's name map
# reaches. Each was checked by eye against the source's own company list; none came from a fuzzy
# matcher. Keys are S&P 500 tickers, values are the verbatim source company name, optionally
# qualified by country where the source holds two companies of that name.
NZT_ALIAS = {
    "DELL": "Dell|USA",
    "FERG": "Ferguson|GBR",
    "HBAN": "Huntington Bank|USA",
    "PRU": "Prudential|USA",
    "PSKY": "Paramount|USA",
    "SW": "WestRock|USA",
    "NEM": "Newmont Mining",
    "UPS": "UPS|USA",
}
SBTI_ALIAS = {
    "DD": "DuPont de Nemours, Inc.",
    "FDX": "FedEx Corporation",
    "J": "Jacobs",
    "LYB": "LyondellBasell Industries N.V.",
    "SW": "WestRock Company",
    "PSKY": "Paramount Global",
    "WM": "WM",
    "WTW": "WTW",
}


# ---------------------------------------------------------------- xlsx (stdlib, streaming)

XNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _shared_strings(z):
    out, buf = [], []
    with z.open("xl/sharedStrings.xml") as f:
        for ev, el in ET.iterparse(f, events=("end",)):
            if el.tag == XNS + "si":
                out.append("".join(buf))
                buf = []
                el.clear()
            elif el.tag == XNS + "t":
                buf.append(el.text or "")
    return out


def _colnum(ref):
    n = 0
    for c in re.match(r"([A-Z]+)", ref).group(1):
        n = n * 26 + (ord(c) - 64)
    return n - 1


def xlsx_rows(blob):
    """Stream an xlsx worksheet. Both SBTi workbooks hold a single sheet at sheet1.xml.

    sheet1.xml in targets-excel.xlsx is 46 MB uncompressed, so it is parsed incrementally. Cells
    that omit the r attribute are tracked by a running column index; a parser that assumes r is
    present crashes on this file.
    """
    z = zipfile.ZipFile(io.BytesIO(blob))
    ss = _shared_strings(z)
    with z.open("xl/worksheets/sheet1.xml") as f:
        cells, col = {}, 0
        for ev, el in ET.iterparse(f, events=("end",)):
            if el.tag == XNS + "c":
                ref, t = el.get("r"), el.get("t")
                v, ise = el.find(XNS + "v"), el.find(XNS + "is")
                if t == "s" and v is not None and v.text is not None:
                    val = ss[int(v.text)]
                elif t == "inlineStr" and ise is not None:
                    val = "".join(x.text or "" for x in ise.iter(XNS + "t"))
                else:
                    val = (v.text or "") if v is not None else ""
                col = _colnum(ref) if ref else col
                cells[col] = val
                col += 1
                el.clear()
            elif el.tag == XNS + "row":
                n = (max(cells) + 1) if cells else 0
                yield [cells.get(i, "") for i in range(n)]
                cells, col = {}, 0
                el.clear()


# ---------------------------------------------------------------- small parsers


def to_int(v):
    if v is None:
        return None
    m = re.search(r"(\d{4})", str(v))
    return int(m.group(1)) if m else None


def to_pct(v):
    if v is None or str(v).strip() in ("", "NA", "N/A", "None"):
        return None
    m = re.match(r"^\s*(-?[0-9]*\.?[0-9]+)\s*%?\s*$", str(v))
    return float(m.group(1)) if m else None


def excel_date(v):
    try:
        return (date(1899, 12, 30) + timedelta(days=float(v))).isoformat()
    except (TypeError, ValueError):
        return None


def geometric_rate(total_pct, base_year, target_year):
    """Compound percent per year implied by cutting total_pct between the two years."""
    if total_pct is None or not base_year or not target_year or target_year <= base_year:
        return None
    r = min(float(total_pct), 99.0) / 100.0
    n = target_year - base_year
    return round((1 - (1 - r) ** (1 / n)) * 100, 4)


def effective_reduction(pct):
    """A promise of a 100% or greater absolute cut is the same physical claim as net zero.

    Read at face value it makes the geometric rate diverge, so it gets the same abatement floor as
    a bare net-zero pledge. Returns (percent, capped).
    """
    if pct is not None and float(pct) >= 100.0:
        return NET_ZERO_ABATEMENT_PCT, True
    return pct, False


def linear_rate(total_pct, base_year, target_year):
    if total_pct is None or not base_year or not target_year or target_year <= base_year:
        return None
    return round(float(total_pct) / (target_year - base_year), 4)


# ---------------------------------------------------------------- universe


def load_universe():
    """Prefer the universe lane's table if it has landed, otherwise fetch the constituent list."""
    for name in ("universe.parquet", "sp500_universe.parquet", "sp500.parquet"):
        p = INTERIM / name
        if p.exists():
            df = pd.read_parquet(p)
            cols = {c.lower(): c for c in df.columns}
            if "ticker" in cols:
                name_col = next(
                    (cols[c] for c in ("security", "name", "company", "company_name") if c in cols),
                    None,
                )
                sec_col = next(
                    (cols[c] for c in ("gics_sector", "sector", "gics sector") if c in cols), None
                )
                out = pd.DataFrame(
                    {
                        "ticker": df[cols["ticker"]].astype(str).str.upper().str.replace("-", ".", regex=False),
                        "company": df[name_col] if name_col else df[cols["ticker"]],
                        "gics_sector": df[sec_col] if sec_col else None,
                    }
                )
                print(f"universe: {len(out)} rows from data/interim/{name}")
                return out
    blob = get("sp500_constituents", SP500_CSV, RAW / "sp500_constituents" / "constituents.csv")
    rows = list(csv.DictReader(io.StringIO(blob.decode("utf-8"))))
    out = pd.DataFrame(
        {
            "ticker": [r["Symbol"].strip().upper().replace("-", ".") for r in rows],
            "company": [r["Security"].strip() for r in rows],
            "gics_sector": [r["GICS Sector"].strip() for r in rows],
        }
    )
    print(f"universe: {len(out)} rows from the datasets.io S&P 500 constituent list")
    return out


# ---------------------------------------------------------------- Net Zero Tracker


def fetch_nzt(universe):
    blob = get("net_zero_tracker", NZT_LIST, RAW / "net_zero_tracker" / "companies.json")
    listing = json.loads(blob)
    print(f"nzt: {len(listing)} companies in the index")

    sp_norm = {norm(c) for c in universe["company"]}
    sp_first = {n.split(" ")[0] for n in sp_norm if n}
    alias_names = {norm(v) for v in NZT_ALIAS.values()}

    # Detail records are one call each, so only pull the ones that could be S&P 500 names: every
    # US company, anything whose normalised name matches, and anything sharing a first token.
    wanted = []
    for c in listing:
        n = norm(c["name"])
        if c["country"] == "USA" or n in sp_norm or n in alias_names or (n and n.split(" ")[0] in sp_first):
            wanted.append(c)
    print(f"nzt: {len(wanted)} candidate detail records to fetch")

    details, fetched = [], 0
    for i, c in enumerate(wanted):
        dest = RAW / "net_zero_tracker" / "companies" / f"{c['id_code']}.json"
        cached = dest.exists() and dest.stat().st_size > 0
        body = get("net_zero_tracker", c["api_url"], dest)
        details.append(json.loads(body))
        if not cached:
            fetched += 1
            time.sleep(0.3)
        if (i + 1) % 200 == 0:
            print(f"nzt: {i + 1}/{len(wanted)} details ({fetched} over the network)")
    print(f"nzt: {len(details)} detail records held ({fetched} fetched, {len(details) - fetched} cached)")
    return details


# ---------------------------------------------------------------- SBTi


def fetch_sbti():
    comp_blob = get("sbti", SBTI_COMPANIES, RAW / "sbti" / "companies-excel.xlsx")
    tgt_blob = get("sbti", SBTI_TARGETS, RAW / "sbti" / "targets-excel.xlsx", timeout=600)

    it = xlsx_rows(comp_blob)
    hdr = next(it)
    ci = {h: i for i, h in enumerate(hdr) if h}
    companies = [r for r in it if len(r) > ci["company_name"] and r[ci["company_name"]].strip()]
    print(f"sbti: companies-excel {len(companies)} rows x {len(ci)} named columns")

    it = xlsx_rows(tgt_blob)
    hdr = next(it)
    ti = {h: i for i, h in enumerate(hdr) if h}
    targets = [r for r in it if len(r) > ti["company_name"] and r[ti["company_name"]].strip()]
    print(f"sbti: targets-excel {len(targets)} rows x {len(ti)} named columns")
    print("sbti: action split " + str(dict(Counter(r[ti["action"]] for r in targets))))
    return companies, ci, targets, ti


# ---------------------------------------------------------------- OpenFIGI


def map_isins(isins):
    """ISIN to US ticker. Cached, so a second run makes no request."""
    cache_path = RAW / "openfigi" / "isin_ticker.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    todo = sorted(i for i in isins if i and i not in cache)
    print(f"openfigi: {len(isins)} distinct ISINs, {len(todo)} not yet cached")

    for k in range(0, len(todo), 10):
        batch = todo[k : k + 10]
        body = json.dumps([{"idType": "ID_ISIN", "idValue": i, "exchCode": "US"} for i in batch])
        r = SESSION.post(OPENFIGI, data=body, headers={"Content-Type": "application/json"}, timeout=60)
        if r.status_code == 429:
            time.sleep(30)
            r = SESSION.post(OPENFIGI, data=body, headers={"Content-Type": "application/json"}, timeout=60)
        r.raise_for_status()
        for isin, res in zip(batch, r.json()):
            hit = (res.get("data") or [None])[0]
            cache[isin] = {"ticker": hit["ticker"], "name": hit.get("name")} if hit else None
        if (k // 10) % 20 == 0:
            print(f"openfigi: {min(k + 10, len(todo))}/{len(todo)} resolved")
        time.sleep(2.6)

    cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    record(
        "openfigi",
        OPENFIGI,
        200,
        cache_path.read_bytes(),
        note=(
            f"POST endpoint, 10 ISINs per request at one request every 2.6s; "
            f"{len(cache)} ISINs in the cumulative cache. sha256 is of that cache file."
        ),
        refresh=bool(todo),
    )
    resolved = {k: v["ticker"] for k, v in cache.items() if v}
    print(f"openfigi: {len(resolved)}/{len(cache)} ISINs resolved to a US ticker")
    return cache


# ---------------------------------------------------------------- joining


def build_join(universe, records, name_key, isin_key, alias, figi, name_map, label):
    """Attach a source's records to S&P 500 tickers. Returns {ticker: [records]} and the method.

    Four exact routes, in order: ISIN through OpenFIGI, an exact match on normalised names, the
    universe lane's name_to_ticker map (which carries SEC entity and former names), then a short
    hand-reviewed alias list. No fuzzy matching anywhere.
    """
    by_norm = defaultdict(list)
    by_isin = defaultdict(list)
    by_name_exact = defaultdict(list)
    for r in records:
        by_norm[norm(r[name_key])].append(r)
        by_name_exact[r[name_key]].append(r)
        iso = (r[isin_key] or "").strip()
        if iso:
            by_isin[iso].append(r)

    # ISIN -> ticker, restricted to ISINs this source actually carries
    isin_to_ticker = {}
    for iso in by_isin:
        hit = figi.get(iso)
        if hit:
            isin_to_ticker.setdefault(hit["ticker"].upper().replace("-", "."), []).append(iso)

    # source name -> ticker, through the universe lane's map
    by_universe = defaultdict(list)
    for r in records:
        tk = name_map.get(alnum_key(r[name_key]))
        if tk:
            by_universe[tk].append(r)

    def country_of(r):
        return str(r.get("country", "")).upper()

    matched, method, rejected = {}, {}, []
    for _, row in universe.iterrows():
        tk, sec = row["ticker"], row["company"]
        got_isin = got_name = got_map = None
        for iso in isin_to_ticker.get(tk, []):
            cand = by_isin[iso]
            if shares_token(cand[0][name_key], sec):
                got_isin = cand
                break
            rejected.append((tk, sec, iso, cand[0][name_key]))
        n = norm(sec)
        if n in by_norm and len(by_norm[n]) == 1:
            got_name = by_norm[n]
        elif n in by_norm:
            # several source companies normalise to the same name; take a US one if unambiguous
            us = [r for r in by_norm[n] if country_of(r) in ("USA", "UNITED STATES")]
            if len(us) == 1:
                got_name = us
        if tk in by_universe:
            hits = by_universe[tk]
            names = {r[name_key] for r in hits}
            if len(names) == 1:
                got_map = hits
        if got_isin:
            matched[tk] = got_isin
            method[tk] = "isin"
        elif got_name:
            matched[tk] = got_name
            method[tk] = "name"
        elif got_map:
            matched[tk] = got_map
            method[tk] = "universe_name_map"
        elif tk in alias:
            want, _, want_country = alias[tk].partition("|")
            cand = [r for r in by_name_exact.get(want, []) if not want_country or country_of(r) == want_country]
            if cand:
                matched[tk] = cand
                method[tk] = "alias"
        if tk in matched and tk not in method:
            method[tk] = "unknown"

    # the routes are computed independently, so report how many each one could have carried alone
    isin_capable = sum(1 for _, row in universe.iterrows() if row["ticker"] in isin_to_ticker)
    name_capable = sum(1 for _, row in universe.iterrows() if norm(row["company"]) in by_norm)
    mc = Counter(method.values())
    print(f"{label}: matched {len(matched)}/{len(universe)} tickers by route " + str(dict(mc)))
    print(
        f"{label}:   reachable by ISIN alone {isin_capable}, by normalised name alone {name_capable}, "
        f"either {len(matched) - mc['universe_name_map'] - mc['alias']}"
    )
    if rejected:
        print(f"{label}: {len(rejected)} ISIN matches held back for sharing no name token with the constituent")
        for tk, sec, iso, nm in rejected[:12]:
            note = "recovered by another route" if tk in matched else "DROPPED"
            print(f"{label}:   hold {tk} {sec!r} <- {iso} {nm!r} [{note}]")
    return matched, method


# ---------------------------------------------------------------- long table


def nzt_scopes(rec, prefix):
    keys = [(prefix + "scope_1", "1"), (prefix + "scope_2", "2"), (prefix + "scope_3", "3")]
    yes = [lab for k, lab in keys if str(rec.get(k)) == "Yes"]
    part = [lab for k, lab in keys if str(rec.get(k)) == "Partial"]
    canon = "+".join(yes + [p + "~" for p in part]) or None
    detail = ";".join(f"scope{lab}={rec.get(k)}" for k, lab in keys)
    return canon, detail


def nzt_target_rows(tk, company, rec):
    rows = []
    end = (rec.get("end_target") or "").strip()
    if end and end.lower() not in ("no target", "not applicable"):
        y, b = to_int(rec.get("end_target_year")), to_int(rec.get("end_target_baseline_year"))
        pct = to_pct(rec.get("end_target_percentage_reduction"))
        canon, detail = nzt_scopes(rec, "")
        if pct is not None and y and b:
            dq = 2
        elif y and b and end in NET_ZERO_LABELS:
            dq = 3
        elif y:
            dq = 4
        else:
            dq = 5
        rows.append(
            dict(
                ticker=tk,
                company=company,
                target_type="net_zero",
                target_label=end,
                target_year=y,
                baseline_year=b,
                reduction_pct=pct,
                scopes_covered=canon,
                scopes_detail=detail,
                target_measure=None,
                target_submeasure=None,
                temperature_alignment=None,
                status=(rec.get("end_target_status") or None),
                source="net_zero_tracker",
                source_ref=rec.get("id_code"),
                source_url=rec.get("source_url"),
                last_updated=rec.get("last_updated"),
                dq=dq,
            )
        )
    interim = (rec.get("interim_target") or "").strip()
    if interim and interim.lower() not in ("no target", "not applicable"):
        y, b = to_int(rec.get("interim_target_year")), to_int(rec.get("interim_target_baseline_year"))
        pct = to_pct(rec.get("interim_target_percentage_reduction"))
        canon, detail = nzt_scopes(rec, "interim_")
        if pct is not None and y and b:
            dq = 2
        elif y and b:
            dq = 3
        elif y:
            dq = 4
        else:
            dq = 5
        rows.append(
            dict(
                ticker=tk,
                company=company,
                target_type="interim",
                target_label=interim,
                target_year=y,
                baseline_year=b,
                reduction_pct=pct,
                scopes_covered=canon,
                scopes_detail=detail,
                target_measure=None,
                target_submeasure=None,
                temperature_alignment=None,
                status=None,
                source="net_zero_tracker",
                source_ref=rec.get("id_code"),
                source_url=rec.get("source_url"),
                last_updated=rec.get("last_updated"),
                dq=dq,
            )
        )
    return rows


def sbti_target_rows(tk, company, rows_in, ti):
    out = []
    for r in rows_in:
        if r[ti["action"]] != "Target":
            continue
        val = to_pct(r[ti["target_value"]])
        b, y = to_int(r[ti["base_year"]]), to_int(r[ti["target_year"]])
        typ, sub = r[ti["type"]].strip(), r[ti["sub_type"]].strip()
        absolute = typ == "Absolute" and sub == "Reduction"
        dq = 1 if (absolute and val is not None and b and y) else 2
        out.append(
            dict(
                ticker=tk,
                company=company,
                target_type="sbti_validated",
                target_label=(r[ti["target"]] or "").strip() or None,
                target_year=y,
                baseline_year=b,
                reduction_pct=val,
                scopes_covered=(r[ti["scope"]] or "").strip() or None,
                scopes_detail=None,
                target_measure=typ or None,
                target_submeasure=sub or None,
                temperature_alignment=(r[ti["target_classification_short"]] or "").strip() or None,
                status=(r[ti["status"]] or "").strip() or None,
                source="sbti",
                source_ref=(r[ti["sbti_id"]] or "").strip() or None,
                source_url="https://sciencebasedtargets.org/target-dashboard",
                last_updated=excel_date(r[ti["date_published"]]),
                dq=dq,
            )
        )
    return out


# ---------------------------------------------------------------- per-company promise

# Scope 1+2 (or scope 1 alone) is what compares against EPA facility emissions. Scope 2 alone does
# not: every SBTi scope-2 row here is a renewable-electricity target, which says nothing about the
# stacks the EPA measures.
S12_SCOPES = {"1+2", "1", "1 + 2"}
COMBINED_SCOPES = {"1+2+3", "1 + 2 + 3"}

# A target horizon shorter than this annualises into noise. The upper bound applies only to the
# inferred net-zero path: Microsoft's Net Zero Tracker baseline is 1975, which is the year it
# promises to have removed its historical emissions back to, not an emissions-reduction baseline.
MIN_HORIZON_YEARS = 3
MAX_INFERRED_HORIZON_YEARS = 45
THIS_YEAR = date.today().year


def best_absolute(rows, scopes):
    cand = []
    for r in rows:
        if r["source"] != "sbti" or r["target_measure"] != "Absolute" or r["target_submeasure"] != "Reduction":
            continue
        if (r["scopes_covered"] or "") not in scopes:
            continue
        if not r["baseline_year"] or not r["target_year"]:
            continue
        if r["target_year"] - r["baseline_year"] < MIN_HORIZON_YEARS:
            continue
        pct, capped = effective_reduction(r["reduction_pct"])
        g = geometric_rate(pct, r["baseline_year"], r["target_year"])
        if g is not None:
            cand.append((g, r, pct, capped))
    if not cand:
        return None
    # several rows per scope are common, P&G files two for scope 3; take the most ambitious
    return max(cand, key=lambda t: t[0])


def _promise(rate, total, base, target, scopes, basis, dq, capped=False, imputed=False, base_src="reported"):
    return dict(
        promised_annual_reduction_pct=rate,
        promised_annual_reduction_pct_linear=linear_rate(total, base, target),
        promised_basis=basis,
        promised_total_reduction_pct=total,
        promised_baseline_year=base,
        promised_target_year=target,
        promised_scopes=scopes,
        promised_capped_at_netzero=capped,
        promised_baseline_source=base_src,
        baseline_year_imputed=imputed,
        dq=dq,
    )


def derive_promise(rows, fallback_baseline=None):
    """Pick the single target that defines the company's promised annual rate. See module docstring."""
    hit = best_absolute(rows, S12_SCOPES)
    if hit:
        g, r, pct, capped = hit
        return _promise(g, pct, r["baseline_year"], r["target_year"], r["scopes_covered"],
                        "sbti_s12_absolute", 2 if capped else 1, capped=capped)

    interim = [
        r
        for r in rows
        if r["target_type"] == "interim"
        and r["reduction_pct"] is not None
        and r["baseline_year"]
        and r["target_year"]
        and r["target_year"] - r["baseline_year"] >= MIN_HORIZON_YEARS
        # keep targets that cover scope 1 and those where Net Zero Tracker recorded no scope flags
        # at all; drop only the handful that are explicitly scope 2 or scope 3 alone
        and ("1" in (r["scopes_covered"] or "") or not r["scopes_covered"])
    ]
    if interim:
        scored = []
        for r in interim:
            pct, capped = effective_reduction(r["reduction_pct"])
            scored.append((geometric_rate(pct, r["baseline_year"], r["target_year"]), r, pct, capped))
        g, r, pct, capped = max(scored, key=lambda t: t[0])
        return _promise(g, pct, r["baseline_year"], r["target_year"],
                        r["scopes_covered"] or "unspecified", "nzt_interim", 2, capped=capped)

    hit = best_absolute(rows, COMBINED_SCOPES)
    if hit:
        g, r, pct, capped = hit
        return _promise(g, pct, r["baseline_year"], r["target_year"], r["scopes_covered"],
                        "sbti_combined", 2 if capped else 1, capped=capped)

    # A net-zero pledge with no interim number. Read as the SBTi 90% abatement floor.
    nz = [
        r
        for r in rows
        if r["target_type"] == "net_zero" and r["target_year"] and (r["target_label"] in NET_ZERO_LABELS)
    ]
    # a pledge whose year has already passed is not a forward-looking promise
    nz = [r for r in nz if r["target_year"] >= THIS_YEAR]
    if nz:
        r = min(nz, key=lambda r: r["target_year"])

        def usable(b):
            return bool(b) and MIN_HORIZON_YEARS <= r["target_year"] - b <= MAX_INFERRED_HORIZON_YEARS

        base, base_src, imputed = r["baseline_year"], "reported", False
        if not usable(base):
            # the company's own baseline from its other target on the same record, else the year of
            # the disclosure Net Zero Tracker assessed. Both are flagged, neither is silent.
            others = [o["baseline_year"] for o in rows if usable(o["baseline_year"]) and o["source"] == r["source"]]
            if others:
                base, base_src, imputed = min(others), "other_target_on_same_record", True
            elif usable(fallback_baseline):
                base, base_src, imputed = fallback_baseline, "nzt_status_date", True
            else:
                base = None
        g = geometric_rate(NET_ZERO_ABATEMENT_PCT, base, r["target_year"])
        if g is not None:
            return _promise(g, NET_ZERO_ABATEMENT_PCT, base, r["target_year"], r["scopes_covered"],
                            "netzero_inferred", 4 if imputed else 3, capped=True,
                            imputed=imputed, base_src=base_src)

    return _promise(None, None, None, None, None, "none", 5)


# ---------------------------------------------------------------- main


def main():
    INTERIM.mkdir(parents=True, exist_ok=True)
    PROV.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    universe = load_universe()
    n_uni = len(universe)
    name_map = load_name_map()

    nzt = fetch_nzt(universe)
    sbti_companies, ci, sbti_targets, ti = fetch_sbti()

    # ISINs worth resolving: everything Net Zero Tracker carries for a candidate, plus every SBTi
    # company that is US-domiciled or whose normalised name matches a constituent.
    sp_norm = {norm(c) for c in universe["company"]}
    isins = {(r.get("isin_id") or "").strip() for r in nzt}
    for r in sbti_companies:
        iso = r[ci["isin"]].strip()
        if iso and (iso.startswith("US") or norm(r[ci["company_name"]]) in sp_norm):
            isins.add(iso)
    isins.discard("")
    figi = map_isins(isins)

    nzt_recs = [dict(r) for r in nzt]
    nzt_match, nzt_method = build_join(universe, nzt_recs, "name", "isin_id", NZT_ALIAS, figi, name_map, "nzt")

    # targets-excel is one row per target, so fold it to one record per company before joining
    sbti_by_company = defaultdict(list)
    for r in sbti_targets:
        sbti_by_company[r[ti["company_name"]]].append(r)
    sbti_recs = [
        {
            "name": name,
            "isin_id": next((r[ti["isin"]].strip() for r in rows if r[ti["isin"]].strip()), ""),
            "country": next((r[ti["location"]].strip() for r in rows), ""),
            "rows": rows,
        }
        for name, rows in sbti_by_company.items()
    ]
    print(f"sbti: {len(sbti_recs)} distinct companies in targets-excel")
    sbti_match, sbti_method = build_join(universe, sbti_recs, "name", "isin_id", SBTI_ALIAS, figi, name_map, "sbti")

    # per-company validation status from companies-excel, keyed the same way
    comp_recs = [
        {"name": r[ci["company_name"]], "isin_id": r[ci["isin"]].strip(), "country": r[ci["location"]], "row": r}
        for r in sbti_companies
    ]
    comp_match, _ = build_join(universe, comp_recs, "name", "isin_id", SBTI_ALIAS, figi, name_map, "sbti_companies")

    # ---- long table
    long_rows = []
    for _, u in universe.iterrows():
        tk, company = u["ticker"], u["company"]
        for rec in nzt_match.get(tk, []):
            long_rows.append(nzt_target_rows(tk, company, rec))
        for rec in sbti_match.get(tk, []):
            long_rows.append(sbti_target_rows(tk, company, rec["rows"], ti))
    long_rows = [r for chunk in long_rows for r in chunk]
    long = pd.DataFrame(long_rows)
    print()
    print(f"targets long table: {len(long)} rows for {long['ticker'].nunique()} tickers")
    print("  by target_type: " + str(dict(long["target_type"].value_counts())))
    print("  by source:      " + str(dict(long["source"].value_counts())))
    print("  by dq:          " + str(dict(long["dq"].value_counts().sort_index())))
    print(f"  reduction_pct present: {int(long['reduction_pct'].notna().sum())}/{len(long)}")
    print(f"  target_year present:   {int(long['target_year'].notna().sum())}/{len(long)}")
    print(f"  baseline_year present: {int(long['baseline_year'].notna().sum())}/{len(long)}")

    # ---- per-company table
    by_ticker = defaultdict(list)
    for r in long_rows:
        by_ticker[r["ticker"]].append(r)

    comp_rows = []
    for _, u in universe.iterrows():
        tk = u["ticker"]
        rows = by_ticker.get(tk, [])
        nz = nzt_match.get(tk, [{}])[0] if tk in nzt_match else {}
        cr = comp_match.get(tk, [None])[0]
        c = cr["row"] if cr else None
        s12 = best_absolute(rows, S12_SCOPES)
        s3 = best_absolute(rows, {"3", "3.0"})
        rec = dict(
            ticker=tk,
            company=u["company"],
            gics_sector=u.get("gics_sector"),
            in_nzt=tk in nzt_match,
            in_sbti=tk in sbti_match or tk in comp_match,
            nzt_match_method=nzt_method.get(tk),
            sbti_match_method=sbti_method.get(tk),
            n_targets=len(rows),
            nzt_end_target=(nz.get("end_target") or None),
            nzt_end_target_year=to_int(nz.get("end_target_year")),
            nzt_end_target_status=(nz.get("end_target_status") or None),
            nzt_has_interim=bool(
                nz and (nz.get("interim_target") or "").strip().lower() not in ("", "no target", "not applicable")
            )
            if nz
            else None,
            nzt_interim_target_year=to_int(nz.get("interim_target_year")),
            nzt_interim_reduction_pct=to_pct(nz.get("interim_target_percentage_reduction")),
            nzt_scope3=(nz.get("scope_3") or None),
            nzt_has_plan=(nz.get("has_plan") or None),
            nzt_accountability=(nz.get("accountability") or None),
            nzt_reporting_mechanism=(nz.get("reporting_mechanism") or None),
            nzt_race_to_zero=(nz.get("race_to_zero_member") or None),
            nzt_source_url=(nz.get("source_url") or None),
            sbti_near_term_status=(c[ci["near_term_status"]].strip() or None) if c else None,
            sbti_near_term_classification=(c[ci["near_term_target_classification"]].strip() or None) if c else None,
            sbti_near_term_target_year=to_int(c[ci["near_term_target_year"]]) if c else None,
            sbti_net_zero_status=(c[ci["net_zero_status"]].strip() or None) if c else None,
            sbti_net_zero_year=to_int(c[ci["net_zero_year"]]) if c else None,
            sbti_s12_absolute_annual_pct=s12[0] if s12 else None,
            sbti_s3_absolute_annual_pct=s3[0] if s3 else None,
        )
        rec["scope3_ambition_gap_pp"] = (
            round(rec["sbti_s12_absolute_annual_pct"] - rec["sbti_s3_absolute_annual_pct"], 4)
            if s12 and s3
            else None
        )
        rec.update(derive_promise(rows, fallback_baseline=to_int(nz.get("status_date"))))
        comp_rows.append(rec)

    comp = pd.DataFrame(comp_rows)
    covered = comp[(comp["in_nzt"]) | (comp["in_sbti"])]
    print()
    print(f"company table: {len(comp)} rows (the full constituent list, absence is explicit)")
    print(f"  with any target record: {len(covered)}/{n_uni} ({len(covered) / n_uni:.1%})")
    print(f"  in Net Zero Tracker:    {int(comp['in_nzt'].sum())}/{n_uni}")
    print(f"  in SBTi:                {int(comp['in_sbti'].sum())}/{n_uni}")
    print(f"  in both:                {int((comp['in_nzt'] & comp['in_sbti']).sum())}/{n_uni}")
    print(
        f"  promised_annual_reduction_pct present: "
        f"{int(comp['promised_annual_reduction_pct'].notna().sum())}/{n_uni}"
    )
    print("  promised_basis: " + str(dict(comp["promised_basis"].value_counts())))
    print("  dq:             " + str(dict(comp["dq"].value_counts().sort_index())))
    print(f"  baseline_year_imputed: {int(comp['baseline_year_imputed'].sum())}")
    nzt_only = comp[comp["in_nzt"] & ~comp["in_sbti"]]
    pledged = comp["nzt_end_target"].isin(NET_ZERO_LABELS)
    print(f"  net-zero or equivalent pledge in NZT: {int(pledged.sum())}")
    print(f"  of those with no interim milestone at all: {int((pledged & (comp['nzt_has_interim'] == False)).sum())}")
    print(f"  in NZT with end_target 'No target': {int((comp['nzt_end_target'] == 'No target').sum())}")
    print(f"  claimed only (NZT, no SBTi record): {len(nzt_only)}")
    print(f"  SBTi near-term status: " + str(dict(comp['sbti_near_term_status'].value_counts())))
    print(f"  SBTi near-term classification: " + str(dict(comp['sbti_near_term_classification'].value_counts())))
    strict = comp[comp["dq"] <= 3]["promised_annual_reduction_pct"].notna().sum()
    print(f"  promised rate at dq<=3 (no borrowed baseline): {int(strict)}/{n_uni}")
    print(f"  promised rate capped at the net-zero floor: {int(comp['promised_capped_at_netzero'].sum())}")
    print("  promised_baseline_source: " + str(dict(comp["promised_baseline_source"].value_counts())))
    print(f"  scope3_ambition_gap computable: {int(comp['scope3_ambition_gap_pp'].notna().sum())}")
    p = comp["promised_annual_reduction_pct"].dropna()
    if len(p):
        print(
            f"  promised rate %/yr: min {p.min():.2f} p25 {p.quantile(.25):.2f} median {p.median():.2f} "
            f"p75 {p.quantile(.75):.2f} max {p.max():.2f}"
        )

    for col in ("target_year", "baseline_year", "dq"):
        long[col] = long[col].astype("Int64")
    long["reduction_pct"] = long["reduction_pct"].astype("Float64")
    for col in ("nzt_end_target_year", "nzt_interim_target_year", "sbti_near_term_target_year",
                "sbti_net_zero_year", "promised_baseline_year", "promised_target_year", "dq"):
        comp[col] = comp[col].astype("Int64")
    for col in ("in_nzt", "in_sbti", "nzt_has_interim", "baseline_year_imputed", "promised_capped_at_netzero"):
        comp[col] = comp[col].astype("boolean")

    long.to_parquet(INTERIM / "targets.parquet", index=False)
    comp.to_parquet(INTERIM / "targets_company.parquet", index=False)
    for source, log in FETCHLOG.items():
        fetchlog_path(source).parent.mkdir(parents=True, exist_ok=True)
        fetchlog_path(source).write_text(json.dumps(log, indent=1, sort_keys=True))
        (PROV / f"{source}.json").write_text(json.dumps(sorted(log.values(), key=lambda r: r["url"]), indent=1))
    print()
    print(f"wrote {INTERIM / 'targets.parquet'} ({len(long)} rows)")
    print(f"wrote {INTERIM / 'targets_company.parquet'} ({len(comp)} rows)")
    for source, log in FETCHLOG.items():
        print(f"wrote {PROV / (source + '.json')} ({len(log)} fetch records)")
    print(f"elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
