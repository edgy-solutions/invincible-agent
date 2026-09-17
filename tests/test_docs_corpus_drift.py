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


# ── THE POINTER HALF ──────────────────────────────────────────────────────────────────────────

def test_every_page_carries_a_locator_and_a_sha_that_match_the_file():
    """THE GRAPH HOLDS A POINTER, NEVER THE MARKDOWN, so the pointer has to be true.

    Three things must agree, and they are computed in three different places: the sha in the row,
    the sha embedded in the content-addressed key, and the sha of the bytes on disk. Any two
    agreeing while the third does not is a page that resolves to nothing at answer time — the
    failure a reader sees and no CI check would.
    """
    import hashlib
    import importlib.util

    import rdflib
    spec = importlib.util.spec_from_file_location("gen_docs_corpus", GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    g = rdflib.Graph()
    g.parse(TTL, format="turtle")
    mesh = rdflib.Namespace("http://invincible-agent/mesh#")

    rows = {}
    for page in g.subjects(rdflib.RDF.type, mesh.DocPage):
        src = g.value(page, mesh.source)
        sha = g.value(page, mesh.body_sha)
        assert src is not None, f"{page} has no mesh:source — the route has nowhere to read from"
        assert sha is not None, f"{page} has no mesh:body_sha — the route cannot verify what it read"
        rows[str(src)] = str(sha)
    assert rows, "no page carries a locator; this test is asserting nothing"

    for path in gen.pages():
        # THROUGH THE GENERATOR'S OWN NORMALISATION. Hashing raw working-tree bytes here
        # made this seal agree with a Windows-generated TTL and disagree with every Linux
        # consumer — the instrument sharing the producer's platform bug and so confirming
        # it. The sha must be a property of the CONTENT, not of the checkout.
        on_disk = hashlib.sha256(gen.page_bytes(path)).hexdigest()
        computed_sha, key = gen.page_locator(path)
        assert computed_sha == on_disk, "the generator's sha is not the sha of the file it read"
        assert key in rows, (
            f"{path.name} hashes to a key the corpus does not name ({key}) — the TTL is stale "
            f"against this file and the body would be uploaded where no row points")
        assert rows[key] == on_disk, (
            f"{path.name}: the row's body_sha does not match the file")
        assert on_disk in key, (
            "the key is not content-addressed on the sha it carries, so a stale object is "
            "reachable rather than orphaned")


def test_the_uploader_refuses_to_upload_past_drift():
    """BREAK ON PURPOSE, and it must fail BEFORE touching the network.

    Uploading a body while the committed rows point elsewhere is the worst available outcome: the
    prime reports success, every seal stays green, and the page resolves to nothing the first time
    a reader asks. Restored by bytes.
    """
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from setup.prime_databases import upload_doc_pages

    original = TTL.read_bytes()
    try:
        TTL.write_bytes(original + b"\n# drift\n")
        with pytest.raises(RuntimeError) as caught:
            upload_doc_pages()
        assert "drift" in str(caught.value).lower(), (
            f"the refusal does not name drift: {caught.value}")
    finally:
        TTL.write_bytes(original)
    assert TTL.read_bytes() == original, "the tree was left mutated by a test"


def test_the_vocabulary_declares_the_pointer_terms():
    """A row asserting mesh:source against a term that was never declared is the fail-by-passing
    case: ingest accepts it, and nothing ever matches."""
    import rdflib
    g = rdflib.Graph()
    g.parse(ROOT / "setup" / "ontologies" / "mesh_system.ttl", format="turtle")
    mesh = rdflib.Namespace("http://invincible-agent/mesh#")
    for term in ("source", "body_sha", "source_committed_at"):
        assert (mesh[term], None, None) in g, f"mesh:{term} is not declared in mesh_system.ttl"


def test_page_bodies_do_not_share_the_ontology_bucket():
    """RULED: a refusal is not a router.

    Page bodies once lived in the ontology bucket and were kept out of the TTL parser by the
    ontology sensor DECLINING an undeclared domain. That held only while that guard had no
    default; the day it gained one, a runbook would have become a parse error inside the prime,
    surfacing as an ontology error about a file that is not an ontology.

    The separation is asserted rather than assumed because a deployment that points both names at
    one bucket rebuilds the coupling silently — nothing else would notice.
    """
    import os
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from setup.prime_databases import upload_doc_pages

    before = {k: os.environ.get(k) for k in ("DOCS_BUCKET", "ONTOLOGY_BUCKET")}
    try:
        os.environ["DOCS_BUCKET"] = "same-bucket"
        os.environ["ONTOLOGY_BUCKET"] = "same-bucket"
        with pytest.raises(RuntimeError) as caught:
            upload_doc_pages()
        msg = str(caught.value)
        assert "DOCS_BUCKET" in msg and "ONTOLOGY_BUCKET" in msg, (
            f"the refusal does not name both settings, so a reader cannot act on it: {msg}")

        # THE OTHER DIRECTION, which is the half that would rot silently: distinct buckets must
        # get PAST this guard. A refusal that fires always is indistinguishable from one that
        # works, and it would block every prime rather than the misconfigured ones.
        #
        # Proven WITHOUT a network by making the very next step fail with a marker: reaching the
        # S3 client at all means the separation guard let us through. Calling for real took 54s
        # of connect timeouts in an environment with no MinIO, which is a slow test that proves
        # the same thing less clearly.
        import setup.prime_databases as pdb

        class _Marker(Exception):
            pass

        class _StubBoto3:
            @staticmethod
            def client(*a, **k):
                raise _Marker("reached the S3 client")

        real_boto3 = pdb.boto3
        try:
            pdb.boto3 = _StubBoto3
            os.environ["DOCS_BUCKET"] = "doc-pages"
            os.environ["ONTOLOGY_BUCKET"] = "ontologies"
            with pytest.raises(_Marker):
                upload_doc_pages()
        finally:
            pdb.boto3 = real_boto3
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_THE_SHA_IS_A_PROPERTY_OF_THE_CONTENT_not_of_the_checkout():
    """A page's sha must not depend on which platform ran the generator.

    ⛔ IT DID, AND IT COST A FLEET ROLL. `git` stores LF and checks out CRLF on Windows, and the
    generator hashed working-tree bytes — so on `rolling-a-service.md`:

        working tree (CRLF)    899eb4469f5b   <- what a Windows regeneration wrote
        git blob / Linux image 1b6db61a4e32   <- what every consumer computes

    The prime refused the whole upload, CORRECTLY: the key would have named a body nothing could
    resolve, and every doc answer would resolve to nothing at answer time. I regenerated on
    Windows, committed, rolled — and it refused again with a DIFFERENT wrong sha. **The second
    failure was indistinguishable from the first**, which is what makes this worth sealing rather
    than remembering.

    THE OLD SEAL COULD NOT SEE IT because it recomputed with `path.read_bytes()` — the producer's
    own platform bug, in the instrument. It agreed with the Windows TTL and disagreed with the
    cluster, which is the instrument and the subject sharing a defect rather than a surface.

    This asserts against `git cat-file`, which is the one reading of a file that is the same on
    every machine.
    """
    import hashlib
    import importlib.util
    import subprocess

    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("gen_docs_corpus", GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    checked = 0
    for path in gen.pages():
        blob = subprocess.run(
            ["git", "cat-file", "-p", f"HEAD:docs/runbooks/{path.name}"],
            cwd=str(ROOT), capture_output=True, timeout=60,
        )
        if blob.returncode != 0:
            continue                      # not committed yet; the drift seals above own that
        want = hashlib.sha256(blob.stdout).hexdigest()
        got, _key = gen.page_locator(path)
        assert got == want, (
            f"{path.name}: the generator hashes to {got[:12]} but the COMMITTED content hashes "
            f"to {want[:12]}. The sha is a property of this checkout rather than of the content "
            f"— almost always CRLF in the working tree. `gen.page_bytes` must normalise line "
            f"endings, and the upload must use the same bytes."
        )
        checked += 1
    assert checked >= 5, (
        f"only {checked} page(s) could be compared against git — this seal is quantifying over "
        f"almost nothing and would pass on a tree where every page had drifted"
    )


# ── THE ORDERING RULE'S SECOND INPUT ──────────────────────────────────────────────────────────

def test_every_page_carries_a_commit_time_DERIVED_FROM_GIT():
    """Derived from the act, not typed — so the check recomputes it rather than trusting it.

    A stamp a human could set is a stamp that can claim a date the history does not support, and
    this one ORDERS THE CORPUS: a wrong value does not fail, it silently promotes a page.
    """
    import subprocess

    import rdflib
    g = rdflib.Graph()
    g.parse(TTL, format="turtle")
    mesh = rdflib.Namespace("http://invincible-agent/mesh#")

    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_docs_corpus", GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    stamped = {}
    for page in g.subjects(rdflib.RDF.type, mesh.DocPage):
        v = g.value(page, mesh.source_committed_at)
        assert v is not None, f"{page} has no mesh:source_committed_at — the ordering rule's key"
        stamped[str(page).rsplit("#", 1)[-1]] = str(v)
    assert stamped, "no page carries a commit time; this test asserts nothing"

    for path in gen.pages():
        want = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        key = f"runbook-{path.stem}"
        assert stamped.get(key) == want, (
            f"{path.name}: the corpus says {stamped.get(key)!r} and git says {want!r}. The stamp "
            f"is derived from the commit, so a disagreement means the corpus was not regenerated "
            f"after the page changed — and this field ORDERS the answer.")


def test_the_commit_times_actually_DISCRIMINATE():
    """THE CONTROL THAT KEEPS THIS KEY FROM BEING DECORATIVE.

    A time field identical on every page passes every other assertion here and orders nothing —
    which is exactly the state the corpus was in before this field existed, since one prime lands
    the whole corpus and every page shares an ingest time to the second. The key earns its place
    only if it separates pages.
    """
    import rdflib
    g = rdflib.Graph()
    g.parse(TTL, format="turtle")
    mesh = rdflib.Namespace("http://invincible-agent/mesh#")
    times = [str(v) for v in g.objects(None, mesh.source_committed_at)]
    assert len(times) >= 5, f"only {len(times)} stamps — too few to say anything about ordering"
    assert len(set(times)) > 1, (
        "every page carries the SAME commit time, so this key orders nothing and the ordering "
        "rule is back to stable-identity. That is the pre-existing state, not a passing test")
    # Not asserting all-distinct: two pages committed together is legitimate and is precisely the
    # tie the rule hands to the engine to render as a list.


def test_the_generator_REFUSES_a_page_git_does_not_know():
    """A fabricated timestamp would order the corpus confidently and wrongly.

    The tempting fallbacks are both worse than stopping: a file's mtime is a property of whoever
    last checked out the tree, and `now` is invented. Asserted at the function rather than by
    creating an untracked page, so the test leaves no file behind.
    """
    import importlib.util
    import pathlib as _p
    spec = importlib.util.spec_from_file_location("gen_docs_corpus", GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    with pytest.raises(SystemExit) as caught:
        gen.source_committed_at(_p.Path("docs/runbooks/a-page-that-was-never-committed.md"))
    msg = str(caught.value)
    assert "REFUSED" in msg and "invent" in msg, (
        f"the refusal does not say what it refused to do: {msg}")
