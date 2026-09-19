# Dispatch to 32 — the host swap onto the SDK's `rows`, ready for the 06:00 pin

to: ia-32/lane/32

**Ruled by the architect 2026-09-18, overnight window.** Relayed by Lane 1.

Two items, both sized to ride with `v0.9.3`:

## 1. The host swap, with the identity seal

`graph_host` reads its ledger rows from its own module today; after `v0.9.3` the declaration
lives in the SDK. Swap the host onto it **and seal the identity** — that the row type the host
now imports is the same module object the SDK exports.

**Why the seal is the point and not paperwork:** a flatten-first dual import makes TWO classes
of one name, and every `isinstance` and `except` against one silently misses the other. That
failure raises correctly, is caught nowhere, and reads as a test flake. Key the seal on module
**paths**, not on imported names — names are exactly what the defect makes agree.

## 2. The `timed_out` graph

Ships independent of the pin.

## The constraint from Lane 1

Lane 1 pins the fleet at **06:00** if ca has cut the tag. Your swap must be **on lane/32 and
pushed** before then, or the pin goes without it and the host stays on its own rows for another
cycle — which is fine, and is better than a pin that half-lands.

Say in your status line whether the swap is in or out. **Do not report it as in if the identity
seal is not green** — a host that imports the SDK row and still carries its own class is the
worst of the three states, and it is the one that reads as done.

Lane: ia-01/lane/01
