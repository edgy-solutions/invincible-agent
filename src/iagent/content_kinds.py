"""The content-kind registry (ADR-0021, ADR-0041 §4/§8; SDK `iagent_mesh.ingest`, 0.9.7).

`registrations()` composes this platform's seed (empty — the mapping table is chartable and
domain-owned, the same reason `iagent_mesh.task_kinds` ships no rows of its own) with a
deployment's overlay directories, read from `CONTENT_KIND_OVERLAY_DIRS` the same way
`human_tasks.py` reads `TASK_KIND_OVERLAY_DIRS` (colon/pathsep-separated directories, composed
in order via `iagent_mesh.ingest.compose`, ADR-0036).

FAIL CLOSED, NOT FAIL OPEN, AND THAT IS A DELIBERATE DIFFERENCE FROM `human_tasks._declared_kinds`.
That function returns `None` on an unreadable registry and falls back to "today's behaviour" --
because withholding a task-kind decision is the dangerous direction for that gate (R-012's
asymmetry). Here the registry governs `manifest["domain_type"]` and whether an arriving event
seeds a workflow (sections 1/3 of the ingest/origin seam spec) -- a silently-empty registry would
not refuse anything, it would just stop stamping the domain and stop starting workflows, which is
a silent CORRECTNESS regression, not a safety one. So a load error here RAISES: there is no
not-registered fallback that is safer than knowing the registry could not be read.

Cached on SUCCESS only. A transient failure (a mistyped path at pod start, before a ConfigMap
remount) is retried on the next call rather than pinned as a permanent failure for the process's
lifetime.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iagent_mesh.ingest import ContentKindRegistration

#: The platform seed: README only, no rows. See module docstring.
_SEED_DIR = Path(__file__).resolve().parents[2] / "policy" / "content_kinds"

#: Colon/pathsep-separated overlay directories, read the same way `human_tasks.py` reads
#: `TASK_KIND_OVERLAY_DIRS` -- see that module's `_OVERLAY_DIRS_ENV`.
_OVERLAY_DIRS_ENV = "CONTENT_KIND_OVERLAY_DIRS"

_REGISTRATIONS_CACHE: "tuple[ContentKindRegistration, ...] | None" = None


def registrations() -> "tuple[ContentKindRegistration, ...]":
    """Every composed content-kind registration (seed + overlays), cached on success.

    Raises whatever `iagent_mesh.ingest.compose` raises (a `DeclarationError`, or a pydantic
    `ValidationError` from a row the SDK's `ContentKindRegistration` validator rejects) -- fail
    closed, no empty fallback. See module docstring for why this gate differs from
    `human_tasks._declared_kinds`.
    """
    global _REGISTRATIONS_CACHE
    if _REGISTRATIONS_CACHE is not None:
        return _REGISTRATIONS_CACHE
    from iagent_mesh.ingest import compose  # noqa: PLC0415

    raw = (os.getenv(_OVERLAY_DIRS_ENV) or "").strip()
    overlay_dirs = [p for p in (s.strip() for s in raw.split(os.pathsep)) if p] if raw else []
    rows = tuple(compose(_SEED_DIR, overlay_dirs))
    _REGISTRATIONS_CACHE = rows
    return rows


def by_kind(kind: str) -> "ContentKindRegistration | None":
    """The registration for `kind`, or None if it is not registered.

    Deliberately NOT `iagent_mesh.ingest.resolve_content_kind` (which HALTs by raising
    `ContentKindUnregistered`) -- this seam's own callers (gateway's `/ingest` route) treat
    "declared but not registered" as "behaviour unchanged", not a halt; the HALT case belongs to
    the driver that resolves `content_kind` against `manifest.metadata`, not to this lookup.
    """
    if not kind:
        return None
    for row in registrations():
        if row.kind == kind:
            return row
    return None
