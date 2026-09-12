"""Headquarters city per S&P 500 company -> lat/lon via Nominatim (OpenStreetMap).
HQ city/state/country come from the yfinance snapshot (421 companies) and the Sustainalytics address field (rest).
Writes data/hq_geocode.json cache and web/data/hq.json. Run: python3 data/build_hq.py
"""
import csv, json, os, re, time, urllib.request, urllib.parse
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
T = lambda *p: os.path.join(ROOT, "tmp", *p)
nt = lambda t: t.replace("-", ".").upper().strip()
hq = {}
for r in csv.DictReader(open(T("climate-credit-risk-analyzer-main", "climate_credit_risk_data.csv"))):
    if r["City"]: hq[nt(r["Symbol"])] = (r["City"], r["State"], r["Country"])
for r in csv.DictReader(open(T("SP 500 ESG Risk Ratings.csv"))):
    t = nt(r["Symbol"])
    if t in hq or not r["Address"]: continue
    lines = [l.strip() for l in r["Address"].split("\n") if l.strip()]
    if len(lines) >= 2:
        m = re.match(r"(.+?),\s*([A-Z]{2})\s+\d{5}", lines[-1])
        if m: hq[t] = (m.group(1), m.group(2), "United States"); continue
        hq[t] = (lines[-2] if len(lines) > 2 else lines[-1], "", lines[-1])
spine = [r for r in csv.DictReader(open(os.path.join(ROOT, "data", "sp500_ocr.csv")))]
tickers = [nt(r["Ticker"]) for r in spine]
print(f"HQ known for {sum(1 for t in tickers if t in hq)} of {len(tickers)}")

cache_p = os.path.join(ROOT, "data", "hq_geocode.json")
cache = json.load(open(cache_p)) if os.path.exists(cache_p) else {}
keys = sorted({hq[t] for t in tickers if t in hq})
for i, (city, state, country) in enumerate(keys):
    k = "|".join((city, state, country))
    if k in cache: continue
    q = ", ".join(x for x in (city, state, country) if x)
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ethhack-greenrank/0.1 (hackathon; contact via github)"})
        res = json.load(urllib.request.urlopen(req, timeout=20))
        cache[k] = [float(res[0]["lat"]), float(res[0]["lon"])] if res else None
    except Exception as e:
        cache[k] = None; print("fail", q, e)
    json.dump(cache, open(cache_p, "w"), indent=0)
    time.sleep(1.1)
    if i % 25 == 0: print(f"geocoded {i}/{len(keys)}")

out = {}
for t in tickers:
    if t not in hq: continue
    city, state, country = hq[t]; ll = cache.get("|".join(hq[t]))
    if ll: out[t] = {"city": city, "state": state, "country": country, "lat": ll[0], "lon": ll[1]}
json.dump(out, open(os.path.join(ROOT, "web", "data", "hq.json"), "w"))
print(f"wrote web/data/hq.json with {len(out)} companies; {sum(1 for v in cache.values() if v is None)} failed lookups")
