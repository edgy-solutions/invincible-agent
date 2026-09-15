"""`grant_to: svc:*` is refused — the rule that lived in a comment is now a property of the file.

THE GAP, named by `invincible-agent-81` against the grant rail. `svc:` subjects ARE seeded users
— deliberately, so the identities are legible and grantable through the rails — so
`unknown_user_subjects` resolves them happily. A grant reading `grant_to: svc:cortex-bff` passed
validation, would have synced, and would have read back green.

**THE RULE ALREADY EXISTED. IT LIVED IN A COMMENT**, in `policy/users.yaml`, beside
`svc:data-analyst`:

    the service credential says WHICH SERVICE is calling, not WHOSE data may be read.
    DA serves every caller, so a read grant on svc:data-analyst would entitle EVERY caller
    to whatever it can reach — the confused deputy the per-caller conjunction exists to prevent.

**An engine-local rule the rail silently accepts is droppable by the next person who edits the
rail without reading the engine.** A validator makes it a property of the file, which is the
whole difference between a convention and a constraint — the same move as a lesson written
beside a list not maintaining the list.

SCOPE IS DISCLOSURE-RECIPIENT GRANTS. `capability_grants.yaml` is deliberately exempt: an INVOKE
is an EFFECT rather than a read, as that file's own header says, and a service invoking a
capability is not the confused deputy. The exemption is asserted below so it stays a decision.

Run: uv run --frozen pytest tests/test_a_service_identity_is_not_a_disclosure_recipient.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "policy" / "sync"))

from validate_policy import (  # noqa: E402
    SERVICE_SUBJECT_PREFIX,
    service_identity_recipients,
)

_USERS = _REPO / "policy" / "users.yaml"
_VALIDATOR = _REPO / "policy" / "sync" / "validate_policy.py"


def test_A_SERVICE_GRANTEE_IS_REFUSED():
    errs = service_identity_recipients("task_grants.yaml", [("some-task", "svc:cortex-bff")])
    assert len(errs) == 1, "a svc: grantee passed the disclosure gate"
    assert "svc:cortex-bff" in errs[0]
    assert "confused deputy" in errs[0], (
        "the refusal does not name WHY. A refusal a reader cannot act on gets worked around, "
        "and the workaround is a grant to a service by another name."
    )


def test_THE_CONTROL_a_human_grantee_is_NOT_refused():
    """Without this, a gate that refused every grantee would satisfy the assertion above while
    making the rail unusable — trading a silent wrong-grant for a rail nobody can use, which is
    how a guard gets deleted rather than fixed."""
    assert service_identity_recipients(
        "task_grants.yaml",
        [("t", "alice@example.com"), ("t", "E12345"), ("t", "carol@example.com")],
    ) == []


def test_THE_PREFIX_IS_THE_ONE_users_yaml_ACTUALLY_USES():
    """THE JOIN. The gate matches a PREFIX; if the roster spelled service identities any other
    way the gate would be green over a file full of them.

    Asserted against users.yaml rather than restated, because a prefix registry that agrees with
    itself and not with the data is the failure this repo has met before.
    """
    body = _USERS.read_text(encoding="utf-8")
    assert f"- id: {SERVICE_SUBJECT_PREFIX}" in body, (
        f"no seeded user id begins with {SERVICE_SUBJECT_PREFIX!r} — the gate matches a prefix "
        f"the roster does not use, and refuses nothing"
    )


def test_THE_REASON_IS_IN_THE_VALIDATOR_not_only_in_a_comment_elsewhere():
    """The point of the ruling: the rule must travel with the rail that enforces it. A reader
    editing the validator must meet the reason without having to open users.yaml."""
    src = _VALIDATOR.read_text(encoding="utf-8")
    assert "confused deputy" in src
    assert "not whose data may be read" in src.lower(), (
        "the validator does not carry the reason, so the next edit to this file has nothing to "
        "weigh the refusal against"
    )


def test_CAPABILITY_GRANTS_ARE_EXEMPT_DELIBERATELY():
    """SCOPE, asserted so the exemption stays a decision rather than an oversight.

    An INVOKE is an EFFECT, not a read. If a capability grant ever conveys disclosure this must
    be revisited — and a reader deciding that should find the exemption stated, not infer it
    from an absence.
    """
    src = _VALIDATOR.read_text(encoding="utf-8")
    assert 'service_identity_recipients("capability_grants.yaml"' not in src, (
        "capability grants were added to the disclosure gate. If that is intended, the "
        "exemption's reasoning in `service_identity_recipients` must be rewritten, not just "
        "the call list."
    )
    assert 'service_identity_recipients("asset_grants.yaml"' in src
    assert 'service_identity_recipients("task_grants.yaml"' in src
    assert 'service_identity_recipients("ontology_compartments.yaml"' in src


def test_THE_GATE_DOES_NOT_DEPEND_ON_THE_ROSTER_PARSING():
    """It asks 'may this KIND of principal receive disclosure', which does not depend on
    users.yaml being readable. Nested inside the `known_users` guard, a broken roster would
    silently disable it — a gate that fails open exactly when the file it protects is damaged."""
    # ⛔ THE FIRST VERSION COMPARED OFFSETS against "the next `return errors`" — which is the
    # FUNCTION's return, sitting after the gate rather than closing the guard. It reported the
    # gate as nested when it is not: my instrument could not see the structure it was asserting
    # about, and answered anyway. Indentation is what actually decides scope here, so read that.
    for ln in _VALIDATOR.read_text(encoding="utf-8").splitlines():
        if 'service_identity_recipients("asset_grants.yaml"' in ln:
            indent = len(ln) - len(ln.lstrip())
            assert indent <= 4, (
                f"the service-identity gate is indented {indent} spaces, so it sits inside the "
                f"`if known_users:` block — a roster that fails to parse disables it silently, "
                f"which is a gate failing open exactly when the file it protects is damaged"
            )
            break
    else:
        raise AssertionError("the asset_grants call to the service-identity gate is gone")
