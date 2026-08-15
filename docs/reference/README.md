# Reference — standing design and posture with current authority

**These are consulted to decide things.** Design notes, posture rulings, contracts, schemas and
runbooks that describe how something *is*, not what someone is going to do about it. They have
no lifecycle in the ADR-0040 sense: they are not open or closed, they are **true or superseded**.

Placed here by the taxonomy ruling in
[../plans/board-migration.md](../plans/board-migration.md) (2026-08-15), which found this to be
the sharper half of the problem. The instance that forced it:

> `standards-posture.md` is cited live by ADR-0029 and two packets. It is not open, not closed,
> and not history. Shelving it under "what happened" would have made three ADRs point at a
> graveyard.

The test that put a document here rather than in [`docs/plans/archive/`](../plans/archive/):
**does anything consult this to decide something today?** Two worked examples, because both are
judgement calls someone will want to re-argue:

- `analyst-loop-red-baseline.md` is a *record of a measurement*, which sounds like archive — but
  ADR-0032 measures its design against it, so it is a live yardstick. Reference.
- `adr0034-trust-lifecycle-build-directive.md` is a *directive*, which sounds authoritative — but
  it has been executed. A build plan that has been built is history. Archive.

**Superseding, not closing.** When one of these stops being true, say so in the document and
point at what replaced it. There is no `status: closed` here to reach for, and inventing one
would rebuild the category error this directory exists to fix.

**Citations into this directory are checked.** `tests/test_citation_paths.py` fails if anything
cites a `docs/` path that does not exist — which matters more here than anywhere, because these
are the documents ADRs and code comments point at.
