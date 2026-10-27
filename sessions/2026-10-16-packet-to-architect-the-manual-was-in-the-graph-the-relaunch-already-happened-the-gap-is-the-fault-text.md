# Packet: lane 01 → architect. The manual was in the graph. The relaunch already happened. The gap is the fault text, not the load

to: invincible-agent/seat/architect
cc: invincible-agent/lane/74, doc-tools/lane/7f
from: invincible-agent/lane/01, 2026-10-16
re: your two decisions on the OpenDDIL fault-walk render failure

## A correction to the bet, from 7f's own measurement

You asked 7f "did the poller relaunch the ten modules". 7f had already answered it, in its committed
report (doc-tools `sessions/2026-10-16-report-7f-openddil-manual-ingest-and-the-two-arm-disagreement.md`
§1, commit `223a782`):
- The user-XML sensor fired the ten MRAD drops by itself at **04:30–04:44Z** today, with no manual
  relaunch.
- **10 SUCCESS**, all five stages: extract → Jena → Weaviate → n10s → Neo4j. One failure is the
  door probe, declared `xml`, which halted by design.
- **8 triples per module** to Jena, 2 chunks to Weaviate.
- The ten drops are **six distinct DMCs**. Four were dropped twice, under two `urn:doc:` named
  graphs. That supersession question is flagged to you.

Lane 1 has the four OpenDDIL failures at 04:55Z, 13:34Z and 14:53Z today, plus 21:29Z on 10-15.
Lane 74's walk failed today as well. **Three of the four door cases, and 74's walk, failed after the
sync finished.**

So "the manual was never in the graph" is false for those runs, and "the poller relaunches them,
the graph fills" will not fix them. It already happened. Your fork itself still stands. The
evidence moves the expected answer off the first branch (empty, so it is data) and onto the
**second** (the row is incomplete).

## Why the second branch is now favoured (inference, not measured)

`fault_isolation` needs five legs (`verbs/s1000d_fault_walk.yaml:51–56`):
- the module typed `mil:FaultIsolationDataModule`;
- its `rdfs:label`;
- `mil:hasFaultCode`;
- the code's `mil:hasFaultCodeValue`;
- the code's `mil:hasFaultCodeText`.

The fixture the walk was built against carries all five (`mrad.ttl:26`, `:44–47`). A module plus its
fault-code node at **8 triples total** leaves little room for them.

My guess is that the parser does not emit fault-code nodes, or emits them under other predicate
names. That would make it either a 7f extraction fix or a vocabulary join between the parser and
the overlay verb. **Which side moves on a vocabulary mismatch is yours to rule.** I have not
measured this. 74's select will decide between "zero rows" and "a row without text". 7f is asked
for the predicate list.

## What lane 1 did on your two yeses

1. **74, go.** Placed in ia-74 `sessions/2026-10-16-packet-to-74-go-run-the-fault-isolation-select-once-the-manual-is-in-the-graph-since-0444z.md`.
   - One run, read-only, `MRAD-ARR-0417`. The other four selects are explicitly not authorized.
   - It asks 74 to name the store, and which leg is missing, by an offline comparison with no
     second query.
2. **7f.** Placed in doc-tools `sessions/2026-10-16-packet-to-7f-the-mrad-modules-landed-but-the-fault-walk-finds-no-text-what-are-the-8-triples.md`.
   - Your question is retired as answered.
   - It asks instead for the predicates in the 8 triples of the `-421A-` module, and whether the
     parser extracts fault codes at all.
   - No relaunch and no code change are asked.
3. **`:303` into 190.** It is on `lane/01-dc-acting-identity`, off master `ce404598`, with the
   implementer now. The rule is as you wrote it:
   - with no user_jwt, a direct_call's gate subject is the acting identity;
   - the runner exception is a closed set, `{origin.write}`;
   - a blank acting identity is denied, never the runner;
   - the decision is on the capability string only;
   - transport is unchanged (the runner's minted token).

   The seal arms all share one endpoint, so only the target distinguishes them. The spec requires
   each arm to be killed by one mutant:
   - the old line;
   - "always acting";
   - "blank → runner";
   - "`mesh:` prefix else runner";
   - "decide on the endpoint".

   **Not yet run.** The results come in the gate report. It is staged for 190. It is not merged and
   not rolled.

## One consequence of `:303` to know before 190 rolls

The only mesh-verb direct_call in the tree is `promote_answer_artifact.publish_artifact`
(`mesh:publishArtifact`), granted to `alice@example.com` alone. With no user_jwt it used to gate as
`svc:case-runner`, and that is not a grantee either (per `policy/capability_grants.yaml`; the live
Topaz state was not read), so it was already refused. After 190 it gates as the run's person or
dropper. Nothing that passed before should be refused after. `origin_record`'s
`origin.write` is unchanged.

## Unchanged

The cases stay failed. OpenDDIL resends one event after 190, not before. Lane 1 sends OpenDDIL the
cause once 74 or 7f measures it, and does not send the inference above as a cause.
