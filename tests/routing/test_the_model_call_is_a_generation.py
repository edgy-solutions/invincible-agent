"""Engine O records each model call as a generation: model, parameters, usage, two hashes.

Architect ruling 2026-11-24: the prompt and reply TEXT are recorded only when a deployment
setting turns that on; where it is off the hashes still let two runs be compared.

baml_py's real `Collector` cannot be filled offline (only a live call fills it), so the wrapper's
`collector_factory` is injected with a stub that has the same read surface (`last.calls[i]
.http_request.body.raw()`, `.http_response.body.text()`, `.usage`, `.timing`, `.client_name`).
The fake inner client plays the BAML client: it fills the collector it is handed.

Run:  uv run python -m pytest tests/routing/test_the_model_call_is_a_generation.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "agent_fleet" / "ontology_service"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.ontology_service import model_generations as mg  # noqa: E402
from agent_fleet.ontology_service.inflight import CoalescingClient  # noqa: E402

PROMPT_MARK = "PROMPT-MARKER-7741"
REPLY_MARK = "REPLY-MARKER-9928"
REQ = json.dumps({
    "model": "gpt-oss:120b", "temperature": 0.2, "reasoning_effort": "high", "max_tokens": 900,
    "top_p": 0.9, "seed": 7, "messages": [{"role": "user", "content": f"classify {PROMPT_MARK}"}],
}).encode()
RESP = json.dumps({
    "model": "gpt-oss:120b-2026-01", "system_fingerprint": "fp_abc",
    "choices": [{"message": {"content": f"answer {REPLY_MARK}"}}],
}).encode().decode()


class _Body:
    def __init__(self, raw: bytes):
        self._raw = raw

    def raw(self):
        return self._raw

    def text(self):
        return self._raw.decode()

    def json(self):
        return json.loads(self._raw)


class _Collector:
    last = None


def _fill(collector, req=REQ, resp=RESP):
    call = NS(
        selected=True, client_name="Ollama",
        http_request=NS(body=_Body(req)), http_response=NS(body=_Body(resp.encode())),
        usage=NS(input_tokens=120, output_tokens=33, cached_input_tokens=10),
        timing=NS(duration_ms=42),
    )
    collector.last = NS(calls=[call], raw_llm_response=f"answer {REPLY_MARK}")


class _Fake:
    """A BAML-shaped async client."""

    def __init__(self, *, fail=None, delay=0.0):
        self.fail, self.delay = fail, delay
        self.seen: list = []
        self.result = {"domain": "X"}
        outer = self

        class _Request:
            def ClassifyDomainIntent(self, *a, **k):
                return NS(body=_Body(REQ))
        self.request = _Request()
        self.stream = "stream-passthrough"

    async def ClassifyDomainIntent(self, *args, baml_options=None, **kw):
        self.seen.append((args, kw, baml_options))
        if self.delay:
            await asyncio.sleep(self.delay)
        _fill(baml_options["collector"])
        if self.fail:
            raise self.fail
        return self.result

    def with_options(self, **kw):
        return ("with_options", kw)


def _client(inner, records):
    # The setting is read at CONSTRUCTION, so tests set the environment before building.
    return mg.GenerationRecordingClient(inner, emit=records.append, collector_factory=_Collector)


def _run(coro):
    return asyncio.run(coro)


def _sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _setting_unset(monkeypatch):
    monkeypatch.delenv(mg.TEXT_SETTING, raising=False)


def test_the_record_has_model_parameters_usage_and_both_hashes():
    recs: list = []
    out = _run(_client(_Fake(), recs).ClassifyDomainIntent("q"))
    assert out == {"domain": "X"}
    (r,) = recs
    assert r["name"] == "ClassifyDomainIntent" and r["level"] == "DEFAULT"
    assert r["model"] == "gpt-oss:120b"
    assert r["model_version"] == "gpt-oss:120b-2026-01@fp_abc"
    assert r["model_parameters"] == {
        "temperature": 0.2, "reasoning_effort": "high", "max_tokens": 900, "top_p": 0.9, "seed": 7}
    assert r["usage"] == {"input_tokens": 120, "output_tokens": 33, "cached_input_tokens": 10}
    assert r["prompt_sha256"] == _sha(REQ)
    assert r["reply_sha256"] == _sha(RESP)
    assert r["client_name"] == "Ollama" and "latency_ms" in r


def test_the_prompt_hash_is_the_coalescers_key_without_the_name_prefix():
    recs: list = []
    _run(_client(_Fake(), recs).ClassifyDomainIntent("q"))
    assert recs[0]["prompt_sha256"] == hashlib.sha256(REQ).hexdigest()
    assert recs[0]["prompt_sha256"] != hashlib.sha256(b"ClassifyDomainIntent\0" + REQ).hexdigest()


@pytest.mark.parametrize("setting", [None, "off"])
def test_with_the_setting_off_no_text_appears_anywhere(monkeypatch, setting):
    if setting is not None:
        monkeypatch.setenv(mg.TEXT_SETTING, setting)
    recs: list = []
    _run(_client(_Fake(), recs).ClassifyDomainIntent("q"))
    (r,) = recs
    assert "input" not in r and "output" not in r
    blob = json.dumps(r)
    assert PROMPT_MARK not in blob and REPLY_MARK not in blob


@pytest.mark.parametrize("setting", ["on"])
def test_control_with_the_setting_on_both_markers_appear(monkeypatch, setting):
    """The control for the off-test: the same call with the setting on shows both markers."""
    monkeypatch.setenv(mg.TEXT_SETTING, setting)
    recs: list = []
    _run(_client(_Fake(), recs).ClassifyDomainIntent("q"))
    blob = json.dumps(recs[0])
    assert PROMPT_MARK in blob and REPLY_MARK in blob
    assert "input" in recs[0] and "output" in recs[0]


@pytest.mark.parametrize("bad", ["1", "true", "ture", "", "ON", "yes"])
def test_a_bad_setting_refuses_at_construction_naming_only_the_setting(monkeypatch, bad):
    monkeypatch.setenv(mg.TEXT_SETTING, bad)
    with pytest.raises(ValueError) as ei:
        _client(_Fake(), [])
    assert mg.TEXT_SETTING in str(ei.value)
    assert "ture" not in str(ei.value)


def test_the_setting_is_read_once_not_per_call(monkeypatch):
    recs: list = []
    c = _client(_Fake(), recs)  # built with the setting unset
    monkeypatch.setenv(mg.TEXT_SETTING, "on")
    _run(c.ClassifyDomainIntent("q"))
    assert "input" not in recs[0]


def test_the_result_is_returned_unchanged_and_the_callers_options_are_not_mutated():
    inner, recs = _Fake(), []
    sentinel = object()
    opts = {"tb": sentinel, "client_registry": "reg"}
    out = _run(_client(inner, recs).ClassifyDomainIntent("q", baml_options=opts))
    assert out is inner.result
    assert opts == {"tb": sentinel, "client_registry": "reg"}
    sent = inner.seen[0][2]
    assert sent["tb"] is sentinel and sent["client_registry"] == "reg" and "collector" in sent


def test_a_callers_own_collector_leaves_the_call_untouched_and_records_nothing():
    inner, recs = _Fake(), []
    mine = _Collector()
    _run(_client(inner, recs).ClassifyDomainIntent("q", baml_options={"collector": mine}))
    assert inner.seen[0][2]["collector"] is mine and recs == []


def test_passthrough_attributes_still_work():
    c = _client(_Fake(), [])
    assert c.stream == "stream-passthrough"
    assert c.with_options(x=1) == ("with_options", {"x": 1})
    assert c.request.ClassifyDomainIntent().body.raw() == REQ


def test_an_inner_exception_is_reraised_and_records_an_error_without_text():
    boom = ValueError(f"bad {PROMPT_MARK} {REPLY_MARK}")
    recs: list = []
    with pytest.raises(ValueError) as ei:
        _run(_client(_Fake(fail=boom), recs).ClassifyDomainIntent("q"))
    assert ei.value is boom
    (r,) = recs
    assert r["level"] == "ERROR" and r["status_message"] == "ValueError"
    assert "input" not in r and "output" not in r
    blob = json.dumps(r)
    assert PROMPT_MARK not in blob and REPLY_MARK not in blob


def test_an_emit_that_raises_does_not_break_the_call():
    def bad(_rec):
        raise RuntimeError("langfuse down")
    c = mg.GenerationRecordingClient(_Fake(), emit=bad, collector_factory=_Collector)
    assert _run(c.ClassifyDomainIntent("q")) == {"domain": "X"}


def test_two_concurrent_identical_calls_through_the_coalescer_give_one_record():
    inner, recs = _Fake(delay=0.05), []

    async def both():
        c = CoalescingClient(_client(inner, recs))
        return await asyncio.gather(c.ClassifyDomainIntent("q"), c.ClassifyDomainIntent("q"))

    a, b = _run(both())
    assert a == b == {"domain": "X"}
    assert len(inner.seen) == 1 and len(recs) == 1


def test_main_installs_the_recorder_inside_the_coalescer():
    """The recorder is bound first, the coalescer last (inflight's own wiring test needs `b`)."""
    lines = (_ROOT / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8").splitlines()
    rec = [i for i, ln in enumerate(lines) if ln.startswith("b = GenerationRecordingClient(b")]
    coal = [i for i, ln in enumerate(lines) if ln.startswith("b = CoalescingClient(b")]
    assert len(rec) == 1 and len(coal) == 1 and rec[0] < coal[0]
