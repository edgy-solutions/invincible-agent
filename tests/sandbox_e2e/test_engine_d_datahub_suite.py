# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Engine D (DataHub) query suite — routed through Engine A.

The user-facing path is Engine A's `search_datahub` tool, which calls
Engine D's /query_metadata. So every test here fires through Engine A
via cortex-bff /orchestrate; we never hit Engine D directly.

Prereqs:

    kubectl -n sandbox port-forward svc/iagent-keycloak  18083:8080 &
    kubectl -n sandbox port-forward svc/iagent-cortex-bff 18090:8090 &

DataHub must be deployed (helm chart) and seeded with the canned
catalog data via scripts/seed_datahub_catalog.py.

Run:
    uv run tests/sandbox_e2e/test_engine_d_datahub_suite.py
    uv run tests/sandbox_e2e/test_engine_d_datahub_suite.py --only ownership
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_client import run  # noqa: E402


# The suite is organized by the kind of question a data engineer or
# decision-maker would actually ask. Each entry is (slug, prompt).
# Engine A's smolagent translates the natural-language ask into one
# or more `search_datahub` calls, then synthesizes a grounded answer.
SUITE = [
    # ---------------- ownership ----------------
    ("ownership_dashboard",
     "Who owns the 'Sales Performance Q1' dashboard in DataHub?"),
    ("ownership_dataset",
     "Who is the owner of the `customers_gold` dataset in our catalog?"),
    ("ownership_by_user",
     "List every dataset and dashboard owned by alice@company.com."),

    # ---------------- freshness ----------------
    ("freshness_dataset",
     "When was the `orders_fact` dataset last updated according to "
     "DataHub?"),
    ("freshness_stale",
     "List all datasets in the catalog that haven't been updated in "
     "the last 30 days."),

    # ---------------- lineage ----------------
    ("lineage_source_of_truth",
     "What is the source of truth for the 'Revenue by Region' "
     "dashboard? Follow the lineage all the way back to the raw source."),
    ("lineage_downstream_impact",
     "If we change the schema of the `customers_silver` table, which "
     "dashboards and downstream datasets will be impacted?"),
    ("lineage_upstream",
     "Show the upstream lineage of the `revenue_summary` dataset — "
     "every dataset that feeds it, transitively."),

    # ---------------- schema ----------------
    ("schema_columns",
     "What are the columns and data types of the `customers_gold` "
     "dataset?"),
    ("schema_primary_key",
     "What is the primary key of the `orders_fact` dataset, and which "
     "downstream datasets reference it?"),

    # ---------------- catalog ----------------
    ("catalog_by_platform",
     "Show me every Superset dashboard registered in the catalog."),
    ("catalog_by_tag",
     "Find every dataset tagged 'pii' that's exposed to a Superset "
     "dashboard."),

    # ---------------- decision-maker ----------------
    ("dm_cost_view",
     "Which datasets in the catalog have the most downstream consumers? "
     "I need to understand what's load-bearing before we plan a refactor."),
    ("dm_compliance",
     "Are there any datasets containing PII that don't have an owner "
     "assigned? List them."),
    ("dm_data_source_audit",
     "For our finance dashboards, what underlying source systems are "
     "we depending on? I need a list for the data-source audit."),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="substring to filter slugs by", default=None)
    args = parser.parse_args()

    todo = [(s, q) for s, q in SUITE if not args.only or args.only.lower() in s]
    if not todo:
        print(f"no tests match --only={args.only!r}")
        return 2

    results = []
    for slug, prompt in todo:
        print()
        print(f"==== [{slug}] {prompt[:80]}... ====")
        try:
            result = run(prompt, session_prefix=f"d-{slug}")
            results.append({"slug": slug, "prompt": prompt, **result})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"slug": slug, "prompt": prompt,
                            "error": str(e), "elapsed_s": 0.0})

    print()
    print("==== summary ====")
    failed = []
    for r in results:
        ok = (r.get("final") is not None
              or (r.get("text") and len(r["text"]) > 200))
        if not ok:
            failed.append(r["slug"])
        print(f"  {'PASS' if ok else 'FAIL'}  "
              f"[{r.get('elapsed_s', 0):6.1f}s]  {r['slug']:32s}")
        if r.get("error"):
            print(f"          error: {r['error']}")
        elif r.get("final"):
            preview = json.dumps(r["final"])[:160]
            print(f"          preview: {preview}")

    print()
    print(f"  {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
