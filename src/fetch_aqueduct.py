"""WRI Aqueduct 4.0 water risk, joined to EPA GHGRP facilities by point-in-polygon.

The premise of the whole project is that we only score what a company files under legal penalty or
what a regulator measures. Water fits: the facility coordinates come from EPA GHGRP filings, which
are mandatory, and the water stress of the basin under those coordinates is a WRI hydrological model
that the company has no say in. Nobody self-reports a number anywhere in this file.

Aqueduct geometries are the union of a HydroBASINS level-6 sub-basin, a GADM level-1 province and a
WHYMAP aquifer, keyed by string_id. The future projections are basin only, keyed by pfaf_id, so the
forward cut is joined back on pfaf_id rather than by a second spatial join.

Outputs:
  data/interim/water_facility.parquet    one row per GHGRP facility, its basin and its water risk
  data/interim/water_by_ticker.parquet   rolled up to S&P 500 ticker three ways
  data/interim/provenance/aqueduct.json  source, licence, indicator codebook, join diagnostics
"""

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import Geod
from shapely.ops import nearest_points

ROOT = Path(__file__).resolve().parent.parent
RAW_ZIP = ROOT / "data/raw/aqueduct-4-0-water-risk-data.zip"
RAW_DIR = ROOT / "data/raw/aqueduct"
INTERIM = ROOT / "data/interim"
PROV = INTERIM / "provenance"

BUNDLE = "Aqueduct40_waterrisk_download_Y2023M07D05"
GDB = RAW_DIR / BUNDLE / "GDB/Aq40_Y2023D07M05.gdb"
CSV_BASE = RAW_DIR / BUNDLE / "CVS/Aqueduct40_baseline_annual_y2023m07d05.csv"
CSV_FUT = RAW_DIR / BUNDLE / "CVS/Aqueduct40_future_annual_y2023m07d05.csv"

SOURCE_URL = "https://www.wri.org/data/aqueduct-global-maps-40-data"
DICT_URL = "https://github.com/wri/Aqueduct40/blob/master/data_dictionary_water-risk-atlas.md"
LICENCE = (
    "CC BY 4.0. Cite: Kuzma, S., M.F.P. Bierkens, S. Lakshman, T. Luo, L. Saccoccia, "
    "E. H. Sutanudjaja, and R. Van Beek. 2023. 'Aqueduct 4.0: Updated decision-relevant global "
    "water risk indicators.' Technical Note. Washington, DC: World Resources Institute. "
    "doi.org/10.46830/writn.23.00061"
)

# Confirmed against the Aqueduct 4.0 Water Risk Atlas data dictionary, not from memory. The label
# text in the CSV carries the thresholds and agrees with this, which is the check that matters.
INDICATORS = {
    "bws": "Baseline water stress: withdrawals as a share of available renewable surface and "
           "groundwater supply. Extremely High is >80%.",
    "bwd": "Baseline water depletion: the share of available water consumed, not merely withdrawn. "
           "Extremely High is >75%.",
    "iav": "Interannual variability: year to year variation in water supply.",
    "sev": "Seasonal variability: within-year variation in water supply.",
    "gtd": "Groundwater table decline: rate of decline of the water table in cm per year. "
           "Extremely High is >8 cm/y.",
    "rfr": "Riverine flood risk: expected annual share of population affected by river flooding.",
    "cfr": "Coastal flood risk: expected annual share of population affected by coastal flooding.",
    "drr": "Drought risk: composite of drought hazard, exposure and vulnerability, 0 to 1.",
    "ucw": "Untreated connected wastewater: share of collected wastewater that is not treated.",
    "cep": "Coastal eutrophication potential: nutrient loading delivered to coastal waters.",
    "udw": "Unimproved or no drinking water: share of population without improved drinking water.",
    "usa": "Unimproved or no sanitation: share of population without improved sanitation.",
    "rri": "Peak RepRisk country ESG risk index.",
    "w_awr_def_tot": "Weighted aggregated water risk, default weighting, overall. A 0 to 5 "
                     "composite of the 13 indicators.",
}
SUFFIXES = {
    "_raw": "raw value, units per indicator",
    "_score": "indicator mapped to a 0 to 5 scale",
    "_cat": "integer category -1 to 4 (-1 and -9999 are special, see notes)",
    "_label": "human readable category with its threshold",
}
# Two traps in this data, both of which would put a wrong number on a slide.
CAT_NOTES = {
    "bws_cat = -1": "Arid and Low Water Use. bws_score is 5.0, the maximum, but the label is not "
                    "'Extremely High'. Counted separately here, never folded into the high stress "
                    "share.",
    "gtd_cat = -9999": "Insignificant Trend, which is a real finding and not missing data. 60,244 "
                       "of 68,510 basin rows. gtd_score is also -9999 there, so it must be masked "
                       "before any mean.",
    "other -9999": "No Data. Masked everywhere.",
}

# Physical water indicators we carry through to the facility table.
KEEP_CODES = ["bws", "bwd", "iav", "sev", "gtd", "rfr", "cfr", "drr", "ucw", "w_awr_def_tot"]
KEEP_COLS = [f"{c}{s}" for c in KEEP_CODES for s in ("_score", "_cat", "_label")]

# The forward cut. Business as usual is SSP3 RCP7.0, the middle of the road path, which is the one
# to quote when the point is "this is what happens if nothing changes".
FUT_SCENARIO = "bau"
FUT_YEARS = ["30", "50"]
FLEET_YEAR = 2023  # latest GHGRP reporting year, the current fleet


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract():
    """Unpack the bundle once. The zip is the retrieved artefact; these are a cache of it."""
    if CSV_BASE.exists() and GDB.exists() and CSV_FUT.exists():
        print(f"extract: cache present under {RAW_DIR}")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RAW_ZIP) as z:
        z.extractall(RAW_DIR)
    print(f"extract: unpacked {RAW_ZIP.name} to {RAW_DIR}")


def mask_nodata(df, cols):
    """-9999 means No Data in every score column. Turn it into NaN so no mean silently uses it."""
    for c in cols:
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
            n_bad = int((df[c] <= -9998).sum())
            if n_bad:
                df.loc[df[c] <= -9998, c] = np.nan
    return df


def load_basins():
    """Basin polygons from the GDB, attributes from the CSV, joined on string_id.

    The GDB carries the same 231 attribute columns as the CSV, but reading geometry plus four key
    columns and then joining the CSV is both faster and makes the join explicit, so a mismatch
    between the two files shows up as a failed join instead of being papered over.
    """
    layers = pyogrio.list_layers(str(GDB))
    print(f"gdb layers: {[list(r) for r in layers]}")
    # baseline_annual is the only layer whose geometry is the basin x province x aquifer union that
    # string_id keys. baseline_monthly and future_annual are basin only and carry no admin split.
    geo = gpd.read_file(
        GDB, layer="baseline_annual", columns=["string_id", "pfaf_id", "gid_1", "aqid"],
        engine="pyogrio", use_arrow=True,
    )
    print(f"geometry: {len(geo):,} polygons, crs {geo.crs}, "
          f"{geo.string_id.nunique():,} unique string_id")

    usecols = ["string_id", "pfaf_id", "gid_1", "aqid", "gid_0", "name_0", "name_1",
               "area_km2"] + KEEP_COLS
    attrs = pd.read_csv(CSV_BASE, usecols=usecols, low_memory=False)
    print(f"baseline annual csv: {len(attrs):,} rows, {attrs.string_id.nunique():,} unique string_id")
    dupes = attrs.string_id.duplicated().sum()
    if dupes:
        # Four byte-identical rows for basin 353020 in Russia. Nothing in the US touches them.
        attrs = attrs.drop_duplicates(subset="string_id")
        print(f"baseline annual csv: dropped {dupes} exact duplicate string_id rows, "
              f"{len(attrs):,} remain")

    attrs = mask_nodata(attrs, [c for c in attrs.columns if c.endswith("_score")])
    # -9999 in a category column means No Data for every indicator except gtd, where it means
    # Insignificant Trend. That is a real finding, so gtd_cat keeps its -9999 and the code that
    # reads it tests for cat >= 2, which is False for -9999 and needs no imputation.
    attrs = mask_nodata(attrs, [c for c in attrs.columns
                                if c.endswith("_cat") and not c.startswith("gtd")])

    # -9999 is the pfaf sentinel for geometries with no HydroBASINS parent, mostly small islands.
    # It must not survive into the join to the future projections, which are keyed on pfaf_id.
    n_nopfaf = int((attrs.pfaf_id < 0).sum())
    attrs.loc[attrs.pfaf_id < 0, "pfaf_id"] = np.nan
    print(f"baseline annual csv: {n_nopfaf:,} rows have no HydroBASINS pfaf_id, set to null")

    basins = geo[["string_id", "geometry"]].merge(attrs, on="string_id", how="left", validate="1:1")
    missing = basins["bws_label"].isna().sum()
    print(f"basins joined: {len(basins):,} polygons, {missing:,} with no CSV attribute row")
    return basins


def load_future():
    """Projected water stress by basin. Keyed by pfaf_id, no admin split."""
    cols = ["pfaf_id"] + [f"{FUT_SCENARIO}{y}_ws_x_{t}" for y in FUT_YEARS for t in ("s", "c", "l")]
    fut = pd.read_csv(CSV_FUT, usecols=cols, low_memory=False)
    print(f"future annual csv: {len(fut):,} rows, {fut.pfaf_id.nunique():,} unique pfaf_id")
    fut = fut.drop_duplicates(subset="pfaf_id")
    fut = mask_nodata(fut, [c for c in fut.columns if c.endswith("_x_s")])
    ren = {}
    for y in FUT_YEARS:
        for t, name in (("s", "score"), ("c", "cat"), ("l", "label")):
            ren[f"{FUT_SCENARIO}{y}_ws_x_{t}"] = f"ws_{FUT_SCENARIO}20{y}_{name}"
    return fut.rename(columns=ren)


def load_facilities():
    """One row per GHGRP facility id, at its most recent reported coordinates."""
    fac = pd.read_parquet(INTERIM / "ghgrp_facilities.parquet")
    print(f"ghgrp facilities: {len(fac):,} facility-year-parent rows, "
          f"{fac.facility_id.nunique():,} unique facility ids, "
          f"years {fac.year.min()} to {fac.year.max()}")

    # One row per facility per year first, then the latest year. The parent fan-out is handled in
    # the rollup, not here.
    per_year = fac.drop_duplicates(subset=["facility_id", "year"])
    per_year = per_year.sort_values(["facility_id", "year"])
    latest = per_year.groupby("facility_id", as_index=False).tail(1).copy()
    latest = latest.rename(columns={"year": "latest_year"})
    print(f"deduplicated to {len(latest):,} facilities at their most recent coordinates")

    # The primary parent is the largest ownership share in the latest year. The facility table needs
    # one name on it; every parent link is used in the rollup.
    par = fac.merge(
        latest[["facility_id", "latest_year"]],
        left_on=["facility_id", "year"], right_on=["facility_id", "latest_year"], how="inner",
    )
    par = par.sort_values(["facility_id", "ownership_frac"], ascending=[True, False])
    primary = par.groupby("facility_id", as_index=False).head(1)[
        ["facility_id", "parent_name_clean", "n_parents"]
    ]
    latest = latest.drop(columns=["parent_name_clean", "n_parents"]).merge(
        primary, on="facility_id", how="left"
    )

    # Coordinate hygiene before anything is projected. EPA coordinates are filer-entered.
    lat, lon = latest["latitude"], latest["longitude"]
    bad_null = lat.isna() | lon.isna()
    bad_zero = (lat.abs() < 1e-9) & (lon.abs() < 1e-9)
    bad_range = (lat.abs() > 90) | (lon.abs() > 180)
    print(f"coordinates: {int(bad_null.sum())} null, {int(bad_zero.sum())} at (0,0), "
          f"{int(bad_range.sum())} out of range")
    latest["coord_flag"] = np.where(
        bad_null, "null", np.where(bad_zero, "zero", np.where(bad_range, "out_of_range", "ok"))
    )
    return latest


def spatial_join(fac, basins):
    """Point in polygon, then a nearest fallback for the ones that miss, then a look at the rest."""
    ok = fac[fac.coord_flag == "ok"].copy()
    print(f"spatial join: {len(ok):,} facilities with usable coordinates, "
          f"{len(fac) - len(ok):,} excluded on coordinate flags")

    pts = gpd.GeoDataFrame(
        ok, geometry=gpd.points_from_xy(ok.longitude, ok.latitude), crs="EPSG:4326"
    )
    hit = gpd.sjoin(pts[["facility_id", "geometry"]], basins[["string_id", "geometry"]],
                    how="inner", predicate="within")
    multi = hit.facility_id.duplicated().sum()
    if multi:
        # Shared boundaries. Aqueduct polygons partition the land surface, so this is slivers.
        print(f"spatial join: {multi} facilities matched more than one polygon, keeping the first")
        hit = hit.drop_duplicates(subset="facility_id")
    print(f"spatial join: {len(hit):,} facilities fell inside a basin polygon")

    inside = set(hit.facility_id)
    miss = pts[~pts.facility_id.isin(inside)].copy()
    print(f"spatial join: {len(miss):,} facilities fell outside every polygon")

    near = pd.DataFrame(columns=["facility_id", "string_id", "dist_km"])
    if len(miss):
        n = gpd.sjoin_nearest(
            miss[["facility_id", "geometry"]], basins[["string_id", "geometry"]],
            how="left", distance_col="dist_deg",
        ).drop_duplicates(subset="facility_id")
        # sjoin_nearest ranks by degrees, which is fine for picking the candidate but is not a
        # distance. Measure the real one on the ellipsoid so the 10 km cutoff below means 10 km.
        geod = Geod(ellps="WGS84")
        bgeom = basins.set_index("string_id").geometry
        dists = []
        for pt, sid in zip(n.geometry, n.string_id):
            a, b = nearest_points(pt, bgeom.loc[sid])
            dists.append(geod.inv(a.x, a.y, b.x, b.y)[2] / 1000.0)
        n["dist_km"] = dists
        near = n[["facility_id", "string_id", "dist_km"]]
        print("geodesic distance to the nearest basin polygon, for the misses:")
        print(near["dist_km"].describe().to_string())

    # Anything within 10 km of a basin is a coastline or a coordinate rounded to the wrong side of
    # one. Anything further out is genuinely offshore and gets no water stress, not a guessed one.
    TOL_KM = 10.0
    accept = near[near.dist_km <= TOL_KM]
    reject = near[near.dist_km > TOL_KM]
    print(f"nearest fallback: {len(accept):,} accepted within {TOL_KM:.0f} km of a basin, "
          f"{len(reject):,} left unassigned")

    if len(reject):
        look = fac.merge(reject, on="facility_id", how="inner").nlargest(
            10, "dist_km"
        )[["facility_id", "facility_name", "state", "latitude", "longitude", "dist_km"]]
        print("furthest unassigned facilities:")
        print(look.to_string(index=False))
        print("unassigned by state:")
        print(fac.merge(reject, on="facility_id")["state"].value_counts().head(12).to_string())

    assign = pd.concat([
        hit[["facility_id", "string_id"]].assign(join_method="within", join_dist_km=0.0),
        accept.rename(columns={"dist_km": "join_dist_km"}).assign(join_method="nearest"),
    ], ignore_index=True)
    out = fac.merge(assign, on="facility_id", how="left")
    out["join_method"] = out["join_method"].fillna("none")
    print(f"spatial join: {(out.join_method != 'none').sum():,} of {len(out):,} facilities "
          f"carry a basin")
    return out, {
        "facilities_total": int(len(fac)),
        "coord_unusable": int(len(fac) - len(ok)),
        "matched_within": int(len(hit)),
        "matched_nearest_le_10km": int(len(accept)),
        "unassigned": int(len(reject) + (len(fac) - len(ok))),
    }


def rollup(wf, fac_raw, fut_years):
    """Facilities to tickers, three weightings, because the right one is a judgement call."""
    universe = pd.read_parquet(INTERIM / "universe.parquet")[
        ["ticker", "company_name", "gics_sector"]
    ]
    pmap = pd.read_parquet(INTERIM / "parent_ticker_map.parquet")[
        ["parent_name_clean", "ticker"]
    ].dropna().drop_duplicates()
    print(f"parent map: {len(pmap):,} parent to ticker links, {pmap.ticker.nunique():,} tickers")

    # The fleet is what the company reported in the latest GHGRP year. A plant it shut in 2016 is
    # not its current water exposure.
    fleet = fac_raw[fac_raw.year == FLEET_YEAR][
        ["facility_id", "parent_name_clean", "ownership_frac", "co2e_tonnes_share"]
    ].dropna(subset=["parent_name_clean"]).drop_duplicates(
        subset=["facility_id", "parent_name_clean"]
    )
    print(f"fleet year {FLEET_YEAR}: {fleet.facility_id.nunique():,} facilities, "
          f"{len(fleet):,} facility-parent links")

    link = fleet.merge(pmap, on="parent_name_clean", how="inner")
    link = link.merge(universe, on="ticker", how="inner")
    print(f"linked to S&P 500: {link.facility_id.nunique():,} facilities, "
          f"{link.ticker.nunique():,} tickers, {len(link):,} facility-ticker links")
    print(f"S&P 500 coverage: {link.ticker.nunique()} of {universe.ticker.nunique()} tickers have "
          f"at least one GHGRP facility in {FLEET_YEAR}")

    futcols = [f"ws_{FUT_SCENARIO}20{y}_cat" for y in fut_years]
    cols = ["facility_id", "string_id", "bws_cat", "bws_score", "bwd_score", "gtd_cat",
            "rfr_score", "drr_score", "w_awr_def_tot_score"] + futcols
    d = link.merge(wf[cols], on="facility_id", how="left")

    d["w_co2"] = d["co2e_tonnes_share"].fillna(0.0).clip(lower=0.0)
    d["has_basin"] = d["string_id"].notna()
    d["has_bws"] = d["bws_cat"].notna()
    d["high"] = d["bws_cat"].isin([3.0, 4.0])
    d["exhigh"] = d["bws_cat"] == 4.0
    d["arid"] = d["bws_cat"] == -1.0
    # gtd_cat 2 and above is a water table falling faster than 2 cm a year. -9999 is Insignificant
    # Trend and fails this test, which is what we want.
    d["gtd_decline"] = d["gtd_cat"] >= 2.0
    for y in fut_years:
        d[f"high_{y}"] = d[f"ws_{FUT_SCENARIO}20{y}_cat"].isin([3.0, 4.0])
        d[f"has_{y}"] = d[f"ws_{FUT_SCENARIO}20{y}_cat"].notna()

    def wmean(g, col, wcol):
        m = g[col].notna() & (g[wcol] > 0)
        if not m.any():
            return np.nan
        return float(np.average(g.loc[m, col], weights=g.loc[m, wcol]))

    rows = []
    for tk, g in d.groupby("ticker"):
        n = len(g)
        nbasin = int(g.has_basin.sum())
        nb = int(g.has_bws.sum())
        r = {
            "ticker": tk,
            "company_name": g.company_name.iloc[0],
            "gics_sector": g.gics_sector.iloc[0],
            "n_facilities": n,
            "n_facilities_with_basin": nbasin,
            "n_facilities_with_bws": nb,
            "co2e_tonnes_equity": float(g.w_co2.sum()),
            # one facility one vote
            "mean_bws_score": float(g.bws_score.mean()) if nb else np.nan,
            "mean_bwd_score": float(g.bwd_score.mean()),
            "mean_drr_score": float(g.drr_score.mean()),
            "mean_rfr_score": float(g.rfr_score.mean()),
            "mean_water_risk_score": float(g.w_awr_def_tot_score.mean()),
            "share_facilities_groundwater_declining":
                float(g.gtd_decline.sum() / nbasin) if nbasin else np.nan,
            # weighted by the CO2 we already measure
            "co2w_bws_score": wmean(g, "bws_score", "w_co2"),
            "co2w_bwd_score": wmean(g, "bwd_score", "w_co2"),
            "co2w_drr_score": wmean(g, "drr_score", "w_co2"),
            "co2w_water_risk_score": wmean(g, "w_awr_def_tot_score", "w_co2"),
            # the share a human understands
            "share_facilities_high_water_stress": float(g.high.sum() / nb) if nb else np.nan,
            "share_facilities_extremely_high_water_stress":
                float(g.exhigh.sum() / nb) if nb else np.nan,
            "share_facilities_arid_low_water_use": float(g.arid.sum() / nb) if nb else np.nan,
            "n_facilities_high_water_stress": int(g.high.sum()),
            "n_facilities_extremely_high_water_stress": int(g.exhigh.sum()),
        }
        hw = g.loc[g.has_bws, "w_co2"].sum()
        r["share_co2e_high_water_stress"] = (
            float(g.loc[g.high, "w_co2"].sum() / hw) if hw > 0 else np.nan
        )
        for y in fut_years:
            nf = int(g[f"has_{y}"].sum())
            r[f"n_facilities_with_ws_{FUT_SCENARIO}20{y}"] = nf
            r[f"share_facilities_high_water_stress_{FUT_SCENARIO}20{y}"] = (
                float(g[f"high_{y}"].sum() / nf) if nf else np.nan
            )
        rows.append(r)

    out = pd.DataFrame(rows)
    for y in fut_years:
        out[f"delta_share_high_water_stress_{FUT_SCENARIO}20{y}"] = (
            out[f"share_facilities_high_water_stress_{FUT_SCENARIO}20{y}"]
            - out["share_facilities_high_water_stress"]
        )
    out["scenario"] = f"{FUT_SCENARIO} (SSP3 RCP7.0)"
    out["fleet_year"] = FLEET_YEAR
    out["provenance_class"] = "modelled"
    return out.sort_values("share_facilities_extremely_high_water_stress", ascending=False)


# The independent check on the join. Aqueduct polygons carry a GADM level-1 province, and the EPA
# filing carries a state. They come from different institutions and never touched each other, so
# if the point landed in the right polygon they agree. Anything that disagrees is either a bad
# coordinate in the EPA filing or a point sat on a state line.
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def check_states(wf):
    c = wf[(wf.join_method == "within") & wf.state.isin(STATES) & wf.name_1.notna()].copy()
    c["expect"] = c.state.map(STATES)
    agree = (c.expect == c.name_1)
    print()
    print(f"state check: {int(agree.sum()):,} of {len(c):,} within-polygon facilities in the 50 "
          f"states plus DC landed in the GADM province matching their EPA state "
          f"({agree.mean() * 100:.2f}%)")
    bad = c[~agree]
    if len(bad):
        print("disagreements:")
        print(bad[["facility_id", "facility_name", "state", "name_1", "lat", "lon"]]
              .head(20).to_string(index=False))
    off = wf[(wf.name_0.notna()) & (wf.name_0 != "United States")]
    off = off[~off.state.isin(["PR", "VI", "GU", "AS", "MP"])]
    if len(off):
        print("facilities whose basin is outside the United States:")
        print(off[["facility_id", "facility_name", "state", "lat", "lon", "name_0", "name_1"]]
              .to_string(index=False))
    foreign = wf[wf.name_0.notna() & (wf.name_0 != "United States")]
    print(f"basins outside the United States: {len(foreign):,} facilities "
          f"({sorted(foreign.name_0.unique())})")


def fix_flipped_longitude(joined, basins, diag):
    """A US facility whose basin is in Kyrgyzstan has a longitude that lost its minus sign.

    This is the one coordinate repair made here, and it is made only when flipping the sign puts the
    point in the GADM province that matches the state on the EPA filing. That is a test the wrong
    answer fails, so nothing is guessed.
    """
    attr = basins.drop(columns="geometry")[["string_id", "name_0", "name_1"]]
    cand = joined.merge(attr, on="string_id", how="left")
    cand = cand[cand.state.isin(STATES) & cand.name_0.notna() & (cand.name_0 != "United States")]
    if not len(cand):
        return joined, diag

    print(f"longitude check: {len(cand)} facilities in a US state landed in {sorted(set(cand.name_0))}")
    flip = gpd.GeoDataFrame(
        cand[["facility_id", "state", "longitude"]].assign(lon2=-cand.longitude),
        geometry=gpd.points_from_xy(-cand.longitude, cand.latitude), crs="EPSG:4326",
    )
    hit = gpd.sjoin(flip, basins[["string_id", "geometry", "name_1"]], how="left",
                    predicate="within").drop_duplicates(subset="facility_id")
    hit["expect"] = hit.state.map(STATES)
    good = hit[hit.name_1 == hit.expect]
    print(f"longitude check: {len(good)} of {len(cand)} land in the right state once flipped, "
          f"and are corrected")
    if not len(good):
        return joined, diag

    joined = joined.set_index("facility_id")
    for fid, row in good.set_index("facility_id").iterrows():
        joined.loc[fid, "longitude"] = row.lon2
        joined.loc[fid, "string_id"] = row.string_id
        joined.loc[fid, "join_method"] = "within_lon_sign_corrected"
        joined.loc[fid, "join_dist_km"] = 0.0
        joined.loc[fid, "coord_flag"] = "lon_sign_corrected"
    joined = joined.reset_index()
    diag["lon_sign_corrected"] = int(len(good))
    return joined, diag


def check_resolution(wf, basins):
    """The baseline and the future are at different spatial resolutions. Show that it does not bite.

    Baseline indicators are given per basin x province x aquifer piece, the future projections per
    basin. Comparing a company's baseline share against its 2050 share is only honest if the pieces
    of a basin agree with each other, otherwise the change would partly be a change of resolution.
    """
    a = basins.drop(columns="geometry")
    us = a[(a.gid_0 == "USA") & a.pfaf_id.notna() & a.bws_cat.notna()]
    n = us.groupby("pfaf_id")["bws_cat"].nunique()
    print(f"resolution check: {len(n):,} US basins, {int((n == 1).sum()):,} carry one baseline water "
          f"stress category across all their province and aquifer pieces "
          f"({(n == 1).mean() * 100:.1f}%)")
    hit = wf[wf.pfaf_id.notna()].merge(n.rename("ncat"), left_on="pfaf_id", right_index=True,
                                       how="left")
    same = int((hit.ncat == 1).sum())
    tot = int(hit.ncat.notna().sum())
    print(f"resolution check: {same:,} of {tot:,} facilities sit in such a basin, so the baseline "
          f"to 2050 comparison is like for like")
    return {"us_basins": int(len(n)), "us_basins_single_bws_category": int((n == 1).sum()),
            "facilities_in_single_category_basin": same, "facilities_checked": tot}


def national_shares(wf):
    base = float(wf.bws_cat.isin([3.0, 4.0]).sum() / wf.bws_cat.notna().sum())
    print(f"all {int(wf.bws_cat.notna().sum()):,} GHGRP facilities with a basin: "
          f"{base * 100:.1f}% sit in High or Extremely High baseline water stress")
    out = {"baseline": round(base, 4)}
    for y in FUT_YEARS:
        c = wf[f"ws_{FUT_SCENARIO}20{y}_cat"]
        v = float(c.isin([3.0, 4.0]).sum() / c.notna().sum())
        print(f"  under {FUT_SCENARIO} 20{y}: {v * 100:.1f}%")
        out[f"{FUT_SCENARIO}20{y}"] = round(v, 4)
    return out


def main():
    extract()
    basins = load_basins()
    fut = load_future()
    fac = load_facilities()

    joined, diag = spatial_join(fac, basins)
    joined, diag = fix_flipped_longitude(joined, basins, diag)

    attr = basins.drop(columns="geometry")
    wf = joined.merge(attr, on="string_id", how="left")
    wf = wf.merge(fut, on="pfaf_id", how="left")

    keep = ["facility_id", "facility_name", "latitude", "longitude", "state", "county",
            "naics_code", "sector", "latest_year", "co2e_tonnes", "parent_name_clean", "n_parents",
            "coord_flag", "join_method", "join_dist_km", "string_id", "pfaf_id", "gid_1", "aqid",
            "name_0", "name_1", "area_km2"] + KEEP_COLS + \
           [c for c in wf.columns if c.startswith(f"ws_{FUT_SCENARIO}")]
    wf = wf[[c for c in keep if c in wf.columns]].rename(
        columns={"latitude": "lat", "longitude": "lon", "area_km2": "basin_area_km2"}
    )
    wf["provenance_class"] = "modelled"

    print()
    check_states(wf)
    print()
    print(f"water_facility: {len(wf):,} rows, {wf.facility_id.nunique():,} unique facility ids")
    print(f"  with a basin        {int(wf.string_id.notna().sum()):,}")
    print(f"  with a bws category {int(wf.bws_cat.notna().sum()):,}")
    print("  baseline water stress category:")
    print(wf.bws_label.value_counts(dropna=False).to_string())
    print()
    res = check_resolution(wf, basins)
    print()
    nat = national_shares(wf)
    wf.to_parquet(INTERIM / "water_facility.parquet", index=False)

    fac_raw = pd.read_parquet(INTERIM / "ghgrp_facilities.parquet")
    tick = rollup(wf, fac_raw, FUT_YEARS)
    print()
    print(f"water_by_ticker: {len(tick):,} tickers")
    tick.to_parquet(INTERIM / "water_by_ticker.parquet", index=False)

    print()
    print("Top 10 S&P 500 companies by share of facilities in EXTREMELY HIGH baseline water stress")
    print("(minimum 5 facilities with a basin)")
    top = tick[tick.n_facilities_with_bws >= 5].nlargest(
        10, "share_facilities_extremely_high_water_stress"
    )
    print(top[["ticker", "company_name", "gics_sector",
               "share_facilities_extremely_high_water_stress",
               "n_facilities_extremely_high_water_stress", "n_facilities_with_bws",
               "share_facilities_high_water_stress",
               f"share_facilities_high_water_stress_{FUT_SCENARIO}2050"]].to_string(index=False))

    print()
    print("Same list restricted to companies with at least 20 facilities in a basin")
    top20 = tick[tick.n_facilities_with_bws >= 20].nlargest(
        10, "share_facilities_extremely_high_water_stress"
    )
    print(top20[["ticker", "company_name", "gics_sector",
                 "share_facilities_extremely_high_water_stress",
                 "n_facilities_extremely_high_water_stress", "n_facilities_with_bws",
                 "share_facilities_high_water_stress",
                 f"share_facilities_high_water_stress_{FUT_SCENARIO}2050"]].to_string(index=False))

    print()
    print("Same list with no facility-count floor")
    top_all = tick.nlargest(10, "share_facilities_extremely_high_water_stress")
    print(top_all[["ticker", "company_name", "share_facilities_extremely_high_water_stress",
                   "n_facilities_extremely_high_water_stress",
                   "n_facilities_with_bws"]].to_string(index=False))

    PROV.mkdir(parents=True, exist_ok=True)
    prov = {
        "source": "aqueduct",
        "description": "WRI Aqueduct 4.0 water risk indicators, July 2023 release, HydroBASINS "
                       "level 6, joined to EPA GHGRP facility coordinates by point in polygon.",
        "provenance_class": "modelled",
        "provenance_note": "The water indicators are a WRI hydrological model, not a company "
                           "disclosure. The facility coordinates they are joined to come from "
                           "mandatory EPA GHGRP filings. No self-reported figure is used.",
        "url": SOURCE_URL,
        "data_dictionary_url": DICT_URL,
        "retrieved_at": datetime.fromtimestamp(
            RAW_ZIP.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "bytes": RAW_ZIP.stat().st_size,
        "sha256": sha256_of(RAW_ZIP),
        "local_path": str(RAW_ZIP.relative_to(ROOT)),
        "licence": LICENCE,
        "redistribution": "CC BY 4.0 permits redistribution of derived tables and charts with "
                          "attribution to the World Resources Institute and a link to the licence.",
        "attribution_required": "World Resources Institute, Aqueduct 4.0 (2023), CC BY 4.0",
        "layer_used": "baseline_annual",
        "layer_choice_reason": "The only GDB layer whose geometry is the basin x province x aquifer "
                               "union that string_id keys. baseline_monthly and future_annual are "
                               "basin only.",
        "future_scenario": f"{FUT_SCENARIO} business as usual, SSP3 RCP7.0",
        "future_years": [f"20{y}" for y in FUT_YEARS],
        "fleet_year": FLEET_YEAR,
        "indicator_codebook": INDICATORS,
        "suffixes": SUFFIXES,
        "category_traps": CAT_NOTES,
        "join_diagnostics": diag,
        "resolution_check": res,
        "national_share_high_or_extremely_high_water_stress": nat,
        "outputs": ["data/interim/water_facility.parquet", "data/interim/water_by_ticker.parquet"],
    }
    (PROV / "aqueduct.json").write_text(json.dumps(prov, indent=2))
    print()
    print(f"wrote {PROV / 'aqueduct.json'}")


if __name__ == "__main__":
    main()
