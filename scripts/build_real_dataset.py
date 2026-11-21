"""Build the real Bajaur planning dataset from cached public sources (see fetch_real.py).

Real inputs (data/real/raw/):
  * OSM: district + 7 tehsil boundaries, named settlements, main roads (ODbL)
  * GeoNames PK gazetteer: populated places (CC BY 4.0)
  * HDX "Health Facilities in KP Tribal Districts" (FATA Health Dept, WHO, OCHA; CC BY):
    44 Bajaur facilities with type, coordinates and functional status (registry dated 2018)
  * Census 2023 (PBS) tehsil populations and literacy (data/real/census_2023_bajaur.json)
  * Travel: OSRM car durations on OSM roads + walking time to the nearest road (cached)
  * geoBoundaries Pakistan ADM0/ADM1 outlines (for the national map)

Everything that is NOT observed is listed in ASSUMPTIONS and written into the manifest.
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
import urllib.request
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "real" / "raw"
OUT = ROOT / "data" / "real"
sys.path.insert(0, str(ROOT / "services" / "api"))

from civitwin_engine.dataset.schema import (  # noqa: E402
    Community,
    Dataset,
    DatasetManifest,
    Edge,
    Node,
    ProvenanceRecord,
    Site,
)
from civitwin_engine.dataset.validation import validate_dataset, with_hash  # noqa: E402

UA = "civitwin-hackathon-research/0.1 (offline planning prototype)"
import os
MODE = os.environ.get("CIVITWIN_TRAVEL_MODE", "car")  # "car" or "foot"
OSRM = {"car": "https://router.project-osrm.org/table/v1/driving/",
        "foot": "https://routing.openstreetmap.de/routed-foot/table/v1/driving/"}[MODE]
SERVICE = {"car": "router.project-osrm.org (OSRM demo, car profile, OSM roads)",
           "foot": "routing.openstreetmap.de (FOSSGIS OSRM, foot profile, OSM paths and roads)"}[MODE]
SUFFIX = "" if MODE == "car" else "_walk"
FAR_MIN = 30 if MODE == "car" else 60

ASSUMPTIONS = {
    "visits_per_person_per_year": 1.0,
    "capacity_visits_per_week": {"AHQH": 3000, "THQH": 900, "CH": 900, "Type D HOSP": 700, "RHC": 700,
                                 "CHC": 400, "MCHC": 300, "MHF": 300, "BHU": 300, "SHC": 150, "CD": 150,
                                 "TBC": 100, "NEW_BHU": 300},
    "reactivation_cost_pkr_per_week": 60000,
    "new_bhu_cost_pkr_per_week": 150000,
    "walking_speed_kmh_to_road": 4.0,
    "settlement_weight": {"town": 5, "village": 1, "hamlet": 0.5, "other": 1},
    "settlement_cluster_radius_km": 2.4,
    "new_bhu_candidates": 15,
    "new_bhu_min_spacing_km": 5.0,
    "nearest_sites_kept_per_cluster": 25,
}
TYPE_NAMES = {"AHQH": "Agency Headquarters Hospital", "THQH": "Tehsil Headquarters Hospital", "CH": "Civil Hospital",
              "RHC": "Rural Health Centre", "Type D HOSP": "Type D Hospital", "BHU": "Basic Health Unit",
              "CD": "Civil Dispensary", "CHC": "Community Health Centre", "MCHC": "Mother & Child Health Centre",
              "TBC": "TB Centre", "SHC": "Sub Health Centre", "MHF": "Model Health Facility"}
TEHSIL_ALIASES = {"bar chamer kand": "Bar Chamarkand", "bar chamarkand": "Bar Chamarkand", "barang": "Barang",
                  "khar bajaur": "Khar Bajaur", "mamund": "Mamund", "nawagai": "Nawagai", "salarzai": "Salarzai",
                  "utmankhel": "Utman Khel", "utman khel": "Utman Khel"}


# ---------------------------------------------------------------- geometry helpers
def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lon1, lat1), (lon2, lat2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def stitch(ways: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    segs = [w[:] for w in ways if len(w) > 1]
    rings = []
    while segs:
        ring = segs.pop(0)
        grew = True
        while grew and ring[0] != ring[-1]:
            grew = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]; segs.pop(i); grew = True; break
                if s[-1] == ring[-1]:
                    ring += s[::-1][1:]; segs.pop(i); grew = True; break
        rings.append(ring)
    return rings


def rel_rings(rel: dict) -> list[list[tuple[float, float]]]:
    ways = [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in rel["members"]
            if m["type"] == "way" and m.get("role") in ("outer", "") and m.get("geometry")]
    return [r for r in stitch(ways) if len(r) > 3]


def inside(pt: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    x, y = pt
    c = False
    for i in range(len(ring)):
        x1, y1 = ring[i]; x2, y2 = ring[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def simplify(ring: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker (degrees) for display layers only."""
    if len(ring) < 4:
        return ring

    def rdp(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(pts) < 3:
            return pts
        (x1, y1), (x2, y2) = pts[0], pts[-1]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-12
        idx, dmax = 0, 0.0
        for i in range(1, len(pts) - 1):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / n
            if d > dmax:
                idx, dmax = i, d
        if dmax > tol:
            return rdp(pts[: idx + 1])[:-1] + rdp(pts[idx:])
        return [pts[0], pts[-1]]

    if ring[0] == ring[-1]:
        # closed ring: split at the vertex farthest from the start, simplify both halves
        x0, y0 = ring[0]
        k = max(range(len(ring)), key=lambda i: (ring[i][0] - x0) ** 2 + (ring[i][1] - y0) ** 2)
        out = rdp(ring[: k + 1])[:-1] + rdp(ring[k:])
    else:
        out = rdp(ring)
    return [(round(x, 5), round(y, 5)) for x, y in out]


# ---------------------------------------------------------------- sources
def load_json(name: str) -> dict:
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def load_registry() -> list[dict]:
    import openpyxl

    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(RAW / "hdx_kp_tribal_hf_registry_20180320.xlsx", read_only=True, data_only=True)
    rows = list(wb["FATA_HF_Registry_new"].iter_rows(values_only=True))
    out = []
    for r in rows[1:]:
        if not r[5] or "bajaur" not in str(r[5]).lower():
            continue
        beds = r[16] if isinstance(r[16], (int, float)) else None
        out.append({"sr": int(r[0]), "tehsil_hd": r[7], "full_name": str(r[11]).strip(), "name": str(r[12]).strip(),
                    "type": str(r[13]).strip(), "lat": float(r[14]), "lon": float(r[15]),
                    "beds": int(beds) if beds else None, "functional": str(r[18]).strip() == "Functional",
                    "infrastructure": r[19], "gazetteer_located": str(r[12]).strip().endswith("*")})
    return out


def load_settlements(district: list[tuple[float, float]]) -> list[dict]:
    pts = []
    osm = load_json("osm_places.json")
    for e in osm["elements"]:
        t = e["tags"]
        kind = t.get("place")
        name = t.get("name:en") or t.get("name")
        pt = (e["lon"], e["lat"])
        if name and inside(pt, district):
            pts.append({"name": name, "kind": "town" if kind in ("town", "city") else "village" if kind == "village"
                        else "hamlet" if kind == "hamlet" else "other", "pt": pt, "src": "OSM"})
    z = zipfile.ZipFile(RAW / "geonames_PK.zip")
    xs = [p[0] for p in district]; ys = [p[1] for p in district]
    for line in io.TextIOWrapper(z.open("PK.txt"), encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if f[6] != "P":
            continue
        lat, lon = float(f[4]), float(f[5])
        if not (min(ys) <= lat <= max(ys) and min(xs) <= lon <= max(xs)) or not inside((lon, lat), district):
            continue
        pts.append({"name": f[1], "kind": "village", "pt": (lon, lat), "src": "GeoNames"})
    return pts


# ---------------------------------------------------------------- travel times
def osrm_table(points: list[tuple[float, float]], n_src: int) -> dict:
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in points)
    src = ";".join(str(i) for i in range(n_src))
    dst = ";".join(str(i) for i in range(n_src, len(points)))
    url = f"{OSRM}{coords}?sources={src}&destinations={dst}&annotations=duration,distance"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                body = json.loads(r.read())
            if body.get("code") == "Ok":
                return body
            raise RuntimeError(body.get("code"))
        except Exception as exc:
            print(f"  osrm retry {attempt + 1}: {exc}")
            time.sleep(3 * (attempt + 1))
    raise SystemExit("OSRM unavailable; rerun later (results are cached once fetched)")


def travel_minutes(clusters: list[dict], sites: list[dict]) -> tuple[dict, dict]:
    cache_file = OUT / f"travel_osrm_cache{SUFFIX}.json"
    key = json.dumps([[c["pt"] for c in clusters], [s["pt"] for s in sites]])
    if cache_file.exists():
        cache = json.loads(cache_file.read_text())
        if cache.get("key") == key:
            print("travel: using cached OSRM table")
            return cache["minutes"], cache["meta"]
    dests = [s["pt"] for s in sites]
    batch = max(1, 99 - len(dests))
    minutes: dict[str, float] = {}
    snap_src, snap_dst = {}, {}
    for b in range(0, len(clusters), batch):
        part = clusters[b:b + batch]
        body = osrm_table([c["pt"] for c in part] + dests, len(part))
        for j, w in enumerate(body["destinations"]):
            snap_dst[sites[j]["id"]] = w.get("distance", 0.0)
        for i, c in enumerate(part):
            snap_src[c["id"]] = body["sources"][i].get("distance", 0.0)
            for j, s in enumerate(sites):
                d = body["durations"][i][j]
                if d is None:
                    continue
                walk_m = snap_src[c["id"]] + snap_dst[s["id"]]
                walk_min = walk_m / 1000 / ASSUMPTIONS["walking_speed_kmh_to_road"] * 60
                minutes[f"{c['id']}|{s['id']}"] = round(d / 60 + walk_min, 1)
        print(f"  osrm batch {b // batch + 1}: {len(part)} clusters x {len(dests)} sites")
        time.sleep(1.2)  # be polite to the public demo server
    meta = {"service": SERVICE, "mode": MODE,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "walk_to_road": f"snap distance at {ASSUMPTIONS['walking_speed_kmh_to_road']} km/h added",
            "max_snap_m": round(max(list(snap_src.values()) + list(snap_dst.values()) + [0]), 1)}
    cache_file.write_text(json.dumps({"key": key, "minutes": minutes, "meta": meta}))
    return minutes, meta


# ---------------------------------------------------------------- build
def main() -> None:
    census = json.loads((OUT / "census_2023_bajaur.json").read_text())
    pop_by_tehsil = {t["name"]: t["pop_2023"] for t in census["tehsils"]}
    lit_by_tehsil = {t["name"]: t["literacy_2023_pct"] for t in census["tehsils"]}

    district = rel_rings(load_json("osm_district.json")["elements"][0])
    district = max(district, key=len)
    tehsils = {}
    for rel in load_json("osm_tehsils.json")["elements"]:
        nm = (rel["tags"].get("name:en") or rel["tags"].get("name", "")).replace(" Tehsil", "").strip().lower()
        canon = TEHSIL_ALIASES.get(nm)
        if canon:
            tehsils[canon] = max(rel_rings(rel), key=len)
    assert set(tehsils) == set(pop_by_tehsil), (set(tehsils), set(pop_by_tehsil))

    def tehsil_of(pt: tuple[float, float]) -> str:
        for name, ring in tehsils.items():
            if inside(pt, ring):
                return name
        # boundary slivers: nearest tehsil by vertex distance
        return min(tehsils, key=lambda n: min(haversine_km(pt, v) for v in tehsils[n][::5]))

    # settlements -> demand clusters, population from census by tehsil
    settle = load_settlements(district)
    for s in settle:
        s["tehsil"] = tehsil_of(s["pt"])
    order = {"town": 0, "village": 1, "other": 2, "hamlet": 3}
    settle.sort(key=lambda s: (order[s["kind"]], s["src"] != "OSM", s["name"]))
    R = ASSUMPTIONS["settlement_cluster_radius_km"]
    clusters: list[dict] = []
    for s in settle:
        best = None
        for c in clusters:
            if c["tehsil"] == s["tehsil"] and haversine_km(c["pt"], s["pt"]) <= R:
                best = c; break
        if best is None:
            clusters.append({"name": s["name"], "pt": s["pt"], "tehsil": s["tehsil"], "members": [s], "kind": s["kind"]})
        else:
            best["members"].append(s)
    for t, pop in pop_by_tehsil.items():
        cs = [c for c in clusters if c["tehsil"] == t]
        if not cs:  # tehsil with no mapped settlement: use its centroid
            ring = tehsils[t]
            pt = (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
            clusters.append({"name": f"{t} (centre)", "pt": pt, "tehsil": t, "members": [], "kind": "other"})
            cs = clusters[-1:]
        w = {id(c): sum(ASSUMPTIONS["settlement_weight"][m["kind"]] for m in c["members"]) or 1 for c in cs}
        tot = sum(w.values())
        acc = 0
        for k, c in enumerate(cs):
            share = pop if k == len(cs) - 1 else round(pop * w[id(c)] / tot)
            if k == len(cs) - 1:
                share = pop - acc
            c["population"] = share
            acc += share
    clusters.sort(key=lambda c: (c["tehsil"], -c["population"]))
    for i, c in enumerate(clusters, 1):
        c["id"] = f"V{i:03d}"
    print(f"settlements: {len(settle)} points -> {len(clusters)} demand clusters")
    assert sum(c["population"] for c in clusters) == census["district_total"]

    # facilities
    reg = load_registry()
    cap = ASSUMPTIONS["capacity_visits_per_week"]
    sites: list[dict] = []
    for f in sorted(reg, key=lambda f: f["sr"]):
        sites.append({"id": f"H{f['sr']:04d}", "label": f["full_name"].rstrip("* "), "pt": (f["lon"], f["lat"]),
                      "kind": "existing" if f["functional"] else "reactivate", "ftype": f["type"],
                      "capacity": cap.get(f["type"], 150), "cost": 0 if f["functional"] else ASSUMPTIONS["reactivation_cost_pkr_per_week"],
                      "beds": f["beds"], "tehsil": tehsil_of((f["lon"], f["lat"])), "gazetteer_located": f["gazetteer_located"],
                      "infrastructure": f["infrastructure"]})
    print(f"facilities: {sum(s['kind'] == 'existing' for s in sites)} functional, {sum(s['kind'] == 'reactivate' for s in sites)} non-functional")

    # first travel pass to existing + reactivation sites, to locate underserved clusters for new-BHU candidates
    minutes, tmeta = travel_minutes(clusters, sites)
    func = [s for s in sites if s["kind"] == "existing"]
    def nearest(c: dict, pool: list[dict]) -> float:
        vals = [minutes.get(f"{c['id']}|{s['id']}") for s in pool]
        vals = [v for v in vals if v is not None]
        return min(vals) if vals else 999.0
    for c in clusters:
        c["nearest_functional_min"] = nearest(c, func)
    far = sorted([c for c in clusters if c["nearest_functional_min"] > FAR_MIN], key=lambda c: -c["population"])
    picks: list[dict] = []
    for c in far:
        if all(haversine_km(c["pt"], p["pt"]) >= ASSUMPTIONS["new_bhu_min_spacing_km"] for p in picks) and \
                all(haversine_km(c["pt"], s["pt"]) >= 2.0 for s in sites):
            picks.append(c)
        if len(picks) >= ASSUMPTIONS["new_bhu_candidates"]:
            break
    for k, c in enumerate(picks, 1):
        sites.append({"id": f"N{k:02d}", "label": f"New BHU at {c['name']}", "pt": c["pt"], "kind": "new", "ftype": "NEW_BHU",
                      "capacity": cap["NEW_BHU"], "cost": ASSUMPTIONS["new_bhu_cost_pkr_per_week"], "beds": None,
                      "tehsil": c["tehsil"], "gazetteer_located": False, "infrastructure": None, "village": c["name"]})
    minutes, tmeta = travel_minutes(clusters, sites)  # full table including candidates (cached)

    # engine dataset
    vpy = ASSUMPTIONS["visits_per_person_per_year"]
    nodes, edges, comms, sts = [], [], [], []
    for c in clusters:
        nodes.append(Node(id=f"n{c['id']}", label=c["name"], display_x=round(c["pt"][0], 6), display_y=round(c["pt"][1], 6)))
        zone = "central" if c["nearest_functional_min"] <= FAR_MIN else ("rural" if c["nearest_functional_min"] <= 2 * FAR_MIN else "remote")
        comms.append(Community(id=c["id"], label=f"{c['name']} ({c['tehsil']})", demand_visits_per_week=round(c["population"] * vpy / 52),
                               population=c["population"], zone_class=zone, node_id=f"n{c['id']}"))
    for s in sites:
        nodes.append(Node(id=f"n{s['id']}", label=s["label"], display_x=round(s["pt"][0], 6), display_y=round(s["pt"][1], 6)))
        sts.append(Site(id=s["id"], label=s["label"], type="existing" if s["kind"] == "existing" else "candidate",
                        node_id=f"n{s['id']}", capacity_per_week=s["capacity"], fixed_cost_pkr=s["cost"], eligible=True))
    K = ASSUMPTIONS["nearest_sites_kept_per_cluster"]
    for c in clusters:
        pairs = sorted(((minutes[f"{c['id']}|{s['id']}"], s["id"]) for s in sites if f"{c['id']}|{s['id']}" in minutes))[:K]
        for m, sid in pairs:
            edges.append(Edge(from_node=f"n{c['id']}", to_node=f"n{sid}", minutes=max(0.5, m), direction="one_way"))
    manifest = DatasetManifest(
        id="bajaur-real-v1" if MODE == "car" else "bajaur-real-walk-v1", version="1", district_label="Bajaur District, Khyber Pakhtunkhwa — real public data" + (" (by vehicle)" if MODE == "car" else " (on foot)"),
        is_synthetic=False, source_url="https://data.humdata.org/dataset/health-facilities-in-khyber-pakhtunkhwa-tribal-districts",
        source_date="2026-11-21", license="Mixed open licences: ODbL (OSM), CC BY 4.0 (GeoNames), CC BY (HDX registry), PBS census figures",
        assumptions=(
            "Population: PBS Census 2023 tehsil totals (1,287,960), shared across real mapped settlements (OSM + GeoNames) by settlement weight; settlement sizes are not published, so the split inside a tehsil is estimated.",
            f"Demand: {vpy} public primary-care visit per person per year (assumption) — weekly visits = population x {vpy} / 52.",
            "Facilities: 44 government health facilities from the FATA Health Department / WHO registry (OCHA, 2018). Functional facilities are open; the 7 listed as non-functional are candidates for reactivation. Status may have changed since 2018.",
            "Facility locations come from the NGA/FATA gazetteer or catchment villages, not field GPS (registry note).",
            "Capacity per facility type (visits/week) and weekly-equivalent costs are planning assumptions, not official figures.",
            f"New BHU candidates: up to {ASSUMPTIONS['new_bhu_candidates']} most-populous settlement clusters more than {FAR_MIN} minutes from any functional facility, at least {ASSUMPTIONS['new_bhu_min_spacing_km']} km apart.",
            ("Travel time: OSRM car durations on OpenStreetMap roads plus walking to the nearest road at 4 km/h. Families without vehicles, mountain conditions and seasons make real journeys longer." if MODE == "car" else "Travel time: OSRM walking durations on OpenStreetMap paths and roads (FOSSGIS foot profile). Steep terrain, weather and seasons can make real journeys longer."),
            "Education coordination uses real tehsil literacy rates (Census 2023); school locations are not openly published for Bajaur.",
        ),
        model_scope="Primary health care access across Bajaur's 7 tehsils, one modeled week; coordinated with education need by tehsil.",
        generator={"builder": "scripts/build_real_dataset.py", "clusters": len(clusters), "sites": len(sites)},
    )
    prov = (
        ProvenanceRecord(entity="community", field="population", source="PBS Census 2023 tehsil totals + OSM/GeoNames settlements", method="estimated", timestamp="2026-11-21", caveat="Within-tehsil split by settlement weight"),
        ProvenanceRecord(entity="community", field="demand_visits_per_week", source="population x visits-per-person assumption", method="estimated", timestamp="2026-11-21", caveat="Utilisation rate is an assumption"),
        ProvenanceRecord(entity="site", field="location/type/status", source="HDX: FATA Health Dept, WHO, OCHA registry v2 (2018-03-20)", method="observed", timestamp="2018-03-20", caveat="Gazetteer-based coordinates; status as of registry"),
        ProvenanceRecord(entity="site", field="capacity_per_week", source="assumption by facility type", method="estimated", timestamp="2026-11-21", caveat="Replace with DHIS OPD statistics"),
        ProvenanceRecord(entity="site", field="fixed_cost_pkr", source="assumption", method="estimated", timestamp="2026-11-21", caveat="Planning cost, not procurement price"),
        ProvenanceRecord(entity="edge", field="minutes", source=tmeta["service"], method="estimated", timestamp=tmeta["fetched_at"], caveat=tmeta["walk_to_road"]),
    )
    ds = with_hash(Dataset(manifest=manifest, nodes=tuple(nodes), edges=tuple(edges), communities=tuple(comms),
                           sites=tuple(sts), provenance=prov))
    ds = validate_dataset(ds.model_dump(mode="json"))
    (OUT / f"bajaur_real{SUFFIX}_v1.json").write_text(json.dumps(ds.model_dump(mode="json"), ensure_ascii=False, indent=1))

    # GIS layers for the map (display only)
    pak = json.loads((RAW / "gb_PAK_ADM0_simplified.geojson").read_text())
    adm1 = json.loads((RAW / "gb_PAK_ADM1_simplified.geojson").read_text())
    def polys(geom: dict) -> list[list[list[float]]]:
        cs = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        return [simplify([tuple(p) for p in poly[0]], 0.02) for poly in cs if len(poly[0]) > 20]
    roads = []
    for w in load_json("osm_roads.json")["elements"]:
        g = w.get("geometry")
        if g:
            roads.append({"class": w["tags"].get("highway"), "name": w["tags"].get("name:en") or w["tags"].get("name"),
                          "pts": simplify([(p["lon"], p["lat"]) for p in g], 0.0004)})
    lit_mean = sum(lit_by_tehsil[t] * pop_by_tehsil[t] for t in pop_by_tehsil) / census["district_total"]
    geo = {
        "attribution": ["© OpenStreetMap contributors (ODbL)", "GeoNames (CC BY 4.0)", "geoBoundaries (gbOpen)",
                        "FATA Health Department, WHO; OCHA Pakistan (HDX, CC BY)", "Pakistan Bureau of Statistics, Census 2023",
                        "Routing: OSRM / project-osrm.org"],
        "pakistan": [p for f in pak["features"] for p in polys(f["geometry"])],
        "provinces": [{"name": f["properties"]["shapeName"], "rings": polys(f["geometry"])} for f in adm1["features"]],
        "district": simplify(district, 0.0008),
        "tehsils": [{"name": t, "ring": simplify(r, 0.0008), "population": pop_by_tehsil[t], "literacy_pct": lit_by_tehsil[t],
                     "area_km2": next(x["area_km2"] for x in census["tehsils"] if x["name"] == t)} for t, r in tehsils.items()],
        "literacy_district_weighted_pct": round(lit_mean, 2),
        "roads": roads,
        "settlements": [{"name": s["name"], "lon": round(s["pt"][0], 5), "lat": round(s["pt"][1], 5), "src": s["src"], "kind": s["kind"]} for s in settle],
        "clusters": [{"id": c["id"], "name": c["name"], "tehsil": c["tehsil"], "lon": round(c["pt"][0], 5), "lat": round(c["pt"][1], 5),
                      "population": c["population"], "members": len(c["members"]), "nearest_functional_min": c["nearest_functional_min"]} for c in clusters],
        "facilities": [{"id": s["id"], "label": s["label"], "lon": round(s["pt"][0], 5), "lat": round(s["pt"][1], 5), "kind": s["kind"],
                        "type": s["ftype"], "type_name": TYPE_NAMES.get(s["ftype"], "New Basic Health Unit (proposed)"), "tehsil": s["tehsil"],
                        "beds": s["beds"], "capacity": s["capacity"], "cost": s["cost"], "gazetteer_located": s["gazetteer_located"]} for s in sites],
        "travel": tmeta,
        "assumptions": ASSUMPTIONS,
    }
    (OUT / f"bajaur_geo{SUFFIX}.json").write_text(json.dumps(geo, ensure_ascii=False))
    print(f"dataset: {len(comms)} clusters, {len(sts)} sites ({sum(s.type == 'candidate' for s in sts)} candidates), {len(edges)} edges")
    print(f"sha256 {ds.manifest.sha256}")
    print("demand visits/week", sum(c.demand_visits_per_week for c in comms), "functional capacity", sum(s.capacity_per_week for s in sts if s.type == "existing"))


if __name__ == "__main__":
    main()
