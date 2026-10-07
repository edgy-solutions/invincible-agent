"""The exported package's verification harness. STDLIB ONLY.

This module is embedded into the self-contained HTML page verbatim and runs inside Pyodide,
in the recipient's browser, with no network reach (ADR-0047 §8.2). It is also imported
directly, in CPython, by `scripts/build_fin_package.py`'s own build-time refusal (`verify`
must reproduce every served panel over the NARROWED state before the artifact may be
written) and by `tests/finance/test_fin_package_export.py`'s "page logic in CPython" seal.
ONE FUNCTION, TWO CALLERS — the build and the browser run the identical check, which is the
whole reason a divergence caught at build time is the same divergence the recipient's own
re-run would have found.

NOTHING HERE CHOOSES A VIEW. This harness answers one question only — does re-running the
pinned algorithm over the embedded state reproduce the rows the package claims to serve — and
leaves what a panel LOOKS like to markup this module does not touch.
"""
from __future__ import annotations

import json
from typing import Any

try:  # flat in the image (/app) and inside the embedded page's Pyodide FS
    import measures
    import state_codec
except ImportError:
    from agent_fleet.finance_agent import measures
    from agent_fleet.finance_agent import state_codec


def _canonical(obj: Any) -> str:
    """SAME SERIALISATION as `export._canonical` — stdlib-only here, because this module is
    embedded into the page and `export.py` is not (it imports nothing the browser cannot
    resolve either, but duplicating the one function is cheaper than embedding a fourth
    module whose only use inside Pyodide would be this one line)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def verify(state_dict: dict[str, Any], panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild `FinanceState` from `state_dict` and re-run each panel's verb against it.

    `panels` is `[{panel, verb, fn, params, rows}, ...]` — the SERVED rows, exactly as
    `_measure_envelope` produced them (never recomputed here; recomputing the comparison
    target from the same run as the thing being checked would make this function unable to
    ever disagree with itself). Returns one entry per panel:

        {"panel": i, "verb": ..., "reproduced": bool, "detail": str}

    `reproduced` is False on ANY divergence — a different row set, or the measure itself
    refusing (`NotInModel`, `MethodRequired`, or any other exception) where the served
    envelope held rows. A refusal here over data that once answered is exactly the
    "cost of guessing" case this engine already treats as load-bearing: silence about it
    would let a stale or tampered state pass as verified.
    """
    state = state_codec.state_from_dict(state_dict)
    results: list[dict[str, Any]] = []
    for p in panels:
        fn = p["fn"]
        func = getattr(measures, fn, None)
        if func is None:
            results.append({
                "panel": p["panel"], "verb": p["verb"], "reproduced": False,
                "detail": f"measure {fn!r} is not present in this package's embedded measures.py",
            })
            continue
        try:
            rows = func(state, **p["params"])
        except Exception as exc:  # noqa: BLE001 - ANY divergence is reported, never swallowed
            results.append({
                "panel": p["panel"], "verb": p["verb"], "reproduced": False,
                "detail": f"re-running {fn!r} raised {exc.__class__.__name__}: {exc}",
            })
            continue
        reproduced = _canonical(rows) == _canonical(p["rows"])
        results.append({
            "panel": p["panel"], "verb": p["verb"], "reproduced": reproduced,
            "detail": "matches the served rows" if reproduced
            else "re-running the pinned algorithm over the embedded state produced DIFFERENT rows",
        })
    return results
