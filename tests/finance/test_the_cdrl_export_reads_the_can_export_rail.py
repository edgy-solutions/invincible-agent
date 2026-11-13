"""The CDRL export and its listing read the `can_export` rail, deny by default: one rail, not dead rows.

`policy/capability_grants.yaml` carried `can_export:<profile>` rows for fin's CDRL profiles, and
`/cdrl_export` read none of them: any program member holding the cells could produce any profile.
The rail is engine-cost's (`utils.export_capability.can_export`, `capability_grants`,
`can_export:<profile name>`, relation `can_invoke`), and so is the refusal.

Arms:
  a  granted: the file is built, and the rail was asked for THIS profile and THIS caller.
  b  THE CONTROL: the same world with the rail answering no. 403 `not_entitled_to_export` with the
     compliant envelope, and nothing measured, built or written. It differs from (a) only in the
     rail's answer.
  c  the rail is keyed per profile: a caller granted one profile is refused another.
  d  a rail that cannot be asked is a 503 `can_export_unavailable`, never a deny and never a file.
  e  deny by default, through the REAL `can_export`: no directory configured is a 403, and against a
     directory double the wire request is the capability check and a 404 ("no such object") is a 403.
  f  order: an unknown profile (404) and a non-member (403 `program_not_visible`) are refused before
     the rail is asked, as engine-cost asks its reader rail before `can_export`.
  g  the join: every CDRL profile the sandbox serves has a `can_export` row, so none of them is
     exportable by nobody.

`/cdrl_profiles` lists only what the caller may export (the review export's rule, the BFF's
`/ingest/export/profiles`), by `_cdrl_may_export`, the predicate the export refuses on:
  h  the listing is the profiles the rail grants THIS caller, asked per profile as this caller.
  i  THE CONTROL: the same world with the rail granting nothing lists nothing, and granting every
     profile lists every profile.
  j  the offer equals what the export builds: listed if and only if the export is not refused.
  k  a service caller, or no caller, is listed nothing, and the rail is never asked.
  l  a rail that cannot be asked is a 503, never an empty list.
  m  deny by default through the real `can_export`: no directory configured lists nothing.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. tests/finance/test_the_cdrl_export_reads_the_can_export_rail.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import cdrl, export_profiles, seed  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402

SAMPLE = REPO / "policy" / "overlays" / "sample" / "fin_export_profiles"
GRANTS = REPO / "policy" / "capability_grants.yaml"
PROGRAM = seed.PROGRAM_ID
ALICE, BOB = "alice@example.com", "bob@example.com"
PROFILE = "cdrl_a001_ev_summary"
OTHER = "cdrl_a001_ev_summary_json"


def _not_entitled(profile: str) -> dict:
    return {
        "error": "not_entitled_to_export",
        "refusal": {
            "policy_id": f"capability_grants:can_export:{profile}",
            "missing_binding": f"can_invoke can_export:{profile}",
            "candidates": [],
        },
        "message": f"You are not entitled to export {profile}.",
    }


class Members:
    """`can_view_program`: ALICE is on the program, BOB is not."""

    def __call__(self, program, caller_id, **kw):
        return (program, caller_id) == (PROGRAM, ALICE)


class Rail:
    """`can_export`: grants exactly the `(profile, caller)` pairs it is given, records every ask, and
    raises `raises` when set (the rail cannot be asked)."""

    def __init__(self, grants=(), raises=None):
        self.grants = set(grants)
        self.raises = raises
        self.calls = []

    def __call__(self, profile_name, caller_id, **kw):
        self.calls.append((profile_name, caller_id))
        if self.raises is not None:
            raise self.raises
        return (profile_name, caller_id) in self.grants


@pytest.fixture
def profiles(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(REPO / "policy/overlays/sample/measure_verbs"))
    declared = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", declared)
    monkeypatch.setitem(engine.VERB_TO_FN, "mesh:finToCompletePerformanceIndex", "fin_tcpi")
    monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(SAMPLE))
    p = {x.name: x for x in export_profiles.load_export_profiles(declared=declared)}
    monkeypatch.setattr(engine, "PROFILES", p)
    return p


@pytest.fixture
def world(profiles, monkeypatch, tmp_path):
    """The engine with ALICE on the program, the artifact directory under tmp_path, and spies on
    the build and on every source measured. Each arm installs its own rail."""
    monkeypatch.setattr(engine, "can_view_program", Members())
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(engine, "_repo_root", lambda: root)
    built, ran = [], []
    real_build, real_measure = cdrl.build_cdrl, engine._measure_envelope
    monkeypatch.setattr(cdrl, "build_cdrl", lambda *a, **k: (built.append(1), real_build(*a, **k))[1])
    monkeypatch.setattr(engine, "_measure_envelope", lambda *a, **k: (ran.append(1), real_measure(*a, **k))[1])

    def rail(r):
        monkeypatch.setattr(engine, "can_export", r)
        return r

    with TestClient(engine.app) as c:
        yield c, root / "dist", built, ran, rail


def _post(c, profile=PROFILE, user=ALICE):
    return c.post("/cdrl_export", json={"profile": profile, "program_id": PROGRAM, "user_email": user})


def _nothing_made(dist, built, ran):
    assert not built and not ran, "the rail was asked after a source was measured or the file built"
    assert not dist.exists() or not list(dist.iterdir()), "a refused export wrote a file"


# -- a / b: the arm and its control differ only in the rail's answer --------------------------------

def test_a_a_granted_caller_gets_the_file_and_the_rail_was_asked_for_this_profile_and_caller(world):
    c, dist, built, ran, rail = world
    r = rail(Rail(grants={(PROFILE, ALICE)}))
    resp = _post(c)
    assert resp.status_code == 200, resp.text
    assert (dist / resp.json()["artifact_filename"]).is_file()
    assert built and ran
    assert r.calls == [(PROFILE, ALICE)]


def test_b_the_control_a_caller_the_rail_does_not_grant_is_refused_and_nothing_is_made(world):
    c, dist, built, ran, rail = world
    r = rail(Rail(grants=()))
    resp = _post(c)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == _not_entitled(PROFILE)
    _nothing_made(dist, built, ran)
    assert r.calls == [(PROFILE, ALICE)]


# -- c: per profile ----------------------------------------------------------------------------------

def test_c_a_grant_on_one_profile_does_not_export_another(world):
    c, dist, built, ran, rail = world
    assert OTHER in engine.PROFILES, sorted(engine.PROFILES)
    r = rail(Rail(grants={(PROFILE, ALICE)}))
    resp = _post(c, profile=OTHER)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == _not_entitled(OTHER)
    _nothing_made(dist, built, ran)
    assert r.calls == [(OTHER, ALICE)]


# -- d: an outage is a 503 ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [httpx.ConnectError("directory down"), RuntimeError("malformed answer")],
                         ids=["transport", "malformed"])
def test_d_a_rail_that_cannot_be_asked_is_a_503_never_a_deny_and_never_a_file(world, exc):
    c, dist, built, ran, rail = world
    rail(Rail(grants={(PROFILE, ALICE)}, raises=exc))
    resp = _post(c)
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"] == {"reason": "can_export_unavailable"}
    _nothing_made(dist, built, ran)


# -- e: deny by default through the real `can_export` ------------------------------------------------

def _real_rail_module():
    mod = sys.modules[engine.can_export.__module__]
    assert mod.__name__.endswith("utils.export_capability"), mod.__name__
    assert engine.can_export is mod.can_export
    return mod


def test_e_with_no_directory_configured_the_real_rail_refuses(world, no_default_export_grant, monkeypatch):
    c, dist, built, ran, _ = world
    _real_rail_module()
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    resp = _post(c)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == _not_entitled(PROFILE)
    _nothing_made(dist, built, ran)


def test_e_the_real_rail_asks_the_capability_and_a_404_is_a_deny(world, no_default_export_grant, monkeypatch):
    """The directory double answers `check: true` for `can_export:<PROFILE>` / ALICE only, and 404
    (Topaz's "object not found" for an ungranted capability) for anything else."""
    c, dist, built, ran, _ = world
    mod = _real_rail_module()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if body == mod.check_payload(PROFILE, ALICE):
            return httpx.Response(200, json={"check": True})
        return httpx.Response(404, json={"code": 5, "message": "not found"})

    real_client = httpx.Client
    monkeypatch.setattr(mod.httpx, "Client",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://directory.invalid")

    assert _post(c).status_code == 200
    assert seen == [("/api/v3/directory/check", {
        "object_type": "capability", "object_id": f"can_export:{PROFILE}", "relation": "can_invoke",
        "subject_type": "user", "subject_id": ALICE})]
    built.clear(), ran.clear()
    for f in list(dist.iterdir()):
        f.unlink()

    resp = _post(c, profile=OTHER)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == _not_entitled(OTHER)
    _nothing_made(dist, built, ran)


# -- f: order ----------------------------------------------------------------------------------------

def test_f_an_unknown_profile_is_404_before_the_rail_is_asked(world):
    c, _, _, _, rail = world
    r = rail(Rail(grants={(PROFILE, ALICE)}))
    resp = _post(c, profile="no_such_profile")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "unknown_profile"
    assert r.calls == []


def test_f_a_non_member_is_refused_on_the_program_before_the_rail_is_asked(world):
    c, dist, built, ran, rail = world
    r = rail(Rail(grants={(PROFILE, BOB)}))
    resp = _post(c, user=BOB)
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "program_not_visible"
    _nothing_made(dist, built, ran)
    assert r.calls == []


# -- g: the join --------------------------------------------------------------------------------------

def test_g_every_cdrl_profile_the_sandbox_serves_has_a_can_export_row(profiles):
    rows = (yaml.safe_load(GRANTS.read_text(encoding="utf-8")) or {}).get("capabilities") or {}
    granted = {k.split(":", 1)[1] for k, v in rows.items()
               if k.startswith("can_export:") and (v or {}).get("grant_to_groups")}
    served = set(profiles)
    assert served, "the sample overlay served no CDRL profile"
    assert served <= granted, f"served with no can_export row, so exportable by nobody: {sorted(served - granted)}"


# -- h..m: the listing serves only what the caller may export (the review export's rule) ------------

def _list(c, user=ALICE):
    return c.get("/cdrl_profiles", params={"user_email": user})


def test_h_the_listing_is_the_profiles_the_rail_grants_this_caller(world):
    c, _, _, _, rail = world
    r = rail(Rail(grants={(PROFILE, ALICE), (OTHER, BOB)}))
    resp = _list(c)
    assert resp.status_code == 200, resp.text
    assert [p["name"] for p in resp.json()] == [PROFILE]
    assert sorted(r.calls) == sorted((name, ALICE) for name in engine.PROFILES), "asked per profile, as this caller"


def test_i_the_control_a_caller_granted_nothing_is_listed_nothing_and_granted_all_is_listed_all(world):
    c, _, _, _, rail = world
    rail(Rail(grants=()))
    assert _list(c).json() == []
    rail(Rail(grants={(name, ALICE) for name in engine.PROFILES}))
    assert [p["name"] for p in _list(c).json()] == sorted(engine.PROFILES)


def test_j_the_offer_equals_what_the_export_builds(world):
    """Per profile: listed if and only if `/cdrl_export` does not refuse it as not entitled."""
    c, _, _, _, rail = world
    rail(Rail(grants={(PROFILE, ALICE)}))
    listed = {p["name"] for p in _list(c).json()}
    for name in sorted(engine.PROFILES):
        resp = _post(c, profile=name)
        refused = resp.status_code == 403 and resp.json()["detail"]["error"] == "not_entitled_to_export"
        assert (name in listed) == (not refused), (name, resp.status_code, resp.text[:200])
    assert listed == {PROFILE}


@pytest.mark.parametrize("who", ["svc:supervisor", ""], ids=["service", "nobody"])
def test_k_a_service_caller_or_no_caller_is_listed_nothing_without_asking_the_rail(world, who):
    c, _, _, _, rail = world
    r = rail(Rail(grants={(name, who) for name in engine.PROFILES}))
    resp = _list(c, user=who)
    assert resp.status_code == 200 and resp.json() == []
    assert r.calls == []


def test_l_a_rail_that_cannot_be_asked_lists_a_503_never_an_empty_list(world):
    c, _, _, _, rail = world
    rail(Rail(grants={(PROFILE, ALICE)}, raises=httpx.ConnectError("directory down")))
    resp = _list(c)
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"] == {"reason": "can_export_unavailable"}


def test_m_with_no_directory_configured_the_real_rail_lists_nothing(world, no_default_export_grant, monkeypatch):
    c, _, _, _, _ = world
    _real_rail_module()
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    resp = _list(c)
    assert resp.status_code == 200 and resp.json() == []
