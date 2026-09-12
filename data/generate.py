"""Generate a SYNTHETIC S&P 500 sustainability dataset.

Company names, tickers, sectors and domains are real (needed for logos and
believable demo). Every metric value is random, seeded, and sector-calibrated.
Swap this file for a real pipeline (EDGAR / EPA GHGRP / Violation Tracker)
without changing the web app: keep the JSON schema.

Run:  python3 data/generate.py   -> writes web/data/companies.json
"""
import json, random, math, os

random.seed(2026)

# ticker, name, sector, domain
COMPANIES = [
 ("XOM","Exxon Mobil","Energy","exxonmobil.com"),("CVX","Chevron","Energy","chevron.com"),
 ("COP","ConocoPhillips","Energy","conocophillips.com"),("SLB","Schlumberger","Energy","slb.com"),
 ("EOG","EOG Resources","Energy","eogresources.com"),("PSX","Phillips 66","Energy","phillips66.com"),
 ("LIN","Linde","Materials","linde.com"),("SHW","Sherwin-Williams","Materials","sherwin-williams.com"),
 ("FCX","Freeport-McMoRan","Materials","fcx.com"),("NEM","Newmont","Materials","newmont.com"),
 ("DOW","Dow","Materials","dow.com"),("NUE","Nucor","Materials","nucor.com"),
 ("CAT","Caterpillar","Industrials","caterpillar.com"),("HON","Honeywell","Industrials","honeywell.com"),
 ("UNP","Union Pacific","Industrials","up.com"),("BA","Boeing","Industrials","boeing.com"),
 ("DE","Deere","Industrials","deere.com"),("GE","GE Aerospace","Industrials","geaerospace.com"),
 ("AMZN","Amazon","Consumer Discretionary","amazon.com"),("TSLA","Tesla","Consumer Discretionary","tesla.com"),
 ("HD","Home Depot","Consumer Discretionary","homedepot.com"),("MCD","McDonald's","Consumer Discretionary","mcdonalds.com"),
 ("NKE","Nike","Consumer Discretionary","nike.com"),("F","Ford","Consumer Discretionary","ford.com"),
 ("PG","Procter & Gamble","Consumer Staples","pg.com"),("KO","Coca-Cola","Consumer Staples","coca-colacompany.com"),
 ("PEP","PepsiCo","Consumer Staples","pepsico.com"),("WMT","Walmart","Consumer Staples","walmart.com"),
 ("COST","Costco","Consumer Staples","costco.com"),("MDLZ","Mondelez","Consumer Staples","mondelezinternational.com"),
 ("JNJ","Johnson & Johnson","Health Care","jnj.com"),("UNH","UnitedHealth","Health Care","unitedhealthgroup.com"),
 ("PFE","Pfizer","Health Care","pfizer.com"),("LLY","Eli Lilly","Health Care","lilly.com"),
 ("MRK","Merck","Health Care","merck.com"),("ABT","Abbott","Health Care","abbott.com"),
 ("JPM","JPMorgan Chase","Financials","jpmorganchase.com"),("BAC","Bank of America","Financials","bankofamerica.com"),
 ("GS","Goldman Sachs","Financials","goldmansachs.com"),("V","Visa","Financials","visa.com"),
 ("MA","Mastercard","Financials","mastercard.com"),("BRK.B","Berkshire Hathaway","Financials","berkshirehathaway.com"),
 ("AAPL","Apple","Information Technology","apple.com"),("MSFT","Microsoft","Information Technology","microsoft.com"),
 ("NVDA","NVIDIA","Information Technology","nvidia.com"),("INTC","Intel","Information Technology","intel.com"),
 ("CSCO","Cisco","Information Technology","cisco.com"),("ORCL","Oracle","Information Technology","oracle.com"),
 ("GOOGL","Alphabet","Communication Services","google.com"),("META","Meta","Communication Services","meta.com"),
 ("NFLX","Netflix","Communication Services","netflix.com"),("DIS","Disney","Communication Services","disney.com"),
 ("VZ","Verizon","Communication Services","verizon.com"),("T","AT&T","Communication Services","att.com"),
 ("NEE","NextEra Energy","Utilities","nexteraenergy.com"),("DUK","Duke Energy","Utilities","duke-energy.com"),
 ("SO","Southern Company","Utilities","southerncompany.com"),("AEP","American Electric Power","Utilities","aep.com"),
 ("EXC","Exelon","Utilities","exeloncorp.com"),("XEL","Xcel Energy","Utilities","xcelenergy.com"),
 ("PLD","Prologis","Real Estate","prologis.com"),("AMT","American Tower","Real Estate","americantower.com"),
 ("EQIX","Equinix","Real Estate","equinix.com"),("SPG","Simon Property","Real Estate","simon.com"),
 ("O","Realty Income","Real Estate","realtyincome.com"),("WELL","Welltower","Real Estate","welltower.com"),
]

# Sector calibration: (ghg intensity tCO2e/$M rev, revenue $B median, margin, water intensity m3/$M)
SECTOR = {
 "Energy":                 (600, 120, 0.12, 900),
 "Materials":              (900,  25, 0.14, 1500),
 "Industrials":            (150,  40, 0.13, 200),
 "Consumer Discretionary": ( 60,  90, 0.09, 150),
 "Consumer Staples":       ( 80,  80, 0.10, 400),
 "Health Care":            ( 30,  60, 0.20, 120),
 "Financials":             (  5,  70, 0.30, 20),
 "Information Technology": ( 15, 100, 0.28, 60),
 "Communication Services": ( 20,  90, 0.22, 50),
 "Utilities":              (2500, 22, 0.18, 6000),
 "Real Estate":            ( 50,   6, 0.35, 300),
}

def lognorm(median, sigma):
    return median * math.exp(random.gauss(0, sigma))

def maybe_missing(v, p):
    """Return None with probability p (simulates non-reporting)."""
    return None if random.random() < p else round(v, 2)

rows = []
for t, name, sector, domain in COMPANIES:
    gi, rev_med, margin, wi = SECTOR[sector]
    revenue = lognorm(rev_med, 0.6)
    intensity = lognorm(gi, 0.5)
    scope12 = intensity * revenue            # tCO2e (revenue in $B -> $M x1000 cancels: keep units simple)
    rows.append({
        "ticker": t, "name": name, "sector": sector, "domain": domain,
        "financial": {
            "revenueB": round(revenue, 1),
            "marketCapB": round(revenue * lognorm(3, 0.7), 1),
            "ebitB": round(revenue * max(0.02, random.gauss(margin, 0.04)), 2),
            "return5y": round(random.gauss(60, 45), 1),
            "pe": round(lognorm(22, 0.4), 1),
        },
        "env": {
            "ghgIntensity": round(intensity, 1),           # tCO2e per $M revenue
            "scope12Mt": round(scope12 / 1000, 3),         # Mt CO2e
            "scope3Reported": random.random() < 0.6,
            "renewableShare": maybe_missing(min(100, max(0, random.gauss(35, 25))), 0.15),
            "waterIntensity": maybe_missing(lognorm(wi, 0.6), 0.25),
            "netZeroTarget": random.choice([2030, 2040, 2050, 2050, None]),
        },
        "social": {
            "injuryRate": maybe_missing(lognorm(1.2, 0.6), 0.2),   # TRIR per 100 FTE
            "penaltiesM": round(lognorm(8, 1.5) if random.random() < 0.7 else 0, 1),  # $M, Violation Tracker
            "genderPayGap": maybe_missing(random.gauss(8, 5), 0.3),  # %
        },
        "gov": {
            "boardIndependence": round(min(100, max(40, random.gauss(82, 8))), 0),
            "ceoPayRatio": round(lognorm(250, 0.7), 0),
            "climateInProxy": random.random() < 0.55,
        },
        "meta": {"source": "SYNTHETIC (seed 2026)", "asOf": "2025-12-31"},
    })

out = os.path.join(os.path.dirname(__file__), "..", "web", "data", "companies.json")
with open(out, "w") as f:
    json.dump({"generated": "synthetic", "companies": rows}, f, indent=1)
print(f"wrote {len(rows)} companies -> {out}")
