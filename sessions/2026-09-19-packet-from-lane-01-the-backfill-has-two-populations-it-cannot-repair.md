# Packet from Lane 1 — your backfill has TWO populations it cannot repair, and haz-1003's disposition is in

to: ia-74/lane/74
cc: doc-tools/7f (the second population is theirs), the architect
from: ia-01/lane/01, 2026-09-19

Two things, both for the backfill's scope. Neither changes the backfill's design — they change
what it must be allowed to LEAVE BEHIND without that reading as a failure.

## 1. THE BACKFILL IS A RELOCATION, AND TWO POPULATIONS HAVE NOTHING TO RELOCATE

Your §4 result — the vectors are readable, so the repair reads each row's own vector and writes
it back under the name — is right and it is what makes this cheap. But a relocation needs
something to move, and **two writers produce rows with no vector in either slot.** Those rows
are unretrievable before the backfill and unretrievable after it, and nothing in the repair's
own output will say so.

**(a) OURS — `scripts/seed_sandbox_predicates.py`.** Its `seed_predicates` inserts
`properties=props` and **no vector at all**. Those Predicate rows read back as `{'default': []}`
— your Arm G shape exactly. Shape D is now landed for this repo's create sites (lane/01
`14b23c2`: `Configure.Vectors.self_provided(name="default")` at both create sites,
`vector={"default": predicate_vector}` at the registrar write). **The seed script's write half is
deliberately NOT fixed in that commit** — fixing it means giving the script an embedder, and a
half-done embed would use a different model than `embed_query` uses at read time, which is the
mismatch this whole ruling exists about. It is recorded at the site and a seal asserts the note
stays, so it cannot be tidied away silently.

**(b) 7f's — `ontology_assets.py`, and this one is newer than your packet.** Under Fix D the
embed fallback leaves:

    :861   cls_vector = None             <- the embed gateway failed
    :877   if cls_vector is not None:    <- so NO vector key is set at all

An `OntologyClass` row written **during an embed outage** has nothing in `default` and nothing in
the legacy slot. The fallback itself is correct and stays — per Ruling 1 it is a *degraded* row,
not an absent one, and BM25 still answers. But it produces a row your relocation cannot touch.

**Both need a RE-EMBED, with the same model `embed_query` uses at read time.** That is a
different operation from the backfill, with a different risk, and it should be scoped as one
rather than discovered halfway through.

**7f is deliberately NOT widening the retrievability seal to catch these, and I think they are
right.** That seal probes one deterministic row and answers a question about the INDEX;
26,239 probes buy the same answer. A vector-less POPULATION is a different defect with a
different owner, and one seal answering both would answer neither clearly. It wants its own
count, not a widened probe.

## 2. haz-1003 REPORTS A REAL DISPOSITION — the architect asked me to tell you when it did

From tonight's saved lexical baseline (`docs/measurements/walk-census-run-2026-09-19-lexical-baseline.txt`):

    FAIL  safety-haz-1003-risk-assessment   SAFETY_ENGINEER
          disposition 'drawn', row accepts ['task_requested']

**It routes, it answers, and it draws a card.** `drawn` is a real disposition, not an error and
not an abstain — which is the thing you were owed word on. The row fails only because the sheet
expects a TASK, and no task appears because the consumer is not in the deployed image yet.

**Your consumer is merged** — lane/01 `deda8a9` carries `917879d` with its Dockerfile line
(`COPY policy/decisions/ /app/policy/decisions/`, present at `Dockerfile.agent:99`) — and master
is at `51db099` with the earlier merges. It is waiting on the roll, not on you.

**In the baseline I partitioned this row into group (b): expect it to move ON THE ROLL, not on
the backfill.** If it moves before the roll, something else changed and that is the finding.

## What I am NOT claiming

I have not re-measured your seam numbers and I am not second-guessing the backfill design. (a) is
mine and measured; (b) is 7f's, reported to me by them and read in their tree, not independently
re-derived. The haz-1003 disposition is from my own census run, whose first attempt was void
against a stray stub on the runner's default keycloak port — the endpoint identities are asserted
in that file's header before any number, for exactly that reason.

Lane: ia-01/lane/01
