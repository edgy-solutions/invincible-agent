"""Validate a payload against a REGISTERED contract (ADR-0017 amendment, slice 2c).

WHAT THIS REPLACES. `chart_normalizer.normalize_chart_data_to_recharts` COERCED chart data
into `[{"name": str, "value": number}]` because the widget was believed to hardcode
`dataKey="name"` / `dataKey="value"`. That belief is stale: ChartWidget INFERS its keys
(xKey = first categorical, valueKey = first numeric) and accepts any array of objects with
at least one numeric column. The coercion was therefore INFORMATION-DESTROYING -- data the
component could have drawn as multi-series or scatter was flattened to single-series before
it ever arrived, and nothing failed, which is why it went unnoticed for months.

So the coercion is DEAD COMPENSATION and is deleted. What survives is the half that was
always legitimate: deciding whether a payload is RENDERABLE, so an unrenderable one routes
to the honest KNOWLEDGE_DOCUMENT fallback instead of an empty widget reading as a
malfunction.

THE DIFFERENCE THAT MATTERS: the old code answered "can I reshape this?" and treated "no"
as unrenderable -- which meant a payload the COMPONENT could draw but the NORMALIZER could
not reshape was thrown away (witnessed at work 2026-08-15). This answers "does this satisfy
the component's own published contract?", which is the question that was always being asked.

REASONS COME FROM THE CONTRACT, NOT FROM HERE. The refusal strings are the ones
ChartWidget.contract.ts publishes and its test suite proves the component can emit. That is
why the vocabulary is trustworthy: a reason this validator returns is a reason the component
would have produced for the same payload. The one reason that could NOT be emitted was
caught by that suite on its first run and unpublished.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

# Fallback requirements, used when a caller registered no typed contract (legacy rows).
# Mirrors ChartWidget.contract.ts CHART_ROW_REQUIREMENTS. Kept minimal deliberately: this
# is the floor for an UNTYPED registration, not a second home for the contract.
_DEFAULT_CHART_REQUIREMENTS = {
    "minRows": 1,
    "minNumericColumns": 1,
    "minCategoricalColumnsForCategoricalAxis": 1,
    "categoricalAxisTypes": ["BAR", "LINE", "PIE"],
    "minNumericColumnsForScatter": 2,
}


def _parse_rows(chart_data: Any) -> Tuple[Optional[List[Any]], Optional[str]]:
    """chart_data -> rows, or a refusal reason.

    `chart_data` is a JSON-ENCODED STRING, not an array -- the single most surprising fact
    in the contract and the one `expected_fields` could never carry.
    """
    if chart_data is None:
        return None, "no rows"
    if isinstance(chart_data, list):
        return chart_data, None
    if isinstance(chart_data, str):
        s = chart_data.strip()
        if not s:
            return None, "no rows"
        try:
            parsed = json.loads(s)
        except Exception:
            try:
                parsed = json.loads(s.replace("'", '"'))
            except Exception:
                return None, "JSON parse failure"
        if not isinstance(parsed, list):
            return None, "not an array"
        return parsed, None
    return None, "not an array"


def validate_chart_payload(
    chart_data: Any,
    chart_type: Optional[str] = None,
    contract: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return a refusal reason, or None when the payload is renderable.

    Column classification mirrors the component exactly: by the FIRST ROW's value types,
    `number` -> numeric, `str` -> categorical, everything else ignored. Booleans are NOT
    numeric here because JS `typeof true === "boolean"`, and a validator that disagreed
    with the component about a bool would accept a payload the component then refuses.
    """
    req = dict(_DEFAULT_CHART_REQUIREMENTS)
    if isinstance(contract, dict):
        declared = contract.get("rowRequirements")
        if isinstance(declared, dict):
            req.update(declared)

    rows, reason = _parse_rows(chart_data)
    if reason:
        return reason
    if len(rows) < int(req.get("minRows", 1)):
        return "no rows"

    first = rows[0]
    if not isinstance(first, dict):
        return "rows aren't objects"

    numeric, categorical = [], []
    for k, v in first.items():
        if isinstance(v, bool):
            continue  # matches the component: typeof true === "boolean", not "number"
        if isinstance(v, (int, float)):
            numeric.append(k)
        elif isinstance(v, str):
            categorical.append(k)

    if len(numeric) < int(req.get("minNumericColumns", 1)):
        return "no numeric column"

    ctype = (chart_type or "").upper()
    if ctype == "SCATTER":
        if len(numeric) < int(req.get("minNumericColumnsForScatter", 2)):
            return "scatter requires 2 numeric columns (x and y)"
        return None

    axis_types = req.get("categoricalAxisTypes") or _DEFAULT_CHART_REQUIREMENTS["categoricalAxisTypes"]
    if not ctype or ctype in axis_types:
        if len(categorical) < int(req.get("minCategoricalColumnsForCategoricalAxis", 1)):
            return "no categorical column"
    return None
