"""ADR-0050 §3's SEED_PANEL REBUILD — the stream side, sealed.

`_pre_resolved_from_seed_panel` (`src/iagent/gateway.py`) is what `_generate_dagster_stream_inner`
calls to rebuild a dispatch route from a ratified template's own panel, when `seed_panel` is
present and no ask is being answered. It reads `panel.subject` directly as `subject_uri` — no
ontology lookup, because none exists — and `panel.verb` as `verb_iri`; `dispatch_pre_
resolved`'s own `find_compatible_verbs` call still confirms both against the live mesh on every
dispatch (ROUTED/ABSTAIN/FALL_BACK), so the seal here is only about what THIS function hands it,
never about the mesh's answer.

THE TWO MUTATIONS THIS SEAL MUST CATCH:
  1. Accepting a client-supplied verb (anything in `seed_panel["bindings"]` or elsewhere in the
     request) instead of the TEMPLATE's own `panel.verb` — `test_a_client_supplied_verb_key_is_
     IGNORED` plants one in `bindings` under the name `verb` and asserts it never reaches
     `verb_iri`.
  2. Dropping the bound shared slot (`program_id`) from the dispatch params —
     `test_the_bound_shared_slot_reaches_params_under_its_bind_as_name` asserts `program_id` is
     actually in the returned params, not merely that the call did not raise.

Run: uv run pytest tests/planning/test_seed_panel_rebuilds_from_the_template.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402


def _seed_panel_for(panel_idx: int, **bindings) -> dict:
    return {"template_id": "program_finance", "panel": panel_idx, "bindings": dict(bindings)}


def test_subject_and_verb_come_from_the_templates_own_panel():
    """THE BASE CASE. Panel 0 is `mesh:finFundingStatus`, declared `subject`
    `http://invincible-agent/fin#FundingLine` (policy/canvases/program_finance.yaml) — both must
    come through verbatim, with no ontology lookup in between."""
    pre_resolved, params = gw._pre_resolved_from_seed_panel(
        _seed_panel_for(0, program="NP-MERIDIAN")
    )
    assert pre_resolved["subject_uri"] == "http://invincible-agent/fin#FundingLine"
    assert pre_resolved["verb_iri"] == "mesh:finFundingStatus"
    assert pre_resolved["subject_instance_id"] == "NP-MERIDIAN"
    assert params == {"program_id": "NP-MERIDIAN"}


def test_a_client_supplied_verb_key_is_IGNORED():
    """MUTATION TARGET 1. A `seed_panel.bindings` carrying a key named `verb` is not a shared
    slot `program_finance` declares, so it must have NO effect on the dispatched verb — the
    verb is the TEMPLATE's `panel.verb`, never anything the request body could supply. A
    mutation that reads a client-supplied verb (e.g. `seed_panel.get("verb") or panel.verb`,
    or splatting unrecognised bindings keys into the pre_resolved dict) would let this binding
    override the dispatch; this must stay `mesh:finFundingStatus`."""
    pre_resolved, _ = gw._pre_resolved_from_seed_panel(
        _seed_panel_for(0, program="NP-MERIDIAN", verb="mesh:finEacCalculation")
    )
    assert pre_resolved["verb_iri"] == "mesh:finFundingStatus", (
        f"a bindings key named 'verb' reached verb_iri: {pre_resolved['verb_iri']!r}"
    )


def test_the_bound_shared_slot_reaches_params_under_its_bind_as_name():
    """MUTATION TARGET 2. `program` is the ASK's identity; `program_id` is what every finance
    verb actually declares (`SharedSlot.bind_as`). A mutation that drops the bound-shared-slot
    merge (or that binds under `name` instead of `bind_as`) must turn this red: `program_id`
    specifically must be a key in the returned params, carrying the bound value."""
    _, params = gw._pre_resolved_from_seed_panel(_seed_panel_for(3, program="NP-MERIDIAN"))
    assert "program_id" in params, f"program_id dropped from dispatch params: {params}"
    assert params["program_id"] == "NP-MERIDIAN"
    # Panel 3 is `mesh:finVarianceAnalysis`, whose OWN signature defaults (variance_kind,
    # materiality, max_depth) must survive alongside the merged shared slot, not be replaced by
    # it — the merge is additive.
    assert params["variance_kind"] == "cost"
    assert params["materiality"] == 0.05
    assert params["max_depth"] == 3


def test_an_unbound_consumed_slot_yields_no_instance_and_no_binding():
    """Without `program` bound, nothing names the subject instance and `program_id` must not
    appear at all — an empty string would be a fabricated binding, not an honest absence."""
    pre_resolved, params = gw._pre_resolved_from_seed_panel(_seed_panel_for(0))
    assert pre_resolved["subject_instance_id"] == ""
    assert "program_id" not in params


def test_a_panel_declaring_no_subject_refuses_the_rebuild():
    """`portfolio`'s panels declare no `subject` (ADR-0050 §3's carry has not landed there) —
    the rebuild must refuse rather than hand `dispatch_pre_resolved` an empty `subject_uri`."""
    pre_resolved, params = gw._pre_resolved_from_seed_panel(
        {"template_id": "portfolio", "panel": 0, "bindings": {}}
    )
    assert pre_resolved == {}
    assert params == {}


def test_an_out_of_range_panel_refuses_the_rebuild():
    pre_resolved, params = gw._pre_resolved_from_seed_panel(
        {"template_id": "program_finance", "panel": 99, "bindings": {}}
    )
    assert pre_resolved == {}
    assert params == {}


def test_an_unknown_template_refuses_the_rebuild():
    pre_resolved, params = gw._pre_resolved_from_seed_panel(
        {"template_id": "no_such_template", "panel": 0, "bindings": {}}
    )
    assert pre_resolved == {}
    assert params == {}
