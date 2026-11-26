"""A BROKER REFUSAL REACHES ENGINE-FIN AS A DENIAL, NOT AN OUTAGE (dag-tools 0.18.0).

Until 0.17.0 the central gateway turned a broker 403 into a 502, which the client classifies
as `MeshUnavailable`, so engine-fin answered `AssetUnavailable` (503, "could not be read just
now"): a refusal told the caller to retry. From 0.18.0 the gateway forwards the 403, and the
client classifies a 403 as `NotEntitled`.

This drives the REAL `CortexDataClient` (the pinned dag-tools) over an HTTP wire that answers
the gateway's 403, through engine-fin's real `require_grant` and `_raise_for_read_failure`.
Nothing in between is a double. Its control is the same wire answering 502, which must still
be `AssetUnavailable`. The 403 is the forwarded form, with `detail={"error": <reason>}`.

No refusal site is added. `_asset_read_errors` already answers `AssetDenied` with
`refusal.policy_id = asset_grants`. What changes is which upstream outcome reaches it.

Run: uv run pytest tests/finance/test_a_broker_refusal_reaches_fin_as_a_denial.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

pytest.importorskip("polars")

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import asset_inputs  # noqa: E402
from dag_tools.cortex_data import client as cortex_client  # noqa: E402

URN = "urn:li:dataset:(urn:li:dataPlatform:s3,fin.ledger,PROD)"
GATEWAY = "http://central-gateway.test"


def _wire(monkeypatch, status: int, detail) -> list[httpx.Request]:
    """The client's own `httpx.Client()` over a transport that answers `status`."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"detail": detail})

    real = httpx.Client
    monkeypatch.setattr(cortex_client.httpx, "Client",
                        lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k))
    return seen


def _read(urn: str):
    return cortex_client.CortexDataClient(broker_url=GATEWAY, jwt_token="t").get_dataframe_with_ticket(urn)


def test_a_forwarded_broker_403_is_asset_denied(monkeypatch):
    seen = _wire(monkeypatch, 403, {"error": "unminted_refused"})
    with pytest.raises(asset_inputs.AssetDenied):
        asset_inputs.require_grant(_read, URN)
    assert len(seen) == 1 and seen[0].url.path.endswith("/authorize"), "the read never reached the wire"


def test_control_a_502_is_still_asset_unavailable(monkeypatch):
    seen = _wire(monkeypatch, 502, "Bad gateway: Domain broker error")
    with pytest.raises(asset_inputs.AssetUnavailable) as e:
        asset_inputs.require_grant(_read, URN)
    assert not isinstance(e.value, asset_inputs.AssetDenied)
    assert len(seen) == 1


def test_the_pinned_client_classifies_403_as_not_entitled():
    """The step the seal rests on, read from the pinned client rather than assumed."""
    from dag_tools.cortex_data.identity import MeshUnavailable, NotEntitled, classify_response
    assert isinstance(classify_response(403, "x"), NotEntitled)
    assert isinstance(classify_response(502, "x"), MeshUnavailable)
    _cls, not_entitled, mesh_unavailable = asset_inputs._load_client()
    assert (not_entitled, mesh_unavailable) == (NotEntitled, MeshUnavailable), (
        "engine-fin's seam names other exception classes than the client raises")
