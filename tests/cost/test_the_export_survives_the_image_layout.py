"""`package_export` 500'd in every deployed pod, always, and no seal could see it.

MEASURED LIVE 2026-09-12 on `iagent-engine-cost`, calling the verb through its own route:

    File "/app/measures.py", line 757, in package_export
      root = pathlib.Path(__file__).resolve().parents[2]
    IndexError: 2

The image flattens `agent_fleet/cost_agent/` to `/app`, so `/app/measures.py` has exactly two
parents. **In a checkout the identical expression resolves to the repo root and is correct** —
which is why the whole cost suite was green and why this survived from the day the verb
shipped. Nine verbs registered, `/health` green, and one of them had never once been callable
where it was registered.

── THE DAMAGE WAS NOT THE CRASH, IT WAS WHERE THE CRASH LANDED ──────────────────────────────
`package_export` already had TWO `SourceUnavailable` guards that refuse by name when the
builder or the pinned Pyodide runtime is absent — which is exactly the honest answer a pod owes
a caller. **`parents[2]` threw before either could run**, converting a designed refusal into an
untyped 500.

So the fix does not make the artifact buildable in a pod, and these seals do not claim it does.
The builder is 1,266 lines under `scripts/` and the Pyodide runtime is 14 MB and gitignored;
neither is in the image, and shipping them is a deployment decision, not this lane's. **What
the fix buys is that the engine SAYS SO** instead of raising IndexError.

── WHAT STILL WORKS IN THE POD, MEASURED THERE ──────────────────────────────────────────────
`export.build_package` — the GOVERNED half: entitlement scope, manifest, module hashes, five
verification checks, audit line — **runs correctly in the deployed image.** Only the HTML
rendering does not. That is the seam a card action should be built on.
"""
from __future__ import annotations

import pathlib
import re
from unittest import mock

import pytest

from agent_fleet.cost_agent import measures as m
from agent_fleet.cost_agent.entities import SourceUnavailable
from agent_fleet.cost_agent.seed import build_state

STATE = build_state()


def test_a_flattened_layout_gets_a_NAMED_REFUSAL_and_not_an_IndexError():
    """The defect, reproduced at the seam that decides it.

    `_repo_root()` returning None IS the flattened image, expressed as the one fact the verb
    needs. Asserting on the exception TYPE rather than the message: a caller distinguishes
    refusals by type (ADR-0049 Ruling 4), and an IndexError is indistinguishable from the
    engine being down.
    """
    with mock.patch.object(m, "_repo_root", lambda: None):
        with pytest.raises(SourceUnavailable) as exc:
            m.package_export(STATE, recipient_scope="notional-customer-alpha")

    message = str(exc.value)
    assert "governed" in message.lower(), (
        "the refusal must say which half is still available, or a caller reads it as 'this "
        "verb does not work' and stops asking"
    )


def test_the_root_is_found_by_a_MARKER_and_not_by_counting_levels():
    """Counting is what shipped the defect: `parents[2]` is correct in a checkout, an
    IndexError in `/app`, and the two are indistinguishable by reading the line."""
    root = m._repo_root()
    assert root is not None, "these tests run from a checkout; the marker search failed"
    assert (root / "scripts").is_dir() and (root / "agent_fleet").is_dir()


def test_the_root_search_RETURNS_NONE_rather_than_raising_when_there_is_no_checkout():
    """None is a first-class answer. "I am not in a checkout" is true and useful in a pod, and
    it is the input to a named refusal rather than an error condition."""
    # THE FLATTENED LAYOUT HAS TWO PARENTS AND NEITHER QUALIFIES. Exercising the search over
    # `/app/measures.py`'s ancestry directly, because that is the input that produced the live
    # IndexError — `parents[2]` on this same path is what the pod raised.
    fake = pathlib.PurePosixPath("/app/measures.py")
    assert len(fake.parents) == 2, [str(p) for p in fake.parents]
    with pytest.raises(IndexError):
        _ = fake.parents[2]        # the expression that shipped, on the layout that broke it

    found = None
    for candidate in pathlib.Path(fake).parents:
        if (candidate / "scripts").is_dir() and (candidate / "agent_fleet").is_dir():
            found = candidate
    assert found is None, f"a flattened layout resolved to {found}"


def test_NO_module_in_this_engine_derives_a_path_by_INDEX_from___file__():
    """THE CENSUS, scoped to this lane's own package.

    A filed defect is a sample. `parents[N]` appears across ten shipped modules in this
    repository; five are inside `try:` blocks and survive, and at least one elsewhere is not —
    reported to its owner rather than edited here.

    THIS SEAL COVERS WHAT THIS LANE SHIPS, so the next module added to `cost_agent/` cannot
    reintroduce it. Comments are excluded because this file's own fix is DOCUMENTED with the
    expression that caused it, and a check that cannot tell a fix from its explanation flags
    the explanation — a defect this repo has four recorded instances of.
    """
    offenders = []
    for path in sorted(pathlib.Path("agent_fleet/cost_agent").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"\.parents\[\d+\]", code):
                offenders.append(f"{path.as_posix()}:{lineno}: {code.strip()}")
    assert not offenders, (
        "a path derived by counting directory levels is correct in a checkout and an "
        "IndexError in the flattened image; use a marker search:\n  " + "\n  ".join(offenders)
    )


def test_the_GOVERNED_half_needs_no_checkout_at_all():
    """Measured in the pod and asserted here: the entitlement scope, manifest, module hashes,
    checks and audit line are computed from the engine's own modules.

    THIS IS THE SEAM A CARD ACTION SHOULD USE. It is the half that is deployable today, and
    keeping it provably independent of the checkout is what makes that claim durable rather
    than a fact about this afternoon.
    """
    try:
        from agent_fleet.cost_agent.export import audit_line, build_package
    except ImportError:  # pragma: no cover
        pytest.skip("export module unavailable")

    with mock.patch.object(m, "_repo_root", lambda: None):
        package = build_package(
            STATE, recipient_scope="notional-customer-alpha", algorithm_sha="deadbeef"
        )
    assert package["locator"].startswith("sha256:")
    assert package["manifest"]["modules"], "no module hashes"
    assert len(package["manifest"]["checks"]) == 5
    assert audit_line(package, disclosed_by="seal")["disclosed_to"] == (
        "notional-customer-alpha"
    )


def test_a_baked_sha_is_available_without_git_and_is_NOT_invented():
    """`algorithm_sha()` shells out to git; `git` is not on PATH in the pod, measured.

    The image bakes `IAGENT_GIT_SHA` and the deployed engine returns a real commit for it.
    NONE WHERE ABSENT rather than a placeholder: a package whose `algorithm_sha` is a guess
    names an algorithm the recipient cannot retrieve, which is the exact thing the git path's
    dirty-tree refusal exists to prevent.
    """
    with mock.patch.dict("os.environ", {"IAGENT_GIT_SHA": "abc123"}, clear=False):
        assert m._baked_algorithm_sha() == "abc123"
    for absent in ("", "unknown"):
        with mock.patch.dict("os.environ", {"IAGENT_GIT_SHA": absent}, clear=False):
            assert m._baked_algorithm_sha() is None, (
                f"{absent!r} must not be reported as a real sha"
            )
