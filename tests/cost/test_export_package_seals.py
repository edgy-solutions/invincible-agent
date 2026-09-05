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
from decimal import Decimal

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


@pytest.mark.skipif(not DIST.exists(), reason="build the package first")
def test_the_shim_declares_a_MIME_TYPE_for_every_embedded_file():
    """Third layer of the same onion, and the third only visible by opening the file.

    WebAssembly's streaming instantiation REFUSES a response whose Content-Type is not
    `application/wasm` — "Response has unsupported MIME type '' expected 'application/wasm'".
    So a shim returning the correct BYTES with no type yields a package that loads its
    loader, fetches its wasm, and then cannot instantiate it.

    THE PATTERN WORTH RECORDING: embed the files (layer 1) → route the module import
    (layer 2) → declare the MIME types (layer 3). Every layer passed the previous layer's
    seal. Each was found by a human opening the artifact, and none was visible to any check
    that reads the file as text. That is the honest cost of a structural-only seal, and it is
    why ADR-0048 §3 item 4 gives the open-it step a human owner rather than a CI job.
    """
    import scripts.build_cost_package as B

    html = DIST.read_text(encoding="utf-8")
    assert "'application/wasm'" in html, "the wasm has no declared MIME type; it cannot instantiate"
    # Every embedded file needs a type, not just the one that failed loudest.
    for f in B.RUNTIME_FILES:
        assert f"'{f}':" in html, f"{f} has no MIME entry in the shim's table"


# ═══════════════════════════════════════════════════════════════════════════
# SLICE 2 SEALS — the three the dispatch added, plus what they needed to bite
# ═══════════════════════════════════════════════════════════════════════════
import json as _json

from agent_fleet.cost_agent import page as PAGE


@pytest.fixture(scope="module")
def slice2(state):
    import scripts.build_cost_dataset as D

    db = ROOT / "dist" / "cost-notional-customer-alpha.duckdb"
    if not db.exists():
        pytest.skip("build the slice-2 dataset first")
    pkg = X.build_dataset_package(
        state, recipient_scope="notional-customer-alpha", algorithm_sha=SHA,
        duckdb_path=str(db), duckdb_hash=D.file_hash(db))
    PAGE.verify(_json.dumps(pkg))
    return pkg, db


# ── SEAL 6 — a lot change re-renders EVERY metric ───────────────────────────
def test_every_labor_metric_differs_between_lots(slice2):
    """THE MUTATION THIS GUARDS: freeze the selector and the page keeps lot 1 on screen.

    A stale chart is invisible — it renders, it is well-formed, and it is simply the wrong
    lot. So the seal asserts that each metric ACTUALLY MOVES between lots: if any were
    constant across the package, a frozen selector would be undetectable in that metric and
    the guard would be measuring nothing.
    """
    pkg, _ = slice2
    lots = pkg["lots"]
    views = {n: PAGE.labor_view(n) for n in lots}
    for metric in ("total_hours", "total_cost", "touch_per_unit", "unit_price"):
        values = {views[n][metric] for n in lots}
        assert len(values) == len(lots), (
            f"{metric} repeats across lots {sorted(values)} — a frozen lot selector would be "
            "undetectable in this metric"
        )


def test_the_chart_parts_change_between_lots(slice2):
    pkg, _ = slice2
    a = PAGE.labor_view(pkg["lots"][0])["parts"]
    b = PAGE.labor_view(pkg["lots"][-1])["parts"]
    assert [p["key"] for p in a] == [p["key"] for p in b], "kinds must keep their render order"
    assert [p["display"] for p in a] != [p["display"] for p in b], "the bar would be stale"


def test_labor_view_holds_no_state_between_calls(slice2):
    """A view that cached its first lot would pass the difference test and still be stale."""
    pkg, _ = slice2
    first = PAGE.labor_view(pkg["lots"][0])
    PAGE.labor_view(pkg["lots"][-1])
    again = PAGE.labor_view(pkg["lots"][0])
    assert first == again, "labor_view is not a pure function of its lot argument"


# ── SEAL 7 — an edited rate moves the SCENARIO and not the BASELINE ─────────
def test_an_edited_rate_changes_the_scenario_and_leaves_the_baseline(slice2):
    pkg, _ = slice2
    lot = pkg["lots"][2]
    before = PAGE.scenario_view(lot, _json.dumps({}), "1")
    after = PAGE.scenario_view(lot, _json.dumps({"overhead": "0.99"}), "1")
    assert after["scenario_price"] != before["scenario_price"], "the edit did nothing"
    assert after["baseline_price"] == before["baseline_price"], (
        "THE BASELINE MOVED — an edit must never touch the verified figure"
    )


def test_the_baseline_in_a_scenario_is_the_MANIFEST_figure(slice2):
    """Read from the manifest, not recomputed — so the comparison is against what was asserted."""
    pkg, _ = slice2
    lot = pkg["lots"][1]
    manifest_price = next(c["expected"]["price"] for c in pkg["manifest"]["checks"]
                          if c["lot"] == lot)
    sv = PAGE.scenario_view(lot, _json.dumps({"profit": "0.5"}), "0.8")
    assert sv["baseline_price"].replace(",", "") == manifest_price


def test_the_RESET_STATE_reproduces_the_baseline_exactly(slice2):
    """THE SEAL THE $732,148.44 DEFECT ASKED FOR — and the state it checks is the one the UI
    actually opens in, not a convenient one.

    The previous version asserted identity at slope "1". That passed, and the page shipped
    disagreeing with itself, because the field DEFAULTS to the engine's realized slope (0.92)
    and the arithmetic treated it as a further multiplier. A seal that tests a state the
    interface never presents is not testing the interface.

    So identity is read from the package — the same value the field and the reset button take —
    rather than written as a literal here. If the two ever diverge again, this goes red.
    """
    pkg, _ = slice2
    reset_slope = pkg["dataset"]["learning_slope"]
    for lot in pkg["lots"]:
        sv = PAGE.scenario_view(lot, _json.dumps({}), reset_slope)
        assert sv["difference"] == "0.00", (
            f"lot {lot}: the UNTOUCHED scenario differs from the baseline by "
            f"{sv['difference']} — the package disagrees with itself before the customer "
            f"touches anything")
        assert sv["scenario_price"] == sv["baseline_price"]


def test_the_reset_slope_is_the_ENGINES_slope_not_a_literal(slice2):
    """The two meanings that collided: 'the field's default' and 'the curve the engine ran'."""
    from agent_fleet.cost_agent.seed import LEARNING_SLOPE

    pkg, _ = slice2
    assert pkg["dataset"]["learning_slope"] == str(LEARNING_SLOPE)


def test_a_scenario_is_labelled_unverified(slice2):
    pkg, _ = slice2
    assert PAGE.scenario_view(pkg["lots"][0], _json.dumps({}), "1")["verified"] is False


def test_an_out_of_range_slope_falls_back_TO_THE_BASELINE_not_to_one(slice2):
    """Falling back to 1 looks like "no adjustment" and means "no learning at all"."""
    pkg, _ = slice2
    base = pkg["dataset"]["learning_slope"]
    for bad in ("9.9", "0.1", "", "not a number", "-1"):
        sv = PAGE.scenario_view(pkg["lots"][0], _json.dumps({}), bad)
        assert sv["slope"] == base, f"{bad!r} fell back to {sv['slope']}, not {base}"
        assert sv["difference"] == "0.00", f"{bad!r} silently moved the scenario"


# ── SEAL 8 — the dataset hash bites when a row is altered ───────────────────
def test_the_embedded_rows_and_the_duckdb_agree(slice2):
    pkg, db = slice2
    assert X.datasets_agree(pkg["dataset"]["rows"], str(db)) == []


def test_the_agreement_check_BITES_on_an_altered_row(slice2, tmp_path):
    """Tamper with the shipped FILE — the case a hash-by-construction check cannot see."""
    import shutil

    import duckdb
    import scripts.build_cost_dataset as D

    pkg, db = slice2
    tampered = tmp_path / "tampered.duckdb"
    shutil.copy(db, tampered)
    con = duckdb.connect(str(tampered))
    con.execute("UPDATE results SET price = 1.00 WHERE category = 'price'")
    con.close()

    problems = X.datasets_agree(pkg["dataset"]["rows"], str(tampered))
    assert problems, "an altered row was not detected"
    assert D.file_hash(tampered) != pkg["dataset"]["duckdb_sha256"], "the file hash is blind"


def test_the_manifest_carries_BOTH_dataset_hashes(slice2):
    """One identifies the file handed over; the other identifies what the page computes from."""
    pkg, _ = slice2
    d = pkg["dataset"]
    assert d["duckdb_sha256"].startswith("sha256:")
    assert d["rows_sha256"].startswith("sha256:")
    assert d["duckdb_sha256"] != d["rows_sha256"], (
        "the two hashes are over different things and must not coincide"
    )


def test_the_support_touch_ratio_is_CONSTANT_and_so_cannot_detect_staleness(slice2):
    """Recorded so nobody later 'completes' the metric seal by adding this one.

    Support hours are a fixed fraction of touch hours in the seed, so the ratio is 0.450 for
    every lot BY CONSTRUCTION. It is a correct figure and a useless staleness indicator: a
    frozen selector leaves it looking right. The four metrics in the seal above are the ones
    that actually move, and this test pins the reason this one is excluded.
    """
    pkg, _ = slice2
    ratios = {PAGE.labor_view(n)["support_touch_ratio"] for n in pkg["lots"]}
    assert len(ratios) == 1, (
        "the ratio now varies — it has become a usable staleness indicator and should be "
        "added to test_every_labor_metric_differs_between_lots"
    )


def test_a_scenario_cannot_RELABEL_the_rate_vintage(slice2):
    """The provenance lie with no arithmetic tell: relabel the vintage, price does not move."""
    pkg, _ = slice2
    lot = pkg["lots"][0]
    honest = PAGE.scenario_view(lot, _json.dumps({}), "1")
    lied = PAGE.scenario_view(
        lot, _json.dumps({"vintage": "FY99-approved", "fiscal_year": 1999}), "1")
    assert lied == honest, "a label override was accepted into the scenario"
    # ASSERT ON THE LABEL ITSELF, not only on the payload being unchanged. The first version of
    # this seal compared payloads that did not carry the vintage at all, so removing the fence
    # left it green — it was asserting on the neighbour. These two lines are what bites.
    assert lied["rate_vintage"] != "FY99-approved"
    assert lied["rate_fiscal_year"] != 1999


def test_the_scenario_composition_comes_from_the_MANIFEST(slice2):
    """§7's amendment says composition is not editable. This is that claim, executed."""
    pkg, _ = slice2
    lot = pkg["lots"][0]
    forged = _json.dumps({"plus_steps": ["nonsense"], "composition": [], "basis_kind": "x"})
    assert PAGE.scenario_view(lot, forged, "1") == PAGE.scenario_view(lot, "{}", "1")


def test_the_ROW_hash_is_reproducible_and_the_FILE_hash_is_not(slice2):
    """The measured asymmetry, pinned — so nobody treats a rebuild as a corruption.

    Three builds from identical inputs give three distinct .duckdb file hashes at identical
    size: DuckDB stamps per-database metadata. The row hash is stable across the same builds.
    If this test ever fails on the second assertion, DuckDB has become reproducible and
    `duckdb_sha256` may then be used for data identity — which today it may NOT.
    """
    import os
    import scripts.build_cost_dataset as D

    pkg, _ = slice2
    tmp = pathlib.Path(os.environ.get("TEMP", "/tmp"))
    hashes = {D.file_hash(D.build("notional-customer-alpha", tmp / f"repro{i}.duckdb"))
              for i in (1, 2)}
    rows = X.dataset_rows(build_state(), lots=tuple(pkg["lots"]))
    assert X.content_hash(rows) == pkg["dataset"]["rows_sha256"], "the ROW hash must reproduce"
    assert len(hashes) == 2, (
        "the .duckdb is now byte-reproducible — the comment in export.py and this seal both "
        "need revisiting, and duckdb_sha256 may be promoted to data identity"
    )


def test_the_slope_moves_the_scenario_in_BOTH_directions(slice2):
    """A slope that only ever reduced would be a discount knob, not a learning curve."""
    pkg, _ = slice2
    lot = pkg["lots"][-1]
    base = Decimal(pkg["dataset"]["learning_slope"])
    better = PAGE.scenario_view(lot, "{}", str(base - Decimal("0.04")))
    worse = PAGE.scenario_view(lot, "{}", str(base + Decimal("0.04")))
    assert better["difference"].startswith("-"), "a steeper curve must reduce the price"
    assert not worse["difference"].startswith("-"), "a shallower curve must raise it"


def test_ONE_money_format_across_every_rendered_figure(slice2):
    """Two formats on one screen from one package: the composition table printed raw strings."""
    pkg, _ = slice2
    lot = pkg["lots"][0]
    figures = [r[k] for r in PAGE.composition_view(lot)
               for k in ("basis", "amount", "running_total")]
    lv = PAGE.labor_view(lot)
    figures += [lv["total_hours"], lv["total_cost"], lv["unit_price"], lv["touch_per_unit"]]
    for f in figures:
        assert re.fullmatch(r"-?[\d,]+\.\d{2}", f), f"{f!r} is not the shared money format"
    big = [f for f in figures if len(f.split(".")[0].replace("-", "")) > 3]
    assert big and all("," in f for f in big), "a four-digit figure is missing its separator"


def test_formatting_NEVER_changes_a_verified_figure(slice2):
    """The formatter groups and pads. If it re-rounded, the page would show a number the
    manifest does not assert — a divergence with no divergence banner."""
    pkg, _ = slice2
    for chk in pkg["manifest"]["checks"]:
        rendered = PAGE.composition_view(chk["lot"])
        for got, want in zip(rendered, chk["intermediates"]):
            assert got["amount"].replace(",", "") == want["amount"]
            assert got["running_total"].replace(",", "") == want["running_total"]


# ═══════════════════════════════════════════════════════════════════════════
# THE ACROSS-LOTS HALF
# ═══════════════════════════════════════════════════════════════════════════

def test_the_ENGINES_HOURS_follow_the_stated_slope(slice2):
    """THE SEAL THE CHARTS ASKED FOR, on an axis the hours did not produce.

    A learning-curve chart carries its slope in the legend, which makes the slope a claim the
    reader can check with two points and a calculator. Under the previous seed the per-unit
    figures implied **0.7248** beside a label reading **0.92**: the engine scaled a lot's TOTAL
    hours by cumulative position, so a lot's hours did not depend on its own quantity and lot 5
    (24 units) came out below lot 1 (12 units).

    THE FIRST VERSION OF THIS SEAL WAS TAUTOLOGICAL and passed on that very seed. It read the
    plotted `x` — the ALGEBRAIC LOT MIDPOINT — and checked that the points lay on the curve.
    But `x` is computed as `(y/U1)^(1/b)`: it is derived FROM `y` through the same curve, so
    the points lie on it by construction no matter what the engine produced. A bite-check
    caught it: the mutation that restored the broken seed left this green.

    So the check is now against the axis the hours did NOT come from — each lot's cumulative
    range and its own quantity:

        predicted average unit hours = U1 * (C(cum) - C(cum - qty)) / qty

    Every term is independent of the figure being tested.
    """
    import math

    pkg, _ = slice2
    d = pkg["dataset"]
    u1, slope = float(d["unit1_hours"]), Decimal(d["learning_slope"])
    for row in PAGE.learning_curve_view()["baseline"]:
        meta = next(l for l in d["rows"]["lots"] if l["lot"] == row["lot"])
        cum, qty = meta["cumulative_units"], meta["quantity"]
        predicted = u1 * (PAGE._cum(cum, slope) - PAGE._cum(cum - qty, slope)) / qty
        assert abs(predicted - row["y"]) / row["y"] < 5e-5, (
            f"lot {row['lot']}: engine says {row['y']:.2f} h/unit, a {slope} curve over "
            f"units {cum - qty + 1}..{cum} says {predicted:.2f} — the chart would contradict "
            f"its own legend")


def test_the_lot_midpoint_is_a_PLOTTING_device_not_evidence(slice2):
    """Pins the circularity, so the tautological seal cannot come back wearing its name.

    If `_lot_midpoint` is ever changed to something not derived from `y`, this fails and the
    curve-agreement seal above can be simplified. Until then, `x` proves nothing about `y`.
    """
    import math

    pkg, _ = slice2
    d = pkg["dataset"]
    u1, b = float(d["unit1_hours"]), math.log(float(d["learning_slope"])) / math.log(2.0)
    for row in PAGE.learning_curve_view()["baseline"]:
        assert abs(u1 * math.pow(row["x"], b) - row["y"]) / row["y"] < 1e-12, (
            "the midpoint is no longer the exact inverse of the curve")
        # AND IT IS NOT THE CUMULATIVE UNIT COUNT — the two axes must not be confused.
        assert row["x"] != row["cumulative_units"]


def test_a_lots_hours_depend_on_ITS_OWN_quantity(slice2):
    """The defect underneath: hours that ignore lot size. A bigger lot cannot cost less."""
    pkg, _ = slice2
    pv = PAGE.program_view()
    by_lot = {s["lot"]: s for s in pv["series"]}
    for a, b in zip(pv["series"], pv["series"][1:]):
        if b["quantity"] > a["quantity"]:
            assert b["total"] > a["total"], (
                f"lot {b['lot']} has {b['quantity']} units against lot {a['lot']}'s "
                f"{a['quantity']} and FEWER total hours — hours ignore lot size")
    assert by_lot  # the population is derived, not remembered


def test_touch_hours_per_unit_declines_across_the_programme(slice2):
    lc = PAGE.learning_curve_view()
    ys = [p["y"] for p in lc["baseline"]]
    assert all(b < a for a, b in zip(ys, ys[1:])), f"learning is not visible: {ys}"


def test_the_program_chart_carries_its_OWN_scale(slice2):
    """`max_hours` is arithmetic, so it comes from Python. A renderer computing its own could
    rescale one chart against another and no seal would see it."""
    pv = PAGE.program_view()
    assert pv["max_hours"] == max(s["total"] for s in pv["series"])
    for s in pv["series"]:
        assert abs(sum(g["value"] for g in s["segments"]) - s["total"]) < 0.005
        assert [g["key"] for g in s["segments"]] == pv["kinds"]


def test_the_program_view_covers_EXACTLY_the_entitled_lots(slice2):
    pkg, _ = slice2
    assert [s["lot"] for s in PAGE.program_view()["series"]] == list(pkg["lots"])


def test_the_curve_overlay_COINCIDES_at_the_engines_slope(slice2):
    pkg, _ = slice2
    lc = PAGE.learning_curve_view(pkg["dataset"]["learning_slope"])
    assert lc["scenario_is_baseline"] is True
    for b, s in zip(lc["baseline"], lc["scenario"]):
        assert b["display"] == s["display"], f"lot {b['lot']}: the overlay diverges at identity"


def test_the_curve_overlay_MOVES_when_the_slope_is_edited(slice2):
    pkg, _ = slice2
    base = Decimal(pkg["dataset"]["learning_slope"])
    lc = PAGE.learning_curve_view(str(base - Decimal("0.04")))
    assert lc["scenario_is_baseline"] is False
    # LOT 1 IS THE REFERENCE POINT and its average still moves, because the average is over
    # units 1..12 and a different slope changes what units 2..12 cost.
    assert all(s["y"] < b["y"] for b, s in zip(lc["baseline"], lc["scenario"]))


def test_the_overlay_uses_THE_SAME_factor_as_the_scenario_panel(slice2):
    """One model on the page. A chart drawn from a second one would be a picture of nothing."""
    pkg, _ = slice2
    slope = str(Decimal(pkg["dataset"]["learning_slope"]) - Decimal("0.04"))
    lc = PAGE.learning_curve_view(slope)
    base_slope = Decimal(pkg["dataset"]["learning_slope"])
    for b, s in zip(lc["baseline"], lc["scenario"]):
        factor = PAGE._touch_factor(b["lot"], Decimal(slope), base_slope)
        assert abs(b["y"] * float(factor) - s["y"]) < 1e-6


def test_the_baseline_states_the_curve_it_APPLIED(slice2):
    """The reader's remaining blind spot: the baseline table named no slope at all."""
    pkg, _ = slice2
    first, last = pkg["lots"][0], pkg["lots"][-1]
    cf0, cfN = PAGE.curve_factor(first), PAGE.curve_factor(last)
    assert cf0["slope"] == pkg["dataset"]["learning_slope"]
    # A CURVE PRESENT WITH NIL EFFECT IS NOT THE SAME STATEMENT AS NO CURVE.
    assert cf0["factor"] == "1.0000" and "reference point" in cf0["note"]
    assert float(cfN["factor"]) < 1.0 and "below the reference" in cfN["note"]
