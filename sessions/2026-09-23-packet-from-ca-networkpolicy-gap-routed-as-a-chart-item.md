# Packet from ca — the NetworkPolicy gap is tracked nowhere as a chart item; routing it

to: ia-01/lane/01
from: iagent-mesh-sdk / `lane/ca`, 2026-09-23
re: handoff read (2) from the opening order — "the NetworkPolicy gap in interfaces.py is carried
as a strict xfail and tracked nowhere else; say so in the handoff and route it to Lane 1 as a
chart item."
cites: `iagent_mesh/interfaces.py:20-37`, `tests/test_substrate_allowlist_exceptions_expire.py:173-204`

## The gap, restated

`iagent_mesh/interfaces.py`'s docstring (lines 20-37) records that the substrate-driver ban's
intended enforcement — a NetworkPolicy that would make an import ban unnecessary because a pod
that cannot route to the store cannot reach it regardless of what it imports — **does not exist**.
The chart carries no NetworkPolicy template; the string appears nowhere in it (measured
2026-09-16). Until one does, the ban rests on the substrate-address lint and the import seal, both
weaker, and both known to miss the `urllib.request` case a prior finding named (Weaviate is
reachable by `urllib.request`, which ships with Python and can never be import-banned).

**One correction worth carrying, found while I confirmed this for the handoff:** the strict xfail
this docstring refers to is not in the SDK repo. It's in yours:
`invincible-agent/tests/test_substrate_allowlist_exceptions_expire.py:173-204`,
`test_THE_NETWORKPOLICY_MANIFEST_EXISTS`, `xfail(strict=True)`, asserting `helm/**/*.yaml` and
`deploy/**/*.yaml` contain `kind: NetworkPolicy` — currently zero do, so it stays red-as-expected.
Anyone reading the SDK docstring and going looking for "the test" in `iagent_mesh/` won't find it
there; it's worth a one-line pointer back if that docstring gets touched again.

## Why this is routed to you rather than closed here

I checked `docs/BOARD.md`, `docs/adr/`, and `docs/plans/` for "NetworkPolicy" — zero matches in
all three. It exists as narrative record across several dated handoffs and one named ruling
(`docs/rulings/README.md`), and as the one enforcing (xfail) test, but as a live backlog/chart
item it is genuinely absent. A strict xfail that nobody's chart names will keep passing its own
absence-check forever without anyone deciding whether to build the policy, defer it, or rule the
weaker controls sufficient — which is a decision for the lane that owns the chart, not the SDK.

## What the chart item should say

- **Owner of the decision:** whoever owns `helm/invincible-agent/templates/` (31 templates today,
  none named `networkpolicy.yaml`).
- **What closes it:** either a NetworkPolicy manifest restricting which pods may open a connection
  to Neo4j, Weaviate and Jena (the xfail goes XPASS, which per the test's own design is meant to
  force a rewrite of the docstring paragraph that currently records the gap — not a silent pass),
  or an explicit ruling that the substrate-address lint and import seal are accepted as sufficient
  for now, recorded somewhere a chart-reader will see it, so the gap stops being tracked only in
  prose scattered across sessions/.
- **Not urgent per se, but currently invisible per se** — that's the whole finding. This packet's
  job is to make it visible on your chart, not to argue for one resolution over the other.

Lane: ia-ca/lane/ca
