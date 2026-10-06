to: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-06 ~03:50Z
re: the overnight order (roll #18 fire authorized)

# Roll #18 not armed: the trigger is a report from a lane that is not running tonight

**Nothing was fired.** Item 1 arms "when 7f reports the doc-tools pin rolled". At 03:45Z
doc-tools PR #73 (the 877677c pin) is still OPEN, no 7f packet is on master, and your order
says Lane 1 is the only lane running tonight -- so the trigger cannot arrive before morning.
I did not merge #73 or roll doc-tools myself: the 7f packet (a446180b) says Lane 1 does not,
and the order gates on 7f's report, not on the merge.

## State of the trigger (measured)

- PR #73: OPEN, MERGEABLE/UNSTABLE. Required check `corpus-gate`: SUCCESS. `build-and-push`
  (run 37408010836): SUCCESS. Advisory `corpus-gate-verdict`: FAILURE --
  `Diodes_PCN_2683_FULLGREEN.pdf: header fields disagree across fires and needs_review is not
  True in all three fires (undeclared silent write)` plus `pcn_corpus_run.py exited 1 --
  parts/crop-seal gate not met`. This is the same fixture flagged in the 10-04 roll-16 packet;
  it is advisory and does not block the merge, but 7f should see it before merging.

## What is ready, untouched

- `lane/01-roll-18` @ 5dc8edbe, pushed: key fix, requesters (15d06474), 200 contract,
  lane/74-acceptance-requester, lane/74-outcome-from, lane/74-engine-w-mesh, cortex pin
  sha256:8b929940..., chart 0.4.32. Not merged to master.
- engine-w `KNOWLEDGE_SEARCH_VIA_MESH`: defaults `"false"` in
  `agent_fleet/weaviate_expert/service.py:162`; no chart value sets it. Ships off.
- Item 2 probe written (Lane 1 scratch): drops a never-dropped notice, PCN26-117, as alice with
  `content_kind=pcn` (registered in doc-tools `registry/content_kinds/pcn.yaml`) -- the 10-04
  drop declared no content kind, which the /ingest docstring says HALTs at the driver, so this is
  not a repeat of that measurement. It polls to `review`, acts as bob with a reason, asks
  "which parts does PCN26-117 affect" as alice and scans the SSE for `provenance_floor`. Note
  the gateway's own comment: no production engine attaches a ProvenanceBlock yet, so an absent
  floor is the expected first result.

## Item 4 baseline (measured 03:48Z, as alice)

The Oct 4 PCN23-002 record (`sha256:0096a523...`): stage `received`, `updated_at ==
created_at` (2026-10-04 04:27Z). It has not moved. The sensor that would move it arrives with the
doc-tools roll, so this is the baseline, not a finding.

## Not run

Items 2, 3 and 5 (drop, census x3, HAZ-1003 row, mock modules) all follow the roll; none ran.

## Your call

1. **Wait** -- 7f merges #73 and rolls in the morning; Lane 1 arms on the report as ordered.
2. **Authorize Lane 1** to merge #73 and roll doc-tools to 877677c tonight (a ruling over
   the 7f packet's "Lane 1 does not roll doc-tools").
3. **Arm roll #18 without waiting** for the doc-tools pin (the invincible-agent side does not
   depend on it; the drop measurement does, because the ingress sensor is doc-tools').

Lane 1's recommendation: 1, unless Tuesday's drop needs tonight's numbers -- then 2, since
3 would give a drop measurement against the old sensor.
