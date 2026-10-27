to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, cortex-ui/master
from: invincible-agent/lane/01
date: 2026-10-21
re: your "Measure work-instruction on the title read, picker, /leaf and promotion before building; send anything that assumes pcn|pdn to me"
relay: Chris

This report carries no secret. I read code only; nothing is built, rolled or fired.

# work-instruction as a PDF leaf: the leaf set widens cleanly, but promotion and its review card are built for a notice. Two questions

## 1. What widens with no change beyond the set

These places only ask "is this one of the leaves?", so reading the set from the registry is enough:

| surface | where | what it does |
| --- | --- | --- |
| title read | `_title_leaf` | a leaf iff `doc_type_source == "title"` and the lowercased `doc_type` is in the set |
| the row's leaf | `_row_leaf`, `_declared_leaf` | a drop that declares a leaf kind is recorded `leaf_source=declared` |
| picker | `_backstop_candidates`, `hold_for_kind` | candidates outside the set are dropped |
| `/leaf` | `unknown_leaf` 422 | `allowed` lists the set |
| re-class vs re-run | `_same_passes` | read from registry passes. pcn↔work-instruction passes differ, so the change re-runs |
| promotion routing | the task's audience | read from the kind's registry domain: `document_promotion:MANUFACTURING`, which `policy/task_grants.yaml` already grants |

**One thing in the title read is 7f's to answer.** A title read names work-instruction only if doc-tools prints a `doc_type` that lowercases to exactly `work-instruction`, with source `title`. According to the BFF's docstring (I have not read doc-tools' code), it prints `PCN` or `PDN` today and defaults to `PCN`.

## 2. What is notice-shaped (you asked to see these)

- **The task's title and summary.** They come from the review's notice summary: `header.mfr`, the notice date and the part count. A work instruction would read "manufacturer unknown, ? parts". The kind label is uppercased only for pcn and pdn, which is cosmetic.
- **The reject codes.** `not_a_notice`, `unreadable`, `parts_unusable`, `duplicate`. Two of the four have no meaning for a work instruction.
- **The steward's edits.** `row_edits` and `header_edits` are a notice's part rows and header fields.
- **The act.** Approving makes the notice's `SUBJECT_TO` part edges equal the reviewed rows, but only when a notice node exists in the graph. A work instruction has none, so it would take the generic path: ingest node present, then the promotion fact. **Mechanically it would promote. Nothing reconciles a work instruction's own content.**
- **Re-run after a re-class.** pcn→work-instruction sends the row back to doc-tools. Whether doc-tools then runs the manufacturing extraction because `content_kind` changed is 7f's to say.

**Not measured:**
- the shape of a work instruction's extraction output;
- whether a work instruction dropped today ever reaches a `document_promotion` task at all. The drop door reads its accepted kinds from the registry, and the overlay registers work-instruction;
- doc-tools' title vocabulary.

## 3. Two questions

**Q1. What review does a work-instruction leaf get?**
- (i) The same `document_promotion` card with the notice parts hidden: reject codes `unreadable` and `duplicate` only, no row or header edits, approve writes the fact.
- (ii) A review of its own, shaped by its extraction. That is new work for cortex and 7f.
- (iii) Offer it as a leaf for routing only. Picking it hands the row to the manufacturing pipeline, and there is no `document_promotion` review.

I would build (i) only once 7f shows what a work instruction's extraction contains.

**Q2. Does rule (a) give XML drops a leaf?** As worded, "the domain-declaring kinds whose arrives_as includes the drop's format" gives an XML drop one leaf, s1000d-data-module. Today XML rows are not leaf-capable: the status body has no leaf keys and `/leaf` refuses them. I read your "s1000d stays on xml" as **no**: the leaf machinery (title read, `awaiting_kind`, `/leaf`) stays on the formats it runs on, PDF today. So I would derive the set from `arrives_as` and keep the format gate where it is. Say if you meant yes.

Nothing is built, as ruled: after the dry run, once ca releases `arrives_as`, and once you answer Q1.
