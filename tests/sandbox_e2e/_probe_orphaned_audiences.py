"""Orphaned-audience probe — pending HumanTask rows whose stored audience grants NOBODY.

THE CLASS THIS CATCHES (found live 2026-08-04, the M3.1 audience rename):
`audience` is a **denormalized authz value stored on a durable row and RE-EVALUATED at
action time** (`resolve_task` re-checks Topaz `can_act` against the task's STORED audience).
So renaming or revoking an audience strands every row already carrying the old value: the
reviewer still SEES the task (its projection row was materialized when the grant existed)
and every action is denied.

**The failure mode is SILENCE, not an error** — and that is why it needs a probe rather
than a rule. Deny-by-default plus a stale stored value produces a correct denial, so the
loud-fail machinery never fires: a queue that has stopped clearing is indistinguishable
from a queue nobody is working. Six rows sat in exactly that state for an hour after the
rename, and were found by driving a live notice, not by anything automated.

WIDER THAN KEYS: any value COPIED onto durable state and later re-evaluated against live
vocabulary is a migration surface — even when it is not an identity key and does not look
like one. Keys announce themselves; stored-and-rechecked values do not, which is how this
got past a plan written by people who had just generalised the key rule.

Run:  kubectl exec -n <ns> <cortex-bff-pod> -- python /app/tests/sandbox_e2e/_probe_orphaned_audiences.py
Exit: 0 clean · 1 orphans found · 2 the probe could not tell (see POSITIVE CONTROL)
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app/src")

from iagent import human_tasks as ht  # noqa: E402

# Statuses whose rows are still expected to be ACTIONABLE. Terminal rows keep their old
# audience DELIBERATELY — they are audit records of a decision taken under that key, and
# rewriting them would falsify history (the same reason the run-log exhibits were left
# verbatim through the rename).
LIVE_STATUSES = ("pending",)


def main() -> int:
    q = (
        "SELECT audience, kind, COUNT(*) FROM human_task_projection "
        "WHERE status = ANY(%s) GROUP BY audience, kind ORDER BY audience, kind"
    )
    with ht._pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(q, (list(LIVE_STATUSES),))
            rows = cur.fetchall()

    if not rows:
        print("no live task rows — nothing to check (NOT a pass; there is nothing to be wrong)")
        return 0

    orphans, healthy = [], []
    for audience, kind, n in rows:
        actors = ht._resolve_audience_actors(audience)
        (healthy if actors else orphans).append((audience, kind, n, actors))
        print(f"  {audience:<40} kind={kind:<20} rows={n:<4} actors={len(actors)}")

    # POSITIVE CONTROL — the see-the-category rule applied to THIS probe. If NOTHING
    # resolves, the resolver/Topaz is broken and "every audience is orphaned" is a probe
    # failure wearing an outage's clothes. A probe that can only ever report RED has not
    # demonstrated it can report GREEN, and its RED must not be acted on.
    if not healthy:
        print(
            "\nINCONCLUSIVE: not a single audience resolved to an actor. That is far more "
            "likely a broken resolver / unreachable Topaz than every audience being "
            "simultaneously revoked. Fix the probe's reachability before believing its RED."
        )
        return 2

    if orphans:
        print(f"\nORPHANED AUDIENCES: {len(orphans)} — these rows are VISIBLE BUT UNACTIONABLE")
        for audience, kind, n, _ in orphans:
            print(f"  {audience} ({kind}): {n} live row(s) grant NOBODY")
        print(
            "\nCure: either migrate the rows to the current audience key, or expire them if "
            "they are residue. Do NOT re-grant the old key just to clear this — that reverses "
            "a completed rename to silence its own symptom."
        )
        return 1

    print(f"\nCLEAN: {len(healthy)} live audience(s), every one grants at least one actor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
