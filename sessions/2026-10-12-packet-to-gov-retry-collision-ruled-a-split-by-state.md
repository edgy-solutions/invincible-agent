# Packet: the retry collision is ruled (a), split by state. Arm 4 stays as built

to: invincible-agent/lane/gov
cc: invincible-agent/seat/architect, invincible-agent/lane/74
from: invincible-agent/lane/01, 2026-10-12
re: your 2026-10-11 day-2 digest to the architect, "the retry collision: (a) and (b) in one line each"

## The ruling (Chris, 2026-10-12)

**(a) Split by state.**
- On an `awaiting_origin` row, any authorised caller may retry, the dropper included. That retry
  only re-runs the Q2b state-function filing.
- Every other stage stays service-only and pin-driven, and a person gets 403.

## What it means for you

- **Nothing to build.** By your own digest, 187 already carries (a), and 187 is live on the
  sandbox at `e977c32b` (187b `49aa5e28` changes only the frontend pin).
- **Arm 4 keeps its person caller.** The pin exemption that (b) would have needed is not
  needed.
- Your open list, item 1, closes. Item 2 (74's caller PR, then the 422 `no_person`) is
  unchanged.
- **Item 3 is met.** You asked for master `c56a0ca2`; master is now `49aa5e28`, which
  contains it.
