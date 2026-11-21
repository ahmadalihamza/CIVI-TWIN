"""Deterministic synthetic dataset generator (SRS §4.2).

Everything produced here is fictional: no real facility names, coordinates, staff
locations or patient data. Positions are schematic display positions only.
"""

from __future__ import annotations

import math
import random

from .schema import Community, Dataset, DatasetManifest, Edge, Node, ProvenanceRecord, Site
from .validation import with_hash

DEFAULT_SEED = 2026
GENERATED_AT = "2026-11-20T00:00:00Z"  # fixed so the dataset hash is reproducible

# Calibrated ranges (see docs/IMPLEMENTATION_STATUS.md, decision D2): the SRS
# illustrative demand range 40-160 made demand ~2x existing capacity, so demand is
# drawn from 30-110 visits/week instead. Other ranges follow SRS §4.2.
DEMAND_RANGE = (30, 110)
EXISTING_CAPACITY_RANGE = (150, 300)
CANDIDATE_CAPACITY_RANGE = (180, 300)
CANDIDATE_COST_RANGE_K = (90, 160)  # thousands of PKR per week
MINUTES_PER_UNIT = 1.25  # schematic distance unit -> travel minutes
TERRAIN_FACTOR_RANGE = (1.0, 1.6)
INELIGIBLE_CANDIDATES = ("N05",)  # chosen so no cluster is left with zero reachable sites

WIDTH, HEIGHT = 100.0, 80.0


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _sample_points(
    rng: random.Random,
    n: int,
    box: tuple[float, float, float, float],
    min_gap: float,
    taken: list[tuple[float, float]],
    accept=lambda p: True,
) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = box
    out: list[tuple[float, float]] = []
    attempts = 0
    while len(out) < n:
        attempts += 1
        if attempts > 20000:
            raise RuntimeError("could not place points; relax spacing")
        p = (round(rng.uniform(x0, x1), 1), round(rng.uniform(y0, y1), 1))
        if all(_dist(p, q) >= min_gap for q in taken + out) and accept(p):
            out.append(p)
    return out


def _connect(
    rng: random.Random, positions: dict[str, tuple[float, float]], k: int = 3
) -> list[Edge]:
    """k-nearest-neighbour road network, then bridge components so it is connected."""
    ids = sorted(positions)
    pairs: set[tuple[str, str]] = set()
    for a in ids:
        near = sorted((b for b in ids if b != a), key=lambda b: (_dist(positions[a], positions[b]), b))
        for b in near[:k]:
            pairs.add(tuple(sorted((a, b))))  # type: ignore[arg-type]

    parent = {i: i for i in ids}

    def find(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in pairs:
        parent[find(a)] = find(b)
    while len({find(i) for i in ids}) > 1:
        best = min(
            ((a, b) for a in ids for b in ids if a < b and find(a) != find(b)),
            key=lambda ab: (_dist(positions[ab[0]], positions[ab[1]]), ab),
        )
        pairs.add(best)
        parent[find(best[0])] = find(best[1])

    edges = []
    for a, b in sorted(pairs):
        terrain = rng.uniform(*TERRAIN_FACTOR_RANGE)
        minutes = max(1, round(_dist(positions[a], positions[b]) * MINUTES_PER_UNIT * terrain))
        edges.append(Edge(from_node=a, to_node=b, minutes=float(minutes), direction="two_way"))
    return edges


def generate_demo_dataset(seed: int = DEFAULT_SEED) -> Dataset:
    rng = random.Random(seed)

    existing_pos = _sample_points(rng, 5, (35, 28, 68, 54), 9.0, [])

    def far_from_existing(p: tuple[float, float]) -> bool:
        return min(_dist(p, e) for e in existing_pos) >= 22

    candidate_pos = _sample_points(rng, 8, (4, 4, 96, 76), 14.0, existing_pos, far_from_existing)
    community_pos = _sample_points(rng, 24, (3, 3, 97, 77), 7.5, existing_pos + candidate_pos)

    nodes: list[Node] = []
    positions: dict[str, tuple[float, float]] = {}
    for i, p in enumerate(existing_pos, 1):
        nid = f"V-E{i:02d}"
        positions[nid] = p
        nodes.append(Node(id=nid, label=f"Existing site E{i:02d} location", display_x=p[0],
                          display_y=p[1]))
    for i, p in enumerate(candidate_pos, 1):
        nid = f"V-N{i:02d}"
        positions[nid] = p
        nodes.append(Node(id=nid, label=f"Candidate zone N{i:02d} location", display_x=p[0],
                          display_y=p[1]))
    for i, p in enumerate(community_pos, 1):
        nid = f"V-C{i:02d}"
        positions[nid] = p
        nodes.append(Node(id=nid, label=f"Cluster C{i:02d} centre", display_x=p[0],
                          display_y=p[1]))

    edges = _connect(rng, positions)

    communities = []
    for i, p in enumerate(community_pos, 1):
        d_exist = min(_dist(p, e) for e in existing_pos)
        zone = "central" if d_exist < 15 else ("rural" if d_exist < 32 else "remote")
        communities.append(
            Community(
                id=f"C{i:02d}",
                label=f"Cluster C{i:02d} (synthetic)",
                demand_visits_per_week=rng.randint(*DEMAND_RANGE),
                population=rng.randint(20, 150) * 100,
                zone_class=zone,
                node_id=f"V-C{i:02d}",
            )
        )

    sites = []
    for i in range(1, 6):
        sites.append(
            Site(
                id=f"E{i:02d}",
                label=f"Existing service site E{i:02d} (synthetic)",
                type="existing",
                node_id=f"V-E{i:02d}",
                capacity_per_week=rng.randint(EXISTING_CAPACITY_RANGE[0] // 10,
                                              EXISTING_CAPACITY_RANGE[1] // 10) * 10,
                fixed_cost_pkr=0,
                eligible=True,
            )
        )
    for i in range(1, 9):
        sid = f"N{i:02d}"
        sites.append(
            Site(
                id=sid,
                label=f"Candidate zone {sid} (synthetic)",
                type="candidate",
                node_id=f"V-N{i:02d}",
                capacity_per_week=rng.randint(CANDIDATE_CAPACITY_RANGE[0] // 10,
                                              CANDIDATE_CAPACITY_RANGE[1] // 10) * 10,
                fixed_cost_pkr=rng.randint(CANDIDATE_COST_RANGE_K[0] // 5,
                                           CANDIDATE_COST_RANGE_K[1] // 5) * 5000,
                eligible=sid not in INELIGIBLE_CANDIDATES,
            )
        )

    caveat = "Fictional value generated for demonstration; not a real district statistic."
    provenance = tuple(
        ProvenanceRecord(entity=entity, field=field, source=f"civitwin generator seed {seed}",
                         method="synthetic", timestamp=GENERATED_AT, caveat=caveat)
        for entity, field in [
            ("community", "demand_visits_per_week"),
            ("community", "population"),
            ("site", "capacity_per_week"),
            ("site", "fixed_cost_pkr"),
            ("site", "eligible"),
            ("edge", "minutes"),
            ("node", "display_x/display_y"),
        ]
    )

    manifest = DatasetManifest(
        id="demo-bajaur-v1",
        version="1",
        district_label="Bajaur — synthetic planning sandbox",
        is_synthetic=True,
        source_url=None,
        source_date="2026-11-20",
        license="CC0-1.0 (synthetic demonstration data)",
        assumptions=(
            "All values are synthetic and do not describe the real district.",
            "Demand means scheduled outpatient visits requested per week, not people.",
            "Costs are illustrative weekly-equivalent planning costs in PKR, not procurement prices.",
            "Travel minutes come from a schematic road network, not real roads or terrain.",
            "Population is descriptive only and is not used to compute demand.",
            f"Candidate(s) {', '.join(INELIGIBLE_CANDIDATES)} marked ineligible to exercise the "
            "eligibility constraint.",
        ),
        model_scope="Non-emergency outpatient accessibility, one modeled week, aggregate clusters.",
        generator={
            "seed": seed,
            "demand_range": list(DEMAND_RANGE),
            "existing_capacity_range": list(EXISTING_CAPACITY_RANGE),
            "candidate_capacity_range": list(CANDIDATE_CAPACITY_RANGE),
            "candidate_cost_range_pkr": [CANDIDATE_COST_RANGE_K[0] * 1000,
                                         CANDIDATE_COST_RANGE_K[1] * 1000],
            "neighbours_per_node": 3,
        },
    )

    return with_hash(
        Dataset(manifest=manifest, nodes=tuple(nodes), edges=tuple(edges),
                communities=tuple(communities), sites=tuple(sites), provenance=provenance)
    )


def generate_disconnected_fixture() -> Dataset:
    """Separate test fixture: cluster D03 has no road at all (SRS §4.2, T03)."""
    nodes = (
        Node(id="v1", label="v1", display_x=10, display_y=10),
        Node(id="v2", label="v2", display_x=30, display_y=10),
        Node(id="v3", label="v3", display_x=90, display_y=70),
        Node(id="ve", label="ve", display_x=20, display_y=20),
        Node(id="vn", label="vn", display_x=40, display_y=20),
    )
    edges = (
        Edge(from_node="v1", to_node="ve", minutes=10, direction="two_way"),
        Edge(from_node="v2", to_node="ve", minutes=35, direction="two_way"),
        Edge(from_node="v2", to_node="vn", minutes=12, direction="two_way"),
    )
    communities = (
        Community(id="D01", label="D01", demand_visits_per_week=50, zone_class="central",
                  node_id="v1"),
        Community(id="D02", label="D02", demand_visits_per_week=40, zone_class="rural",
                  node_id="v2"),
        Community(id="D03", label="D03 (no road)", demand_visits_per_week=30,
                  zone_class="remote", node_id="v3"),
    )
    sites = (
        Site(id="DE1", label="DE1", type="existing", node_id="ve", capacity_per_week=200,
             fixed_cost_pkr=0, eligible=True),
        Site(id="DN1", label="DN1", type="candidate", node_id="vn", capacity_per_week=100,
             fixed_cost_pkr=100_000, eligible=True),
    )
    manifest = DatasetManifest(
        id="fixture-disconnected-v1", version="1", district_label="Test fixture (disconnected)",
        is_synthetic=True, source_date="2026-11-20", license="CC0-1.0",
        model_scope="Test fixture only.",
        assumptions=("Cluster D03 has no road connection.",),
    )
    return with_hash(Dataset(manifest=manifest, nodes=nodes, edges=edges,
                             communities=communities, sites=sites))
