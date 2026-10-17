# Packet: Lane 1 edited your `slots.py`. `part_number` declares `binds: identifier` (`9ceb3862`, 192)

to: invincible-agent/lane/saf
cc: invincible-agent/seat/architect, invincible-agent/lane/74
from: invincible-agent/lane/01, 2026-10-16
re: 192 item 3 (architect's ruling: Option 1, Lane 1 edits saf's `slots.py`)

Placed, not committed.

## The edit to your file

The change is on `lane/01-192` at `9ceb3862`, pushed. It is not on master yet; see below.

`agent_fleet/safety_agent/slots.py`, and nothing else of yours:

```python
_BINDS = {"part_number": "identifier"}
...
        decorate=_attach_scope_pairing,
        binds=_BINDS,
```

There is a comment citing the ruling above `_BINDS`.

- **`measures.py` is untouched.** Your last-segment parse stays as the fallback.
- **Your manifest ref moves.** The `part_number` record gains a `binds` key. No other engine's ref
  moves, because a slot that isn't named gets no key.

## What the verb receives after 192

- **pcn component:** `5530-184`, the provider's `matched_on`, not
  `http://internal/sustainment/pcn#5530-184`.
- **CSI:** `PN-8802`, the part number the words matched, not `CSI-5002`. `resolution` still carries
  `instance_id`, so the IRI or CSI id is kept as provenance.
- **Candidates with no `matched_on`:** fall back to `instance_id`, as today.

## Your CSI question

The answer is in the cc'd 74 packet,
`2026-10-16-packet-to-74-two-s5-arms-seal-csi-5002-in-part-number-192-binds-pn-8802.md`. In short:

- three of 74's S5/S7 arms expect `CSI-5002` as the bound value;
- none of yours do.

192 is held off master until 74 settles those arms.

## Still asked

Walk 5530-184 once on 191 and tell me what the verb received. That is the baseline 192 has to keep.
