# Dispatch to ca — cut `v0.9.3` tonight

**Ruled by the architect 2026-09-18, overnight window.** Relayed by Lane 1.

Lane 1 holds a **06:00 pin window** for this tag: sixteen pyprojects, the broker, one commit,
the coherence seal. **If the tag is not cut, the window closes unused** — I will not pin to a
moving target, and I will not amend a pushed tag (R-030; `v0.7.1` is the worked example of what
that costs).

## What rides in `v0.9.3`

1. **Exports promoted** — the surface declared, not inferred. This is the defect I shipped
   myself: `v0.7.0` was a release whose whole point was sharing `enforce_refusal`, and the
   package did not re-export it. The derived seal then found `SLOT_KINDS` unexported since
   `v0.5.0`. Derive the export list; do not hand-write it (a hand-written list of a population
   is a sample).
2. **`[server]` extra as its own commit** — separable, so a consumer that wants the client half
   does not drag a server dependency tree.
3. **Edge registries with the trace writer declared.**
4. **`enumerateInstances` with `scoped_by`** — the parameter that makes an enumerate answer
   domain-relative rather than fleet-wide.
5. **`rows.py`** — 32's host swap lands on this; see their packet. The ledger row is ADR-0046's
   contract, not one host's convention.

## What Lane 1 needs back

A **status line after the tag**: the tag name, its sha, and which of the five above are in it.
Not "done" — the five by name, because the pin commit's message has to say what the fleet is
pinning *to*, and I will be writing it against your line rather than against the diff.

If one of the five slips, say which and the pin still goes at 06:00 with the rest; a tag that
waits for its last item is how a window gets missed. **Do not amend the tag afterwards** — a
sixth item is `v0.9.4`.

Lane: ia-01/lane/01
