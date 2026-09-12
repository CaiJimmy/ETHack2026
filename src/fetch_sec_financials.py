"""S&P 500 fundamentals from SEC XBRL: fiscal years 2015-2025, plus a current market cap.

Everything comes from data.sec.gov/api/xbrl/companyfacts, one document per CIK, cached on disk.
Frames are used only to build a name index that catches companies whose financial history sits
under a predecessor CIK (ExxonMobil is the live example).

Every number carries the XBRL tag it came from. Where a figure had to be derived, the *_tag column
holds the formula and `dq` records how far from a filed number it is:
    1 straight from a reported tag in a 10-K
    2 reported tag, but not from an annual-report form
    3 derived from other reported tags by an accounting identity
    4 proxy or annualised estimate
Nothing is imputed. A value we could not find stays null and is counted.

Conventions worth knowing before you join to this:
  fy is the calendar year holding most of the fiscal period, so Walmart's year to 2026-01-31 is
  fy2025. That keeps fiscal years aligned with the calendar-year emissions data.
  Dual-class listings get one row each and carry the same company financials; is_primary_listing
  marks one of them so you can deduplicate. Sum market cap over cik, never over ticker.
  Share counts in the panel are as filed and are not restated for later stock splits. The count in
  market_cap.parquet is aged forward through any split that happened after the filing date,
  because the price it is multiplied by already reflects the split.

Outputs:
    data/interim/financials.parquet    one row per (ticker, fiscal year)
    data/interim/market_cap.parquet    one row per ticker, current price x shares outstanding
    data/interim/provenance/sec_financials.json
    data/interim/provenance/yahoo_prices.json
"""

import csv
import datetime as dt
import gzip
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data/raw")
INTERIM = os.path.join(ROOT, "data/interim")
PROV = os.path.join(INTERIM, "provenance")

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
SEC_SLEEP = 0.12          # ~8 req/s, under the SEC fair-access limit of 10
YAHOO_SLEEP = 0.35
FY_MIN, FY_MAX = 2015, 2025

CONSTITUENTS_URL = ("https://raw.githubusercontent.com/datasets/s-and-p-500-companies"
                    "/main/data/constituents.csv")

# Revenue hides behind a different tag for banks, insurers, utilities and REITs, and the pre-2018
# taxonomy used SalesRevenueNet where the post-2018 one uses RevenueFromContractWithCustomer*.
# First hit in this order wins.
REVENUE_TAGS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "RevenuesNetOfInterestExpense",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "RegulatedAndUnregulatedOperatingRevenue",
    "InterestAndDividendIncomeOperating",
    "InterestIncomeOperating",
    "RealEstateRevenueNet",
    "OperatingLeaseLeaseIncome",
    "OperatingLeasesIncomeStatementLeaseRevenue",
    "HealthCareOrganizationRevenue",
]
# The six revenue tags that still exist as frames. SalesRevenueNet and its siblings were retired
# from the taxonomy and 404 on that endpoint, though they are still present in the history of
# companyfacts documents.
FRAME_REVENUE_TAGS = REVENUE_TAGS[:4] + ["RegulatedAndUnregulatedOperatingRevenue",
                                         "InterestAndDividendIncomeOperating"]
NET_INCOME_TAGS = ["NetIncomeLoss", "ProfitLoss",
                   "NetIncomeLossAvailableToCommonStockholdersBasic"]
PRETAX_TAGS = [
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
]
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForCapitalImprovements",
    "PaymentsToAcquireOilAndGasProperty",
    "PaymentsToExploreAndDevelopOilAndGasProperties",
    "PaymentsToAcquireMachineryAndEquipment",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment",
    "PaymentsToAcquireRealEstate",
]
RND_TAGS = [
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    "ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost",
]
EQUITY_TAGS = ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "MembersEquity"]
DEBT_TAGS = ["DebtLongtermAndShorttermCombinedAmount",
             "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"]
DEBT_CORE = ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt"]
DEBT_ADDONS = [["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
               ["ShortTermBorrowings", "OtherShortTermBorrowings"]]
SHARES_WA_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding",
                  "WeightedAverageNumberOfSharesOutstandingBasic",
                  "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"]
ANNUAL_FORMS = ("10-K", "20-F", "40-F")

_prov = defaultdict(dict)


# ---------------------------------------------------------------- http + cache

def _atomic_write(path, blob):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, path)


def fetch(url, cache, source, ua=UA, sleep=SEC_SLEEP, tries=4):
    """Return raw bytes, from disk if we already have them. None on a hard 404."""
    if os.path.exists(cache) and os.path.getsize(cache) > 50:
        blob = open(cache, "rb").read()
        _record(source, url, blob, 200, cached=True, mtime=os.path.getmtime(cache))
        return blob
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
    backoff = 1.0
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                blob = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    blob = gzip.decompress(blob)
                status = resp.status
            _atomic_write(cache, blob)
            _record(source, url, blob, status, cached=False)
            time.sleep(sleep)
            return blob
        except urllib.error.HTTPError as err:
            if err.code == 404:
                _record(source, url, b"", 404, cached=False)
                return None
            time.sleep(backoff * (attempt + 1) if err.code != 429 else backoff * 4 * (attempt + 1))
        except Exception:
            time.sleep(backoff * (attempt + 1))
    _record(source, url, b"", 0, cached=False)
    return None


LICENCES = {
    "sec_financials": ("US federal government work, public domain (SEC EDGAR); the constituent "
                       "list is ODC-PDDL-1.0",
                       "Derived numbers may be published freely. EDGAR data carries no "
                       "redistribution restriction. The GICS sector labels that ride along in the "
                       "constituent list are S&P Global and MSCI property, so publish those as "
                       "display labels, not as a bulk data file."),
    "yahoo_prices": ("Yahoo Finance terms of service, no redistribution grant",
                     "Market caps derived from these prices may be shown with attribution. Do not "
                     "publish the raw price table as a downloadable dataset."),
}


def _record(source, url, blob, status, cached, mtime=None):
    ts = dt.datetime.fromtimestamp(mtime, dt.timezone.utc) if mtime else dt.datetime.now(dt.timezone.utc)
    licence, redistribution = LICENCES[source]
    _prov[source][url] = {
        "url": url,
        "retrieved_at": ts.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "http_status": status,
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest() if blob else None,
        "from_cache": cached,
        "licence": licence,
        "redistribution": redistribution,
    }


def write_provenance(source, licence, redistribution):
    os.makedirs(PROV, exist_ok=True)
    doc = {
        "source": source,
        "licence": licence,
        "redistribution": redistribution,
        "user_agent": UA,
        "written_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
                        .isoformat().replace("+00:00", "Z"),
        "n_urls": len(_prov[source]),
        "urls": sorted(_prov[source].values(), key=lambda r: r["url"]),
    }
    path = os.path.join(PROV, f"{source}.json")
    _atomic_write(path, json.dumps(doc, indent=1).encode())
    return path


# ---------------------------------------------------------------- fact picking

def _days(fact):
    a = dt.date.fromisoformat(fact["start"])
    b = dt.date.fromisoformat(fact["end"])
    return (b - a).days


def fiscal_year(end_iso):
    """Calendar year holding most of the fiscal period, so fiscal years line up with the
    calendar-year emissions data we join against downstream."""
    year, month = int(end_iso[:4]), int(end_iso[5:7])
    return year if month >= 6 else year - 1


def _units(facts, tag, taxonomy="us-gaap", unit="USD"):
    return facts.get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit, [])


def annual_facts(facts, tag, taxonomy="us-gaap", unit="USD"):
    return [f for f in _units(facts, tag, taxonomy, unit)
            if "start" in f and 330 <= _days(f) <= 400]


def instant_facts(facts, tag, taxonomy="us-gaap", unit="USD"):
    return [f for f in _units(facts, tag, taxonomy, unit) if "start" not in f]


def _choose(cands):
    """Pick one fact out of several for the same period: the annual report wins over a 10-Q
    comparative, and the earliest filing wins over later restatements, so the number is the one
    the company actually published for that year."""
    if not cands:
        return None
    annual = [f for f in cands if str(f.get("form", "")).startswith(ANNUAL_FORMS)]
    pool = annual or cands
    return min(pool, key=lambda f: (f.get("filed", "9999"), -abs(f.get("val") or 0)))


def annual_value(facts, tags, fy, taxonomy="us-gaap"):
    """First tag in the ladder that has an annual fact for this fiscal year."""
    for tag in tags:
        hit = _choose([f for f in annual_facts(facts, tag, taxonomy) if fiscal_year(f["end"]) == fy])
        if hit is not None:
            dq = 1 if str(hit.get("form", "")).startswith(ANNUAL_FORMS) else 2
            return hit["val"], tag, hit["end"], dq
    return None, None, None, None


def instant_value(facts, tags, fy, period_end, taxonomy="us-gaap", unit="USD"):
    for tag in tags:
        cands = instant_facts(facts, tag, taxonomy, unit)
        same = [f for f in cands if period_end and f["end"] == period_end]
        if not same:
            same = [f for f in cands if fiscal_year(f["end"]) == fy]
            if same:
                last = max(f["end"] for f in same)
                same = [f for f in same if f["end"] == last]
        hit = _choose(same)
        if hit is not None:
            dq = 1 if str(hit.get("form", "")).startswith(ANNUAL_FORMS) else 2
            return hit["val"], tag, hit["end"], dq
    return None, None, None, None


def _grouped_instant(facts, tag, taxonomy, unit, at_end):
    """Return the share count reported at one date. Multi-class filers tag one fact per class and
    the XBRL API strips the class dimension, so several facts share an accession and date; sum the
    distinct values or the count is only one class."""
    cands = [f for f in instant_facts(facts, tag, taxonomy, unit) if f["end"] == at_end]
    if not cands:
        return None, False
    by_accn = defaultdict(set)
    for f in cands:
        by_accn[f.get("accn")].add(f["val"])
    accn = min(by_accn, key=lambda a: (len(by_accn[a]) == 1, a or ""))
    vals = sorted(by_accn[accn])
    return (sum(vals) if len(vals) > 1 else vals[0]), len(vals) > 1


def shares_for_period(facts, fy, period_end):
    """Shares outstanding as close to the fiscal year end as the filings allow.

    dei:EntityCommonStockSharesOutstanding is the cover-page count and is the one we want, but for
    about 8% of the index (Berkshire, Visa, Meta, Comcast, Ford, Nike, UPS, Mastercard...) it is
    tagged per share class, so the dimensionless API never shows it. Weighted-average diluted
    shares is the honest stand-in there: it is a consolidated total across classes and sits within
    a couple of percent of the year-end count."""
    if period_end:
        end = dt.date.fromisoformat(period_end)
        cover = [f for f in instant_facts(facts, "EntityCommonStockSharesOutstanding", "dei", "shares")
                 if 0 <= (dt.date.fromisoformat(f["end"]) - end).days <= 150]
        if cover:
            at = min(f["end"] for f in cover)
            val, multi = _grouped_instant(facts, "EntityCommonStockSharesOutstanding", "dei",
                                          "shares", at)
            if val:
                return val, "dei:EntityCommonStockSharesOutstanding", at, multi, 1

        for tag in ("CommonStockSharesOutstanding", "CommonStockSharesIssued"):
            same = [f for f in instant_facts(facts, tag, "us-gaap", "shares")
                    if f["end"] == period_end]
            if same:
                val, multi = _grouped_instant(facts, tag, "us-gaap", "shares", period_end)
                if val:
                    return val, f"us-gaap:{tag}", period_end, multi, 2

    for tag in SHARES_WA_TAGS:
        cands = [f for f in annual_facts(facts, tag, "us-gaap", "shares")
                 if fiscal_year(f["end"]) == fy]
        if cands:
            at = max(f["end"] for f in cands)
            val = max(f["val"] for f in cands if f["end"] == at)
            return val, f"us-gaap:{tag}", at, False, 3
    return None, None, None, False, None


def latest_shares(facts):
    """Most recent share count, for the market cap table. A stale count is worse than none: the
    last dimensionless count Berkshire filed is from 2011 and is denominated in class A shares,
    which would price the company at under a billion dollars. Anything older than 400 days is
    dropped."""
    floor = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    out = []
    cover = instant_facts(facts, "EntityCommonStockSharesOutstanding", "dei", "shares")
    if cover:
        at = max(f["end"] for f in cover)
        val, multi = _grouped_instant(facts, "EntityCommonStockSharesOutstanding", "dei", "shares", at)
        if val:
            out.append((val, "dei:EntityCommonStockSharesOutstanding", at, multi, 1))
    for tag in ("CommonStockSharesOutstanding", "CommonStockSharesIssued"):
        cands = instant_facts(facts, tag, "us-gaap", "shares")
        if cands:
            at = max(f["end"] for f in cands)
            val, multi = _grouped_instant(facts, tag, "us-gaap", "shares", at)
            if val:
                out.append((val, f"us-gaap:{tag}", at, multi, 2))
    for tag in SHARES_WA_TAGS:
        cands = annual_facts(facts, tag, "us-gaap", "shares")
        if cands:
            at = max(f["end"] for f in cands)
            out.append((max(f["val"] for f in cands if f["end"] == at),
                        f"us-gaap:{tag}", at, False, 3))
    fresh = [o for o in out if o[2] >= floor]
    if not fresh:
        return None, None, None, False, None
    return min(fresh, key=lambda o: (o[4], -dt.date.fromisoformat(o[2]).toordinal()))


def public_float(facts):
    """Cover-page public float, latest first. Ares filed $0.33bn for 2025 against $25.5bn for 2024,
    which is an issuer error, so a float that collapses by more than five times falls back to the
    year before."""
    cands = instant_facts(facts, "EntityPublicFloat", "dei", "USD")
    if not cands:
        return None, None
    by_date = {}
    for f in cands:
        by_date.setdefault(f["end"], f["val"])
    dates = sorted(by_date)
    latest = dates[-1]
    if len(dates) > 1 and by_date[latest] < 0.2 * by_date[dates[-2]]:
        latest = dates[-2]
    return by_date[latest], latest


# ------------------------------------------------- revenue repairs (the ladder)

def revenue_repairs(facts, fy, latest_fy):
    """Run only when no tag in REVENUE_TAGS produced an annual fact for this year. Each level
    returns (value, tag, period_end, dq, method). Levels follow the cases the probe found in the
    ten S&P 500 companies the plain ladder misses."""

    # Merger or spin-off year: two non-overlapping 10-K stubs that tile one fiscal year.
    for tag in REVENUE_TAGS:
        stubs = sorted({(f["start"], f["end"], f["val"])
                        for f in _units(facts, tag)
                        if "start" in f and f.get("fp") == "FY"
                        and str(f.get("form", "")).startswith("10-K")
                        and fiscal_year(f["end"]) == fy})
        chain, total, covered = [], 0.0, 0
        for start, end, val in stubs:
            if chain and start <= chain[-1][1]:
                continue
            chain.append((start, end, val))
            total += val
            covered += (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
        if len(chain) >= 2 and 330 <= covered <= 400:
            return total, f"{tag} (stitched {len(chain)} stubs)", chain[-1][1], 3, "stitched_stubs"

    # Issuer duration error: the fp=FY fact in the 10-K carries a quarter-length start date.
    # L3Harris files its $21.9bn FY2025 revenue with a 90-day start. Only accept it if it clears
    # the same year's nine-month figure by about one quarter, which is what separates a full year
    # filed with a broken date from an ordinary quarter.
    for tag in REVENUE_TAGS:
        cands = [f for f in _units(facts, tag)
                 if "start" in f and f.get("fp") == "FY"
                 and str(f.get("form", "")).startswith("10-K")
                 and fiscal_year(f["end"]) == fy and not 330 <= _days(f) <= 400]
        if not cands:
            continue
        hit = max(cands, key=lambda f: f["end"])
        ytd = [f["val"] for f in _units(facts, tag)
               if "start" in f and 240 <= _days(f) <= 290 and fiscal_year(f["end"]) == fy]
        if not ytd or max(ytd) <= 0:
            continue
        if 1.05 <= hit["val"] / max(ytd) <= 1.75:
            return (hit["val"], f"{tag} (10-K FY fact, issuer duration error)", hit["end"], 3,
                    "repaired_duration")

    # No revenue tag in any standard taxonomy: the company uses an extension tag, which the XBRL
    # API does not expose. Back it out of the income statement identity.
    op = {f["end"]: f["val"] for f in annual_facts(facts, "OperatingIncomeLoss")
          if fiscal_year(f["end"]) == fy}
    cost = {f["end"]: f["val"] for f in annual_facts(facts, "CostsAndExpenses")
            if fiscal_year(f["end"]) == fy}
    shared = sorted(set(op) & set(cost))
    if shared:
        end = shared[-1]
        return op[end] + cost[end], "OperatingIncomeLoss + CostsAndExpenses", end, 3, "identity"

    # Newly public: no annual period exists yet. Scale the longest year-to-date fact.
    if fy == latest_fy:
        ytd = []
        for tag in REVENUE_TAGS:
            for f in _units(facts, tag):
                if "start" in f and 150 <= _days(f) <= 300 and fiscal_year(f["end"]) == fy:
                    ytd.append((f["end"], _days(f), f["val"], tag))
        if ytd:
            ytd.sort()
            end, days, val, tag = ytd[-1]
            return val * 365.0 / days, f"{tag} (annualised {days}d)", end, 4, "annualised_ytd"

    return None, None, None, None, None


def revenue_candidates(facts, fy):
    """Every revenue tag that has an annual fact for this year, in ladder order."""
    out = []
    for tag in REVENUE_TAGS:
        val, _, end, dq = annual_value(facts, [tag], fy)
        if val:                       # a zero revenue line is a tagging artefact, not a fact
            out.append((val, tag, end, dq))
    return out


def pick_revenue_tag(cand_by_fy, op_by_fy):
    """One revenue definition per company, held across every year.

    Picking the first ladder hit year by year produces fake swings: Bank of New York tags
    Revenues in ten of eleven years and only interest income in 2016, and taking that one year at
    face value shows revenue falling from $15.1bn to $3.6bn and back. Tags that land below
    operating income in any year are fee-income fragments rather than a top line, so they are
    dropped first, then the earliest surviving tag in ladder order wins as long as it covers most
    of the panel."""
    years, order = {}, {t: i for i, t in enumerate(REVENUE_TAGS)}
    for fy, cands in cand_by_fy.items():
        for val, tag, _, _ in cands:
            years.setdefault(tag, set()).add(fy)
    if not years:
        return None
    survivors = []
    for tag, yrs in years.items():
        fragment = any(val < op_by_fy[fy]
                       for fy in yrs for val, t, _, _ in cand_by_fy[fy]
                       if t == tag and op_by_fy.get(fy) is not None)
        if not fragment:
            survivors.append(tag)
    if not survivors:
        survivors = list(years)
    # The taxonomy changed under these companies in 2018: DuPont tags Revenues through 2020 and
    # RevenueFromContractWithCustomer from 2019 on. Anchor on the tag that is still in use, or the
    # panel ends in the middle of a discontinued tag.
    newest = max(max(years[t]) for t in survivors)
    current = [t for t in survivors if max(years[t]) == newest]
    best = max(len(years[t]) for t in current)
    ranked = sorted(current, key=lambda t: order.get(t, 99))
    for tag in ranked:
        if len(years[tag]) >= 0.6 * best:
            return tag
    return ranked[0]


def operating_income(facts, fy, revenue):
    """OperatingIncomeLoss where it exists, then two identities, then an EBIT proxy. Banks and
    insurers rarely tag an operating income line at all, so pretax income plus interest expense is
    the honest stand-in and is labelled as such."""
    val, tag, end, dq = annual_value(facts, ["OperatingIncomeLoss"], fy)
    if val is not None:
        return val, tag, end, dq, "reported"

    gross, _, gend, _ = annual_value(facts, ["GrossProfit"], fy)
    opex, _, _, _ = annual_value(facts, ["OperatingExpenses"], fy)
    if gross is not None and opex is not None:
        return gross - opex, "GrossProfit - OperatingExpenses", gend, 3, "derived_gross_profit"

    costs, _, cend, _ = annual_value(facts, ["CostsAndExpenses"], fy)
    if revenue is not None and costs is not None:
        return revenue - costs, "revenue - CostsAndExpenses", cend, 3, "derived_costs"

    # Pretax income, with no interest add-back. Adding interest expense back for a bank inflates
    # the figure by the cost of its own funding: JPMorgan FY2023 goes from $61.6bn to $142.9bn.
    # Pretax is consistent across sectors and years, and understating the denominator is the
    # conservative direction for an earnings-at-risk ratio.
    pretax, ptag, pend, _ = annual_value(facts, PRETAX_TAGS, fy)
    if pretax is not None:
        return pretax, ptag, pend, 4, "pretax_proxy"

    net, _, nend, _ = annual_value(facts, NET_INCOME_TAGS, fy)
    tax, _, _, _ = annual_value(facts, ["IncomeTaxExpenseBenefit",
                                        "CurrentIncomeTaxExpenseBenefit"], fy)
    if net is not None and tax is not None:
        return net + tax, "NetIncomeLoss + IncomeTaxExpenseBenefit", nend, 4, "pretax_tax_addback"
    return None, None, None, None, None


def total_debt(facts, fy, period_end):
    val, tag, _, dq = instant_value(facts, DEBT_TAGS, fy, period_end)
    if val is not None:
        return val, tag, dq
    lt, ltag, _, dq = instant_value(facts, DEBT_CORE, fy, period_end)
    if lt is None:
        return None, None, None
    total, names = lt, [ltag]
    for group in DEBT_ADDONS:
        add, atag, _, _ = instant_value(facts, group, fy, period_end)
        if add is not None:
            total += add
            names.append(atag)
    return total, " + ".join(names), (dq if len(names) == 1 else 3)


# ---------------------------------------------------------------- entity names

_SUFFIX = ("CORPORATION", "CORP", "INCORPORATED", "INC", "COMPANY", "CO", "PLC", "HOLDINGS",
           "HOLDING", "LTD", "LIMITED", "LP", "GROUP", "THE")


def norm_name(name):
    out = "".join(ch for ch in name.upper() if ch.isalnum())
    for _ in range(3):
        for suf in _SUFFIX:
            if out.endswith(suf) and len(out) > len(suf):
                out = out[: -len(suf)]
                break
        else:
            break
    return out


# ---------------------------------------------------------------------- driver

def load_constituents():
    blob = fetch(CONSTITUENTS_URL, os.path.join(RAW, "datahub/constituents.csv"),
                 "sec_financials", sleep=0.0)
    rows = list(csv.DictReader(blob.decode().splitlines()))
    listings = []
    for row in rows:
        listings.append({
            "ticker": row["Symbol"].strip().upper(),
            "cik": int(row["CIK"]),
            "company": row["Security"].strip(),
            "gics_sector": row["GICS Sector"].strip(),
        })
    return listings


def load_companyfacts(cik):
    blob = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                 os.path.join(RAW, f"sec/companyfacts/CIK{cik:010d}.json"), "sec_financials")
    if not blob:
        return None
    try:
        return json.loads(blob)
    except Exception:
        return None


def build_alias_index():
    """Companies that reorganise keep filing under the old CIK while the ticker map already points
    at the new holdco. Exact normalised name equality against the CY2025 revenue frames finds the
    CIK that actually holds the history. Prefix matching is not safe here: it matches
    'Sea Limited' to 'Seagate Technology'."""
    index = {}
    for tag in FRAME_REVENUE_TAGS:
        blob = fetch(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/CY2025.json",
                     os.path.join(RAW, f"sec/frames/us-gaap_{tag}_USD_CY2025.json"), "sec_financials")
        if not blob:
            continue
        for row in json.loads(blob).get("data", []):
            index.setdefault(norm_name(row["entityName"]), (row["cik"], row["entityName"]))
    return index


def company_panel(cik, facts_doc, latest_fy):
    """One dict per fiscal year for a single company."""
    facts = facts_doc.get("facts", {})
    years = list(range(FY_MIN, FY_MAX + 1))
    cand_by_fy = {fy: revenue_candidates(facts, fy) for fy in years}
    provisional = {fy: (cand_by_fy[fy][0][0] if cand_by_fy[fy] else None) for fy in years}
    op_by_fy = {fy: operating_income(facts, fy, provisional[fy])[0] for fy in years}
    primary = pick_revenue_tag(cand_by_fy, op_by_fy)

    revenue = {}
    for fy in years:
        hit = next((c for c in cand_by_fy[fy] if c[1] == primary), None)
        if hit:
            revenue[fy] = (hit[0], hit[1], hit[2], hit[3], "reported")
            continue
        # No fact under the company's own revenue tag this year. Another tag is only acceptable if
        # it sits at the same scale as the nearest year that does have the primary tag.
        ref = None
        for step in range(1, len(years)):
            for other in (fy - step, fy + step):
                near = next((c for c in cand_by_fy.get(other, []) if c[1] == primary), None)
                if near:
                    ref = near[0]
                    break
            if ref:
                break
        pick = None
        if ref and cand_by_fy[fy] and ref > 0:
            close = min(cand_by_fy[fy], key=lambda c: abs((c[0] / ref) - 1))
            if 0.4 <= close[0] / ref <= 2.5:
                pick = close
        elif ref is None and cand_by_fy[fy]:
            pick = cand_by_fy[fy][0]
        if pick:
            revenue[fy] = (pick[0], pick[1], pick[2], pick[3], "substitute_tag")
        else:
            revenue[fy] = revenue_repairs(facts, fy, latest_fy)

    rows = []
    for fy in years:
        rev, rev_tag, rev_end, rev_dq, rev_method = revenue[fy]
        oi, oi_tag, oi_end, oi_dq, oi_method = operating_income(facts, fy, rev)

        ni, ni_tag, ni_end, ni_dq = annual_value(facts, NET_INCOME_TAGS, fy)
        capex, capex_tag, capex_end, capex_dq = annual_value(facts, CAPEX_TAGS, fy)
        rnd, rnd_tag, rnd_end, rnd_dq = annual_value(facts, RND_TAGS, fy)

        ends = [e for e in (rev_end, oi_end, ni_end, capex_end, rnd_end) if e]
        period_end = max(set(ends), key=ends.count) if ends else None

        assets, assets_tag, assets_end, assets_dq = instant_value(facts, ["Assets"], fy, period_end)
        equity, equity_tag, _, equity_dq = instant_value(facts, EQUITY_TAGS, fy, period_end)
        if period_end is None:
            period_end = assets_end
        debt, debt_tag, debt_dq = total_debt(facts, fy, period_end)
        shares, shares_tag, shares_end, multi, shares_dq = shares_for_period(facts, fy, period_end)

        if all(v is None for v in (rev, oi, ni, assets, equity, capex, rnd, shares)):
            continue

        dq_scores = [d for d in (rev_dq, oi_dq, ni_dq, assets_dq, equity_dq, capex_dq, rnd_dq,
                                 shares_dq) if d]
        rows.append({
            "cik": f"{cik:010d}",
            "fy": fy,
            "period_end": period_end,
            "revenue": rev, "revenue_tag": rev_tag, "revenue_method": rev_method,
            "operating_income": oi, "operating_income_tag": oi_tag,
            "operating_income_method": oi_method,
            "net_income": ni, "net_income_tag": ni_tag,
            "assets": assets, "assets_tag": assets_tag,
            "equity": equity, "equity_tag": equity_tag,
            "capex": capex, "capex_tag": capex_tag,
            "rnd": rnd, "rnd_tag": rnd_tag,
            "total_debt": debt, "total_debt_tag": debt_tag,
            "shares_outstanding": shares, "shares_tag": shares_tag,
            "shares_asof": shares_end, "shares_multiclass_summed": multi,
            "dq": max(dq_scores) if dq_scores else None,
        })
    return rows


def yahoo_chart(ticker):
    """Two years of daily closes plus split events. One request per ticker gives the current price,
    the closes needed to price a public float, and the splits needed to age a share count."""
    symbol = ticker.replace(".", "-")
    blob = fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                 f"?range=2y&interval=1d&events=split",
                 os.path.join(RAW, f"yahoo/chart_{symbol}.json"), "yahoo_prices",
                 sleep=YAHOO_SLEEP, tries=3)
    if not blob:
        return None
    try:
        return json.loads(blob)["chart"]["result"][0]
    except Exception:
        return None


def chart_price(chart):
    if not chart:
        return None, None
    meta = chart.get("meta", {})
    stamp = meta.get("regularMarketTime")
    asof = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date().isoformat() if stamp else None
    return meta.get("regularMarketPrice"), asof


def chart_close_on(chart, date_iso):
    if not chart:
        return None
    try:
        stamps = chart["timestamp"]
        closes = chart["indicators"]["quote"][0]["close"]
    except Exception:
        return None
    best = None
    for stamp, close in zip(stamps, closes):
        day = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date().isoformat()
        if close is not None and day <= date_iso:
            best = close
    return best


def split_factor_since(chart, date_iso):
    """Product of every split after the given date. A share count filed on a 10-Q cover page is not
    restated when the stock splits, but the price we multiply it by is, so Amphenol's 2:1 split on
    2026-09-03 halves its market cap unless the count is aged forward."""
    if not chart or not date_iso:
        return 1.0
    factor = 1.0
    for event in (chart.get("events", {}).get("splits", {}) or {}).values():
        day = dt.datetime.fromtimestamp(event["date"], dt.timezone.utc).date().isoformat()
        num, den = event.get("numerator"), event.get("denominator")
        if not (day > date_iso and num and den):
            continue
        ratio = num / den
        # Yahoo also files spin-off price adjustments as splits, at ratios like 1.067 for Comcast
        # and Versant. Those change the price without changing the share count, so only a real
        # split counts.
        if 0.67 < ratio < 1.5:
            continue
        factor *= ratio
    return factor


def main():
    t0 = time.time()
    os.makedirs(INTERIM, exist_ok=True)

    listings = load_constituents()
    by_cik = defaultdict(list)
    for row in listings:
        by_cik[row["cik"]].append(row)
    print(f"constituents: {len(listings)} listings, {len(by_cik)} companies")

    alias_index = build_alias_index()
    print(f"frames name index: {len(alias_index)} filers")

    panel, alias_used, no_facts = [], {}, []
    for i, (cik, rows) in enumerate(sorted(by_cik.items())):
        doc = load_companyfacts(cik)
        source = f"companyfacts/CIK{cik:010d}"
        if doc is None:
            no_facts.append(rows[0]["ticker"])
            continue
        latest_fy = FY_MAX
        company_rows = company_panel(cik, doc, latest_fy)

        # If the CIK the ticker map points at has no recent revenue, the history probably sits with
        # a predecessor entity that files under the same name.
        recent = [r for r in company_rows
                  if r["fy"] >= FY_MAX - 1 and r["revenue_method"] == "reported"]
        if not recent:
            for candidate in {norm_name(rows[0]["company"]), norm_name(doc.get("entityName", ""))}:
                hit = alias_index.get(candidate)
                if hit and hit[0] != cik:
                    alt = load_companyfacts(hit[0])
                    if alt is None:
                        continue
                    alt_rows = company_panel(cik, alt, latest_fy)
                    if any(r["revenue_method"] == "reported" for r in alt_rows
                           if r["fy"] >= FY_MAX - 1):
                        company_rows = alt_rows
                        alias_used[rows[0]["ticker"]] = hit
                        source = f"companyfacts/CIK{hit[0]:010d} (predecessor of CIK{cik:010d})"
                    break

        for row in company_rows:
            row["source"] = source
            for listing in rows:
                out = dict(row)
                out["ticker"] = listing["ticker"]
                out["company"] = listing["company"]
                out["gics_sector"] = listing["gics_sector"]
                out["is_primary_listing"] = listing is rows[0]
                panel.append(out)
        if (i + 1) % 100 == 0:
            print(f"  companyfacts {i + 1}/{len(by_cik)}  rows so far {len(panel)}")

    if no_facts:
        print(f"no companyfacts document: {len(no_facts)} -> {no_facts}")
    for ticker, (alt_cik, name) in sorted(alias_used.items()):
        print(f"alias: {ticker} history read from CIK {alt_cik} ({name})")

    cols = ["ticker", "cik", "company", "gics_sector", "fy", "period_end",
            "revenue", "operating_income", "net_income", "assets", "equity", "capex", "rnd",
            "total_debt", "shares_outstanding",
            "revenue_tag", "revenue_method", "operating_income_tag", "operating_income_method",
            "net_income_tag", "assets_tag", "equity_tag", "capex_tag", "rnd_tag",
            "total_debt_tag", "shares_tag", "shares_asof", "shares_multiclass_summed",
            "dq", "is_primary_listing", "source"]
    fin = pd.DataFrame(panel)[cols].sort_values(["ticker", "fy"]).reset_index(drop=True)
    fin["retrieved_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) \
        .isoformat().replace("+00:00", "Z")
    out_fin = os.path.join(INTERIM, "financials.parquet")
    fin.to_parquet(out_fin, index=False)

    n_tickers = len(listings)
    print(f"\nfinancials.parquet: {len(fin)} rows, {fin.ticker.nunique()} tickers, "
          f"fy {fin.fy.min()}-{fin.fy.max()}")
    print(f"\ncoverage by fiscal year (tickers with a value, out of {n_tickers})")
    print(f"  {'fy':>4} {'rows':>5} {'revenue':>8} {'op_inc':>8} {'net_inc':>8} {'assets':>8} "
          f"{'equity':>8} {'capex':>8} {'rnd':>8} {'shares':>8}")
    for fy, grp in fin.groupby("fy"):
        print(f"  {fy:>4} {len(grp):>5} " + " ".join(
            f"{grp[c].notna().sum():>8}" for c in
            ["revenue", "operating_income", "net_income", "assets", "equity", "capex", "rnd",
             "shares_outstanding"]))

    latest = fin[fin.fy == FY_MAX]
    print(f"\nFY{FY_MAX} coverage out of {n_tickers} tickers:")
    for col in ["revenue", "operating_income", "net_income", "assets", "equity", "capex", "rnd",
                "total_debt", "shares_outstanding"]:
        got = latest[col].notna().sum()
        print(f"  {col:20s} {got:>3}/{n_tickers}  ({got / n_tickers * 100:.1f}%)")

    print("\noperating income method, FY2025:")
    for method, count in latest.operating_income_method.value_counts(dropna=False).items():
        print(f"  {str(method):26s} {count}")
    missing_oi = latest[latest.operating_income.isna()]
    if len(missing_oi):
        print(f"  missing operating income: {len(missing_oi)} tickers")
        print("   by sector: " + ", ".join(f"{s}={n}" for s, n in
                                           missing_oi.gics_sector.value_counts().items()))
        print("   " + " ".join(sorted(missing_oi.ticker)))

    print("\nrevenue method, FY2025:")
    for method, count in latest.revenue_method.value_counts(dropna=False).items():
        print(f"  {str(method):26s} {count}")
    missing_rev = sorted(latest[latest.revenue.isna()].ticker)
    if missing_rev:
        print(f"  missing revenue: {len(missing_rev)} -> {missing_rev}")

    # ---- market cap
    shares_now = {}
    for cik, rows in sorted(by_cik.items()):
        doc = load_companyfacts(cik)
        if doc is None:
            continue
        facts = doc.get("facts", {})
        val, tag, asof, multi, dq = latest_shares(facts)
        flt, flt_asof = public_float(facts)
        shares_now[cik] = (val, asof, multi, tag, dq, flt, flt_asof)

    # A handful of companies (Berkshire, Visa, Constellation, Erie) tag every share count and every
    # EPS line by share class, so the dimensionless XBRL API shows no usable count at all. Their
    # public float is dimensionless, and dividing it by the price on the day the float was measured
    # gives a share count that misses only the affiliate holdings. It is an estimate and is
    # labelled as one.
    float_floor = (dt.date.today() - dt.timedelta(days=550)).isoformat()
    mcap_rows = []
    for listing in listings:
        chart = yahoo_chart(listing["ticker"])
        price, asof = chart_price(chart)
        shares, sh_asof, multi, sh_tag, sh_dq, flt, flt_asof = shares_now.get(
            listing["cik"], (None, None, False, None, None, None, None))
        if shares is None and flt and flt_asof and flt_asof >= float_floor:
            then = chart_close_on(chart, flt_asof)
            if then:
                shares = flt / then
                sh_asof, sh_tag, sh_dq = flt_asof, "dei:EntityPublicFloat / price on float date", 4
        split = split_factor_since(chart, sh_asof)
        if shares is not None and split != 1.0:
            shares *= split
        mcap_rows.append({
            "ticker": listing["ticker"],
            "cik": f"{listing['cik']:010d}",
            "company": listing["company"],
            "price": price,
            "price_asof": asof,
            "price_source": "yahoo_v8_chart" if price is not None else None,
            "shares_outstanding": shares,
            "shares_tag": sh_tag,
            "shares_asof": sh_asof,
            "shares_multiclass_summed": multi,
            "split_factor_applied": split,
            "public_float_usd": flt,
            "public_float_asof": flt_asof,
            "market_cap": price * shares if (price is not None and shares is not None) else None,
            "is_primary_listing": listing is by_cik[listing["cik"]][0],
            "dq": sh_dq if (price is not None and shares is not None) else None,
        })
    mcap = pd.DataFrame(mcap_rows)
    # Dual-class tickers share one company share count, so the class A and class C rows each carry
    # the whole company. Sum market cap over unique CIK, not over tickers.
    mcap["market_cap_company"] = mcap.groupby("cik")["market_cap"].transform("mean")
    out_mcap = os.path.join(INTERIM, "market_cap.parquet")
    mcap.to_parquet(out_mcap, index=False)

    print(f"\nmarket_cap.parquet: {len(mcap)} rows")
    print(f"  price          {mcap.price.notna().sum()}/{len(mcap)}")
    print(f"  shares         {mcap.shares_outstanding.notna().sum()}/{len(mcap)}")
    print(f"  market cap     {mcap.market_cap.notna().sum()}/{len(mcap)}")
    total = mcap[mcap.is_primary_listing].market_cap_company.sum()
    print(f"  index total    ${total / 1e12:.2f}tn across "
          f"{mcap[mcap.is_primary_listing].market_cap_company.notna().sum()} companies")
    top = mcap.dropna(subset=["market_cap_company"]).sort_values("market_cap_company",
                                                                ascending=False).head(8)
    for _, row in top.iterrows():
        print(f"    {row.ticker:6s} ${row.market_cap_company / 1e12:6.3f}tn  "
              f"px {row.price:8.2f}  sh {row.shares_outstanding / 1e9:6.3f}bn")
    no_price = sorted(mcap[mcap.price.isna()].ticker)
    if no_price:
        print(f"  no price: {len(no_price)} -> {no_price}")
    split_hits = mcap[mcap.split_factor_applied != 1.0]
    if len(split_hits):
        print("  share counts aged forward through a split: " + ", ".join(
            f"{r.ticker} x{r.split_factor_applied:g}" for r in split_hits.itertuples()))
    print("  shares source: " + ", ".join(
        f"{t}={n}" for t, n in mcap.shares_tag.value_counts().items()))
    no_shares = sorted(mcap[mcap.shares_outstanding.isna()].ticker)
    if no_shares:
        print(f"  no shares: {len(no_shares)} -> {no_shares}")

    p1 = write_provenance("sec_financials", *LICENCES["sec_financials"])
    p2 = write_provenance("yahoo_prices", *LICENCES["yahoo_prices"])
    print(f"\nwrote {out_fin}")
    print(f"wrote {out_mcap}")
    print(f"wrote {p1}")
    print(f"wrote {p2}")
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
