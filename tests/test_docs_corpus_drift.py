"""`setup/ontologies/docs_corpus.ttl` is GENERATED, committed, and must match its source.

WHY A COMMITTED GENERATED FILE NEEDS A SEAL AND NOT JUST A BUILD STEP. The artifact is checked in
so a reviewer can read what will prime — a generated file produced only at deploy time is a change
nobody reviews. The cost of checking it in is that it becomes a COPY, and a copy stops matching its
source silently. This is the same trade `tests/test_canvas_schema_drift.py` makes for the canvas
JSON Schema, and the same seal shape.

WHAT DRIFT LOOKS LIKE HERE, CONCRETELY: someone edits a runbook's `explains` list, or renames a
page's H1, and does not re-run the generator. The corpus then primes rows describing pages that no
longer say that — and every check downstream is green, because the TTL is internally consistent and
its targets all resolve. **The failure is agreement with the wrong version of the truth.**
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts" / "generate_docs_corpus.py"
TTL = ROOT / "setup" / "ontologies" / "docs_corpus.ttl"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GEN), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_the_generator_exists_and_help_writes_nothing():
    """POSITIVE CONTROL, and the second half is the one that matters: a `--help` that writes the
    artifact would make every check below pass by regenerating what it is about to compare."""
    assert GEN.is_file(), "the generator is gone; every test here would pass vacuously"
    before = TTL.read_bytes() if TTL.is_file() else None
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    after = TTL.read_bytes() if TTL.is_file() else None
    assert before == after, "--help wrote the artifact; the drift check cannot be trusted"


def test_the_committed_corpus_matches_the_frontmatter():
    r = _run("--check")
    assert r.returncode == 0, (
        f"docs_corpus.ttl has drifted from docs/runbooks/*.md — re-run "
        f"`python scripts/generate_docs_corpus.py`.\n{r.stdout}\n{r.stderr}")


def test_the_check_can_say_no():
    """BREAK ON PURPOSE. A drift check that has only ever seen a matching file has not been shown
    able to report a mismatch. Restored by BYTES, not text: a `write_text` restore re-emits
    platform line endings and leaves the file MODIFIED after a PASSING test."""
    original = TTL.read_bytes()
    try:
        TTL.write_bytes(original + b"\n# a line the generator would never write\n")
        r = _run("--check")
        assert r.returncode != 0, "the check passed on a mutated artifact — it is not comparing"
        assert "DRIFT" in (r.stdout + r.stderr).upper(), "the failure does not name drift"
    finally:
        TTL.write_bytes(original)
    assert TTL.read_bytes() == original, "the tree was left mutated by a test"


def test_the_corpus_parses_and_every_page_is_a_DocPage():
    import rdflib
    g = rdflib.Graph()
    g.parse(TTL, format="turtle")
    mesh = rdflib.Namespace("http://invincible-agent/mesh#")
    pages = set(g.subjects(rdflib.RDF.type, mesh.DocPage))
    assert len(pages) >= 5, f"only {len(pages)} DocPage rows — the corpus has shrunk unexpectedly"
    for p in pages:
        assert str(p).startswith("http://invincible-agent/docs#"), (
            f"{p} is not in the docs namespace; an unregistered prefix matches nothing")
        assert (p, rdflib.RDFS.label, None) in g, f"{p} has no label"
        assert (p, mesh.doc_kind, None) in g, f"{p} has no doc_kind"
        assert (p, mesh.audience_hint, None) in g, f"{p} has no audience_hint"


def test_a_page_that_explains_nothing_still_has_a_row():
    """`explains: none` is ADMITTED AND MARKED. This asserts the corpus actually contains such a
    row rather than trusting the generator's branch — a page that explains nothing yet and a page
    nobody wrote must not look the same, and today two pages are in that state."""
    import rdflib
    g = rdflib.Graph()
    g.parse(TTL, format="turtle")
    mesh = rdflib.Namespace("http://invincible-agent/mesh#")
    pages = set(g.subjects(rdflib.RDF.type, mesh.DocPage))
    without = [p for p in pages if (p, mesh.explains, None) not in g]
    assert without, (
        "no page in the corpus has an empty `explains`. If every page now explains something the "
        "branch is untested — point this at a page that does not, or the admitted-and-marked "
        "claim is unproven")


def test_the_manifest_lands_it_in_its_own_domain():
    """A docs entry filed under an existing domain lands in that domain's vocabulary graph. The
    drop set is derived per domain, so the partition is what keeps the sweep correct."""
    sys.path.insert(0, str(ROOT))
    from setup.prime_databases import CANONICAL_TTL_MANIFEST
    rows = [e for e in CANONICAL_TTL_MANIFEST if e.get("name") == "docs_corpus"]
    assert rows, "docs_corpus is not in CANONICAL_TTL_MANIFEST — the corpus would never prime"
    assert rows[0]["domain"] == "DOCS", f"docs_corpus is filed under {rows[0]['domain']!r}"
    assert (ROOT / "setup" / rows[0]["path"]).is_file(), (
        "the manifest points at a file that does not exist — priming would fail for every lane")


def test_the_generator_refuses_an_unregistered_prefix():
    """THE CONTROL ON THE PREFIX GATE, which is the defect that has shipped three times.

    Asserted at the function rather than by mutating a runbook, because the page belongs to
    whoever wrote it and a test must not leave someone else's file changed even briefly.
    """
    sys.path.insert(0, str(ROOT))
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_docs_corpus", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with pytest.raises(SystemExit) as caught:
        mod._prefix_bindings({"mesh", "docs", "nope"})
    assert "nope" in str(caught.value), "the refusal does not name the offending prefix"

    ok = mod._prefix_bindings({"mesh", "docs"})
    assert "http://invincible-agent/docs#" in ok, "a registered prefix is not bound"
