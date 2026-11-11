"""Span helpers for the BFF, the Dagster supervisor and engine-docs /explain (#327).

Ruling (architect, 2026-11-10): the BFF mints a trace id when the caller sends none. The BFF,
the supervisor and engine-docs ``/explain`` get spans on provenance-telemetry 0.2.1's primitives
(``observed_trace``), with the parent id passed as the ``parent_span_id=`` keyword. The hop
carries it as ``X-Parent-Span-Id`` next to ``X-Trace-Id`` (headers) and ``parent_span_id``
(Dagster run config). Everything here is fail-soft: telemetry never breaks the observed work.
"""
from __future__ import annotations

import functools
import importlib.util
import inspect
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _load_shim() -> Any:
    # One module object. In the cortex-bff image /app/telemetry.py is the shim.
    try:
        import telemetry as _t  # type: ignore[import-not-found]
        if hasattr(_t, "build_trace_values"):
            return _t
    except Exception:  # noqa: BLE001
        pass
    try:
        if "telemetry" in sys.modules:
            return sys.modules["telemetry"]
        path = Path(__file__).resolve().parents[2] / "baml_shared" / "telemetry.py"
        spec = importlib.util.spec_from_file_location("telemetry", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["telemetry"] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop("telemetry", None)
            raise
        return mod
    except Exception:  # noqa: BLE001
        return None


_t = _load_shim()

try:
    observed_trace = _t.observed_trace
    MAPPING = _t.MAPPING
    build_trace_values = _t.build_trace_values
    flush = _t.flush
except Exception:  # noqa: BLE001  no-op stubs: the mesh runs identically without telemetry

    @contextmanager
    def observed_trace(*_a, **_k):  # type: ignore[misc]
        yield None

    MAPPING = None

    def build_trace_values(**_k):  # type: ignore[misc]
        return {}

    def flush(*_a, **_k):  # type: ignore[misc]
        return None


def mint_trace_id() -> str:
    return uuid.uuid4().hex


def request_trace_id(header_value: str | None) -> str:
    v = (header_value or "").strip()
    return v if v else mint_trace_id()


def current_span_id() -> str:
    try:
        from opentelemetry import trace as otel_trace
        ctx = otel_trace.get_current_span().get_span_context()
        return format(ctx.span_id, "016x") if ctx.is_valid else ""
    except Exception:  # noqa: BLE001
        return ""


def _config_of(fn: Any, args: tuple, kwargs: dict) -> Any:
    # The op's `config` argument: by keyword, else by position via the original signature.
    try:
        cfg = kwargs.get("config")
        if cfg is None:
            cfg = inspect.signature(fn).bind_partial(*args, **kwargs).arguments.get("config")
        return cfg
    except Exception:  # noqa: BLE001
        return None


def _safe_flush() -> None:
    # Each Dagster step is its own process and exits before the batch exporter's timer fires,
    # so the step flushes itself.
    try:
        flush()
    except Exception:  # noqa: BLE001
        pass


def step_spanned(name: str):
    """Decorator for Dagster ops, placed UNDER ``@op``. Spans the step when its config
    carries a ``trace_id``; otherwise calls straight through (no span, no flush)."""
    def _span(cfg: Any):
        return observed_trace(
            MAPPING,
            build_trace_values(
                trace_id=cfg.trace_id,
                session_id=getattr(cfg, "session_id", "") or None,
                engine="dagster-supervisor",
                verb=name,
            ),
            name=name,
            parent_span_id=getattr(cfg, "parent_span_id", "") or None,
        )

    def deco(fn):
        if inspect.isgeneratorfunction(fn):
            @functools.wraps(fn)
            def gen_wrapper(*args, **kwargs):
                cfg = _config_of(fn, args, kwargs)
                if cfg is None or not getattr(cfg, "trace_id", ""):
                    yield from fn(*args, **kwargs)
                    return
                try:
                    with _span(cfg):
                        yield from fn(*args, **kwargs)
                finally:
                    _safe_flush()
            return gen_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            cfg = _config_of(fn, args, kwargs)
            if cfg is None or not getattr(cfg, "trace_id", ""):
                return fn(*args, **kwargs)
            try:
                with _span(cfg):
                    return fn(*args, **kwargs)
            finally:
                _safe_flush()
        return wrapper
    return deco
