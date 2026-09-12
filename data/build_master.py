"""Build one master S&P 500 sustainability table from the files in tmp/.

Spine  : data/sp500_ocr.csv  (OCR'd list: ticker, name, market cap, price, revenue)
Joins  : tmp/SP 500 ESG Risk Ratings.csv               (Sustainalytics via Kaggle, 2024)  on ticker
         tmp/climate-credit-risk-analyzer-main/...csv   (yfinance snapshot: EBITDA, growth, employees) on ticker
         tmp/preprocessed_content.csv                   (sustainability-report NLP scores) on ticker, latest year
         tmp/ghg.csv                                    (EPA GHGRP 2023, facility-level)  on parent-company name
Output : web/data/master.csv, web/data/master.json, data/ghgrp_unmatched_parents.csv

Needs openpyxl (.venv). Run: .venv/bin/python data/build_master.py
"""
import csv, json, re, os, sys, collections
csv.field_size_limit(sys.maxsize)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
T = lambda *p: os.path.join(ROOT, "tmp", *p)

def money(s):
    """'5.27T' -> 5270 ($B), '897.54M' -> 0.898"""
    if not s: return None
    m = re.match(r"([\d.]+)([TBM])", s.strip())
    if not m: return None
    v, u = float(m.group(1)), m.group(2)
    return round(v * {"T": 1000, "B": 1, "M": 0.001}[u], 3)

def num(s):
    try: return float(str(s).replace(",", "").replace("%", ""))
    except: return None

norm_tick = lambda t: t.replace("-", ".").upper().strip()

# ---------- 1. spine ----------
spine = []
seen_names = set()
for r in csv.DictReader(open(os.path.join(ROOT, "data", "sp500_ocr.csv"))):
    key = (r["Company"], r["Revenue"])
    dual = key in seen_names                      # GOOG/GOOGL, FOX/FOXA, NWS/NWSA
    seen_names.add(key)
    spine.append({
        "ticker": norm_tick(r["Ticker"]), "name": r["Company"], "rank_by_mcap": int(r["Rank"]),
        "market_cap_b": money(r["Market Cap"]), "price": num(r["Price"]), "revenue_b": money(r["Revenue"]),
        "dual_class_duplicate": dual,
    })
by_tick = {c["ticker"]: c for c in spine}

# ---------- 2. Sustainalytics ESG risk ----------
n = 0
for r in csv.DictReader(open(T("SP 500 ESG Risk Ratings.csv"))):
    c = by_tick.get(norm_tick(r["Symbol"]))
    if not c: continue
    n += 1
    c.update({
        "sector": r["Sector"] or None, "industry": r["Industry"] or None,
        "employees": num(r["Full Time Employees"]),
        "esg_risk_total": num(r["Total ESG Risk score"]), "esg_risk_env": num(r["Environment Risk Score"]),
        "esg_risk_social": num(r["Social Risk Score"]), "esg_risk_gov": num(r["Governance Risk Score"]),
        "controversy_level": r["Controversy Level"] or None, "controversy_score": num(r["Controversy Score"]),
        "esg_risk_percentile": num((r["ESG Risk Percentile"] or "").split()[0]) if r["ESG Risk Percentile"] else None,
        "esg_risk_level": r["ESG Risk Level"] or None,
    })
print(f"Sustainalytics: matched {n}")

# ---------- 3. yfinance snapshot (credit-risk repo) ----------
n = 0
for r in csv.DictReader(open(T("climate-credit-risk-analyzer-main", "climate_credit_risk_data.csv"))):
    c = by_tick.get(norm_tick(r["Symbol"]))
    if not c: continue
    n += 1
    c["ebitda_b"] = round(num(r["Ebitda"]) / 1e9, 3) if num(r["Ebitda"]) else None
    c["revenue_growth"] = num(r["Revenuegrowth"])
    c.setdefault("employees", num(r["Fulltimeemployees"]))
    c.setdefault("sector", r["Sector"] or None); c.setdefault("industry", r["Industry"] or None)
    c["ntc_climate_credit_score"] = num(r["climate_credit_risk_score"])
print(f"yfinance snapshot: matched {n}")

# ---------- 4. sustainability-report NLP scores (latest year per ticker) ----------
best = {}
with open(T("preprocessed_content.csv")) as f:
    for r in csv.DictReader(f):
        t = norm_tick(r["ticker"]); y = int(r["year"])
        if t in by_tick and (t not in best or y > best[t][0]):
            best[t] = (y, r)
        by_tick.get(t, {}).setdefault("report_count", 0)
        if t in by_tick: by_tick[t]["report_count"] += 1
for t, (y, r) in best.items():
    by_tick[t].update({"report_year": y, "report_e_score": num(r["e_score"]), "report_s_score": num(r["s_score"]),
                       "report_g_score": num(r["g_score"]), "report_total_score": num(r["total_score"])})
print(f"Report NLP scores: matched {len(best)}")


DSTOP = {"inc", "corp", "corporation", "company", "co", "plc", "ltd", "group", "holdings", "incorporated", "limited", "the", "and", "of",
         "international", "technologies", "technology", "industries", "energy", "financial", "services", "global", "systems", "solutions",
         "health", "healthcare", "communications", "resources", "properties", "trust", "partners", "capital", "products", "brands", "foods",
         "worldwide", "sciences", "materials", "stores", "realty", "power", "electric", "american", "general", "united", "national", "first", "new"}
def domain_plausible(domain, name, ticker):
    toks = [w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if len(w) >= 3 and w not in DSTOP]
    host = domain.split(".")[0].replace("-", "")
    return any(w[:4] in host for w in toks) or any(host[:4] in w for w in toks if len(host) >= 4) or ticker.lower() == host

# ---------- 4b. Global Corporate ESG and Financial Dataset (Kaggle mrbossjaysrb; Yahoo/Sustainalytics-style fields) ----------
CTR6 = ["Controversies.Environment", "Controversies.Social", "Controversies.Customers", "Controversies.Human Rights & Community",
        "Controversies.Labor Rights & Supply Chain", "Controversies.Governance"]
SEV = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
n = 0; seen_corp = set()
for r in csv.DictReader(open(T("Global Corporate ESG and Financial Dataset.csv")), delimiter=";"):
    tk = norm_tick(r.get("ticker") or ""); c = by_tick.get(tk)
    if not c or tk in seen_corp: continue
    seen_corp.add(tk); n += 1
    nz = lambda v: None if v in ("", "null", None) else v
    c["logo_domain"] = nz(r["domain"])
    if c["logo_domain"] and not domain_plausible(c["logo_domain"], c["name"], c["ticker"]): c["logo_domain"] = None   # dataset column is often a different company
    c["altman_z"] = num(nz(r["altman_score"]))
    c["piotroski_f"] = num(nz(r["piotroski_score"]))
    c["esg_risk_yahoo"] = num(nz(r["esg"]))
    c["decarb_target_year"] = num(nz(r["Decarbonization Target.Target Year"]))
    c["decarb_ambition_pa_pct"] = num(nz(r["Decarbonization Target.Ambition p.a."]))
    c["decarb_coverage_pct"] = num(nz(r["Decarbonization Target.Comprehensiveness"]))
    c["temp_goal_c"] = num(nz(r["Temperature Goal"]))
    flags = [SEV.get(r[k]) for k in CTR6 if r[k] in SEV]
    if flags:
        c["controversy_flags"] = sum(1 for f in flags if f > 0)
        c["controversy_worst"] = ["Green", "Yellow", "Orange", "Red"][max(flags)]
    sdg = [k for k in r if k.startswith("sdg.") and k != "sdg"]
    if any(r[k] for k in sdg): c["sdg_aligned_count"] = sum(1 for k in sdg if r[k] == "Aligned")
    c.setdefault("employees", num(nz(r["employees"])))
    c.setdefault("industry", (r["industry"] or "").strip() or None)
print(f"Global Corporate ESG dataset: matched {n}")

# ---------- 5. EPA GHGRP 2023 -> parent company -> ticker ----------
STOP = {"INC", "CORP", "CORPORATION", "CO", "COMPANY", "COMPANIES", "LLC", "LP", "L P", "PLC", "LTD", "LIMITED",
        "HOLDINGS", "HOLDING", "GROUP", "THE", "SA", "NV", "N V", "USA", "US", "INTERNATIONAL", "INCORPORATED", "TRUST",
        "ENTERPRISES", "PARTNERS", "GLOBAL", "INDUSTRIES", "TECHNOLOGIES", "SERVICES", "SYSTEMS", "ENERGY"}
def norm_name(s):
    s = re.sub(r"[^A-Z0-9 ]", " ", s.upper().replace("&", " AND "))
    toks = [t for t in s.split() if t not in STOP]
    return " ".join(toks)
# manual aliases where the GHGRP parent name and the OCR name differ too much
ALIAS = {
    "EXXON MOBIL": "XOM", "CHEVRON": "CVX", "MARATHON PETROLEUM": "MPC", "PHILLIPS 66": "PSX", "VALERO": "VLO",
    "DUKE": "DUK", "SOUTHERN": "SO", "DOMINION": "D", "NEXTERA": "NEE", "AMERICAN ELECTRIC POWER": "AEP",
    "XCEL": "XEL", "ENTERGY": "ETR", "EXELON": "EXC", "FIRSTENERGY": "FE", "PPL": "PPL", "DTE": "DTE",
    "CMS": "CMS", "AMEREN": "AEE", "EVERGY": "EVRG", "ALLIANT": "LNT", "WEC": "WEC", "NRG": "NRG",
    "VISTRA": "VST", "CONSTELLATION": "CEG", "AES": "AES", "SEMPRA": "SRE", "EDISON": "EIX", "PG AND E": "PCG",
    "CENTERPOINT": "CNP", "NISOURCE": "NI", "ATMOS": "ATO", "PINNACLE WEST": "PNW", "EVERSOURCE": "ES",
    "CONSOLIDATED EDISON": "ED", "PUBLIC SERVICE ENTERPRISE": "PEG", "BERKSHIRE HATHAWAY": "BRK.B",
    "KINDER MORGAN": "KMI", "WILLIAMS": "WMB", "THE WILLIAMS COS": "WMB", "ONEOK": "OKE", "TARGA RESOURCES": "TRGP",
    "WASTE MANAGEMENT": "WM", "REPUBLIC": "RSG", "EOG RESOURCES": "EOG", "CONOCOPHILLIPS": "COP",
    "OCCIDENTAL PETROLEUM": "OXY", "DEVON": "DVN", "DIAMONDBACK": "FANG", "APA": "APA", "EQT": "EQT",
    "EXPAND": "EXE", "CHESAPEAKE": "EXE", "NUCOR": "NUE", "STEEL DYNAMICS": "STLD", "DOW": "DOW",
    "LYONDELLBASELL": "LYB", "LINDE": "LIN", "AIR PRODUCTS AND CHEMICALS": "APD", "CF": "CF", "MOSAIC": "MOS",
    "FREEPORT MCMORAN": "FCX", "NEWMONT": "NEM", "MARTIN MARIETTA": "MLM", "VULCAN MATERIALS": "VMC",
    "INTERNATIONAL PAPER": "IP", "PACKAGING OF AMERICA": "PKG", "WEYERHAEUSER": "WY", "LOEWS": "L",
    "UNION PACIFIC": "UNP", "CSX": "CSX", "NORFOLK SOUTHERN": "NSC", "GENERAL MOTORS": "GM", "FORD MOTOR": "F",
    "TESLA": "TSLA", "CATERPILLAR": "CAT", "DEERE": "DE", "3M": "MMM", "HONEYWELL": "HON", "HONEYWELL UOP": "HON", "BLACKSTONE GSO": "BX", "TYSON FOODS": "TSN",
    "ARCHER DANIELS MIDLAND": "ADM", "BUNGE": "BG", "PEPSICO": "PEP", "COCA COLA": "KO", "KRAFT HEINZ": "KHC",
    "GENERAL MILLS": "GIS", "HORMEL FOODS": "HRL", "ECOLAB": "ECL", "PPG": "PPG", "SHERWIN WILLIAMS": "SHW",
    "DUPONT DE NEMOURS": "DD", "CORTEVA": "CTVA", "ALBEMARLE": "ALB", "CELANESE": None, "BALL": "BALL",
    "AMCOR": "AMCR", "SMURFIT WESTROCK": "SW", "WESTROCK": "SW", "PROCTER AND GAMBLE": "PG", "KIMBERLY CLARK": "KMB",
    "AMAZON COM": "AMZN", "MICROSOFT": "MSFT", "ALPHABET": "GOOGL", "GOOGLE": "GOOGL", "META PLATFORMS": "META",
    "APPLE": "AAPL", "INTEL": "INTC", "MICRON": "MU", "TEXAS INSTRUMENTS": "TXN", "CORNING": "GLW",
    "EQUINIX": "EQIX", "DIGITAL REALTY": "DLR", "BOEING": "BA", "LOCKHEED MARTIN": "LMT", "GENERAL DYNAMICS": "GD",
    "RTX": "RTX", "RAYTHEON": "RTX", "NORTHROP GRUMMAN": "NOC", "GENERAL ELECTRIC": "GE", "GE VERNOVA": "GEV",
    "DELTA AIR LINES": "DAL", "UNITED AIRLINES": "UAL", "SOUTHWEST AIRLINES": "LUV", "FEDEX": "FDX",
    "UNITED PARCEL SERVICE": "UPS", "JOHNSON AND JOHNSON": "JNJ", "PFIZER": "PFE", "MERCK": "MRK", "ELI LILLY": "LLY",
    "ABBVIE": "ABBV", "AMGEN": "AMGN", "BRISTOL MYERS SQUIBB": "BMY", "THERMO FISHER SCIENTIFIC": "TMO",
    "HCA HEALTHCARE": "HCA", "CUMMINS": "CMI", "PACCAR": "PCAR", "EMERSON ELECTRIC": "EMR", "EATON": "ETN",
    "CARRIER": "CARR", "TRANE": "TT", "JOHNSON CONTROLS": "JCI", "OTIS": "OTIS", "ILLINOIS TOOL WORKS": "ITW",
    "PARKER HANNIFIN": "PH", "DOVER": "DOV", "STANLEY BLACK AND DECKER": "SWK", "MASCO": "MAS", "OWENS CORNING": None,
    "WALMART": "WMT", "COSTCO WHOLESALE": "COST", "TARGET": "TGT", "KROGER": "KR", "HOME DEPOT": "HD", "LOWE S": "LOW",
    "MCDONALD S": "MCD", "STARBUCKS": "SBUX", "MARRIOTT": "MAR", "HILTON WORLDWIDE": "HLT", "LAS VEGAS SANDS": "LVS",
    "MGM RESORTS": "MGM", "CARNIVAL": "CCL", "ROYAL CARIBBEAN CRUISES": "RCL", "DISNEY": "DIS", "WALT DISNEY": "DIS",
    "COMCAST": "CMCSA", "AT AND T": "T", "VERIZON COMMUNICATIONS": "VZ", "AMERICAN WATER WORKS": "AWK",
    "PROLOGIS": "PLD", "SIMON PROPERTY": "SPG", "IRON MOUNTAIN": "IRM", "HALLIBURTON": "HAL", "BAKER HUGHES": "BKR",
    "SLB": "SLB", "SCHLUMBERGER": "SLB", "TEXAS PACIFIC LAND": "TPL", "MOLSON COORS": "TAP", "CONSTELLATION BRANDS": "STZ",
    "BROWN FORMAN": "BF.B", "PHILIP MORRIS": "PM", "ALTRIA": "MO", "MONDELEZ": "MDLZ", "HERSHEY": "HSY",
    "J M SMUCKER": "SJM", "MCCORMICK": "MKC", "CAMPBELL": None, "CONAGRA": None, "KELLANOVA": None,
    "SYSCO": "SYY", "CINTAS": "CTAS", "AVERY DENNISON": "AVY", "IFF": "IFF", "INTERNATIONAL FLAVORS AND FRAGRANCES": "IFF",
    "NUCOR STEEL": "NUE", "SOUTHWESTERN": None, "CALPINE": "CEG", "CPN MANAGEMENT": "CEG",
}
spine_norm = {}
for c in spine:
    if not c["dual_class_duplicate"]:
        spine_norm.setdefault(norm_name(c["name"]), c["ticker"])

def match_parent(raw):
    nn = norm_name(raw)
    if nn in ALIAS: return ALIAS[nn]
    if nn in spine_norm: return spine_norm[nn]
    # prefix match on space-stripped names, both directions, min 6 chars
    flat = nn.replace(" ", "")
    if len(nn.split()) < 2: return None          # single generic token (AMERICAN, SOUTHERN, CITIZENS): no prefix match
    for sn, t in spine_norm.items():
        if len(sn.split()) < 2: continue
        sf = sn.replace(" ", "")
        if len(sf) >= 8 and len(flat) >= 8 and (flat.startswith(sf) or sf.startswith(flat)):
            return t
    return None

# Direct emissions per facility per year (supplier subparts MM/NN/PP etc. are NOT included here)
import openpyxl
DIRECT_SHEETS = ["Direct Point Emitters", "Onshore Oil & Gas Prod.", "Gathering & Boosting",
                 "Transmission Pipelines", "LDC - Direct Emissions", "SF6 from Elec. Equip."]
YEARS = [2023, 2022, 2021, 2020, 2019]
fac_em = {}                       # facility id -> {year: tCO2e}
fac_sector = {}
wb = openpyxl.load_workbook(T("2023_data_summary_spreadsheets", "ghgp_data_by_year_2023.xlsx"), read_only=True)
for sh in DIRECT_SHEETS:
    ws = wb[sh]; hdr = None
    for row in ws.iter_rows(values_only=True):
        if hdr is None:
            if row and row[0] == "Facility Id":
                hdr = list(row)
                ycol = {y: i for i, h in enumerate(hdr) for y in YEARS if h and str(h).startswith(f"{y} ")}
                scol = next((i for i, h in enumerate(hdr) if h and "Industry Type (sectors)" in str(h)), None)
            continue
        if not row or row[0] is None: continue
        fid = str(row[0]).split(".")[0]
        d = fac_em.setdefault(fid, {})
        for y, i in ycol.items():
            v = row[i]
            if v is not None: d[y] = d.get(y, 0) + float(v)
        fac_sector.setdefault(fid, str(row[scol]) if scol is not None and row[scol] else sh)
print(f"EPA GHGRP: {len(fac_em)} facilities with direct emissions; 2023 total {sum(d.get(2023,0) for d in fac_em.values())/1e6:.0f} Mt")

# facility -> parents (with ownership %)
fac_parents = collections.defaultdict(list)
for r in csv.DictReader(open(T("ghgp_data_parent_company(2023).csv"), encoding="cp1252")):
    fac_parents[r["GHGRP FACILITY ID"]].append((r["PARENT COMPANY NAME"], num(r["PARENT CO. PERCENT OWNERSHIP"]) or 100.0))

ghg = collections.defaultdict(lambda: {"y": collections.Counter(), "fac": 0, "sectors": collections.Counter()})
unmatched = collections.Counter(); audit = collections.Counter()
for fid, d in fac_em.items():
    for pname, pct in fac_parents.get(fid, []):
        t = match_parent(pname)
        if t:
            g = ghg[t]; g["fac"] += 1; g["sectors"][fac_sector.get(fid, "?")] += 1
            audit[(pname, t)] += d.get(2023, 0) * pct / 100
            for y, v in d.items(): g["y"][y] += v * pct / 100
        else:
            unmatched[pname] += d.get(2023, 0) * pct / 100
for t, g in ghg.items():
    c = by_tick[t]
    c["ghgrp_scope1_mt"] = round(g["y"][2023] / 1e6, 4)       # Mt CO2e direct, US facilities >25 kt, ownership-weighted
    c["ghgrp_scope1_2019_mt"] = round(g["y"][2019] / 1e6, 4)
    c["ghgrp_trend_5y_pct"] = round(100 * (g["y"][2023] / g["y"][2019] - 1), 1) if g["y"][2019] > 0 else None
    c["ghgrp_facilities"] = g["fac"]
    c["ghgrp_main_subsector"] = g["sectors"].most_common(1)[0][0]
    if c["revenue_b"]:
        c["ghg_intensity_t_per_musd"] = round(g["y"][2023] / (c["revenue_b"] * 1000), 1)
print(f"EPA GHGRP: matched {len(ghg)} companies, {sum(g['fac'] for g in ghg.values())} facility-parent rows")
with open(os.path.join(ROOT, "data", "ghgrp_unmatched_parents.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["parent_company", "tCO2e_2023_attributed"])
    for p, v in unmatched.most_common(300): w.writerow([p, round(v)])
with open(os.path.join(ROOT, "data", "ghgrp_matches.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["parent_company", "ticker", "matched_name", "tCO2e_2023_attributed"])
    for (p, t), v in sorted(audit.items(), key=lambda kv: (kv[0][1], -kv[1])): w.writerow([p, t, by_tick[t]["name"], round(v)])

# ---------- 6. derived + output ----------
COLS = ["ticker", "name", "rank_by_mcap", "dual_class_duplicate", "sector", "industry", "market_cap_b", "price", "revenue_b",
        "ebitda_b", "revenue_growth", "employees",
        "esg_risk_total", "esg_risk_env", "esg_risk_social", "esg_risk_gov", "esg_risk_percentile", "esg_risk_level",
        "controversy_level", "controversy_score",
        "ghgrp_scope1_mt", "ghgrp_scope1_2019_mt", "ghgrp_trend_5y_pct", "ghgrp_facilities", "ghgrp_main_subsector", "ghg_intensity_t_per_musd",
        "logo_domain", "altman_z", "piotroski_f", "esg_risk_yahoo", "decarb_target_year", "decarb_ambition_pa_pct", "decarb_coverage_pct",
        "temp_goal_c", "controversy_flags", "controversy_worst", "sdg_aligned_count",
        "report_year", "report_count", "report_e_score", "report_s_score", "report_g_score", "report_total_score",
        "ntc_climate_credit_score"]
for c in spine:
    for k in COLS: c.setdefault(k, None)
    if c["ghgrp_scope1_mt"] is None and c["sector"] and not c["dual_class_duplicate"]:
        c["ghgrp_scope1_mt_note"] = "no GHGRP facility matched (no US facility >25kt, or name unmatched)"
os.makedirs(os.path.join(ROOT, "web", "data"), exist_ok=True)
with open(os.path.join(ROOT, "web", "data", "master.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(spine)
with open(os.path.join(ROOT, "web", "data", "master.json"), "w") as f:
    json.dump({"sources": {
        "spine": "OCR'd S&P 500 list (rank, market cap, price, revenue), Sep 2026",
        "esg_risk_*": "Sustainalytics ESG Risk Ratings via Kaggle (SP 500 ESG Risk Ratings.csv, 2024)",
        "ebitda_b/revenue_growth/employees": "yfinance snapshot bundled in climate-credit-risk-analyzer (2025)",
        "ghgrp_*": "EPA GHGRP direct (Scope 1) emissions 2019-2023 from ghgp_data_by_year_2023.xlsx, attributed to parent company by ownership share from ghgp_data_parent_company(2023).csv; excludes supplier subparts",
        "logo_domain/altman_z/piotroski_f/decarb_*/temp_goal_c/controversy_flags/sdg_aligned_count": "Global Corporate ESG and Financial Dataset (Kaggle, mrbossjaysrb; Yahoo Finance and Sustainalytics fields)",
        "report_*": "NLP keyword scores of company sustainability-report PDFs (Kaggle jaidityachopra)",
    }, "companies": spine}, f, indent=1)

# coverage
live = [c for c in spine if not c["dual_class_duplicate"]]
print(f"\nMaster rows: {len(spine)} ({len(live)} after dropping dual-class duplicates)")
for k in ["sector", "esg_risk_total", "ebitda_b", "employees", "ghgrp_scope1_mt", "altman_z", "piotroski_f", "temp_goal_c", "decarb_target_year", "controversy_flags", "logo_domain"]:
    have = sum(1 for c in live if c[k] is not None)
    print(f"  {k:22s} {have:4d}/{len(live)}  ({100*have//len(live)}%)")
print("\nTop 12 GHGRP emitters (Mt CO2e, attributed):")
for c in sorted(live, key=lambda c: -(c["ghgrp_scope1_mt"] or 0))[:12]:
    print(f"  {c['ticker']:6s} {c['name'][:32]:32s} {c['ghgrp_scope1_mt']:8.2f} Mt  5y {str(c['ghgrp_trend_5y_pct']):>6s}%  {c['ghgrp_facilities']:4d} fac  {c['ghgrp_main_subsector']}")
print("\nTop unmatched GHGRP parents (Mt):")
for p, v in unmatched.most_common(15): print(f"  {v/1e6:7.2f}  {p}")
