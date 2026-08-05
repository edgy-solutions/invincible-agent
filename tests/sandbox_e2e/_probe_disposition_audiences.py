"""Disposition-queue audience probe — every queue a dispatch CAN route to must grant somebody.

THE CLASS THIS CATCHES, and why it is not the orphaned-audience probe. Its sibling
`_probe_orphaned_audiences.py` walks the audiences that live ROWS already carry, so it can only
see a queue a dispatch has ALREADY reached. That is a reachability blind spot in the exact shape
the arc keeps re-finding: it proves behaviour on the inputs GIVEN, never that the *other* inputs
can arrive. A disposition nobody has picked yet has no rows, so an audience with zero actors is
invisible to it — right up until the first reviewer picks that disposition, at which point the
dispatch routes to NOBODY and the approval reads settled with no effects.

FOUND BY THIS PROBE'S REASONING, 2026-08-05, before it had run once:
`dispatch_plan._DISPOSITION_QUEUE` declares THREE queues. At the time of writing, `qualification`
was granted in git+live, `procurement` was granted LIVE ONLY (an uncommitted hand-fix from the
notice-A repair, one sync-prune from revocation), and `sourcing` was granted NOWHERE. Notice A's
second defect — an empty `procurement` audience masked by a 401 — was therefore not one bug. It
was one of three, and the other two were still open.

WHY IT READS THE MAP INSTEAD OF LISTING AUDIENCES. The question is not "does every audience that
exists grant somebody" — it is "does every audience the CODE CAN PRODUCE grant somebody." Those
differ precisely at the queues nothing has produced yet, which is the whole point. So the probe
imports `_DISPOSITION_QUEUE` — the ONE declaration, never a copy. A copied map would pass forever
while the real one grew a fourth queue (two escapers of one meaning; the failure that
`utils/service_identity.py` exists to prevent).

`archive` maps to None BY DESIGN (acknowledge, no task, no queue) and is skipped, not failed.

Run:  kubectl exec -n <ns> deploy/iagent-cortex-bff -- python /app/tests/sandbox_e2e/_probe_disposition_audiences.py
Exit: 0 every reachable queue grants >=1 actor · 1 some queue grants NOBODY · 2 the probe could
      not tell (see POSITIVE CONTROL / the map could not be read)
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app/src")
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/agent_fleet/restate_analyst")

from iagent import human_tasks as ht  # noqa: E402


def _load_queue_map() -> dict:
    """Read the ONE declaration of disposition -> queue. Both import paths are tried because
    the same file is `dispatch_plan` in engine-a's flattened image and
    `agent_fleet.restate_analyst.dispatch_plan` in the repo-shaped ones — the lazy-import dance
    every restate_analyst core carries.

    A failure here returns {} and the caller exits INCONCLUSIVE. That is deliberate: a probe that
    cannot read the map has learned NOTHING about the audiences, and reporting green because the
    loop had nothing to iterate is the empty-set lie this codebase treats as worse than a red.
    """
    try:
        from agent_fleet.restate_analyst.dispatch_plan import _DISPOSITION_QUEUE  # type: ignore
        return dict(_DISPOSITION_QUEUE)
    except Exception:  # noqa: BLE001
        pass
    try:
        from dispatch_plan import _DISPOSITION_QUEUE  # type: ignore[no-redef]
        return dict(_DISPOSITION_QUEUE)
    except Exception as exc:  # noqa: BLE001
        print(f"INCONCLUSIVE: could not import _DISPOSITION_QUEUE ({type(exc).__name__}: {exc})")
        return {}


def main() -> int:
    queue_map = _load_queue_map()
    if not queue_map:
        print(
            "\nThe probe could not read the disposition->queue map, so it has checked NOTHING. "
            "This is exit 2, not exit 0: an empty loop is not a clean result."
        )
        return 2

    # `archive` -> None is a declared no-task disposition, not a missing grant.
    reachable = {d: q for d, q in queue_map.items() if q}
    skipped = sorted(d for d, q in queue_map.items() if not q)
    if skipped:
        print(f"skipped (no queue BY DESIGN): {', '.join(skipped)}")
    if not reachable:
        print("INCONCLUSIVE: the map declares no queue-bearing disposition at all.")
        return 2

    empty, granted = [], []
    print(f"\n{'disposition':<24} {'queue':<20} actors")
    for disposition, queue in sorted(reachable.items()):
        try:
            actors = ht._resolve_audience_actors(queue)
        except Exception as exc:  # noqa: BLE001
            print(f"INCONCLUSIVE: resolver raised for {queue!r} ({type(exc).__name__}: {exc})")
            return 2
        (granted if actors else empty).append((disposition, queue, actors))
        print(f"  {disposition:<22} {queue:<20} {len(actors)}"
              f"{'   <-- GRANTS NOBODY' if not actors else ''}")

    # POSITIVE CONTROL — the see-the-category rule, same as the orphaned-audience probe. If NOT ONE
    # queue resolves, the far likelier explanation is a broken resolver or an unreachable Topaz than
    # every queue being simultaneously ungranted. A probe that has never been observed to report
    # GREEN has not earned the right to have its RED acted on.
    if not granted:
        print(
            "\nINCONCLUSIVE: not a single disposition queue resolved to an actor. That is far more "
            "likely an unreachable Topaz / broken resolver than every queue being revoked at once. "
            "Fix the probe's reachability before believing its RED."
        )
        return 2

    if empty:
        print(f"\nUNROUTABLE QUEUES: {len(empty)} — a dispatch to these dies with the approval "
              f"already recorded as settled")
        for disposition, queue, _ in empty:
            print(f"  {disposition} -> {queue!r} grants NOBODY")
        print(
            "\nCure: grant the queue in policy/task_grants.yaml and run task_grant_sync (a hand-"
            "grant in Topaz is a MITIGATION, not a fix — this sync prunes what git does not "
            "assert, so an uncommitted grant is one run from revocation). Do NOT remove the "
            "disposition from _DISPOSITION_QUEUE to silence this: that deletes a capability to "
            "hide a missing grant."
        )
        return 1

    print(f"\nCLEAN: {len(granted)} reachable disposition queue(s), every one grants >=1 actor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
