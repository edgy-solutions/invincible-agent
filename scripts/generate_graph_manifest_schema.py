#!/usr/bin/env python
"""Generate (or --check) the committed JSON Schema for a graph manifest row.

ADR-0050 §1.2, applied to ADR-0046's manifest: *"The schema is a committed artifact generated
from the models... The models and the schema cannot disagree because one is generated from the
other."* Same `--check` shape as `scripts/generate_board.py`, so its reader
(`tests/graph_host/test_graph_manifest_schema_drift.py`) can be the same one test / one
subprocess call — and, per that file's own lesson, the reader ships WITH the generator rather
than after it. A generator nobody invokes is an aspirational seal.

It also VALIDATES every ratified row in `policy/graphs/` against the models, so an invalid row
fails here — and in CI — rather than at boot in a pod. That is §1.3's "validation runs in the
rails" for this family; the rail is the same one ADR-0050 creates.

  python scripts/generate_graph_manifest_schema.py           # write the schema
  python scripts/generate_graph_manifest_schema.py --check   # exit 1 if it would change
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_fleet.graph_host.manifest import (  # noqa: E402
    GraphManifest,
    load_manifests,
    manifest_ref,
)

SCHEMA = ROOT / "schemas" / "graph_manifest.schema.json"
POLICY = ROOT / "policy" / "graphs"


def _rendered() -> str:
    return json.dumps(GraphManifest.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    check = "--check" in sys.argv

    # ── the rows first: a schema that matches the models is worth nothing if the ratified
    # rows do not match either. Failing here names the file, which is what makes it fixable
    # at merge rather than at boot.
    try:
        manifests = load_manifests(POLICY)
    except Exception as exc:
        print(f"INVALID RATIFIED ROW: {exc}")
        return 1

    if not manifests:
        # POSITIVE CONTROL ON THE POPULATION. With zero rows every assertion about rows is
        # vacuously true, and this script would report success the day the policy directory
        # moved. Same floor as the Engine B removal seal, for the same reason.
        print(f"NO RATIFIED ROWS in {POLICY} — either the directory moved or the population "
              f"is empty; both make every row check pass vacuously")
        return 1

    text = _rendered()
    if check:
        current = SCHEMA.read_text(encoding="utf-8") if SCHEMA.exists() else ""
        if current != text:
            print("SCHEMA DRIFT: schemas/graph_manifest.schema.json does not match the models. "
                  "Run scripts/generate_graph_manifest_schema.py")
            return 1
        print(f"schema current; {len(manifests)} ratified row(s) valid")
        for m in manifests:
            print(f"  {manifest_ref(m)}  ->  {m.verb}")
        return 0

    SCHEMA.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA.write_text(text, encoding="utf-8")
    print(f"wrote {SCHEMA.relative_to(ROOT)}; {len(manifests)} ratified row(s) valid")
    for m in manifests:
        print(f"  {manifest_ref(m)}  ->  {m.verb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
