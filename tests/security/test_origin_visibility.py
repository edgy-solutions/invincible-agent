"""Origin entitlement (architect ruling, 2026-10-02: "ORIGIN, not audience").

An artifact carries `origin = {owner_domain, program}`, set by EVIDENCE (a resolver
out of scope here). A viewer may read it iff `can_consume(viewer's domain role,
origin.owner_domain)` (policy/domain_consumption.yaml) AND
`program_member(viewer, origin.program)` (policy/program_members.yaml, Topaz
`program` `can_view_program`). An artifact with NO recorded origin stays on the
dropper/owner-only path — today's behaviour, unchanged.

Four arms, in order:
  1. iagent.origin — the pure entitlement core (no network, no file IO).
  2. GET /artifacts/{id} — the read path, Neo4j + Topaz monkeypatched.
  3. validate_policy.py — the three new checks, each proved by a POSITIVE control
     (passes on the shipped files) and a NEGATIVE one (fails on a mutated copy).
  4. Mutation proof: a named test above is shown RED against each of three
     mutants (recorded in this module's docstring at the bottom), then the
     mutation is reverted — this is manual verification, not a shipped test.

Run: uv run --frozen pytest tests/security/test_origin_visibility.py -v
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
_SYNC = _ROOT / "policy" / "sync"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from iagent.origin import (  # noqa: E402
    Origin,
    can_consume,
    check_dropper_bound,
    DropperNotProgramMember,
    load_domain_consumption,
    origin_visible,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. iagent.origin — pure entitlement core
# ══════════════════════════════════════════════════════════════════════════════

def test_no_implicit_identity_without_a_row_is_denied():
    """NO IMPLICIT IDENTITY: a domain consuming ITS OWN origin with no asserted row
    is a MISS, not a pass — the row must be explicit in domain_consumption.yaml.
    MUTANT m1 (can_consume returns True when owner_domain == any viewer domain
    without a row) turns this test red."""
    assert can_consume(["AVIATION"], "AVIATION", {}) is False


def test_cross_domain_allowed_only_with_an_explicit_row():
    table = {"AVIATION": frozenset({"DEFENSE"})}
    assert can_consume(["AVIATION"], "DEFENSE", table) is True
    assert can_consume(["AVIATION"], "DEFENSE", {}) is False
    assert can_consume(["AVIATION"], "ENTERPRISE", table) is False


def test_program_non_member_is_not_visible_even_with_consumption():
    """Both conjuncts must hold. A viewer who can_consume the owner_domain but is
    NOT a program member must still be denied. MUTANT m2 (origin_visible drops the
    program-member conjunct) turns this test red."""
    table = {"AVIATION": frozenset({"AVIATION"})}
    origin = Origin(owner_domain="AVIATION", program="SANDBOX_PROGRAM_ALPHA", obtained_via="evidence")
    assert origin_visible(
        viewer_domains=["AVIATION"], is_program_member=False, origin=origin, table=table,
    ) is False


def test_program_member_and_consumption_together_is_visible():
    table = {"AVIATION": frozenset({"AVIATION"})}
    origin = Origin(owner_domain="AVIATION", program="SANDBOX_PROGRAM_ALPHA", obtained_via="evidence")
    assert origin_visible(
        viewer_domains=["AVIATION"], is_program_member=True, origin=origin, table=table,
    ) is True


def test_unresolved_origin_is_never_visible_by_this_path():
    """origin=None (unresolved) is the dropper/owner-only artifact — this function
    is not the grant for it, under any viewer/membership combination."""
    assert origin_visible(
        viewer_domains=["AVIATION"], is_program_member=True, origin=None, table={},
    ) is False


def test_dropper_bound_raises_when_dropper_is_not_a_member():
    origin = Origin(owner_domain="AVIATION", program="SANDBOX_PROGRAM_ALPHA", obtained_via="evidence")
    with pytest.raises(DropperNotProgramMember):
        check_dropper_bound(False, origin)


def test_dropper_bound_is_a_noop_when_dropper_is_a_member():
    origin = Origin(owner_domain="AVIATION", program="SANDBOX_PROGRAM_ALPHA", obtained_via="evidence")
    assert check_dropper_bound(True, origin) is None


def test_load_domain_consumption_builds_the_table_from_the_shipped_file():
    raw = yaml.safe_load((_ROOT / "policy" / "domain_consumption.yaml").read_text(encoding="utf-8"))
    table = load_domain_consumption(raw)
    assert "AVIATION" in table
    assert "AVIATION" in table["AVIATION"], "the shipped sandbox row is an identity row"


# ══════════════════════════════════════════════════════════════════════════════
# 2. GET /artifacts/{id} — the read path (Neo4j + Topaz monkeypatched)
# ══════════════════════════════════════════════════════════════════════════════

class _Entitled:
    def __init__(self, domains):
        self.cells = [_Cell(d) for d in domains]


class _Cell:
    def __init__(self, domain):
        self.domain = domain


class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = "bob@example.com"
    email = "bob@example.com"

    def __init__(self, domains=("AVIATION",)):
        self.entitlements = _Entitled(domains)


def _row(**over):
    base = {
        "id": "artifact-1", "status": "complete", "summary": "s", "question_text": "q",
        "valid_as_of": 1, "duration_ms": 1, "derived_from": None, "is_owner": False,
        "resolved_intent": None, "routing_inline": None,
        "origin_owner_domain": None, "origin_program": None,
    }
    base.update(over)
    return base


@pytest.fixture()
def read(monkeypatch):
    """Call the REAL route with Neo4j and Topaz faked — the transport, not the logic."""
    import iagent.gateway as gw

    def _make(row):
        class _Res:
            def single(self_inner):
                return row

        class _Sess:
            def run(self_inner, cypher, **params):
                return _Res()

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        class _Drv:
            def session(self_inner):
                return _Sess()

        return _Drv()

    async def _go(row, *, user=None, can_view_program=True, table=None, topaz_raises=False):
        monkeypatch.setattr(gw, "neo4j_driver", _make(row))

        import iagent.human_tasks as human_tasks_mod

        def _check(program, caller_id):
            if topaz_raises:
                raise RuntimeError("topaz unreachable")
            return can_view_program

        monkeypatch.setattr(human_tasks_mod, "check_can_view_program", _check)
        monkeypatch.setattr(
            gw, "_load_domain_consumption_table",
            lambda: table if table is not None else {},
        )
        return await gw.get_artifact("artifact-1", user or _User())

    return _go


@pytest.mark.asyncio
async def test_owner_reads_unchanged_even_when_origin_is_recorded(read):
    """Owner path is untouched by this feature — `is_owner` short-circuits before
    origin is ever consulted."""
    out = await read(_row(is_owner=True, origin_owner_domain="DEFENSE", origin_program="OTHER_PROGRAM"))
    assert out.id == "artifact-1"


@pytest.mark.asyncio
async def test_non_owner_with_origin_and_both_checks_true_reads_200(read):
    row = _row(origin_owner_domain="AVIATION", origin_program="SANDBOX_PROGRAM_ALPHA")
    out = await read(
        row, user=_User(("AVIATION",)), can_view_program=True,
        table={"AVIATION": frozenset({"AVIATION"})},
    )
    assert out.id == "artifact-1"


@pytest.mark.asyncio
async def test_non_owner_denied_when_not_a_program_member(read):
    from fastapi import HTTPException

    row = _row(origin_owner_domain="AVIATION", origin_program="SANDBOX_PROGRAM_ALPHA")
    with pytest.raises(HTTPException) as exc:
        await read(
            row, user=_User(("AVIATION",)), can_view_program=False,
            table={"AVIATION": frozenset({"AVIATION"})},
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_non_owner_denied_when_cannot_consume_the_origin_domain(read):
    from fastapi import HTTPException

    row = _row(origin_owner_domain="AVIATION", origin_program="SANDBOX_PROGRAM_ALPHA")
    with pytest.raises(HTTPException) as exc:
        await read(
            row, user=_User(("ENTERPRISE",)), can_view_program=True,
            table={"AVIATION": frozenset({"AVIATION"})},  # ENTERPRISE has no row
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_non_owner_with_no_recorded_origin_stays_404():
    """No origin props at all (today's artifacts) — the dropper/owner-only path,
    unaffected by this feature; no Topaz call should even be needed.
    MUTANT m3 (the read path treats missing origin props as visible) turns this
    test red."""
    import iagent.gateway as gw
    from fastapi import HTTPException

    class _Res:
        def single(self_inner):
            return _row(origin_owner_domain=None, origin_program=None)

    class _Sess:
        def run(self_inner, cypher, **params):
            return _Res()

        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

    class _Drv:
        def session(self_inner):
            return _Sess()

    mp = pytest.MonkeyPatch()
    mp.setattr(gw, "neo4j_driver", _Drv())
    try:
        with pytest.raises(HTTPException) as exc:
            await gw.get_artifact("artifact-1", _User(("AVIATION",)))
        assert exc.value.status_code == 404
    finally:
        mp.undo()


@pytest.mark.asyncio
async def test_topaz_down_fails_closed_with_503_not_404(read):
    """"Could not tell" must not collapse into the same 404 a real deny produces —
    the same distinction get_current_user already draws for the entitlement matrix
    itself (auth.py's AuthorizationUnavailable -> 503)."""
    from fastapi import HTTPException

    row = _row(origin_owner_domain="AVIATION", origin_program="SANDBOX_PROGRAM_ALPHA")
    with pytest.raises(HTTPException) as exc:
        await read(
            row, user=_User(("AVIATION",)), topaz_raises=True,
            table={"AVIATION": frozenset({"AVIATION"})},
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_topaz_down_is_still_404_for_a_caller_the_table_already_refuses(read):
    """No existence oracle through an outage: a caller whose domains cannot consume the
    origin is refused by the pure table check BEFORE Topaz is asked, so an existing
    artifact answers 404 exactly as a missing one does, Topaz up or down. Same row and
    same outage as the 503 arm above; the only difference is the table."""
    from fastapi import HTTPException

    row = _row(origin_owner_domain="AVIATION", origin_program="SANDBOX_PROGRAM_ALPHA")
    with pytest.raises(HTTPException) as exc:
        await read(row, user=_User(("AVIATION",)), topaz_raises=True, table={})
    assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 3. validate_policy.py — the three new checks (positive on shipped, negative on
#    a mutated copy)
# ══════════════════════════════════════════════════════════════════════════════

from validate_policy import validate  # noqa: E402

_POLICY_DIR = _ROOT / "policy"


def _copy_policy(tmp_path: Path) -> Path:
    dest = tmp_path / "policy"
    shutil.copytree(_POLICY_DIR, dest)
    return dest


def test_shipped_policy_has_no_domain_consumption_or_program_member_errors():
    errors = validate(_POLICY_DIR, _POLICY_DIR)
    assert not any("domain_consumption.yaml" in e for e in errors), errors
    assert not any("program_members.yaml" in e for e in errors), errors


# (a) every domain in domain_consumption.yaml exists in domains.yaml
def test_unknown_origin_domain_in_domain_consumption_is_refused(tmp_path):
    policy_dir = _copy_policy(tmp_path)
    dc_path = policy_dir / "domain_consumption.yaml"
    doc = yaml.safe_load(dc_path.read_text(encoding="utf-8"))
    doc["domain_consumption"]["AVIATION"]["allowed_origins"] = ["NOT_A_REAL_DOMAIN"]
    dc_path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    errors = validate(policy_dir, policy_dir)
    assert any("NOT_A_REAL_DOMAIN" in e and "domain_consumption.yaml" in e for e in errors), errors


# (b) every grantee email in program_members.yaml exists in users.yaml
def test_unknown_grantee_in_program_members_is_refused(tmp_path):
    policy_dir = _copy_policy(tmp_path)
    pm_path = policy_dir / "program_members.yaml"
    doc = yaml.safe_load(pm_path.read_text(encoding="utf-8"))
    doc["programs"]["SANDBOX_PROGRAM_ALPHA"]["grant_to"] = ["nobody@example.com"]
    pm_path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    errors = validate(policy_dir, policy_dir)
    assert any("nobody@example.com" in e and "program_members.yaml" in e for e in errors), errors


# (c) required fields present (both files)
def test_domain_consumption_row_missing_granted_by_is_refused(tmp_path):
    policy_dir = _copy_policy(tmp_path)
    dc_path = policy_dir / "domain_consumption.yaml"
    doc = yaml.safe_load(dc_path.read_text(encoding="utf-8"))
    del doc["domain_consumption"]["AVIATION"]["granted_by"]
    dc_path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    errors = validate(policy_dir, policy_dir)
    assert any(
        "domain_consumption.yaml" in e and "granted_by" in e for e in errors
    ), errors


def test_program_members_missing_reason_is_refused(tmp_path):
    policy_dir = _copy_policy(tmp_path)
    pm_path = policy_dir / "program_members.yaml"
    doc = yaml.safe_load(pm_path.read_text(encoding="utf-8"))
    del doc["programs"]["SANDBOX_PROGRAM_ALPHA"]["reason"]
    pm_path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    errors = validate(policy_dir, policy_dir)
    assert any(
        "program_members.yaml" in e and "reason" in e for e in errors
    ), errors


# ADR-0047 §5.1: a svc: principal must never be a program member
def test_service_identity_recipient_in_program_members_is_refused(tmp_path):
    policy_dir = _copy_policy(tmp_path)
    pm_path = policy_dir / "program_members.yaml"
    doc = yaml.safe_load(pm_path.read_text(encoding="utf-8"))
    doc["programs"]["SANDBOX_PROGRAM_ALPHA"]["grant_to"] = ["svc:cost-agent"]
    pm_path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    errors = validate(policy_dir, policy_dir)
    assert any("svc:" in e and "program_members.yaml" in e for e in errors), errors


# ══════════════════════════════════════════════════════════════════════════════
# 4. Mutation proof (manual — recorded here, not re-run by this suite)
# ══════════════════════════════════════════════════════════════════════════════
#
# m1 — src/iagent/origin.py `can_consume`: made it `return True` immediately when
#      `owner_domain in viewer_domains`, bypassing `table` entirely (implicit
#      identity). RED: test_no_implicit_identity_without_a_row_is_denied.
#      Reverted; file matches the version above again.
#
# m2 — src/iagent/origin.py `origin_visible`: removed the
#      `if not is_program_member: return False` line, so only can_consume gated
#      the result. RED: test_program_non_member_is_not_visible_even_with_
#      consumption. Reverted.
#
# m3 — src/iagent/gateway.py `_origin_visible_to_caller`: changed the early guard
#      from `if not owner_domain or not program: return False` to
#      `if not owner_domain or not program: return True`. RED:
#      test_non_owner_with_no_recorded_origin_stays_404. Reverted.
