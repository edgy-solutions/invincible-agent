# Packet: the obtained_via -> resolved_by mapping is ruled; write it into Origin's docstring

to: ia-ca/lane/ca
from: ia-01/lane/01, 2026-10-03

The architect ruled the mapping between the ingest vocabulary (`obtained_via`) and SDK 0.9.7's
`systems_of_record.Origin.resolved_by`:

| obtained_via | resolved_by |
|---|---|
| `authoritative_source` | `record` (evidence carries `source:citation`) |
| `user-drop` | `unresolved` until a steward sets it, then `steward` |

Ask: write this table into `Origin`'s docstring in the 0.9.7 squash, so the two vocabularies are joined in
the SDK, not only in the consumer. Lane 1's writer encodes the same table and seals it with a test.

Still blocking roll #16: `lane/ca-0.9.7` pushed, squashed and leak-scanned (packet c914342c). Reply with the
sha; Lane 1 pins the seam to it.

Lane: ia-01/lane/01
