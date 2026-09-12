"""master_company: one row per S&P 500 listing, every contested fact with the source that won.

Builds docs/master_table_spec.md. Four artefacts:

  data/master/master_company.parquet / .csv   503 listings x the full column set
  data/master/master_company.xlsx             the same, readable, with the registry on sheet 2
  data/master/master_panel.parquet            long: ticker x year x metric, 2010-2026
  data/master/column_registry.csv             one row per column of master_company

It also persists data/interim/ghgrp_ticker_year.parquet, the fossil-only equity-apportioned
GHGRP roll-up that compare_reported_measured.py computes and then throws away.

Three rules the whole thing rests on:
  every one of the 503 listings appears, nothing is dropped for being unmeasurable;
  a missing value is null and counted, never zero and never imputed;
  a mandatory and a voluntary number never merge without a _basis column naming the winner.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "data" / "master"
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "src"))

GENERATED_AT = datetime.now(timezone.utc).replace(microsecond=0)

# ----------------------------------------------------------------- modelled assumptions
# None of the three blocks below is data. Each is an assumption with a default, settable in
# the UI, and each is labelled modelled with dq 5 wherever it appears.

# NGFS publishes in US$2010 per tCO2. BEA's GDP implicit price deflator for 2010 against 2026
# is 1.44. This is a hard constant, not a fetched series, which is why the raw US$2010 figure
# is carried beside the deflated one in price_usd2010_per_t.
USD2010_TO_USD2026 = 1.44

# The share of the carbon cost a company pushes to its customers. There is no empirical source
# for this anywhere in the repo. Regulated utilities recover fuel and compliance costs through
# tariffs, staples and health care face inelastic demand, trade-exposed commodity producers
# compete against unpriced imports and can pass on least.
PASSTHROUGH_DEFAULT = {
    "Utilities": 0.80,
    "Consumer Staples": 0.70,
    "Health Care": 0.70,
    "Energy": 0.60,
    "Information Technology": 0.60,
    "Communication Services": 0.60,
    "Real Estate": 0.60,
    "Industrials": 0.50,
    "Financials": 0.50,
    "Consumer Discretionary": 0.40,
    "Materials": 0.35,
}
PASSTHROUGH_FALLBACK = 0.50

# Default penalty coverage. Scope 3 is off by default because double counting it across a
# 500-company index would price the same tonne several times.
COVERAGE_S1, COVERAGE_S2, COVERAGE_S3 = 100.0, 100.0, 0.0
HORIZON_YEAR = 2030

# The one NGFS price the stored defaults use. Named, not averaged: GCAM's 2030 US net-zero
# price is 98.6 and REMIND's is 283.7 for the same scenario, so a mean of the two is a number
# no model produced.
NGFS_SCENARIO = "Net Zero 2050"
NGFS_MODEL = "Downscaling[GCAM 6.0 NGFS]"
NGFS_REGION = "USA"
NGFS_YEAR = 2030

# A GHGRP figure older than this is carried in its own column but is not allowed to become the
# headline. IBM's last GHGRP year is 2014 and Vulcan's is 2013.
MEASURED_MIN_YEAR = 2019

# EV/EBITDA guards. dEV = dEBIT x multiple, so a negative or 1942x multiple destroys the answer.
EV_EBITDA_FLOOR, EV_EBITDA_CAP = 4.0, 40.0

REGISTRY = []


def col(D, name, values, unit, definition, source, provenance_class, dq_typical):
    """Attach a column and its registry row in one place so the two cannot drift apart.

    Columns land in a plain dict and the frame is assembled once at the end. Inserting 135
    columns into a live DataFrame fragments it, and a per-row .at lookup on a half-built
    string column is exactly where pandas 3 hands back a truthy pd.NA.
    """
    D[name] = list(values) if not isinstance(values, np.ndarray) else values
    REGISTRY.append({
        "name": name, "unit": unit, "definition": definition, "source": source,
        "provenance_class": provenance_class, "dq_typical": dq_typical,
        "script": "src/build_master.py",
    })


def latest_by(df, key, value_col, year_col):
    """Latest year carrying a non-null value, per key. Returns value and year as two dicts."""
    s = df[df[value_col].notna()].sort_values([key, year_col])
    last = s.groupby(key).tail(1)
    return (dict(zip(last[key], last[value_col])), dict(zip(last[key], last[year_col])))


def mapcol(index, mapping):
    """A plain-dict lookup down the spine. Never build a str-or-None list in pandas 3: the
    resulting string column makes a miss pd.NA, and pd.NA is truthy."""
    return [mapping.get(t) for t in index]


# ============================================================== 1. GHGRP fossil-only rebuild
def build_ghgrp_ticker_year():
    """Fossil-only, equity-apportioned Scope 1 per ticker-year, persisted.

    EPA's published CO2e includes gas_id 8, biogenic CO2 from biomass combustion, which the
    GHG Protocol keeps out of Scope 1. compare_reported_measured.py already splits the gases
    and reconciles the all-gas column to emissions_by_ticker to the tonne; it just never
    writes the result down.
    """
    path = INTERIM / "ghgrp_ticker_year.parquet"
    if path.exists():
        g = pd.read_parquet(path)
        print(f"ghgrp_ticker_year.parquet  reused   {len(g):,} rows, {g.ticker.nunique()} tickers")
        return g
    from compare_reported_measured import build_measured, load_facility_gas
    gas = load_facility_gas()
    g, _ = build_measured(gas)
    g.to_parquet(path, index=False)
    print(f"ghgrp_ticker_year.parquet  written  {len(g):,} rows, {g.ticker.nunique()} tickers")
    return g


# ============================================================== 2. sources
def load_sources():
    s = {}
    s["universe"] = pd.read_parquet(INTERIM / "universe.parquet")
    s["ghgrp"] = build_ghgrp_ticker_year()
    s["emissions"] = pd.read_parquet(INTERIM / "emissions_by_ticker.parquet")
    s["wba_em"] = pd.read_parquet(INTERIM / "wba_emissions.parquet")
    s["wba_co"] = pd.read_parquet(INTERIM / "wba_company.parquet")
    s["scope23"] = pd.read_parquet(INTERIM / "scope23.parquet")
    s["ct"] = pd.read_parquet(INTERIM / "climatetrace_company.parquet")
    s["saydo"] = pd.read_parquet(INTERIM / "say_do_gap.parquet")
    s["targets"] = pd.read_parquet(INTERIM / "targets_company.parquet")
    s["fin"] = pd.read_parquet(INTERIM / "financials.parquet")
    s["mcap"] = pd.read_parquet(INTERIM / "market_cap.parquet")
    s["viol"] = pd.read_parquet(INTERIM / "violations_summary.parquet")
    s["rex"] = pd.read_parquet(INTERIM / "revenue_exclusions.parquet")
    s["portfolio"] = pd.read_parquet(INTERIM / "portfolio.parquet")
    s["scores"] = pd.read_parquet(INTERIM / "scores.parquet")
    s["vendor"] = pd.read_parquet(INTERIM / "esg_vendor_consensus.parquet")
    s["ngfs"] = pd.read_parquet(INTERIM / "ngfs_scenarios.parquet")
    s["md"] = pd.read_csv(RAW / "master_dataset.csv")
    s["xwalk"] = pd.read_csv(RAW / "wba_join" / "WBA join SP500" / "sp500_wba_crosswalk.csv",
                             dtype=str)
    return s


# ============================================================== 3. WBA crosswalk reconciliation
def wba_crosswalk_gains(src):
    """Their CIK -> Wikidata -> WBA crosswalk against ours, and the one row it gets wrong.

    Theirs matches 250 tickers and ours 247, ours is a strict subset, and the wba_company_id
    agrees on all 247. Three are new. One of the three is a different company: their EQT is
    EQT AB Group, the Swedish asset manager (QID Q1275733, ISIN SE0012853455), matched by
    exact_normalized_name against EQT Corporation, the US gas producer (QID Q5323987). Its
    self-reported Scope 1 is 33 tonnes against 1.82 MMT that EPA measured on EQT Corporation's
    own wells in 2023.

    The rule: accept a crosswalk row that is new to us only when the two Wikidata QIDs agree,
    or when one side has no QID. Six of the 250 disagree on QID; five of those six (AMCR,
    AVGO, DOW, HWM, WM) are the same company under a second QID and are independently
    confirmed by our own ISIN or LEI match, so only EQT is rejected.
    """
    xw = src["xwalk"][src["xwalk"].wba_matched == "True"].copy()
    ours = set(src["wba_co"].ticker)
    new = xw[~xw.ticker.isin(ours)]
    qid_bad = (xw.sp_wikidata_qid.notna() & xw.wba_wikidata_qid.notna()
               & (xw.sp_wikidata_qid != xw.wba_wikidata_qid))
    rejected = sorted(set(new.ticker) & set(xw[qid_bad].ticker))
    accepted = sorted(set(new.ticker) - set(rejected))
    print(f"\nWBA crosswalk: theirs {len(xw)}, ours {len(ours)}, ours a strict subset "
          f"{set(ours) <= set(xw.ticker)}")
    print(f"  QID disagreements across all 250: {int(qid_bad.sum())} "
          f"({', '.join(sorted(xw[qid_bad].ticker))})")
    print(f"  new to us, accepted: {accepted}")
    print(f"  new to us, REJECTED on QID mismatch: {rejected} "
          f"(their EQT is EQT AB Group, the Swedish asset manager)")
    ids = dict(zip(xw[xw.ticker.isin(accepted)].ticker,
                   xw[xw.ticker.isin(accepted)].wba_company_id))
    return ids, rejected


def wba_backfill_rows(company_ids):
    """Scope 1/2/3 for the tickers their crosswalk adds, read from the raw WBA climate profile
    the same way fetch_wba.py reads it, so the numbers arrive on the same footing."""
    if not company_ids:
        return pd.DataFrame(columns=["ticker", "fy", "scope", "tonnes_co2e", "dq",
                                     "provenance_class", "preferred"])
    cp = pd.read_csv(RAW / "wba" / "WBA Data" / "climateprofiles.csv", dtype=str)
    cp = cp[cp.company_id.isin(company_ids.values())]
    id_to_ticker = {v: k for k, v in company_ids.items()}
    rows = []
    for _, r in cp.iterrows():
        fy = str(r["climate_profile_year"]).strip("{}")
        if not fy.isdigit():
            continue
        for scope, c in [("1", "climate_profile_scope_1"), ("2", "climate_profile_scope_2"),
                         ("3", "climate_profile_scope_3"), ("1+2", "climate_profile_scope_1x2")]:
            v = str(r[c]).strip("{}")
            if v in ("", "nan", "None"):
                continue
            rows.append({"ticker": id_to_ticker[r["company_id"]], "fy": int(fy), "scope": scope,
                         "tonnes_co2e": float(v), "dq": 3, "provenance_class": "voluntary",
                         "preferred": True, "source_table": "climate_profile"})
    out = pd.DataFrame(rows)
    print(f"  WBA backfill rows from the accepted crosswalk additions: {len(out)} "
          f"({out.ticker.nunique() if len(out) else 0} tickers)")
    return out


# ---------------------------------------------------------------- PDF report magnitude screen
REPORT_SPAN_MAX = 10.0


def screen_report_pdf(s23):
    """scope23.parquet is a PDF extraction and it is not reliable at magnitude.

    Two screens, both measured rather than hand-picked:

    (a) the upstream magnitude_suspect flag, which tests a self-report against the company's own
        GHGRP tonnage and fires on 17 rows. It only catches a report far BELOW a measured figure,
        so it cannot see a company with no EPA facilities.

    (b) a within-company consistency test on Scope 1 and Scope 2 only. PTC's extracted Scope 1
        goes 1,073 t in FY2018 to 1,054,119 t in FY2019, and its Scope 2 goes 14,200 to
        11,270,214, a factor of about a thousand in one year at a software company. Steel
        Dynamics goes 1.9 MMT, 1,081 t, 1.7 MMT in three consecutive years. Where a ticker-scope
        has three or more years, a year more than 10x from the median of that series is dropped;
        where it has exactly two and they differ by more than 10x, both go, because there is no
        way to tell which one is the typo. Scope 3 is exempt: a company that starts counting
        category 1 purchased goods really does jump three orders of magnitude.

    Dropped rows stay in master_panel with the flag, so nothing is deleted, only demoted.
    """
    s = s23[s23.tonnes_co2e.notna()].copy()
    s["screen"] = None
    s.loc[s.magnitude_suspect.fillna(False), "screen"] = "magnitude_suspect_vs_ghgrp"
    tested = s.scope.isin(["1", "2_market", "2_location"]) & s.screen.isna()
    t = s[tested]
    med = t.groupby(["ticker", "scope"]).tonnes_co2e.transform("median")
    n = t.groupby(["ticker", "scope"]).tonnes_co2e.transform("size")
    span = (t.groupby(["ticker", "scope"]).tonnes_co2e.transform("max")
            / t.groupby(["ticker", "scope"]).tonnes_co2e.transform("min").replace(0, np.nan))
    ratio = np.maximum(t.tonnes_co2e / med.replace(0, np.nan),
                       med.replace(0, np.nan) / t.tonnes_co2e.replace(0, np.nan))
    off = ((n >= 3) & (ratio > REPORT_SPAN_MAX)) | ((n == 2) & (span > REPORT_SPAN_MAX))
    s.loc[t.index[off.fillna(False)], "screen"] = "within_company_magnitude"
    dropped = s[s.screen.notna()]
    print(f"\nPDF report screen: {len(dropped)} of {len(s)} tonnage rows dropped from the "
          f"headline over {dropped.ticker.nunique()} tickers")
    for name, grp in dropped.groupby("screen"):
        print(f"  {name}: {len(grp)} rows, "
              + ", ".join(f"{r.ticker} FY{int(r.fy)} {r.scope} {r.tonnes_co2e:,.0f}"
                          for r in grp.sort_values(["ticker", "fy"]).itertuples())[:600])
    return s[s.screen.isna()].copy()


# ============================================================== 4. the table
def build(src):
    u = src["universe"].copy()
    D = {}
    idx = pd.Index(u.ticker.tolist(), name="ticker")
    pos = {t: i for i, t in enumerate(idx)}

    # ---------------------------------------------------------- 4.1 identity
    uu = u.set_index("ticker")
    pf = src["portfolio"].set_index("ticker")
    col(D, "ticker", idx.to_list(), "", "S&P 500 listing, uppercase, dots not dashes",
        "universe.parquet", "mandatory", 1)
    col(D, "company_name", mapcol(idx, uu.company_name.to_dict()), "",
        "Index constituent name", "universe.parquet", "mandatory", 1)
    col(D, "cik", mapcol(idx, uu.cik.to_dict()), "",
        "SEC central index key, zero padded", "universe.parquet", "mandatory", 1)
    col(D, "gics_sector", mapcol(idx, uu.gics_sector.to_dict()), "",
        "GICS sector, 11 values", "universe.parquet", "mandatory", 1)
    col(D, "gics_sub_industry", mapcol(idx, uu.gics_sub_industry.to_dict()), "",
        "GICS sub-industry", "universe.parquet", "mandatory", 1)
    # portfolio.parquet has 499 rows, not 503: it drops the three secondary listings and ARES.
    # A secondary listing takes its sibling's section, and ARES takes the modal section of its
    # GICS sector, so a null here never reads as "not a high-impact sector".
    nace = pf.nace_section.to_dict()
    sib = dict(zip(u.ticker, u.share_class_siblings))
    sector_mode = (src["portfolio"].groupby("gics_sector").nace_section
                   .agg(lambda s: s.mode().iloc[0] if len(s.mode()) else None).to_dict())
    sec_of = dict(zip(u.ticker, u.gics_sector))
    for t in idx:
        if pd.isna(nace.get(t, None)):
            s_ = sib.get(t)
            if isinstance(s_, str) and s_ in nace and pd.notna(nace[s_]):
                nace[t] = nace[s_]
            else:
                nace[t] = sector_mode.get(sec_of.get(t))
    col(D, "nace_section", mapcol(idx, nace), "",
        "NACE section, the PAB high-impact-sector test. Taken from the sibling listing, or "
        "from the sector mode, on the four listings portfolio.parquet does not carry",
        "portfolio.parquet", "modelled", 3)
    col(D, "is_primary_listing", [bool(v) for v in mapcol(idx, uu.is_primary_listing.to_dict())],
        "bool", "False on GOOG, FOX and NWS; filter this before summing anything",
        "universe.parquet", "mandatory", 1)
    col(D, "share_class_siblings", mapcol(idx, uu.share_class_siblings.to_dict()), "",
        "The other listing of the same registrant, where one exists",
        "universe.parquet", "mandatory", 1)
    hq = {t: (v.split(",")[-1].strip() if isinstance(v, str) and v else None)
          for t, v in uu.hq_location.to_dict().items()}
    col(D, "hq_country_iso", mapcol(idx, hq), "",
        "Headquarters country or US state as the index publishes it",
        "universe.parquet", "mandatory", 2)
    col(D, "date_added", mapcol(idx, uu.date_added.to_dict()), "date",
        "Date the listing entered the index", "universe.parquet", "mandatory", 1)

    # ---------------------------------------------------------- 4.2 emissions, measured
    g = src["ghgrp"].copy()
    g["net"] = g.meas_fossil_equity - g.meas_fossil_lookahead
    # 2023 is the last GHGRP reporting year. Four tickers stopped filing earlier; they keep
    # their own last year and scope1_measured_us_year makes that visible.
    g = g.sort_values(["ticker", "year"])
    last = g.groupby("ticker").tail(1).set_index("ticker")
    ar6_ratio = (last.meas_fossil_ar6 / last.meas_fossil_equity.replace(0, np.nan))

    col(D, "scope1_measured_us_t", mapcol(idx, last.net.to_dict()), "tCO2e",
        "EPA GHGRP Scope 1, fossil only, equity apportioned, net of perimeter changes",
        "ghgrp_ticker_year.parquet", "mandatory", 1)
    col(D, "scope1_measured_us_year", mapcol(idx, last.year.to_dict()), "year",
        "Reporting year of scope1_measured_us_t", "ghgrp_ticker_year.parquet", "mandatory", 1)
    col(D, "scope1_measured_allgas_t", mapcol(idx, last.meas_all_equity.to_dict()), "tCO2e",
        "The same roll-up including biogenic CO2, for reconciliation only, never a headline",
        "ghgrp_ticker_year.parquet", "mandatory", 1)
    col(D, "scope1_biogenic_t", mapcol(idx, last.meas_biogenic_equity.to_dict()), "tCO2e",
        "Biogenic CO2, gas_id 8, reported separately as the GHG Protocol requires",
        "ghgrp_ticker_year.parquet", "mandatory", 1)
    col(D, "scope1_ar6_t", mapcol(idx, (last.net * ar6_ratio).to_dict()), "tCO2e",
        "scope1_measured_us_t with CH4 and N2O restated from AR4 to AR6 GWPs, a band not a fix",
        "ghgrp_ticker_year.parquet", "modelled", 2)
    col(D, "scope1_lookahead_excluded_t", mapcol(idx, last.meas_fossil_lookahead.to_dict()),
        "tCO2e", "Tonnes removed because the facility was not inside the perimeter that year",
        "ghgrp_ticker_year.parquet + PERIMETER_CHANGES", "modelled", 2)
    col(D, "scope1_facility_count", mapcol(idx, last.facility_count.to_dict()), "count",
        "Distinct GHGRP facilities behind scope1_measured_us_t",
        "ghgrp_ticker_year.parquet", "mandatory", 1)
    zero = {t: True for t in g.groupby("ticker").net.max().pipe(lambda s: s[s <= 0]).index}
    col(D, "ghgrp_matched_zero_fossil",
        [bool(zero.get(t, False)) for t in idx], "bool",
        "Matched to GHGRP facilities and measured zero fossil tonnes in every year: checked "
        "and found zero, not missing", "ghgrp_ticker_year.parquet", "mandatory", 1)

    em = src["emissions"]
    camd = em[em.scope1_camd_tonnes.notna() & (em.scope1_camd_tonnes > 0)]
    camd_v, camd_y = latest_by(camd, "ticker", "scope1_camd_tonnes", "year")
    col(D, "scope1_current_signal_t", mapcol(idx, camd_v), "tCO2e",
        "Latest CAMD stack-measured CO2. A currency check only: its boundary is Acid Rain and "
        "CSAPR combustion units, not the company, so it never sets a level",
        "emissions_by_ticker.parquet", "mandatory", 1)
    col(D, "scope1_current_signal_year", mapcol(idx, camd_y), "year",
        "Year of scope1_current_signal_t", "emissions_by_ticker.parquet", "mandatory", 1)

    # ---------------------------------------------------------- 4.3 emissions, self-reported
    wba = src["wba_em"]
    wba = wba[wba.preferred].copy()
    wba = pd.concat([wba, src["wba_backfill"]], ignore_index=True)
    s23 = src["scope23_screened"]

    def self_reported(scope_wba, scope_rep):
        """WBA first, PDF report second, latest fiscal year wins. The two never cover the same
        year for Scope 1 alone: WBA's scope 1 series is FY2023-24 and scope23 ends FY2022."""
        a = wba[wba.scope == scope_wba][["ticker", "fy", "tonnes_co2e", "dq"]].copy()
        a["src"] = "wba"
        b = s23[s23.scope.isin(scope_rep)][["ticker", "fy", "tonnes_co2e", "dq"]].copy()
        b["src"] = "report_pdf"
        both = pd.concat([a, b], ignore_index=True)
        both["_pref"] = (both.src == "report_pdf").astype(int)  # WBA wins a tie on fy
        both = both.sort_values(["ticker", "fy", "_pref"])
        last = both.groupby("ticker").tail(1).set_index("ticker")
        return (last.tonnes_co2e.to_dict(), last.fy.to_dict(), last.src.to_dict(),
                last.dq.to_dict())

    s1v, s1y, s1s, s1dq = self_reported("1", ["1"])
    s2v, s2y, s2s, s2dq = self_reported("2", ["2_market"])
    s3v, s3y, s3s, s3dq = self_reported("3", ["3_total"])
    s2loc = s23[s23.scope == "2_location"]
    s2loc_v, s2loc_y = latest_by(s2loc, "ticker", "tonnes_co2e", "fy")
    s12 = wba[wba.scope == "1+2"]
    s12_v, s12_y = latest_by(s12, "ticker", "tonnes_co2e", "fy")

    col(D, "scope1_selfreported_t", mapcol(idx, s1v), "tCO2e",
        "Company-declared global Scope 1, WBA climate profile first, PDF report second",
        "wba_emissions.parquet, scope23.parquet", "voluntary", 2)
    col(D, "scope1_selfreported_year", mapcol(idx, s1y), "year",
        "Fiscal year of scope1_selfreported_t", "wba_emissions.parquet, scope23.parquet",
        "voluntary", 2)
    col(D, "scope1_selfreported_source", mapcol(idx, s1s), "",
        "wba or report_pdf", "wba_emissions.parquet, scope23.parquet", "voluntary", 2)

    ct = src["ct"]
    ct_eq = (ct.groupby(["ticker", "year"]).equity_share_tonnes_co2e.sum().reset_index())
    ct_v, ct_y = latest_by(ct_eq, "ticker", "equity_share_tonnes_co2e", "year")
    col(D, "scope1_modelled_t", mapcol(idx, ct_v), "tCO2e",
        "Climate TRACE equity share, an asset inventory with no corporate boundary. Equity, "
        "not gross: gross double counts joint ventures",
        "climatetrace_company.parquet", "modelled", 4)
    col(D, "scope1_modelled_year", mapcol(idx, ct_y), "year",
        "Release year of scope1_modelled_t", "climatetrace_company.parquet", "modelled", 4)

    # ---------------------------------------------------------- 4.4 the decided Scope 1
    # Precedence, first hit wins:
    #   1 self-report where it exists and clears the measured floor. A global perimeter is the
    #     right one for a global penalty and it is newer, FY2024 against 2023.
    #   2 GHGRP fossil equity where there is no self-report, or where the self-report sits
    #     below what EPA measured on the company's own US sites, which is not possible on
    #     boundary alone.
    #   3 Climate TRACE where neither exists.
    #   4 null, counted, never zero.
    v, yr, basis, dq, floor_flag = [], [], [], [], []
    for t in idx:
        meas = D["scope1_measured_us_t"][pos[t]]
        meas_y = D["scope1_measured_us_year"][pos[t]]
        meas_ok = (pd.notna(meas) and meas > 0 and pd.notna(meas_y)
                   and meas_y >= MEASURED_MIN_YEAR)
        self_v, self_y = s1v.get(t), s1y.get(t)
        self_ok = self_v is not None and pd.notna(self_v)
        below = bool(self_ok and meas_ok and self_v < meas)
        floor_flag.append(below)
        if self_ok and not below:
            v.append(float(self_v)); yr.append(int(self_y))
            basis.append("self_reported")
            d = s1dq.get(t)
            dq.append(int(d) if pd.notna(d) else 3)
        elif meas_ok:
            v.append(float(meas)); yr.append(int(meas_y))
            basis.append("ghgrp_fossil_floor" if below else "ghgrp_fossil")
            dq.append(1)
        elif t in ct_v:
            v.append(float(ct_v[t])); yr.append(int(ct_y[t]))
            basis.append("climatetrace_equity"); dq.append(4)
        else:
            v.append(np.nan); yr.append(None); basis.append(None); dq.append(None)
    col(D, "scope1_t", v, "tCO2e",
        "The decided Scope 1: self-report where it clears the EPA-measured floor, else GHGRP "
        "fossil equity, else Climate TRACE, else null", "precedence over the three above",
        "mixed", 2)
    col(D, "scope1_year", yr, "year", "Fiscal or reporting year of scope1_t",
        "precedence over the three above", "mixed", 2)
    col(D, "scope1_basis", basis, "",
        "self_reported | ghgrp_fossil | ghgrp_fossil_floor | climatetrace_equity",
        "precedence over the three above", "mixed", 2)
    col(D, "scope1_dq", dq, "1-5",
        "PCAF data quality of scope1_t: 1 verified mandatory, 2 reported, 4 modelled",
        "precedence over the three above", "mixed", 2)
    col(D, "scope1_below_measured_floor", floor_flag, "bool",
        "The company reported a global Scope 1 below what EPA measured on its US sites alone, "
        "so the mandatory figure won", "precedence over the three above", "mixed", 1)

    col(D, "scope2_market_t", mapcol(idx, s2v), "tCO2e",
        "Scope 2. WBA does not label market against location basis, so scope2_basis says which "
        "table spoke rather than which accounting basis",
        "wba_emissions.parquet, scope23.parquet", "voluntary", 2)
    col(D, "scope2_basis", mapcol(idx, s2s), "", "wba (basis unlabelled) or report_pdf (market)",
        "wba_emissions.parquet, scope23.parquet", "voluntary", 2)
    col(D, "scope2_dq", mapcol(idx, s2dq), "1-5", "PCAF data quality of scope2_market_t",
        "wba_emissions.parquet, scope23.parquet", "voluntary", 2)
    col(D, "scope2_location_t", mapcol(idx, s2loc_v), "tCO2e",
        "Location-based Scope 2 where a report stated it separately",
        "scope23.parquet", "voluntary", 3)
    col(D, "scope2_year", mapcol(idx, s2y), "year", "Fiscal year of scope2_market_t",
        "wba_emissions.parquet, scope23.parquet", "voluntary", 2)
    col(D, "scope3_total_t", mapcol(idx, s3v), "tCO2e",
        "Total Scope 3 as declared. Not summable across the index: one company's Scope 3 is "
        "another's Scope 1", "wba_emissions.parquet, scope23.parquet", "voluntary", 3)
    col(D, "scope3_basis", mapcol(idx, s3s), "", "wba or report_pdf",
        "wba_emissions.parquet, scope23.parquet", "voluntary", 3)
    col(D, "scope3_dq", mapcol(idx, s3dq), "1-5", "PCAF data quality of scope3_total_t",
        "wba_emissions.parquet, scope23.parquet", "voluntary", 3)
    col(D, "scope3_year", mapcol(idx, s3y), "year", "Fiscal year of scope3_total_t",
        "wba_emissions.parquet, scope23.parquet", "voluntary", 3)
    col(D, "scope12_t", mapcol(idx, s12_v), "tCO2e",
        "WBA combined Scope 1+2, the only voluntary series with a multi-year history. For a "
        "trend only, never into a Scope-1-only column", "wba_emissions.parquet", "voluntary", 2)
    col(D, "scope12_year", mapcol(idx, s12_y), "year", "Fiscal year of scope12_t",
        "wba_emissions.parquet", "voluntary", 2)

    # ---------------------------------------------------------- 4.5 power
    gridrows = src["scope23"]
    gridrows = gridrows[gridrows.scope2_factor_g_per_kwh_hq_region.notna()]
    gf, _ = latest_by(gridrows, "ticker", "scope2_factor_g_per_kwh_hq_region", "fy")
    col(D, "grid_factor_hq_g_per_kwh", mapcol(idx, gf), "gCO2e/kWh",
        "eGRID subregion emission factor for the HQ region", "scope23.parquet", "mandatory", 3)
    col(D, "power_intensity_g_per_kwh", mapcol(idx, pf.power_intensity_g_per_kwh.to_dict()),
        "gCO2e/kWh", "Generation-weighted intensity of the company's own plants, the Article "
        "12(1)(g) test", "plant_intensity.parquet via portfolio.parquet", "modelled", 2)
    col(D, "power_gen_mwh", mapcol(idx, pf.power_gen_mwh.to_dict()), "MWh",
        "Net generation behind power_intensity_g_per_kwh",
        "eia_plant_totals.parquet via portfolio.parquet", "mandatory", 1)

    # ---------------------------------------------------------- 4.6 trajectory
    sd = src["saydo"].set_index("ticker")
    col(D, "delivered_pct_yr", mapcol(idx, sd.delivered_pct_yr.to_dict()), "%/yr",
        "OBSERVED annual change in measured tonnage, OLS on the longest clean window. "
        "Negative is falling. This is the model's abatement input, never the promised rate",
        "say_do_gap.parquet", "modelled", 2)
    col(D, "delivered_basis", mapcol(idx, sd.emissions_source.to_dict()), "",
        "Which measured series the fit ran on; ghgrp on all 134",
        "say_do_gap.parquet", "modelled", 2)
    col(D, "delivered_dq", [2 if pd.notna(x) else None
                            for x in mapcol(idx, sd.delivered_pct_yr.to_dict())], "1-5",
        "PCAF data quality of delivered_pct_yr: 2, an OLS on mandatory tonnage",
        "say_do_gap.parquet", "modelled", 2)
    col(D, "delivered_se_pct_yr", mapcol(idx, sd.delivered_se_boot.to_dict()), "%/yr",
        "Bootstrap standard error of delivered_pct_yr", "say_do_gap.parquet", "modelled", 2)
    col(D, "delivered_r2", mapcol(idx, sd.delivered_r2.to_dict()), "",
        "R squared of the log-linear fit", "say_do_gap.parquet", "modelled", 2)
    col(D, "delivered_n_years", mapcol(idx, sd.delivered_n_years.to_dict()), "count",
        "Years in the fitted window", "say_do_gap.parquet", "modelled", 2)
    col(D, "delivered_year_start", mapcol(idx, sd.delivered_year_start.to_dict()), "year",
        "First year of the fitted window", "say_do_gap.parquet", "modelled", 2)
    col(D, "delivered_year_end", mapcol(idx, sd.delivered_year_end.to_dict()), "year",
        "Last year of the fitted window", "say_do_gap.parquet", "modelled", 2)
    col(D, "delivered_camd_pct_yr", mapcol(idx, sd.delivered_camd_pct_yr.to_dict()), "%/yr",
        "The same fit on CAMD stack data, which runs to 2025 where GHGRP stops at 2023",
        "say_do_gap.parquet", "modelled", 2)

    # promised: ours, 341, backfilled from WBA on the 17 it covers and we do not
    tg = src["targets"].set_index("ticker")
    ours_p = sd.promised_pct_yr.to_dict()
    wba_p = sd.wba_promised_pct_yr.to_dict()
    ours_b = sd.promised_source.to_dict()
    pv, pb, pdq = [], [], []
    for t in idx:
        a, b = ours_p.get(t), wba_p.get(t)
        if pd.notna(a):
            pv.append(float(a))
            src_name = ours_b.get(t)
            pb.append(src_name if (pd.notna(src_name) and src_name != "none") else "unknown")
            pdq.append(2)
        elif pd.notna(b):
            pv.append(float(b)); pb.append("wba"); pdq.append(3)
        else:
            pv.append(np.nan); pb.append(None); pdq.append(None)
    col(D, "promised_pct_yr", pv, "%/yr",
        "Implied annual reduction from the company's own target, negative is falling. Ours "
        "first, WBA for the 17 it covers and we do not",
        "say_do_gap.parquet, wba_targets.parquet", "voluntary", 2)
    col(D, "promised_basis", pb, "",
        "sbti_s12_absolute | nzt_interim | netzero_inferred | sbti_combined | wba",
        "say_do_gap.parquet, wba_targets.parquet", "voluntary", 2)
    col(D, "promised_dq", pdq, "1-5", "PCAF data quality of promised_pct_yr",
        "say_do_gap.parquet, wba_targets.parquet", "voluntary", 2)
    col(D, "promised_target_year", mapcol(idx, tg.promised_target_year.to_dict()), "year",
        "Target year the promised rate was implied from", "targets_company.parquet",
        "voluntary", 2)
    col(D, "promised_baseline_year", mapcol(idx, tg.promised_baseline_year.to_dict()), "year",
        "Baseline year of the target", "targets_company.parquet", "voluntary", 2)
    col(D, "gap_pct_yr", mapcol(idx, sd.gap_pct_yr.to_dict()), "%/yr",
        "delivered minus promised. Positive means the company is cutting more slowly than it "
        "said", "say_do_gap.parquet", "modelled", 2)
    col(D, "sbti_near_term_status", mapcol(idx, tg.sbti_near_term_status.to_dict()), "",
        "SBTi near-term target status", "targets_company.parquet", "voluntary", 1)
    col(D, "sbti_near_term_classification",
        mapcol(idx, tg.sbti_near_term_classification.to_dict()), "",
        "SBTi temperature classification of the near-term target",
        "targets_company.parquet", "voluntary", 1)
    col(D, "sbti_net_zero_status", mapcol(idx, tg.sbti_net_zero_status.to_dict()), "",
        "SBTi net-zero target status", "targets_company.parquet", "voluntary", 1)
    col(D, "sbti_net_zero_year", mapcol(idx, tg.sbti_net_zero_year.to_dict()), "year",
        "Stated net-zero year", "targets_company.parquet", "voluntary", 1)

    # ---------------------------------------------------------- 4.7 financials
    fin = src["fin"]
    md = src["md"].set_index("Symbol")

    def latest_field(field):
        s = fin[fin[field].notna()].sort_values(["ticker", "fy"])
        last = s.groupby("ticker").tail(1)
        return (dict(zip(last.ticker, last[field])), dict(zip(last.ticker, last.fy)),
                dict(zip(last.ticker, last.period_end)))

    rev, rev_fy, rev_pe = latest_field("revenue")
    ebit, ebit_fy, ebit_pe = latest_field("operating_income")
    capex, capex_fy, _ = latest_field("capex")
    debt, debt_fy, _ = latest_field("total_debt")

    col(D, "revenue_musd", mapcol(idx, {k: v / 1e6 for k, v in rev.items()}), "USD millions",
        "SEC XBRL revenue, latest fiscal year carrying the field. Their sec_revenue is "
        "rejected: it takes the contract-revenue tag, which is a crumb for a bank or a REIT",
        "financials.parquet", "mandatory", 1)
    col(D, "revenue_basis", ["sec_xbrl" if k in rev else None for k in idx], "",
        "sec_xbrl on every row that has one", "financials.parquet", "mandatory", 1)
    col(D, "revenue_dq", [1 if k in rev else None for k in idx], "1-5",
        "PCAF data quality of revenue_musd", "financials.parquet", "mandatory", 1)
    col(D, "revenue_fy", mapcol(idx, rev_fy), "year", "Fiscal year of revenue_musd",
        "financials.parquet", "mandatory", 1)
    col(D, "revenue_period_end", mapcol(idx, rev_pe), "date",
        "Fiscal year end. 119 of 502 FY2023 rows end outside December",
        "financials.parquet", "mandatory", 1)
    col(D, "ebit_musd", mapcol(idx, {k: v / 1e6 for k, v in ebit.items()}), "USD millions",
        "SEC XBRL operating income, latest fiscal year carrying the field",
        "financials.parquet", "mandatory", 1)
    col(D, "ebit_basis", ["sec_xbrl" if k in ebit else None for k in idx], "",
        "sec_xbrl on every row that has one", "financials.parquet", "mandatory", 1)
    col(D, "ebit_dq", [1 if k in ebit else None for k in idx], "1-5",
        "PCAF data quality of ebit_musd", "financials.parquet", "mandatory", 1)
    col(D, "ebit_fy", mapcol(idx, ebit_fy), "year", "Fiscal year of ebit_musd",
        "financials.parquet", "mandatory", 1)
    col(D, "capex_musd", mapcol(idx, {k: v / 1e6 for k, v in capex.items()}), "USD millions",
        "SEC XBRL capital expenditure, latest fiscal year carrying the field",
        "financials.parquet", "mandatory", 1)
    col(D, "capex_fy", mapcol(idx, capex_fy), "year", "Fiscal year of capex_musd",
        "financials.parquet", "mandatory", 1)

    # D&A is the one number we did not extract. It comes from the teammate's master_dataset,
    # labelled sec_secondhand, and it feeds the EBITDA denominator and nothing else.
    da_v, da_y = {}, {}
    for y in (2024, 2023, 2022):
        c = md[f"sec_dep_amort_{y}"]
        for t, val in c.items():
            if t not in da_v and pd.notna(val):
                da_v[t], da_y[t] = float(val) / 1e6, y
    col(D, "da_musd", mapcol(idx, da_v), "USD millions",
        "Depreciation and amortisation. The only D&A anywhere in the project, taken from the "
        "teammate's extraction rather than our own",
        "data/raw/master_dataset.csv sec_dep_amort_*", "vendor", 3)
    col(D, "da_basis", ["sec_secondhand" if t in da_v else None for t in idx], "",
        "sec_secondhand: an SEC figure we did not extract ourselves",
        "data/raw/master_dataset.csv", "vendor", 3)
    col(D, "da_fy", mapcol(idx, da_y), "year", "Calendar year of da_musd",
        "data/raw/master_dataset.csv", "vendor", 3)

    # EBITDA is built, not taken. Our EBIT at the D&A's own year plus their D&A, so the two
    # halves cover the same period; else Yahoo's TTM figure, which is a different period and
    # is labelled as such.
    ebit_by_fy = {(r.ticker, r.fy): r.operating_income for r in
                  fin[fin.operating_income.notna()].itertuples()}
    yh_ebitda = md.yh_ebitda_ttm.to_dict()
    ev, eb, edq, efy = [], [], [], []
    for t in idx:
        y = da_y.get(t)
        e = ebit_by_fy.get((t, y)) if y else None
        if y and e is not None and pd.notna(e):
            ev.append(e / 1e6 + da_v[t]); eb.append("sec_ebit_plus_secondhand_da")
            edq.append(2); efy.append(y)
        elif pd.notna(yh_ebitda.get(t, np.nan)):
            ev.append(float(yh_ebitda[t]) / 1e6); eb.append("yahoo_ttm")
            edq.append(3); efy.append(None)
        else:
            ev.append(np.nan); eb.append(None); edq.append(None); efy.append(None)
    col(D, "ebitda_musd", ev, "USD millions",
        "Our SEC operating income at the D&A's own year plus that D&A, else Yahoo's trailing "
        "twelve months. Their sec_ebitda is rejected: it inherits their EBIT",
        "financials.parquet + master_dataset.csv, else yh_ebitda_ttm", "mixed", 2)
    col(D, "ebitda_basis", eb, "", "sec_ebit_plus_secondhand_da | yahoo_ttm",
        "financials.parquet + master_dataset.csv", "mixed", 2)
    col(D, "ebitda_dq", edq, "1-5", "PCAF data quality of ebitda_musd",
        "financials.parquet + master_dataset.csv", "mixed", 2)
    col(D, "ebitda_fy", efy, "year",
        "Fiscal year of ebitda_musd; null where the basis is a trailing twelve months",
        "financials.parquet", "mixed", 2)

    yh_debt = md.yh_total_debt.to_dict()
    dv, db, ddq = [], [], []
    for t in idx:
        if t in debt:
            dv.append(debt[t] / 1e6); db.append("sec_xbrl"); ddq.append(1)
        elif pd.notna(yh_debt.get(t, np.nan)):
            dv.append(float(yh_debt[t]) / 1e6); db.append("yahoo"); ddq.append(3)
        else:
            dv.append(np.nan); db.append(None); ddq.append(None)
    col(D, "total_debt_musd", dv, "USD millions",
        "SEC XBRL total debt, Yahoo where SEC has none", "financials.parquet, yh_total_debt",
        "mixed", 2)
    col(D, "total_debt_basis", db, "", "sec_xbrl | yahoo", "financials.parquet, yh_total_debt",
        "mixed", 2)
    col(D, "total_debt_dq", ddq, "1-5", "PCAF data quality of total_debt_musd",
        "financials.parquet, yh_total_debt", "mixed", 2)
    col(D, "total_debt_fy", mapcol(idx, debt_fy), "year",
        "Fiscal year of total_debt_musd where the basis is sec_xbrl",
        "financials.parquet", "mandatory", 1)
    col(D, "total_cash_musd",
        mapcol(idx, {k: v / 1e6 for k, v in md.yh_total_cash.dropna().to_dict().items()}),
        "USD millions", "Cash and equivalents. New to the project; our XBRL pull has none",
        "master_dataset.csv yh_total_cash", "vendor", 3)

    # Market cap: ours, with four named overrides. All four are up-C or multi-class structures
    # where the 10-K cover page counts one class and understates the holding by two to four x.
    mc = src["mcap"].set_index("ticker")
    ours_mc = mc.market_cap.to_dict()
    yh_mc = md.yh_market_cap.to_dict()
    mv, mb, mdq, stale = [], [], [], []
    asof = mc.shares_asof.to_dict()
    overrides = []
    for t in idx:
        a, b = ours_mc.get(t), yh_mc.get(t)
        if pd.notna(a) and pd.notna(b) and abs(a / b - 1) > 0.25:
            mv.append(b / 1e6); mb.append("yahoo_override_upc"); mdq.append(3)
            overrides.append((t, a / 1e9, b / 1e9))
        elif pd.notna(a):
            mv.append(a / 1e6); mb.append("sec_shares_x_price"); mdq.append(1)
        elif pd.notna(b):
            mv.append(b / 1e6); mb.append("yahoo"); mdq.append(3)
        else:
            mv.append(np.nan); mb.append(None); mdq.append(None)
        s = asof.get(t)
        stale.append(bool(isinstance(s, str) and s < "2026-01-01"))
    col(D, "market_cap_musd", mv, "USD millions",
        "SEC cover-page shares times the 2026-09-11 price, with four up-C names taken from "
        "Yahoo because the cover page counts one share class",
        "market_cap.parquet, yh_market_cap", "mixed", 1)
    col(D, "market_cap_basis", mb, "", "sec_shares_x_price | yahoo_override_upc | yahoo",
        "market_cap.parquet, yh_market_cap", "mixed", 1)
    col(D, "market_cap_dq", mdq, "1-5", "PCAF data quality of market_cap_musd",
        "market_cap.parquet, yh_market_cap", "mixed", 1)
    col(D, "market_cap_shares_stale", stale, "bool",
        "Share count is from a cover page filed before 2026, while the price is 2026-09-11. "
        "This is the 10 to 25 per cent band against Yahoo, a staleness to flag not a bug",
        "market_cap.parquet", "mandatory", 2)

    evic = [(a + b) if (pd.notna(a) and pd.notna(b)) else (a if pd.notna(a) else np.nan)
            for a, b in zip(mv, dv)]
    col(D, "evic_musd", evic, "USD millions",
        "Enterprise value including cash, market cap plus total debt, as PAB Article 5 defines "
        "it. Deliberately gross of cash: it is the financed-emissions denominator",
        "market_cap_musd + total_debt_musd", "mixed", 2)
    col(D, "evic_debt_observed", [pd.notna(x) for x in dv], "bool",
        "False where evic_musd is market cap alone because no debt figure exists",
        "financials.parquet, yh_total_debt", "mixed", 2)
    col(D, "ev_musd",
        mapcol(idx, {k: v / 1e6 for k, v in md.yh_enterprise_value.dropna().to_dict().items()}),
        "USD millions",
        "Enterprise value net of cash, for the valuation leg. We have none of our own",
        "master_dataset.csv yh_enterprise_value", "vendor", 3)

    # EV/EBITDA: reject a non-positive EBITDA, winsorise inside the sector, clamp globally,
    # then fall back to the sector median. dEV = dEBIT x multiple, so an outlier here is not a
    # cosmetic problem.
    raw_mult = md.yh_ev_ebitda.to_dict()
    raw_ebitda_ttm = md.yh_ebitda_ttm.to_dict()
    sect = dict(zip(idx, D["gics_sector"]))
    usable = {t: float(raw_mult[t]) for t in idx
              if pd.notna(raw_mult.get(t, np.nan))
              and pd.notna(raw_ebitda_ttm.get(t, np.nan)) and raw_ebitda_ttm[t] > 0}
    tmp = pd.DataFrame({"ticker": list(usable), "x": list(usable.values())})
    tmp["sector"] = tmp.ticker.map(sect)
    q = tmp.groupby("sector").x.quantile([0.05, 0.95]).unstack()
    sector_median = tmp.groupby("sector").x.median().to_dict()
    mult, mbasis, mdq2 = [], [], []
    n_wins = 0
    for t in idx:
        s = sect.get(t)
        if t in usable:
            x = usable[t]
            lo, hi = q.loc[s, 0.05], q.loc[s, 0.95]
            w = min(max(x, lo), hi)
            w = min(max(w, EV_EBITDA_FLOOR), EV_EBITDA_CAP)
            if abs(w - x) > 1e-9:
                mult.append(w); mbasis.append("yahoo_winsorised"); mdq2.append(3); n_wins += 1
            else:
                mult.append(x); mbasis.append("yahoo"); mdq2.append(2)
        elif s in sector_median:
            mult.append(float(sector_median[s])); mbasis.append("sector_median"); mdq2.append(4)
        else:
            mult.append(np.nan); mbasis.append(None); mdq2.append(None)
    col(D, "ev_ebitda_x", mult, "x",
        "EV/EBITDA multiple, winsorised to the sector 5th and 95th percentile then clamped to "
        f"[{EV_EBITDA_FLOOR:.0f}, {EV_EBITDA_CAP:.0f}], with the sector median where Yahoo "
        "publishes no positive EBITDA", "master_dataset.csv yh_ev_ebitda", "vendor", 3)
    col(D, "ev_ebitda_basis", mbasis, "", "yahoo | yahoo_winsorised | sector_median",
        "master_dataset.csv yh_ev_ebitda", "vendor", 3)
    col(D, "ev_ebitda_dq", mdq2, "1-5", "PCAF data quality of ev_ebitda_x",
        "master_dataset.csv yh_ev_ebitda", "vendor", 3)
    col(D, "ev_ebitda_raw_x", mapcol(idx, {t: float(raw_mult[t]) for t in idx
                                           if pd.notna(raw_mult.get(t, np.nan))}), "x",
        "The unguarded vendor multiple, kept so the guard is visible: three are negative and "
        "eleven exceed 60x", "master_dataset.csv yh_ev_ebitda", "vendor", 4)
    col(D, "fcf_musd",
        mapcol(idx, {k: v / 1e6 for k, v in md.yh_fcf.dropna().to_dict().items()}),
        "USD millions", "Free cash flow. New to the project, not used by the model chain",
        "master_dataset.csv yh_fcf", "vendor", 3)
    col(D, "beta_x", mapcol(idx, md.yh_beta.dropna().to_dict()), "x",
        "Equity beta. Needed only if the reweight is risk adjusted",
        "master_dataset.csv yh_beta", "vendor", 3)
    col(D, "revenue_ttm_musd_check",
        mapcol(idx, {k: v / 1e6 for k, v in md.yh_revenue_ttm.dropna().to_dict().items()}),
        "USD millions",
        "Yahoo trailing-twelve-month revenue. A cross-check only: TTM and fiscal year are "
        "different periods and must not be mixed", "master_dataset.csv yh_revenue_ttm",
        "vendor", 3)
    total_cap = float(np.nansum([v for v, p in zip(mv, D["is_primary_listing"]) if p]))
    col(D, "index_weight_pct",
        [100.0 * v / total_cap if (pd.notna(v) and p) else (0.0 if pd.notna(v) else np.nan)
         for v, p in zip(mv, D["is_primary_listing"])], "%",
        "Market cap share of the 500 primary listings. Secondary listings carry 0 so the "
        "column sums to 100", "market_cap_musd", "mixed", 1)

    # ---------------------------------------------------------- 4.8 penalty model at defaults
    price2010 = ngfs_price(src["ngfs"])
    price = price2010 * USD2010_TO_USD2026
    col(D, "price_usd2010_per_t", [price2010] * len(idx), "US$2010/tCO2",
        f"NGFS {NGFS_SCENARIO}, {NGFS_MODEL}, {NGFS_REGION}, {NGFS_YEAR}, exactly as published. "
        "Not averaged across models: GCAM says 98.6 and REMIND 283.7 for the same scenario",
        "ngfs_scenarios.parquet", "modelled", 3)
    col(D, "price_sector_usd_per_t", [price] * len(idx), "USD/tCO2",
        f"The stored default carbon penalty, price_usd2010_per_t deflated by "
        f"{USD2010_TO_USD2026}. The UI overwrites this per sector; NGFS itself publishes no "
        "sector differentiation", "ngfs_scenarios.parquet x a hard deflator", "modelled", 4)
    col(D, "coverage_scope1_pct", [COVERAGE_S1] * len(idx), "%",
        "Share of Scope 1 the penalty touches. Settable", "assumption", "modelled", 5)
    col(D, "coverage_scope2_pct", [COVERAGE_S2] * len(idx), "%",
        "Share of Scope 2 the penalty touches. Settable", "assumption", "modelled", 5)
    col(D, "coverage_scope3_pct", [COVERAGE_S3] * len(idx), "%",
        "Share of Scope 3 the penalty touches. Zero by default: pricing Scope 3 across a "
        "500-company index charges the same tonne several times", "assumption", "modelled", 5)
    pt = [PASSTHROUGH_DEFAULT.get(s, PASSTHROUGH_FALLBACK) * 100 for s in D["gics_sector"]]
    col(D, "passthrough_pct", pt, "%",
        "Share of the carbon cost pushed to customers. NO EMPIRICAL SOURCE EXISTS IN THIS "
        "REPO. A sector assumption with a default, settable, and labelled modelled everywhere",
        "assumption, PASSTHROUGH_DEFAULT in src/build_master.py", "modelled", 5)

    t1 = np.array([x if pd.notna(x) else np.nan for x in D["scope1_t"]], dtype=float)
    t2 = np.array([x if pd.notna(x) else np.nan for x in D["scope2_market_t"]], dtype=float)
    t3 = np.array([x if pd.notna(x) else np.nan for x in D["scope3_total_t"]], dtype=float)
    priced = (np.nan_to_num(t1) * COVERAGE_S1 / 100 + np.nan_to_num(t2) * COVERAGE_S2 / 100
              + np.nan_to_num(t3) * COVERAGE_S3 / 100)
    any_scope = np.isfinite(t1) | np.isfinite(t2) | np.isfinite(t3)
    priced = np.where(any_scope, priced, np.nan)
    cost = priced * price / 1e6
    col(D, "carbon_cost_musd", cost, "USD millions",
        "Priced tonnes times the penalty, before abatement. Null where no scope is known; "
        "a scope that is null inside a company that has another contributes nothing",
        "scope1_t, scope2_market_t, scope3_total_t x price_sector_usd_per_t", "mixed", 3)

    dl = np.array([x if pd.notna(x) else np.nan for x in D["delivered_pct_yr"]], dtype=float)
    base_year = np.array([y if pd.notna(y) else np.nan for y in D["scope1_year"]], dtype=float)
    years = np.clip(HORIZON_YEAR - base_year, 0, None)
    factor = np.where(np.isfinite(dl) & np.isfinite(years),
                      np.power(1 + dl / 100.0, np.nan_to_num(years)), 1.0)
    col(D, "abatement_factor", factor, "",
        f"(1 + delivered_pct_yr/100) ^ (2030 - scope1_year). 1.0 where no observed rate "
        "exists, which is the conservative reading: no credit for an unmeasured cut",
        "delivered_pct_yr", "modelled", 3)
    col(D, "carbon_cost_abated_musd", cost * factor, "USD millions",
        f"carbon_cost_musd after the company's OBSERVED reduction rate is run to "
        f"{HORIZON_YEAR}", "carbon_cost_musd x abatement_factor", "mixed", 3)
    dpt = np.array(pt, dtype=float) / 100.0
    debit = cost * factor * (1 - dpt)
    col(D, "d_ebit_musd", debit, "USD millions",
        "Abated carbon cost that lands on earnings, after the passthrough assumption",
        "carbon_cost_abated_musd x (1 - passthrough_pct)", "mixed", 4)
    ebit_arr = np.array([x if pd.notna(x) else np.nan for x in D["ebit_musd"]], dtype=float)
    col(D, "d_ebit_pct_of_ebit",
        np.where(ebit_arr > 0, 100 * debit / ebit_arr, np.nan), "%",
        "Earnings at risk. Null where operating income is zero or negative, never a ratio "
        "against a negative denominator", "d_ebit_musd / ebit_musd", "mixed", 4)
    mult_arr = np.array([x if pd.notna(x) else np.nan for x in D["ev_ebitda_x"]], dtype=float)
    dev = debit * mult_arr
    col(D, "d_ev_musd", dev, "USD millions",
        "Change in enterprise value, the earnings hit capitalised at the company's own "
        "multiple", "d_ebit_musd x ev_ebitda_x", "mixed", 4)
    ev_arr = np.array([x if pd.notna(x) else np.nan for x in D["ev_musd"]], dtype=float)
    col(D, "d_ev_pct_of_ev", np.where(ev_arr > 0, 100 * dev / ev_arr, np.nan), "%",
        "Value at risk. This is the reweighting input", "d_ev_musd / ev_musd", "mixed", 4)
    model_dq = []
    for i, t in enumerate(idx):
        parts = [D["scope1_dq"][pos[t]], D["ebit_dq"][pos[t]],
                 D["ev_ebitda_dq"][pos[t]], 5]
        vals = [int(p) for p in parts if pd.notna(p)]
        model_dq.append(max(vals) if np.isfinite(debit[i]) else None)
    col(D, "model_dq", model_dq, "1-5",
        "Worst PCAF grade among the inputs that fed d_ev_musd. Never better than 5 because "
        "passthrough is an assumption", "the columns above", "modelled", 5)

    # ---------------------------------------------------------- 4.9 constraints and conduct
    rex = src["rex"]
    fired = rex[rex.flag_best]
    art = (fired.sort_values(["ticker", "article"]).groupby("ticker").article
           .apply(lambda s: ";".join(sorted(set(s)))).to_dict())
    basis_by_t = (fired.sort_values(["ticker", "flag_dq"]).groupby("ticker").flag_basis
                  .first().to_dict())
    dq_by_t = fired.groupby("ticker").flag_dq.max().to_dict()
    rex_dq_all = rex.groupby("ticker").flag_dq.max().to_dict()
    # The three secondary listings inherit their sibling's power test; ARES has no plants.
    g12 = {t: bool(v) for t, v in pf.excl_12g.to_dict().items() if pd.notna(v)}
    for t in idx:
        if t not in g12:
            s_ = sib.get(t)
            g12[t] = bool(g12.get(s_, False)) if isinstance(s_, str) else False
    col(D, "excl_12g", [bool(g12.get(t, False)) for t in idx], "bool",
        "The Article 12(1)(g) test: a power generator above 100 gCO2e/kWh",
        "plant_intensity.parquet via portfolio.parquet", "modelled", 2)
    excl = [bool(t in art or g12.get(t, False)) for t in idx]
    arts = []
    for t in idx:
        a = art.get(t, "")
        if g12.get(t, False):
            a = ";".join([x for x in [a, "Article 12(1)(g)"] if x])
        arts.append(a if a else None)
    col(D, "excluded", excl, "bool",
        "Any EU 2020/1818 Article 12 exclusion fires", "revenue_exclusions.parquet + excl_12g",
        "mixed", 2)
    col(D, "excl_articles", arts, "",
        "Which articles fire, semicolon separated", "revenue_exclusions.parquet + excl_12g",
        "mixed", 2)
    eb = []
    for t in idx:
        b = basis_by_t.get(t)
        if b is None and g12.get(t, False):
            b = "power_intensity_12g"
        eb.append(b)
    col(D, "excl_basis", eb, "",
        "Which screen decided the exclusion: sec_segment (measured segment revenue tested "
        "against the article threshold), gics_proxy, nbim_exclusion, or power_intensity_12g "
        "where only the 100 gCO2e/kWh test fires. Null where nothing fires",
        "revenue_exclusions.parquet, plant_intensity.parquet", "mixed", 2)
    col(D, "excl_dq", [dq_by_t.get(t, rex_dq_all.get(t)) for t in idx], "1-5",
        "PCAF data quality of the exclusion decision: 1 where measured segment revenue was "
        "tested against the article's own threshold, 4 or 5 for a sector proxy",
        "revenue_exclusions.parquet", "mixed", 3)
    hi = pf.high_impact.to_dict()
    high_nace = set("ABCDEFGH") | {"L"}  # PAB Annex I high-impact sections
    col(D, "high_impact_nace",
        [bool(hi[t]) if (t in hi and pd.notna(hi[t]))
         else bool(D["nace_section"][pos[t]] in high_nace) for t in idx], "bool",
        "NACE high-impact sector under the PAB rules, derived from nace_section on the four "
        "listings portfolio.parquet does not carry", "portfolio.parquet", "modelled", 3)

    vi = src["viol"].set_index("ticker")
    col(D, "penalty_usd_environment", mapcol(idx, vi.penalty_usd_environment.to_dict()), "USD",
        "Violation Tracker environmental penalties, 2000-2026",
        "violations_summary.parquet", "mandatory", 1)
    col(D, "case_count_environment", mapcol(idx, vi.case_count_environment.to_dict()), "count",
        "Environmental enforcement cases behind that total",
        "violations_summary.parquet", "mandatory", 1)
    col(D, "penalty_usd_total", mapcol(idx, vi.penalty_usd_total.to_dict()), "USD",
        "All Violation Tracker penalties, every offence group",
        "violations_summary.parquet", "mandatory", 1)
    pe_env = vi.penalty_usd_environment.to_dict()
    col(D, "conduct_measured_zero",
        [bool(pd.notna(pe_env.get(t)) and pe_env.get(t) == 0) for t in idx], "bool",
        "Searched and found no environmental penalty. A measured zero, not a missing value",
        "violations_summary.parquet", "mandatory", 1)

    # ---------------------------------------------------------- 4.10 benchmark, never an input
    sc = src["scores"].set_index("ticker")
    vd = src["vendor"].set_index("ticker")
    col(D, "vendor_percentile", mapcol(idx, vd.vendor_percentile.to_dict()), "percentile",
        "Consensus percentile across six free ESG datasets. VENDOR: a benchmark for our score, "
        "never an input to it", "esg_vendor_consensus.parquet", "vendor", 4)
    col(D, "vendor_n_sources", mapcol(idx, vd.n_sources.to_dict()), "count",
        "How many vendor datasets carry the company", "esg_vendor_consensus.parquet",
        "vendor", 4)
    col(D, "our_percentile", mapcol(idx, sc.our_percentile.to_dict()), "percentile",
        "Our score as a percentile, built from mandatory and voluntary data only",
        "scores.parquet", "modelled", 2)
    col(D, "rank_median", mapcol(idx, sc.rank_median.to_dict()), "rank",
        "Median rank over the uncertainty draws, 1 is best", "scores.parquet", "modelled", 2)
    col(D, "rank_p05", mapcol(idx, sc.rank_p05.to_dict()), "rank",
        "5th percentile of the rank distribution", "scores.parquet", "modelled", 2)
    col(D, "rank_p95", mapcol(idx, sc.rank_p95.to_dict()), "rank",
        "95th percentile of the rank distribution. rank_p95 minus rank_p05 is the honest width "
        "of the answer", "scores.parquet", "modelled", 2)
    col(D, "coverage_tier", mapcol(idx, sc.coverage_tier.to_dict()), "",
        "measured (mandatory tonnage), reported (voluntary only) or unmeasurable",
        "scores.parquet", "modelled", 1)
    col(D, "score_mirrored_from", mapcol(idx, sc.mirrored_from.to_dict()), "",
        "The primary listing whose score this secondary listing copies",
        "scores.parquet", "modelled", 1)

    # Two provenance columns, and both are a fact about the row rather than a worst-of roll-up
    # across everything. A worst-of column reads "vendor" on all 503 rows, because the EV/EBITDA
    # multiple and the second-hand D&A are vendor numbers on nearly every row, and a column with
    # one value says nothing. provenance_class is the class of the headline emissions fact and
    # is the schema enforcement: it must never say vendor.
    S1 = {"self_reported": "voluntary", "ghgrp_fossil": "mandatory",
          "ghgrp_fossil_floor": "mandatory", "climatetrace_equity": "modelled"}
    col(D, "provenance_class",
        [S1[b] if (b is not None and pd.notna(b)) else None for b in D["scope1_basis"]], "",
        "Provenance of scope1_t: mandatory where EPA measured it, voluntary where the company "
        "declared it, modelled where Climate TRACE inferred it, null where nobody knows. Never "
        "vendor, by construction and by assertion", "this script", "modelled", 1)

    ORDER = ["mandatory", "voluntary", "modelled", "vendor"]
    FB = {"sec_xbrl": "mandatory", "sec_shares_x_price": "mandatory",
          "yahoo": "vendor", "yahoo_override_upc": "vendor"}
    fin_cls = []
    for i in range(len(idx)):
        cc = [FB.get(D[c][i]) for c in ("revenue_basis", "ebit_basis", "total_debt_basis",
                                        "market_cap_basis")]
        cc = [c for c in cc if c]
        fin_cls.append(max(cc, key=ORDER.index) if cc else None)
    col(D, "financial_provenance_class", fin_cls, "",
        "Worst class among the four financial facts we extracted ourselves: revenue, EBIT, "
        "debt and market cap. EBITDA and the multiple are excluded because they are vendor by "
        "design and carry their own _basis", "this script", "modelled", 1)
    col(D, "generated_at", [GENERATED_AT] * len(idx), "timestamp",
        "When this row was built", "this script", "modelled", 1)

    return pd.DataFrame(D), overrides, n_wins, price2010


def ngfs_price(ngfs):
    p = ngfs[(ngfs.scenario == NGFS_SCENARIO) & (ngfs.model == NGFS_MODEL)
             & (ngfs.region == NGFS_REGION) & (ngfs.year == NGFS_YEAR)
             & (ngfs.variable == "Price|Carbon")]
    assert len(p) == 1, f"NGFS price is not unique: {len(p)} rows"
    return float(p.value.iloc[0])


# ============================================================== 5. the panel
def build_panel(src):
    """Long: ticker, year, metric, value. Emissions and financials 2010-2026 where they exist."""
    rows = []

    def add(df, ticker_c, year_c, value_c, metric, unit, source, cls, dq_c=None, dq=None,
            eligible=True):
        d = df[df[value_c].notna()]
        rows.append(pd.DataFrame({
            "ticker": d[ticker_c].to_numpy(), "year": d[year_c].astype(int).to_numpy(),
            "metric": metric, "value": d[value_c].astype(float).to_numpy(),
            "unit": unit, "source": source, "provenance_class": cls,
            "dq": (d[dq_c].to_numpy() if dq_c else dq),
            "headline_eligible": (d[eligible].to_numpy() if isinstance(eligible, str)
                                  else eligible)}))

    g = src["ghgrp"].copy()
    g["net"] = g.meas_fossil_equity - g.meas_fossil_lookahead
    add(g, "ticker", "year", "net", "scope1_ghgrp_fossil_t", "tCO2e",
        "ghgrp_ticker_year.parquet", "mandatory", dq=1)
    add(g, "ticker", "year", "meas_all_equity", "scope1_ghgrp_allgas_t", "tCO2e",
        "ghgrp_ticker_year.parquet", "mandatory", dq=1)
    add(g, "ticker", "year", "meas_biogenic_equity", "scope1_ghgrp_biogenic_t", "tCO2e",
        "ghgrp_ticker_year.parquet", "mandatory", dq=1)
    add(g, "ticker", "year", "meas_fossil_lookahead", "scope1_ghgrp_lookahead_t", "tCO2e",
        "ghgrp_ticker_year.parquet", "modelled", dq=2)
    add(g, "ticker", "year", "meas_fossil_ar6", "scope1_ghgrp_fossil_ar6_t", "tCO2e",
        "ghgrp_ticker_year.parquet", "modelled", dq=2)

    em = src["emissions"]
    add(em, "ticker", "year", "scope1_camd_tonnes", "scope1_camd_t", "tCO2",
        "emissions_by_ticker.parquet", "mandatory", dq_c="dq_camd")

    wba = src["wba_em"]
    wba = pd.concat([wba[wba.preferred], src["wba_backfill"]], ignore_index=True)
    for scope, metric in [("1", "scope1_selfreported_t"), ("2", "scope2_selfreported_t"),
                          ("3", "scope3_selfreported_t"), ("1+2", "scope12_selfreported_t")]:
        add(wba[wba.scope == scope], "ticker", "fy", "tonnes_co2e", metric, "tCO2e",
            "wba_emissions.parquet", "voluntary", dq_c="dq")
    # The panel carries every extracted row, including the ones the magnitude screen demoted,
    # with headline_eligible saying which ones master_company was allowed to read.
    s23 = src["scope23"]
    s23 = s23[s23.tonnes_co2e.notna()].copy()
    kept = set(zip(src["scope23_screened"].ticker, src["scope23_screened"].fy,
                   src["scope23_screened"].scope))
    s23["_ok"] = [tuple(x) in kept for x in zip(s23.ticker, s23.fy, s23.scope)]
    for scope, metric in [("1", "scope1_report_t"), ("2_market", "scope2_market_report_t"),
                          ("2_location", "scope2_location_report_t"),
                          ("3_total", "scope3_report_t")]:
        add(s23[s23.scope == scope], "ticker", "fy", "tonnes_co2e", metric, "tCO2e",
            "scope23.parquet", "voluntary", dq_c="dq", eligible="_ok")

    ct = src["ct"].groupby(["ticker", "year"], as_index=False).equity_share_tonnes_co2e.sum()
    add(ct, "ticker", "year", "equity_share_tonnes_co2e", "scope1_climatetrace_equity_t",
        "tCO2e", "climatetrace_company.parquet", "modelled", dq=4)

    fin = src["fin"].copy()
    for field, metric in [("revenue", "revenue_musd"), ("operating_income", "ebit_musd"),
                          ("capex", "capex_musd"), ("total_debt", "total_debt_musd"),
                          ("net_income", "net_income_musd"), ("assets", "assets_musd"),
                          ("equity", "equity_musd")]:
        d = fin[fin[field].notna()].copy()
        d["_v"] = d[field] / 1e6
        add(d, "ticker", "fy", "_v", metric, "USD millions", "financials.parquet",
            "mandatory", dq=1)

    md = src["md"]
    for y in (2022, 2023, 2024):
        d = md[md[f"sec_dep_amort_{y}"].notna()].copy()
        d["_y"] = y
        d["_v"] = d[f"sec_dep_amort_{y}"] / 1e6
        add(d, "Symbol", "_y", "_v", "da_musd", "USD millions",
            "data/raw/master_dataset.csv", "vendor", dq=3)

    panel = pd.concat(rows, ignore_index=True)
    panel = panel[panel.year.between(2010, 2026)]
    panel["dq"] = pd.to_numeric(panel.dq, errors="coerce")
    panel = panel.sort_values(["ticker", "metric", "year"]).reset_index(drop=True)
    return panel


# ============================================================== 6. outputs
def write_xlsx(master, registry, path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "master_company"
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1F3A5F")
    ws.append(list(master.columns))
    for c in ws[1]:
        c.font = head
        c.fill = fill
        c.alignment = Alignment(vertical="center", wrap_text=False)
    for rec in master.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and not np.isfinite(v)) or v is pd.NA
                   or (not isinstance(v, (list, tuple, np.ndarray)) and pd.isna(v))
                   else (v.to_pydatetime().replace(tzinfo=None)
                         if isinstance(v, pd.Timestamp) else v)
                   for v in rec])
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    THOUSANDS = {"tCO2e", "tCO2", "USD", "count", "rank", "MWh", "USD millions"}
    PLAIN = {"year", "1-5"}
    for i, name in enumerate(master.columns, start=1):
        L = get_column_letter(i)
        unit = next(r["unit"] for r in registry if r["name"] == name)
        numeric = (pd.api.types.is_numeric_dtype(master[name])
                   and not pd.api.types.is_bool_dtype(master[name]))
        # Wide enough for the widest value, not just the header: 86,320,993 needs 12 characters.
        floor = 15 if (numeric and unit in THOUSANDS) else 10
        ws.column_dimensions[L].width = max(floor, min(34, len(name) + 3))
        if numeric:
            fmt = "0" if unit in PLAIN else ("#,##0" if unit in THOUSANDS
                                             else ("0.000" if unit == "" else "#,##0.00"))
            for cell in ws[L][1:]:
                cell.number_format = fmt

    ws2 = wb.create_sheet("column_registry")
    cols = ["name", "unit", "definition", "source", "provenance_class", "dq_typical",
            "non_null_count", "script"]
    ws2.append(cols)
    for c in ws2[1]:
        c.font = head
        c.fill = fill
    for r in registry:
        ws2.append([r[c] for c in cols])
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = ws2.dimensions
    for L, w in zip("ABCDEFGH", [34, 16, 96, 44, 18, 12, 15, 22]):
        ws2.column_dimensions[L].width = w
    for row in ws2.iter_rows(min_row=2):
        row[2].alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(path)


def coverage_table(master):
    reg = {r["name"]: r for r in REGISTRY}
    rows = []
    prim = master.is_primary_listing.to_numpy()
    for c in master.columns:
        s = master[c]
        nn = int(s.notna().sum())
        if pd.api.types.is_bool_dtype(s):
            nn = int(len(s))
        rows.append({"column": c, "unit": reg[c]["unit"],
                     "provenance_class": reg[c]["provenance_class"],
                     "non_null_503": nn,
                     "non_null_500_primary": int(s[prim].notna().sum())
                     if not pd.api.types.is_bool_dtype(s) else int(prim.sum()),
                     "pct_of_503": round(100 * nn / len(master), 1)})
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    src = load_sources()
    ids, rejected = wba_crosswalk_gains(src)
    src["scope23_screened"] = screen_report_pdf(src["scope23"])
    src["wba_backfill"] = wba_backfill_rows(ids)
    master, overrides, n_wins, price2010 = build(src)

    # ------------------------------------------------------------------ assertions
    assert len(master) == 503, f"expected 503 listings, got {len(master)}"
    assert master.ticker.is_unique, "duplicate ticker"
    assert int(master.is_primary_listing.sum()) == 500, (
        f"is_primary_listing sums to {int(master.is_primary_listing.sum())}, expected 500")
    assert set(master.ticker) == set(src["universe"].ticker), "ticker set differs from universe"
    names = [r["name"] for r in REGISTRY]
    assert names == list(master.columns), "registry and frame disagree on columns or order"
    assert len(set(names)) == len(names), "duplicate column in the registry"
    # The schema is the enforcement: no vendor number reaches a climate fact.
    assert not (master.provenance_class == "vendor").any(), "vendor provenance on a climate row"
    assert master.scope1_basis.dropna().isin(
        ["self_reported", "ghgrp_fossil", "ghgrp_fossil_floor", "climatetrace_equity"]).all()
    for c in master.columns:
        if c.endswith("_t") or c.endswith("_musd") or c == "scope1_t":
            v = pd.to_numeric(master[c], errors="coerce")
            assert not ((v == 0) & master[c].notna()).all(), f"{c} is all zero"
    print(f"\nassertions passed: {len(master)} listings, "
          f"{int(master.is_primary_listing.sum())} primary, {master.shape[1]} columns")

    panel = build_panel(src)

    cov = coverage_table(master)
    reg = pd.DataFrame(REGISTRY)
    reg = reg.merge(cov[["column", "non_null_503"]].rename(
        columns={"column": "name", "non_null_503": "non_null_count"}), on="name")
    reg = reg[["name", "unit", "definition", "source", "provenance_class", "dq_typical",
               "non_null_count", "script"]]

    master.to_parquet(OUT / "master_company.parquet", index=False)
    master.to_csv(OUT / "master_company.csv", index=False)
    panel.to_parquet(OUT / "master_panel.parquet", index=False)
    reg.to_csv(OUT / "column_registry.csv", index=False)
    write_xlsx(master, reg.to_dict("records"), OUT / "master_company.xlsx")

    # ------------------------------------------------------------------ what happened
    print(f"\nmarket cap overrides ({len(overrides)}): " + ", ".join(
        f"{t} {a:.1f}bn -> {b:.1f}bn" for t, a, b in overrides))
    print(f"EV/EBITDA: {int((master.ev_ebitda_basis == 'yahoo').sum())} taken as published, "
          f"{n_wins} winsorised or clamped, "
          f"{int((master.ev_ebitda_basis == 'sector_median').sum())} on the sector median, "
          f"{int(master.ev_ebitda_x.isna().sum())} null")
    print(f"NGFS default price: {price2010:.2f} US$2010/tCO2 -> "
          f"{price2010 * USD2010_TO_USD2026:.2f} USD/tCO2 at a {USD2010_TO_USD2026} deflator")

    # Cross-checks worth printing because they are the ones a reader will doubt.
    pf = src["portfolio"].set_index("ticker")
    j = master.set_index("ticker").join(pf[["evic_musd"]].rename(
        columns={"evic_musd": "evic_portfolio"}), how="inner")
    r = (j.evic_musd / j.evic_portfolio).replace([np.inf, -np.inf], np.nan).dropna()
    print(f"\nevic_musd against portfolio.parquet on {len(r)} shared rows: "
          f"median {r.median():.4f}, within 1% on {int((r.sub(1).abs() < 0.01).sum())}")
    fl = master[master.scope1_below_measured_floor]
    near = int((fl.scope1_selfreported_t / fl.scope1_measured_us_t > 0.90).sum())
    print(f"floor rule fired on {len(fl)} listings; {near} of them report within 10% of the "
          f"measured figure, which is boundary noise, and {len(fl) - near} are materially "
          f"below: " + ", ".join(sorted(fl[fl.scope1_selfreported_t
                                           / fl.scope1_measured_us_t <= 0.90].ticker)))

    p = master[master.is_primary_listing]
    print("\nSCOPE 1 PRECEDENCE, 500 primary listings")
    print(p.scope1_basis.value_counts(dropna=False).rename("listings").to_string())
    print(f"  self-reports rejected against the EPA-measured floor: "
          f"{int(p.scope1_below_measured_floor.sum())}")
    print(f"  any Scope 1 at all: {int(p.scope1_t.notna().sum())}, "
          f"none: {int(p.scope1_t.isna().sum())}")
    print("\nScope 1 coverage by sector, primary listings")
    bysec = p.groupby("gics_sector").agg(n=("ticker", "size"),
                                         with_s1=("scope1_t", "count"))
    bysec["pct"] = (100 * bysec.with_s1 / bysec.n).round(0)
    print(bysec.sort_values("pct", ascending=False).to_string())

    print("\nPROVENANCE, 503 listings")
    print(pd.DataFrame({
        "climate": master.provenance_class.value_counts(dropna=False),
        "financial": master.financial_provenance_class.value_counts(dropna=False),
    }).fillna(0).astype(int).to_string())
    print("\nCOVERAGE TIER")
    print(master.coverage_tier.value_counts(dropna=False).to_string())

    print(f"\nPANEL  {len(panel):,} rows x {panel.shape[1]} cols, "
          f"{panel.ticker.nunique()} tickers, {panel.metric.nunique()} metrics, "
          f"{panel.year.min()}-{panel.year.max()}")
    print(panel.groupby("metric").agg(rows=("value", "size"), tickers=("ticker", "nunique"),
                                      y0=("year", "min"), y1=("year", "max")).to_string())

    print(f"\nFULL COVERAGE TABLE, {len(cov)} columns of master_company")
    print(f"{'column':<32}{'unit':<16}{'class':<11}{'n/503':>7}{'n/500prim':>11}{'pct':>7}")
    for r in cov.itertuples(index=False):
        print(f"{r.column:<32}{r.unit[:15]:<16}{r.provenance_class:<11}"
              f"{r.non_null_503:>7}{r.non_null_500_primary:>11}{r.pct_of_503:>7.1f}")

    print(f"\nwrote {OUT}/master_company.parquet   {master.shape[0]} x {master.shape[1]}")
    print(f"wrote {OUT}/master_company.csv")
    print(f"wrote {OUT}/master_company.xlsx")
    print(f"wrote {OUT}/master_panel.parquet       {panel.shape[0]} x {panel.shape[1]}")
    print(f"wrote {OUT}/column_registry.csv        {len(reg)} rows")
    cov.to_csv(OUT / "coverage_table.csv", index=False)
    print(f"wrote {OUT}/coverage_table.csv")
    (OUT / "build_notes.json").write_text(json.dumps({
        "generated_at": GENERATED_AT.isoformat(),
        "rows": int(len(master)), "columns": int(master.shape[1]),
        "primary_listings": int(master.is_primary_listing.sum()),
        "panel_rows": int(len(panel)),
        "wba_crosswalk_accepted": sorted(ids), "wba_crosswalk_rejected": rejected,
        "market_cap_overrides": [t for t, _, _ in overrides],
        "ngfs_price_usd2010": price2010, "deflator": USD2010_TO_USD2026,
        "passthrough_default": PASSTHROUGH_DEFAULT,
    }, indent=1))


if __name__ == "__main__":
    main()
