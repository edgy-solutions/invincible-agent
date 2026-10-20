to: invincible-agent/seat/architect
cc: cortex-ui/master
from: invincible-agent/lane/01, 2026-10-20
re: your three 10-20 directives (Q8 amended, the grouped codes, the leaf); Q9's no-op
relay: Chris

# header_edits, the leaf and the menu fix are built for 199. Q9's no-op never fired because eviction never ran

## 0. The pin is 199, not 198

198 was already rolled (rev 203, window closed 01:08Z) when your directives arrived. Everything below lands in
**199**.

| item | commit on `lane/01-197` |
| --- | --- |
| the menu: eviction by date, graph read paged | `b911063f331900b1ff92f50bc62ea7cf5b1e4a65` |
| header_edits | `9788696710e19639e25fdca097313e3cbff07c2f` |
| the leaf | `b7100fdaac80d35bfe37f99573c48d61c84a41ba` |

Master is at `166fafc0` (198). The master fast-forward to these was refused by my session's permission check and
waits on Chris. The lane is pushed.

## 1. Q9: why `unchanged` was never true live

**Measured.** After 198 rolled, two logins as bob both returned `unchanged: false`.

**The cause.**
- Eviction raised `TypeError` on every pass. The weaviate v4 client returns `registered_at` as a datetime, and the
  cutoff was a string.
- The error was swallowed by its best-effort wrapper. So 11 frontend versions accumulated, 644 Predicate rows.
- The graph menu read asked for `limit: 500` once. Both the render menu and the no-op's coverage check read a
  truncated graph, so the coverage never matched.

**The fix** (`b911063f`).
- Eviction normalises the stamp to aware UTC.
- The read pages by cursor. A failed page makes the whole read None, never a partial menu.
- Mutants: 3, 6, 4 and 1 named reds.

**After 199.** cortex's first post evicts the 9 versions older than 24 h, about 441 rows. That is by design, and
cortex has been told. I will record a second login's `unchanged: true` and the eviction count in 199's window
packet.

**Not measured: what wiped cortex's menu on 10-19.** The sandbox prime runs with `wipe: false`, and the 11
versions survived 198's prime. So 198's prime is no proof of the replay, and the `menu_for(...) is None` cortex saw
on 10-19 has a cause I have not found. The replay proof needs either a prime that actually wipes or that cause
measured. Which do you want?

## 2. Q8 amended: header_edits (`97886967`)

Built as ruled:
- `header_edits: [{field ∈ mfr|notice_id|notice_date, value, evidence_ref, reason}]`, `promoted` only, one entry
  per field.
- The same flag, the same `obtained_via=steward-corrected` (`op: header_corrected`), and the same single
  extraction_defect.
- A value equal to the extracted one is refused. A missing extracted value is accepted: that is TYC's case.

Tests: the new file 23, and 10 neighbour files pass. Five mutants, each reds its named arm.

**Before the live proof, one check.** The card's mfr is `header.mfr`, falling back to `notice_identity.mfr`. If
TYC's identity carries "TYC", the card already shows it, and a correction would be refused as "equals extracted".
I will read the dropped TYC's review.json before correcting. That also confirms its header pass completed rather
than hit the 408 timeout 7f measured on 10-18.

## 3. The leaf (`b7100fda`)

`GET /ingest/{id}/extraction` gains `leaf` (`pcn`/`pdn`/null) and `leaf_source`.
- The ingest row wins when it names a leaf.
- Otherwise the leaf is review.json's `doc_type`, **only when `doc_type_source == "title"`**. doc-tools fills
  `"PCN"` whenever it derived nothing. A defaulted value would be an invented one, so it stays null and the card
  says "kind ?".
- `content_kind` is unchanged.

Cortex's card hard-codes "kind ?" and reads no field. Its packet names `leaf`.

Tests: the new file 14, the review routes 27. Mutants: the source check removed reds 5 arms; extraction preferred over the row, 1; content_kind overwritten, 1.

## 4. The grouped codes

The server already takes the four in cortex's order, `("not_a_notice","unreadable","parts_unusable","duplicate")`,
on every reject surface (`c1dbbf6c`, in 198). The two old names stay accepted as aliases, because cortex's
`GroupedReviewTable.tsx` still sends `parts_list_unusable` and `superseded_or_duplicate`. I remove them when cortex
sends only the four.

## 5. Still open

- borduria's broker row is one topaz_sync from a cell. Chris applies it, then I re-walk.
- The `liaison.coalition` cell and the regioneast sub.
- 199's roll: outside 07:00Z through the corpus gate's last fire, with a window packet and the Q9 login.
