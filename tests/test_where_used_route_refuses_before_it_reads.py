"""`/where_used`: an unentitled caller is refused before any read; the default configuration
reaches the shaping; a dataset that fails to load, or a program directory that is out, is a
503; a defect in the program check is a 500.

Run: uv run pytest tests/test_where_used_route_refuses_before_it_reads.py -q
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_fleet.ontology_service import main as eo
from agent_fleet.ontology_service import where_used as w


@pytest.fixture()
def client():
    return TestClient(eo.app)  # no `with`: the lifespan (stores, registration) is not run


def test_NOT_ENTITLED_IS_REFUSED_BEFORE_THE_DATASET_IS_READ(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the dataset was read for an unentitled caller")

    monkeypatch.setattr(eo._where_used, "load_dataset", boom)
    r = client.post("/where_used", json={"params": {"part": "x"}, "entitled_domains": ["OTHER"]})
    assert r.status_code == 200
    assert r.json()["reason"] == "not_entitled" and r.json()["refused"] is True


def test_THE_DEFAULT_CONFIGURATION_REACHES_THE_SHAPING(client, monkeypatch):
    seen = {}

    def fake(dataset, part, configuration, **kw):
        seen.update(part=part, configuration=configuration, caller=kw["caller_id"])
        return {"status": "ok"}

    monkeypatch.setattr(eo._where_used, "where_used", fake)
    for params in ({"part": "p"}, {"part": "p", "configuration": ""}):
        seen.clear()
        r = client.post("/where_used", json={
            "params": params, "entitled_domains": [w.DOMAIN], "user_email": "alice@example.com"})
        assert r.status_code == 200
        assert seen == {"part": "p", "configuration": w.DEFAULT_CONFIGURATION,
                        "caller": "alice@example.com"}


def test_A_DATASET_THAT_WILL_NOT_LOAD_IS_A_503_WITH_THE_LOADERS_MESSAGE(client, monkeypatch, tmp_path):
    monkeypatch.setenv(w.DATASET_ENV, str(tmp_path / "absent.yaml"))
    r = client.post("/where_used", json={"params": {"part": "p"}, "entitled_domains": [w.DOMAIN]})
    assert r.status_code == 503 and "unreadable" in r.json()["detail"]


_PART = "0SYN1:PN-1001"  # P in the shipped fixture: its end items carry programs, so the check runs


@pytest.mark.parametrize("outage", [
    httpx.ConnectError("directory unreachable"),
    httpx.DecodingError("directory answered garbage"),
])
def test_A_PROGRAM_DIRECTORY_OUTAGE_IS_A_503_WITH_NO_ROWS(client, monkeypatch, outage):
    def out(program, caller):
        raise outage

    monkeypatch.setattr(eo, "_notice_parts_can_view_program", out)
    r = client.post("/where_used", json={
        "params": {"part": _PART}, "entitled_domains": [w.DOMAIN], "user_email": "alice@example.com"})
    assert r.status_code == 503 and "rows" not in r.json()


def test_A_DEFECT_IN_THE_PROGRAM_CHECK_IS_A_500_NOT_AN_OUTAGE(monkeypatch):
    def defect(program, caller):
        raise KeyError("a defect, not an outage")

    monkeypatch.setattr(eo, "_notice_parts_can_view_program", defect)
    r = TestClient(eo.app, raise_server_exceptions=False).post("/where_used", json={
        "params": {"part": _PART}, "entitled_domains": [w.DOMAIN], "user_email": "alice@example.com"})
    assert r.status_code == 500
