"""Write the deterministic synthetic datasets and JSON schemas to data/ (idempotent)."""

from __future__ import annotations

import json
from pathlib import Path

from civitwin_engine.dataset.generator import generate_demo_dataset, generate_disconnected_fixture
from civitwin_engine.dataset.schema import Dataset
from civitwin_engine.fixtures import golden_dataset
from civitwin_engine.planspec import PlanSpec

ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        print(f"unchanged  {path.relative_to(ROOT)}")
        return
    path.write_text(text, encoding="utf-8")
    print(f"wrote      {path.relative_to(ROOT)}")


def main() -> None:
    demo = generate_demo_dataset()
    write(ROOT / "data/demo/demo-bajaur-v1.json", demo.model_dump(mode="json"))
    write(ROOT / "data/fixtures/disconnected.json",
          generate_disconnected_fixture().model_dump(mode="json"))
    write(ROOT / "data/fixtures/golden.json", golden_dataset().model_dump(mode="json"))
    write(ROOT / "data/schemas/dataset.schema.json", Dataset.model_json_schema())
    write(ROOT / "data/schemas/planspec.schema.json", PlanSpec.model_json_schema())
    print(f"demo dataset sha256 {demo.manifest.sha256}")


if __name__ == "__main__":
    main()
