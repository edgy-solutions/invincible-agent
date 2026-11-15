"""Loader for span_taxonomy.yaml: the declared span names (lane/perf brief).

Fail-soft on purpose: a missing or malformed file yields an empty dict rather than an
import error, because telemetry support must never stop a service starting. Enforcement
that every emitted name is declared lives in tests/perf, not here.
"""
from __future__ import annotations

import os

_PATH = os.path.join(os.path.dirname(__file__), "span_taxonomy.yaml")


def _load() -> dict[str, dict]:
    try:
        import yaml
        with open(_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        spans = data.get("spans") or {}
        return {str(k): dict(v or {}) for k, v in spans.items()}
    except Exception:  # noqa: BLE001 - absent/garbled taxonomy -> empty, never a crash
        return {}


SPAN_NAMES: dict[str, dict] = _load()


def declared(name: str) -> bool:
    return name in SPAN_NAMES
