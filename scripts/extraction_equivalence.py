"""The ADR-0053 §7 equivalence harness: the pre-change function beside the new one.

R-029 made this the REQUIRED instrument for an extraction, because unlike a seal it makes no
claim that can age — it just compares. §7 wants byte-identical output for a step-1 extraction,
and for a step-2 Decimal pass it wants every moved value NAMED.

── WHY THIS IS A CHECKED-IN SCRIPT AND NOT A SNIPPET IN /tmp ────────────────────────────────
The first three extractions each used a throwaway copy, and they drifted: one compared whole
objects and one compared shared keys only, so the same change reported `DIFFS: 10` in one and
`moved: 0` in the other. **That disagreement was mine, between two copies of my own
instrument** — the shape §6b now names, arrived at by having no single place for the tool.

── §6b, WHICH THIS SCRIPT EXISTS TO OBEY ────────────────────────────────────────────────────
**It reports two numbers separately**, because a whole-object comparison calls an ADDED field a
diff and therefore can never return clean again once a verb has taken its step-2 pass:

    shared-key values moved   ->  must be 0, or each named
    fields added / removed    ->  expected on step 2; a REMOVAL is a finding

An instrument whose alarm cannot be cleared by doing the right thing stops being read.

Usage — the OLD module comes from git, never from a memory of what it used to do:

    git show <sha>:agent_fleet/finance_agent/measures.py > /tmp/old_measures.py
    python scripts/extraction_equivalence.py /tmp/old_measures.py fin_burn_rate
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
from typing import Any, Callable, Iterable


def load_module(path: str, name: str = "_pre_extraction"):
    """Load the pre-change module by PATH, under its own name.

    Loading it under a distinct name matters: importing it as `measures` would let it collide
    with the live module in `sys.modules` and silently compare something against itself — the
    failure mode that makes an equivalence run agree by construction.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def compare(
    old_fn: Callable[..., Iterable[dict[str, Any]]],
    new_fn: Callable[..., Iterable[dict[str, Any]]],
    state: Any,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run both over every case and report the two numbers §6b requires."""
    moved: list[str] = []
    added: set[str] = set()
    removed: set[str] = set()
    unchanged = rows = 0

    for case in cases:
        before = list(old_fn(state, **case))
        after = list(new_fn(state, **case))
        if len(before) != len(after):
            # A ROW-COUNT CHANGE IS NEVER A PRESENTATION DETAIL. Reported as its own failure
            # rather than folded into the moved count, because it means the verb now answers a
            # different question — and it would otherwise show up as dozens of "moved" fields.
            raise SystemExit(
                f"ROW COUNT MOVED for {case}: {len(before)} -> {len(after)}"
            )
        rows += len(after)
        for row_before, row_after in zip(before, after):
            added |= set(row_after) - set(row_before)
            removed |= set(row_before) - set(row_after)
            for key in set(row_before) & set(row_after):
                if row_before[key] != row_after[key]:
                    moved.append(
                        f"{row_after.get('period', row_after.get('entity_id', '?'))}"
                        f".{key}: {row_before[key]!r} -> {row_after[key]!r}"
                    )
                else:
                    unchanged += 1

    return {
        "cases": len(cases), "rows": rows,
        "shared_keys_unchanged": unchanged,
        "shared_key_values_moved": len(moved),
        "moved_detail": moved,
        "fields_added": sorted(added),
        "fields_removed": sorted(removed),
    }


def report(result: dict[str, Any], *, expect_no_moves: bool) -> int:
    print(f"cases {result['cases']} | rows {result['rows']}")
    print(f"shared-key values unchanged : {result['shared_keys_unchanged']}")
    print(f"shared-key values MOVED     : {result['shared_key_values_moved']}")
    for line in result["moved_detail"][:20]:
        print(f"    {line}")
    print(f"fields ADDED                : {result['fields_added'] or 'none'}")
    print(f"fields REMOVED              : {result['fields_removed'] or 'none'}")

    problems = []
    if result["fields_removed"]:
        # A REMOVAL IS ALWAYS A FINDING, on either step. Consumers read those keys.
        problems.append("a field was REMOVED")
    if expect_no_moves and result["shared_key_values_moved"]:
        problems.append("values moved on a step-1 extraction, which must be behaviour-preserving")
    if problems:
        print("\nFAIL: " + "; ".join(problems))
        return 1
    print("\nOK" + ("" if expect_no_moves else " — moved values must each be named in the commit"))
    return 0


def main() -> int:  # pragma: no cover - a CLI
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("old_module", help="path to the pre-change module, from `git show`")
    ap.add_argument("verb", help="function name present in both modules")
    ap.add_argument("--cases", help="JSON list of kwargs dicts; default is one empty case")
    ap.add_argument("--step", choices=("1", "2"), default="1",
                    help="1 = extraction, no value may move; 2 = Decimal pass, moves are named")
    args = ap.parse_args()

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from agent_fleet.finance_agent import measures as new_module
    from agent_fleet.finance_agent.seed import build_seed

    old_module = load_module(args.old_module)
    cases = json.loads(args.cases) if args.cases else [{}]
    result = compare(getattr(old_module, args.verb), getattr(new_module, args.verb),
                     build_seed(), cases)
    return report(result, expect_no_moves=args.step == "1")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
