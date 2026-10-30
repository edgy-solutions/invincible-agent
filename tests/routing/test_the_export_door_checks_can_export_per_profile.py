"""The export door checks `can_export:<profile>` on single and batch, in addition to
`ingest:exportBatch` (architect ruling 2026-10-30). DENY BY DEFAULT: a profile with no row is
exportable by nobody.

The capability check is doubled at `human_tasks.can_invoke_or_unavailable`, a function of
(capability, caller) that records every capability asked, so the arms assert on the REQUEST.
Fixtures and doubles are the review-export test file's own.

  a. batch: exportBatch yes, can_export:<profile> no -> 403 not_entitled_to_export, naming the profile.
  b. batch: both yes -> 200.
  c. batch: exportBatch no -> 403 not_entitled_to_export_batch and can_export is never asked.
  d. single, review-access path (the dropper): no -> 403, yes -> 200.
  e. single, exportBatch-fallback path: no -> 403 not_entitled_to_export.
  f. an unknown profile is 422 on both routes and can_export is never asked.
  g. Topaz down on the can_export check is 503, never 403.
  h. policy: every profile in policy/exports/ has a can_export row granted to alert-processors.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

import yaml  # noqa: E402

from src.iagent import export_profiles as ep  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from tests.routing.test_a_review_export_resolves_every_column_or_refuses import (  # noqa: E402
    DROPPER, REV_C, ROOT, SIMPLE, STRANGER, Ledger, _as, _get, _install, _iid, _use_profiles, _world,
)

BATCH = "ingest:exportBatch"
CE = "can_export:t"


@pytest.fixture(autouse=True)
def _cleanup():
    ep.clear_cache()
    yield
    gateway.app.dependency_overrides.clear()
    ep.clear_cache()


def _door(monkeypatch, tmp_path, *, grants, who, error=None, worlds=True):
    """Install the world, then the capability double over it. `grants`: capability strings that
    answer True for everyone. `error`: {capability: exception instance to raise}."""
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world(1, REV_C)] if worlds else [])
    asks = []

    def can_invoke(capability, caller):
        asks.append(capability)
        if error and capability in error:
            raise error[capability]
        return capability in grants

    monkeypatch.setattr(ht, "can_invoke_or_unavailable", can_invoke)
    _as(who)
    return asks


def _batch(profile="t"):
    return _get(f"/ingest/export?profile={profile}&from=2026-10-01&to=2026-10-02")


def _single(profile="t"):
    return _get(f"/ingest/{_iid(1)}/export?profile={profile}")


# a / b / c ---------------------------------------------------------------------------------

def test_a_batch_without_can_export_is_403_and_names_the_profile(monkeypatch, tmp_path):
    asks = _door(monkeypatch, tmp_path, grants={BATCH}, who=STRANGER)
    r = _batch()
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["error"] == "not_entitled_to_export"
    assert d["refusal"]["policy_id"] == "capability_grants:can_export:t"
    assert d["refusal"]["missing_binding"] == "can_invoke can_export:t"
    assert asks == [BATCH, CE]
    assert Ledger.calls == []


def test_b_batch_with_both_is_200(monkeypatch, tmp_path):
    asks = _door(monkeypatch, tmp_path, grants={BATCH, CE}, who=STRANGER)
    r = _batch()
    assert r.status_code == 200, r.text
    assert asks == [BATCH, CE]


def test_c_batch_without_exportbatch_never_asks_can_export(monkeypatch, tmp_path):
    asks = _door(monkeypatch, tmp_path, grants={CE}, who=STRANGER)
    r = _batch()
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_entitled_to_export_batch"
    assert asks == [BATCH]


# d / e -------------------------------------------------------------------------------------

def test_d_single_review_path_needs_can_export(monkeypatch, tmp_path):
    asks = _door(monkeypatch, tmp_path, grants=set(), who=DROPPER)
    r = _single()
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "not_entitled_to_export"
    assert r.json()["detail"]["refusal"]["policy_id"] == "capability_grants:can_export:t"
    assert asks == [CE]
    asks = _door(monkeypatch, tmp_path, grants={CE}, who=DROPPER)
    r = _single()
    assert r.status_code == 200, r.text
    assert asks == [CE]


def test_e_single_exportbatch_fallback_path_needs_can_export(monkeypatch, tmp_path):
    asks = _door(monkeypatch, tmp_path, grants={BATCH}, who=STRANGER)
    r = _single()
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "not_entitled_to_export"
    assert asks == [BATCH, CE]
    asks = _door(monkeypatch, tmp_path, grants={BATCH, CE}, who=STRANGER)
    assert _single().status_code == 200
    assert asks == [BATCH, CE]


# f -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("route", [_batch, _single])
def test_f_an_unknown_profile_is_422_and_can_export_is_never_asked(monkeypatch, tmp_path, route):
    asks = _door(monkeypatch, tmp_path, grants={BATCH, CE}, who=DROPPER if route is _single else STRANGER)
    r = route("nope")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_profile_unknown"
    assert not [a for a in asks if a.startswith("can_export:")]


# g -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("route,who,grants", [
    (_batch, STRANGER, {BATCH}), (_single, DROPPER, set()), (_single, STRANGER, {BATCH})])
def test_g_topaz_down_on_can_export_is_503_not_403(monkeypatch, tmp_path, route, who, grants):
    _door(monkeypatch, tmp_path, grants=grants, who=who,
          error={CE: ht.AuthorizationUnavailable("down")})
    r = route()
    assert r.status_code == 503 and r.json()["detail"]["error"] == "authorization_unavailable"


# h -----------------------------------------------------------------------------------------

def test_h_every_shipped_profile_has_a_can_export_row_for_alert_processors():
    names = sorted(yaml.safe_load(p.read_text(encoding="utf-8"))["name"]
                   for p in (ROOT / "policy" / "exports").glob("*.yaml"))
    assert names, "no shipped export profile found"
    grants = yaml.safe_load((ROOT / "policy" / "capability_grants.yaml").read_text(encoding="utf-8"))
    rows = grants.get("capabilities") or grants.get("grants") or grants
    for n in names:
        row = rows.get(f"can_export:{n}")
        assert row is not None, f"profile {n!r} ships no can_export:{n} row (deny by default)"
        assert "alert-processors" in row["grant_to_groups"]
