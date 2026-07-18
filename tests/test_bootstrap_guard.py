"""Seal the bootstrap-state-debt refuse-to-run guard (docs/principles/bootstrap-state-debt.md).

The guard is machinery, so it must be proven: a work-shaped target is refused OUTRIGHT
(no flag overrides), an un-acked sandbox run is refused, and only an acked throwaway with
no work signal is permitted. Pure — no cluster.

Run:  PYTHONPATH=scripts pytest tests/test_bootstrap_guard.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _bootstrap_guard import refuse_unless_throwaway  # noqa: E402

_ACK = "ALLOW_TEST_SEED"
_KW = dict(ack_env=_ACK, reproducible_home="the ingest asset")

_ALL_ENV = ("IAGENT_ENV", "CLUSTER_ENV", "DEPLOY_ENV", "ENVIRONMENT", _ACK,
            "NEO4J_URI", "WEAVIATE_URL", "DATAHUB_GMS_URL")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ALL_ENV:
        monkeypatch.delenv(k, raising=False)


def test_work_env_refused_outright_even_when_acked(monkeypatch):
    """IAGENT_ENV=work -> refused, and the ack flag CANNOT override it (the law)."""
    monkeypatch.setenv("IAGENT_ENV", "work")
    monkeypatch.setenv(_ACK, "1")  # even acked
    with pytest.raises(SystemExit) as e:
        refuse_unless_throwaway("Neo4j edges", **_KW)
    assert "work-shaped" in str(e.value)


@pytest.mark.parametrize("val", ["work", "prod", "production", "staging"])
def test_all_work_env_values_refused(monkeypatch, val):
    monkeypatch.setenv("CLUSTER_ENV", val)
    with pytest.raises(SystemExit):
        refuse_unless_throwaway("store", **_KW)


def test_work_shaped_target_string_refused_outright(monkeypatch):
    """A connection target that looks like a real cluster is refused even without an env flag."""
    monkeypatch.setenv(_ACK, "1")
    with pytest.raises(SystemExit) as e:
        refuse_unless_throwaway("Weaviate", targets=["https://neo4j.corp.internal:7687"], **_KW)
    assert "work-shaped" in str(e.value)


def test_unacked_sandbox_refused(monkeypatch):
    """Sandbox / ambiguous target with no ack flag -> refused with the law message."""
    monkeypatch.setenv("NEO4J_URI", "bolt://iagent-neo4j:7687")
    with pytest.raises(SystemExit) as e:
        refuse_unless_throwaway("Neo4j", targets=["bolt://iagent-neo4j:7687"], **_KW)
    msg = str(e.value)
    assert "NON-REPRODUCIBLE" in msg and _ACK in msg and "this session" in msg.lower()


def test_acked_throwaway_permitted(monkeypatch, capsys):
    """Acked, sandbox-shaped, no work signal -> permitted (returns None) + same-session reminder."""
    monkeypatch.setenv(_ACK, "1")
    monkeypatch.setenv("NEO4J_URI", "bolt://iagent-neo4j:7687")
    assert refuse_unless_throwaway("Neo4j", targets=["bolt://iagent-neo4j:7687"], **_KW) is None
    err = capsys.readouterr().err
    assert "acked throwaway" in err and "must land THIS session" in err


def test_work_env_beats_ack_precedence(monkeypatch):
    """Ordering: the work check runs BEFORE the ack check — work is refused even if acked."""
    monkeypatch.setenv("DEPLOY_ENV", "production")
    monkeypatch.setenv(_ACK, "1")
    with pytest.raises(SystemExit) as e:
        refuse_unless_throwaway("Postgres", **_KW)
    assert "work-shaped" in str(e.value)  # not the ack message
