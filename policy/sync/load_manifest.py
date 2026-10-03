"""Load the chart-shipped Topaz ReBAC manifest into the Directory — fail-closed pre-check +
positive-control readback, so a startup sync that needs a NEW type (e.g. program_member_sync's
`program`) never dies E20026 with "unknown type" and no human has to hand-run
`topaz ds set manifest` first.

WHY THIS EXISTS. 82ed0b7f added the `program` type to topaz-configmap.yaml's manifest.yaml.
The roll shipped the configmap, but nothing LOADED it into Topaz's directory in sandbox
(topazSeed.enabled=false; the only loader was the hand-run `topaz ds set manifest`). This
script, run by templates/topaz-manifest-load-job.yaml, folds the load into the roll exactly as
task-grant-sync-job.yaml folded the grant seed.

A MANIFEST SET REPLACES THE WHOLE SCHEMA — there is no partial/merge apply
(TopazClient.set_manifest_from_file POSTs the whole document). So this is not a blind "load the
file": if the LIVE directory already declares a type the file does not (an operator-added type
this chart doesn't know about, or a type this revision accidentally dropped), loading would
silently DELETE it along with every object/relation of that type. The pre-check below is
fail-closed: it refuses and loads NOTHING rather than risk that.

FLOW:
  1. PRE-CHECK: fetch the live manifest (TopazClient.get_manifest). Empty/absent (a fresh
     cluster — nothing has ever been loaded) always proceeds, since there is nothing to lose.
     Otherwise, if the live manifest declares any top-level type the FILE does not, REFUSE
     (exit non-zero, name the types, load nothing).
  2. LOAD: POST the file via TopazClient.set_manifest_from_file (idempotent — safe to re-run
     every release).
  3. READBACK (positive control): fetch the live manifest again; every top-level type the file
     declares must now be present, else exit non-zero naming the missing ones — the apply lied.

Types are parsed from the `types:` mapping with a YAML parser on BOTH sides — never a regex.
Exit codes mirror the other startup syncs in this directory (task_grant_sync.py,
program_member_sync.py): 0 ok, 2 refused pre-check, 4 readback failed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml


def parse_types(manifest_text: str) -> set[str]:
    """PURE: a manifest YAML document (or "" / a doc with no `types:`) -> its top-level type
    names. A YAML parser, never a regex — a rebac manifest is real YAML and a regex over it is
    exactly the class of parser this project keeps re-discovering is wrong."""
    if not manifest_text or not manifest_text.strip():
        return set()
    doc = yaml.safe_load(manifest_text) or {}
    types = doc.get("types") or {}
    return set(types.keys())


def precheck(file_types: set[str], live_types: set[str]) -> list[str]:
    """Types the LIVE directory declares that the FILE does not — loading would DROP them.
    An empty live_types (fresh cluster, nothing loaded yet) always passes (returns [])."""
    if not live_types:
        return []
    return sorted(live_types - file_types)


def missing_after_load(file_types: set[str], live_types_after: set[str]) -> list[str]:
    """Types the FILE declares that are NOT present in the live directory after the load — the
    positive control. Non-empty means the apply lied."""
    return sorted(file_types - live_types_after)


def load_manifest(client, path: Path) -> int:
    """Orchestrate pre-check -> load -> readback against a TopazClient (or a recording double
    exposing get_manifest()/set_manifest_from_file()). Returns the process exit code.

    Exit codes: 0 ok, 2 pre-check REFUSED (an existing live type would be dropped — set is
    NEVER called), 4 readback failed (set was called, but a file type does not resolve
    present afterward)."""
    file_text = path.read_text()
    file_types = parse_types(file_text)

    print("===== PRE-CHECK (live manifest vs. file) =====")
    live_text = client.get_manifest()
    live_types = parse_types(live_text)
    extra = precheck(file_types, live_types)
    if extra:
        print(
            "REFUSED — the live directory declares type(s) this manifest file does not; "
            f"loading would DROP them (nothing loaded): {', '.join(extra)}",
            file=sys.stderr,
        )
        return 2
    print(f"  live declares {len(live_types)} type(s); none would be dropped. Proceeding.")

    print(f"===== LOAD manifest from {path} =====")
    client.set_manifest_from_file(path)
    print("  loaded.")

    print("===== READBACK (positive control) =====")
    live_text_after = client.get_manifest()
    live_types_after = parse_types(live_text_after)
    missing = missing_after_load(file_types, live_types_after)
    if missing:
        print(
            f"FAIL: type(s) in the file are NOT present after load — apply lied: "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )
        return 4
    print(f"types: {len(file_types)} loaded, {len(live_types_after)} present")
    return 0


def main() -> int:
    """CLI. Env: TOPAZ_MANIFEST_FILE (default /topaz-config/manifest.yaml — the mount path
    templates/topaz-manifest-load-job.yaml uses for the chart-shipped manifest), and
    TOPAZ_DIRECTORY_URL (default http://topaz-svc:9393)."""
    from topaz_sync import TopazClient

    manifest_file = os.getenv("TOPAZ_MANIFEST_FILE", "/topaz-config/manifest.yaml")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    with TopazClient(topaz_url) as client:
        return load_manifest(client, Path(manifest_file))


if __name__ == "__main__":
    sys.exit(main())
