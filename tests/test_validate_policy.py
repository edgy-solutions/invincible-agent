"""Pin the validator's AUTHOR-BUG gate on grant subjects, family-wide.

The phantom-group hazard (broken-closed, grant side): ALL FOUR grant syncs
(asset/task/ontology/capability) write `user` subjects unconditionally, so a
grant subject that names a GROUP seeds a phantom `user:<group>` that PASSES
readback while granting nothing to the group's members. The readback (seed-
fidelity) cannot catch this — it's an AUTHOR bug, caught by the VALIDATOR (input-
validity). This pins that division: `unknown_user_subjects` refuses any grant
subject not in the known-user set. On task_grants it's the sharpest (an approval
task routed to nobody). Group grants are DEFERRED (needs an audit-semantics ruling).

Run:  PYTHONPATH=policy/sync pytest tests/test_validate_policy.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from validate_policy import unknown_user_subjects  # noqa: E402

KNOWN = {"alice@example.com", "bob@example.com", "E12345"}


def test_known_user_grant_passes():
    pairs = [("mesh:publishArtifact", "alice@example.com")]
    assert unknown_user_subjects("capability_grants.yaml", pairs, KNOWN) == []


def test_employee_id_known_user_passes():
    pairs = [("some:asset", "E12345")]
    assert unknown_user_subjects("asset_grants.yaml", pairs, KNOWN) == []


def test_group_name_grant_is_refused():
    """The exact phantom-group hazard: a group name is NOT a known user."""
    pairs = [("mesh:publishArtifact", "data-engineers")]
    errs = unknown_user_subjects("capability_grants.yaml", pairs, KNOWN)
    assert len(errs) == 1
    assert "data-engineers" in errs[0]
    assert "known user" in errs[0]
    assert "phantom" in errs[0]


def test_task_grants_group_routed_to_nobody_is_refused():
    """The sharpest instance: an approval AUDIENCE granted to a group would route
    the task to nobody while the file says it's covered."""
    pairs = [("promotion:DATA_ENGINEERING", "data-engineers")]
    errs = unknown_user_subjects("task_grants.yaml", pairs, KNOWN)
    assert len(errs) == 1
    assert "task_grants.yaml" in errs[0]
    assert "data-engineers" in errs[0]


def test_file_label_and_context_surface_in_message():
    pairs = [("PII_COMPARTMENT", "analysts")]
    errs = unknown_user_subjects("ontology_compartments.yaml", pairs, KNOWN)
    assert "ontology_compartments.yaml" in errs[0]
    assert "PII_COMPARTMENT" in errs[0]


def test_only_the_unknown_grantee_is_flagged():
    pairs = [("k", "alice@example.com"), ("k", "data-engineers")]
    errs = unknown_user_subjects("capability_grants.yaml", pairs, KNOWN)
    assert len(errs) == 1
    assert "data-engineers" in errs[0]
    assert "alice@example.com" not in errs[0]


def test_empty_is_safe():
    assert unknown_user_subjects("capability_grants.yaml", [], KNOWN) == []
