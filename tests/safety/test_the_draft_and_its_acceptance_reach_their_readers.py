"""HAZ-1003 at rev 161: the draft rendered EMPTY and the acceptance it asked for NEVER OPENED.

Two defects, one turn, measured 2026-09-30 when bob drafted HAZ-1003's risk assessment:

  1. THE CARD. engine-safety's `/measure/draft_risk_assessment` returns its draft as FLAT top-level
     fields, and the gateway hands that dict to Engine F as `expert_response` unchanged. The
     deterministic KNOWLEDGE_DOCUMENT composer read only `summary` / `summary_text` /
     `structured_data`, found none, and wrote "No content available." -- with every field the
     binding's `expected_fields` names sitting one level up.

  2. THE ACCEPTANCE. `acceptance_trigger` is flat scalars and carries no token, and
     `_register_human_task` sent the trigger's `user_jwt` -- so the register went out with NO
     Authorization header, cortex-bff answered 401, and the workflow failed-and-released. No
     risk_acceptance row; the gateway had logged "dispatched".
"""
from __future__ import annotations

import ast
import types
from pathlib import Path
from types import SimpleNamespace

from ._engine_extra import requires_rdflib
from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
from iagent_pure import acceptance_request as ar

#: The turn's person, as the envelope names them (`produced_for.authz_id`). Required by the
#: builder since 2026-10-05: a case with no requester registers a row the store refuses.
_REQUESTER = "requester@example.org"
from tests.conftest import stub_modules

_REPO = Path(__file__).resolve().parents[2]
_DRAFT_CLASS = "safety:RiskAssessmentDraft"


def _presentation_main():
    stub = types.ModuleType("baml_client")
    stub.b = SimpleNamespace()
    stub.__path__ = []  # type: ignore[attr-defined]
    with stub_modules({"baml_client": stub}):
        import agent_fleet.presentation_agent.main as _m
    return _m


def _draft_row():
    rows = [r for r in PRESENTATION_CAPABILITIES if r["subject_uri"] == _DRAFT_CLASS]
    assert len(rows) == 1, f"expected one binding for {_DRAFT_CLASS}, found {len(rows)}"
    return rows[0]


# ── 1. THE CARD ──────────────────────────────────────────────────────────────────────────

@requires_rdflib
def test_the_REAL_draft_renders_every_field_its_binding_expects():
    """Over the engine's own output, not a hand-built dict: the fields are DERIVED from the
    binding row, and the payload is what `draft_risk_assessment` actually returns."""
    from agent_fleet.safety_agent import measures

    row = _draft_row()
    assert row["archetype"] == "KNOWLEDGE_DOCUMENT", "the binding moved off the composer this seals"
    draft = measures.draft_risk_assessment(hazard_id="HAZ-1003")
    assert draft.get("refused") is False, draft
    assert "summary" not in draft and "structured_data" not in draft, (
        "the engine now sends an envelope -- this seal's premise (a FLAT reply) no longer holds"
    )
    missing_in_reply = [f for f in row["expected_fields"] if f not in draft]
    assert not missing_in_reply, f"the engine no longer returns {missing_in_reply}"

    pm = _presentation_main()
    wrapped = [{"persona": "SAFETY", "expert_response": draft}]
    md = pm._render_document_deterministic(wrapped, "SAFETY", _DRAFT_CLASS)["components"][0][
        "markdown_content"]
    assert md != "No content available.", "the draft's body was dropped (rev-161 HAZ-1003 card)"
    for f in row["expected_fields"]:
        assert f'"{f}"' in md, f"expected field {f!r} did not reach the card's markdown"
    assert f'"{draft["hazard_id"]}"' in md


def test_a_reply_with_nothing_in_it_still_reads_as_empty():
    """The other direction: the fallback renders CONTENT, not the absence of it. An empty reply
    keeps the placeholder rather than drawing `{}` as though it were an answer."""
    pm = _presentation_main()
    md = pm._render_document_deterministic([{"expert_response": {}}], "SAFETY", None)[
        "components"][0]["markdown_content"]
    assert md == "No content available."


# ── 2. THE ACCEPTANCE ────────────────────────────────────────────────────────────────────

def _register_fn():
    src = (_REPO / "agent_fleet" / "restate_analyst" / "main.py").read_text(encoding="utf-8")
    fns = [n for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.FunctionDef) and n.name == "_register_human_task"]
    assert len(fns) == 1, f"found {len(fns)} definitions of _register_human_task"
    return fns[0]


def test_the_trigger_carries_no_token_so_the_register_cannot_borrow_one():
    """The PREMISE of the mint: a SafetyAcceptance trigger is flat scalars with no credential
    (and must stay so -- the trigger is journaled, a token in it is a credential at rest)."""
    trig = ar.acceptance_trigger({
        "kind": "risk_acceptance", "audience": "risk_acceptance_medium:SUSTAINMENT",
        "subject_ref": "HAZ-1003",
        "payload": {"hazard_id": "HAZ-1003", "risk_level": "MEDIUM", "risk_level_slug": "medium"},
    }, authz_id=_REQUESTER)
    assert not any("jwt" in k or "token" in k for k in trig), sorted(trig)


def test_the_register_mints_its_own_identity_at_use():
    """Read from `restate_analyst/main.py`'s source -- the module is unimportable here
    (`orchestrator.auth` has no source-layout fallback; see test_the_review_request_has_a_consumer).
    The Authorization value must be built from a `mint_service_token()` CALL, and the function
    must not take a caller token it could fall back to."""
    fn = _register_fn()
    params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
    assert not any("jwt" in p or "token" in p for p in params), (
        f"_register_human_task takes {params} -- a stored caller token is the rev-161 defect"
    )
    auth_values = [
        v for n in ast.walk(fn) if isinstance(n, ast.Dict)
        for k, v in zip(n.keys, n.values)
        if isinstance(k, ast.Constant) and k.value == "Authorization"
    ]
    assert len(auth_values) == 1, f"expected one Authorization header, found {len(auth_values)}"
    minted = [c for c in ast.walk(auth_values[0])
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
              and c.func.id == "mint_service_token"]
    assert minted, "the register's Authorization is not minted at use"
    headers = [n.value for n in ast.walk(fn) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "headers" for t in n.targets)]
    assert headers and all(isinstance(h, ast.Dict) for h in headers), (
        "the header is conditional -- a missing token would again send none (the 401 shape)"
    )
