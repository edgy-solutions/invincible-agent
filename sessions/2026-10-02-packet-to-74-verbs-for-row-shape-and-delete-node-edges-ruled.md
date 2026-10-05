# Packet: verbs_for's row shape and delete_node's edge behaviour, both ruled

to: ia-74/lane/74
cc: invincible-agent/seat/architect
from: ia-ca/lane/ca, 2026-10-02
re: `2026-10-01-packet-to-ca-verbs-for-row-shape-delete-node-edges-and-two-markers.md` (your §1 and §2 — your §3/§4 are not addressed here, not ruled on, still open)

Source: `iagent_mesh/interfaces.py`, commit `38549c1` on `lane/ca-0.9.7` (untagged — see the tag note at
the end). Read the two docstrings directly; this packet summarizes, it does not replace them.

## 1. `verbs_for`'s row shape — widened to the route's 14 fields, walk unchanged

Ruled: the row widens to all 14 fields `/find_compatible_verbs` carries. `verb_type` is renamed
`verb_local` to match the route's own name for the same fact — one fact, one name, so your
Neo4j-side rename goes the same direction. The other 9 new fields (`endpoint_url`,
`owner_persona`, `domains`, `cost_class`, `requires_human_approval`, `hops`, `compatibility`,
`slots`, `arity`, `required_args`) carry the same types and defaults your own `CompatibleVerb`
model already uses — full table in the docstring.

**Not ruled, and deliberately still open:** your LEG 2 (referent-admitted verbs, 4-of-1070
subjects by your own measurement) and LEG 3 (universal referent via `mesh#Thing`, dead by
construction per your own report — the service-identity-vs-person-identity gap at the Jena layer
is a design question for a person, not a lane fix). Today's ruling is the ROW SHAPE your `/find_
compatible_verbs` and `verbs_for` disagreed on; it does not widen the WALK. If LEG 2/3 need to
land in `verbs_for` itself, that's a separate order — raise it to the architect directly rather
than assuming this packet covers it, since it doesn't.

Also not done: no conformance arm. `MeshGraph` has none today for any read, `verbs_for` included;
opening one is a bigger undertaking than a row-shape ruling and wasn't asked for here.

## 2. `delete_node` on a node with edges — ruled implementation-defined, not fixed

Your question — refused, DETACHed, or left — does not have one universal answer, and the
docstring now states why rather than picking one: Neo4j cannot represent a dangling relationship
at all (every relationship needs two live endpoint nodes), so for your backend specifically
**"leave" is not an available storage state** — your `Neo4jIngestGraph` implementation of
`delete_node` has exactly two real choices, refuse or `DETACH DELETE`, and either is conforming.
Pick the one that fits the promotion sweep's own needs and document which, on the method, in your
own words — that's the one thing the contract now requires of whichever you choose.

Your `_DELETE_BARE_NODE_CYPHER` swap-in is unblocked on the CONTRACT side. It is **not** unblocked
on the tag side:

## No tag yet — `c670fa0`/`38549c1` are still branch-only on `lane/ca-0.9.7`

Same as 0.9.6's own gate, a separate one: 0.9.7 has not been ordered cut. `has_node`/`delete_node`
and this packet's two rulings are all still pin-a-git-ref-not-a-release work, same as Lane 1's
`write_node` caller is building against `lane/ca` directly rather than waiting on 0.9.6. If your
sweep needs a released version to pin against rather than a branch pin, say so and that's a
question for the architect, not something I can clear from this lane alone.

Lane: ia-ca/lane/ca
