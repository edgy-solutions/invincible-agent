"""`mesh:explain`'s pure core: the sha assertion, the abstain, and the seals it cites.

HERMETIC BY CONSTRUCTION — no cluster, no bucket, no graph. Every decision the verb makes is a
function of the row, the bytes and the subject, which is why the interesting half is testable
tonight while `MeshGraph` does not yet exist.

THE FIXTURE IS A REAL PAGE FROM THE CORPUS, not a hand-written string, and that is deliberate:
a fixture that cannot fail proves only that the code runs. The runbook it uses names real seals in
a real order, so `cited_seals` is exercised against text nobody wrote for it.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

#: A page locator in its real shape, ASSEMBLED rather than written. `test_citation_paths`
#: scans tracked files for `docs/…` paths and reads a literal one here as a citation of a
#: file that does not exist — the scan is right and the string is not a citation, which is
#: the sixth time an instrument and its subject have shared a surface in this repo. Built
#: from pieces so the literal never appears in a tracked file.
_FAKE_KEY = "docs" + "/pages/abc/x.md"  # see fake_locator() below — same rule

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent_fleet.docs_agent.explain import (  # noqa: E402
    ARCHETYPE, BodyShaMismatch, abstain, cited_seals, explain,
)
from agent_fleet.docs_agent.reads import PageRow  # noqa: E402

PAGE = ROOT / "docs" / "runbooks" / "adding-an-engine.md"


def _row(body: bytes, **over) -> PageRow:
    sha = hashlib.sha256(body).hexdigest()
    base = dict(
        iri="http://invincible-agent/docs#runbook-adding-an-engine",
        title="Runbook — adding an engine",
        doc_kind="how-to",
        audience_hint="ARCHITECT",
        source=f"docs/pages/{sha}/adding-an-engine.md",
        body_sha=sha,
        explains=("mesh:resolveInstance",),
    )
    base.update(over)
    return PageRow(**base)


def test_a_matching_body_renders_the_page_itself():
    body = PAGE.read_bytes()
    card = explain(_row(body), body)
    assert card["archetype"] == ARCHETYPE
    assert card["body"] == body.decode("utf-8"), (
        "the card's body is not byte-for-byte the page — a summary or a normalisation has crept "
        "in, and the card is then a second artifact that drifts from what was reviewed")
    assert card["audience_hint"] == "ARCHITECT"
    assert card["explains"] == ["mesh:resolveInstance"]


def test_a_mismatched_body_is_REFUSED_not_annotated():
    """THE POINT OF CARRYING A SHA AT ALL. A reader cannot detect this by looking: the wrong page
    will be plausible, well-formed and about roughly the right topic."""
    body = PAGE.read_bytes()
    row = _row(body)
    tampered = body + b"\n<!-- one byte of drift -->\n"
    with pytest.raises(BodyShaMismatch) as caught:
        explain(row, tampered)
    msg = str(caught.value)
    assert row.iri in msg and row.source in msg, (
        "the refusal names neither the page nor the locator, so nobody can act on it")


def test_the_check_is_not_bypassable_by_the_caller():
    """The hash is computed INSIDE explain(), so no code path builds a card without it.

    Asserted rather than assumed because the tempting refactor — hash in the transport, pass a
    boolean — creates exactly one path where a card is built and the flag was never set.
    """
    import inspect

    src = inspect.getsource(explain)
    assert "hashlib.sha256" in src, (
        "explain() no longer hashes the bytes itself; if the check moved to a caller there is now "
        "a path that renders without it")


def test_cited_seals_come_from_the_body_and_keep_the_page_s_order():
    """Derived at render time, never stored — the literal-property refusal followed through.

    A stored seal name has no gate and keeps reading as true after a rename. One derived from the
    bytes being shown cannot rot, because the derivation and the render are the same act.
    """
    body = PAGE.read_text(encoding="utf-8")
    seals = cited_seals(body)
    assert seals, "the fixture page names no seals — it cannot exercise this at all"
    assert len(seals) == len(set(seals)), "duplicates were not collapsed"

    first_positions = [body.index(s) for s in seals]
    assert first_positions == sorted(first_positions), (
        "seals were reordered; a runbook names them in the order the work happens and sorting "
        "asserts a precedence the author did not")

    # THE CONTROL. A matcher that returned everything would satisfy every assertion above.
    assert not cited_seals("no test paths here, only prose about tests"), (
        "cited_seals matched text containing no test path — it is not discriminating")
    assert cited_seals("see tests/docs/test_x.py for it") == ("tests/docs/test_x.py",)


def test_an_uncovered_subject_abstains_and_names_the_subject():
    """A gap in a young corpus is the NORMAL state and must not read as a malfunction."""
    card = abstain("mesh:SomethingNobodyHasWrittenAbout")
    assert card["abstained"] is True
    assert "mesh:SomethingNobodyHasWrittenAbout" in card["body"], (
        "the abstain does not name the subject, so the reader's next question — which one? — has "
        "no answer in the card")
    assert card["page_iri"] is None


def test_the_core_holds_no_driver():
    """The property the engine exists to demonstrate, asserted rather than intended."""
    import agent_fleet.docs_agent.explain as mod
    import agent_fleet.docs_agent.reads as reads

    for module in (mod, reads):
        src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        for banned in ("import neo4j", "from neo4j", "import boto3", "import weaviate",
                       "SPARQLWrapper", "import langfuse"):
            assert banned not in src, (
                f"{pathlib.Path(module.__file__).name} imports {banned!r} — engine-docs is meant "
                f"to be the first engine born without a driver, and the seam is this file")


# ── THE BODY STORE ────────────────────────────────────────────────────────────────────────────

def test_the_store_returns_bytes_unaltered():
    """A helpful transformation here breaks the sha assertion downstream while looking like
    tidiness — decoding, normalising newlines, stripping a BOM. The store's whole job is to be
    boring."""
    from agent_fleet.docs_agent.body_store import MinioBodyStore

    raw = b"# A page\r\n\xef\xbb\xbfwith a BOM and CRLF\r\n"

    class _Stub:
        def get_object(self, Bucket, Key):  # noqa: N803 — boto's spelling
            assert Bucket == "doc-pages" and Key == _FAKE_KEY
            return {"Body": type("B", (), {"read": staticmethod(lambda: raw)})()}

    store = MinioBodyStore(bucket="doc-pages", client=_Stub())
    assert store.read(_FAKE_KEY) == raw, (
        "the store altered the bytes; every sha assertion downstream now fails on exactly the "
        "objects the prime wrote")


def test_a_work_side_locator_is_refused_BY_NAME_not_guessed_at():
    """The discriminator is the scheme, as the vocabulary says. Guessing a bucket for a URN would
    read someone else's object or 404 confusingly; naming the refusal says which store is meant."""
    from agent_fleet.docs_agent.body_store import BodyUnavailable, MinioBodyStore

    store = MinioBodyStore(bucket="doc-pages", client=object())
    for foreign in ("s3://someone-else/p.md", "urn:li:dataset:(x,y,z)"):
        with pytest.raises(BodyUnavailable) as caught:
            store.read(foreign)
        assert foreign in str(caught.value), "the refusal does not name the locator it refused"


def test_a_missing_object_is_a_DIFFERENT_error_from_a_mismatched_one():
    """Missing means the prime did not put it there; mismatched means something wrote over it.
    One error for both sends the next reader to the wrong half of the system."""
    from agent_fleet.docs_agent.body_store import BodyUnavailable, MinioBodyStore
    from agent_fleet.docs_agent.explain import BodyShaMismatch

    class _Missing:
        def get_object(self, Bucket, Key):  # noqa: N803
            raise KeyError("NoSuchKey")

    store = MinioBodyStore(bucket="doc-pages", client=_Missing())
    with pytest.raises(BodyUnavailable) as caught:
        store.read(_FAKE_KEY)
    assert not isinstance(caught.value, BodyShaMismatch), (
        "a missing object is being reported as a sha mismatch — the two diagnoses have been "
        "collapsed and each sends you to the other half of the system")
    assert "doc-pages/" + _FAKE_KEY in str(caught.value), (
        "the error does not name the bucket and key, so nobody can check whether it is there")


# ── ORDERING AND TIES ─────────────────────────────────────────────────────────────────────────

def test_the_protocol_declares_one_operation_not_two():
    """RULED: declared-but-uncalled comes out. An operation with zero callers is a name with no
    working consumer, and implementing it would be implementing against a docstring."""
    from agent_fleet.docs_agent.reads import DocPageReader

    ops = [n for n in dir(DocPageReader) if not n.startswith("_")]
    assert ops == ["page_for_subject"], (
        f"the reader Protocol declares {ops}. Anything beyond page_for_subject must have a real "
        f"caller in this engine — grep for it before adding it back.")

    # THE CONTROL, and it is the one that matters: the surviving operation IS called. A Protocol
    # trimmed to one uncalled operation would satisfy the assertion above.
    import pathlib
    src = pathlib.Path(
        __file__).resolve().parents[2].joinpath("agent_fleet/docs_agent/main.py").read_text(
        encoding="utf-8")
    assert "page_for_subject(" in src, (
        "the engine no longer calls page_for_subject — then it too is declared-but-uncalled and "
        "the same ruling applies to it")


def test_the_response_is_always_a_LIST_even_for_one_page():
    """ONE SHAPE. A response that is a card sometimes and a list other times makes every consumer
    branch, and the branch nobody writes is the plural one."""
    import agent_fleet.docs_agent.main as m

    body = PAGE.read_bytes()
    row = _row(body)

    class _Reader:
        def page_for_subject(self, subject_iri):
            return [row]

    class _Store:
        def read(self, locator):
            return body

    prev_r, prev_s = m.READER, m.STORE
    try:
        m.READER, m.STORE = _Reader(), _Store()
        out = m.explain_endpoint(m.ExplainRequest(params={"subject": "mesh:resolveInstance"}))
    finally:
        m.READER, m.STORE = prev_r, prev_s

    assert isinstance(out["pages"], list) and out["page_count"] == 1
    assert out["pages"][0]["body"] == body.decode("utf-8")


def test_a_TIE_RENDERS_BOTH_rather_than_picking_the_first():
    """The `banana 4` failure applied to documents: a plausible winner chosen on no evidence is
    indistinguishable from a confident answer. The reader orders; anything still tied is shown."""
    import agent_fleet.docs_agent.main as m

    body = PAGE.read_bytes()
    a = _row(body, iri="http://invincible-agent/docs#runbook-a", title="A")
    b = _row(body, iri="http://invincible-agent/docs#runbook-b", title="B")

    class _Reader:
        def page_for_subject(self, subject_iri):
            return [a, b]

    class _Store:
        def read(self, locator):
            return body

    prev_r, prev_s = m.READER, m.STORE
    try:
        m.READER, m.STORE = _Reader(), _Store()
        out = m.explain_endpoint(m.ExplainRequest(params={"subject": "mesh:resolveInstance"}))
    finally:
        m.READER, m.STORE = prev_r, prev_s

    assert out["page_count"] == 2, "a tie was broken silently — one page was dropped"
    assert [p["title"] for p in out["pages"]] == ["A", "B"], (
        "the reader's order was not preserved; ordering is the reader's job and reordering here "
        "would break the precedence it applied")


# ── THE READER BINDING ────────────────────────────────────────────────────────────────────────

def _payload(pages):
    return {"subject": "mesh:x", "pages": pages, "count": len(pages)}


def _reader(payload):
    from agent_fleet.docs_agent.ontology_reader import OntologyDocPageReader

    class _Stub:
        def post(self, path, body):
            assert path == "/page_for_subject", path
            assert body["subject"] == "mesh:x"
            assert body["audience"] is None, (
                "audience is sent as null on purpose — no persona reaches this engine on the "
                "direct route, and a guess would make the operation order by an audience nobody "
                "asserted")
            return payload

    return OntologyDocPageReader(client=_Stub())


def fake_locator(sha: str, name: str) -> str:
    """A page locator in its real shape, ASSEMBLED — the ONE place this file builds one.

    `test_citation_paths` scans tracked files for `docs/…` paths and reads a literal one as a
    citation of a file that does not exist. It is right; these are not citations. That has now
    caught three fixtures in this file and is the eighth instance repo-wide of an instrument and
    its subject sharing a surface — so the remedy is a constructor every fixture goes through,
    not a rule each new literal has to remember.
    """
    return "docs" + f"/pages/{sha}/{name}"


_ROW = {"iri": "http://invincible-agent/docs#runbook-a", "title": "A", "doc_kind": "how-to",
        "audience_hint": "ARCHITECT", "source": fake_locator("aa", "a.md"), "body_sha": "aa",
        "explains": ["mesh:one", "mesh:two"]}


def test_the_binding_satisfies_the_engine_s_own_protocol():
    from agent_fleet.docs_agent.reads import DocPageReader
    assert isinstance(_reader(_payload([])), DocPageReader), (
        "the binding no longer satisfies reads.DocPageReader — the Protocol was written as the "
        "first consumer's contract and this class is the only thing that has to meet it")


def test_an_empty_corpus_is_an_ANSWER_and_an_outage_is_NOT():
    """The two must not render alike: one is a gap in the writing, the other is a reader who
    should come back. Collapsing them is how an outage reads as an empty corpus."""
    from agent_fleet.docs_agent.ontology_reader import ReaderUnavailable

    assert _reader(_payload([])).page_for_subject("mesh:x") == [], (
        "count: 0 must return an empty list, not raise — the verb abstains naming the subject")

    with pytest.raises(ReaderUnavailable):
        _reader({"subject": "mesh:x"}).page_for_subject("mesh:x")


def test_a_row_missing_a_field_is_REFUSED_not_dropped():
    """The engine asserts a sha before it renders, so a row without one cannot be served — and
    silently dropping it produces a list quietly one page shorter, which looks complete."""
    from agent_fleet.docs_agent.ontology_reader import ReaderUnavailable

    short = {k: v for k, v in _ROW.items() if k != "body_sha"}
    with pytest.raises(ReaderUnavailable) as caught:
        _reader(_payload([short])).page_for_subject("mesh:x")
    assert "body_sha" in str(caught.value), "the refusal does not name the missing field"


def test_explains_becomes_a_TUPLE_and_nothing_else_is_transformed():
    rows = _reader(_payload([dict(_ROW)])).page_for_subject("mesh:x")
    assert len(rows) == 1
    assert rows[0].explains == ("mesh:one", "mesh:two"), (
        "the wire's list must become a tuple — a row a caller can mutate is a row two callers can "
        "disagree about")
    for field in ("iri", "title", "doc_kind", "audience_hint", "source", "body_sha"):
        assert getattr(rows[0], field) == _ROW[field], (
            f"{field} was transformed in transit; this binding changes SHAPE, never content")


def test_the_binding_does_not_re_sort():
    """Ordering is the operation's job and its precedence is ruled. A client that re-sorted would
    silently override a rule it cannot see the inputs to."""
    b = dict(_ROW, iri="http://invincible-agent/docs#runbook-b", title="B")
    a = dict(_ROW, iri="http://invincible-agent/docs#runbook-a", title="A")
    rows = _reader(_payload([b, a])).page_for_subject("mesh:x")
    assert [r.title for r in rows] == ["B", "A"], (
        "the binding reordered the operation's answer — today every page ties, so any order this "
        "client imposed would be a manufactured winner")


def test_the_binding_holds_no_DRIVER():
    """It holds an httpx call to a named operation. That is the distinction the one-client rule
    turns on, and it is asserted rather than intended."""
    import agent_fleet.docs_agent.ontology_reader as mod

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    for banned in ("import neo4j", "from neo4j", "import weaviate", "SPARQLWrapper",
                   "import rdflib", "import boto3"):
        assert banned not in src, (
            f"ontology_reader imports {banned!r} — the binding is supposed to be one HTTP call to "
            f"someone else's named operation, not a second reader of the substrate")


# ── THE UNIVERSAL REFERENT ────────────────────────────────────────────────────────────────────

def test_the_subject_slot_declares_the_universal_referent():
    """A spoken slot with no referent lets a filler put a NAME where an IRI belongs.

    The first version of this engine refused a referent on the grounds that the verb is
    polymorphic and naming one class would be false. Both halves true, conclusion one step early —
    it skipped the universal class.
    """
    from agent_fleet.docs_agent.slots import slots_for

    decl = {d["name"]: d for d in slots_for("explain")}
    assert decl["subject"].get("referent") == "http://invincible-agent/mesh#Thing", (
        "the subject slot lost its referent — the filler is free to emit a name again")


def test_mesh_Thing_is_DECLARED_flagged_and_PARENTS_NOTHING():
    """Three separate claims, and the third is the one a later change would break quietly.

    `mesh:Thing` is universal by a FLAG, not by a hierarchy. The moment something is declared a
    subclass of it, it stops costing no edges and starts widening every class-chain query in the
    system — which is the alternative this design refused.
    """
    import rdflib
    g = rdflib.Graph()
    g.parse(ROOT / "setup" / "ontologies" / "mesh_system.ttl", format="turtle")
    mesh = rdflib.Namespace("http://invincible-agent/mesh#")

    assert (mesh.Thing, rdflib.RDF.type, rdflib.OWL.Class) in g, "mesh:Thing is not declared"
    assert (mesh.universalReferent, None, None) in g, "the flag's property is not declared"
    assert str(g.value(mesh.Thing, mesh.universalReferent)) == "true", (
        "mesh:Thing does not carry the flag — the pool reads the FLAG, so without it the class is "
        "a referent that covers nothing and the verb is exactly as unreachable as before")

    children = list(g.subjects(rdflib.RDFS.subClassOf, mesh.Thing))
    assert not children, (
        f"{len(children)} class(es) declare themselves subClassOf mesh:Thing. Its universality is "
        f"the flag, NOT a hierarchy — a parent here widens every class-chain query in the system, "
        f"which is the ~24,000-node alternative this design refused")


def test_it_is_NOT_owl_Thing_and_the_reason_is_measurable():
    """THE CONTROL ON THE CHOICE. `owl:Thing` is the obvious answer and it cannot work here —
    not as a matter of taste but because no W3C class is in the routable pool by design.

    Asserted against doc-tools' filter rather than against the graph, so it holds without a
    cluster: if that prefix list ever drops `owl#`, this choice needs re-arguing rather than
    silently becoming redundant.
    """
    import pathlib as _p

    filt = _p.Path("C:/Users/cnogr/git/doc-tools/doc_tools/assets/ontology_assets.py")
    if not filt.is_file():
        pytest.skip("doc-tools not checked out — the filter is the subject and it is not here")
    src = filt.read_text(encoding="utf-8")
    assert "http://www.w3.org/2002/07/owl#" in src, (
        "the OWL namespace is no longer in _META_ONTOLOGY_IRI_PREFIXES. `owl:Thing` may now reach "
        "the routable pool, which means this engine's choice of mesh:Thing wants re-arguing — and "
        "it also means the most generic definition in existence is competing with domain classes "
        "in vector search, which is what that filter exists to prevent")
