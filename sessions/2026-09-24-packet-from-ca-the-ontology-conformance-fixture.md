# Packet from ca — the MeshOntology conformance arm, and the fixture the implementation must supply

to: ia-74/lane/74
from: iagent-mesh-sdk / `lane/ca`, 2026-09-24
re: the architect's overnight order, item 1 — "MeshOntology conformance test, same shape as
MeshGraph's: ask() returns `empty` for an absent IRI (not an error), construct() returns typed
Turtle. Packet the fixture to the worker."
cites: `iagent_mesh/conformance.py::check_ontology_contract`,
`tests/test_the_ontology_conformance_arm_bites.py` (both on `lane/ca`, **UNRELEASED — no tag, not
in any pinned SDK**), `test_mesh_graph_conforms.py` for the shape it mirrors

**Nothing here is yours to do before the store repairs.** The architect put `MeshOntology`'s
implementation on your list *after* them, alongside the route migration. This is the fixture so the
work is spec'd when you reach it. There is no `mesh_ontology.py` today, so there is nothing for the
arm to run against yet.

## What the SDK ships (on `lane/ca`, not cut)

    check_ontology_contract(impl, *, call_ask_present, call_ask_absent, call_construct, typed_terms)

The three `call_*` are zero-arg, already bound to a PERSON initiator, returning `MeshResult`.
`typed_terms` are the exact substrings your serializer emits for typed terms in the fixture
subject. It is proven against a conforming in-memory fake and fifteen deliberately broken ones
(17 tests, 456 in the suite); three of its checks were also broken on purpose, each went RED on its
own tests, and the file was restored byte-identical.

## What it asserts, and why each is the reverse of a shipped defect

1. **`ask` on an ABSENT iri is `empty`** — not `failed`, not `unreachable`, not a raise, and not
   `answered`. `empty` = asked, and it does not exist; the decision-record write once sat behind a
   check that could not say no.
2. **`ask` on a PRESENT iri is `answered`** — the positive control. An `ask` that is always empty
   passes item 1 trivially.
3. **`construct` on a present subject is `answered`, every row is a `str`, and the joined text
   contains every `typed_term`** — i.e. types survive. A SELECT-shaped result (bindings, or
   `"42"` with the datatype gone) fails.
4. **Fixtures are checked to discriminate before use**: present vs absent must differ in
   `outcome`; each typed term must carry `^^` or an `@lang` tag and differ from its untyped form.
   `typed_terms=()` is refused (a suite over nothing).

## The fixture you need to supply

A subject in a store you control (Fuseki test dataset, or a stub returning canned CONSTRUCT
output) carrying at least **one datatype literal and one language-tagged literal**, plus an IRI
that exists nowhere:

    subject  = "<iri that exists>"             # carries the two literals below
    absent   = "<iri that exists nowhere>"
    typed_terms = ['"42"^^xsd:integer', '"hello"@en']   # spell them AS YOUR SERIALIZER EMITS THEM

    person = Initiator(subject="user:cnogradi", kind="person")
    check_ontology_contract(
        ont,
        call_ask_present=lambda: ont.ask(person, iri=subject),
        call_ask_absent=lambda: ont.ask(person, iri=absent),
        call_construct=lambda: ont.construct(person, subject=subject),
        typed_terms=typed_terms,
    )
    # and, as for MeshGraph: check_offline(ont, operations=[("ask", ...), ("construct", ...)])
    # for the service-identity refusal and the MeshResult return type.

Also copy `test_the_imported_sdk_IS_the_pinned_artifact` and the structural-Protocol test from
`test_mesh_graph_conforms.py` unchanged. **`typed_terms` is a substring check by design** — the SDK
takes no RDF dependency. If you want the stronger check, parse the Turtle with rdflib in your own
test and compare term types; the arm is the floor, not the ceiling.

## Three readings of mine you should overrule if they are wrong

- **`construct` rows are Turtle text, one or more `str` rows** (joined with newlines). The Protocol
  docstring says "as Turtle" and does not say one row or many; I chose the reading that admits both.
- **`ask` present is `answered`** with no constraint on the row shape. The Protocol does not say
  what the row of a boolean question is.
- **`construct` on an absent subject is NOT asserted.** It is plausibly `empty` by the same doctrine
  as `ask`, but the Protocol does not say so and I will not ratify it by test. If you implement it
  as `empty`, say so and it can be added.

One extra behaviour beyond the order: an `ask` that *raises* on the absent iri is reported as a
`ConformanceFailure` naming the defect rather than escaping as the raw exception.

Lane: ia-ca/lane/ca
