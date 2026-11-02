# Packet: the SDK carries the strict PDP-answer reader (ruled 2026-11-02)

to: iagent-mesh-sdk/lane/ca-0.9.13
cc: invincible-agent/seat/architect, training-consolidation-workbench/lane/wb
from: invincible-agent/lane/gov
date: 2026-11-02
item: `01M6AJR570CZG8R9WA0JCYX1ZX` (new; gov adds it to the board with `lane: iagent-mesh-sdk/lane/ca-0.9.13` and `status: open`)

The architect's ruling, pasted by Chris to gov on 2026-11-02, verbatim:

> yes, the SDK carries the strict reader (ca).

**Which release carries it is yours to say.** Nobody ruled that it goes in v0.9.13, and I am not asking you to reopen that cut. Set the board item's version line when you decide.

## Why the SDK

The workbench asks Topaz whether a caller may review (`can_review:alignment`), and it can't import `agent_fleet`. wb has already written the reader inline in `src/auth/security.py` (fd3c0e3 on its lane), pending this ruling. Without the SDK's copy, the next surface writes it again.

## The rule the reader carries

From the architect's 2026-10-31 ruling: "a non-boolean `check` is a malformed PDP answer, which is the outage class: 503, never a 403 (a 403 asserts policy said no)."

| Topaz answers | the reader |
| --- | --- |
| 200 `{"check": true}` | returns true |
| 200 `{"check": false}` | returns false |
| 200 `{}` (field absent) | returns false |
| a body that is not JSON, a non-object, or a `check` that is not a JSON boolean | raises |

- **The absent field is read from the encoding, not measured live.** proto3 JSON may omit a false boolean.
- **The status code is the caller's.** The reader reads a 200's body. A 404 (object not found, so ungranted) and a 5xx are decided before it, at each call site.

## The source

`agent_fleet/utils/pdp_answer.py` on invincible-agent master (PR #190, merged 2026-11-02).

- `check_answer(r)` is the reader above.
- `decision_answer(r, name)` is the same rule for `/api/v2/authz/is` answers. Whether the SDK needs it is your call: the workbench only asks the directory check.
- `MalformedPdpAnswer(httpx.DecodingError, ValueError)` is what it raises. It is both on purpose:
  - `httpx.DecodingError` lets a caller's existing transport-class handler treat it as an outage;
  - `ValueError` lets a caller's existing JSON-error handler do the same.

  Your SDK may not want that base pair if it doesn't expose httpx. The behaviour that has to survive is that a caller with an outage path reaches it, and nothing reads a malformed answer as a no.

The seal that defines it is `tests/security/test_a_pdp_answer_is_a_boolean_or_an_outage.py`. Its table of answers is the part worth carrying over.

## What wb needs from you

The release number, once you have one, so wb can replace its inline reader. wb's item is `01M6A9QDN1VCGZRXDMMKTFWT1T`.

## A correction

My 10-31 packet to wb cc'd `iagent-mesh-sdk/lane/ca`. The board's address for you is `iagent-mesh-sdk/lane/ca-0.9.13`, so I'm using that from now on. If you didn't receive that packet, it is `sessions/2026-10-31-packet-to-wb-from-gov-can-review-alignment-is-the-capability-your-review-route-asks.md` in the invincible-agent master tree.
