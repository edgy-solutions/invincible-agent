"""Canvas templates have an overlay layer (ADR-0036), and a deployment's board for its own measure
lives there: `program_finance_tcpi`, shipped as a SAMPLE under `policy/overlays/sample/canvases/`.

Env unset: the ratified set is the seed's, byte for byte. Env set: the overlay's templates join it,
validate, and an overlay template carrying a seed's id replaces it. A seed through the real
`/canvas/seed` route POSTs one panel per verb, the declared measure's among them.

Run: uv run --no-sync pytest tests/planning/test_canvas_templates_have_an_overlay_layer.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import iagent.canvas_template as ct  # noqa: E402

SAMPLE = REPO / "policy" / "overlays" / "sample" / "canvases"
TID = "program_finance_tcpi"


def test_env_unset_the_sample_is_not_ratified(monkeypatch):
    monkeypatch.delenv("CANVAS_OVERLAY_DIRS", raising=False)
    assert TID not in ct.ratified_template_ids()
    with pytest.raises(KeyError):
        ct.load_template(TID)
    seed_only = sorted(p.stem for p in (REPO / "policy" / "canvases").glob("*.yaml"))
    assert ct.ratified_template_ids() == seed_only


def test_env_set_the_sample_is_ratified_and_validates(monkeypatch):
    monkeypatch.setenv("CANVAS_OVERLAY_DIRS", str(SAMPLE))
    assert TID in ct.ratified_template_ids()
    t = ct.load_template(TID)
    assert [p.verb for p in t.panels] == ["mesh:finPerformanceIndices",
                                          "mesh:finToCompletePerformanceIndex"]


def test_an_overlay_template_with_a_seed_id_replaces_it(tmp_path, monkeypatch):
    raw = yaml.safe_load((REPO / "policy" / "canvases" / "program_finance.yaml")
                         .read_text(encoding="utf-8"))
    raw["title"] = "OVERLAY REPLACEMENT"
    (tmp_path / "program_finance.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.delenv("CANVAS_OVERLAY_DIRS", raising=False)
    assert ct.load_template("program_finance").title != "OVERLAY REPLACEMENT"
    monkeypatch.setenv("CANVAS_OVERLAY_DIRS", str(tmp_path))
    assert ct.load_template("program_finance").title == "OVERLAY REPLACEMENT"
    assert ct.ratified_template_ids().count("program_finance") == 1


def test_an_explicit_directory_means_that_directory_only(monkeypatch):
    monkeypatch.setenv("CANVAS_OVERLAY_DIRS", str(SAMPLE))
    assert ct.ratified_template_ids(SAMPLE) == [TID]


# ── the seed, through the real route ─────────────────────────────────────────────────────────

class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = "alice@example.com"
    email = "alice@example.com"


class _Req:
    headers = {"Authorization": "Bearer t"}


class _Ctx:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        yield "event: final_payload"
        yield "data: {}"


class _Client:
    calls: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, json=None, headers=None):
        _Client.calls.append({"url": url, "json": json})
        return _Ctx()


@pytest.mark.asyncio
async def test_a_seed_posts_two_panels_one_per_declared_verb(monkeypatch):
    import iagent.gateway as gw

    _Client.calls = []
    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    monkeypatch.setenv("CANVAS_OVERLAY_DIRS", str(SAMPLE))
    req = gw.CanvasSeedRequest(template_id=TID, bindings={"program": "NP-MERIDIAN"})
    await gw.canvas_seed(req, _Req(), _User())
    assert len(_Client.calls) == 2
    t = ct.load_template(TID)
    for i, call in enumerate(_Client.calls):
        sp = call["json"]["seed_panel"]
        assert (sp["template_id"], sp["panel"]) == (TID, i)
    verbs = [ct.panel_dispatch(t, i, {"program": "NP-MERIDIAN"})[0] for i in range(2)]
    assert verbs == ["mesh:finPerformanceIndices", "mesh:finToCompletePerformanceIndex"]


@pytest.mark.asyncio
async def test_the_control_without_the_env_the_seed_is_refused(monkeypatch):
    import iagent.gateway as gw

    _Client.calls = []
    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    monkeypatch.delenv("CANVAS_OVERLAY_DIRS", raising=False)
    req = gw.CanvasSeedRequest(template_id=TID, bindings={"program": "NP-MERIDIAN"})
    with pytest.raises(HTTPException):
        await gw.canvas_seed(req, _Req(), _User())
    assert _Client.calls == []
