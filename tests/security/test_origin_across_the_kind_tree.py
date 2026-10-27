"""The origin entitlement across the content-kind tree (lane/gov).

    entitlement = can_consume(domain_role, origin_domain) AND program_member

`test_origin_visibility.py` seals the conjunction for ONE hand-picked origin. This file seals it
for EVERY kind the deployment registers, with the population DERIVED from the registry rows
(`policy/content_kinds/` + `policy/overlays/*/content_kinds/`), so a kind added tomorrow is
covered -- or fails here -- without anyone remembering to list it.

Each registered kind falls in exactly one bucket, decided from the row itself:

  event       `branch: event` -- never reaches the stage route's review step (no bytes, no
              promotion task); exempt, and the reason is the row's own `branch`.
  domainless  `domain: null` written EXPLICITLY (`model_fields_set`) -- the stage route sends it to
              `awaiting_origin`; nothing may be consumable by KIND, only by recorded origin.
  domained    a document kind with a domain -- its (UPPERCASED) domain must be a declared domain,
              must have a `domain_consumption` row naming ITSELF (no implicit identity), and its
              `document_promotion:<DOMAIN>` audience must reach at least one RECIPIENT, else the
              kind's task or artifacts are unreachable by anyone. A recipient is a `grant_to`
              user, or a MEMBER of a `grant_to_groups` group (group -> members, the 2026-10-10
              group-audience form). A group with no member in users.yaml reaches nobody; that
              is the predicate `validate_policy.unusable_group_audiences` refuses, and an arm
              here pins the two to the same answer.
  undecided   anything else (a document kind with the domain key OMITTED). MUST FAIL: the stage
              route answers it 422 `no_declared_domain`, so it is a defect, not a bucket.

Controls differ in exactly ONE leg: for every domained kind the four (consume, member) cells are
run against the REAL route helper, and only (True, True) is visible; a Topaz outage on a caller the
table already admits is 503, never an allow and never a silent deny.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT / "policy" / "sync"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validate_policy import unusable_group_audiences  # noqa: E402

_POLICY = _ROOT / "policy"
_SEED = _POLICY / "content_kinds"
_OVERLAYS = sorted(p for p in (_POLICY / "overlays").glob("*/content_kinds") if p.is_dir())


def _registrations():
    from iagent_mesh.ingest import compose

    rows = []
    for overlay in _OVERLAYS:
        rows.extend(compose(_SEED, [str(overlay)]))
    return tuple(rows)


def _bucket(reg) -> str:
    if getattr(reg, "branch", "document") == "event":
        return "event"
    if reg.domain:
        return "domained"
    if "domain" in reg.model_fields_set and reg.domain is None:
        return "domainless"
    return "undecided"


_REGS = _registrations()
_BY_BUCKET: dict[str, list] = {}
for _r in _REGS:
    _BY_BUCKET.setdefault(_bucket(_r), []).append(_r)

_DECLARED_DOMAINS = {str(d) for d in yaml.safe_load((_POLICY / "domains.yaml").read_text())["domains"]}
_CONSUMPTION = yaml.safe_load((_POLICY / "domain_consumption.yaml").read_text())["domain_consumption"]
_AUDIENCES = yaml.safe_load((_POLICY / "task_grants.yaml").read_text())["audiences"]
_GROUPS = yaml.safe_load((_POLICY / "groups.yaml").read_text(encoding="utf-8"))["groups"]
_USERS = yaml.safe_load((_POLICY / "users.yaml").read_text(encoding="utf-8"))["users"]


def _ids(regs):
    return [r.kind for r in regs]


# ── the population ────────────────────────────────────────────────────────────

def test_the_population_is_non_empty_and_every_row_has_a_bucket():
    assert _OVERLAYS, "no policy/overlays/*/content_kinds directory found -- the population is empty"
    assert _REGS, "the registry composed to zero kinds"
    assert set(_BY_BUCKET) <= {"event", "domained", "domainless", "undecided"}
    # Both document-side buckets are populated today; if one empties, the parametrised arms below
    # would silently collect nothing, which is exactly what this guards.
    assert _BY_BUCKET.get("domained"), "no domained document kind in any overlay"
    assert _BY_BUCKET.get("domainless"), "no deliberately domainless kind in any overlay"


def test_no_registered_kind_is_undecided():
    """A document kind that OMITS `domain` is neither domained nor deliberately domainless.
    The stage route refuses it 422 `no_declared_domain`; the registry must not ship one."""
    bad = _ids(_BY_BUCKET.get("undecided", []))
    assert not bad, f"kinds with no `domain` key at all (write `domain: null` or a domain): {bad}"


def test_the_bucketing_itself_discriminates_the_four_cases():
    """Positive control for `_bucket`: build one registration of each shape and see each land in
    its own bucket -- including the omitted-key case, which `reg.domain is None` alone cannot tell
    from an explicit null."""
    from iagent_mesh.ingest import ContentKindRegistration as R

    base = {"kind": "k", "passes": ["identity.document_identity"], "outputs": ["mesh:PDFArtifact"]}
    assert _bucket(R(**base, domain="x")) == "domained"
    assert _bucket(R(**base, domain=None)) == "domainless"
    assert _bucket(R(**base)) == "undecided"
    assert _bucket(R(kind="e", branch="event", domain="x", seeds_workflow="w",
                     identity_field="f")) == "event"


# ── domained kinds: the domain is reachable ───────────────────────────────────

def _members(group, groups, users) -> set[str]:
    """group -> members: the users.yaml ids listing `group`, for a group groups.yaml declares."""
    if group not in (groups or {}):
        return set()
    return {str(u.get("id")) for u in users or [] if isinstance(u, dict)
            and group in (u.get("groups") or [])}


def _recipients(audience, groups, users) -> set[str]:
    """Everyone a task audience reaches: its `grant_to` users, plus the members of each of its
    `grant_to_groups` groups."""
    audience = audience or {}
    out = {str(g) for g in audience.get("grant_to") or []}
    for g in audience.get("grant_to_groups") or []:
        out |= _members(str(g), groups, users)
    return out


def _reachability_problems(kind, domain, domains, consumption, audiences, groups, users):
    dom = domain.upper()
    out = []
    if dom not in domains:
        out.append(f"{kind}: {dom} is not in policy/domains.yaml")
    if dom not in ((consumption.get(dom) or {}).get("allowed_origins") or []):
        out.append(f"{kind}: no domain_consumption row lets {dom} read an artifact whose origin is "
                   f"{dom} (no implicit identity)")
    if not _recipients(audiences.get(f"document_promotion:{dom}"), groups, users):
        out.append(f"{kind}: document_promotion:{dom} reaches no recipient (no grant_to user and "
                   f"no member of a grant_to_groups group) -- the task is visible to nobody")
    return out


_SOURCES = dict(domains=_DECLARED_DOMAINS, consumption=_CONSUMPTION, audiences=_AUDIENCES,
                groups=_GROUPS, users=_USERS)


@pytest.mark.parametrize("reg", _BY_BUCKET.get("domained", []), ids=_ids(_BY_BUCKET.get("domained", [])))
def test_a_domained_kinds_domain_is_declared_consumable_by_itself_and_has_a_reviewer(reg):
    assert _reachability_problems(reg.kind, reg.domain, **_SOURCES) == []


@pytest.mark.parametrize("missing", ["domains", "consumption", "audiences"])
def test_the_reachability_check_fails_when_each_source_loses_the_domain(missing):
    """Control: the SAME predicate, same kind, with exactly one source emptied -> exactly that
    source's problem appears. Proves each of the three clauses can fire."""
    reg = _BY_BUCKET["domained"][0]
    args = dict(_SOURCES)
    args[missing] = set() if missing == "domains" else {}
    got = _reachability_problems(reg.kind, reg.domain, **args)
    assert len(got) == 1, got


# ── a group grant reaches its members ─────────────────────────────────────────

_G_GROUPS = {"stewards": {}, "empty-group": {}}
_G_USERS = [{"id": "bob@example.com", "groups": ["stewards"]},
            {"id": "carol@example.com", "groups": ["ghost"]}]


@pytest.mark.parametrize("audience, reaches", [
    ({"grant_to": ["bob@example.com"]}, {"bob@example.com"}),
    ({"grant_to_groups": ["stewards"]}, {"bob@example.com"}),
    ({"grant_to": [], "grant_to_groups": ["stewards"]}, {"bob@example.com"}),
    ({"grant_to_groups": ["empty-group"]}, set()),  # declared, no member: reaches nobody
    ({"grant_to_groups": ["ghost"]}, set()),  # a member lists it, groups.yaml does not
    ({"grant_to": [], "grant_to_groups": []}, set()),
    (None, set()),
], ids=["user", "group", "group-beside-empty-users", "memberless-group", "undeclared-group",
        "both-empty", "no-audience"])
def test_a_group_grant_counts_as_a_recipient_through_its_members(audience, reaches):
    """Two-sided: a group with a member is a recipient; a declared group with no member, or a
    group groups.yaml does not declare, is not. The domain clauses pass, so the only thing that
    differs between the rows is who the audience reaches."""
    assert _recipients(audience, _G_GROUPS, _G_USERS) == reaches
    got = _reachability_problems(
        "k", "d", {"D"}, {"D": {"allowed_origins": ["D"]}},
        {} if audience is None else {"document_promotion:D": audience}, _G_GROUPS, _G_USERS)
    assert len(got) == (0 if reaches else 1), got


def _join(names, groups, users) -> dict[str, tuple[bool, bool]]:
    """group -> (validate_policy refuses it, this file finds it memberless)."""
    from types import SimpleNamespace
    return {g: (bool(unusable_group_audiences(
                [SimpleNamespace(key=f"probe:{g}", grant_to=(), grant_to_groups=(g,))], groups, users)),
                not _members(g, groups, users)) for g in sorted(names)}


def test_a_groups_members_agree_with_what_validate_policy_refuses():
    """THE JOIN. This file's group -> members is empty exactly when `unusable_group_audiences`
    refuses the group, so a drift between the two answers reds here, not in a walk. It is
    decided over two populations:
      - the real policy: every group groups.yaml declares and every group an audience grants.
        Today all of them are usable, so this half alone only ever compares "fine" with "fine";
      - the fixture, which holds one group of each outcome (a member, declared but memberless,
        listed by a user but undeclared). That half is what makes a disagreement observable."""
    real = set(_GROUPS) | {str(g) for a in _AUDIENCES.values() for g in (a or {}).get(
        "grant_to_groups") or []}
    assert any((a or {}).get("grant_to_groups") for a in _AUDIENCES.values()), (
        "no audience grants a group: the join has nothing to compare")
    fixture = _join({"stewards", "empty-group", "ghost"}, _G_GROUPS, _G_USERS)
    assert {r for r, _ in fixture.values()} == {True, False}, fixture  # both outcomes occur
    for g, (refused, memberless) in {**_join(real, _GROUPS, _USERS), **{
            f"fixture:{k}": v for k, v in fixture.items()}}.items():
        assert refused == memberless, g


def test_every_document_promotion_audience_reaches_a_recipient():
    """Every `document_promotion:<DOMAIN>` audience the policy declares, whether or not a
    registered kind uses it yet, reaches someone. That includes the 2026-10-14 MANUFACTURING
    grant, which reaches its stewards only through a group."""
    keys = [k for k in _AUDIENCES if k.startswith("document_promotion:")]
    assert keys
    assert {k: sorted(_recipients(_AUDIENCES[k], _GROUPS, _USERS)) for k in keys
            if not _recipients(_AUDIENCES[k], _GROUPS, _USERS)} == {}
    assert any((_AUDIENCES[k] or {}).get("grant_to_groups") and not (_AUDIENCES[k] or {}).get(
        "grant_to") for k in keys), "no document_promotion audience is group-only: the group " \
        "path is not exercised by real policy"


# ── the conjunction, per domained kind, one leg at a time ─────────────────────

class _Cell:
    def __init__(self, d):
        self.domain = d


class _User:
    authz_id = "viewer@example.com"

    def __init__(self, domains):
        self.entitlements = type("E", (), {"cells": [_Cell(d) for d in domains]})()


@pytest.fixture()
def route(monkeypatch):
    import iagent.gateway as gw
    import iagent.human_tasks as ht

    table = {k: frozenset(v.get("allowed_origins") or []) for k, v in _CONSUMPTION.items()}
    calls: list = []

    def _go(rec, *, domains, member=True, topaz_raises=False):
        def _check(program, caller):
            calls.append((program, caller))
            if topaz_raises:
                raise RuntimeError("topaz unreachable")
            return member

        monkeypatch.setattr(ht, "check_can_view_program", _check)
        monkeypatch.setattr(gw, "_load_domain_consumption_table", lambda: table)
        return gw._origin_visible_to_caller(rec, _User(domains))

    _go.calls = calls
    return _go


def _rec(dom):
    return {"origin_owner_domain": dom, "origin_program": "SANDBOX_PROGRAM_ALPHA"}


_DOMAINED = _BY_BUCKET.get("domained", [])


@pytest.mark.asyncio
@pytest.mark.parametrize("reg", _DOMAINED, ids=_ids(_DOMAINED))
@pytest.mark.parametrize("consumes", [True, False])
@pytest.mark.parametrize("member", [True, False])
async def test_only_both_legs_true_is_visible(route, reg, consumes, member):
    dom = reg.domain.upper()
    # A viewer domain with a row for `dom` (itself) vs one with no row at all.
    domains = (dom,) if consumes else ("DOMAIN_WITH_NO_ROW",)
    got = await route(_rec(dom), domains=domains, member=member)
    assert got is (consumes and member), (reg.kind, consumes, member)
    if not consumes:
        assert route.calls == [], "the pure leg must refuse BEFORE Topaz is asked (no 503 oracle)"


@pytest.mark.asyncio
@pytest.mark.parametrize("reg", _DOMAINED, ids=_ids(_DOMAINED))
async def test_a_topaz_outage_is_503_for_an_admitted_caller_and_never_an_allow(route, reg):
    from fastapi import HTTPException

    dom = reg.domain.upper()
    with pytest.raises(HTTPException) as exc:
        await route(_rec(dom), domains=(dom,), topaz_raises=True)
    assert exc.value.status_code == 503
    # control, one leg different: the same outage for a caller the table refuses is a plain deny.
    assert await route(_rec(dom), domains=("DOMAIN_WITH_NO_ROW",), topaz_raises=True) is False


# ── awaiting_origin: no origin, no consumption by kind ────────────────────────

_DOMAINLESS = _BY_BUCKET.get("domainless", [])


@pytest.mark.asyncio
@pytest.mark.parametrize("reg", _DOMAINLESS, ids=_ids(_DOMAINLESS))
@pytest.mark.parametrize("rec", [
    {"origin_owner_domain": None, "origin_program": None},
    {},
    {"origin_owner_domain": None, "origin_program": "SANDBOX_PROGRAM_ALPHA"},
    {"origin_owner_domain": "  ", "origin_program": "SANDBOX_PROGRAM_ALPHA"},
], ids=["both-null", "absent", "no-domain", "blank-domain"])
async def test_an_awaiting_origin_artifact_is_never_visible_by_origin_and_never_asks_topaz(route, reg, rec):
    """A domainless kind's artifact has no origin until evidence resolves one. Every viewer leg is
    set to TRUE (best-case viewer) and the answer is still False, with Topaz untouched -- a program
    with no domain is no origin. (A domain with NO program is NOT half an origin: it is a steward
    attestation, decided by can_consume alone -- Q1 ruling 2026-10-10; see the arm below.)"""
    got = await route(rec, domains=tuple(_CONSUMPTION), member=True)
    assert got is False
    assert route.calls == []


_STEWARD_REC = {"origin_owner_domain": "MAINTENANCE", "origin_program": None}


@pytest.mark.asyncio
async def test_a_program_less_origin_is_a_steward_attestation_decided_by_consumption_alone(route):
    """Q1 ruling 2026-10-10: a recorded domain with no program is visible to a viewer whose
    domains can consume it, and Topaz is NOT asked."""
    assert await route(_STEWARD_REC, domains=tuple(_CONSUMPTION), member=False) is True
    assert route.calls == []


@pytest.mark.asyncio
async def test_control_a_program_less_origin_is_still_refused_to_a_non_consumer(route):
    """Differs from the arm above in exactly one thing: the viewer's domains cannot consume it."""
    assert await route(_STEWARD_REC, domains=("DOMAIN_WITH_NO_ROW",), member=False) is False
    assert route.calls == []


@pytest.mark.asyncio
async def test_control_the_same_best_case_viewer_sees_it_once_an_origin_is_recorded(route):
    """Differs from the arm above in exactly one thing: the origin is now recorded."""
    dom = next(iter(_CONSUMPTION))
    assert await route(_rec(dom), domains=(dom,), member=True) is True


# ── the pure core's own conjunction (the route pre-checks the consume leg, so a mutant that
#    drops it from `origin_visible` is invisible to the route arms above) ────────────────────

@pytest.mark.parametrize("reg", _DOMAINED, ids=_ids(_DOMAINED))
@pytest.mark.parametrize("consumes", [True, False])
@pytest.mark.parametrize("member", [True, False])
def test_origin_visible_is_the_conjunction_of_its_two_legs(reg, consumes, member):
    from iagent.origin import Origin, origin_visible

    dom = reg.domain.upper()
    table = {k: frozenset(v.get("allowed_origins") or []) for k, v in _CONSUMPTION.items()}
    got = origin_visible(
        viewer_domains=(dom,) if consumes else ("DOMAIN_WITH_NO_ROW",),
        is_program_member=member,
        origin=Origin(owner_domain=dom, program="SANDBOX_PROGRAM_ALPHA", obtained_via="recorded"),
        table=table,
    )
    assert got is (consumes and member)
