"""Report the access grants that enforce but are not in committed policy.

Two lists, both READ-ONLY (this script writes neither the ledger nor the directory):
  ledger     approved and recorded in `access_grant_ledger`, awaiting a commit to policy
             (ADR-0062 section 7), with who asked, who approved, when and why.
  directory  `reader` relations live in the directory that neither committed policy nor the
             ledger names: a hand write, and the ones to chase.

Env: PROJECTOR_POSTGRES_DSN (the ledger), TOPAZ_DIRECTORY_URL (the directory; omit to skip that
list), ASSET_GRANTS_FILE (committed policy). Run from the repo root with this tree's venv:
  uv run python scripts/report_access_grants.py
Exit 0 when both lists are empty, 1 when either is not (so a schedule can alarm on it).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "policy" / "sync"))


def _live(url: str) -> set:
    from grant_sync import MANAGED_GRANT_RELATIONS
    from topaz_sync import TopazClient

    out = set()
    with TopazClient(url) as client:
        for obj_type, rel in MANAGED_GRANT_RELATIONS:
            for r in client.list_relations(object_type=obj_type, relation=rel):
                out.add((r.subject_id, r.object_id, r.object_type))
    return out


def main() -> int:
    from src.iagent import human_tasks as ht

    url = os.getenv("TOPAZ_DIRECTORY_URL", "").strip()
    report = ht.grants_absent_from_policy(_live(url) if url else None)
    print(f"ledger grants not in committed policy: {len(report['ledger'])}")
    for r in report["ledger"]:
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["granted_at"] / 1000))
        print(f"  {r['subject']} -> {r['asset']} ({r['kind']}) asked by {r['requested_by']}, "
              f"approved by {r['granted_by']} at {at}: {r['reason']}")
    if url:
        print(f"directory grants in neither policy nor ledger: {len(report['directory'])}")
        for subject, asset, kind in report["directory"]:
            print(f"  {subject} -> {asset} ({kind})")
    else:
        print("directory: skipped (TOPAZ_DIRECTORY_URL unset)")
    return 1 if (report["ledger"] or report["directory"]) else 0


if __name__ == "__main__":
    sys.exit(main())
