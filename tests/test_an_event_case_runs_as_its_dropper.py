"""Ruling 2026-10-11: step 1 of the maintenance fault walk runs on_behalf_of the event's
`dropped_by` (via svc:openddil); svc:case-runner never gets a verb grant. `_run_definition`
derives its identity via `_run_subject`, with the dropper as the LAST fallback."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for p in (_ROOT, _ROOT / "src", _ROOT / "agent_fleet" / "restate_analyst"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from agent_fleet.restate_analyst import main as ra_main  # noqa: E402

_run_subject = ra_main._run_subject

_FIXTURES = {
    "dropper_only": ({"dropped_by": {"authz_id": "svc:openddil", "via": "svc:openddil"}}, "svc:openddil"),
    "dropper_person": ({"dropped_by": {"authz_id": "erin@example.com", "via": "svc:openddil"}}, "erin@example.com"),
    "dropper_padded": ({"dropped_by": {"authz_id": "  erin@example.com "}}, "erin@example.com"),
    "explicit": ({"authz_id": "a@x", "caller_email": "c@x", "dropped_by": {"authz_id": "svc:openddil"}}, "a@x"),
    "caller_email": ({"caller_email": "c@x", "dropped_by": {"authz_id": "svc:openddil"}}, "c@x"),
    "none": ({}, ""),
    "str": ({"dropped_by": "svc:openddil"}, ""),
    "no_authz": ({"dropped_by": {"via": "svc:openddil"}}, ""),
    "blank": ({"dropped_by": {"authz_id": "   "}}, ""),
    "non_str": ({"dropped_by": {"authz_id": 7}}, ""),
}


def test_dropper_only():
    assert _run_subject(_FIXTURES["dropper_only"][0]) == "svc:openddil"


def test_dropper_is_a_person():
    assert _run_subject(_FIXTURES["dropper_person"][0]) == "erin@example.com"


def test_dropper_is_stripped():
    assert _run_subject(_FIXTURES["dropper_padded"][0]) == "erin@example.com"


def test_explicit_authz_id_beats_dropper():
    assert _run_subject(_FIXTURES["explicit"][0]) == "a@x"


def test_caller_email_beats_dropper():
    assert _run_subject(_FIXTURES["caller_email"][0]) == "c@x"


def test_control_nothing_present_is_blank():
    assert _run_subject(_FIXTURES["none"][0]) == ""


@pytest.mark.parametrize("name", ["str", "no_authz", "blank", "non_str"])
def test_malformed_dropped_by_contributes_nothing(name):
    assert _run_subject(_FIXTURES[name][0]) == ""


def test_never_the_runner_itself():
    for name, (req, _want) in _FIXTURES.items():
        assert _run_subject(req) != "svc:case-runner", name


def test_run_definition_identity_is_built_from_the_helper():
    """WIRING: the identity dict's authz_id in `_run_definition` is `_run_subject(request)`."""
    tree = ast.parse((_ROOT / "agent_fleet/restate_analyst/main.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_definition")
    vals = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "identity" for t in n.targets):
            vals += [v for k, v in zip(n.value.keys, n.value.values)
                     if isinstance(k, ast.Constant) and k.value == "authz_id"]
    assert len(vals) == 1, "identity['authz_id'] not found exactly once"
    v = vals[0]
    assert isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "_run_subject", ast.dump(v)
