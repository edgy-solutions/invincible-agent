"""Two wire-level seals, and the second is the one that would have caught the real drop.

WHAT HAPPENED, 2026-09-03. `reference` and `verdict` were added to two finance envelopes and
arrived at no card. The reporting lane read it as a producer bug -- "report says emitted, wire
says absent" -- and asked for a seal on the measure endpoint's response body.

**THE MEASURE ENDPOINT WAS CORRECT THE WHOLE TIME.** Verified on the deployed pod: its HTTP
body carries `reference`, `verdict`, and a `series` list with `unit` and `dashed` intact. A seal
on that endpoint would have PASSED while the cards stayed wrong -- measuring the neighbour,
which is the very failure the request was trying to avoid.

The drop was `_PROJECTED_ARCHETYPES`: the projector carries the payload key plus a declared
tuple of passthrough fields and NOTHING ELSE, and that tuple predated both additions.

AND THE CONTRAST IS THE WHOLE LESSON. `favourable` shipped in the same commit and arrived fine,
because it rides inside `rows`, which pass through verbatim. So a ROW-level addition needs no
declaration and an ENVELOPE-level addition needs one -- and nothing anywhere reported the
difference. Two fields added, one silently discarded.

So: seal 1 is what was asked for and guards the engine. Seal 2 guards the seam that actually
broke, and is derived from the engine's own declaration tables rather than a remembered list.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.finance_agent import measures  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed  # noqa: E402

_STATE = build_seed()
_KW = {"fin_eac_calculation": {"method": "CPI"}}


def _envelope(fn: str) -> dict:
    """The response body `/measure/<fn>` builds, via the app itself rather than a copy of it."""
    from fastapi.testclient import TestClient
    from agent_fleet.finance_agent.main import app
    with TestClient(app) as client:
        r = client.post(f"/measure/{fn}",
                        json={"params": {"program_id": "NP-MERIDIAN", **_KW.get(fn, {})}})
    assert r.status_code == 200, f"{fn}: {r.status_code} {r.text[:200]}"
    return r.json()


# -- SEAL 1 -- the engine's own wire, as requested --------------------------------------

def test_the_measure_response_BODY_carries_every_declared_envelope_field():
    """Asserted on the real HTTP body, not on the measure function's return value.

    The declaration tables are the population, so a seventh verb that declares a reference
    inherits this without an edit here.
    """
    for fn, decl in measures.SERIES.items():
        body = _envelope(fn)
        assert body.get("series") == decl, (
            f"{fn}: `series` on the wire is {body.get('series')!r}, declared {decl!r}"
        )
    for fn, ref in measures.REFERENCE.items():
        assert _envelope(fn).get("reference") == ref, f"{fn}: `reference` absent or altered"
    for fn, verdict_of in measures.VERDICT.items():
        rows = getattr(measures, fn)(_STATE, program_id="NP-MERIDIAN")
        expected = verdict_of(rows)
        body = _envelope(fn)
        if expected is None:
            assert "verdict" not in body, f"{fn}: emitted a null verdict key"
        else:
            assert body.get("verdict") == expected, (
                f"{fn}: verdict on the wire {body.get('verdict')!r} != {expected!r}"
            )


def test_series_entries_keep_their_unit_and_dashed_on_the_wire():
    """`dashed` and `unit` are the fields most likely to be dropped by a serializer, because
    they are OPTIONAL and per-entry. The burn card's dashed plan line depends on one of them
    reaching the card, and it was specifically doubted."""
    burn = _envelope("fin_burn_rate")["series"]
    plan = [s for s in burn if s["key"] == "planned"]
    assert plan and plan[0].get("dashed") is True, "the plan series lost `dashed` on the wire"
    assert all(s.get("unit") == "USD" for s in burn), "a burn series lost its `unit`"
    idx = _envelope("fin_performance_indices")["series"]
    assert all("unit" not in s for s in idx), (
        "a dimensionless index gained a unit -- absence is the assertion, per the contract"
    )


# -- SEAL 2 -- the seam that actually broke ---------------------------------------------

def _projector_passthrough() -> dict:
    """Parsed from the projector's own source, because presentation_agent/main.py imports
    baml_client and cannot be imported outside its container -- the same reason
    `capability_slug` was untestable until it moved."""
    src = (_ROOT / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    block = re.search(r"_PROJECTED_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    assert block, "could not find _PROJECTED_ARCHETYPES -- the projector's shape moved"
    out = {}
    for name, key, rest in re.findall(
        r'^\s*"(\w+)":\s*\("(\w+)",\s*\(([^)]*)\)\)', block.group(1), re.M
    ):
        out[name] = (key, tuple(re.findall(r'"(\w+)"', rest)))
    assert out, "parsed no entries -- the regex is stale, not the table"
    return out


def _fin_bindings() -> dict:
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
    by_output = {uri: fn for fn, uri in measures.OUTPUT_URI.items()}
    out = {}
    for cap in PRESENTATION_CAPABILITIES:
        subj = cap["subject_uri"]
        if not subj.startswith("fin:"):
            continue
        full = subj.replace("fin:", "http://invincible-agent/fin#", 1)
        fn = by_output.get(full) or by_output.get(subj)
        if fn:
            out[fn] = cap["archetype"]
    return out


def test_every_envelope_field_a_verb_declares_survives_its_archetype_passthrough():
    """THE SEAL THE MEASURE-ENDPOINT ONE COULD NOT BE.

    The projector carries `rows` plus a declared tuple and DISCARDS THE REST SILENTLY. So an
    envelope-level field is only real if its archetype declares it, and nothing connected the
    two declarations until this test.

    Derived from three sources that must agree -- the engine's declaration tables, the
    capability bindings, and the projector's own table -- so a new field, a new verb or a
    rebinding each fail here rather than at a card.
    """
    passthrough = _projector_passthrough()
    bindings = _fin_bindings()
    assert bindings, "derived no fin bindings -- the derivation is stale"

    declared_by_fn: dict = {}
    for table, field in ((measures.SERIES, "series"),
                         (measures.REFERENCE, "reference"),
                         (measures.VERDICT, "verdict")):
        for fn in table:
            declared_by_fn.setdefault(fn, set()).add(field)

    missing = []
    for fn, fields in sorted(declared_by_fn.items()):
        archetype = bindings.get(fn)
        assert archetype, f"{fn} declares {sorted(fields)} but is bound to no archetype"
        spec = passthrough.get(archetype)
        assert spec, f"{archetype} is not in the projector table -- {fn} cannot render at all"
        carried = set(spec[1])
        for f in sorted(fields - carried):
            missing.append(f"{fn} declares {f!r} -> {archetype} passthrough {spec[1]} drops it")
    assert not missing, (
        "envelope fields DISCARDED by the projector, silently:\n  " + "\n  ".join(missing)
        + "\n\nThe engine emits them and no card receives them. Add the field to that "
          "archetype's passthrough tuple, or stop emitting it."
    )


def test_row_level_fields_need_NO_declaration_and_that_is_why_favourable_survived():
    """The contrast, pinned, because it is what made the drop invisible.

    `favourable` was added in the same commit as `reference` and `verdict` and arrived at the
    card, because rows pass through verbatim. Anyone reasoning "the other field arrived, so the
    payload is fine" was reasoning from a real observation about a different mechanism.
    """
    key, carried = _projector_passthrough()["MULTI_SERIES"]
    assert key == "rows", "MULTI_SERIES no longer projects `rows` -- this test's premise moved"
    tree = measures.fin_variance_analysis(_STATE, program_id="NP-MERIDIAN")[0]
    assert "favourable" in tree, "the tree stopped emitting a verdict"
    assert "favourable" not in carried, (
        "`favourable` is declared as a passthrough field -- it is a ROW field and needs no "
        "declaration; listing it here would suggest row additions require one, which is the "
        "confusion that hid this bug"
    )


# ── THE ARCHETYPE AXIS, widened 2026-09-05 ────────────────────────────────────────────
#
# The seal above derives its population from THIS ENGINE's declaration tables, so it covers
# every archetype a fin: verb produces and NOTHING ELSE. ELICITATION is produced by the
# supervisor's ask path, not by a measure verb, so it sat outside the population entirely — and
# a whole archetype with no projector entry fell through to KNOWLEDGE_DOCUMENT silently, which
# is the same drop as `reference`/`verdict` one level up: not a field discarded, a card.
#
# So the axis is now derived from CORTEX'S CONTRACTS — every archetype the frontend declares it
# can draw — rather than from what this engine happens to emit. That is the population the
# projector actually has to cover.

_CORTEX = _ROOT.parent / "cortex-ui"


def _cortex_declared_archetypes() -> dict:
    """archetype -> set(required field names), parsed from cortex's *.contract.ts."""
    out = {}
    if not _CORTEX.is_dir():
        return out
    for p in _CORTEX.rglob("*.contract.ts"):
        src = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'archetype:\s*"([A-Z_]+)"', src)
        if not m:
            continue
        fields = re.search(r"fields:\s*\{(.*?)\n  \}", src, re.S)
        req = set()
        if fields:
            for fname, body in re.findall(r"(\w+):\s*\{([^}]*)\}", fields.group(1)):
                if "required: true" in body:
                    req.add(fname)
        out[m.group(1)] = req
    return out


def _flat_archetypes() -> dict:
    src = (_ROOT / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    block = re.search(r"_FLAT_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    if not block:
        return {}
    out = {}
    for name, groups in re.findall(r'^\s*"(\w+)":\s*\((.*?)\),\n', block.group(1), re.S | re.M):
        out[name] = tuple(re.findall(r'"(\w+)"', groups))
    return out


def test_ELICITATION_is_projected_and_carries_the_field_its_contract_REQUIRES():
    """The specific regression: an ask with no menu drew as KNOWLEDGE_DOCUMENT.

    Pinned on the REQUIRED field rather than the whole list, because the optional ones are
    absent-means-something and asserting their presence would forbid a legitimate ask.
    """
    flat = _flat_archetypes()
    assert "ELICITATION" in flat, (
        "ELICITATION has no projector entry — an archetype with no path falls through to "
        "KNOWLEDGE_DOCUMENT by construction, which is a whole card lost silently"
    )
    declared = _cortex_declared_archetypes()
    if "ELICITATION" not in declared:
        pytest.skip("cortex-ui not checked out beside this repo")
    missing = declared["ELICITATION"] - set(flat["ELICITATION"])
    assert not missing, (
        f"ELICITATION's projector does not carry {sorted(missing)}, which cortex's contract "
        f"marks required — the card mounts and cannot say what it is asking for"
    )


def test_an_ask_with_NO_MENU_is_still_projectable():
    """⛔ THE CASE THAT MOTIVATED A SECOND TABLE, and the one a list projector rejects.

    `options` is legitimately EMPTY whenever no provider could enumerate the slot — the producer
    says why in `free_text_reason`, and "which program? I could not list them" is a complete
    ask. The list projector returns None on an empty payload, which is correct for a grid and
    exactly wrong here: it would reject the asks that most need to render.

    So ELICITATION must NOT be in the list-projected table, and this asserts that separation
    rather than trusting it.
    """
    passthrough = _projector_passthrough()
    assert "ELICITATION" not in passthrough, (
        "ELICITATION is in _PROJECTED_ARCHETYPES, whose projector requires a NON-EMPTY list "
        "under its payload key. An ask with no menu has none, so every menu-less ask would "
        "silently degrade — the failure this separation exists to prevent."
    )
    flat = _flat_archetypes()
    assert "options" not in flat["ELICITATION"][:1], (
        "`options` is declared REQUIRED for ELICITATION; an ask with no menu is legitimate"
    )


def test_every_archetype_cortex_can_draw_has_SOME_projector_path():
    """The widened axis. Reported per archetype so a gap names itself.

    An archetype cortex declares and the backend cannot project is a card that will never
    render — and it degrades to KNOWLEDGE_DOCUMENT rather than erroring, so nothing goes red.
    Archetypes served by a hardened BAML renderer are legitimately absent from both tables, so
    those are listed rather than asserted: this fails only for an archetype with NO path at all.
    """
    declared = _cortex_declared_archetypes()
    if not declared:
        pytest.skip("cortex-ui not checked out beside this repo")
    projected = set(_projector_passthrough()) | set(_flat_archetypes())
    hardened = {"CHART_WIDGET", "KNOWLEDGE_DOCUMENT", "PROCESS_TOPOLOGY",
                "HAZARD_DECLARATION", "ASSET_STATE_METRIC", "GROUPED_REVIEW",
                "APPROVAL_TASK", "WORKFLOW_OBSERVATION", "INSTANCES_BY_PROPERTY",
                "DECISION_RECORD", "CANVAS_SEED"}
    orphans = sorted(set(declared) - projected - hardened)
    assert not orphans, (
        f"{len(orphans)} archetype(s) cortex declares with NO backend projection path: "
        f"{orphans}. Each degrades to KNOWLEDGE_DOCUMENT silently. Add a projector entry, or "
        f"add it to the hardened-renderer set in this test if a BAML renderer serves it."
    )
