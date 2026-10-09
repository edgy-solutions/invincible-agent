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
              must have a `domain_consumption` row naming ITSELF (no implicit identity), and must
              have a `document_promotion:<DOMAIN>` audience grant, else the kind's task or
              artifacts are unreachable by anyone.
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
for _p in (_ROOT / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

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

def _reachability_problems(kind, domain, domains, consumption, audiences):
    dom = domain.upper()
    out = []
    if dom not in domains:
        out.append(f"{kind}: {dom} is not in policy/domains.yaml")
    if dom not in ((consumption.get(dom) or {}).get("allowed_origins") or []):
        out.append(f"{kind}: no domain_consumption row lets {dom} read an artifact whose origin is "
                   f"{dom} (no implicit identity)")
    if not (audiences.get(f"document_promotion:{dom}") or {}).get("grant_to"):
        out.append(f"{kind}: no document_promotion:{dom} grant -- the task has no recipient")
    return out


@pytest.mark.parametrize("reg", _BY_BUCKET.get("domained", []), ids=_ids(_BY_BUCKET.get("domained", [])))
def test_a_domained_kinds_domain_is_declared_consumable_by_itself_and_has_a_reviewer(reg):
    assert _reachability_problems(reg.kind, reg.domain, _DECLARED_DOMAINS, _CONSUMPTION, _AUDIENCES) == []


@pytest.mark.parametrize("missing", ["domains", "consumption", "audiences"])
def test_the_reachability_check_fails_when_each_source_loses_the_domain(missing):
    """Control: the SAME predicate, same kind, with exactly one source emptied -> exactly that
    source's problem appears. Proves each of the three clauses can fire."""
    reg = _BY_BUCKET["domained"][0]
    args = dict(domains=_DECLARED_DOMAINS, consumption=_CONSUMPTION, audiences=_AUDIENCES)
    args[missing] = set() if missing == "domains" else {}
    got = _reachability_problems(reg.kind, reg.domain, **args)
    assert len(got) == 1, got


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
    {"origin_owner_domain": "MAINTENANCE", "origin_program": None},
    {"origin_owner_domain": None, "origin_program": "SANDBOX_PROGRAM_ALPHA"},
    {"origin_owner_domain": "  ", "origin_program": "SANDBOX_PROGRAM_ALPHA"},
], ids=["both-null", "absent", "no-program", "no-domain", "blank-domain"])
async def test_an_awaiting_origin_artifact_is_never_visible_by_origin_and_never_asks_topaz(route, reg, rec):
    """A domainless kind's artifact has no origin until evidence resolves one. Every viewer leg is
    set to TRUE (best-case viewer) and the answer is still False, with Topaz untouched -- half an
    origin (a domain without a program, or the reverse) is no origin."""
    got = await route(rec, domains=tuple(_CONSUMPTION), member=True)
    assert got is False
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
