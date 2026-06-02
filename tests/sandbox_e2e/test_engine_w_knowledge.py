# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Engine W (mesh:retrieveKnowledge) end-to-end sandbox test.

Fires a maintenance-domain knowledge-retrieval query through
cortex-bff /orchestrate and verifies that Engine W returns a
markdown response citing a real manual document.

Prereqs (port-forwards in the background):

    kubectl -n sandbox port-forward svc/iagent-keycloak  18083:8080 &
    kubectl -n sandbox port-forward svc/iagent-cortex-bff 18090:8090 &

Weaviate must have a populated DocumentChunk collection
(see scripts/seed_weaviate_manuals.py).

Run:
    uv run tests/sandbox_e2e/test_engine_w_knowledge.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_client import run  # noqa: E402


QUERIES = [
    "Search the maintenance manuals: what are the common failure modes "
    "of an aircraft auxiliary fuel pump?",
    "Search the maintenance manuals: what is the inspection schedule for "
    "the C-130 APU?",
    "Search the manufacturing manuals: what is the standard cure cycle "
    "for an epoxy carbon fiber laminate?",
]


def main() -> int:
    results = []
    for q in QUERIES:
        print()
        print(f"==== query: {q[:80]}... ====")
        result = run(q, session_prefix="w")
        results.append({"query": q, **result})

    print()
    print("==== summary ====")
    for r in results:
        ok = r.get("final") is not None or (r.get("text") and len(r["text"]) > 200)
        print(f"  {'PASS' if ok else 'FAIL'}  "
              f"[{r['elapsed_s']:6.1f}s]  {r['query'][:60]}")
        if r.get("final"):
            payload_str = json.dumps(r["final"])[:200]
            print(f"          final preview: {payload_str}")

    failed = [r for r in results if not (r.get("final") or (r.get("text") and len(r["text"]) > 200))]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
