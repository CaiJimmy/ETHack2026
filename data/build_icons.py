"""Bundle one logo per S&P 500 company into web/icons/ so the site needs no external icon service.

Order of preference per company:
  1. Google favicon service (sz=64) if it returns a real image (not the blue-globe placeholder) larger than 16 px
  2. icon.horse if it returns a real logo (not its grey generated letter)
  3. the small Google icon if that is all there is
  4. nothing -> the app draws a ticker circle
Domains: the curated DOMAINS map in web/app.js first, then the dataset's logo_domain, then a guess.
Writes web/icons/<TICKER>.png|ico and web/data/icons.json. Run: python3 data/build_icons.py
"""
import json, os, re, hashlib, struct, urllib.request, concurrent.futures as cf
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "web", "icons"); os.makedirs(OUT, exist_ok=True)
PLACEHOLDERS = set(l.strip() for l in open(os.path.join(ROOT, "data", "icon_placeholders.txt")) if l.strip())
js = open(os.path.join(ROOT, "web", "app.js")).read()
body = re.search(r"const DOMAINS = (\{[\s\S]*?\});", js).group(1)
DOMAINS = {k: v for k, v in re.findall(r'["\']?([A-Z][A-Z0-9.]*)["\']?\s*:\s*"([^"]+)"', body)}
comps = [c for c in json.load(open(os.path.join(ROOT, "web", "data", "master.json")))["companies"] if not c["dual_class_duplicate"] and c["market_cap_b"]]
def guess(name):
    n = re.sub(r"^the ", "", name.lower()); n = re.sub(r"[,.]?\s*(inc|corp|corporation|company|co|plc|ltd|group|holdings|incorporated|limited)\b.*$", "", n)
    return re.sub(r"[^a-z0-9]", "", n) + ".com"
def get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ethhack-greenrank"})
        with urllib.request.urlopen(req, timeout=25) as r: return r.status, r.read()
    except Exception as e:
        return 0, b""
def kind(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n": w, h = struct.unpack(">II", b[16:24]); return "png", min(w, h)
    if b[:4] == b"\x00\x00\x01\x00":
        n = struct.unpack("<H", b[4:6])[0]; return "ico", max((b[6 + 16 * i] or 256) for i in range(n)) if n else 0
    if b[:3] == b"\xff\xd8\xff": return "jpg", 64
    return None, 0
def best(c):
    d = DOMAINS.get(c["ticker"]) or c.get("logo_domain") or guess(c["name"])
    st, g = get(f"https://www.google.com/s2/favicons?domain={d}&sz=64")
    gk, gs = kind(g); gok = st == 200 and gk in ("png", "jpg") and hashlib.md5(g).hexdigest() not in PLACEHOLDERS
    pick = None
    if gok and gs > 16: pick = (gk, g, "google")
    else:
        st2, h = get(f"https://icon.horse/icon/{d}")
        if st2 != 200: st2, h = get(f"https://icon.horse/icon/{d}")          # one retry, the service throttles bursts
        hk, hs = kind(h)
        generated = hk == "png" and hs == 256 and len(h) < 4000        # icon.horse's grey letter tile
        hok = st2 == 200 and hk in ("png", "ico", "jpg") and not generated
        if hok and hs >= 32: pick = (hk, h, "icon.horse")
        elif gok: pick = (gk, g, "google-small")
        elif hok: pick = (hk, h, "icon.horse-small")
    if not pick: return c["ticker"], d, None, None
    ext, data, src = pick; fn = f'{c["ticker"]}.{ext}'
    open(os.path.join(OUT, fn), "wb").write(data)
    return c["ticker"], d, fn, src
res = {}; stats = {}
with cf.ThreadPoolExecutor(4) as ex:
    for t, d, fn, src in ex.map(best, comps):
        if fn: res[t] = fn
        stats[src] = stats.get(src, 0) + 1
        if not fn: print("no icon:", t, d)
json.dump(res, open(os.path.join(ROOT, "web", "data", "icons.json"), "w"), indent=0)
print(f"{len(res)} of {len(comps)} icons bundled; sources {stats}")

# Hand-checked exclusions: these domains resolve to an unrelated site's icon. Keep them as ticker circles.
WRONG = {"BRK.B", "ROP"}
res = {t: f for t, f in res.items() if t not in WRONG}
for t in WRONG:
    for ext in ("png", "ico", "jpg"):
        p = os.path.join(OUT, f"{t}.{ext}")
        if os.path.exists(p): os.remove(p)
json.dump(res, open(os.path.join(ROOT, "web", "data", "icons.json"), "w"), indent=0)
print(f"{len(res)} icons after removing hand-checked wrong ones {sorted(WRONG)}")
