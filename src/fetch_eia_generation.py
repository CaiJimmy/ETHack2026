"""EIA-923 annual net generation per power plant, 2015 through the latest published year.

This is the denominator for the PAB Article 12(1)(d) test. That rule excludes a company deriving
50% or more of revenue from electricity generation whose generation-weighted carbon intensity is
above 100 gCO2e/kWh. EPA CAMD gives measured CO2 mass per ORIS unit; this gives the MWh those units
produced. EIA's plantCode is the ORIS code, so camd_unit_year.oris_code joins straight onto
eia_plant_totals.plant_code with no name matching anywhere.

Outputs:
  data/interim/eia_plant_generation.parquet  every row the API returns, with a row_level label
  data/interim/eia_plant_totals.parquet      one row per (plant_code, year), the denominator
  data/interim/provenance/eia_generation.json

WHICH ROWS TO USE, because this is where the numbers go wrong
------------------------------------------------------------
The API returns the same generation three times, at three levels of one hierarchy:

  fuel2002=ALL  fuelType=ALL  primeMover=ALL   plant total          row_level='plant_total'
  fuel2002=NG   fuelType=NG   primeMover=ALL   subtotal by fuel     row_level='fuel_subtotal'
  fuel2002=NG   fuelType=NG   primeMover=CT    leaf                 row_level='fuel_prime_mover'

For 2024 each level sums to 4,325.0 TWh on its own. Summing the file without filtering gives
12,975 TWh, three times US net generation. So:

  denominator for carbon intensity   -> eia_plant_totals.parquet, or row_level == 'plant_total'
  fuel mix, coal share, gas share    -> row_level == 'fuel_subtotal'
  technology detail                  -> row_level == 'fuel_prime_mover'

Never mix two levels in one sum.

ONE ROW IS NOT A PLANT
----------------------
plantCode 99999, "State-Fuel Level Increment", is EIA's imputed residual for plants that file
annually and have not been processed yet. It carries no ORIS code and must never be joined to CAMD.
is_real_plant is False on exactly that row and True everywhere else. The increment is 0.0-0.5% of
national generation for 2015-2024, but 12.2% in 2025, because the 2025 annual release names only
3,442 plants against 2024's 13,257. So 2025 is sound as a national total and thin at plant level;
the intensity calculation should run on 2024.

fuelType is the aggregated fuel category and fuel_2002 the detailed code beneath it: bituminous and
subbituminous coal are two fuel_2002 values sharing fuelType='COL'. The row key therefore needs
fuel_2002; (plant_code, year, fuel_type, prime_mover) alone collides on 467 rows in 2024.

Why unfaceted paging rather than faceting by state: the whole 2015-2025 window is 399,709 rows and
the API caps a page at 5,000, so paging costs about 80 requests. Faceting by state would cost at
least 51 states times 11 years = 561 requests for the same rows. Unfaceted wins by 6x.
"""

import hashlib
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "eia"
INTERIM = ROOT / "data" / "interim"
PROV_PATH = INTERIM / "provenance" / "eia_generation.json"

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
API = "https://api.eia.gov/v2/electricity/facility-fuel/data/"
API_KEY = os.environ.get("EIA_API_KEY")

FIRST_YEAR = 2015
LAST_YEAR = datetime.now(timezone.utc).year  # probed downwards; years with no annual data are skipped

PAGE = 5000  # the API silently truncates anything larger

# EIA's placeholder for generation it has not yet attributed to a named plant. Not an ORIS code.
INCREMENT_PLANT_CODE = 99999

LICENCE = "US federal government work, public domain (17 U.S.C. 105). Form EIA-923."
REDISTRIBUTION = (
    "Public domain. We may publish derived numbers, tables and charts, citing the US Energy "
    "Information Administration Form EIA-923 and the retrieval date."
)

# Utility-scale US net generation, 2024. EIA's own Electric Power Annual puts it at about 4,300 TWh.
# A run landing at three times this means the row_level filter was dropped somewhere.
CHECK_YEAR = 2024
CHECK_TWH_LOW, CHECK_TWH_HIGH = 4_000, 4_600

session = requests.Session()
session.headers.update({"User-Agent": UA})

provenance = {}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_existing_provenance():
    if not PROV_PATH.exists():
        return
    try:
        for rec in json.loads(PROV_PATH.read_text()):
            provenance[rec["url"]] = rec
    except (ValueError, KeyError):
        pass


def build_url(params, mask):
    """Return the request URL. With mask=True the key is replaced, for anything written to disk."""
    key = "<api_key>" if mask else API_KEY
    return API + "?" + urllib.parse.urlencode([("api_key", key)] + list(params))


def scrub(body):
    """Blank the key EIA echoes back inside the response body.

    Every response carries request.params.api_key with the live key in it. Caching that verbatim
    would leave 86 copies of a working credential on disk, so it is replaced before anything is
    written and the recorded sha256 is the hash of the scrubbed file.
    """
    params = body.get("request", {}).get("params", {})
    if params.get("api_key") not in (None, "<api_key>"):
        params["api_key"] = "<api_key>"
        return True
    return False


def record(shown_url, dest, http_status, from_cache):
    blob = dest.read_bytes()
    prior = provenance.get(shown_url, {})
    provenance[shown_url] = {
        "url": shown_url,
        "retrieved_at": prior.get("retrieved_at") if from_cache and prior else _now(),
        "http_status": prior.get("http_status") if from_cache and prior else http_status,
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "local_path": str(dest.relative_to(ROOT)),
        "licence": LICENCE,
        "redistribution": REDISTRIBUTION,
        "served_from_cache_this_run": from_cache,
    }


def fetch_page(params, dest):
    """Fetch one page to dest, reusing dest if it already holds bytes. A second run hits no network."""
    shown = build_url(params, mask=True)
    if dest.exists() and dest.stat().st_size > 0:
        body = json.loads(dest.read_text())
        # A file cached by an older run still holds the echoed key, so scrub it in place.
        if scrub(body):
            dest.write_text(json.dumps(body))
        record(shown, dest, None, from_cache=True)
        return body

    url = build_url(params, mask=False)
    delay = 2.0
    for attempt in range(6):
        resp = session.get(url, timeout=300)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", delay))
            print(f"  rate limited, sleeping {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 2, 120)
            continue
        if resp.status_code >= 500:
            print(f"  HTTP {resp.status_code}, retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 120)
            continue
        if resp.status_code != 200:
            # The body can echo the key back in an error message, so only the status is shown.
            raise SystemExit(f"EIA returned HTTP {resp.status_code} for {shown}")
        body = resp.json()
        if "response" not in body:
            raise SystemExit(f"EIA returned no response block for {shown}")
        scrub(body)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(body))
        record(shown, dest, resp.status_code, from_cache=False)
        time.sleep(0.4)  # the published limit is vague, so stay well under a request per second
        return body

    raise SystemExit(f"gave up on {shown} after repeated rate limiting")


def year_params(year, offset):
    return [
        ("frequency", "annual"),
        ("data[0]", "generation"),
        ("start", str(year)),
        ("end", str(year)),
        # Offset paging over an unsorted result set can skip and repeat rows, so the sort is explicit.
        ("sort[0][column]", "plantCode"),
        ("sort[0][direction]", "asc"),
        ("offset", str(offset)),
        ("length", str(PAGE)),
    ]


def download_year(year):
    """Page through one year. Returns the raw row dicts, or None if the year is not published."""
    first = fetch_page(year_params(year, 0), RAW / f"facility_fuel_annual_{year}_p000.json")
    total = int(first["response"]["total"])
    if total == 0:
        print(f"  {year}: no annual data published")
        return None

    rows = list(first["response"]["data"])
    pages = (total + PAGE - 1) // PAGE
    for p in range(1, pages):
        body = fetch_page(year_params(year, p * PAGE), RAW / f"facility_fuel_annual_{year}_p{p:03d}.json")
        rows.extend(body["response"]["data"])

    if len(rows) != total:
        raise SystemExit(f"{year}: API said {total:,} rows, paging collected {len(rows):,}")
    print(f"  {year}: {pages} pages, {len(rows):,} rows")
    return rows


def download_all():
    print(f"EIA-923 annual facility generation, {FIRST_YEAR}-{LAST_YEAR}")
    by_year = {}
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        rows = download_year(year)
        if rows:
            by_year[year] = rows
    print(f"  years with data: {min(by_year)}-{max(by_year)}")
    print(f"  raw rows across all years: {sum(len(v) for v in by_year.values()):,}")
    return by_year


def label_level(df):
    """Name the hierarchy level of every row so downstream sums cannot cross levels by accident."""
    total = df["fuel_2002"].eq("ALL")
    subtotal = ~total & df["prime_mover"].eq("ALL")
    level = pd.Series("fuel_prime_mover", index=df.index, dtype="string")
    level[subtotal] = "fuel_subtotal"
    level[total] = "plant_total"
    return level


def build_generation(by_year):
    print("\nbuilding the plant-fuel table")
    df = pd.DataFrame([r for rows in by_year.values() for r in rows])
    print(f"  raw rows: {len(df):,}")

    df = df.rename(columns={
        "period": "year",
        "plantCode": "plant_code",
        "plantName": "plant_name",
        "fuel2002": "fuel_2002",
        "fuelType": "fuel_type",
        "fuelTypeDescription": "fuel_type_description",
        "primeMover": "prime_mover",
        "generation": "generation_mwh",
        "stateDescription": "state_description",
    })

    df["year"] = pd.to_numeric(df["year"]).astype("int16")
    codes = pd.to_numeric(df["plant_code"], errors="coerce")
    bad = codes.isna().sum()
    if bad:
        # An ORIS code that will not parse cannot be joined to CAMD, so it is dropped and counted
        # rather than carried as a string that silently matches nothing.
        print(f"  dropping {bad:,} rows whose plantCode is not numeric")
        df = df[codes.notna()]
        codes = codes[codes.notna()]
    df["plant_code"] = codes.astype("int32")

    df["generation_mwh"] = pd.to_numeric(df["generation_mwh"], errors="coerce")
    print(f"  null generation_mwh: {df['generation_mwh'].isna().sum():,}")

    for col in ("plant_name", "state", "state_description", "fuel_2002", "fuel_type",
                "fuel_type_description", "prime_mover"):
        df[col] = df[col].astype("string")

    df["row_level"] = label_level(df)
    df["is_real_plant"] = df["plant_code"].ne(INCREMENT_PLANT_CODE)

    key = ["plant_code", "year", "fuel_2002", "fuel_type", "prime_mover"]
    dupes = df.duplicated(key).sum()
    if dupes:
        print(f"  WARNING: {dupes:,} duplicate rows on {key}, keeping the first of each")
        df = df.drop_duplicates(key)

    order = ["plant_code", "plant_name", "state", "state_description", "year",
             "fuel_type", "fuel_type_description", "fuel_2002", "prime_mover",
             "row_level", "is_real_plant", "generation_mwh"]
    df = df[order].sort_values(["year", "plant_code", "fuel_2002", "prime_mover"]).reset_index(drop=True)
    print(f"  rows: {len(df):,}")
    print(f"  {df['row_level'].value_counts().to_dict()}")
    return df


def build_totals(df):
    """One row per plant and year: the reported plant total, plus the fuel that dominated it."""
    print("\nbuilding the plant totals table")
    tot = df[df["row_level"] == "plant_total"].copy()
    tot = tot[["plant_code", "plant_name", "state", "state_description", "year",
               "is_real_plant", "generation_mwh"]]

    dupes = tot.duplicated(["plant_code", "year"]).sum()
    if dupes:
        raise SystemExit(f"{dupes} plants carry more than one plant_total row")

    fuels = df[df["row_level"] == "fuel_subtotal"]

    # The dominant fuel decides whether a plant is a fossil generator at all, which is the first
    # half of the PAB 12(1)(d) test. Ranking is on the raw MWh: pumped storage reports negative net
    # generation, and a negative should never be allowed to look like the biggest contributor.
    ranked = fuels.sort_values("generation_mwh", ascending=False)
    top = ranked.drop_duplicates(["plant_code", "year"])[
        ["plant_code", "year", "fuel_type", "generation_mwh"]
    ].rename(columns={"fuel_type": "top_fuel_type", "generation_mwh": "top_fuel_mwh"})

    counts = fuels.groupby(["plant_code", "year"], as_index=False).agg(
        fuel_types=("fuel_type", "nunique"),
        fuel_subtotal_mwh=("generation_mwh", "sum"),
    )

    out = tot.merge(counts, on=["plant_code", "year"], how="left")
    out = out.merge(top, on=["plant_code", "year"], how="left")

    # Reconciliation travels with the table so a downstream reader can see the gap rather than
    # trust it. Nothing is rewritten: generation_mwh stays exactly what EIA reported.
    out["reconciliation_mwh"] = out["generation_mwh"] - out["fuel_subtotal_mwh"]
    out["top_fuel_share"] = (out["top_fuel_mwh"] / out["generation_mwh"]).where(
        out["generation_mwh"] > 0
    )

    order = ["plant_code", "plant_name", "state", "state_description", "year", "is_real_plant",
             "generation_mwh", "fuel_types", "top_fuel_type", "top_fuel_mwh", "top_fuel_share",
             "fuel_subtotal_mwh", "reconciliation_mwh"]
    out = out[order].sort_values(["year", "plant_code"]).reset_index(drop=True)
    print(f"  plant-year rows: {len(out):,}")
    print(f"  distinct plants: {out['plant_code'].nunique():,}")
    print(f"  rows for the state-fuel increment rather than a real plant: {(~out['is_real_plant']).sum():,}")
    print(f"  plants with no fuel subtotal rows: {out['fuel_subtotal_mwh'].isna().sum():,}")
    off = out["reconciliation_mwh"].abs() > 1
    print(f"  plant-years where the total and the fuel subtotals differ by over 1 MWh: {off.sum():,}")
    return out


def report(df, totals):
    print("\n  year     rows    plants   plant_total TWh   fuel_subtotal TWh   leaf TWh")
    for year, g in df.groupby("year"):
        lv = g.groupby("row_level")["generation_mwh"].sum() / 1e6
        print(f"  {year}  {len(g):7,}  {g['plant_code'].nunique():8,}   "
              f"{lv.get('plant_total', 0):15,.1f}   {lv.get('fuel_subtotal', 0):17,.1f}   "
              f"{lv.get('fuel_prime_mover', 0):8,.1f}")

    print("\n  year   named plants   named TWh   increment TWh   increment share")
    for year, g in totals.groupby("year"):
        real = g[g["is_real_plant"]]
        inc = g.loc[~g["is_real_plant"], "generation_mwh"].sum() / 1e6
        tt = g["generation_mwh"].sum() / 1e6
        print(f"  {year}   {len(real):12,}   {real['generation_mwh'].sum() / 1e6:9,.1f}   "
              f"{inc:13,.1f}   {100 * inc / tt:14.1f}%")

    chk = totals[totals["year"] == CHECK_YEAR]["generation_mwh"].sum() / 1e6
    naive = df[df["year"] == CHECK_YEAR]["generation_mwh"].sum() / 1e6
    print(f"\n  {CHECK_YEAR} US net generation, plant totals only: {chk:,.1f} TWh")
    print(f"  {CHECK_YEAR} the same file summed without a row_level filter: {naive:,.1f} TWh "
          f"({naive / chk:.1f}x, which is the double counting this table is labelled to prevent)")
    assert CHECK_TWH_LOW <= chk <= CHECK_TWH_HIGH, (
        f"{CHECK_YEAR} net generation came out at {chk:,.1f} TWh, outside the expected "
        f"{CHECK_TWH_LOW:,}-{CHECK_TWH_HIGH:,} TWh"
    )

    latest = int(totals["year"].max())
    last = totals[totals["year"] == latest]
    inc_share = last.loc[~last["is_real_plant"], "generation_mwh"].sum() / last["generation_mwh"].sum()
    if inc_share > 0.02:
        print(f"\n  NOTE: {latest} is an early annual release. The national total holds, but "
              f"{100 * inc_share:.1f}% of it sits in the unattributed state-fuel increment, so "
              f"plant-level coverage is thin. Run the intensity test on {CHECK_YEAR}.")

    fossil = ["COL", "NG", "PET", "OOG", "PC"]
    real = totals[totals["is_real_plant"] & (totals["year"] == CHECK_YEAR)]
    f24 = real[real["top_fuel_type"].isin(fossil)]
    print(f"\n  {CHECK_YEAR} named plants whose dominant fuel is fossil: {len(f24):,}, "
          f"{f24['generation_mwh'].sum() / 1e6:,.1f} TWh of "
          f"{real['generation_mwh'].sum() / 1e6:,.1f} TWh across all named plants")


def main():
    if not API_KEY:
        raise SystemExit("EIA_API_KEY is not set; the devshell should have sourced .env")

    RAW.mkdir(parents=True, exist_ok=True)
    PROV_PATH.parent.mkdir(parents=True, exist_ok=True)
    load_existing_provenance()

    by_year = download_all()
    df = build_generation(by_year)
    totals = build_totals(df)
    report(df, totals)

    gen_path = INTERIM / "eia_plant_generation.parquet"
    tot_path = INTERIM / "eia_plant_totals.parquet"
    df.to_parquet(gen_path, index=False)
    totals.to_parquet(tot_path, index=False)

    PROV_PATH.write_text(json.dumps(list(provenance.values()), indent=2) + "\n")
    print(f"\nwrote {gen_path} ({len(df):,} rows)")
    print(f"wrote {tot_path} ({len(totals):,} rows)")
    print(f"wrote {PROV_PATH} ({len(provenance)} urls)")


if __name__ == "__main__":
    sys.exit(main())
