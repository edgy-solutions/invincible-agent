"""The case's `received` row is labelled by its trigger's declaration, and by nothing else.

The architect (2026-11-08): "the case's 'received' row label is served by the runner from the
workflow declaration (an `intake` label on the case, one field) ... No word in code on either
side." The row is recorded before any definition is selected, so the trigger is the declaration
it can come from. The runner stamps it on the case at open, and the projection serves it.

Each arm is a claim about what the case may NOT do:

* SERVE A LABEL ITS TRIGGER DID NOT DECLARE -- the control trigger declares none, and its case
  carries no `intake` key at all (an empty or null one would read as a declared blank);
* SERVE ONE FOR A CASE OPENED BEFORE THE STAMP -- an old record has no key, and gets none;
* LOAD A BLANK LABEL -- a whitespace `intake:` is refused at load, not served as a blank row.

Run: uv run --frozen pytest tests/test_the_case_serves_the_intake_label_its_trigger_declares.py -v
"""
from __future__ import annotations

import pytest

from src.iagent import case_projection  # noqa: E402
from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: E402,F401
    _DEFINITIONS, _TABLES, _Cluster, _answer, _dump, _facts, R, registered, wd,
)

#: The label is the declaration's own text; this file invents one, and reads it back from the row.
_LABEL = "reported"

_TRIGGERS = {
    "labelled": {"trigger": "labelled", "selection": "sel", "key": "event_id",
                 "intake": _LABEL},
    "unlabelled": {"trigger": "unlabelled", "selection": "sel", "key": "event_id"},
}


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_TRIGGER_DIR", str(_dump(tmp_path / "triggers", _TRIGGERS)))
    monkeypatch.setenv("DECISION_TABLE_DIR", str(_dump(tmp_path / "decisions", _TABLES)))
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR",
                       str(_dump(tmp_path / "workflows", _DEFINITIONS)))
    monkeypatch.setattr(wd, "load_stub_verbs", lambda: {})
    return tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger, want", [("labelled", _LABEL), ("unlabelled", None)],
                         ids=["declared", "control-undeclared"])
async def test_THE_CASE_SERVES_THE_INTAKE_ITS_TRIGGER_DECLARES_AND_NONE_OTHERWISE(
        policy, registered, trigger, want):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    out = await c.start("E-1", trigger, _facts())
    assert out["status"] == "CLOSED", out
    case = c.case("E-1")
    # the received row is the case's first, and the label is stamped before it
    assert case["transitions"][0]["outcome"] == "received", case["transitions"][0]
    assert case["intake"] == want, case
    served = case_projection.project_workflow_case(case, {}, [])
    if want is None:
        assert "intake" not in served, served
    else:
        assert served["intake"] == want, served


def test_A_CASE_OPENED_BEFORE_THE_STAMP_IS_SERVED_NO_INTAKE():
    old = {"case_id": "E-0", "terminal": None, "state": None, "transitions": []}
    served = case_projection.project_workflow_case(old, {}, [])
    assert "intake" not in served, served


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "whitespace"])
def test_A_BLANK_INTAKE_IS_REFUSED_AT_LOAD(blank):
    row = dict(_TRIGGERS["labelled"], intake=blank)
    with pytest.raises(ValueError):
        R.Trigger.model_validate(row)
    # control: the same row with its declared label loads, and keeps it
    assert R.Trigger.model_validate(_TRIGGERS["labelled"]).intake == _LABEL
