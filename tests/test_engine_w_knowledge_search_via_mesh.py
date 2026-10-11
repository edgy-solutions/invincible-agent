"""Engine W's knowledge search, flag OFF and flag ON: THE SAME CHUNKS REACH SYNTHESIS.

`KNOWLEDGE_SEARCH_VIA_MESH` moves the retrieval onto the fleet's `MeshVectors` reader
(`agent_fleet/utils/mesh_vectors.py`, `mode="vector_only"`, metadata filters passed through). It
must not move the ENFORCEMENT: the per-chunk `can_read` gate decides what the model sees, on
either path. So the arms below run both paths against one fake cluster and one grant table and
assert they keep the same chunks, drop the same chunks, and project the same Sources relevance.

The differences the flag DOES make are listed in service.py beside the flag, and each has an arm
here that pins it to the path it belongs to, so none of them can drift onto the other path
unnoticed.

The driver's classes are REAL (`weaviate.classes.query.Filter`, `MetadataQuery`), so a filter
asserted here is the object the cluster would receive. Only the client is a double.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SERVICE = _REPO / "agent_fleet" / "weaviate_expert" / "service.py"

# `baml_client` is generated and not importable from a source checkout; Engine W imports it at
# module top and uses nothing from it on the paths under test. Stubbed for the import ONLY, and
# restored, so no later file in the session sees the stub.
_saved = sys.modules.get("baml_client")
_stub = types.ModuleType("baml_client")
_stub.b = types.SimpleNamespace(with_options=lambda **_k: None)
try:
    sys.modules["baml_client"] = _stub
    import agent_fleet.weaviate_expert.service as s  # noqa: E402
finally:
    if _saved is None:
        sys.modules.pop("baml_client", None)
    else:
        sys.modules["baml_client"] = _saved

from agent_fleet.utils.embed import EmbeddingObservation  # noqa: E402

VEC = (0.1, 0.2, 0.3)
VEC2 = (0.9, 0.8, 0.7)
QUERY = "torque spec"
QUERY2 = "bolt pattern"
CALLER = "alice@example.test"
BOB = "bob@example.test"  # holds every grant
CAROL = "carol@example.test"  # holds none
GRANTS = (
    {(CALLER, "https://docs/A"), (CALLER, "https://docs/C")}
    | {(BOB, f"https://docs/{d}") for d in "ABCEF"}
)


def _vec(text):
    """A query-dependent embedding, so the two queries reach DIFFERENT hit sets on both paths."""
    return list(VEC if text == QUERY else VEC2)


# Four chunks, ranked by similarity. B is not granted; D has no resolvable source at all.
CHUNKS = [
    ({"doc_id": "A", "text": "alpha", "page_number": 1, "source_url": "https://docs/A",
      "domain": "SUSTAINMENT"}, 0.91),
    ({"doc_id": "B", "text": "bravo", "page_number": 2, "source_url": "https://docs/B",
      "domain": "SUSTAINMENT"}, 0.83),
    ({"doc_id": "C", "text": "charlie", "page_number": 3, "source_url": "https://docs/C",
      "domain": "SUSTAINMENT"}, 0.72),
    ({"text": "orphan", "domain": "SUSTAINMENT"}, 0.65),
]


def _chunk(d, page, sim):
    return ({"doc_id": d, "text": d.lower(), "page_number": page, "source_url": f"https://docs/{d}",
             "domain": "SUSTAINMENT"}, sim)


# A second query's hits: a different set, a different rank order, five of them (the search limit).
CHUNKS2 = [_chunk("C", 3, 0.95), _chunk("E", 5, 0.88), _chunk("A", 1, 0.50),
           _chunk("B", 2, 0.40), _chunk("F", 6, 0.30)]
CHUNKS_BY_QUERY = {QUERY: CHUNKS, QUERY2: CHUNKS2}


class _Query:
    """The driver's three query shapes, with the metadata each REALLY returns: near_vector's
    `score` is 0.0 whatever is asked; certainty/distance only when asked."""

    def __init__(self, chunks):
        self._chunks = chunks  # a list (every query) or {query text: list}
        self.sent: list[dict] = []

    def _pick(self, kind, kw):
        if not isinstance(self._chunks, dict):
            return self._chunks
        if kind == "near_vector":
            text = QUERY if tuple(kw["near_vector"]) == VEC else QUERY2
        else:
            text = kw["query"]
        return self._chunks[text]

    def _resp(self, kind, kw):
        self.sent.append(dict(kind=kind, **kw))
        asked = kw.get("return_metadata")
        objs = []
        for i, (props, sim) in enumerate(self._pick(kind, kw)[: kw.get("limit", 10)]):
            if kind == "near_vector":
                md = types.SimpleNamespace(
                    score=0.0,
                    certainty=sim if asked.certainty else None,
                    distance=(1 - sim) * 2 if asked.distance else None,
                )
            else:
                md = types.SimpleNamespace(score=sim if asked.score else None,
                                           certainty=None, distance=None)
            objs.append(types.SimpleNamespace(properties=dict(props), metadata=md, uuid=f"u{i}"))
        return types.SimpleNamespace(objects=objs)

    def near_vector(self, **kw):
        return self._resp("near_vector", kw)

    def bm25(self, **kw):
        return self._resp("bm25", kw)

    def hybrid(self, **kw):
        return self._resp("hybrid", kw)


class _Client:
    def __init__(self, chunks=CHUNKS, exists=True):
        self.query = _Query(chunks)
        self._exists = exists
        self.collections = self

    def exists(self, _name):
        return self._exists

    def get(self, name):
        if not self._exists:
            raise RuntimeError(f"collection {name} does not exist")
        return types.SimpleNamespace(query=self.query)


def _observe(text, timeout=30.0):
    return EmbeddingObservation(served="m", requested="m", dimension=len(VEC),
                                vector=tuple(_vec(text)))


def _explode(*_a, **_k):
    raise RuntimeError("embedding gateway down")


@pytest.fixture
def wired(monkeypatch):
    """Auth ON, a grant table, a healthy embed on both paths. Returns a setter for the flag."""
    monkeypatch.setattr(s, "ENABLE_AGENTIC_AUTH", True)
    monkeypatch.setattr(
        s, "_can_read_document",
        lambda caller, src: bool(caller) and bool(src) and (caller, src) in GRANTS,
    )
    monkeypatch.setattr(s, "embed_query", lambda text, **_k: _vec(text))
    monkeypatch.setattr(s, "observe_query_embedding", _observe)

    def flag(on: bool):
        monkeypatch.setattr(s, "KNOWLEDGE_SEARCH_VIA_MESH", on)

    return flag


def _run(client, caller=CALLER, filters=None, query=QUERY):
    return s.retrieve_gated_chunks(
        client, collection_name="DocumentChunks", domain_label="SUSTAINMENT",
        semantic_query=query, metadata_filters=filters, caller_email=caller,
    )


def _render(f):
    """A real driver filter as a comparable value."""
    if f is None:
        return None
    if hasattr(f, "filters"):
        return ("all_of", frozenset(_render(p) for p in f.filters))
    v = f.value
    return (f.operator.value, f.target, tuple(v) if isinstance(v, list) else v)


def _kept_view(kept):
    return [
        (idx, dict(obj.properties), pytest.approx(s._hit_relevance(obj)))
        for idx, obj in kept
    ]


# ── the identity seal: the same chunks, both paths ──────────────────────────────────────────


# (id, caller, query, filters, kept doc_ids at their retrieval positions, dropped, retrieved)
_PARITY = [
    ("some-grants", CALLER, QUERY, None, [(0, "A"), (2, "C")], 2, 4),
    ("every-grant", BOB, QUERY, None, [(0, "A"), (1, "B"), (2, "C")], 1, 4),
    ("no-grants", CAROL, QUERY, None, [], 4, 4),
    ("scalar-filter", CALLER, QUERY, {"doc_id": "A"}, [(0, "A"), (2, "C")], 2, 4),
    ("second-query-some", CALLER, QUERY2, None, [(0, "C"), (2, "A")], 3, 5),
    ("second-query-every", BOB, QUERY2, None,
     [(0, "C"), (1, "E"), (2, "A"), (3, "B"), (4, "F")], 0, 5),
]


@pytest.mark.parametrize("embed_ok", [True, False], ids=["vector", "bm25-degraded"])
@pytest.mark.parametrize("case", _PARITY, ids=[c[0] for c in _PARITY])
def test_the_SAME_chunks_reach_synthesis_with_the_flag_OFF_and_ON(wired, monkeypatch, embed_ok, case):
    """Per (caller, query, filters) case: the gate keeps and drops the same chunks, at the same
    retrieval positions, with the same properties and the same Sources relevance, on BOTH paths,
    and the two paths send the same filter. The cases span a caller holding every grant, some,
    and none; a scalar metadata filter; and a second query whose hits are a different set in a
    different rank order (the double answers per query, so the parity is over different hit sets,
    not one fixed list). Each path is also held to the expected kept ids, so two paths agreeing
    on a wrong answer still fails."""
    _id, caller, query, filters, want_kept, want_dropped, want_retrieved = case
    if not embed_ok:
        monkeypatch.setattr(s, "embed_query", _explode)
        monkeypatch.setattr(s, "observe_query_embedding", _explode)
    views, sent = {}, {}
    for on in (False, True):
        wired(on)
        client = _Client(chunks=CHUNKS_BY_QUERY)
        kept, dropped, retrieved = _run(client, caller=caller, filters=filters, query=query)
        assert (retrieved, dropped) == (want_retrieved, want_dropped), (
            f"flag={on}: retrieved={retrieved} dropped={dropped}")
        assert [(i, o.properties.get("doc_id")) for i, o in kept] == want_kept, f"flag={on}"
        views[on] = _kept_view(kept)
        (one,) = client.query.sent
        sent[on] = _render(one["filters"])
    assert views[True] == views[False]
    assert sent[True] == sent[False]


def test_the_control_with_auth_OFF_both_paths_keep_EVERY_chunk(wired, monkeypatch):
    """The control for the arm above: it differs ONLY in what the gate decides on, so the two
    drops there are the gate's and not the search's."""
    monkeypatch.setattr(s, "ENABLE_AGENTIC_AUTH", False)
    for on in (False, True):
        wired(on)
        kept, dropped, _n = _run(_Client())
        assert (len(kept), dropped) == (4, 0), f"flag={on}"


def test_an_EMPTY_caller_sees_NOTHING_on_either_path(monkeypatch):
    """With the REAL `_can_read_document` (it fails closed on an empty caller before any network).
    OFF: the search runs and the gate drops every chunk. ON: refused before the search — the
    difference numbered 1 in service.py. The refusal is Engine W's named `CallerRequired` (a
    ValueError), raised before the reader is built; the reader's own `Initiator` guard stays
    beneath it as defence in depth."""
    monkeypatch.setattr(s, "ENABLE_AGENTIC_AUTH", True)
    monkeypatch.setattr(s, "embed_query", lambda text, **_k: _vec(text))
    monkeypatch.setattr(s, "observe_query_embedding", _observe)

    monkeypatch.setattr(s, "KNOWLEDGE_SEARCH_VIA_MESH", False)
    kept, dropped, retrieved = _run(_Client(), caller="")
    assert (kept, dropped, retrieved) == ([], 4, 4)

    monkeypatch.setattr(s, "KNOWLEDGE_SEARCH_VIA_MESH", True)
    client = _Client()
    for blank in ("", "   "):
        with pytest.raises(s.CallerRequired):
            _run(client, caller=blank)
    assert client.query.sent == [], "the mesh path searched for a caller it had refused"


# ── the request the mesh path sends ─────────────────────────────────────────────────────────

_EXPECTED_FILTER = ("all_of", frozenset({
    ("Equal", "domain", "SUSTAINMENT"),
    ("Equal", "doc_id", "TM-1"),
    ("Equal", "page_number", 3),
}))


@pytest.mark.parametrize("on", [True, False], ids=["mesh", "direct-control"])
def test_vector_only_with_the_domain_AND_the_callers_filters(wired, on):
    """ON: what the reader sends. OFF is the control — the same filters reach the same query, so
    the only thing the flag changes about the REQUEST is who builds it."""
    wired(on)
    client = _Client()
    _run(client, filters={"doc_id": "TM-1", "page_number": 3})
    (sent,) = client.query.sent
    assert sent["kind"] == "near_vector", f"vector_only reached {sent['kind']!r}"
    assert sent["limit"] == s.KNOWLEDGE_SEARCH_LIMIT
    assert list(sent["near_vector"]) == list(VEC)
    assert _render(sent["filters"]) == _EXPECTED_FILTER


def test_the_mesh_read_is_ATTRIBUTED_to_the_caller_as_a_person(wired, monkeypatch):
    seen = []
    real = s.WeaviateVectors.nominate

    def spy(self, initiator, **kw):
        seen.append((initiator, kw))
        return real(self, initiator, **kw)

    monkeypatch.setattr(s.WeaviateVectors, "nominate", spy)
    wired(True)
    _run(_Client())
    ((initiator, kw),) = seen
    assert (initiator.subject, initiator.kind) == (CALLER, "person")
    assert (kw["mode"], list(kw["domains"])) == ("vector_only", ["SUSTAINMENT"])


def test_a_SERVICE_initiator_is_refused_by_the_reader_Engine_W_now_calls():
    """The person guard the ON path inherits. Engine W never builds a service initiator; this
    pins that the reader it calls would refuse one rather than search."""
    from iagent_mesh.interfaces import Initiator

    client = _Client()
    impl = s.WeaviateVectors(client=client, embed=_observe, filters=s.wvc.query.Filter,
                             metadata=s.wvc.query.MetadataQuery)
    with pytest.raises(Exception, match="(?i)service"):
        impl.nominate(Initiator(subject="engine-w", kind="service"),
                      collection="DocumentChunks", text="q")
    assert client.query.sent == []


def test_a_DEGRADED_mesh_search_is_MARKED(wired, monkeypatch, capsys):
    monkeypatch.setattr(s, "observe_query_embedding", _explode)
    wired(True)
    client = _Client()
    _run(client)
    assert client.query.sent[0]["kind"] == "bm25"
    assert "DEGRADED to bm25" in capsys.readouterr().out


@pytest.mark.parametrize("outcome", ["failed", "unreachable"])
def test_a_mesh_FAILURE_raises_rather_than_reading_as_nothing_found(wired, monkeypatch, outcome):
    from iagent_mesh.interfaces import MeshResult

    monkeypatch.setattr(s.WeaviateVectors, "nominate",
                        lambda self, i, **kw: getattr(MeshResult, outcome)("boom"))
    wired(True)
    with pytest.raises(RuntimeError, match=outcome):
        _run(_Client())


# ── the named differences, each pinned to its path ──────────────────────────────────────────


def test_difference_2_a_LIST_filter_is_membership_ON_and_equal_OFF(wired):
    got = {}
    for on in (False, True):
        wired(on)
        client = _Client()
        _run(client, filters={"doc_id": ["A", "C"]})
        got[on] = _render(client.query.sent[0]["filters"])
    assert ("ContainsAny", "doc_id", ("A", "C")) in got[True][1]
    assert ("Equal", "doc_id", ("A", "C")) in got[False][1]


def test_difference_3_a_sourceless_chunk_s_card_URI_is_doc_and_page_ON(wired, monkeypatch):
    """Two chunks of one page with no source_url/uri: ON they share a derived uuid (one card);
    OFF each keeps its object's uuid."""
    monkeypatch.setattr(s, "ENABLE_AGENTIC_AUTH", False)
    page = [({"doc_id": "TM-9", "text": "x", "page_number": 4}, 0.9),
            ({"doc_id": "TM-9", "text": "y", "page_number": 4}, 0.8)]
    wired(True)
    kept, _d, _n = _run(_Client(chunks=page))
    assert [o.uuid for _i, o in kept] == ["TM-9/p4", "TM-9/p4"]
    wired(False)
    kept, _d, _n = _run(_Client(chunks=page))
    assert [o.uuid for _i, o in kept] == ["u0", "u1"]


def test_difference_4_an_ABSENT_collection_is_empty_ON_and_an_error_OFF(wired):
    wired(True)
    assert _run(_Client(exists=False)) == ([], 0, 0)
    wired(False)
    with pytest.raises(RuntimeError, match="does not exist"):
        _run(_Client(exists=False))


# ── the live tool: an empty caller is a NAMED refusal on the mesh path ──────────────────────


def _drive_live_tool(monkeypatch, client, request):
    """Run `query_knowledge` with everything above the tool doubled, call the REAL
    `search_knowledge_base_local` closure the smolagent is handed, and return what it answered."""
    answers = []

    class _Agent:
        def __init__(self, tools, **_k):
            self._tools = tools

        def run(self, _q):
            answers.append(self._tools[0](semantic_query=QUERY))
            return "ok"

    class _Ctx:
        async def run(self, _name, fn):
            return await fn()

    async def _format(raw, domain):
        return types.SimpleNamespace(model_dump=lambda: {"answer": raw})

    monkeypatch.setattr(s, "get_weaviate_client", lambda: client)
    monkeypatch.setattr(s, "fetch_weaviate_schema", lambda *_a: "schema")
    monkeypatch.setattr(s, "get_smolagent_model", lambda: None)
    monkeypatch.setattr(s, "ToolCallingAgent", _Agent)
    monkeypatch.setattr(s, "b", types.SimpleNamespace(FormatKnowledgeResponse=_format))
    asyncio.run(s.query_knowledge(_Ctx(), request))
    (answer,) = answers
    return answer


_BLANKS = [{"user_query": "q", "user_email": ""}, {"user_query": "q", "user_email": "   "},
           {"user_query": "q"}]
_BLANK_IDS = ["empty", "whitespace", "missing"]


@pytest.mark.parametrize("request_", _BLANKS, ids=_BLANK_IDS)
def test_an_EMPTY_caller_gets_a_NAMED_refusal_from_the_live_tool_and_NO_search(
        wired, monkeypatch, request_):
    """Flag ON: the tool answers the refusal that names the cause (a person's behalf, no
    user_email) -- not the generic error string, not "No relevant information" -- and the double
    records zero queries."""
    wired(True)
    client = _Client()
    answer = _drive_live_tool(monkeypatch, client, request_)
    assert answer == s.KNOWLEDGE_CALLER_REQUIRED_REFUSAL
    assert "user_email" in answer and "behalf" in answer
    assert not answer.startswith("Error executing") and "No relevant information" not in answer
    assert client.query.sent == [], "the mesh path searched for a caller it had refused"


@pytest.mark.parametrize("request_", _BLANKS, ids=_BLANK_IDS)
def test_control_flag_OFF_an_EMPTY_caller_still_SEARCHES(wired, monkeypatch, request_):
    """The control: the change is confined to the mesh path. OFF, the search runs (the double
    records a query) and the gate -- not a refusal -- decides; with auth on every chunk is dropped."""
    wired(False)
    client = _Client()
    answer = _drive_live_tool(monkeypatch, client, request_)
    assert len(client.query.sent) == 1
    assert answer != s.KNOWLEDGE_CALLER_REQUIRED_REFUSAL
    assert answer.startswith("No accessible information found")


# ── the flag itself ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,on", [(None, True), ("", False), ("false", False),
                                    ("true", True), ("1", True), ("YES", True), ("0", False)])
def test_the_flag_DEFAULTS_ON_and_reads_the_env_at_import(monkeypatch, raw, on):
    """Unset is ON; a value that is SET is parsed as written ("false", "0" and "" turn it off).
    A fresh module object under a private name, so the module every other arm patches is not
    reloaded under them."""
    if raw is None:
        monkeypatch.delenv("KNOWLEDGE_SEARCH_VIA_MESH", raising=False)
    else:
        monkeypatch.setenv("KNOWLEDGE_SEARCH_VIA_MESH", raw)
    monkeypatch.setitem(sys.modules, "baml_client", _stub)
    spec = importlib.util.spec_from_file_location("_engine_w_fresh", _SERVICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.KNOWLEDGE_SEARCH_VIA_MESH is on
