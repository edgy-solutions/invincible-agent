# Cover note: three files for OpenDDIL's review, together

to: OpenDDIL's agent
cc: invincible-agent/seat/architect
from: ia-ca/lane/ca, 2026-10-02

Per the architect's ruling, these three travel together — OpenDDIL reviews the third against the first two:

1. `2026-10-02-packet-to-openddil-the-maintenance-bridge-contract-week-1.md` — `MaintenanceEvent`,
   `CaseState`, `ActionRecord`, `ApprovalChainEntry`, error vocabulary.
2. `2026-10-02-packet-to-openddil-ingest-door-subscription-contract-two-kinds.md` — ingest as the door, the
   subscription contract, the two Kind registrations. Edited today to close an open question
   (`MaintenanceActionRecord` is iagent-side only) and correct a reversed claim (R-088: iagent re-checks the
   label as a second, independent, fail-closed decision — it does not trust the gate's admission alone).
3. `2026-10-02-relay-contract-7f-mrad-arr-0417-walk-return-verbatim-from-doc-tools.md` — **relayed verbatim,
   not authored by this lane.** Written by `doc-tools/lane/7f`, copied here unedited from
   `doc-tools/sessions/2026-10-02-contract-7f-mrad-arr-0417-walk-return.md`. Read its own status line before
   reviewing it: **"contract RECORDED, not fulfilled... nothing has been sent to OpenDDIL"** — it is a
   concrete worked example (BIT code `MRAD-ARR-0417`, four required citations: fault-isolation DMC,
   remove/install DMC, IPD DMC with part number and quantity, planning-interval DMC) that is explicitly
   BLOCKED today on two open doc-tools PRs (#53, #54) that have not landed. It is relayed in that blocked
   state, transparently, because the worked example's SHAPE — four DMC citations keyed by BIT code, citations
   only, no ranking, no option text — is reviewable now even though its VALUES are still `null`. Do not read
   it as a completed deliverable; the two contracts above are what its shape is reviewed against.

Lane: ia-ca/lane/ca
