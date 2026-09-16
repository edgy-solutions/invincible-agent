"""RULED 2026-09-15 — a vector's identity is what PRODUCED it, not what the code believes.

The `MeshCollectionMeta` marker beside a vector collection records the model that produced its
vectors. A reader comparing its own MODULE CONSTANT against that marker compares two BELIEFS and
passes: `DEFAULT_EMBED_MODEL` on both sides agreeing while both disagree with the vectors on disk.

TWO WAYS THE CONSTANT AND THE ACT DIVERGE, and only one of them was ever named:

    1. `model = os.getenv("LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL)`  — env-overridable, IDENTICAL
       line in `agent_fleet/utils/embed.py` and doc-tools' twin. A deployment can embed with
       something neither constant names. (Found by doc-tools-7f while reading the contract.)
    2. The endpoint serves something OTHER than what was requested. **No constant on either side
       of the wire can see this one** — only the response can.

MEASURED 2026-09-15 against the configured endpoint (`LLM_BASE_URL=…:11434/v1`): the
`/v1/embeddings` response carries `"model": "nomic-embed-text"` — the served identity, unversioned,
in the same payload as the vector it describes. **We were already making that call and discarding
the identity one line from where it is needed.**

Run: uv run --frozen pytest tests/test_an_embedding_records_what_the_server_served.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.utils import embed  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _stub(monkeypatch, *, served, dim=768):
    """An endpoint that returns `served` as its model, whatever was asked for."""
    payload = {"object": "list", "model": served, "data": [{"embedding": [0.0] * dim, "index": 0}]}
    monkeypatch.setattr(embed.httpx, "post", lambda *a, **k: _Resp(payload))
    monkeypatch.setattr(embed, "_resolve_endpoint", lambda: ("http://stub/v1", "k", "requested-model"))
    monkeypatch.setattr(embed, "_LAST_SERVED", None, raising=False)


def test_the_observation_reports_what_the_SERVER_said(monkeypatch):
    """THE RULING. Not the constant, not the request — the response."""
    _stub(monkeypatch, served="actually-served-model")
    obs = embed.observe_query_embedding("probe")
    assert obs.served == "actually-served-model"
    assert obs.requested == "requested-model", "the request is kept so a divergence stays visible"


def test_a_SERVED_DIFFERENT_FROM_REQUESTED_is_visible(monkeypatch):
    """The case NO constant on either side of the wire can see.

    Both repos could hold identical `DEFAULT_EMBED_MODEL` values, both could resolve the same
    `LLM_EMBED_MODEL`, and an endpoint could still serve something else. Only the response knows.
    """
    _stub(monkeypatch, served="something-else")
    assert embed.observe_query_embedding("probe").diverged is True


def test_agreement_is_NOT_reported_as_divergence(monkeypatch):
    """THE CONTROL. Without it, `diverged` is satisfied by a property that is always true, and
    every healthy deployment would look misconfigured."""
    _stub(monkeypatch, served="requested-model")
    obs = embed.observe_query_embedding("probe")
    assert obs.diverged is False
    assert obs.served == obs.requested


def test_a_response_WITHOUT_a_model_field_is_ABSENT_not_a_divergence(monkeypatch):
    """The third state, and it must not be a failure.

    Not every OpenAI-compatible server echoes `model`. Absent is *the endpoint did not say* — a
    gap — and reporting it as a mismatch would make a silent server look like a misconfigured one.
    Same rule as an absent collection marker: absent is a STATE, never a value.
    """
    payload = {"object": "list", "data": [{"embedding": [0.0] * 768, "index": 0}]}
    monkeypatch.setattr(embed.httpx, "post", lambda *a, **k: _Resp(payload))
    monkeypatch.setattr(embed, "_resolve_endpoint", lambda: ("http://stub/v1", "k", "requested-model"))
    obs = embed.observe_query_embedding("probe")
    assert obs.served is None
    assert obs.diverged is False, "an endpoint that says nothing has not disagreed with anything"


def test_the_dimension_is_OBSERVED_not_declared(monkeypatch):
    """`EXPECTED_EMBED_DIM` is a constant; the vector's length is a fact. The marker's `dimension`
    gets two independent witnesses this way — its own claim, and the stored vectors themselves."""
    _stub(monkeypatch, served="requested-model", dim=1024)
    obs = embed.observe_query_embedding("probe")
    assert obs.dimension == 1024 != embed.EXPECTED_EMBED_DIM


def test_the_existing_helpers_are_UNCHANGED(monkeypatch):
    """This is additive. `embed_query` is on the hot path of every search in the fleet, and a
    change to its return shape would be a routing change wearing a refactor's clothes."""
    _stub(monkeypatch, served="requested-model")
    v = embed.embed_query("probe")
    assert isinstance(v, list) and len(v) == 768 and isinstance(v[0], float)
