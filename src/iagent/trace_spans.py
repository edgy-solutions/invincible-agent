"""One Langfuse trace per answer: BFF root span, a child span per Dagster step, W3C traceparent.

Why this exists: each Dagster step runs in its own subprocess, and the BFF streams SSE from
an async generator. Neither can share an in-process OTel context, so the BFF hands the
supervisor a ``traceparent`` string (in the run config) and each step re-parents onto it.

Fail-soft throughout (the witness-channel axiom, as in baml_shared/telemetry.py): when the
Langfuse keys are unset every helper is a no-op, and no telemetry error ever reaches the
work. An exception from the wrapped BODY always propagates unchanged.

Every span name passed to ``step_span`` / ``open_request_span`` must be declared in
baml_shared/span_taxonomy.yaml; pass names as string literals so tests/perf can scan them.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

_TP_RE = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def _enabled() -> bool:
    # Read at call time (not import) so late-set env and tests behave; same gate as
    # baml_shared/telemetry.py.
    return bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))


def _miss(what: str, exc: BaseException) -> None:
    logger.debug("trace_spans: %s failed: %s", what, exc)


def _valid_ids(trace_id: str, span_id: str) -> bool:
    return bool(
        isinstance(trace_id, str) and isinstance(span_id, str)
        and re.fullmatch(r"[0-9a-f]{32}", trace_id) and re.fullmatch(r"[0-9a-f]{16}", span_id)
        and int(trace_id, 16) and int(span_id, 16)
    )


def traceparent_for(trace_id_hex: str, span_id_hex: str) -> str:
    """W3C traceparent for a span; "" when either id is missing or malformed."""
    if not _valid_ids(trace_id_hex, span_id_hex):
        return ""
    return f"00-{trace_id_hex}-{span_id_hex}-01"


def parse_traceparent(value: str) -> Optional[dict]:
    """``{"trace_id", "parent_span_id"}`` (Langfuse trace_context keys) or None if malformed."""
    if not isinstance(value, str):
        return None
    m = _TP_RE.match(value.strip())
    if not m or m.group(1) != "00" or not _valid_ids(m.group(2), m.group(3)):
        return None
    return {"trace_id": m.group(2), "parent_span_id": m.group(3)}


def current_traceparent() -> str:
    """traceparent of the current OTel span, for outgoing calls; "" when none/disabled."""
    if not _enabled():
        return ""
    try:
        from opentelemetry import trace as otel_trace
        ctx = otel_trace.get_current_span().get_span_context()
        if not ctx.is_valid:
            return ""
        return traceparent_for(f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}")
    except Exception as exc:  # noqa: BLE001
        _miss("current_traceparent", exc)
        return ""


def _trace_context(client: Any, trace_seed: str, traceparent: str) -> Optional[dict]:
    # An explicit parent wins (it joins the BFF's span); a seed makes the trace id the same
    # one engines derive from X-Trace-Id; neither -> let the SDK mint a fresh trace.
    parent = parse_traceparent(traceparent) if traceparent else None
    if parent:
        return parent
    if trace_seed:
        return {"trace_id": client.create_trace_id(seed=trace_seed)}
    return None


@contextmanager
def step_span(name: str, *, trace_seed: str = "", traceparent: str = "") -> Iterator[None]:
    """Span around a SYNC Dagster op body, current in OTel context for its duration.

    flush() in ``finally`` is required: the multiprocess executor exits the step's
    subprocess right after, which would lose the SDK's background batch.
    """
    if not _enabled():
        yield
        return
    client = None
    cm = None
    span = None
    try:
        from langfuse import get_client
        client = get_client()
        cm = client.start_as_current_observation(
            name=name, as_type="span",
            trace_context=_trace_context(client, trace_seed, traceparent),
        )
        span = cm.__enter__()
    except Exception as exc:  # noqa: BLE001
        _miss("step_span open", exc)
        cm = None
    try:
        try:
            yield
        except BaseException as body_exc:
            if cm is not None:
                try:
                    span.update(level="ERROR", status_message=type(body_exc).__name__)
                except Exception as exc:  # noqa: BLE001
                    _miss("step_span error mark", exc)
            raise
        finally:
            if cm is not None:
                try:
                    cm.__exit__(None, None, None)
                except Exception as exc:  # noqa: BLE001
                    _miss("step_span close", exc)
    finally:
        if client is not None:
            try:
                client.flush()
            except Exception as exc:  # noqa: BLE001
                _miss("step_span flush", exc)


def _config_ids(fn: Any, args: tuple, kwargs: dict) -> tuple:
    # The op's `config` argument carries trace_id/traceparent. Found by keyword, else by
    # position via the original signature; absent or odd configs yield empty strings.
    try:
        cfg = kwargs.get("config")
        if cfg is None:
            cfg = inspect.signature(fn).bind_partial(*args, **kwargs).arguments.get("config")
    except Exception:  # noqa: BLE001
        cfg = None
    return str(getattr(cfg, "trace_id", "") or ""), str(getattr(cfg, "traceparent", "") or "")


def step_spanned(name: str):
    """Decorator form of ``step_span`` for Dagster ops, placed UNDER ``@op`` (``@op`` outermost).

    Why a decorator and not a wrapper function: the op bodies are pinned by name by seals
    in other lanes, so they stay exactly where and as named. functools.wraps keeps
    __name__, __wrapped__ and the signature, so Dagster sees the original parameters.
    A generator op (DynamicOut) gets a generator wrapper so it keeps its semantics.
    """
    def deco(fn):
        if inspect.isgeneratorfunction(fn):
            @functools.wraps(fn)
            def gen_wrapper(*args, **kwargs):
                seed, tp = _config_ids(fn, args, kwargs)
                with step_span(name, trace_seed=seed, traceparent=tp):
                    yield from fn(*args, **kwargs)
            return gen_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            seed, tp = _config_ids(fn, args, kwargs)
            with step_span(name, trace_seed=seed, traceparent=tp):
                return fn(*args, **kwargs)
        return wrapper
    return deco


class RequestSpan:
    """Handle for the BFF root span. Non-current on purpose: an async generator's yields
    may resume in a different Context, where an attached OTel token would fail to detach."""

    def __init__(self, client: Any = None, span: Any = None, traceparent: str = "") -> None:
        self._client = client
        self._span = span
        self.traceparent = traceparent

    def _end(self) -> tuple:
        # Idempotent: the generator's finally may run after an earlier close.
        span, client, self._span = self._span, self._client, None
        if span is None:
            return None, None
        try:
            span.end()
        except Exception as exc:  # noqa: BLE001
            _miss("request_span end", exc)
        return client, span

    def close(self) -> None:
        client, span = self._end()
        if span is None:
            return
        try:
            client.flush()
        except Exception as exc:  # noqa: BLE001
            _miss("request_span flush", exc)

    async def aclose(self) -> None:
        client, span = self._end()
        if span is None:
            return
        # flush() blocks on the network; keep it off the event loop. Scheduled, NOT awaited:
        # the BFF is long-lived and its exporter flushes in the background, so the flush only
        # needs to happen soon, and awaiting it would hold the response open for a Langfuse
        # round trip (tail latency on exactly what lane/perf measures).
        try:
            asyncio.get_running_loop().run_in_executor(None, client.flush)
        except Exception as exc:  # noqa: BLE001
            _miss("request_span flush", exc)


def open_request_span(*, name: str = "bff.orchestrate", trace_seed: str, session_id: str,
                      user_id: str) -> RequestSpan:
    """Open the ``bff.orchestrate`` root span. No input/output: the question and answer are
    content-bearing (telemetry-mapping.yaml ``content_bearing``) and stay out of the trace."""
    if not _enabled():
        return RequestSpan()
    try:
        from langfuse import get_client
        client = get_client()
        tc = {"trace_id": client.create_trace_id(seed=trace_seed)} if trace_seed else None
        span = client.start_observation(name=name, as_type="span", trace_context=tc)
        handle = RequestSpan(client, span, traceparent_for(span.trace_id, span.id))
    except Exception as exc:  # noqa: BLE001
        _miss("open_request_span", exc)
        return RequestSpan()
    _set_trace_attrs(span, session_id, user_id)
    return handle


def _set_trace_attrs(span: Any, session_id: str, user_id: str) -> None:
    # SDK v4 has no update_trace; trace attributes go through propagate_attributes, which
    # stamps the CURRENT span. Make the root current only for this synchronous block
    # (attach and detach in one frame, no yield between), then drop it again.
    try:
        from langfuse import propagate_attributes
        from opentelemetry import trace as otel_trace
        attrs: dict = {"trace_name": "answer", "tags": ["cortex-bff"]}
        if session_id:
            attrs["session_id"] = str(session_id)[:200]
        if user_id:
            attrs["user_id"] = str(user_id)[:200]
        with otel_trace.use_span(span._otel_span, end_on_exit=False):
            with propagate_attributes(**attrs):
                pass
    except Exception as exc:  # noqa: BLE001
        _miss("request_span attrs", exc)


def close_request_span(handle: RequestSpan) -> None:
    handle.close()


async def aclose_request_span(handle: RequestSpan) -> None:
    await handle.aclose()
