"""EU 2020/1818 Article 12(1)(a) to (f) exclusion flags for the S&P 500, built three ways.

Article 12(1)(g), the 100 gCO2e/kWh power test, is the one exclusion we can measure directly from
EPA stack monitors, and the power-intensity lane already does that. Everything else in Article 12(1)
turns on a revenue share or on an activity judgement that no mandatory US filing reports in a form
you can read off. So this lane builds the flags from three independent sources and keeps all three,
because what the three disagree about is the interesting part.

    gics_proxy   GICS sub-industry mapped onto the Article 12 categories by an explicit table.
                 Free, reproducible by anyone with the constituent list, and shippable.
    sec_segment  SEC XBRL segment revenue from the DERA Financial Statement Data Sets, which is the
                 only public place dimensional XBRL facts exist. Two routes: commodity-specific
                 revenue tags, and generic revenue tags broken out on the ProductOrService or
                 BusinessSegments axis. Where it fires it implements the actual legal test, a
                 revenue share against the threshold in the regulation.
    vendor       Product-involvement screens from a Kaggle dump of commercial ESG data. Tagged
                 provenance_class = 'vendor' and confined to columns whose names start with
                 vendor_, so nothing here can leak into the headline score.

A fourth source turned out to be worth carrying and is kept in its own nbim_ columns: Norges Bank
Investment Management's public exclusion list. NBIM is not an ESG vendor, it is an asset owner
publishing its own decisions, and its criteria are worded almost exactly like Article 12 -
"production of tobacco", "production of nuclear weapons", "production of coal or coal-based energy",
plus conduct-based exclusions that are the same norms test as Article 12(1)(c). It is the only
source here that speaks to 12(1)(c) at all.

Output
    data/interim/revenue_exclusions.parquet   one row per (listing, Article 12 sub-rule)
    data/interim/provenance/revenue_exclusions.json

Sub-rule ids and thresholds are read out of data/interim/pab_rules.json at run time, never typed in
here, so a change to the parsed regulation propagates instead of drifting.

Reading the output
    flag_gics / flag_sec / flag_vendor   the three independent verdicts, null where the source is
                                         silent about that ticker or that rule
    agreement                            how many of the three non-null verdicts match flag_best
    n_sources                            how many of the three spoke at all
    flag_best + flag_basis + flag_dq     the verdict to trade on, which source decided it, and how
                                         far that source is from the text of the regulation

flag_dq, PCAF-style, 1 is best
    1  a revenue share measured from a filed 10-K, compared against the threshold in the article
    2  an institutional exclusion decision naming the same activity the article names (NBIM)
    3  GICS proxy where the sub-industry definition is the article's activity (Tobacco, Gas Utilities)
    4  GICS proxy where the sub-industry only usually implies the activity
    5  no source spoke; recorded as not excluded, which is an absence of evidence and not a finding
"""

import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_universe import normalise_name  # noqa: E402  same keys as ticker_aliases.json

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance"

# DERA publishes one zip per calendar quarter of filings. Four quarters catch every 10-K whatever
# the fiscal year end, which matters because Walmart, Deere and Oracle do not close in December.
DERA_QUARTERS = ["2025q3", "2025q4", "2026q1", "2026q2"]
DERA_DIR = RAW / "sec" / "financial-statement-data-sets"
DERA_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{q}.zip"

NBIM_URL = "https://www.nbim.no/en/responsible-investment/exclusion-of-companies/"
NBIM_CACHE = RAW / "revenue_exclusions" / "nbim_exclusions.html"

KAGGLE_DATASET = "mrbossjaysrb/global-corporate-esg-and-financial-dataset"
KAGGLE_DIR = RAW / "revenue_exclusions" / "kaggle"
KAGGLE_CSV = KAGGLE_DIR / "Global Corporate ESG and Financial Dataset.csv"


# ---------------------------------------------------------------------------------------------
# 1. The GICS proxy
# ---------------------------------------------------------------------------------------------
# One line per GICS sub-industry, mapping it onto the Article 12 categories and saying how sure the
# mapping is. Deliberately a table and not a regex: a regex over sub-industry names would put
# "Oil & Gas Equipment & Services" in the same bucket as "Integrated Oil & Gas", and the regulation
# does not, because a company selling drill bits derives no revenue from oil fuels.
#
# confidence
#   certain    the GICS sub-industry definition is the activity the article names
#   typical    the activity holds for the ordinary constituent of the sub-industry, not for all
#   ambiguous  the sub-industry straddles the article's line and only revenue data can settle it
#
# Categories: coal = Article 12(1)(d), oil = (e), gas = (f), tobacco = (b), weapons = (a).
# Article 12(1)(c), the UNGC and OECD conduct test, has no sector proxy at all and is left null
# rather than guessed at. Article 12(1)(g) belongs to the power-intensity lane.
GICS_ARTICLE12 = {
    # Extracts and refines crude, and gas is a minority of revenue at both Exxon and Chevron.
    "Integrated Oil & Gas": (["oil"], "typical"),
    # Explores for and extracts oil fuels. The 10% oil bar is low enough that the gas-weighted
    # members (EQT, Expand Energy) still clear it on liquids, but the 50% gas bar is not assumed
    # here: only segment revenue can tell a gas-weighted E&P from an oil-weighted one.
    "Oil & Gas Exploration & Production": (["oil"], "typical"),
    # Refining is named verbatim in Article 12(1)(e).
    "Oil & Gas Refining & Marketing": (["oil"], "certain"),
    # Midstream is the genuinely ambiguous class. Pipelines distribute both oil fuels and gaseous
    # fuels, and which of (e) or (f) bites depends on the mix, so both are flagged and marked.
    "Oil & Gas Storage & Transportation": (["oil", "gas"], "ambiguous"),
    # Deliberately not flagged. Article 12(1)(e) excludes exploration, extraction, distribution and
    # refining of oil fuels. Halliburton, SLB and Baker Hughes sell services to companies doing
    # those things and derive their revenue from service contracts, not from oil. A broader reading
    # is defensible and several index providers take it; this table takes the narrow one and says so.
    "Oil & Gas Equipment & Services": ([], "certain"),
    # Regulated distribution of gaseous fuels is the whole business, which is Article 12(1)(f).
    "Gas Utilities": (["gas"], "certain"),
    # Not in the index today, kept so the table survives index churn back towards coal miners.
    "Coal & Consumable Fuels": (["coal"], "certain"),
    # Deliberately not flagged for coal. Burning coal to make electricity is Article 12(1)(g), the
    # intensity test, not 12(1)(d), which covers exploration, mining, extraction, distribution and
    # refining of the fuel itself. Mapping coal-burning utilities onto (d) is the single most common
    # way to get this rulebook wrong, and it double-counts them against the power test.
    "Electric Utilities": ([], "certain"),
    "Independent Power Producers & Energy Traders": ([], "certain"),
    # Multi-utilities sell both power and piped gas. Gas is rarely half of revenue, so (f) is not
    # assumed, but this is the class most likely to be corrected by segment data.
    "Multi-Utilities": ([], "typical"),
    # Cultivation and production of tobacco, which is the exact wording of Article 12(1)(b).
    "Tobacco": (["tobacco"], "certain"),
    # Deliberately not flagged. Grocers, warehouse clubs, dollar stores and farm stores sell
    # cigarettes, and commercial involvement screens flag them for it, but Article 12(1)(b) excludes
    # cultivation and production, not retail. This is where the proxy and the vendor screen part.
    "Consumer Staples Merchandise Retail": ([], "certain"),
    "Food Retail": ([], "certain"),
    "Other Specialty Retail": ([], "certain"),
    # Defence primes. The article says "any activities related to controversial weapons", which in
    # practice means cluster munitions, anti-personnel mines, biological and chemical weapons and,
    # for most European administrators, nuclear weapons. Only some of this sub-industry builds any
    # of those, so the flag is coarse by construction and its precision is measured below against
    # NBIM's nuclear-weapons and cluster-munitions exclusions.
    "Aerospace & Defense": (["weapons"], "ambiguous"),
    # Deliberately not flagged, and a known miss. Honeywell ran the Kansas City National Security
    # Campus and is on NBIM's nuclear weapons list, but GICS files conglomerates by revenue mix.
    "Industrial Conglomerates": ([], "typical"),
    # Deliberately not flagged. Berkshire owns coal-fired utilities through Berkshire Hathaway
    # Energy, PacifiCorp and MidAmerican, all three of which NBIM excludes, but the listed issuer is
    # a holding company and no sector code can see through it.
    "Multi-Sector Holdings": ([], "typical"),
}

# Short category key -> the property of the parsed rule that identifies it. Read out of the
# regulation text rather than matched on rule ids, which are our names and not the regulation's.
CATEGORY_TESTS = {
    "coal": lambda r: "coal" in str(r.get("commodity", "")).lower(),
    "oil": lambda r: "oil" in str(r.get("commodity", "")).lower(),
    "gas": lambda r: "gaseous" in str(r.get("commodity", "")).lower(),
    "tobacco": lambda r: "tobacco" in r["quote"].lower(),
    "weapons": lambda r: "controversial weapons" in r["quote"].lower(),
    "ungc": lambda r: "global compact" in r["quote"].lower(),
}


# ---------------------------------------------------------------------------------------------
# 2. SEC XBRL segment revenue
# ---------------------------------------------------------------------------------------------
# The companyfacts API, which is where the brief pointed first, does not carry dimensional facts at
# all: it publishes one consolidated series per tag and drops every axis. Checked on ExxonMobil,
# whose companyfacts document has a single Revenues series and no ProductOrService breakdown of any
# kind. The DERA Financial Statement Data Sets are the only public SEC product that keeps the
# dimensions, in a `segments` column of num.txt written as Axis=Member pairs with the namespace and
# the word Axis stripped. That is what this reads.
#
# Two tests per commodity, and between them a band rather than a point estimate, because issuers tag
# overlapping product hierarchies on the same axis and naively summing members double counts:
#
#   lower bound   the largest single member that classifies purely to the commodity, over its
#                 consolidated revenue. A member is always a slice of the whole, so this cannot
#                 overstate. If the lower bound already clears the article's threshold, exclude.
#   upper bound   the sum of members over one decomposition that covers most of the business, with
#                 conjunction members like OilAndGas counted towards both commodities. If the upper
#                 bound is under the threshold, the company is in the clear.
#
# Between the two bounds the answer is null, and null is written out rather than resolved.
REVENUE_TAG_HINTS = ("Revenue", "Revenues", "Sales")
REVENUE_TAG_EXCLUDE = (
    "Deferred", "Unearned", "Cost", "Expense", "Tax", "Receivable", "Remaining",
    "Increase", "Decrease", "Percentage", "Concentration", "Contract", "Performance",
    "Gain", "Loss", "Proceeds", "Payments", "Impairment", "Securities", "Comprehensive",
    "Allowance", "Reserve", "Backlog", "PerShare",
)
# A member crossed with a geography, a customer class or a subsidiary is still a slice of the
# issuer's revenue, so the lower-bound test may use it. The decomposition test may not, because a
# product crossed with a geography is not a decomposition of the whole.
# Axes whose rows are not the registrant's own revenue and must never be counted.
DISQUALIFYING_AXES = {"EquityMethodInvestmentNonconsolidatedInvestee", "ConsolidatedEntities",
                      "OwnershipAxis", "RelatedPartyTransactionsByRelatedParty"}
PRODUCT_AXES = ("ProductOrService", "BusinessSegments", "SubsegmentsOfOperatingSegments")

# Commodity phrases, matched against the member name after CamelCase has been split into words.
# A member matching more than one commodity is a conjunction like OilAndGas: it is an aggregate of
# its own children more often than not, so it counts towards neither lower bound.
COMMODITY_WORDS = {
    "gas": ("natural gas", "gaseous", "lng", "liquefied natural gas", "ngl", "ngls",
            "natural gas liquids", "gas distribution", "gas utility"),
    # Bare "oil" is safe because the member name is split on case, so Oilseeds stays one word.
    # "refined"/"refining" is not safe and is handled separately below.
    "oil": ("oil", "crude", "petroleum", "gasoline", "diesel", "distillate", "jet fuel",
            "residual fuel", "fuel oil", "downstream"),
    "coal": ("coal", "lignite", "anthracite"),
    "tobacco": ("tobacco", "cigarette", "cigarettes", "cigar", "cigars", "smokeable",
                "smokeless", "smoke free", "nicotine", "snuff", "heated tobacco"),
}
# Refining is the trap. Bunge refines soybeans, Freeport refines copper rod, Archer-Daniels sells
# "Refined Products and Other" meaning vegetable oil. So a refining word only reads as Article
# 12(1)(e) when the issuer's own segment names carry no non-petroleum context. That test is made
# per company, from the company's own disclosure, not from its sector code.
REFINING_WORDS = ("refined", "refining", "refinery")
NON_PETROLEUM_CONTEXT = ("oilseed", "oilseeds", "soybean", "edible", "vegetable", "grain",
                         "carbohydrate", "nutrition", "agricultural", "copper", "smelting",
                         "concentrate", "mining", "precious metal", "gold", "sugar", "milling")
# Members that look like a commodity but are not the Article 12 activity.
COMMODITY_FALSE_FRIENDS = ("palm oil", "olive oil", "cooking oil", "vegetable oil", "edible oil",
                           "oilfield", "oil field", "gas turbine", "industrial gases",
                           "medical gas", "coal ash", "asphalt")
# Upstream is exploration and production of both oil and gas, so it is a conjunction like OilAndGas.
BOTH_OIL_AND_GAS = ("upstream", "exploration and production", "oil and gas")
# A member whose every word is in this vocabulary names no product. A decomposition made of these
# covers 100% of revenue and tells you nothing, which is exactly ExxonMobil's product axis: one
# member called SalesAndOtherOperatingRevenue. Tracked so it cannot be read as evidence of absence.
GENERIC_WORDS = {"sales", "sale", "other", "operating", "revenue", "revenues", "product",
                 "products", "service", "services", "total", "all", "and", "from", "contract",
                 "contracts", "with", "customer", "customers", "segment", "segments", "net",
                 "consolidated", "transferred", "at", "a", "point", "in", "time", "over", "the",
                 "of", "goods", "items", "corporate", "reportable", "aggregation", "before"}
# How much of a decomposition may sit in generic members before it stops being evidence of absence.
GENERIC_TOLERANCE = 0.20
# Members where the Article 12 activity only holds on the broad reading of "distribution". Hauling
# coal by rail is the live case: CSX and Norfolk Southern both report a coal revenue line well over
# the 1% bar, and whether that is distribution of hard coal is a legal question, not a data one.
BROAD_READING_WORDS = ("railway", "rail", "freight", "trucking", "logistics", "haulage",
                       "transportation", "coal services")

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def split_member(member):
    """CamelCase member name to a lowercase word string. NaturalGasSales -> 'natural gas sales'."""
    return _CAMEL.sub(" ", member).replace("_", " ").lower()


def classify_member(member, petroleum_context=True):
    """Article 12 commodity categories a segment member name belongs to.

    petroleum_context is the issuer-level switch described above: False where the company's own
    segment names carry agricultural or metals vocabulary, which turns refining words off.
    """
    text = split_member(member)
    for bad in COMMODITY_FALSE_FRIENDS:
        if bad in text:
            return set()
    cats = set()
    for cat, words in COMMODITY_WORDS.items():
        if any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words):
            cats.add(cat)
    if petroleum_context and any(re.search(r"\b" + w + r"\b", text) for w in REFINING_WORDS):
        cats.add("oil")
    if any(w in text for w in BOTH_OIL_AND_GAS):
        cats.update({"oil", "gas"})
    return cats


def is_generic_member(member):
    words = [w for w in split_member(member).split() if w]
    return bool(words) and all(w in GENERIC_WORDS for w in words)


def is_broad_reading(member):
    text = split_member(member)
    return any(w in text for w in BROAD_READING_WORDS)


def parse_segments(seg):
    """'BusinessSegments=Upstream;ProductOrService=Oil;' -> {'BusinessSegments': 'Upstream', ...}."""
    out = {}
    for part in seg.split(";"):
        if "=" in part:
            axis, _, member = part.partition("=")
            out[axis.strip()] = member.strip()
    return out


def is_revenue_tag(tag):
    if not any(h in tag for h in REVENUE_TAG_HINTS):
        return False
    if tag.startswith("RevenueFromContractWithCustomer"):
        return True
    return not any(bad in tag for bad in REVENUE_TAG_EXCLUDE)


def dera_paths():
    """Local zips for the four filing quarters, downloaded once and reused."""
    DERA_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for q in DERA_QUARTERS:
        path = DERA_DIR / f"{q}.zip"
        if not path.exists():
            url = DERA_URL.format(q=q)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = resp.read()
            path.write_bytes(body)
            print(f"  downloaded {q}.zip  {len(body):,} bytes")
        out.append((q, path))
    return out


def read_dera_segments(cik_to_ticker):
    """Annual segment and consolidated revenue facts from every 10-K our companies filed.

    Returns (facts, filings). facts rows are one XBRL number each, already restricted to duration
    facts covering the filing's own fiscal year, so a share is a share of that year's revenue.
    """
    import csv
    csv.field_size_limit(10 ** 9)

    filings = {}
    for q, path in dera_paths():
        with zipfile.ZipFile(path) as z:
            with z.open("sub.txt") as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, "utf-8", "replace"), delimiter="\t")
                for row in reader:
                    if not row["form"].startswith("10-K"):
                        continue
                    ticker = cik_to_ticker.get(int(row["cik"]))
                    if ticker is None:
                        continue
                    period = row["period"]
                    prev = filings.get(row["adsh"])
                    if prev is None:
                        filings[row["adsh"]] = dict(ticker=ticker, period=period, fy=row["fy"],
                                                    form=row["form"], quarter=q, cik=int(row["cik"]))
    print(f"  10-K filings matched to the universe: {len(filings):,} "
          f"covering {len({f['ticker'] for f in filings.values()}):,} tickers")

    # Keep only each ticker's most recent 10-K, so two fiscal years never mix in one share.
    best = {}
    for adsh, f in filings.items():
        cur = best.get(f["ticker"])
        if cur is None or f["period"] > filings[cur]["period"]:
            best[f["ticker"]] = adsh
    keep = set(best.values())

    rows = []
    for q, path in dera_paths():
        with zipfile.ZipFile(path) as z:
            with z.open("num.txt") as fh:
                reader = csv.reader(io.TextIOWrapper(fh, "utf-8", "replace"), delimiter="\t")
                header = next(reader)
                ix = {c: i for i, c in enumerate(header)}
                for row in reader:
                    adsh = row[ix["adsh"]]
                    if adsh not in keep:
                        continue
                    f = filings[adsh]
                    if row[ix["qtrs"]] != "4" or row[ix["ddate"]] != f["period"]:
                        continue      # only the filing's own full fiscal year
                    if row[ix["coreg"]]:
                        continue      # a co-registrant subsidiary's books, not the issuer's
                    if row[ix["uom"]] != "USD":
                        continue
                    tag = row[ix["tag"]]
                    if not is_revenue_tag(tag):
                        continue
                    try:
                        value = float(row[ix["value"]])
                    except ValueError:
                        continue
                    if value <= 0:
                        continue
                    rows.append((f["ticker"], f["period"], tag, row[ix["segments"]], value))
    facts = pd.DataFrame(rows, columns=["ticker", "period", "tag", "segments", "value"])
    facts = facts.drop_duplicates()
    print(f"  annual revenue facts from those filings: {len(facts):,} rows, "
          f"{facts.segments.eq('').sum():,} consolidated and "
          f"{facts.segments.ne('').sum():,} dimensional")
    return facts


def product_member(axes, petroleum=True):
    """The member naming what was sold, and the axis it came from. None if the row is not usable."""
    if DISQUALIFYING_AXES & set(axes):
        return None, None
    consol = axes.get("ConsolidationItems", "")
    if consol and "Intersegment" in consol:
        return None, None           # an elimination, not revenue
    for axis in PRODUCT_AXES:
        member = axes.get(axis)
        if member and classify_member(member, petroleum):
            return member, axis
    for axis in PRODUCT_AXES:
        if axis in axes:
            return axes[axis], axis
    return None, None


# Generic revenue tags whose consolidated value is total revenue. Commodity-specific tags such as
# RegulatedOperatingRevenueGas also carry a consolidated value, and dividing a member by that would
# make Xcel Energy read as 100% gas. So the denominator is always total revenue, never the tag's own.
GENERIC_REVENUE_TAGS = ("Revenues", "Revenue", "RevenueFromContractWithCustomerExcludingAssessedTax",
                        "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesAndOtherIncome",
                        "RegulatedAndUnregulatedOperatingRevenue", "SalesRevenueNet",
                        "SalesRevenueGoodsNet", "OperatingRevenue", "RevenuesNetOfInterestExpense")


def segment_shares(facts, fallback_revenue):
    """Per ticker, a lower and an upper bound on the revenue share of each Article 12 commodity.

    lower   the largest single member that classifies purely to the commodity. A member is a slice
            of the whole, so this never overstates and a lower bound over the threshold excludes.
    upper   over one decomposition of the business, the members classified to the commodity plus
            the members that name no product at all, since those could be anything. An upper bound
            under the threshold clears the company. Between the two the answer stays null.
    """
    out = {}
    for ticker, grp in facts.groupby("ticker", sort=False):
        consolidated = grp[grp.segments == ""].groupby("tag").value.max().to_dict()
        generic = {t: v for t, v in consolidated.items() if t in GENERIC_REVENUE_TAGS}
        denom = max(generic.values()) if generic else fallback_revenue.get(ticker)
        denom_source = "sec_consolidated" if generic else "financials_parquet"
        filed = fallback_revenue.get(ticker)
        if denom and filed and not 0.5 <= denom / filed <= 2.0:
            denom, denom_source = filed, "financials_parquet_denominator_disagreed"
        if not denom or denom <= 0:
            continue

        dim = grp[grp.segments != ""]
        # The issuer-level refining switch, read once from every member name this company filed.
        members_filed = set()
        for sgs in dim.segments.unique():
            axes = parse_segments(sgs)
            members_filed.update(axes[a] for a in PRODUCT_AXES if axes.get(a))
        all_text = " ".join(split_member(m) for m in members_filed)
        petroleum = not any(w in all_text for w in NON_PETROLEUM_CONTEXT)

        # Two lower bounds per commodity. A figure tagged ConsolidationItems=OperatingSegments comes
        # from the segment note and is gross of intersegment sales; a figure on the plain product
        # axis is the ASC 606 disaggregation of revenue from external customers. Delta Air Lines is
        # the case that forces the distinction: its refinery is 11.0% of revenue gross and 8.0% net,
        # so the 10% threshold in Article 12(1)(e) falls between the two readings.
        net, gross, groups = {}, {}, defaultdict(dict)
        for row in dim.itertuples(index=False):
            axes = parse_segments(row.segments)
            member, axis = product_member(axes, petroleum)
            if member is None:
                continue
            share = row.value / denom
            if share > 1.5:
                continue                # a parent total tagged against a smaller base
            cats = classify_member(member, petroleum)
            if axis == "ProductOrService" and not cats and axes.get("BusinessSegments"):
                cats = classify_member(axes["BusinessSegments"], petroleum)
            if len(cats) == 1:
                cat = next(iter(cats))
                book = gross if axes.get("ConsolidationItems") else net
                if share > book.get(cat, (0.0,))[0]:
                    book[cat] = (share, f"{row.tag}/{axis}={member}", is_broad_reading(member))
            if set(axes) - {axis, "ConsolidationItems"}:
                continue                # a product crossed with a geography is not a decomposition
            have = groups[(row.tag, axis)]
            have[member] = max(have.get(member, 0.0), row.value)

        lower, lower_member, lower_broad, lower_gross = {}, {}, {}, {}
        for cat in set(net) | set(gross):
            pick = net.get(cat) or gross[cat]
            lower[cat], lower_member[cat], lower_broad[cat] = pick
            lower_gross[cat] = cat not in net

        best = None
        for (tag, axis), members in groups.items():
            conjunctions = {m for m in members if len(classify_member(m, petroleum)) > 1}
            # Two candidates: every member, and every member bar the conjunctions, which are
            # usually the parent row of their own children and double count if left in.
            for label, keep in (("all", set(members)), ("no_conjunctions", set(members) - conjunctions)):
                if not keep:
                    continue
                total = sum(members[m] for m in keep)
                ratio = total / denom
                if not 0.80 <= ratio <= 1.35:
                    continue
                classified = defaultdict(float)
                generic_share = 0.0
                for m in keep:
                    cats = classify_member(m, petroleum)
                    if cats:
                        for cat in cats:
                            classified[cat] += members[m] / denom
                    elif is_generic_member(m):
                        generic_share += members[m] / denom
                # Pick the decomposition that leaves least revenue unexplained, not the one whose
                # members happen to add up closest to the total. Texas Pacific Land is the case:
                # its business segments are Land And Resource Management and Water Service And
                # Operations, which add to exactly 100% and name nothing, while its product axis
                # says Oil And Gas Royalties.
                explained = sum(classified.values()) + generic_share
                score = (1.0 - min(explained, 1.0)) + 0.05 * abs(ratio - 1.0) \
                    + (0.0 if label == "no_conjunctions" else 0.01)
                if best is None or score < best["score"]:
                    best = dict(score=score, group=f"{tag}/{axis}", variant=label, ratio=ratio,
                                classified={k: min(v, 1.0) for k, v in classified.items()},
                                generic_share=min(generic_share, 1.0))
        out[ticker] = dict(lower=lower, lower_member=lower_member, lower_broad=lower_broad,
                           lower_gross=lower_gross, upper=best, denominator=denom,
                           denominator_source=denom_source, n_dim_rows=len(dim),
                           petroleum_context=petroleum)
    return out


# ---------------------------------------------------------------------------------------------
# 3. Commercial product-involvement screens
# ---------------------------------------------------------------------------------------------
# A Kaggle redistribution of commercial ESG data, downloaded once through the Kaggle CLI. Nothing
# here is scraped from a vendor's own site. Every column this produces is prefixed vendor_ and
# carries provenance_class = 'vendor', and flag_vendor is never allowed to decide flag_best on a
# revenue-share rule, because an involvement screen is a different test from a revenue threshold.
#
# The screens split into two families with very different coverage, measured below rather than
# assumed: involvement.* is the richer set of 14 but is populated for almost nobody, while
# involvement_msci.* has only 4 screens and covers most of the index.
VENDOR_SCREENS = {
    # Article 12(1)(a). Both families carry it; either one saying yes is a yes.
    "weapons": ["involvement.Controversial Weapons", "involvement_msci.Controversial Weapons"],
    # Article 12(1)(b). Note this is an involvement screen, not a production screen, so it flags
    # supermarkets that sell cigarettes. The regulation excludes cultivation and production.
    "tobacco": ["involvement.Tobacco Products", "involvement_msci.Tobacco Products"],
    # Article 12(1)(d). Only the sparse family carries it, so its coverage is close to nil here.
    "coal": ["involvement.Thermal Coal"],
}
# Carried through to the output for context but not mapped onto any article. Military contracting
# is not controversial weapons: selling armoured vehicles is legal everywhere and Article 12(1)(a)
# is aimed at cluster munitions, mines, biological and chemical weapons.
VENDOR_CONTEXT_SCREENS = ["involvement.Military Contracting", "involvement.Small Arms",
                          "involvement.Palm Oil", "involvement.GMO", "involvement.Pesticides",
                          "involvement.Animal Testing"]


def load_vendor_screens(aliases):
    if not KAGGLE_CSV.exists():
        KAGGLE_DIR.mkdir(parents=True, exist_ok=True)
        rc = os.system(f'"{ROOT / ".venv/bin/kaggle"}" datasets download {KAGGLE_DATASET} '
                       f'-p "{KAGGLE_DIR}" --unzip')
        if rc != 0 or not KAGGLE_CSV.exists():
            print("  kaggle download failed; vendor screens will be all null")
            return pd.DataFrame(columns=["ticker"])
    df = pd.read_csv(KAGGLE_CSV, sep=";", dtype=str)
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper().str.replace("-", ".",
                                                                               regex=False)
    df["ticker"] = df["ticker"].map(aliases["aliases"])
    df = df[df.ticker.notna()]
    cols = [c for c in df.columns if c.startswith("involvement")]
    yes = df[cols].apply(lambda s: s.str.strip().str.lower().map({"yes": True, "no": False}))
    yes["ticker"] = df.ticker.values
    # Several rows per ticker where the dump carries more than one snapshot. Any yes wins, and a
    # ticker with only nulls stays null rather than becoming False.
    out = yes.groupby("ticker").max(numeric_only=False)
    print(f"  vendor rows joined to the universe: {len(df):,} over {out.shape[0]:,} tickers")
    for family, label in [("involvement.", "involvement.* (14 screens)"),
                          ("involvement_msci.", "involvement_msci.* (4 screens)")]:
        fam = [c for c in cols if c.startswith(family) and c != family.rstrip(".")]
        covered = out[fam].notna().any(axis=1).sum() if fam else 0
        print(f"    {label}: {covered} of {out.shape[0]} joined tickers carry any value")
    return out.reset_index()


# ---------------------------------------------------------------------------------------------
# 4. Norges Bank Investment Management's exclusion list
# ---------------------------------------------------------------------------------------------
# Not a vendor: an asset owner publishing the decisions of its own Council on Ethics. Worth having
# because its criteria are worded almost exactly like Article 12 and because it is the only source
# available to us that speaks to Article 12(1)(c), the UNGC and OECD conduct test.
#
# One thing this cannot do is Article 12(1)(d). NBIM's coal criterion is a product criterion that
# covers thermal coal mining and coal-fired generation together, and every S&P 500 company on it is
# a generator, which is Article 12(1)(g) and not (d). So NBIM confirms the power test and stays
# silent on the coal value chain, which is itself the finding: the index holds no coal miner.
NBIM_CRITERION_TO_CATEGORY = {
    "production of nuclear weapons": "weapons",
    "production of cluster munitions": "weapons",
    "sales of weapons": "weapons",              # matched as a prefix, the full wording is a sentence
    "production of tobacco": "tobacco",
    "production of coal or coal-based energy": "power",
    "production of coal-based energy": "power",
}
# Every conduct-based NBIM criterion is a finding under the same norms Article 12(1)(c) points at:
# the UNGC principles and the OECD Guidelines for Multinational Enterprises.
NBIM_CONDUCT_CATEGORY = "ungc"
# Hand-verified, because the normalised-name join misses these four and fuzzy matching on US
# company names is worthless on this data. The three Berkshire entities are wholly owned
# subsidiaries with their own listed debt; NBIM excludes them as issuers, and rolling them up to
# the listed parent is our interpretation, recorded as nbim_match_basis = 'subsidiary'.
NBIM_OVERRIDES = {
    "L3HARRISTECHNOLOGIES": ("LHX", "name"),
    "BERKSHIREHATHAWAYENERGY": ("BRK.B", "subsidiary"),
    "MIDAMERICANENERGY": ("BRK.B", "subsidiary"),
    "PACIFI": ("BRK.B", "subsidiary"),          # normalise_name eats the CORP in PacifiCorp
}


def load_nbim(aliases):
    NBIM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if NBIM_CACHE.exists():
        body = NBIM_CACHE.read_bytes()
        meta = json.loads(NBIM_CACHE.with_suffix(".meta.json").read_text())
    else:
        req = urllib.request.Request(NBIM_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            status = resp.status
        NBIM_CACHE.write_bytes(body)
        meta = dict(url=NBIM_URL, retrieved_at=datetime.now(timezone.utc).isoformat(),
                    http_status=status, bytes=len(body),
                    sha256=hashlib.sha256(body).hexdigest())
        NBIM_CACHE.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
    tables = pd.read_html(io.BytesIO(body))
    tbl = max(tables, key=len)
    tbl.columns = [str(c).strip() for c in tbl.columns]
    tbl["key"] = tbl["Company"].map(normalise_name)
    tbl["ticker"] = tbl["key"].map(aliases["name_to_ticker"])
    tbl["match_basis"] = tbl["ticker"].notna().map({True: "name", False: None})
    for key, (ticker, basis) in NBIM_OVERRIDES.items():
        hit = tbl["key"] == key
        tbl.loc[hit, "ticker"] = ticker
        tbl.loc[hit, "match_basis"] = basis
    matched = tbl[tbl.ticker.notna()].copy()
    print(f"  NBIM list: {len(tbl)} decisions, {len(matched)} joined to "
          f"{matched.ticker.nunique()} S&P 500 tickers "
          f"({(matched.match_basis == 'subsidiary').sum()} through a subsidiary)")

    def category(row):
        crit = str(row["Criterion"]).strip().lower()
        if str(row["Category"]).strip().lower().startswith("conduct"):
            return NBIM_CONDUCT_CATEGORY
        for prefix, cat in NBIM_CRITERION_TO_CATEGORY.items():
            if crit.startswith(prefix):
                return cat
        return None

    matched["category"] = matched.apply(category, axis=1)
    unmapped = matched[matched.category.isna()]
    if len(unmapped):
        print(f"    {len(unmapped)} matched decisions map to no Article 12 category: "
              f"{sorted(set(unmapped.Criterion))}")
    return matched, meta


# ---------------------------------------------------------------------------------------------
# 5. Assembly
# ---------------------------------------------------------------------------------------------
def load_article12_rules():
    """Article 12(1)(a) to (f), selected structurally from the parsed regulation, never by id.

    Article 12(1)(g) is left out because its basis is revenue_share_and_intensity and the
    power-intensity lane measures it from EPA stack monitors. Article 12(2), the taxonomy
    do-no-significant-harm test, is left out because nothing here can evaluate it.
    """
    rules = json.loads((INTERIM / "pab_rules.json").read_text())["rules"]
    out = []
    for rule in rules:
        if rule.get("article_number") != 12 or rule.get("type") != "exclusion":
            continue
        if rule.get("basis") not in ("revenue_share", "activity", "conduct"):
            continue
        category = next((c for c, test in CATEGORY_TESTS.items() if test(rule)), None)
        threshold = rule.get("parameters", {}).get("revenue_threshold_pct")
        out.append(dict(rule_id=rule["id"], article=rule["article"], basis=rule["basis"],
                        category=category, quote=rule["quote"],
                        threshold_pct=threshold,
                        threshold=None if threshold is None else threshold / 100.0))
    out.sort(key=lambda r: r["article"])
    for r in out:
        print(f"  {r['article']:>18}  {r['rule_id']:<40} basis={r['basis']:<13} "
              f"category={r['category']}  threshold={r['threshold_pct']}")
    return out


def gics_flag(sub_industry, category):
    """(flag, confidence, reason) for one sub-industry and one Article 12 category."""
    entry = GICS_ARTICLE12.get(sub_industry)
    if category is None or category == "ungc":
        # Article 12(1)(c) is a finding about conduct. No sector code can imply one, so this stays
        # null rather than being written out as a confident False for all 500 companies.
        return None, None, "no sector proxy exists for a conduct rule"
    if entry is None:
        # A sub-industry absent from the table triggers nothing. That is a real verdict for the
        # 100-odd sub-industries with no Article 12 activity, not a missing value.
        return False, "certain", "sub-industry carries none of the Article 12 activities"
    categories, confidence = entry
    if category in categories:
        return True, confidence, f"GICS {sub_industry} implies {category}"
    return False, confidence, f"GICS {sub_industry} does not imply {category}"


def kappa(a, b):
    """Cohen's kappa on two boolean sequences, written out so the number is inspectable."""
    n = len(a)
    if n == 0:
        return None
    tp = sum(1 for x, y in zip(a, b) if x and y)
    tn = sum(1 for x, y in zip(a, b) if not x and not y)
    fp = sum(1 for x, y in zip(a, b) if x and not y)
    fn = sum(1 for x, y in zip(a, b) if not x and y)
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n)
    if pe == 1.0:
        return None                 # both raters constant; kappa is undefined, not 0
    return (po - pe) / (1 - pe)


def build_table(universe, rules, shares, vendor, nbim):
    vendor_ix = vendor.set_index("ticker") if len(vendor) else None
    nbim_by_ticker = defaultdict(list)
    for row in nbim.itertuples(index=False):
        nbim_by_ticker[row.ticker].append(row)

    rows = []
    for u in universe.itertuples(index=False):
        sh = shares.get(u.ticker, {})
        for rule in rules:
            cat = rule["category"]
            flag_gics, confidence, reason = gics_flag(u.gics_sub_industry, cat)

            flag_sec, sec_share, sec_bound, sec_basis = None, None, None, None
            sec_broad, sec_gross = None, None
            if cat in ("coal", "oil", "gas", "tobacco") and sh:
                threshold = rule["threshold"]
                lower = sh["lower"].get(cat)
                dec = sh["upper"]
                upper = None
                if dec is not None:
                    upper = min(1.0, dec["classified"].get(cat, 0.0) + dec["generic_share"])
                if threshold is not None:
                    if lower is not None and lower >= threshold:
                        flag_sec, sec_share, sec_bound = True, lower, "lower"
                        sec_basis = sh["lower_member"].get(cat)
                        sec_broad = sh["lower_broad"].get(cat)
                        sec_gross = sh["lower_gross"].get(cat)
                    elif upper is not None and upper < threshold:
                        flag_sec, sec_share, sec_bound = False, upper, "upper"
                        sec_basis = f"{dec['group']} [{dec['variant']}]"
                else:
                    # Article 12(1)(b) sets no revenue threshold, so the segment route can only say
                    # whether the issuer reports any tobacco revenue at all, and can only say no
                    # when its decomposition actually names products.
                    if lower is not None and lower > 0:
                        flag_sec, sec_share, sec_bound = True, lower, "lower"
                        sec_basis = sh["lower_member"].get(cat)
                        sec_broad = sh["lower_broad"].get(cat)
                        sec_gross = sh["lower_gross"].get(cat)
                    elif (dec is not None and dec["classified"].get(cat, 0.0) == 0.0
                            and dec["generic_share"] <= GENERIC_TOLERANCE):
                        flag_sec, sec_share, sec_bound = False, 0.0, "upper"
                        sec_basis = f"{dec['group']} [{dec['variant']}]"

            flag_vendor, vendor_basis = None, None
            if vendor_ix is not None and u.ticker in vendor_ix.index:
                cols = [c for c in VENDOR_SCREENS.get(cat, []) if c in vendor_ix.columns]
                vals = [vendor_ix.at[u.ticker, c] for c in cols]
                spoke = [(c, v) for c, v in zip(cols, vals) if v is not None and v == v]
                if spoke:
                    flag_vendor = bool(any(v for _, v in spoke))
                    vendor_basis = "|".join(c for c, _ in spoke)

            flag_nbim, nbim_criterion, nbim_decision, nbim_match = None, None, None, None
            # NBIM's coal criterion covers mining and coal-fired generation together, and every
            # S&P 500 company on it is a generator. That is Article 12(1)(g), not (d), so it is
            # carried as a ticker-level cross-check for the power lane instead of as a coal flag.
            nbim_coal_power = any(r.category == "power" for r in nbim_by_ticker.get(u.ticker, []))
            hits = [r for r in nbim_by_ticker.get(u.ticker, []) if r.category == cat]
            if cat in ("weapons", "tobacco", "ungc"):
                flag_nbim = bool(hits)          # NBIM publishes findings, so no row is a weak no
                if hits:
                    nbim_criterion = "; ".join(sorted({str(r.Criterion) for r in hits}))
                    nbim_decision = "; ".join(sorted({str(r.Decision) for r in hits}))
                    nbim_match = "; ".join(sorted({str(r.match_basis) for r in hits}))

            # flag_best. A measured revenue share against the article's own threshold outranks
            # everything. After that, for the two activity rules and the conduct rule, an
            # institution that published an exclusion under the article's own wording outranks a
            # sector code. Vendor involvement screens never decide: they test a different thing.
            if flag_sec is not None:
                flag_best, basis, dq = flag_sec, "sec_segment", 1
            elif flag_nbim:
                flag_best, basis, dq = True, "nbim_exclusion", 2
            elif flag_gics is not None and rule["basis"] != "conduct":
                flag_best = bool(flag_gics)
                basis = "gics_proxy"
                dq = 3 if confidence == "certain" else 4
            elif flag_nbim is False:
                # NBIM reviewed this company and published no finding. That is a weak negative,
                # not a clean bill of health: the Council on Ethics works case by case and does
                # not sweep the whole S&P 500. dq stays 5.
                flag_best, basis, dq = False, "nbim_no_finding", 5
            else:
                flag_best, basis, dq = False, "no_source", 5

            trio = [f for f in (flag_gics, flag_sec, flag_vendor) if f is not None]
            rows.append(dict(
                ticker=u.ticker, cik=u.cik, company_name=u.company_name,
                gics_sector=u.gics_sector, gics_sub_industry=u.gics_sub_industry,
                is_primary_listing=bool(u.is_primary_listing),
                rule_id=rule["rule_id"], article=rule["article"], rule_basis=rule["basis"],
                rule_category=cat, threshold_pct=rule["threshold_pct"],
                flag_gics=flag_gics, gics_confidence=confidence, gics_reason=reason,
                flag_sec=flag_sec, sec_revenue_share=sec_share, sec_bound=sec_bound,
                sec_basis=sec_basis, sec_broad_reading=sec_broad,
                sec_gross_of_eliminations=sec_gross,
                sec_petroleum_context=sh.get("petroleum_context"),
                sec_denominator=sh.get("denominator"),
                sec_denominator_source=sh.get("denominator_source"),
                sec_decomposition=(sh["upper"] or {}).get("group") if sh.get("upper") else None,
                sec_decomposition_ratio=(sh["upper"] or {}).get("ratio") if sh.get("upper") else None,
                sec_generic_share=(sh["upper"] or {}).get("generic_share") if sh.get("upper") else None,
                flag_vendor=flag_vendor, vendor_basis=vendor_basis,
                vendor_provenance_class="vendor",
                flag_nbim=flag_nbim, nbim_criterion=nbim_criterion, nbim_decision=nbim_decision,
                nbim_match_basis=nbim_match, nbim_coal_power=nbim_coal_power,
                n_sources=len(trio),
                agreement=sum(1 for f in trio if f == flag_best),
                flag_best=flag_best, flag_basis=basis, flag_dq=dq,
            ))
    return pd.DataFrame(rows)


def confusion(df, rule, ours="flag_gics", theirs="flag_vendor", name="vendor"):
    """Confusion matrix, precision, recall and kappa for one rule, treating `theirs` as reference.

    The denominator is the tickers where both sources speak. Quoting a precision over the whole
    index when the reference covers a third of it would be the wrong number.
    """
    sub = df[(df.rule_id == rule) & df.is_primary_listing &
             df[ours].notna() & df[theirs].notna()]
    if sub.empty:
        print(f"    vs {name}: no ticker where both sources speak")
        return None
    a = sub[ours].astype(bool).tolist()
    b = sub[theirs].astype(bool).tolist()
    tp = sum(1 for x, y in zip(a, b) if x and y)
    fp = sum(1 for x, y in zip(a, b) if x and not y)
    fn = sum(1 for x, y in zip(a, b) if not x and y)
    tn = len(a) - tp - fp - fn
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    k = kappa(a, b)
    fmt = lambda v: "n/a" if v is None else f"{v:.3f}"
    print(f"    vs {name}: n={len(a)}  TP={tp} FP={fp} FN={fn} TN={tn}  "
          f"precision={fmt(prec)} recall={fmt(rec)} kappa={fmt(k)}")
    if fp:
        print(f"      we flag, {name} does not: "
              f"{', '.join(sorted(sub[sub[ours] & ~sub[theirs].astype(bool)].ticker))}")
    if fn:
        print(f"      {name} flags, we do not: "
              f"{', '.join(sorted(sub[~sub[ours].astype(bool) & sub[theirs]].ticker))}")
    return dict(rule_id=rule, reference=name, n=len(a), tp=tp, fp=fp, fn=fn, tn=tn,
                precision=prec, recall=rec, cohen_kappa=k)


def report(df, rules):
    print("\n" + "=" * 96)
    print("Article 12 exclusions: how many companies each source excludes, primary listings only")
    print("=" * 96)
    primary = df[df.is_primary_listing]
    for rule in rules:
        sub = primary[primary.rule_id == rule["rule_id"]]
        thr = "-" if rule["threshold_pct"] is None else f">={rule['threshold_pct']:g}%"
        print(f"\n{rule['article']}  {rule['rule_id']}  ({rule['basis']}, {thr})")
        for col, label in [("flag_gics", "gics_proxy"), ("flag_sec", "sec_segment"),
                           ("flag_vendor", "vendor"), ("flag_nbim", "nbim")]:
            spoke = sub[col].notna().sum()
            excl = int(sub[col].fillna(False).astype(bool).sum())
            print(f"    {label:<12} speaks for {spoke:>3}/500  excludes {excl:>3}"
                  + (f"  [{', '.join(sorted(sub[sub[col].fillna(False).astype(bool)].ticker))}]"
                     if 0 < excl <= 24 else ""))
        best = int(sub.flag_best.sum())
        print(f"    {'flag_best':<12} excludes {best:>3}  "
              f"by {dict(sub[sub.flag_best].flag_basis.value_counts())}")

    print("\n" + "=" * 96)
    print("The point of the lane: the GICS proxy cross-tabulated against the independent screens")
    print("=" * 96)
    stats = []
    for rule in rules:
        print(f"\n{rule['article']}  {rule['rule_id']}")
        for theirs, name in [("flag_vendor", "vendor"), ("flag_nbim", "nbim"),
                             ("flag_sec", "sec_segment")]:
            got = confusion(df, rule["rule_id"], "flag_gics", theirs, name)
            if got:
                stats.append(got)

    print("\n" + "=" * 96)
    print("Where a reader should not take these flags at face value")
    print("=" * 96)
    broad = primary[primary.sec_broad_reading.fillna(False).astype(bool) & primary.flag_sec.fillna(False).astype(bool)]
    if len(broad):
        for row in broad.itertuples(index=False):
            print(f"  {row.article} {row.ticker}: {row.sec_revenue_share:.1%} of revenue, but the "
                  f"activity is haulage. Article 12(1)(d) says distribution, so this is a legal "
                  f"reading and not a measurement error. Basis: {row.sec_basis}")
    weapons = primary[(primary.rule_category == "weapons") &
                      primary.flag_gics.fillna(False).astype(bool) &
                      (primary.flag_nbim == False)]                      # noqa: E712  nullable bool
    if len(weapons):
        print(f"  Article 12(1)(a): {', '.join(sorted(weapons.ticker))} are flagged by the sector "
              f"proxy and not by NBIM. NBIM's product criterion is nuclear weapons and cluster "
              f"munitions; the article says any activity related to controversial weapons, which "
              f"is wider. flag_best keeps the sector flag, which is the cautious reading and "
              f"costs precision. Set flag_basis = nbim_exclusion to take the narrow one.")
    gross = primary[primary.sec_gross_of_eliminations.fillna(False).astype(bool) & primary.flag_sec.fillna(False).astype(bool)]
    if len(gross):
        print(f"  {len(gross)} flags rest on a segment figure gross of intersegment sales: "
              f"{', '.join(sorted(set(gross.ticker)))}")
    for rule in rules:
        sub = primary[primary.rule_id == rule["rule_id"]]
        if rule["threshold_pct"] is None:
            continue
        undetermined = sub[sub.flag_sec.isna() & sub.flag_gics.fillna(False).astype(bool)]
        if len(undetermined):
            print(f"  {rule['article']}: the segment route could not settle "
                  f"{', '.join(sorted(undetermined.ticker))}; the measured band straddles the "
                  f"{rule['threshold_pct']:g}% threshold, so the GICS proxy decides and flag_dq is 3 or 4")

    print("\n" + "=" * 96)
    print("What the GICS proxy is worth, per rule, against the best independent reference")
    print("=" * 96)
    fmt = lambda v: "n/a" if v is None or v != v else f"{v:.2f}"
    for rule in rules:
        mine = [x for x in stats if x["rule_id"] == rule["rule_id"] and x["n"] > 0]
        if not mine:
            print(f"  {rule['article']}  no independent reference covers this rule")
            continue
        # Prefer whichever reference speaks for the most companies, and prefer a reference that
        # implements the article's own wording over a commercial involvement screen.
        pick = max(mine, key=lambda x: (x["reference"] != "vendor", x["n"]))
        print(f"  {rule['article']}  reference={pick['reference']:<11} n={pick['n']:>3}  "
              f"kappa={fmt(pick['cohen_kappa'])}  precision={fmt(pick['precision'])}  "
              f"recall={fmt(pick['recall'])}")
    return pd.DataFrame(stats)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_provenance(nbim_meta):
    records = []
    for q, path in dera_paths():
        records.append(dict(
            source="sec_dera_financial_statement_data_sets",
            provenance_class="mandatory",
            url=DERA_URL.format(q=q),
            retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            http_status=200, bytes=path.stat().st_size, sha256=sha256_file(path),
            licence="US government work, public domain.",
            redistribution="Public domain. Derived numbers may be published without restriction.",
            note="Structured XBRL from every filing in the quarter. The only public SEC product "
                 "that keeps dimensional facts; the companyfacts API drops every axis.",
        ))
    records.append(dict(
        source="nbim_exclusion_list",
        provenance_class="voluntary",
        url=nbim_meta["url"], retrieved_at=nbim_meta["retrieved_at"],
        http_status=nbim_meta["http_status"], bytes=nbim_meta["bytes"],
        sha256=nbim_meta["sha256"],
        licence="Published by Norges Bank Investment Management on its public website.",
        redistribution="Company-level exclusion decisions are public disclosures by the fund. "
                       "We publish derived flags with attribution and do not rehost the page.",
        note="An asset owner's own decisions, not a commercial ESG rating. Kept in nbim_ columns.",
    ))
    if KAGGLE_CSV.exists():
        records.append(dict(
            source="kaggle_mrbossjaysrb_global_corporate_esg",
            provenance_class="vendor",
            url=f"https://www.kaggle.com/datasets/{KAGGLE_DATASET}",
            retrieved_at=datetime.fromtimestamp(KAGGLE_CSV.stat().st_mtime,
                                                timezone.utc).isoformat(),
            http_status=200, bytes=KAGGLE_CSV.stat().st_size, sha256=sha256_file(KAGGLE_CSV),
            licence="Uploader declares CC0-1.0 on Kaggle. The underlying product-involvement "
                    "screens originate with commercial ESG providers.",
            redistribution="Not republished. Used only to benchmark flags we derive ourselves, "
                           "and confined to columns prefixed vendor_ with "
                           "provenance_class = 'vendor'.",
            note="14 involvement.* screens and 4 involvement_msci.* screens. Coverage of the "
                 "S&P 500 is measured at run time and printed, not assumed.",
        ))
    records.append(dict(
        source="eu_2020_1818_article_12",
        provenance_class="mandatory",
        url="data/interim/pab_rules.json",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        http_status=None, bytes=(INTERIM / "pab_rules.json").stat().st_size,
        sha256=sha256_file(INTERIM / "pab_rules.json"),
        licence="EUR-Lex reuse policy. (c) European Union, 1998-2026.",
        redistribution="Reuse authorised with acknowledgement of the source.",
        note="Sub-rule ids and revenue thresholds are read from this file at run time.",
    ))
    PROV.mkdir(parents=True, exist_ok=True)
    (PROV / "revenue_exclusions.json").write_text(json.dumps(records, indent=1, sort_keys=True))
    print(f"\nwrote {PROV / 'revenue_exclusions.json'}  ({len(records)} source records)")


def main():
    INTERIM.mkdir(parents=True, exist_ok=True)
    universe = pd.read_parquet(INTERIM / "universe.parquet")
    aliases = json.loads((INTERIM / "ticker_aliases.json").read_text())
    print(f"universe: {len(universe)} listings, {int(universe.is_primary_listing.sum())} companies")

    print("\nArticle 12 sub-rules read from pab_rules.json")
    rules = load_article12_rules()

    print("\nSEC XBRL segment revenue")
    # companyfacts first, because that is where the brief pointed. It is a dead end and the
    # measurement below is the evidence, not an assertion.
    dimensional = 0
    checked = 0
    for cik in universe.cik.head(25):
        path = RAW / "sec" / "companyfacts" / f"CIK{cik}.json"
        if not path.exists():
            continue
        checked += 1
        doc = json.loads(path.read_text())
        for taxonomy in doc.get("facts", {}).values():
            for tag in taxonomy.values():
                for series in tag.get("units", {}).values():
                    dimensional += sum(1 for fact in series if "segments" in fact or "dim" in fact)
    print(f"  companyfacts: {checked} documents sampled, {dimensional} facts carrying any "
          f"dimension. The API publishes consolidated series only, so segment revenue cannot "
          f"come from it. Falling through to the DERA Financial Statement Data Sets.")

    cik_to_ticker = {int(c): t for c, t in zip(universe.cik, universe.ticker)}
    for parent, children in aliases["cik_cofilers"]["map"].items():
        if int(parent) in cik_to_ticker:
            for child in children:
                cik_to_ticker.setdefault(int(child), cik_to_ticker[int(parent)])
    facts = read_dera_segments(cik_to_ticker)

    financials = pd.read_parquet(INTERIM / "financials.parquet")
    latest = (financials.sort_values("fy").groupby("ticker").revenue.last().to_dict())
    shares = segment_shares(facts, latest)
    classified = sum(1 for s in shares.values() if s["lower"] or s["upper"])
    print(f"  segment revenue parsed for {len(shares)} tickers, of which {classified} have at "
          f"least one member classified to an Article 12 commodity")

    print("\nVendor product-involvement screens")
    vendor = load_vendor_screens(aliases)

    print("\nNBIM exclusion list")
    nbim, nbim_meta = load_nbim(aliases)

    df = build_table(universe, rules, shares, vendor, nbim)
    for col in ("flag_gics", "flag_sec", "flag_vendor", "flag_nbim", "sec_broad_reading",
                "sec_gross_of_eliminations"):
        df[col] = df[col].astype("boolean")     # nullable, so null stays null and never becomes False
    print(f"\nbuilt {len(df):,} rows = {df.ticker.nunique()} listings x {df.rule_id.nunique()} rules")

    stats = report(df, rules)

    out = INTERIM / "revenue_exclusions.parquet"
    df.to_parquet(out, index=False)
    print(f"\nwrote {out}  {len(df):,} rows, {df.shape[1]} columns")
    cov = df[df.is_primary_listing].groupby("rule_id")[["flag_gics", "flag_sec", "flag_vendor",
                                                        "flag_nbim"]].apply(
        lambda g: g.notna().sum())
    print("\nmeasured coverage, primary listings, out of 500 companies (503 listings)")
    print(cov.to_string())
    if len(stats):
        print("\nagreement summary")
        print(stats.to_string(index=False))
    write_provenance(nbim_meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
