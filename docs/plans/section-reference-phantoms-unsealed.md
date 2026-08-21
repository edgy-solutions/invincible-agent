---
id:         section-reference-phantoms-unsealed
status:     parked
owner:      unassigned
blocked-on:
trigger:    the next §-reference phantom found in the wild — one instance caught by deliberate audit proves the defect exists; a SECOND proves the audit does not scale, and that is what arms the 42-file heading-normalization sweep
closed-by:
code-site:  docs/adr/, tests/test_citation_paths.py
repo:       invincible-agent
summary:    PARKED, evidence-gated. `§N` references inside ADRs have no reader — ADR-0042 shipped a status-line `§9` pointing at a section that did not exist, caught by deliberate audit rather than by any check. One instance does not yet arm a 42-file heading-normalization sweep during a deadline week. TRIGGER: the next §-reference phantom found in the wild — a second instance proves audit does not scale and arms the sweep. FIRST ATTEMPT MEASURED THE INSTRUMENT, NOT THE SUBJECT (see below); a real seal needs heading normalization first.
---

# Section references inside ADRs have no reader

`tests/test_citation_paths.py` seals `docs/…` **paths**. `tests/test_adr_index_complete.py`
seals the ADR **index**, both directions. Neither sees a `§N` reference, and `§N` is the
citation form ADRs use most densely — the whole point of numbered rulings is that later
prose points back at them.

## The instance

ADR-0042 was written to replace two phantom citations in a plan document ("a live-updating-cards
ADR is already in flight," "the PublishedArtifact discriminator pattern") — neither existed.
Its own status line then shipped **`See §9 for what is settled versus directional`** against a
document with eight numbered rulings and no §9. Status line: the first thing every reader sees.

It was caught by a deliberate post-write audit. **No check would have caught it**, and the board
stayed green, every one of the ADR's eighteen `docs/…` citations resolved, and the index seal
passed — all while the document's most-read line pointed nowhere.

That completes a class this repo has now observed at four layers: filenames, line numbers,
conversational shorthand, and section anchors. Citation-writing is transcription, and
transcription lies.

## Why this is PARKED and not built

**The first attempt measured the instrument, not the subject.** A scan across all 42 ADRs
reported dangling `§` references in fifteen files — and printed `sections: none` on every
single row. That is not fifteen findings; that is a heading regex matching nothing, reporting
a dirty answer that means exactly as much as a clean one would have.

Shipping it would have been [`legacy-dns-guard-phantom-scope`](legacy-dns-guard-phantom-scope.md)
verbatim: a guard whose scope is wrong, going green (or red) forever without touching its
subject. The temptation was real and worth recording — it arrived at the moment where shipping
the broken seal *looked like finishing the job*.

## What a real seal needs

ADRs do not share one heading convention. `### 1. Title`, `## Decision N`, bolded `**§3**`
inline, and prose-numbered paragraphs all appear across the 42 files. A seal must normalize
those into one "what sections does this document actually have" answer before it can compare
references against them — otherwise it re-runs the same instrument error with more code.

Estimated: 42 files surveyed for heading conventions, a normalizer, then the comparison. Not
large, but not five minutes, and not during demo week.

## Trigger

**The next `§`-reference phantom found in the wild.** One instance caught by deliberate audit
proves the defect exists; a second proves the audit does not scale, and that is what arms the
sweep. Evidence-gated expansion — the same grammar as ADR-0031's deferred rung 3 and ADR-0028's
behavior-named triggers.

Until then, the mitigation is the audit that worked: after writing any document with numbered
sections, diff the set of `§N` references against the set of section numbers before committing.
Three lines of shell, run by a human who remembers — which is precisely the aspirational-seal
shape this item exists to eventually replace, and saying so is the point.
