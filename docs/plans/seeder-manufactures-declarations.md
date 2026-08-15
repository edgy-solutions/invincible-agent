---
id:         seeder-manufactures-declarations
status:     open
owner:      agent
blocked-on: nothing — the instance is fixed and the sweep is clean; what remains is making the mechanism unable to recur.
closed-by:
code-site:  scripts/seed_sandbox_predicates.py:243
repo:       invincible-agent
summary:    The sandbox seeder MERGEs endpoint OntologyClass nodes as a SIDE EFFECT of seeding a predicate, so it manufactures declarations no TTL contains. Sandbox is green forever and no fresh cluster can be — and nothing inside sandbox can detect the difference.
---

# A seeder that repairs the substrate it seeds against

`seed_sandbox_predicates.py:243-244`:

```cypher
MERGE (s:OntologyClass {uri: $input_uri})
MERGE (o:OntologyClass {uri: $output_uri})
```

MERGE, not MATCH. Seeding a predicate CREATES its endpoint classes if they are absent. So a
verb whose output class no TTL declares works perfectly in sandbox and is impossible on any
fresh cluster.

## The instance, and why it was invisible

`mesh:proposeDisposition` has named `mesh#DispositionReview` as its `output_uri` since the
verb woke. **No TTL in the repo declared that class.** It existed only because the seeder
manufactured it.

Witnessed at work 2026-08-14: nine of Engine A's ten verbs registered after a restart and this
one could not, ever. The registrar's MATCH-not-MERGE is what exposed it, and its Contract D
422 was literally true — no restart conjures a class no source declares.

Fixed at the source (declared in `mesh_system.ttl`, 22 classes → 23). **The mechanism is
still live** and will do it again for the next verb someone seeds.

## This is a distinct species of [[bootstrap-state-debt]]

The law's usual form is state a human created by hand and forgot to reproduce. This is worse
in a specific way: **no observation from inside sandbox can find it.** Running longer, testing
harder, or checking more carefully all fail, because the checking tool is the thing creating
the state. The gap is only visible from a cluster that never ran the seeder.

That is the argument this instance contributes: sandbox fidelity has a ceiling, and it is not
raised by more testing.

## The sweep — bounded, not hoped

All 10 distinct `input_uri`/`output_uri` values in the seeder, resolved through its own
`_MESH`/`_IDP` prefix constants, against the 56 `owl:Class` declarations across the 10 TTLs in
`prime_databases.py`'s manifest: **0 undeclared** with `DispositionReview` added.
`mesh:DispositionReview` was the last one.

(A first pass reported `mesh#Dataset` missing — the checking script folded `_IDP + "Dataset"`
with a hardcoded `mesh#` prefix. Reading the prefix constants rather than assuming them
produced the clean result. Worth repeating if the sweep is ever automated.)

## Work

1. **MATCH, not MERGE** in the seeder, so it fails loudly on an undeclared class exactly as
   the registrar does. A seeder that cannot manufacture a declaration cannot hide one.
2. **Or run the sweep in CI** — every endpoint URI in the seeder against the manifest's TTLs.
   Mechanical, already written once, and it converts the whole class into a build failure.
3. **The honest-docstring obligation** from the bootstrap-state-debt law: the script must name
   itself a non-reproducible manual action and point at its reproducible home. The phase5
   docstring lie is the anti-pattern that law forbids, and this is the same shape.

Option 1 is the durable one: it removes the capability rather than auditing its use.
