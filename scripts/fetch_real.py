"""Fetch real, public data for Bajaur District (run once with internet; results are cached).

Sources (attribution is stored with every file):
  * OpenStreetMap via the Overpass API — boundary, tehsils, health facilities, schools,
    settlements, main roads. © OpenStreetMap contributors, ODbL 1.0.
  * Travel times: OSRM (project-osrm.org demo server, car profile on OSM roads) — fetched by
    scripts/build_real_dataset.py.
Security-sensitive features (police, military, checkposts) are deliberately NOT fetched.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "real" / "raw"
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "civitwin-hackathon-research/0.1 (offline planning prototype)"
DISTRICT_REL = 11010950  # OSM relation "Bajaur District" (admin_level 6)
AREA = f"area(id:{3600000000 + DISTRICT_REL})->.a;"

QUERIES = {
    "district": f"[out:json][timeout:120];relation({DISTRICT_REL});out geom;",
    "tehsils": f"[out:json][timeout:180];{AREA}relation(area.a)[boundary=administrative][admin_level~\"^(7|8)$\"];out geom;",
    "health": f"[out:json][timeout:180];{AREA}(nwr(area.a)[amenity~\"^(hospital|clinic|doctors|health_post)$\"];nwr(area.a)[healthcare];);out center tags;",
    "education": f"[out:json][timeout:180];{AREA}nwr(area.a)[amenity~\"^(school|college|university)$\"];out center tags;",
    "places": f"[out:json][timeout:180];{AREA}node(area.a)[place~\"^(city|town|village|hamlet|suburb|neighbourhood|locality)$\"];out body;",
    "roads": f"[out:json][timeout:180];{AREA}way(area.a)[highway~\"^(trunk|primary|secondary|tertiary)$\"];out geom;",
}


def fetch(name: str, q: str) -> None:
    out = RAW / f"osm_{name}.json"
    if out.exists() and "--force" not in sys.argv:
        print(f"cached   {out.name}")
        return
    data = urllib.parse.urlencode({"data": q}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(OVERPASS, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=240) as r:
                body = json.loads(r.read())
            body["_civitwin"] = {"source": "OpenStreetMap via Overpass API", "endpoint": OVERPASS,
                                 "query": q, "fetched_at": datetime.now(UTC).isoformat(),
                                 "license": "ODbL 1.0 — © OpenStreetMap contributors"}
            out.write_text(json.dumps(body, ensure_ascii=False))
            print(f"fetched  {out.name}: {len(body.get('elements', []))} elements")
            return
        except Exception as exc:  # network is flaky here; retry politely
            print(f"retry {attempt + 1} {name}: {type(exc).__name__}: {exc}")
            time.sleep(10 * (attempt + 1))
    raise SystemExit(f"could not fetch {name}")


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    for name, q in QUERIES.items():
        fetch(name, q)
        time.sleep(3)
