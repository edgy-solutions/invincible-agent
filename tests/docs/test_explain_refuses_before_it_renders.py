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
            assert Bucket == "doc-pages" and Key == "docs/pages/abc/x.md"
            return {"Body": type("B", (), {"read": staticmethod(lambda: raw)})()}

    store = MinioBodyStore(bucket="doc-pages", client=_Stub())
    assert store.read("docs/pages/abc/x.md") == raw, (
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
        store.read("docs/pages/abc/x.md")
    assert not isinstance(caught.value, BodyShaMismatch), (
        "a missing object is being reported as a sha mismatch — the two diagnoses have been "
        "collapsed and each sends you to the other half of the system")
    assert "doc-pages/docs/pages/abc/x.md" in str(caught.value), (
        "the error does not name the bucket and key, so nobody can check whether it is there")
