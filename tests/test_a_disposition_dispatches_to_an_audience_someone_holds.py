"""A disposition whose dispatch audience no group or user holds fails policy validation.

Ruled 2026-11-19 (architect, item 2b). An approved disposition opens a task for the audience
`_DISPOSITION_QUEUE` names; an audience with no holder routes that task to NOBODY. The map is read
from the ONE declaration (dispatch_plan.py, by AST), never copied.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SYNC = ROOT / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from validate_policy import (  # noqa: E402
    disposition_audience_errors,
    load_disposition_queue_map,
    validate,
)

USERS = [
    {"id": "bob@example.com", "groups": ["buyers"]},
    {"id": "dan@example.com", "groups": []},
]
GROUPS = {"buyers": {}, "empty-group": {}}


def _aud(key, grant_to=(), groups=()):
    return SimpleNamespace(key=key, grant_to=tuple(grant_to), grant_to_groups=tuple(groups))


def test_b1_the_real_policy_dir_has_no_unheld_disposition_audience():
    errs = [e for e in validate(ROOT / "policy", ROOT / "policy") if "dispatches to audience" in e]
    assert errs == []


def test_b2_the_map_is_the_one_declaration_and_can_fire():
    try:
        from agent_fleet.restate_analyst.dispatch_plan import _DISPOSITION_QUEUE  # type: ignore
    except Exception:  # noqa: BLE001
        sys.path.insert(0, str(ROOT / "agent_fleet" / "restate_analyst"))
        from dispatch_plan import _DISPOSITION_QUEUE  # type: ignore[no-redef]
    got = load_disposition_queue_map()
    assert got == dict(_DISPOSITION_QUEUE)
    assert got and any(v is not None for v in got.values())


def test_b3_audience_missing_from_task_grants():
    errs = disposition_audience_errors({"dispatchX": "ghost"}, [_aud("other", ["bob@example.com"])],
                                       GROUPS, USERS)
    assert len(errs) == 1 and "'dispatchX'" in errs[0] and "'ghost'" in errs[0]
    assert "NOT an audience" in errs[0]


def test_b4_grant_to_user_absent_from_users_yaml():
    errs = disposition_audience_errors({"d": "a"}, [_aud("a", ["nobody@example.com"])], {}, USERS)
    assert len(errs) == 1 and "NO user or group holds" in errs[0]


def test_b5_group_holder_needs_a_member():
    held = disposition_audience_errors({"d": "a"}, [_aud("a", groups=["buyers"])], GROUPS, USERS)
    assert held == []
    empty = disposition_audience_errors({"d": "a"}, [_aud("a", groups=["empty-group"])],
                                        GROUPS, USERS)
    assert len(empty) == 1 and "'a'" in empty[0]


def test_b6_none_audience_is_never_checked():
    assert disposition_audience_errors({"archive": None}, [], {}, []) == []


def test_b7_renamed_declaration_is_an_error_not_none(tmp_path):
    src = (ROOT / "agent_fleet" / "restate_analyst" / "dispatch_plan.py").read_text(encoding="utf-8")
    assert "_DISPOSITION_QUEUE = {" in src
    f = tmp_path / "dispatch_plan.py"
    f.write_text(src.replace("_DISPOSITION_QUEUE = {", "_RENAMED_QUEUE = {", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot read _DISPOSITION_QUEUE"):
        load_disposition_queue_map(f)
    assert load_disposition_queue_map(tmp_path / "absent.py") is None


def test_b8_validate_itself_runs_the_check(tmp_path):
    """The wiring: a policy dir whose `sourcing` row is gone fails validate() (B1's inverse)."""
    import shutil

    pol = tmp_path / "policy"
    shutil.copytree(ROOT / "policy", pol)
    text = (pol / "task_grants.yaml").read_text(encoding="utf-8")
    a = text.index("  sourcing:\n    granted_by")
    b = text.index("  # ─", a)
    (pol / "task_grants.yaml").write_text(text[:a] + text[b:], encoding="utf-8")
    errs = [e for e in validate(pol, pol) if "dispatches to audience" in e]
    assert len(errs) == 1 and "'dispatchAltSourcing'" in errs[0] and "'sourcing'" in errs[0]
