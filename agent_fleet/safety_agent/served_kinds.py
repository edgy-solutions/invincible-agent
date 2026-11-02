"""The task-kind declarations the draft card READS -- never restates (standing rule, 2026-10-30).

The risk-acceptance card names a task kind and the verbs that need a stated reason. Both are the
deployment's declarations: the kind is the head of the audience key the ratified matrix carries
(`acceptanceAudience` = `<task_kind>:<compartment>`), and `reason_required` is a field of that
kind's composed task-kind row. Code implements the mechanism; the rows name the case.

WHICH COMPOSITION THIS IS, AND WHY NOT `human_tasks`. The gateway reads the rows through
`human_tasks._declared_kinds()`: `compose(policy/task_kinds, TASK_KIND_OVERLAY_DIRS)`. That module
is `src/iagent`, which the flattened engine image does not carry. What the image DOES carry is
the SDK (`iagent_mesh`, pinned in this engine's pyproject), `COPY policy/overlays/` (the sample
overlay holds the risk-acceptance rows), and `TASK_KIND_OVERLAY_DIRS` through the chart's shared
ConfigMap (`envFrom` in engines.yaml). So this calls the SAME composer on the SAME overlay list.
The structural seed (`policy/task_kinds/`) is not baked into the image and is not widened in for
this: a row an overlay declares is a FULL replacement by key, so the overlay alone is the row the
server reads for these kinds. tests/safety/test_the_card_reads_the_served_kind_declaration.py
asserts the two compositions agree row for row.

A DECLARATION THIS PROCESS CANNOT READ IS NOT AN EMPTY ONE. Unset variable, a path that is not
there, or a kind no row names: all raise `ServedDeclarationUnavailable`, and the caller refuses
the draft naming the variable. Falling back to a copy here would be the restated value again.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

OVERLAY_DIRS_ENV = "TASK_KIND_OVERLAY_DIRS"

#: `compose(seed, overlays)` needs a seed argument; a seed directory that is not there composes
#: to nothing (measured against iagent-mesh 0.9.10), which is exactly "overlay rows only".
_NO_SEED = Path("task_kinds.no-seed-in-this-image")

_CACHE: Dict[str, Dict[str, object]] = {}


class ServedDeclarationUnavailable(Exception):
    """The declaration the card must carry cannot be read; the draft refuses rather than guess."""


def _composed() -> Dict[str, object]:
    raw = (os.getenv(OVERLAY_DIRS_ENV) or "").strip()
    if not raw:
        raise ServedDeclarationUnavailable(
            f"{OVERLAY_DIRS_ENV} is unset, so the task-kind rows the card must carry cannot be "
            "read. Set it to the deployment's overlay directories (the chart's shared ConfigMap "
            "sets it for every engine)."
        )
    if raw in _CACHE:
        return _CACHE[raw]
    overlays = [p for p in (s.strip() for s in raw.split(os.pathsep)) if p]
    missing = [p for p in overlays if not Path(p).is_dir()]
    if missing:
        raise ServedDeclarationUnavailable(
            f"{OVERLAY_DIRS_ENV} names {missing}, which are not directories here: unreadable, "
            "not empty."
        )
    try:
        from iagent_mesh.task_kinds import compose  # noqa: PLC0415
        rows = compose(_NO_SEED, overlays)
    except Exception as exc:  # the SDK's own error types, or its absence
        raise ServedDeclarationUnavailable(
            f"the task-kind rows under {OVERLAY_DIRS_ENV} did not compose: {exc}"
        ) from exc
    _CACHE[raw] = {str(r.kind): r for r in rows}
    return _CACHE[raw]


def kind_of_audience(audience: str) -> str:
    """The task kind an audience key names: `<task_kind>:<compartment>`, the key shape
    `policy/task_grants.yaml` and every `human_await` row use. Whether that kind is DECLARED is
    `declared_row`'s question."""
    head, sep, _ = str(audience or "").partition(":")
    if not sep or not head:
        raise ServedDeclarationUnavailable(
            f"audience {audience!r} is not '<task_kind>:<compartment>', so no task kind can be "
            "read from it"
        )
    return head


def declared_row(kind: str):
    rows = _composed()
    if kind not in rows:
        raise ServedDeclarationUnavailable(
            f"task kind {kind!r} is not declared by the rows under {OVERLAY_DIRS_ENV} "
            f"({sorted(rows)}); a kind no deployment composes accepts nothing at /act"
        )
    return rows[kind]


def reason_required_of(kind: str) -> List[str]:
    """The verbs the kind's own row requires a reason for, in the row's verb order."""
    row = declared_row(kind)
    required = set(row.reason_required)
    return [v for v in row.accepts if v in required]
