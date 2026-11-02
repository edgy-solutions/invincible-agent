"""P6 on the review-export routes: a Topaz OUTAGE is 503 and "not granted" is 403, at every route that
asks the rail, for every REAL failure form, with a Topaz-up control in each case.

Extends `test_the_export_door_checks_can_export_per_profile.py` (#158), whose seal g raises
`AuthorizationUnavailable` straight out of a double at `human_tasks.can_invoke_or_unavailable` -- ONE
synthetic form, past the code that decides what a Topaz answer means. Here the REAL
`can_invoke_or_unavailable` runs over `httpx.MockTransport`, so the eight forms a deployment can produce
(connect error, read timeout, HTTP 503, HTTP 500, empty 200, HTML 200, a JSON list, JSON null) reach the
function that classifies them. #158's seal g covers the "AuthorizationUnavailable raised" form and no real
httpx form.

Nothing is typed that the app can tell us:
  * the routes are the app's own GET routes tagged `ingest-export`, found in `gateway.app.routes`;
  * the capabilities a route asks are READ OFF a granted control run (the double records the asks), per
    caller, not listed here;
  * a route that asks the rail nothing (the profile and shape pickers) is DERIVED the same way and is
    asserted to stay rail-free, since it then has no outage and no 403 to answer.
Every ask is then failed in turn (each form -> 503) and then withheld in turn (-> 403, and a Topaz 404
-- "object not found" is how Topaz answers an ungranted capability -- is the same 403).

Run: uv run pytest tests/routing/test_the_review_export_routes_answer_503_on_an_outage_and_403_on_no_grant.py -q
"""
from __future__ import annotations

import re

import httpx
import pytest

pytest.importorskip("fastapi")

from src.iagent import export_profiles as ep  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from tests.routing.test_a_review_export_resolves_every_column_or_refuses import (  # noqa: E402
    DROPPER, REV_C, SIMPLE, STRANGER, _as, _get, _install, _iid, _use_profiles, _world,
)

TAG = "ingest-export"
_REAL_CLIENT = httpx.Client  # captured once: a patched Client must never wrap the previous patch

FORMS = {
    "connect_error": lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused", request=req)),
    "read_timeout": lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=req)),
    "http_503": lambda req: httpx.Response(503, text="unavailable", request=req),
    "http_500": lambda req: httpx.Response(500, text="boom", request=req),
    "empty_200": lambda req: httpx.Response(200, content=b"", request=req),
    "html_200": lambda req: httpx.Response(200, text="<html>gateway</html>", request=req),
    "list_200": lambda req: httpx.Response(200, json=[], request=req),
    "null_200": lambda req: httpx.Response(200, content=b"null", headers={"content-type": "application/json"}, request=req),
    # A 200 whose `check` is a truthy STRING: not an outage, a DENIAL that reads as a grant (see the xfail below).
    "string_false_check": lambda req: httpx.Response(200, json={"check": "false"}, request=req),
}
# The two forms `can_invoke_or_unavailable` cannot classify: it catches (httpx.HTTPError, ValueError) and then
# calls `.get` on the decoded body, so a JSON list / null is an AttributeError -> an unhandled 500, not a 503.
NON_DICT_BODY = ("list_200", "null_200")
OUTAGE_FORMS = [f for f in FORMS if f not in NON_DICT_BODY and f != "string_false_check"]


@pytest.fixture(autouse=True)
def _cleanup():
    ep.clear_cache()
    yield
    gateway.app.dependency_overrides.clear()
    ep.clear_cache()


def _routes():
    """The review-export GET routes, from the app."""
    out = []
    for r in gateway.app.routes:
        if TAG in (getattr(r, "tags", None) or []) and "GET" in (getattr(r, "methods", None) or ()):
            out.append(r.path)
    return sorted(out)


def _url(path):
    p = re.sub(r"\{[^}]+\}", _iid(1), path)
    return p + ("&" if "?" in p else "?") + "profile=t&from=2026-10-01&to=2026-10-02"


class Topaz:
    """The REAL `can_invoke_or_unavailable` over a MockTransport. `plan[cap]` -> absent (granted),
    "deny" (Topaz answers 200 check:false), "404" (object not found), or a FORMS key (that failure)."""

    def __init__(self, monkeypatch):
        self.asks, self.plan = [], {}

        def handler(req):
            import json as _j
            cap = _j.loads(req.content)["object_id"]
            self.asks.append(cap)
            how = self.plan.get(cap)
            if how is None:
                return httpx.Response(200, json={"check": True}, request=req)
            if how == "deny":
                return httpx.Response(200, json={"check": False}, request=req)
            if how == "404":
                return httpx.Response(404, json={}, request=req)
            return FORMS[how](req)

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(handler)
            return _REAL_CLIENT(*a, **k)

        monkeypatch.setattr(ht.httpx, "Client", factory)
        monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "http://topaz.test")


def _world_up(monkeypatch, tmp_path, who):
    real = ht.can_invoke_or_unavailable
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world(1, REV_C)])
    monkeypatch.setattr(ht, "can_invoke_or_unavailable", real)  # undo the file helper's can_export grant
    _as(who)
    return Topaz(monkeypatch)


class _Crashed:
    """What the TestClient re-raises is, on the wire, an unhandled 500."""
    status_code = 500

    def __init__(self, exc):
        self.exc = exc

    def json(self):
        return {"detail": {"error": f"unhandled:{type(self.exc).__name__}"}}

    text = ""


def _hit(monkeypatch, tmp_path, path, who, plan):
    tz = _world_up(monkeypatch, tmp_path, who)
    tz.plan = dict(plan)
    try:
        r = _get(_url(path))
    except Exception as exc:  # noqa: BLE001 -- an unhandled exception IS a 500 to the caller
        r = _Crashed(exc)
    return r, tz.asks


def _code(r):
    try:
        d = r.json()["detail"]
        return (d.get("error") or d.get("reason")) if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None


def test_the_route_set_is_derived_and_nonempty():
    assert len(_routes()) >= 3, _routes()


@pytest.mark.parametrize("who", [DROPPER, STRANGER])
def test_p6_an_outage_is_503_and_no_grant_is_403_at_every_rail_asking_route(monkeypatch, tmp_path, who):
    bad, rail_routes = _matrix(monkeypatch, tmp_path, who, OUTAGE_FORMS, ("deny", "404"))
    assert rail_routes, "no route asked the rail: the derivation found nothing to seal"
    assert not bad, f"{len(bad)} cases: {bad}"


def _matrix(monkeypatch, tmp_path, who, forms, denials):
    bad, rail_routes = [], []
    for path in _routes():
        r, asks = _hit(monkeypatch, tmp_path, path, who, {})
        if not asks:
            continue  # asks the rail nothing: checked by the next test
        assert r.status_code == 200, (path, who, "CONTROL (Topaz up, all granted)", r.status_code, r.text[:160])
        rail_routes.append(path)
        for cap in dict.fromkeys(asks):
            for form in forms:
                got, _ = _hit(monkeypatch, tmp_path, path, who, {cap: form})
                if got.status_code != 503:
                    bad.append((path, cap, form, got.status_code, _code(got)))
            for how in denials:
                got, _ = _hit(monkeypatch, tmp_path, path, who, {cap: how})
                if got.status_code != 403:
                    bad.append((path, cap, how, got.status_code, _code(got)))
    return bad, rail_routes


@pytest.mark.xfail(strict=True, reason=(
    "DEFECT human_tasks.can_invoke_or_unavailable: a Topaz 200 whose JSON body is a list or null is "
    "`.get` on a non-dict -> AttributeError, which neither it nor the gateway catches, so the export "
    "routes answer an unhandled 500 where P6 owes 503. Both batch and single rails inherit it."))
@pytest.mark.parametrize("who", [DROPPER, STRANGER])
def test_p6_a_non_object_json_200_is_503_not_an_unhandled_500(monkeypatch, tmp_path, who):
    bad, rail_routes = _matrix(monkeypatch, tmp_path, who, NON_DICT_BODY, ())
    assert rail_routes
    assert not bad, f"{len(bad)} cases: {bad}"


@pytest.mark.xfail(strict=True, reason=(
    "DEFECT human_tasks.can_invoke_or_unavailable: `bool(r.json().get('check'))` admits a truthy STRING "
    "such as \"false\" -- a fail-open on the capability rail (the class gov closed for can_read_recipient)."))
def test_a_string_check_is_not_a_grant(monkeypatch, tmp_path):
    for path in _routes():
        r, asks = _hit(monkeypatch, tmp_path, path, STRANGER, {})
        if not asks:
            continue
        for cap in dict.fromkeys(asks):
            got, _ = _hit(monkeypatch, tmp_path, path, STRANGER, {cap: "string_false_check"})
            assert got.status_code in (403, 503), (path, cap, got.status_code)


def test_a_route_that_asks_the_rail_nothing_stays_rail_free(monkeypatch, tmp_path):
    """The pickers (profile and shape lists) read policy files only. If one starts asking the rail it
    owes the same 503/403 form and this goes red until it is added to the matrix above."""
    free = []
    for path in _routes():
        r, asks = _hit(monkeypatch, tmp_path, path, STRANGER, {})
        if not asks:
            free.append(path)
            tz = _world_up(monkeypatch, tmp_path, STRANGER)
            tz.plan = {"ingest:exportBatch": "connect_error", "can_export:t": "connect_error"}
            assert _get(_url(path)).status_code == 200, (path, "a rail outage must not touch a rail-free route")
    assert free, "expected the pickers to be rail-free"
