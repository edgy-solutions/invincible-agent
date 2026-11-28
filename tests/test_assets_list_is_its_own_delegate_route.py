"""`assets.list` IS ITS OWN DELEGATE ROUTE: A ROW FOR `assets.authorize` DOES NOT REACH IT (dag-tools 0.19.0).

dag-tools 0.19.0 gives the central gateway's listing its own route id, `assets.list`, and keys
the delegate table per route. The rail (`policy/gateway_delegates.yaml`) has no row for it, by
choice. A service acts for a person only by declared delegation (ruled 11-19), so a grant is
never inferred from upstream adding a route id. If a caller needs the listing, that takes a
ruling, then a row.

This seals that choice under `enforce`, through the gateway's own `resolve_principal`, with a
delegate seam that answers from the rail's gateway rows (the reader dag-tools has not wired
yet; its default seam answers no for everyone). Only signature verification is replaced: the
claims are given, and everything after them is the pinned gateway's code.

  * The absence: each gateway row that names `assets.authorize` and not `assets.list` is
    refused `not_a_delegate` (403) on `assets.list`.
  * Its control: the same row, the same token and the same header on `assets.authorize`
    admit the person, `via` the service.
  * The census: no gateway row names `assets.list`, and the pinned gateway marks the route as
    one a row may name, so the absence is the rail's choice, not a validator's refusal.

Run: uv run pytest tests/test_assets_list_is_its_own_delegate_route.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

identity = pytest.importorskip("dag_tools.central_gateway.identity")

REPO = Path(__file__).resolve().parents[1]
RAIL = REPO / "policy" / "gateway_delegates.yaml"
PERSON = "person-a"  # the named principal; its shape is not what this measures


def _gateway_rows() -> list[dict]:
    rows = (yaml.safe_load(RAIL.read_text(encoding="utf-8")) or {}).get("gateway_delegates") or []
    return [r for r in rows if r.get("door", "gateway") == "gateway"]


def _rail_seam(service: str, route: str) -> bool:
    return any(r["service"] == service and route in (r.get("routes") or []) for r in _gateway_rows())


def _authorize_only_rows() -> list[dict]:
    return [r for r in _gateway_rows()
            if identity.ROUTE_AUTHORIZE in r["routes"] and identity.ROUTE_LIST not in r["routes"]]


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setenv("GATEWAY_IDENTITY_POSTURE", "enforce")
    monkeypatch.delenv("USER_ENTITLEMENT_CLAIM", raising=False)
    monkeypatch.setattr(identity, "is_delegate", _rail_seam)
    assert identity.posture() == identity.POSTURE_ENFORCE


def _as(monkeypatch, service: str) -> None:
    claims = {"sub": "svc-sub", identity.entitlement_claim(): service}
    monkeypatch.setattr(identity, "_verify", lambda token: (claims, None))


def test_there_is_a_row_to_measure():
    assert _authorize_only_rows(), "no gateway row names assets.authorize alone; the seal below measures nothing"


@pytest.mark.parametrize("row", _authorize_only_rows(), ids=lambda r: r["service"])
def test_an_authorize_delegate_is_not_a_delegate_on_the_listing(enforce, monkeypatch, row):
    _as(monkeypatch, row["service"])
    d = identity.resolve_principal("t", PERSON, None, identity.ROUTE_LIST, "-")
    assert d.refused == identity.NOT_A_DELEGATE and d.status == 403, d
    assert d.subject is None


@pytest.mark.parametrize("row", _authorize_only_rows(), ids=lambda r: r["service"])
def test_control_the_same_row_admits_the_person_on_authorize(enforce, monkeypatch, row):
    _as(monkeypatch, row["service"])
    d = identity.resolve_principal("t", PERSON, None, identity.ROUTE_AUTHORIZE, "urn:x")
    assert d.refused is None, d
    assert (d.subject, d.via) == (PERSON, row["service"])


def test_no_gateway_row_names_the_listing_and_the_gateway_would_accept_one():
    assert not [r["service"] for r in _gateway_rows() if identity.ROUTE_LIST in r["routes"]]
    routes = json.loads((Path(identity.__file__).parent / "gateway_routes.json").read_text(encoding="utf-8"))
    rows = routes["routes"] if isinstance(routes, dict) else routes
    listing = [r for r in rows if r.get("id") == identity.ROUTE_LIST]
    assert len(listing) == 1, "the pinned gateway declares no assets.list route"
    assert listing[0].get("delegate_rows_may_name") is True
