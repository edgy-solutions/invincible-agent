"""Arm 8 of a-cdrl-is-an-export-profile: the BFF relays the engine's CDRL routes.

The profiles are relayed; the xlsx comes back with the engine's own filename and `cells_sha256`;
an engine 403 is relayed WITH `grantable_by` (relay_refusal); an engine 404 stays 404.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PROGRAM = "NP-MERIDIAN"
FILENAME = f"fin-cdrl-cdrl_a001_ev_summary-{PROGRAM}.xlsx"
CELLS = "ab" * 32
BYTES = b"PK\x03\x04 not really a workbook"
PROFILES = [{"name": "cdrl_a001_ev_summary", "format": "xlsx", "scope": "program", "label": "L"}]
ENGINE_403 = {"detail": {"error": "program_not_visible",
                         "refusal": {"policy_id": "program_members",
                                     "missing_binding": "can_view_program(program)", "candidates": []},
                         "message": "You are not a member of the program this request names."}}


class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = "alice@example.com"
    email = "alice@example.com"


class _Req:
    headers = {"authorization": "Bearer tok"}


class _Resp:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)
        self.content = content

    def json(self):
        return self._payload


@pytest.fixture
def engine(monkeypatch):
    import iagent.gateway as gw

    calls, answers = [], {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append(("POST", url, json, headers))
            return answers["post"]

        async def get(self, url, headers=None):
            calls.append(("GET", url, None, headers))
            return answers["artifact"] if "/artifact/" in url else answers["profiles"]

    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    answers["post"] = _Resp(200, {
        "artifact_filename": FILENAME, "artifact_sha256": "sha256:" + "0" * 64,
        "envelope": {"kind": "cdrl", "cells_sha256": CELLS}})
    answers["artifact"] = _Resp(200, content=BYTES)
    answers["profiles"] = _Resp(200, PROFILES)
    return calls, answers


def _export(profile="cdrl_a001_ev_summary"):
    import iagent.gateway as gw
    try:
        return 200, asyncio.run(gw.export_cdrl(_Req(), profile, PROGRAM, _User()))
    except HTTPException as exc:
        return exc.status_code, exc.detail


def test_8_profiles_are_relayed(engine):
    import iagent.gateway as gw
    calls, _ = engine
    assert asyncio.run(gw.export_cdrl_profiles(_Req(), _User())) == PROFILES
    assert calls[0][3] == {"Authorization": "Bearer tok"}


def test_8_the_xlsx_carries_the_engines_filename_and_cells_hash(engine):
    calls, _ = engine
    status, resp = _export()
    assert status == 200
    assert resp.body == BYTES
    assert resp.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert resp.headers["content-disposition"] == f'attachment; filename="{FILENAME}"'
    assert resp.headers["x-cells-sha256"] == CELLS
    post = calls[0]
    assert post[2] == {"profile": "cdrl_a001_ev_summary", "program_id": PROGRAM,
                       "user_email": "alice@example.com"}
    assert post[3] == {"Authorization": "Bearer tok"}
    assert calls[1][1].endswith(f"/artifact/{FILENAME}")


def test_8_an_engine_403_is_relayed_with_grantable_by(engine):
    _, answers = engine
    answers["post"] = _Resp(403, ENGINE_403)
    status, detail = _export()
    assert status == 403
    assert detail["error"] == "program_not_visible"
    assert "grantable_by" in detail["refusal"]
    assert "grantable_by" not in ENGINE_403["detail"]["refusal"]


def test_8_an_engine_404_unknown_profile_stays_404(engine):
    _, answers = engine
    answers["post"] = _Resp(404, {"detail": {"error": "unknown_profile", "profiles": ["x"]}})
    status, detail = _export("nope")
    assert status == 404 and detail["error"] == "unknown_profile"


def test_8_a_filename_off_the_cdrl_pattern_is_not_fetched(engine):
    calls, answers = engine
    answers["post"] = _Resp(200, {"artifact_filename": "../../etc/passwd",
                                  "envelope": {"cells_sha256": CELLS}})
    status, detail = _export()
    assert status == 502 and detail["error"] == "fin_engine_bad_cdrl_response"
    assert len(calls) == 1
