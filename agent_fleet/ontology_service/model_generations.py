"""Engine O records each of its model calls as a Langfuse generation.

Architect ruling 2026-11-24: "Engine O records each of its model calls as a generation in
Langfuse: model name and version, temperature, effort setting, token counts, and a hash of the
rendered prompt and of the reply. This is always on. The prompt and reply text are recorded only
when a deployment setting turns that on. [...] text is allowed where a deployment declares it,
and nowhere else. Where it is off, the hashes still let two runs be compared."

Everything on the record is read from what was SENT and RECEIVED (the BAML collector's HTTP
request and response), never from configuration. With the text setting off the record carries no
`input` / `output` key and no other field holds any part of the prompt or the reply: the error
message text is never recorded, only the exception's type name.

Install INSIDE the coalescer, so a call that joins a running call (and makes no model call)
records nothing:  CoalescingClient(GenerationRecordingClient(b)).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time

# ONE name: Lane 1 names it finally; a rename is this line.
TEXT_SETTING = "IAGENT_TRACE_MODEL_TEXT"

_PARAM_KEYS = ("temperature", "reasoning_effort", "reasoning", "think", "max_tokens",
               "max_completion_tokens", "top_p", "seed")


def read_trace_model_text(environ=None) -> bool:
    """The deployment setting, read ONCE at startup. Unset is off; exactly "on" / "off" are
    accepted; anything else (including empty) raises, so a typo refuses engine start rather
    than silently recording or silently not recording text."""
    env = os.environ if environ is None else environ
    if TEXT_SETTING not in env:
        return False
    v = env[TEXT_SETTING]
    if v == "on":
        return True
    if v == "off":
        return False
    raise ValueError(f"{TEXT_SETTING} must be unset, \"on\" or \"off\"")


def _sha(data) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def _body_bytes(body) -> bytes:
    if hasattr(body, "raw"):
        raw = body.raw()
        return raw if isinstance(raw, bytes) else str(raw).encode()
    if hasattr(body, "text"):
        return body.text().encode()
    return json.dumps(body.json(), sort_keys=True).encode()


def _body_text(body) -> str:
    if hasattr(body, "text"):
        return body.text()
    return _body_bytes(body).decode("utf-8", "replace")


def _json(text):
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def build_record(name, collector, *, exc=None, latency_ms=None, with_text=False) -> dict:
    """The generation record for one call. Never raises."""
    rec: dict = {"name": name, "level": "ERROR" if exc is not None else "DEFAULT"}
    if exc is not None:
        rec["status_message"] = type(exc).__name__
    if latency_ms is not None:
        rec["latency_ms"] = latency_ms
    try:
        log = collector.last
        calls = list(getattr(log, "calls", None) or [])
        if not calls:
            return rec
        call = next((c for c in calls if getattr(c, "selected", False)), calls[-1])
        try:
            rec["client_name"] = call.client_name
        except Exception:  # noqa: BLE001
            pass
        req, resp = call.http_request, call.http_response
        req_json = None
        if req is not None:
            req_bytes = _body_bytes(req.body)
            req_json = _json(req_bytes.decode("utf-8", "replace"))
            rec["model"] = req_json.get("model")
            rec["prompt_sha256"] = _sha(req_bytes)
            rec["model_parameters"] = {k: req_json[k] for k in _PARAM_KEYS if k in req_json}
        resp_text = None
        if resp is not None:
            resp_text = _body_text(resp.body)
            resp_json = _json(resp_text)
            rec["reply_sha256"] = _sha(resp_text)
            mv = resp_json.get("model")
            if mv:
                fp = resp_json.get("system_fingerprint")
                mv = f"{mv}@{fp}" if fp else mv
            rec["model_version"] = mv or None
        u = call.usage
        usage = {}
        for k in ("input_tokens", "output_tokens", "cached_input_tokens"):
            v = getattr(u, k, None)
            if v is not None:
                usage[k] = v
        rec["usage"] = usage
        if latency_ms is None and call.timing is not None:
            rec["latency_ms"] = call.timing.duration_ms
        if with_text:
            if req_json is not None:
                rec["input"] = req_json.get("messages")
            out = getattr(log, "raw_llm_response", None)
            rec["output"] = out if out is not None else resp_text
    except Exception:  # noqa: BLE001 -- a record is never load-bearing
        pass
    return rec


def _langfuse_on() -> bool:
    try:
        from telemetry import LANGFUSE_ENABLED  # type: ignore[no-redef]
    except Exception:  # noqa: BLE001
        try:
            from baml_shared.telemetry import LANGFUSE_ENABLED  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            return False
    return bool(LANGFUSE_ENABLED)


def langfuse_emit(rec: dict) -> None:
    """Send one generation; nests under the current OTel span. Fail-soft."""
    try:
        if not _langfuse_on():
            return
        from langfuse import get_client

        kw = {"name": rec["name"], "as_type": "generation", "level": rec.get("level")}
        if rec.get("model"):
            kw["model"] = str(rec["model"])
        if rec.get("model_parameters"):
            kw["model_parameters"] = {
                k: v if isinstance(v, (str, int, float, bool)) else json.dumps(v)
                for k, v in rec["model_parameters"].items()
            }
        usage = rec.get("usage") or {}
        ud = {}
        if "input_tokens" in usage:
            ud["input"] = usage["input_tokens"]
        if "output_tokens" in usage:
            ud["output"] = usage["output_tokens"]
        if "cached_input_tokens" in usage:
            ud["cached_input_tokens"] = usage["cached_input_tokens"]
        if ud:
            kw["usage_details"] = ud
        if rec.get("status_message"):
            kw["status_message"] = rec["status_message"]
        if "input" in rec:
            kw["input"] = rec["input"]
        if "output" in rec:
            kw["output"] = rec["output"]
        kw["metadata"] = {
            k: rec[k]
            for k in ("prompt_sha256", "reply_sha256", "model_version", "client_name", "latency_ms")
            if rec.get(k) is not None
        }
        get_client().start_observation(**kw).end()
    except Exception:  # noqa: BLE001 -- telemetry never breaks the call
        pass


class GenerationRecordingClient:
    """Wraps the BAML async client; each model call is recorded as one generation."""

    def __init__(self, inner, *, emit=None, log=None, collector_factory=None,
                 text_enabled: "bool | None" = None):
        self._text = read_trace_model_text() if text_enabled is None else bool(text_enabled)
        self._inner = inner
        self._emit = emit or langfuse_emit
        self._log = log or logging.getLogger(__name__)
        self._collector_factory = collector_factory

    def _new_collector(self):
        if self._collector_factory is not None:
            return self._collector_factory()
        import baml_py
        return baml_py.Collector()

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name[:1].isupper() and callable(attr):
            async def _recorded(*args, **kwargs):
                return await self._call(name, attr, args, kwargs)

            _recorded.__name__ = name
            return _recorded
        return attr

    async def _call(self, name, fn, args, kwargs):
        collector = None
        try:
            opts = kwargs.get("baml_options")
            # A caller's own collector: leave the call untouched, record nothing.
            if opts is None or (isinstance(opts, dict) and opts.get("collector") is None):
                collector = self._new_collector()
                kwargs = dict(kwargs)
                kwargs["baml_options"] = {**(opts or {}), "collector": collector}
        except Exception:  # noqa: BLE001
            collector = None
        if collector is None:
            return await fn(*args, **kwargs)
        t0 = time.monotonic()
        exc = None
        try:
            return await fn(*args, **kwargs)
        except BaseException as e:
            exc = e
            raise
        finally:
            try:
                ms = int((time.monotonic() - t0) * 1000)
                rec = build_record(name, collector, exc=exc, latency_ms=ms, with_text=self._text)
                self._emit(rec)
                self._log.info("generation: %s sha8=%s", name, (rec.get("prompt_sha256") or "")[:8])
            except Exception:  # noqa: BLE001
                pass
