"""ADR-0048 §5's five acceptance seals for the customer-validation package.

WHAT THESE CAN AND CANNOT PROVE, stated first because the boundary is the honest part:

  * The manifest, entitlement filtering, the pinned SHA and the audit line are all checked
    HERE, against the real packaging path -- not a fixture. §5's own rule: a fixture a
    developer built is a test of the fixture.
  * The no-CDN property is checked STRUCTURALLY (the artifact contains no external URL and
    embeds every runtime file it asks for). That is necessary and NOT sufficient: only
    opening the file with networking disabled proves it renders, and that step needs a human
    with a browser. ADR-0048 §3 item 4 already assigns that an owner; it is not automated
    away here, and calling this seal "the no-CDN seal" without that sentence would overclaim.
  * WASM numeric fidelity is likewise not provable from Python. It is answered by the
    artifact itself: if `decimal` diverges in the browser, the manifest check fails and the
    package refuses to render. Seal and measurement are the same observation by design.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

from agent_fleet.cost_agent import export as X
from agent_fleet.cost_agent.entities import Unentitled
from agent_fleet.cost_agent.seed import RECIPIENT_SCOPES, build_state

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHA = "0" * 40  # a stand-in; the real one comes from git at build time


@pytest.fixture(scope="module")
def state():
    return build_state()


# ── SEAL 1 — the manifest bites ─────────────────────────────────────────────
def test_a_clean_package_verifies(state):
    pkg = X.build_package(state, recipient_scope="notional-customer-alpha",
                          algorithm_sha=SHA)
    assert X.verify_manifest(pkg["manifest"]) == []


def test_the_manifest_BITES_on_a_corrupted_INTERMEDIATE(state):
    """The demo beat: corrupt one intermediate, watch it refuse.

    An intermediate rather than an output on purpose — an output-only manifest would tell a
    recipient THAT something diverged; catching an intermediate is what makes the divergence
    a bounded diagnosis instead of an argument.
    """
    pkg = X.build_package(state, recipient_scope="notional-customer-alpha",
                          algorithm_sha=SHA)
    pkg["manifest"]["checks"][2]["intermediates"][1]["amount"] = "999999.99"
    problems = X.verify_manifest(pkg["manifest"])
    assert problems, "a corrupted intermediate must be caught"
    assert any("step" in p for p in problems)


def test_the_manifest_BITES_on_a_corrupted_EXPECTED_PRICE(state):
    pkg = X.build_package(state, recipient_scope="notional-customer-alpha",
                          algorithm_sha=SHA)
    pkg["manifest"]["checks"][0]["expected"]["price"] = "1.00"
    assert any("price" in p for p in X.verify_manifest(pkg["manifest"]))


def test_a_REORDERED_composition_is_REFUSED_before_any_arithmetic(state):
    """The order IS the algorithm — and the system refuses harder than this test first asked.

    Written expecting a reordered spec to VERIFY AND DIVERGE. It does not: swapping Fringe and
    Overhead makes Overhead's basis name a step that has not run, and `validate_composition`
    raises before a single figure is computed. That is the stronger guarantee, so the seal
    asserts the stronger thing.

    The difference matters to a recipient: divergence says "these numbers disagree", refusal
    says "this is not a composition I can perform" — and only the second is true of a spec
    whose steps are impossible in the stated order.
    """
    from agent_fleet.cost_agent.pricing import CompositionError

    pkg = X.build_package(state, recipient_scope="notional-customer-alpha",
                          algorithm_sha=SHA)
    comp = pkg["manifest"]["composition"]
    comp[0], comp[1] = comp[1], comp[0]
    with pytest.raises(CompositionError, match="has not run yet"):
        X.verify_manifest(pkg["manifest"])


# ── SEAL 2 — entitlement discriminates, three recipients ────────────────────
def test_two_recipients_get_DIFFERENT_embedded_data(state):
    a = X.build_package(state, recipient_scope="notional-customer-alpha", algorithm_sha=SHA)
    b = X.build_package(state, recipient_scope="notional-customer-beta", algorithm_sha=SHA)
    assert a["lots"] != b["lots"]
    assert a["locator"] != b["locator"]
    # And they differ in the DIRECTION the scopes predict, not merely somewhere.
    assert set(a["lots"]) == set(RECIPIENT_SCOPES["notional-customer-alpha"])
    assert set(b["lots"]) == set(RECIPIENT_SCOPES["notional-customer-beta"])


def test_the_scopes_OVERLAP_so_the_discrimination_is_not_accidental(state):
    """Disjoint scopes can pass while keying on the wrong field entirely."""
    a = set(RECIPIENT_SCOPES["notional-customer-alpha"])
    b = set(RECIPIENT_SCOPES["notional-customer-beta"])
    assert a & b, "the two scopes must share a lot"
    assert a - b and b - a, "and must each hold one the other does not"


def test_an_unentitled_scope_REFUSES_rather_than_emitting_an_empty_package(state):
    """An empty package and an out-of-scope one must not look alike (ADR-0047 §5)."""
    with pytest.raises(Unentitled):
        X.build_package(state, recipient_scope="acme-corp", algorithm_sha=SHA)


def test_a_package_embeds_NOTHING_outside_its_scope(state):
    """The disclosure decision is the embedded set, so assert on the set itself."""
    a = X.build_package(state, recipient_scope="notional-customer-alpha", algorithm_sha=SHA)
    embedded_lots = {c["lot"] for c in a["manifest"]["checks"]}
    assert embedded_lots == set(RECIPIENT_SCOPES["notional-customer-alpha"])
    assert 9 not in embedded_lots, "a lot outside the scope reached the package"


# ── SEAL 4 — the pinned SHA matches the embedded modules ────────────────────
def test_the_builder_REFUSES_a_dirty_pricing_module(monkeypatch):
    """A package claiming a SHA whose working copy has edits names an unretrievable algorithm."""
    import scripts.build_cost_package as B

    monkeypatch.setattr(
        B.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": " M agent_fleet/cost_agent/pricing.py"})(),
    )
    with pytest.raises(SystemExit, match="uncommitted"):
        B.algorithm_sha()


# ── SEAL 5 — the audit line is complete ─────────────────────────────────────
def test_the_audit_line_answers_what_to_whom_when_and_by_which_version(state):
    pkg = X.build_package(state, recipient_scope="notional-customer-beta", algorithm_sha=SHA)
    line = X.audit_line(pkg, disclosed_by="alice@example.com")
    for field in ("disclosed_to", "disclosed_by", "at", "algorithm_sha", "locator",
                  "lots_disclosed"):
        assert line.get(field), f"audit line is missing {field}"
    assert line["lot_count"] == len(pkg["lots"])


def test_the_locator_is_a_content_hash_that_changes_with_content(state):
    a = X.build_package(state, recipient_scope="notional-customer-alpha", algorithm_sha=SHA)
    b = X.build_package(state, recipient_scope="notional-customer-alpha", algorithm_sha="beef")
    assert a["locator"].startswith("sha256:")
    assert a["locator"] != b["locator"], "a different algorithm SHA must change the locator"


# ── SEAL 3 — no CDN (STRUCTURAL half; the render half needs a human) ────────
DIST = ROOT / "dist" / "cost-validation-notional-customer-alpha.html"


@pytest.mark.skipif(not DIST.exists(), reason="build the package first")
def test_the_built_artifact_contains_NO_external_url():
    html = DIST.read_text(encoding="utf-8")
    urls = {u for u in re.findall(r"https?://[^\s\"'<>`)]+", html)
            if not u.startswith("http://www.w3.org")}
    assert not urls, f"the artifact would reach out to: {sorted(urls)}"


@pytest.mark.skipif(not DIST.exists(), reason="build the package first")
def test_the_artifact_embeds_every_runtime_file_it_asks_for():
    """Structural no-CDN: the shim can only answer from what is actually embedded."""
    import scripts.build_cost_package as B

    html = DIST.read_text(encoding="utf-8")
    blob = re.search(r'id="embedded-runtime" type="application/json">(.*?)</script>',
                     html, re.S).group(1)
    embedded = json.loads(blob)
    for f in B.RUNTIME_FILES:
        assert f in embedded and len(embedded[f]) > 1000, f"{f} is not embedded"


@pytest.mark.skipif(not DIST.exists(), reason="build the package first")
def test_the_embedded_pricing_source_is_BYTE_IDENTICAL_to_the_pinned_file():
    """§3's whole claim. If this drifts, 'same algorithm' is false and the manifest is theatre."""
    html = DIST.read_text(encoding="utf-8")
    src = json.loads(re.search(r'id="pricing-src" type="application/json">(.*?)</script>',
                               html, re.S).group(1))
    assert src == (ROOT / "agent_fleet" / "cost_agent" / "pricing.py").read_text(
        encoding="utf-8")


@pytest.mark.skipif(not DIST.exists(), reason="build the package first")
def test_the_artifact_contains_NO_UNRESOLVED_DYNAMIC_IMPORT():
    """The seal that was missing when the first build shipped un-openable.

    THE DEFECT THIS EXISTS FOR: a `fetch` shim cannot intercept `import()`. The browser's
    module loader does not route through window.fetch, so the first artifact embedded every
    runtime file, passed the no-external-URL check AND the every-file-embedded check, and
    then died at open with "error loading dynamically imported module: .../pyodide.asm.js".

    Both structural seals were correct and neither could see it. What they measured was
    "nothing points outward"; what was false was "everything points somewhere it can reach".
    Those are different claims, and only opening the file told them apart — which is why this
    check now asserts the mechanism (every dynamic import resolves through the embedded
    resolver) rather than the symptom.
    """
    html = DIST.read_text(encoding="utf-8")
    bare = re.findall(r"await import\(/\* webpackIgnore \*/e\)", html)
    assert not bare, (
        f"{len(bare)} dynamic import(s) still take the loader's raw argument. A fetch shim "
        "cannot intercept import(); these must route through __embeddedModuleURL or the "
        "artifact cannot open offline."
    )
    assert "__embeddedModuleURL" in html, "the embedded-module resolver is absent"
    assert "createObjectURL" in html, "nothing publishes embedded JS as a blob URL"
