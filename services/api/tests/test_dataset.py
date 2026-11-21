"""Seed determinism, hashing and import validation (FR-01, FR-02, T06)."""

import pytest

from civitwin_engine.dataset.generator import generate_demo_dataset
from civitwin_engine.dataset.validation import (
    DatasetValidationError,
    dataset_hash,
    validate_dataset,
)


def test_generator_is_deterministic():
    a, b = generate_demo_dataset(), generate_demo_dataset()
    assert a.manifest.sha256 == b.manifest.sha256
    assert a.model_dump() == b.model_dump()
    assert generate_demo_dataset(seed=7).manifest.sha256 != a.manifest.sha256


def test_demo_shape_matches_srs():
    ds = generate_demo_dataset()
    assert [c.id for c in ds.communities] == [f"C{i:02d}" for i in range(1, 25)]
    assert [s.id for s in ds.sites if s.type == "existing"] == [f"E{i:02d}" for i in range(1, 6)]
    assert [s.id for s in ds.sites if s.type == "candidate"] == [f"N{i:02d}" for i in range(1, 9)]
    assert ds.manifest.is_synthetic and "synthetic" in ds.manifest.district_label
    for c in ds.communities:
        assert 30 <= c.demand_visits_per_week <= 110
    for s in ds.sites:
        if s.type == "candidate":
            assert 180 <= s.capacity_per_week <= 300
            assert 90_000 <= s.fixed_cost_pkr <= 160_000


def test_hash_excludes_its_own_field():
    ds = generate_demo_dataset()
    assert dataset_hash(ds) == ds.manifest.sha256
    assert len(ds.manifest.sha256) == 64


def test_roundtrip_import_accepts_valid_bundle():
    ds = generate_demo_dataset()
    again = validate_dataset(ds.model_dump(mode="json"))
    assert again.manifest.sha256 == ds.manifest.sha256


def _bundle():
    return generate_demo_dataset().model_dump(mode="json")


def test_t06_duplicate_ids_rejected_with_row_errors():
    raw = _bundle()
    raw["communities"][1]["id"] = raw["communities"][0]["id"]
    with pytest.raises(DatasetValidationError) as exc:
        validate_dataset(raw)
    errs = exc.value.errors
    assert any(e["code"] == "duplicate_id" and e["row"] == 1 for e in errs)


def test_t06_bad_reference_negative_value_unknown_column():
    raw = _bundle()
    raw["edges"][0]["to_node"] = "nowhere"
    with pytest.raises(DatasetValidationError) as exc:
        validate_dataset(raw)
    assert any(e["code"] == "unknown_node" for e in exc.value.errors)

    raw = _bundle()
    raw["communities"][3]["demand_visits_per_week"] = -5
    with pytest.raises(DatasetValidationError) as exc:
        validate_dataset(raw)
    assert exc.value.errors[0]["entity"] == "communities" and exc.value.errors[0]["row"] == 3

    raw = _bundle()
    raw["sites"][0]["secret_column"] = 1
    with pytest.raises(DatasetValidationError):
        validate_dataset(raw)

    raw = _bundle()
    raw["edges"][0]["minutes"] = 0
    with pytest.raises(DatasetValidationError):
        validate_dataset(raw)


def test_tampered_content_with_stale_hash_rejected():
    raw = _bundle()
    raw["communities"][0]["demand_visits_per_week"] += 1
    with pytest.raises(DatasetValidationError) as exc:
        validate_dataset(raw)
    assert exc.value.errors[0]["code"] == "hash_mismatch"
