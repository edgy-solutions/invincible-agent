"""Deterministic chart_data normalizer for the Recharts widget.

Extracted to a dep-free module so pure-unit tests can import it
without dragging FastAPI / BAML / uvicorn. The router file
(``main.py``) imports from here.

Why this lives here rather than in the BAML prompt: the widget
hardcodes ``dataKey="name"`` and ``dataKey="value"`` on its
Recharts ``<XAxis>`` and ``<Bar>``. That's the real contract — only
the React component knows the required keys. Asking the LLM
(RenderAsChart's prompt) to rename keys to ``name``/``value`` works
*probably* but leaves shape-conformance to a model that can
hallucinate field names on weird inputs and silently empty the
chart. The §1 principle the project has converged on everywhere
else applies: **LLMs produce data, deterministic steps conform shape.**
"""

from __future__ import annotations

import json
import numbers
import re
from typing import Any, Optional


def normalize_chart_data_to_recharts(raw_data: Any) -> Optional[str]:
    """Coerce an arbitrary chart payload into the exact shape
    ``cortex-ui/src/components/mesh/ChartWidget.tsx`` reads:
    a JSON-stringified array of ``{"name": str, "value": number}``
    objects.

    Accepts the three shapes Engine DA's smolagent typically returns:

    * dict-of-counts/measures: ``{"US-East": 3, "US-West": 2, ...}``
      → category=key, measure=value.
    * list-of-records with named fields:
      ``[{"region": "US-East", "count": 3}, ...]``
      → first non-numeric field is category, first numeric field is
      measure.
    * already-normalized ``[{"name": "...", "value": ...}, ...]``
      → returned unchanged.

    Returns the JSON-stringified array on success, ``None`` when the
    payload doesn't look like chart data (the caller falls back to
    letting BAML do its best, preserving the prior behavior for
    unrecognized shapes).
    """
    payload: Any = raw_data
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            # Sometimes DA's smolagent returns Python-repr (single
            # quotes) rather than JSON — try a quick coerce so we
            # don't fall through to the LLM for a recoverable input.
            try:
                if re.match(r"^\s*[\[{].*[\]}]\s*$", payload, re.S):
                    payload = json.loads(payload.replace("'", '"'))
                else:
                    return None
            except Exception:
                return None

    # Shape 1: dict-of-counts/measures.
    if isinstance(payload, dict):
        rows = [
            {"name": str(k), "value": v}
            for k, v in payload.items()
            if isinstance(v, numbers.Number) and not isinstance(v, bool)
        ]
        if rows:
            return json.dumps(rows)
        return None

    if not isinstance(payload, list) or not payload:
        return None

    # Shape 3 first: already-normalized.
    if all(
        isinstance(r, dict) and "name" in r and "value" in r
        for r in payload
    ):
        return json.dumps([{"name": str(r["name"]), "value": r["value"]} for r in payload])

    # Shape 2: list of records with named fields. Pick category =
    # first non-numeric field, measure = first numeric field. This is
    # deterministic on the row schema, independent of the LLM's
    # choice of field names.
    if not all(isinstance(r, dict) for r in payload):
        return None

    first = payload[0]
    category_key = next(
        (k for k, v in first.items()
         if not isinstance(v, numbers.Number) or isinstance(v, bool)),
        None,
    )
    measure_key = next(
        (k for k, v in first.items()
         if isinstance(v, numbers.Number) and not isinstance(v, bool)),
        None,
    )
    if category_key is None or measure_key is None:
        return None
    return json.dumps(
        [
            {"name": str(r[category_key]), "value": r[measure_key]}
            for r in payload
            if category_key in r and measure_key in r
        ]
    )
