"""Carbon price scenarios and the Paris-Aligned Benchmark rulebook.

Two artefacts, two sources, both free and both citable:

  data/interim/ngfs_scenarios.parquet  NGFS Phase 5 pathways from IIASA's Scenario Explorer.
                                       Carbon price, emissions, energy mix and industrial output
                                       for World and the United States, every scenario, every model.
  data/interim/pab_rules.json          Commission Delegated Regulation (EU) 2020/1818 turned into
                                       machine-readable constraints, every threshold parsed out of
                                       the live EUR-Lex text rather than typed from memory.

The IIASA API has an anonymous guest token: no signup, no key, 12 hour life, free to re-request.
Every response is cached under data/raw/, so a second run touches the network zero times.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from lxml import html as lhtml

ROOT = Path(__file__).resolve().parents[1]
RAW_NGFS = ROOT / "data" / "raw" / "ngfs"
RAW_EURLEX = ROOT / "data" / "raw" / "eurlex"
INTERIM = ROOT / "data" / "interim"
PROV = INTERIM / "provenance"

UA = "ETHack2026/1.0 (artemiy.v.burov@gmail.com)"
AUTH_URL = "https://api.manager.ece.iiasa.ac.at/legacy/anonym/IXSE_NGFS_PHASE_5"
APP_CONFIG_URL = "https://api.manager.ece.iiasa.ac.at/legacy/applications/IXSE_NGFS_PHASE_5/config"
API_BASE = "https://db1.ene.iiasa.ac.at/ngfs-phase-5-api/rest/v2.1"
EURLEX_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32020R1818"

NGFS_LICENCE = (
    "IIASA NGFS Phase 5 Scenario Explorer terms of use: free to use with citation, "
    "liability disclaimed by IIASA and the scenario modelling teams."
)
NGFS_REDISTRIBUTION = (
    "We may publish derived and aggregated numbers with the attribution "
    "'NGFS Climate Scenarios Phase V (November 2024), IIASA NGFS Scenario Explorer'. "
    "We do not republish the raw database wholesale."
)
EURLEX_LICENCE = "EUR-Lex reuse policy. (c) European Union, 1998-2026."
EURLEX_REDISTRIBUTION = (
    "Reuse of EU legislative text and of numbers derived from it is authorised, provided the source "
    "is acknowledged: 'Source: EUR-Lex, (c) European Union, 1998-2026'. We may publish these rules."
)

# The US shows up under a different name in every model's own region hierarchy, and again as an ISO3
# code in the downscaled country runs. Ask for all of them and keep whatever answers.
REGIONS = [
    "World",
    "USA",
    "United States",
    "REMIND-MAgPIE 3.3-4.8|United States of America",
    "GCAM 6.0 NGFS|USA",
    "NiGEM NGFS v1.24.2|United States",
    "MESSAGEix-GLOBIOM 2.0-R12|North America",
]

REGION_SCOPE = {
    "World": "world",
    "USA": "united_states",
    "United States": "united_states",
    "REMIND-MAgPIE 3.3-4.8|United States of America": "united_states",
    "GCAM 6.0 NGFS|USA": "united_states",
    "NiGEM NGFS v1.24.2|United States": "united_states",
    "MESSAGEix-GLOBIOM 2.0-R12|North America": "north_america",
}

VARIABLE_GROUPS = {
    "carbon_price": [
        "Price|Carbon",
        "Price|Carbon|Supply",
        "Price|Carbon|Demand|Industry",
        "Price|Carbon|Demand|Residential and Commercial",
        "Price|Carbon|Demand|Transportation",
        "Price|Primary Energy|Coal",
        "Price|Primary Energy|Oil",
        "Price|Primary Energy|Gas",
        "Price|Secondary Energy|Electricity",
    ],
    "emissions_energy": [
        "Emissions|CO2",
        "Emissions|CO2|Energy",
        "Emissions|CO2|Energy|Supply|Electricity",
        "Emissions|CO2|Energy|Demand|Industry",
        "Emissions|CO2|Energy|Demand|Transportation",
        "Emissions|CO2|Industrial Processes",
        "Emissions|Kyoto Gases",
        "Carbon Sequestration|CCS",
        "Primary Energy",
        "Primary Energy|Coal",
        "Primary Energy|Oil",
        "Primary Energy|Gas",
        "Final Energy",
        "Final Energy|Industry",
        "Final Energy|Transportation",
        "Final Energy|Residential and Commercial",
        "Secondary Energy|Electricity",
        "Secondary Energy|Electricity|Coal",
        "Secondary Energy|Electricity|Gas",
        "Secondary Energy|Electricity|Oil",
        "Secondary Energy|Electricity|Nuclear",
        "Secondary Energy|Electricity|Solar",
        "Secondary Energy|Electricity|Wind",
        "Secondary Energy|Electricity|Hydro",
        "Secondary Energy|Electricity|Biomass",
    ],
    "industry_macro": [
        "Production|Steel",
        "Production|Cement",
        "Capacity|Electricity|Solar",
        "Capacity|Electricity|Wind",
        "Investment|Energy Supply|Electricity",
        "GDP|PPP|Counterfactual without damage",
        "GDP|MER|Counterfactual without damage",
        "GDP|PPP|including medium chronic physical risk damage estimate",
        "GDP|MER|including medium chronic physical risk damage estimate",
    ],
    # NiGEM is the macro model NGFS wraps around each IAM. It reports differences from its own
    # baseline rather than levels, and it is the only place in Phase 5 with an equity price and a
    # corporate profit series, which is the channel a carbon price reaches earnings through.
    "macro_financial": [
        f"{name}({flavour})"
        for name in [
            "Gross Domestic Product (GDP)",
            "Gross operating surplus",
            "Equity prices",
            "Inflation rate ; %",
            "Long term interest rate ; %",
            "Long term real interest rate ; %",
            "Central bank Intervention rate (policy interest rate) ; %",
            "Unemployment rate ; %",
            "Productivity (output per hour worked); US$ Bn",
            "Oil price ; US$ per barrel",
            "Coal price ; US$ per barrel (equiv)",
            "Gas price ; US$ per barrel (equiv)",
            "Volume energy use as a share of GDP ; Bn US$(PPP)",
        ]
        for flavour in ["transition", "physical", "combined"]
    ],
}

# NGFS says so itself on its data-resources page: the physical damage estimates in Phase 5 rest on
# Kotz et al. (2024), which Nature retracted. Transition variables are unaffected. Flag the rows so
# nobody quotes a damage number without the caveat.
RETRACTED_BASIS_MODEL = "IntegratedPhysicalDamages"
RETRACTED_BASIS_VARIABLES = ("physical risk damage", "(physical)", "(combined)")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def meta_path(cache: Path) -> Path:
    return cache.with_suffix(cache.suffix + ".meta.json")


def record(url: str, status: int | None, payload: bytes, licence: str, redistribution: str, **extra) -> dict:
    return {
        "url": url,
        "retrieved_at": utcnow(),
        "http_status": status,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "licence": licence,
        "redistribution": redistribution,
        **extra,
    }


def fetch(url: str, cache: Path, licence: str, redistribution: str,
          session: requests.Session | None = None, token: str | None = None,
          body: dict | None = None) -> tuple[bytes, dict]:
    """Return the response bytes and a provenance record, reading from cache when possible."""
    if cache.exists() and cache.stat().st_size > 0:
        payload = cache.read_bytes()
        mp = meta_path(cache)
        if mp.exists():
            prov = json.loads(mp.read_text())
        else:
            prov = record(url, None, payload, licence, redistribution,
                          note="served from an existing cache file with no provenance sidecar")
        print(f"  cached  {cache.relative_to(ROOT)}  {len(payload):,} bytes")
        return payload, prov

    assert session is not None, f"cache miss for {cache} but no session was opened"
    headers = {"User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is None:
        resp = session.get(url, headers=headers, timeout=180)
    else:
        headers["Content-Type"] = "application/json"
        resp = session.post(url, headers=headers, json=body, timeout=300)
    resp.raise_for_status()
    payload = resp.content

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(payload)
    prov = record(url, resp.status_code, payload, licence, redistribution)
    if body is not None:
        prov["method"] = "POST"
        prov["request_body_sha256"] = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()
        ).hexdigest()
        prov["request_filters"] = body["filters"]
    meta_path(cache).write_text(json.dumps(prov, indent=2))
    print(f"  fetched {cache.relative_to(ROOT)}  HTTP {resp.status_code}  {len(payload):,} bytes")
    time.sleep(0.5)
    return payload, prov


def ngfs_cache_targets() -> dict[str, Path]:
    targets = {
        "app_config": RAW_NGFS / "app_config.json",
        "runs": RAW_NGFS / "runs.json",
        "nodes": RAW_NGFS / "nodes.json",
    }
    for group in VARIABLE_GROUPS:
        targets[group] = RAW_NGFS / f"bulk_{group}.json"
    return targets


def get_guest_token(session: requests.Session) -> tuple[str, dict]:
    """IIASA hands out an anonymous JWT for the public Scenario Explorer. No account needed."""
    sidecar = RAW_NGFS / "auth.meta.json"
    resp = session.get(AUTH_URL, headers={"User-Agent": UA}, timeout=60)
    resp.raise_for_status()
    token = resp.text.strip().strip('"')
    prov = record(AUTH_URL, resp.status_code, resp.content, NGFS_LICENCE, NGFS_REDISTRIBUTION,
                  note="anonymous guest JWT, 12 hour life, body deliberately not cached")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(prov, indent=2))
    print(f"  guest token acquired, {len(token)} chars")
    return token, prov


def fetch_ngfs() -> tuple[pd.DataFrame, list[dict]]:
    targets = ngfs_cache_targets()
    complete = all(p.exists() and p.stat().st_size > 0 for p in targets.values())

    session = None
    token = None
    provenance: list[dict] = []
    if complete:
        print("NGFS: every response already cached, no network I/O")
        sidecar = RAW_NGFS / "auth.meta.json"
        if sidecar.exists():
            provenance.append(json.loads(sidecar.read_text()))
    else:
        session = requests.Session()
        token, auth_prov = get_guest_token(session)
        provenance.append(auth_prov)

    def pull(url, cache, body=None):
        payload, prov = fetch(url, cache, NGFS_LICENCE, NGFS_REDISTRIBUTION,
                              session=session, token=token, body=body)
        provenance.append(prov)
        return json.loads(payload)

    pull(APP_CONFIG_URL, targets["app_config"])
    runs = pull(f"{API_BASE}/runs?getOnlyDefaultRuns=true", targets["runs"])
    nodes = pull(f"{API_BASE}/nodes?hierarchy=%2A", targets["nodes"])
    print(f"NGFS: {len(runs)} default runs, {len(nodes)} regions in the node tree")

    run_ids = sorted(r["run_id"] for r in runs)
    # The bulk endpoint mangles non-ASCII in scenario names ("Below 2?C"), so take the authoritative
    # model and scenario labels from the runs list and join on run id.
    labels = {r["run_id"]: (r["model"], r["scenario"]) for r in runs}

    frames = []
    for group, variables in VARIABLE_GROUPS.items():
        body = {"filters": {"runs": run_ids, "regions": REGIONS, "variables": variables,
                            "units": [], "years": [], "timeslices": []}}
        rows = pull(f"{API_BASE}/runs/bulk/ts", targets[group], body=body)
        df = pd.DataFrame(rows)
        print(f"NGFS group {group:16s} {len(variables):2d} variables requested -> {len(df):,} rows, "
              f"{df['variable'].nunique() if len(df) else 0} variables returned")
        frames.append(df)

    raw = pd.concat(frames, ignore_index=True)
    print(f"NGFS: {len(raw):,} raw timeseries rows across {len(VARIABLE_GROUPS)} queries")

    out = pd.DataFrame({
        "scenario": raw["runId"].map(lambda r: labels[r][1]),
        "model": raw["runId"].map(lambda r: labels[r][0]),
        "region": raw["region"],
        "variable": raw["variable"],
        "unit": raw["unit"],
        "year": raw["year"].astype("int32"),
        "value": raw["value"].astype("float64"),
        "run_id": raw["runId"].astype("int32"),
    })
    out["scenario_key"] = out["scenario"].map(
        lambda s: re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    )
    out["region_scope"] = out["region"].map(REGION_SCOPE).fillna("other")
    out["is_downscaled"] = out["model"].str.startswith("Downscaling[")
    flagged = out["model"].str.contains(RETRACTED_BASIS_MODEL, regex=False)
    for marker in RETRACTED_BASIS_VARIABLES:
        flagged |= out["variable"].str.contains(marker, regex=False)
    out["retracted_damage_basis"] = flagged

    before = len(out)
    out = out.dropna(subset=["value"]).drop_duplicates(
        subset=["run_id", "region", "variable", "year"]
    )
    print(f"NGFS: dropped {before - len(out):,} null or duplicate rows -> {len(out):,} rows")
    out = out.sort_values(["variable", "scenario", "model", "region", "year"]).reset_index(drop=True)
    return out, provenance


def summarise(df: pd.DataFrame) -> None:
    print()
    print(f"rows                 {len(df):,}")
    print(f"scenarios            {df['scenario'].nunique()}  {sorted(df['scenario'].unique())}")
    print(f"models               {df['model'].nunique()}")
    print(f"regions              {df['region'].nunique()}  {sorted(df['region'].unique())}")
    print(f"variables            {df['variable'].nunique()}")
    print(f"years                {df['year'].min()}-{df['year'].max()}")
    print(f"rows 2020-2050       {len(df.query('2020 <= year <= 2050')):,}")
    print(f"rows flagged as resting on the retracted Kotz et al. (2024) damage function: "
          f"{int(df['retracted_damage_basis'].sum()):,}")

    price = df[(df.variable == "Price|Carbon") & (df.model == "REMIND-MAgPIE 3.3-4.8")]
    for region in ["World", "REMIND-MAgPIE 3.3-4.8|United States of America"]:
        sub = price[price.region == region]
        if sub.empty:
            continue
        wide = sub.pivot_table(index="scenario", columns="year", values="value")
        cols = [y for y in (2025, 2030, 2040, 2050) if y in wide.columns]
        print(f"\nPrice|Carbon, REMIND-MAgPIE 3.3-4.8, {region}, {sub['unit'].iloc[0]}")
        print(wide[cols].round(1).to_string())

    # The macro channel the carbon price reaches company earnings through.
    macro = df[(df.region == "NiGEM NGFS v1.24.2|United States")
               & (df.model == "NiGEM NGFS v1.24.2[REMIND-MAgPIE 3.3-4.8]")]
    for variable in ["Gross operating surplus(transition)", "Equity prices(transition)"]:
        sub = macro[macro.variable == variable]
        if sub.empty:
            continue
        wide = sub.pivot_table(index="scenario", columns="year", values="value")
        cols = [y for y in (2025, 2030, 2040, 2050) if y in wide.columns]
        print(f"\n{variable}, United States, NiGEM on REMIND, {sub['unit'].iloc[0]}")
        print(wide[cols].round(2).to_string())


def article_texts(raw: bytes) -> dict[str, str]:
    doc = lhtml.fromstring(raw)
    texts = {}
    for node in doc.xpath("//*[starts-with(@id,'art_') and not(contains(@id,'.'))]"):
        num = node.get("id").split("_", 1)[1]
        texts[num] = re.sub(r"\s+", " ", node.text_content()).strip()
    return texts


def grab(texts: dict[str, str], article: str, pattern: str) -> re.Match:
    """Find a passage in the live regulation. Fail loudly rather than fall back on memory."""
    # Rules are cited as 7(1)(a); the document anchors are one per article.
    text = texts.get(article.split("(")[0])
    if text is None:
        raise SystemExit(f"Article {article} not found in the EUR-Lex document")
    m = re.search(pattern, text)
    if m is None:
        raise SystemExit(
            f"Article {article}: pattern did not match the EUR-Lex text.\n"
            f"  pattern: {pattern}\n  text:    {text[:600]}"
        )
    return m


def build_pab_rules(raw: bytes, prov: dict) -> dict:
    texts = article_texts(raw)
    print(f"EUR-Lex: parsed {len(texts)} articles from the fetched HTML")

    def rule(rid, article, applies_to, kind, pattern, params_from, **extra):
        m = grab(texts, article, pattern)
        params = {name: caster(m.group(grp)) for name, (grp, caster) in params_from.items()}
        return {
            "id": rid,
            "article": f"Article {article}",
            "article_number": int(article.split("(")[0]),
            "applies_to": applies_to,
            "type": kind,
            "parameters": params,
            "quote": m.group(0),
            **extra,
        }

    pct = lambda s: float(s.replace(",", "."))

    rules = [
        rule("reference_temperature_scenario", "2", ["CTB", "PAB"], "reference",
             r"shall use the 1,5\s?°C scenario, with no or limited overshoot, referred to in the "
             r"Special Report on Global Warming of 1,5\s?°C from the Intergovernmental Panel on "
             r"Climate Change \(IPCC\)",
             {"warming_limit_c": (0, lambda _: 1.5)},
             note="Overshoot qualifier means an AR6 C1 category pathway. IIASA's AR6 Scenario "
                  "Explorer serves those under the same anonymous guest token as NGFS.",
             parameters_note="warming_limit_c is read as the literal 1,5 in the quoted passage; "
                             "the regulation writes decimals with a comma."),

        rule("equity_allocation_constraint", "3", ["CTB", "PAB"], "sector_exposure_floor",
             r"aggregated exposure to the sectors listed in Sections ([A-Z]) to ([A-Z]) and Section "
             r"([A-Z]) of Annex I to Regulation \(EC\) No 1893/2006 that is at least equivalent to "
             r"the aggregated exposure of the underlying investable universe to those sectors",
             {"nace_section_range_start": (1, str), "nace_section_range_end": (2, str),
              "nace_section_extra": (3, str)},
             nace_sections=["A", "B", "C", "D", "E", "F", "G", "H", "L"],
             nace_section_titles_note=(
                 "Section letters are quoted from the regulation. The plain-language titles "
                 "(A agriculture, B mining, C manufacturing, D electricity and gas supply, E water "
                 "and waste, F construction, G trade, H transport and storage, L real estate) come "
                 "from NACE Rev. 2 Annex I of Regulation (EC) No 1893/2006, not from 2020/1818."),
             check="sum(w_portfolio[i] for i in high_climate_impact) >= "
                   "sum(w_universe[i] for i in high_climate_impact)",
             why="This is the constraint most teams miss. You are not allowed to hit the intensity "
                 "target by simply dumping energy and utilities."),

        rule("scope3_phase_in", "5", ["CTB", "PAB"], "data_scope",
             r"\(a\) As of 23 December 2020, Scope 3 GHG emissions data for at least the energy and "
             r"mining sectors referred to in Divisions (05 to 09 and 19 and 20).*?"
             r"\(b\) within (two) years from 23 December 2020, .*?Divisions "
             r"(10 to 18, 21 to 33, 41, 42 and 43, 49 to 53 and Division 81).*?"
             r"\(c\) within (four) years from 23 December 2020, Scope 3 GHG emissions data for all "
             r"other sectors",
             {"immediate_nace_divisions": (1, str), "tranche_2_years": (2, lambda _: 2),
              "tranche_2_nace_divisions": (3, str), "tranche_3_years": (4, lambda _: 4)},
             effective_from="2020-12-23",
             all_sectors_in_scope_from="2024-12-23",
             check="scope3 is required for every sector as of 2024-12-23, so we use scope 1+2+3 "
                   "throughout"),

        rule("target_setter_overweight", "6", ["CTB", "PAB"], "optional_tilt",
             r"reduced their GHG intensity or, where applicable, their absolute GHG emissions, "
             r"including Scope 1, 2 and 3 GHG emissions, by an average of at least (\d+)\s?% per "
             r"annum for at least (three) consecutive years",
             {"min_annual_reduction_pct": (1, pct), "min_consecutive_years": (2, lambda _: 3)},
             conditional_on="issuer publishes Scope 1, 2 and 3 emissions consistently and accurately",
             permissive=True,
             why="The only place the regulation lets you overweight anything, and it turns on a "
                 "reduction the issuer has already delivered rather than one it has announced. "
                 "That is the same test as our promise-versus-physics gap."),

        rule("decarbonisation_trajectory_equity", "7(1)(a)", ["CTB", "PAB"], "trajectory",
             r"\(a\) for equity securities admitted to a public market in the Union or in another "
             r"jurisdiction, at least (\d+)\s?% reduction of GHG intensity on average per annum",
             {"min_annual_reduction_pct": (1, pct)},
             basis="GHG intensity, meaning absolute emissions per EUR million of EVIC",
             check="intensity[base_year + n] <= intensity[base_year] * (1 - 0.07) ** n"),

        rule("trajectory_is_geometric", "7(2)", ["CTB", "PAB"], "trajectory_mechanics",
             r"shall be calculated geometrically, which shall mean that the annual minimum (\d+)\s?% "
             r"reduction of GHG intensity or of absolute GHG emissions for year .n. shall be "
             r"calculated based on the GHG intensity or absolute GHG emissions for the year n-1, in "
             r"a geometric progression from the base year",
             {"min_annual_reduction_pct": (1, pct)},
             check="compounding, not linear: a 10 year path is (1-0.07)**10 = 0.484 of the base year"),

        rule("evic_inflation_adjustment", "7(3)", ["CTB", "PAB"], "trajectory_mechanics",
             r"the EVIC of each constituent shall be adjusted by dividing it by an enterprise value "
             r"inflation adjustment factor. That enterprise value inflation adjustment factor shall "
             r"be calculated by dividing the average EVIC of the benchmark constituents at the end "
             r"of a calendar year by the average EVIC of the benchmark constituents at the end of "
             r"the previous calendar year",
             {},
             formula="evic_adjusted[i,t] = evic[i,t] / (mean(evic[:,t]) / mean(evic[:,t-1]))",
             why="Without this a bull market alone would show you decarbonising."),

        rule("missed_target_compensation", "7(4)", ["CTB", "PAB"], "trajectory_mechanics",
             r"for each year in which the targets laid down in paragraph 1 are not achieved, "
             r"compensate for those missed targets by upwardly adjusting the targets in their "
             r"decarbonisation trajectory for the following year",
             {}),

        rule("label_loss", "7(5)", ["CTB", "PAB"], "trajectory_mechanics",
             r"\(a\) the targets laid down in paragraph 1 are not achieved in a given year and the "
             r"target miss is not compensated in the following year; or \(b\) the targets laid down "
             r"in paragraph 1 are not achieved on (three) occasions in any consecutive (\d+)-year "
             r"period",
             {"max_misses": (1, lambda _: 3), "rolling_window_years": (2, int)},
             relabel_condition="meets the trajectory target for two consecutive years after the "
                               "loss, unless the label was lost twice"),

        rule("change_measurement", "8(1)", ["CTB", "PAB"], "measurement",
             r"percentage change between, on the one hand, the weighted average GHG intensity or "
             r"absolute GHG emissions of all constituents of the EU Climate Transition Benchmark or "
             r"the EU Paris-aligned Benchmark at the end of year .n. and, on the other hand, the "
             r"weighted average GHG intensity or absolute GHG emissions of all constituents of the "
             r"benchmarks at the end of year n-1",
             {},
             check="weighted average across constituents, portfolio weights as the weights"),

        rule("ctb_baseline_reduction", "9", ["CTB"], "intensity_floor",
             r"for EU Climate Transition Benchmarks, including Scope 1, 2 and 3 GHG emissions, "
             r"shall be at least (\d+)\s?% lower than the GHG intensity or absolute GHG emissions of "
             r"the investable universe",
             {"min_reduction_vs_universe_pct": (1, pct)},
             scopes=[1, 2, 3],
             check="intensity_portfolio <= intensity_universe * (1 - 0.30)"),

        rule("ctb_exclusions_apply", "10(2)", ["CTB"], "exclusion_reference",
             r"By 31 December 2022, administrators of EU Climate Transition Benchmarks shall comply "
             r"with the requirements set out in Article 12\(1\), points \(a\), \(b\) and \(c\), and "
             r"Article 12\(2\)",
             {},
             inherits=["pab_exclusion_controversial_weapons", "pab_exclusion_tobacco",
                       "pab_exclusion_ungc_oecd", "pab_exclusion_dnsh"],
             note="A CTB inherits the conduct exclusions but not the fossil revenue thresholds."),

        rule("pab_baseline_reduction", "11", ["PAB"], "intensity_floor",
             r"for EU Paris-aligned Benchmarks, including Scope 1, 2 and 3 GHG emissions, shall be "
             r"at least (\d+)\s?% lower than the GHG intensity or absolute GHG emissions of the "
             r"investable universe",
             {"min_reduction_vs_universe_pct": (1, pct)},
             scopes=[1, 2, 3],
             measured_at="inception, against the investable universe",
             check="intensity_portfolio <= intensity_universe * (1 - 0.50)"),

        rule("pab_exclusion_controversial_weapons", "12(1)(a)", ["PAB", "CTB"], "exclusion",
             r"\(a\) companies involved in any activities related to controversial weapons",
             {}, basis="activity"),

        rule("pab_exclusion_tobacco", "12(1)(b)", ["PAB", "CTB"], "exclusion",
             r"\(b\) companies involved in the cultivation and production of tobacco",
             {}, basis="activity"),

        rule("pab_exclusion_ungc_oecd", "12(1)(c)", ["PAB", "CTB"], "exclusion",
             r"\(c\) companies that benchmark administrators find in violation of the United Nations "
             r"Global Compact \(UNGC\) principles or the Organisation for Economic Cooperation and "
             r"Development \(OECD\) Guidelines for Multinational Enterprises",
             {}, basis="conduct"),

        rule("pab_exclusion_coal", "12(1)(d)", ["PAB"], "exclusion",
             r"\(d\) companies that derive (\d+)\s?% or more of their revenues from exploration, "
             r"mining, extraction, distribution or refining of hard coal and lignite",
             {"revenue_threshold_pct": (1, pct)},
             basis="revenue_share",
             operator=">=",
             activities=["exploration", "mining", "extraction", "distribution", "refining"],
             commodity="hard coal and lignite",
             check="revenue_share_coal >= 0.01 -> exclude"),

        rule("pab_exclusion_oil", "12(1)(e)", ["PAB"], "exclusion",
             r"\(e\) companies that derive (\d+)\s?% or more of their revenues from the exploration, "
             r"extraction, distribution or refining of oil fuels",
             {"revenue_threshold_pct": (1, pct)},
             basis="revenue_share",
             operator=">=",
             activities=["exploration", "extraction", "distribution", "refining"],
             commodity="oil fuels",
             check="revenue_share_oil >= 0.10 -> exclude"),

        rule("pab_exclusion_gas", "12(1)(f)", ["PAB"], "exclusion",
             r"\(f\) companies that derive (\d+)\s?% or more of their revenues from the exploration, "
             r"extraction, manufacturing or distribution of gaseous fuels",
             {"revenue_threshold_pct": (1, pct)},
             basis="revenue_share",
             operator=">=",
             activities=["exploration", "extraction", "manufacturing", "distribution"],
             commodity="gaseous fuels",
             check="revenue_share_gas >= 0.50 -> exclude"),

        rule("pab_exclusion_power_generation", "12(1)(g)", ["PAB"], "exclusion",
             r"\(g\) companies that derive (\d+)\s?% or more of their revenues from electricity "
             r"generation with a GHG intensity of more than (\d+)\s?g CO2\s?e/kWh",
             {"revenue_threshold_pct": (1, pct), "intensity_threshold_gco2e_per_kwh": (2, pct)},
             basis="revenue_share_and_intensity",
             operator=">=",
             intensity_operator=">",
             check="revenue_share_power >= 0.50 and generation_intensity_gco2e_kwh > 100 -> exclude",
             why="Both legs must hold. A utility with half its revenue from generation but a clean "
                 "fleet stays in, which is what makes this a transition rule rather than a ban."),

        rule("pab_exclusion_dnsh", "12(2)", ["PAB"], "exclusion",
             r"companies that are found or estimated by them or by external data providers to "
             r"significantly harm one or more of the environmental objectives referred to in "
             r"Article 9 of Regulation \(EU\) 2020/852",
             {}, basis="taxonomy_dnsh",
             note="EU Taxonomy Regulation (EU) 2020/852 Article 9 objectives."),

        rule("estimation_transparency", "13", ["CTB", "PAB"], "disclosure",
             r"that use estimations that are not based on data provided by an external data "
             r"provider, shall formalise, document and make public the methodology upon which such "
             r"estimations are based",
             {},
             why="Our estimated emissions carry a PCAF-style dq score and a named method, which is "
                 "what this article asks for."),

        rule("trajectory_disclosure", "14", ["CTB", "PAB"], "disclosure",
             r"shall formalise, document and make public the decarbonisation trajectories of those "
             r"benchmarks, the base year used for the determination of those decarbonisation "
             r"trajectories",
             {}),

        rule("data_accuracy_standards", "15(1)", ["CTB", "PAB"], "disclosure",
             r"shall ensure that data on Scope 1, 2 and 3 GHG emissions are accurate, in accordance "
             r"with global or European standards, such as the Product Environmental Footprint "
             r"\(PEF\), the Organisation Environmental Footprint \(OEF\) methods.*?, the Corporate "
             r"Value Chain \(Scope 3\) Accounting and Reporting Standard.*?, the EN ISO 14064 or the "
             r"EN ISO 14069",
             {},
             standards=["GHG Protocol Corporate Value Chain (Scope 3) Accounting and Reporting "
                        "Standard", "EN ISO 14064", "EN ISO 14069", "PEF", "OEF"]),
    ]

    definitions = []
    for did, article, pattern, extra in [
        ("ghg_emissions", "1(a)",
         r"\(a\) .greenhouse gas \(GHG\) emissions. means greenhouse gas emissions as defined in "
         r"Article 3, point \(1\), of Regulation \(EU\) 2018/842", {}),
        ("absolute_ghg_emissions", "1(b)",
         r"\(b\) .absolute greenhouse gas \(GHG\) emissions. means tonnes of CO2 equivalent",
         {"unit": "tCO2e"}),
        ("ghg_intensity", "1(c)",
         r"\(c\) .greenhouse gas \(GHG\) intensity. means absolute GHG emissions divided by millions "
         r"of euros in enterprise value including cash",
         {"formula": "absolute_ghg_emissions_tco2e / (evic_eur / 1e6)",
          "unit": "tCO2e per EUR million of EVIC",
          "why": "Per EVIC, not per revenue. The same tonnes over a bigger market cap read as a "
                 "lower intensity, so a share price rally decarbonises a portfolio on paper. "
                 "Article 7(3) patches this for the trajectory but not for the Article 11 level."}),
        ("evic", "1(d)",
         r"\(d\) .enterprise value including cash. or .EVIC. means the sum, at fiscal year-end, of "
         r"the market capitalisation of ordinary shares, the market capitalization of preferred "
         r"shares, and the book value of total debt and non-controlling interests, without the "
         r"deduction of cash or cash equivalents",
         {"formula": "market_cap_ordinary + market_cap_preferred + book_value_total_debt + "
                     "non_controlling_interests",
          "cash_deducted": False,
          "measured_at": "fiscal year-end"}),
        ("investable_universe", "1(e)",
         r"\(e\) .investable universe. means the set of all investable instruments in a given asset "
         r"class or group of asset classes",
         {"our_universe": "S&P 500 constituents"}),
        ("base_year", "1(f)",
         r"\(f\) .base year. means the first of a series of years in a benchmark", {}),
    ]:
        m = grab(texts, "1", pattern)
        definitions.append({"term": did, "article": f"Article {article}", "quote": m.group(0), **extra})

    print(f"EUR-Lex: encoded {len(definitions)} definitions and {len(rules)} rules, "
          f"every quote matched against the fetched text")

    thresholds = {r["id"]: r["parameters"] for r in rules if r["parameters"]}
    return {
        "regulation": {
            "celex": "32020R1818",
            "title": "Commission Delegated Regulation (EU) 2020/1818 of 17 July 2020 supplementing "
                     "Regulation (EU) 2016/1011 of the European Parliament and of the Council as "
                     "regards minimum standards for EU Climate Transition Benchmarks and EU "
                     "Paris-aligned Benchmarks",
            "eli": "http://data.europa.eu/eli/reg_del/2020/1818/oj",
            "source_url": EURLEX_URL,
            "retrieved_at": prov["retrieved_at"],
            "sha256": prov["sha256"],
            "articles_parsed": sorted(int(a) for a in texts),
            "licence": EURLEX_LICENCE,
            "redistribution": EURLEX_REDISTRIBUTION,
            "attribution": "Source: EUR-Lex, (c) European Union, 1998-2026",
        },
        "how_to_read_this_file": (
            "Every rule carries the article it comes from and the sentence it was parsed out of. "
            "The numbers under 'parameters' were extracted by regex from the quoted sentence at "
            "fetch time, so they cannot drift from the regulation. 'check' is the constraint in "
            "the form the portfolio builder should implement it."
        ),
        "definitions": definitions,
        "rules": rules,
        "thresholds": thresholds,
    }


def main() -> int:
    for d in (RAW_NGFS, RAW_EURLEX, INTERIM, PROV):
        d.mkdir(parents=True, exist_ok=True)

    print("=== NGFS Phase 5 scenarios ===")
    scenarios, ngfs_prov = fetch_ngfs()
    summarise(scenarios)
    out_parquet = INTERIM / "ngfs_scenarios.parquet"
    scenarios.to_parquet(out_parquet, index=False)
    print(f"\nwrote {out_parquet.relative_to(ROOT)}  {len(scenarios):,} rows  "
          f"{out_parquet.stat().st_size:,} bytes")
    (PROV / "ngfs.json").write_text(json.dumps({
        "source": "NGFS Phase 5 Scenario Explorer (IIASA)",
        "citation": "NGFS Climate Scenarios Phase V (November 2024), IIASA NGFS Scenario Explorer, "
                    "https://data.ece.iiasa.ac.at/ngfs/",
        "access": "Anonymous guest JWT from the legacy auth service. No account, no API key.",
        "caveat": "NGFS states on its own data-resources page that Kotz et al. (2024), the paper "
                  "underpinning the Phase 5 physical damage estimates, has been retracted from "
                  "Nature. Rows where retracted_damage_basis is true rest on that function: "
                  "every REMIND IntegratedPhysicalDamages run, the GDP variables that name a "
                  "physical risk damage estimate, and the NiGEM (physical) and (combined) "
                  "flavours. Transition variables, including every NiGEM (transition) series, "
                  "are unaffected.",
        "rows": len(scenarios),
        "fetched": ngfs_prov,
    }, indent=2))
    print(f"wrote {(PROV / 'ngfs.json').relative_to(ROOT)}  {len(ngfs_prov)} URLs")

    print("\n=== EU Delegated Regulation 2020/1818 ===")
    eurlex_cache = RAW_EURLEX / "32020R1818.html"
    session = None if eurlex_cache.exists() and eurlex_cache.stat().st_size > 0 else requests.Session()
    raw, eur_prov = fetch(EURLEX_URL, eurlex_cache, EURLEX_LICENCE, EURLEX_REDISTRIBUTION,
                          session=session)
    rules = build_pab_rules(raw, eur_prov)
    out_json = INTERIM / "pab_rules.json"
    out_json.write_text(json.dumps(rules, indent=2, ensure_ascii=False))
    print(f"wrote {out_json.relative_to(ROOT)}  {len(rules['rules'])} rules  "
          f"{out_json.stat().st_size:,} bytes")
    (PROV / "eurlex.json").write_text(json.dumps({
        "source": "EUR-Lex, Commission Delegated Regulation (EU) 2020/1818",
        "citation": "Source: EUR-Lex, (c) European Union, 1998-2026",
        "rules_encoded": len(rules["rules"]),
        "definitions_encoded": len(rules["definitions"]),
        "fetched": [eur_prov],
    }, indent=2))
    print(f"wrote {(PROV / 'eurlex.json').relative_to(ROOT)}  1 URL")

    print("\nkey thresholds parsed out of the regulation text:")
    for rid, params in rules["thresholds"].items():
        print(f"  {rid:36s} {params}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
