"""ADR-0019 Contract A — Engine O ``/classify_predicate`` soundness gate.

Companion to ``test_adr0019_contracts.py``. That file tests the *supervisor's*
contracts (routing decisions assuming Engine O behaves correctly). This file
tests Engine O's ``/classify_predicate`` directly: it asserts the N=1 branch
calls the LLM with the constrained two-value enum ``{verb_iri, UNKNOWN}``,
rather than short-circuiting and returning the lone verb at 0.99.

Why split this out
------------------
The N=1 shortcut bug lives inside Engine O's endpoint (currently at
``agent_fleet/ontology_service/main.py`` lines ~1803-1825), not in the
supervisor's HTTP call. Stubbing the supervisor's ``requests.post`` cannot
catch it — the stub returns whatever it's told. The only way to assert the
contract is to load Engine O's module and observe whether BAML
(``b.ClassifyPredicate``) was invoked.

Contract A (from ADR-0019 §2):

> At N=1, **still call the LLM**, constrained to a two-value enum
> ``{the_verb, UNKNOWN}``. The graph supplies the candidate *set*; the LLM
> validates *fit*.

Until the shortcut is replaced, ``test_n1_calls_baml_with_two_value_enum``
goes red. That red **is** the punch-list entry for the Engine O fix.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

# INTEGRATION: needs a live Engine O. SKIPS when unreachable, RUNS AND FAILS when it is up
# (tests/routing/conftest.py). Before this marker existed the module documented itself as
# "skips if Engine O isn't reachable" while actually emitting ConnectionError failures — an
# environmental fact wearing a defect's clothes, ~32 per run, for months.
pytestmark = pytest.mark.requires_engine_o


_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Stubs — duplicated from test_predicate_hybrid_search.py for self-containment.
# Changes there must not silently affect this file's assertions; same logic.
# ---------------------------------------------------------------------------
def _install_stubs():
    if "rdflib" not in sys.modules:
        rdflib = types.ModuleType("rdflib")

        class _NS:
            def __init__(self, *_a, **_kw):
                pass
        rdflib.Namespace = _NS
        rdflib.Graph = type("Graph", (), {})
        sys.modules["rdflib"] = rdflib

    # Always overwrite weaviate + weaviate.classes; other test modules
    # install MagicMocks for those that confuse the imports.
    wv = types.ModuleType("weaviate")
    sys.modules["weaviate"] = wv
    wvc = types.ModuleType("weaviate.classes")

    class _Q:
        class Filter:
            @staticmethod
            def any_of(parts):
                return ("any_of", parts)

            @staticmethod
            def by_property(name, length=False):
                class _P:
                    def contains_any(self, vals):
                        return ("contains_any", name, vals)

                    def equal(self, val):
                        return ("equal", name, val)
                return _P()

        class MetadataQuery:
            def __init__(self, **kw):
                self.kw = kw
    wvc.query = _Q

    class _CCfg:
        class DataType:
            TEXT = "TEXT"
            TEXT_ARRAY = "TEXT_ARRAY"
            BOOL = "BOOL"

        class Property:
            def __init__(self, *a, **kw):
                pass
    wvc.config = _CCfg
    sys.modules["weaviate.classes"] = wvc
    wv.classes = wvc

    if "neo4j" not in sys.modules:
        n = types.ModuleType("neo4j")
        n.GraphDatabase = type(
            "GraphDatabase", (),
            {"driver": staticmethod(lambda *a, **k: None)},
        )
        sys.modules["neo4j"] = n

    if "baml_client" not in sys.modules:
        bc = types.ModuleType("baml_client")
        bc.b = object()
        sys.modules["baml_client"] = bc
    if "baml_client.types" not in sys.modules:
        t = types.ModuleType("baml_client.types")

        class _R:
            pass
        t.SemanticResolution = _R
        sys.modules["baml_client.types"] = t
    if "baml_client.type_builder" not in sys.modules:
        tb_mod = types.ModuleType("baml_client.type_builder")

        # The real TypeBuilder is opaque; for this test the only thing
        # we need is for ``tb.Predicate.add_value(iri).description(text)``
        # to record every value so we can assert what enum the LLM saw.
        class _ValueBuilder:
            def __init__(self, iri, registry):
                self._iri = iri
                self._registry = registry
                registry[iri] = ""

            def description(self, text):
                self._registry[self._iri] = text
                return self

        class _PredicateEnumBuilder:
            def __init__(self, registry):
                self._registry = registry

            def add_value(self, iri):
                return _ValueBuilder(iri, self._registry)

        class _TB:
            def __init__(self):
                self.values: dict[str, str] = {}
                self.Predicate = _PredicateEnumBuilder(self.values)
        tb_mod.TypeBuilder = _TB
        sys.modules["baml_client.type_builder"] = tb_mod

    if "utils" not in sys.modules:
        sys.modules["utils"] = types.ModuleType("utils")
    if "utils.weaviate_utils" not in sys.modules:
        m = types.ModuleType("utils.weaviate_utils")
        m.create_weaviate_client = lambda *a, **k: None
        sys.modules["utils.weaviate_utils"] = m


@pytest.fixture(scope="module")
def ontology_main():
    _install_stubs()
    spec = importlib.util.spec_from_file_location(
        "ontology_main_contract_a_test",
        str(_REPO / "agent_fleet" / "ontology_service" / "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# BAML call recorder — what the LLM was asked, if anything
# ---------------------------------------------------------------------------
class _BAMLRecorder:
    """Records calls to ``b.ClassifyPredicate``. Returns a canned response so
    the endpoint continues past the LLM step."""

    def __init__(self, response_iri: str = "UNKNOWN",
                 response_confidence: float = 0.10,
                 response_reasoning: str = "stub: declined"):
        self.calls: list[dict] = []
        self.response_iri = response_iri
        self.response_confidence = response_confidence
        self.response_reasoning = response_reasoning

    async def ClassifyPredicate(self, **kwargs):
        self.calls.append({
            "query": kwargs.get("query"),
            "subject_uri": kwargs.get("subject_uri"),
            "subject_reasoning": kwargs.get("subject_reasoning"),
            "domain": kwargs.get("domain"),
            "tb_values": (
                # The TypeBuilder stub records add_value calls; pull the
                # enum the LLM was offered out of baml_options.
                dict(kwargs["baml_options"]["tb"].values)
                if "baml_options" in kwargs else None
            ),
        })

        class _R:
            resolved_verb_iri = self.response_iri
            confidence_score = self.response_confidence
            reasoning = self.response_reasoning
        return _R()


# ---------------------------------------------------------------------------
# The contract-critical test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_n1_calls_baml_with_two_value_enum(ontology_main, monkeypatch):
    """**Contract A teeth.** When the supervisor passes a single
    ``compatible_verb_iri`` (Neo4j said N=1), Engine O's
    ``/classify_predicate`` MUST still call BAML and MUST offer a
    constrained enum that contains both the verb AND ``UNKNOWN`` — so the
    LLM can decline if the lone verb does not fit the query.

    **History — read before editing this test.** This test was authored
    when an N=1 cardinality shortcut existed at
    ``agent_fleet/ontology_service/main.py:1803-1825``, which returned
    the lone verb at confidence 0.99 without invoking BAML. The
    original setup stubbed ``predicate_hybrid_search`` to return ``[]``
    and relied on a "synthesize-stub-from-bare-IRIs" fallback so the
    BAML call still happened — that's what made the assertion teeth
    bite the shortcut.

    The shortcut WAS removed (see the post-fix comment at
    ``main.py:2183-2198``). Separately, the synthesize-stub fallback
    was removed 2026-06-13 in service of ADR-0006 §Addendum's
    conjunctive-read invariant (no Weaviate match → unregistered →
    UNKNOWN without LLM). That second change invalidated the original
    setup: empty-Weaviate now short-circuits to UNKNOWN at
    ``main.py:2200-2230`` *before* reaching BAML, so the test was
    failing on a stale setup path rather than on a contract violation.

    The setup below makes ``predicate_hybrid_search`` RETURN the verb
    as a real Weaviate candidate — that's the production path for an
    N=1 query whose verb is registered in both stores. The assertion
    teeth are unchanged because the contract is unchanged: BAML must
    be called with ``{verb, UNKNOWN}``. The test now catches a
    re-introduction of the N=1 shortcut INDEPENDENTLY of the
    conjunctive-read tightening, restoring a safety assertion that
    was inert from 2026-06-13 until this rewrite (2026-06-13 late).
    """
    # Recorder injected as the module-level ``b`` (BAML client). Real
    # production binds ``b.ClassifyPredicate`` to the LLM; we swap it
    # out so the test observes whether the endpoint even tried.
    recorder = _BAMLRecorder(response_iri="UNKNOWN", response_confidence=0.05)
    monkeypatch.setattr(ontology_main, "b", recorder)

    # Stub predicate_hybrid_search to RETURN the verb as a Weaviate
    # candidate (production path for an N=1 query whose verb is
    # registered in both Cypher AND Weaviate — the conjunctive-read
    # invariant requires both for the verb to enter the enum). The
    # candidate dict shape matches what real predicate_hybrid_search
    # returns; see main.py:2286-2337 for the field accesses.
    async def _hybrid_returns_verb(*_args, **_kwargs):
        return [{
            "verb_iri": "mesh:queryKnowledgeGraph",
            "input_uri": "mro:WorkInstruction",
            "description": "Knowledge graph expert (test stub).",
            "verb_type": "ObjectProperty",
            "owner_persona": "AUDITOR",
        }]
    monkeypatch.setattr(ontology_main, "predicate_hybrid_search", _hybrid_returns_verb)

    request = ontology_main.ClassifyPredicateRequest(
        query="what color was Napoleon's horse?",  # off-topic by design
        subject_uri="mro:WorkInstruction",
        subject_reasoning="A WorkInstruction matches the user's query.",
        entitled_domains=[],
        domain="MAINTENANCE",
        compatible_verb_iris=["mesh:queryKnowledgeGraph"],  # N=1
    )

    response = await ontology_main.classify_predicate(request)

    # ----- Teeth (1): BAML MUST have been called. -----
    assert len(recorder.calls) >= 1, (
        "Contract A: at N=1, /classify_predicate must call BAML with a "
        "constrained two-value enum ({verb, UNKNOWN}). If this fails, "
        "either an N=1 cardinality shortcut has been re-introduced "
        "(the original bug this test was written to catch) or the "
        "setup short-circuited before BAML — read the docstring for "
        "the conjunctive-read trace before assuming the latter."
    )

    # ----- Teeth (2): the enum must contain BOTH the verb AND UNKNOWN. -----
    # The LLM must have an escape hatch; cardinality cannot be presented
    # as fit. The TypeBuilder stub records every add_value call, so we
    # can inspect exactly what the LLM was offered.
    call = recorder.calls[0]
    offered = call["tb_values"] or {}
    assert "mesh:queryKnowledgeGraph" in offered, (
        f"Contract A: the constrained enum at N=1 must include the lone "
        f"verb. Got enum members: {list(offered)}"
    )
    assert "UNKNOWN" in offered, (
        f"Contract A: the constrained enum at N=1 must include UNKNOWN as "
        f"an escape so the LLM can decline when the lone verb does not "
        f"fit. Without UNKNOWN, cardinality silently coerces to fit. "
        f"Got enum members: {list(offered)}"
    )
    assert len(offered) == 2, (
        f"Contract A: the constrained enum at N=1 must be exactly two-"
        f"valued (the verb + UNKNOWN). Got {len(offered)} members: "
        f"{list(offered)}"
    )

    # ----- Teeth (3): the off-topic LLM verdict must propagate. -----
    # When BAML returns UNKNOWN (as our recorder simulates), the endpoint
    # must return UNKNOWN — not coerce back to the lone verb.
    assert response.resolved_verb_iri == "UNKNOWN", (
        f"Contract A: when the LLM declines within the constrained enum, "
        f"/classify_predicate must propagate UNKNOWN. Got "
        f"{response.resolved_verb_iri!r}. If the endpoint is rewriting "
        f"UNKNOWN to the verb because N=1 still 'looks decisive', the "
        f"shortcut has only moved later in the function."
    )


@pytest.mark.asyncio
async def test_n1_on_topic_still_dispatches(ontology_main, monkeypatch):
    """The Contract-A fix must not over-correct. When BAML confirms the
    lone verb at N=1 (on-topic query), the endpoint dispatches it.

    Companion to ``test_n1_calls_baml_with_two_value_enum`` — that one
    asserts BAML is *called* and *can decline*; this one asserts the
    happy path (LLM confirms within the two-value enum → endpoint
    returns the confirmed verb). Both share the same conjunctive-read
    pre-condition: the verb must be present in BOTH Cypher AND
    Weaviate for execution to reach BAML at all (ADR-0006 §Addendum,
    2026-06-13). Same setup-rewrite history as the sibling test —
    see its docstring for the trace.

    Now load-bearing in both directions: it confirms the LLM was
    actually invoked AND that its verb verdict propagates. Before the
    rewrite this was vacuously green when the shortcut existed AND
    silently red after the conjunctive-read tightening removed the
    setup's reach to BAML.
    """
    recorder = _BAMLRecorder(
        response_iri="mesh:queryKnowledgeGraph",
        response_confidence=0.85,
        response_reasoning="stub: lone verb fits on-topic query",
    )
    monkeypatch.setattr(ontology_main, "b", recorder)

    async def _hybrid_returns_verb(*_args, **_kwargs):
        return [{
            "verb_iri": "mesh:queryKnowledgeGraph",
            "input_uri": "mro:WorkInstruction",
            "description": "Knowledge graph expert (test stub).",
            "verb_type": "ObjectProperty",
            "owner_persona": "AUDITOR",
        }]
    monkeypatch.setattr(ontology_main, "predicate_hybrid_search", _hybrid_returns_verb)

    request = ontology_main.ClassifyPredicateRequest(
        query="What is the work instruction for procedure 1234?",
        subject_uri="mro:WorkInstruction",
        subject_reasoning="WorkInstruction matches.",
        entitled_domains=[],
        domain="MAINTENANCE",
        compatible_verb_iris=["mesh:queryKnowledgeGraph"],
    )

    response = await ontology_main.classify_predicate(request)

    # Teeth (1): BAML was actually called (no over-correction skipping
    # the LLM on cardinality alone).
    assert len(recorder.calls) >= 1, (
        "Contract A: even on the on-topic happy path, /classify_predicate "
        "must call BAML at N=1 — the LLM validates fit, the graph just "
        "supplies the candidate set. If this fails the shortcut was "
        "re-introduced as a 'fast path for confident routes' or similar."
    )

    # Teeth (2): the confirmed verb propagates back.
    assert response.resolved_verb_iri == "mesh:queryKnowledgeGraph"
