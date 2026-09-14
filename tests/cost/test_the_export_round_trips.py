"""The export round-trips: the manifest's hash is taken from the artifact AS WRITTEN.

Dispatched as *"the round-trip is the seal, not the build"* — **a generated export whose
manifest is never re-read is the shape where a truncated write reports success.**

── WHAT THERE WAS BEFORE: NO HASH OF THE ARTIFACT AT ALL ────────────────────────────────────
`locator` is `content_hash(body)` — a hash of the package BODY DICT, computed from state. The
HTML was written separately with `write_text` and **never hashed**. So every figure in the
response described what the engine INTENDED to write. A truncated write, a short flush or a
full disk each reports success, and nothing anywhere notices.

**Hashing the produced string in memory would not have been a round trip.** It re-states the
intent in a second place and agrees with itself for exactly the reason that makes it
worthless. The bytes have to come back off the disk, which is the only step that can disagree.

── AND IT CAUGHT A REAL DEFECT ON ITS FIRST RUN ─────────────────────────────────────────────
`dest.write_text(html, encoding="utf-8")` opens in TEXT MODE, which translates "\\n" to the
platform line ending. On Windows the file on disk was **never** the bytes that were produced —
measured directly, 12 produced bytes became 14 on disk with a different sha256.

**That is a reproducibility defect in a governed emit, not a cosmetic one.** ADR-0047's premise
is that a recipient verifies the artifact against the manifest describing it, and a hash over
the produced string would not match the file they downloaded. The artifact was also
PLATFORM-DEPENDENT: same commit, same seed, same algorithm, different bytes and a different
hash on Linux and Windows — so "byte-identical export" was false across the one axis it had to
hold on. Fixed with `write_bytes`.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from agent_fleet.cost_agent import measures as m
from agent_fleet.cost_agent.main import app
from agent_fleet.cost_agent.seed import RECIPIENT_SCOPES, build_state

STATE = build_state()
SCOPE = "notional-customer-alpha"


@pytest.fixture(scope="module")
def exported():
    if m._repo_root() is None:  # pragma: no cover - not reachable from a checkout
        pytest.skip("no checkout; the artifact half cannot be produced here")
    return m.package_export(STATE, recipient_scope=SCOPE)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_the_manifest_hash_is_of_the_FILE_ON_DISK(exported):
    """THE ROUND TRIP. Re-read independently of the verb and compare.

    This re-opens the artifact here rather than trusting the response's own figure, because a
    seal that asks the producer to confirm its own claim is the producer agreeing with itself
    — the same defect as hashing the string in memory, one layer out.
    """
    root = m._repo_root()
    path = root / "dist" / exported["artifact_filename"]
    on_disk = path.read_bytes()

    assert exported["artifact_sha256"] == "sha256:" + hashlib.sha256(on_disk).hexdigest(), (
        "the manifest's artifact hash does not describe the file that was written"
    )
    assert exported["artifact_bytes"] == len(on_disk)


def test_the_artifact_is_written_in_BINARY_so_it_is_not_platform_dependent(exported):
    """No line-ending translation, on any platform.

    A carriage return in the file means it was written in text mode, which makes the bytes —
    and therefore the hash a recipient verifies against — a property of the machine that built
    it rather than of the algorithm that produced it.
    """
    root = m._repo_root()
    on_disk = (root / "dist" / exported["artifact_filename"]).read_bytes()
    assert b"\r\n" not in on_disk, (
        "the artifact contains CRLF; it was written in text mode and its hash is now a "
        "property of the build machine rather than of the algorithm"
    )


def test_a_TRUNCATED_write_is_REFUSED_and_not_reported_as_success(monkeypatch):
    """The failure the round-trip exists for, forced.

    Truncating the write must produce a REFUSAL, not a package. A manifest describing bytes
    that are not on the disk is a false record, and shipping it is worse than shipping nothing
    because the hash it carries will verify against the wrong file.

    ⚠ RUN AGAINST A DIFFERENT RECIPIENT, and that is not tidiness. Written against `SCOPE` it
    left a TRUNCATED FILE ON DISK, and the end-to-end test below then served those bytes and
    failed — a test that damaged the artifact its neighbour was measuring. The artifact is
    shared mutable state between these tests, so the destructive one gets its own subject.
    """
    if m._repo_root() is None:  # pragma: no cover
        pytest.skip("no checkout")
    other = next(s for s in RECIPIENT_SCOPES if s != SCOPE)

    real_write = m.pathlib.Path.write_bytes

    def short_write(self, data):  # truncate every write by one byte
        return real_write(self, data[:-1])

    monkeypatch.setattr(m.pathlib.Path, "write_bytes", short_write)
    with pytest.raises(m.SourceUnavailable) as exc:
        m.package_export(STATE, recipient_scope=other)
    assert "NOT been emitted" in str(exc.value)

    # AND THE DAMAGED FILE IS NOT LEFT BEHIND for whatever runs next, in this suite or from a
    # later developer's `ls dist/`. A truncated artifact on disk with no manifest beside it is
    # exactly the artefact this whole seal exists to make impossible.
    monkeypatch.undo()
    damaged = m._repo_root() / "dist" / f"cost-validation-{other}.html"
    if damaged.exists():
        damaged.unlink()


def test_the_response_carries_a_FETCHABLE_uri_and_not_a_filesystem_path(exported):
    """A card cannot open a path, and a path leaks the deployment's layout to a recipient who
    has no use for it."""
    uri = exported["artifact_uri"]
    assert uri.startswith("http://") or uri.startswith("https://"), uri
    assert uri.endswith("/artifact/" + exported["artifact_filename"])


def test_the_uri_actually_serves_the_artifact_that_was_hashed(exported, client):
    """END TO END: follow the URI the verb published and hash what comes back.

    THIS IS THE CHECK THAT DISTINGUISHES "wrote a file" FROM "wrote the file it says it
    wrote", and it is the only one that exercises the producer and the download path
    together — each is correct on its own today, and nothing before this asserted they agree.
    """
    response = client.get("/artifact/" + exported["artifact_filename"])
    assert response.status_code == 200, response.text
    served = "sha256:" + hashlib.sha256(response.content).hexdigest()
    assert served == exported["artifact_sha256"], (
        "the bytes served over the published URI are not the bytes the manifest describes"
    )


@pytest.mark.parametrize("name", [
    "../../etc/passwd", "..%2f..%2fsecrets", "cost-validation-nope.html",
    "pricing.py", "", "cost-validation-.html",
])
def test_the_route_serves_ONLY_names_this_engine_can_produce(client, name):
    """Traversal is refused STRUCTURALLY, not by sanitizing.

    A route that cleans a filename is one missed encoding away from serving something else; a
    route that will only serve names it computed itself cannot be talked into anything,
    because the input is compared against a closed set rather than transformed into a path.
    """
    assert client.get("/artifact/" + name).status_code == 404


def test_a_file_that_EXISTS_but_is_not_producible_is_STILL_refused(client):
    """⚠ THE SEAL ABOVE WAS VACUOUS AND A MUTATION PROVED IT.

    Deleting the allow-list entirely left all thirteen tests green: `../../etc/passwd` never
    matches the route's path pattern at all, and the other names 404 simply because no such
    file is in `dist/`. **Every one of them passed for a reason unrelated to the guard.**

    So this plants a REAL FILE in the served directory under a name this engine cannot
    produce. Without the allow-list it is served; with it, refused. That is the only
    arrangement in this file that can tell the two apart — and it is the difference between
    testing the guard and testing the filesystem's current contents.
    """
    root = m._repo_root()
    if root is None:  # pragma: no cover
        pytest.skip("no checkout")
    planted = root / "dist" / "not-a-package.html"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_bytes(b"<html>secrets</html>")
    try:
        response = client.get("/artifact/not-a-package.html")
        assert response.status_code == 404, (
            "a file present in the served directory was returned even though this engine "
            "cannot produce that name — the allow-list is not doing anything"
        )
        assert b"secrets" not in response.content
    finally:
        planted.unlink()


def test_the_producible_set_is_DERIVED_from_the_recipient_scopes():
    """Listed names would be a second registry, and a tenth recipient would be unservable
    until somebody remembered this file."""
    from agent_fleet.cost_agent.main import _producible_artifact_names

    names = _producible_artifact_names()
    assert names, "empty producible set; every artifact request would 404"
    for scope in RECIPIENT_SCOPES:
        assert f"cost-validation-{scope}.html" in names
    assert len(names) == 2 * len(RECIPIENT_SCOPES), sorted(names)


def test_a_deployment_with_no_checkout_404s_rather_than_erroring(client, monkeypatch):
    """Every pod today. The builder and the pinned runtime are not in the image, so nothing is
    ever written there — a 404 is the honest answer and the one a card should render as "not
    available from this deployment" rather than as a broken link."""
    monkeypatch.setattr(m, "_repo_root", lambda: None)
    response = client.get(f"/artifact/cost-validation-{SCOPE}.html")
    assert response.status_code == 404
    assert "image" in response.json()["detail"]
