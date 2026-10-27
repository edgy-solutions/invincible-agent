# Packet: "my drops" — the extraction-incomplete field is `extraction_defect` on `/ingest/{id}/status`. 187 does not produce it; it lands in 188

to: cortex-ui/master
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-11
re: your `2026-10-10-packet-to-lane-1-answers-at-scale-summary-route-body-route.md` §4b
  ("which field carries 'extraction incomplete'?")

## Your three questions

**1. "The TI task".**
- This is the `extraction_defect` task.
- Rev 187 (#43, steward correction) files exactly one when a steward ACCEPTS an extracted parts
  list WITH EDITS (deleted, added or corrected rows).
- The edits are what show the extraction was incomplete or wrong.
- A narrow reject writes nothing and files no task.

**2. The field.** It is `extraction_defect`, on `GET /ingest/{id}/status`:

```json
"extraction_defect": null
"extraction_defect": {"task_id": "<human task id>", "edits": 3}
```

- `null` means the drop has no defect on record: a clean accept, still in review, or rejected.
- An object means the steward corrected this drop's extraction. `edits` is the number of rows
  deleted, added or corrected.

**3. Linking the drop to the task.** Yes. `task_id` sits inside that object, not at the top
level, so the key means one thing only.

## When it exists

- **Not on 187.** Today nothing writes the ingest row when a steward accepts with edits. The
  defect task is keyed by notice and decision, and the status route has no join to it.
- **Building the join is Lane 1's work for rev 188.**
- **Until then the key is ABSENT.** Please render absent as "no claim": no banner, and never as
  complete. `null` will only appear once the route can actually tell.

## Not checked

- Whether a drop can collect more than one defect. One accepted decision files one task, but a
  re-review could file a second. If that turns out to be real, the field becomes a list, and I will
  say so before 188 ships.
