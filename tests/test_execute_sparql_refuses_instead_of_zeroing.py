"""THE WIRING, NOT THE MODULE — `execute_sparql` itself, loaded and driven.

`tests/test_an_outage_is_not_an_empty_answer.py` proves the decision is right. This file proves
`main.py` ACTUALLY TAKES IT, which is the half that the decision being correct does not establish.
A correct rule nobody calls changes nothing, and that gap is invisible to any test of the rule.

The stub harness is reused from `test_predicate_hybrid_search.py` rather than copied: it is the one
place in this repo that can load Engine O's `main.py` without an agent-fleet environment, and a
second copy of it would drift from the original exactly when the imports change.

Run: uv run --frozen pytest tests/test_execute_sparql_refuses_instead_of_zeroing.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO), str(_REPO / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_predicate_hybrid_search import ontology_main  # noqa: E402,F401  (the module fixture)

from agent_fleet.ontology_service.read_outcome import SubstrateUnavailable  # noqa: E402


class _RaisingClient:
    """A Jena that cannot be reached — the condition that produced a confident zero."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *a, **k):
        raise ConnectionError("connect timeout")


class _Status500Client(_RaisingClient):
    """A Jena that answered, badly. This case NEVER returned — it fell through to a fallback that
    cannot serve anyone, which is a different road to the same `[]`."""

    async def post(self, *a, **k):
        return type("R", (), {"status_code": 500, "json": lambda self: {}})()


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def pinned_fallback(ontology_main, monkeypatch):
    """PIN PATH B, because otherwise this file measures WHICH OTHER TEST RAN FIRST.

    `_get_local_graph` behaves differently depending on whether the real `rdflib` or
    `test_predicate_hybrid_search`'s stub is in `sys.modules`: a plain `Graph` raises "requires a
    dataset", the stub raises `AttributeError`. Both are failures, so the REFUSAL is identical
    either way - but the DETAIL STRING is not, and three arms here assert on the detail. They
    passed standalone and failed in the full suite, which is a test measuring global state instead
    of its subject.

    Path B's real deadness is asserted in `test_an_outage_is_not_an_empty_answer.py` against rdflib
    directly. Here it is pinned, so these arms measure the WIRING and nothing else.
    """
    def _boom():
        raise RuntimeError("fallback unavailable")

    monkeypatch.setattr(ontology_main, "_get_local_graph", _boom, raising=False)


def test_AN_UNREACHABLE_JENA_RAISES_instead_of_returning_an_empty_list(ontology_main, monkeypatch):
    """THE DEFECT, AT THE REAL FUNCTION. Before this, a dead cluster and an empty graph were the
    same `[]` to all eight callers."""
    monkeypatch.setattr(ontology_main, "_JENA_ENDPOINT", "http://fuseki/ds/query", raising=False)
    monkeypatch.setattr(ontology_main, "_jena_client", lambda: _RaisingClient(), raising=False)

    with pytest.raises(SubstrateUnavailable) as exc:
        _run(ontology_main.execute_sparql("SELECT ?s WHERE { ?s ?p ?o }"))
    detail = str(exc.value)
    assert "jena" in detail and "connect timeout" in detail, detail
    assert "rdflib: RuntimeError" in detail, (
        "the refusal must name BOTH stores it lost — reporting only the fallback's symptom hides "
        "that the cluster was the thing that went down"
    )


def test_A_NON_200_IS_ALSO_A_REFUSAL_and_it_never_even_returned_before(ontology_main, monkeypatch):
    """A 500 from Fuseki previously fell straight through the `if status == 200` with no branch of
    its own — no return, no log, no record. It reached the caller as the fallback's `[]`."""
    monkeypatch.setattr(ontology_main, "_JENA_ENDPOINT", "http://fuseki/ds/query", raising=False)
    monkeypatch.setattr(ontology_main, "_jena_client", lambda: _Status500Client(), raising=False)

    with pytest.raises(SubstrateUnavailable) as exc:
        _run(ontology_main.execute_sparql("SELECT ?s WHERE { ?s ?p ?o }"))
    assert "HTTP 500" in str(exc.value)


def test_A_REAL_EMPTY_RESULT_IS_STILL_AN_EMPTY_LIST(ontology_main, monkeypatch):
    """THE CONTROL THAT KEEPS THE FIX FROM BEING "RAISE MORE".

    `[]` was always correct for *the query ran and matched nothing*. If this arm ever fails, the
    change stopped distinguishing the two worlds and started refusing both — which would break
    every caller whose honest answer is an abstain.
    """
    class _Empty(_RaisingClient):
        async def post(self, *a, **k):
            return type("R", (), {
                "status_code": 200,
                "json": lambda self: {"results": {"bindings": []}},
            })()

    monkeypatch.setattr(ontology_main, "_JENA_ENDPOINT", "http://fuseki/ds/query", raising=False)
    monkeypatch.setattr(ontology_main, "_jena_client", lambda: _Empty(), raising=False)
    assert _run(ontology_main.execute_sparql("SELECT ?s WHERE { ?s ?p ?o }")) == []


def test_ROWS_STILL_COME_BACK_AS_PLAIN_DICTS(ontology_main, monkeypatch):
    """The happy path is unchanged in SHAPE — eight callers index these dicts directly, so the
    marked result must not leak out through the bridge."""
    class _Rows(_RaisingClient):
        async def post(self, *a, **k):
            return type("R", (), {
                "status_code": 200,
                "json": lambda self: {
                    "results": {"bindings": [{"cls": {"value": "http://x/C"}}]}
                },
            })()

    monkeypatch.setattr(ontology_main, "_JENA_ENDPOINT", "http://fuseki/ds/query", raising=False)
    monkeypatch.setattr(ontology_main, "_jena_client", lambda: _Rows(), raising=False)
    rows = _run(ontology_main.execute_sparql("SELECT ?cls WHERE { ?cls ?p ?o }"))
    assert rows == [{"cls": "http://x/C"}]
    assert isinstance(rows, list) and isinstance(rows[0], dict)


def test_AN_UNDECLARED_ENDPOINT_IS_UNREACHABLE_NOT_EMPTY(ontology_main, monkeypatch):
    """A deployment with no Fuseki configured is a configuration answer, not a data answer. It
    still refuses — but the detail says `unset`, which is the sentence an operator can act on."""
    monkeypatch.setattr(ontology_main, "_JENA_ENDPOINT", "", raising=False)
    with pytest.raises(SubstrateUnavailable) as exc:
        _run(ontology_main.execute_sparql("SELECT ?s WHERE { ?s ?p ?o }"))
    assert "unset" in str(exc.value).lower()
