#!/usr/bin/env python
"""Re-key the last `pcn_grouped_review` rows to `grouped_review`. Same species, retired prefix.

WHY A MIGRATION AND NOT A DECLARATION, AND NOT A DELETION. `pcn_grouped_review` is on the
FORBIDDEN list in `tests/test_cross_repo_contracts.py` — a name the M3.1 audience rename
retired at the code layer — and it had **2 live rows** in sandbox's `human_task_projection` on
2026-09-12, against 25 for `grouped_review`.

That left three options and two of them are wrong:

* **Declare it in the overlay** — resurrects a retired name as a supported species, and the
  next reader cannot tell a straggler from a design.
* **Let the task-kind gate refuse it** — turns two live tasks dead as a side effect of setting
  a config variable. The gate is correct; using it to do a data migration is not.
* **Re-key the rows.** The M3.1 rename's own pattern, applied to the last two stragglers.

RULED 2026-09-12: *migrate, do not kill and do not revive.*

NOT THE SAME AS `pcn_disposition`, and the difference is load-bearing. The FORBIDDEN list
carries `pcn_disposition:` **with the colon** — that is the AUDIENCE key, renamed to
`disposition_review:`. The bare task KIND `pcn_disposition` deliberately survives as a
cortex-ui render contract until M3.3 retires `taskKindRegistry`, which is why it belongs in
the overlay as a declared species while this one belongs in a migration. *Two
identical-looking strings, one renamed, one kept*, and the colon is the discriminator.

    DRY RUN (default):  uv run --frozen python scripts/migrate_pcn_grouped_review_rows.py
    APPLY:              uv run --frozen python scripts/migrate_pcn_grouped_review_rows.py --apply

Exit codes:
    0  nothing to do, or applied successfully
    1  rows found and NOT applied (dry run) — so CI can tell "clean" from "pending"
    2  could not look (no DSN, unreachable database)
"""
from __future__ import annotations

import argparse
import os
import sys

OLD_KIND = "pcn_grouped_review"
NEW_KIND = "grouped_review"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="perform the update; without it this only reports")
    args = ap.parse_args()

    dsn = (os.getenv("PROJECTOR_POSTGRES_DSN") or "").strip()
    if not dsn:
        print("PROJECTOR_POSTGRES_DSN is unset — COULD NOT LOOK. This is exit 2, not a pass: "
              "an unreachable database has not told you the rows are gone.")
        return 2

    try:
        import psycopg2
    except ImportError:
        print("psycopg2 is not installed here — COULD NOT LOOK (exit 2).")
        return 2

    try:
        conn = psycopg2.connect(dsn)
    except Exception as exc:  # noqa: BLE001
        print(f"could not connect — COULD NOT LOOK (exit 2): {type(exc).__name__}: {exc}")
        return 2

    with conn:
        with conn.cursor() as cur:
            # WHAT IS THERE, BY ID, BEFORE ANYTHING CHANGES. A migration that reports only a
            # COUNT cannot be checked afterwards by anyone who did not run it — and this one
            # is being run once, by hand, against live rows a person is waiting on.
            cur.execute(
                "SELECT id, task_id, status, recipient_id FROM human_task_projection "
                "WHERE kind = %s ORDER BY id", (OLD_KIND,))
            rows = cur.fetchall()

            if not rows:
                print(f"no {OLD_KIND!r} rows — nothing to migrate.")
                return 0

            print(f"{len(rows)} row(s) with kind={OLD_KIND!r}:")
            for rid, task_id, status, recipient in rows:
                print(f"    id={rid}  task_id={task_id}  status={status}  recipient={recipient}")

            if not args.apply:
                print(f"\nDRY RUN — nothing written. Re-run with --apply to re-key these to "
                      f"{NEW_KIND!r}.")
                print("Exit 1 means ROWS ARE PENDING, not that anything failed.")
                return 1

            # Idempotent by construction: the predicate is the old name, so a second run
            # matches nothing. `status` and every other column are untouched — this is a
            # RENAME of the species, not a change to the task's state, and a migration that
            # quietly normalised a status would be making a decision nobody asked for.
            cur.execute(
                "UPDATE human_task_projection SET kind = %s, updated_at = %s WHERE kind = %s",
                (NEW_KIND, int(__import__("time").time() * 1000), OLD_KIND))
            print(f"\nre-keyed {cur.rowcount} row(s): {OLD_KIND!r} -> {NEW_KIND!r}")

            cur.execute("SELECT count(*) FROM human_task_projection WHERE kind = %s", (OLD_KIND,))
            left = cur.fetchone()[0]
            if left:
                print(f"STILL {left} row(s) with the old kind — the update did not take.")
                return 1
            print(f"verified: 0 rows remain with kind={OLD_KIND!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
