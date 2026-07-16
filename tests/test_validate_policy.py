"""Pin the validator's AUTHOR-BUG gate on capability grant subjects.

The phantom-group hazard (broken-closed, grant side): capability_grant_sync writes
`user` subjects unconditionally, so a grant_to that names a GROUP seeds a phantom
`user:<group>` that PASSES readback while granting nothing to the group's members.
The readback (seed-fidelity) cannot catch this — it's an AUTHOR bug, caught by the
VALIDATOR (input-validity). This pins that division of labor: `unknown_user_grants`
refuses any grant_to not in the known-user set.

Run:  PYTHONPATH=policy/sync pytest tests/test_validate_policy.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from capability_grant_sync import CapabilityRecord  # noqa: E402
from validate_policy import unknown_user_grants  # noqa: E402

KNOWN = {"alice@example.com", "bob@example.com", "E12345"}


def _cap(key, *grantees):
    return CapabilityRecord(key=key, grant_to=tuple(grantees), granted_by="c", reason="r")


def test_known_user_grant_passes():
    caps = [_cap("mesh:publishArtifact", "alice@example.com")]
    assert unknown_user_grants(caps, KNOWN) == []


def test_employee_id_known_user_passes():
    caps = [_cap("mesh:publishArtifact", "E12345")]
    assert unknown_user_grants(caps, KNOWN) == []


def test_group_name_grant_is_refused():
    """The exact phantom-group hazard: a group name is NOT a known user."""
    caps = [_cap("mesh:publishArtifact", "data-engineers")]
    errs = unknown_user_grants(caps, KNOWN)
    assert len(errs) == 1
    assert "data-engineers" in errs[0]
    assert "known user" in errs[0]
    assert "phantom" in errs[0]


def test_only_the_unknown_grantee_is_flagged():
    caps = [_cap("mesh:publishArtifact", "alice@example.com", "data-engineers")]
    errs = unknown_user_grants(caps, KNOWN)
    assert len(errs) == 1
    assert "data-engineers" in errs[0]
    assert "alice@example.com" not in errs[0]


def test_empty_is_safe():
    assert unknown_user_grants([], KNOWN) == []
    assert unknown_user_grants([_cap("mesh:x")], KNOWN) == []
