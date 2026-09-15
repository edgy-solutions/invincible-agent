"""The candidate pool reaches verbs PARAMETERISED BY the subject, not only verbs ABOUT it.

THE DEFECT, measured 2026-09-15 on the live fleet. "how concentrated is purchasing on lot 4"
returned an elicitation from costLotBreakdown instead of a supplier-concentration card, and every
tidy explanation was false:

  * not a synonym gap - costSupplierConcentration carries the near-verbatim synonym
    "how concentrated is purchasing";
  * not a retrieval outage - LLM_BASE_URL was set, reachable from the pod, nomic-embed-text
    present;
  * not a scoring miss - THE TWO VERBS NEVER COMPETED.

costSupplierConcentration hangs off cost#Supplier. The subject resolved to cost#ProductionLot
(0.90) over cost#Supplier (0.29), because the only resolvable instance in the sentence is the
lot. /find_compatible_verbs then returned the five ProductionLot verbs, and the classifier picked
correctly from what it was given.

> ADR-0018's rule worked exactly as written. The verb that answers the question COULD NOT ENTER
> THE ENUM, and no amount of description or synonym work on it can change that.

THE SHAPE THE MISS HAS. costSupplierConcentration declares "lot" as a REQUIRED slot with referent
cost#ProductionLot. It is a Supplier-subject verb PARAMETERISED BY a lot. The question's only
instance mention is that slot's value, not the verb's subject - so subject-first resolution
latches onto the parameter and the pool closes around the wrong class.

THE WIDENING, ruled 2026-09-15: the pool is verbs whose input_uri covers the subject's class
chain (unchanged) PLUS verbs declaring a REQUIRED slot whose referent covers it. ADR-0018's
guarantee survives, because such a verb IS compatible with the subject - parameterised by it
rather than about it.

EDGES, NOT A PARSE, and that decision is why this file exists. r.slots is a JSON string, so
reading referents in Cypher would mean parsing the declaration at query time - a SECOND
implementation of one declaration, which is how two readers come to disagree about it. The
registrar derives a PARAMETERISED_BY edge from the row it already holds; the pool reads edges
through the same door coverage uses.

THE EDGE CONTRACT, AND IT IS A JOIN BETWEEN TWO LANES. The registrar (SDK) writes it and this
query reads it; neither side can assert the pair alone, which is the failure mode that lets a
build succeed while an engine refuses. Written here so the shape is one declaration:

    (verb_subject:OntologyClass)-[:PARAMETERISED_BY]->(referent:OntologyClass)
        verb_iri : the verb's registered iri, joining back to the verb relationship
        slot     : the declaring slot's name
        required : the slot's own required flag, ALWAYS written, true or false

AN EDGE IS WRITTEN FOR EVERY REFERENT-CARRYING SLOT, REQUIRED OR NOT, and the pool does the
filtering. iagent-mesh-sdk-ca asked which of three registrar behaviours this contract means -
edges for all slots, edges only for required ones, or edges with `required` sometimes absent -
and refused to guess, correctly. The answer is the first:

  * the graph then records the whole parameterisation surface, which a later consumer can use
    without a second registration pass;
  * `coalesce(p.required, false)` in the query is DEFENCE against a missing property, not
    permission to omit it. A registrar that leaves `required` off produces an edge this pool
    silently ignores - the shortfall is invisible from either side;
  * and the control arm below only means something if a `required:false` edge can exist. If the
    registrar never wrote one, the arm would be asserting against a case that cannot occur,
    which is a fixture that cannot contain its own failure.

ONLY SPOKEN SLOTS CARRY A REFERENT, SO ONLY SPOKEN SLOTS CAN PARAMETERISE. Named here as an
exclusion with its reason rather than left to be discovered as a missing row. Found by
iagent-mesh-sdk-ca while checking this contract, verified independently at
`agent_fleet/utils/slot_declarations.py:184`:

    if kind.startswith("spoken") and referents and name in referents:
        rec["referent"] = referents[name]

A HANDLE slot is resolved by the dispatcher from the store and was never something a speaker
names, so it has no referent and no edge will ever be written for it - no matter how required it
is. If a verb's only link to a class is through a handle slot, this pool will be CORRECT and
SHORT at the same time, which is the silent-shortfall shape: nothing errors, a row is simply
never there. Widening to handle slots would be a change to what a referent MEANS, not to this
query.

THE DIRECTION IS NOT THE ONE THE RULING DESCRIBED, and the deviation is forced. The ruling said
"an edge from the verb to each required referent class". A verb in this graph IS a relationship -
(subject)-[r:costSupplierConcentration]->(output) - and NEO4J CANNOT ORIGINATE AN EDGE AT A
RELATIONSHIP. So the edge runs from the verb's SUBJECT class to the referent and carries verb_iri
to say which verb it speaks for. Recorded rather than silently substituted: the SDK must write
this shape, not the described one, and a reader comparing the ruling to the code needs to find
the reason here rather than infer a mistake.

VALIDATED ON THE LIVE GRAPH, not asserted from the source. The two-leg query was executed against
the sandbox Neo4j before it was committed - the query it replaces carries its own scar about a
SQL-style comment that took routing down with a 500, so a Cypher change that has only been READ
is not one that has been CHECKED. Leg 2 was then exercised with synthetic classes created,
queried and destroyed inside ONE transaction, so the graph was never left holding a fixture:

    FIRES     mesh:testVerb returned for a subject it only PARAMETERISES     True
    BINDING   input_uri is the VERB's subject, not the resolved subject      True
    CONTROL   a required:false edge does NOT widen the pool                  True
    CONTROL   1 row returned out of the whole graph (ADR-0018 holds)         True
    CLEAN     synthetic nodes left 0, PARAMETERISED_BY edges in graph 0

Run: uv run --frozen pytest tests/routing/test_the_pool_reaches_parameterised_verbs.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ONTO = _REPO / "agent_fleet" / "ontology_service" / "main.py"
_CONST = "_FIND_COMPAT_VERBS_CYPHER = "
_FENCE = chr(34) * 3


def _cypher() -> str:
    """The query as shipped, sliced between its triple-quote fences."""
    src = _ONTO.read_text(encoding="utf-8")
    i = src.index(_CONST) + len(_CONST) + len(_FENCE)
    return src[i:src.index(_FENCE, i)]


def _legs() -> tuple[str, str]:
    a, b = _cypher().split("UNION ALL", 1)
    return a, b


def _columns(text: str) -> list[str]:
    """The RETURN aliases ONLY.

    The first version matched every `AS` in the leg and so swept up leg 1's
    `WITH start, collect(DISTINCT scope) AS scopes` and `UNWIND scopes AS scope` — two
    intermediate bindings that are not columns at all. It then reported a column mismatch
    against a query the live graph had already executed successfully, which is the instrument
    contradicting a measurement. Anchored on RETURN so it reads what a UNION actually compares.
    """
    i = text.index("RETURN DISTINCT")
    return sorted(re.findall(r"AS ([a-z_]+)", text[i:]))


def test_THE_COVERAGE_LEG_IS_UNCHANGED():
    """ADR-0018's original rule is not replaced. A widening that quietly dropped the old leg
    would route by parameterisation ALONE, which is the verb-only regression under a new name."""
    cy = _cypher()
    assert "subClassOf*0..$MAXHOPS$" in cy
    assert "AS compatibility" in cy, (
        "the rows are no longer labelled, so a caller cannot tell which rule admitted a verb"
    )
    assert "subject" in _legs()[0]


def test_THE_PARAMETERISATION_LEG_EXISTS():
    cy = _cypher()
    assert "PARAMETERISED_BY" in cy, (
        "the pool cannot reach a verb parameterised by the subject; the lot 4 question returns "
        "the lot's verbs and never the supplier's"
    )
    assert "referent" in _legs()[1]


def test_ONLY_REQUIRED_SLOTS_WIDEN_THE_POOL():
    """THE ARM WITH TEETH. An OPTIONAL slot's referent would drag in every verb that can merely
    MENTION a class, which is the unconstrained enum ADR-0018 exists to prevent.

    Measured against the live graph with a required:false edge in place: the verb was NOT
    returned, so this is asserting a behaviour that was observed rather than intended.
    """
    _, leg2 = _legs()
    assert re.search(r"coalesce\(p\.required,\s*false\)\s*=\s*true", leg2), (
        "the parameterisation leg does not filter on `required`, so an optional slot widens the "
        "pool and the classifier sees verbs the subject merely appears in"
    )


def test_THE_PARAMETERISED_ROW_REPORTS_THE_VERBS_OWN_SUBJECT():
    """THE BINDING HALF, and getting it wrong is worse than not widening at all.

    A parameterised verb answers about ITS subject - costSupplierConcentration answers about the
    set of suppliers on lot 4 - and the resolved instance belongs in the SLOT. Returning the
    resolved subject as input_uri would tell every downstream reader the verb is about the lot,
    and the arity check would then demand an instance the verb does not take.
    """
    _, leg2 = _legs()
    assert "vsubj.uri" in leg2 and "AS input_uri" in leg2, (
        "the parameterisation leg reports the RESOLVED subject as input_uri, so the binding is "
        "inverted: the answer would claim to be about the parameter"
    )


def test_THE_JOIN_BACK_TO_THE_VERB_IS_BY_IRI():
    """The edge cannot point at a relationship, so it carries the verb's iri instead. Without the
    join, one PARAMETERISED_BY edge would admit EVERY verb on that subject class."""
    _, leg2 = _legs()
    assert "r.iri = p.verb_iri" in leg2, (
        "the leg does not join the edge back to a specific verb, so a single parameterisation "
        "edge admits every verb registered on that subject class"
    )


def test_BOTH_LEGS_RETURN_THE_SAME_COLUMNS():
    """A UNION with mismatched columns is a runtime SyntaxError, and this query's own history is
    a comment character taking routing down with a 500. Checked statically because the failure is
    TOTAL: /find_compatible_verbs returns nothing and every question falls to the generalist."""
    a, b = _legs()
    assert _columns(a) == _columns(b), (
        "the legs return different columns and the query will not parse: "
        "coverage=" + str(_columns(a)) + " parameterised=" + str(_columns(b))
    )


def test_THE_EDGE_CONTRACT_IS_WRITTEN_DOWN_FOR_THE_REGISTRAR():
    """THE JOIN NEITHER SIDE CAN ASSERT ALONE. The SDK writes the edge and this query reads it.
    Both can be internally correct while the pair is wrong - the build succeeds and the pool
    stays empty - so the shape is stated in one place and this asserts it stayed there."""
    doc = Path(__file__).read_text(encoding="utf-8")
    for token in ("verb_iri", "slot", "required", "PARAMETERISED_BY"):
        assert token in doc
    assert "NEO4J CANNOT ORIGINATE AN EDGE AT A" in doc, (
        "the reason the edge direction differs from the ruling is no longer recorded; a reader "
        "will read the deviation as a mistake and fix it into something Neo4j cannot store"
    )


def test_THE_SPOKEN_ONLY_EXCLUSION_IS_READ_FROM_THE_SOURCE_not_restated():
    """The exclusion is asserted against the code that creates it, so it cannot go stale.

    Only SPOKEN slots carry a referent, so only spoken slots can parameterise a verb - a handle
    slot is resolved by the dispatcher from the store and was never something a speaker names.
    That bounds this whole feature, and it is the kind of bound that fails silently: the pool is
    correct and short at the same time, and a missing row looks like nothing at all.

    Written as an assertion on `slot_declarations.py` rather than as a sentence in the docstring
    because a restated constraint is a copy that drifts. If the gate is ever widened to handle
    slots, this fails and the docstring above has to be rewritten deliberately - which is the
    point, since widening it changes what a referent MEANS rather than changing this query.
    """
    decl = _REPO / "agent_fleet" / "utils" / "slot_declarations.py"
    assert decl.is_file(), "the shared slot declaration builder is gone"
    src = decl.read_text(encoding="utf-8")
    gate = re.search(
        r'if kind\.startswith\(.spoken.\)[^\n]*referents[^\n]*:\s*\n\s*rec\["referent"\]',
        src,
    )
    assert gate, (
        "the spoken-only gate on `referent` is no longer in the shared builder. Either handle "
        "slots can now carry a referent - in which case the exclusion documented in this file "
        "is wrong and the pool's reach has changed - or the derivation moved and this seal is "
        "reading a file that no longer decides it. Both need a person."
    )
    doc = Path(__file__).read_text(encoding="utf-8")
    assert "ONLY SPOKEN SLOTS CARRY A REFERENT" in doc


@pytest.mark.parametrize(
    "marker", ["costSupplierConcentration", "ADR-0018", "EDGES, NOT A PARSE"]
)
def test_THE_REASONING_TRAVELS(marker: str):
    """A later reader seeing a two-leg pool will reasonably try to simplify it to one. The
    measured cost of the single-leg version is recorded where that edit would happen."""
    assert marker in Path(__file__).read_text(encoding="utf-8")
