"""Where a lineage walk starts: the asset the resolver already identified.

Ruling: the lineage engine receives the resolved asset and walks from it,
filtered by platform. It never re-derives a subject that was resolved
upstream. PURE module -- no network, no framework -- so the start-of-walk
decision can be tested without importing the engine. Nothing here names a
platform, vendor or kind; the case lives in configuration and in the data.
"""

from __future__ import annotations


def supplied_instance(semantic_ctx: dict, threaded_label: str = "") -> tuple[str, str]:
    """Return ``(instance_id, label)`` from the resolution context.

    The supervisor path flattens the instance to a top-level ``instance_id``;
    the legacy path carries the raw resolver JSON, where it sits under
    ``provenance.instance_id`` / ``provenance.instance_label``. The top level
    wins; a threaded label wins over the provenance label. A missing or
    non-dict ``provenance`` is tolerated.
    """
    ctx = semantic_ctx if isinstance(semantic_ctx, dict) else {}
    prov = ctx.get("provenance")
    if not isinstance(prov, dict):
        prov = {}
    instance_id = (
        str(ctx.get("instance_id") or "").strip()
        or str(prov.get("instance_id") or "").strip()
    )
    label = (
        str(threaded_label or "").strip()
        or str(prov.get("instance_label") or "").strip()
    )
    return instance_id, label


def start_of(instance_id: str) -> str:
    """Classify the start of a walk: ``"urn"`` for a URN, ``"name"`` for any
    other non-empty id (to be searched), ``"none"`` for an empty id.
    """
    if instance_id.startswith("urn:"):
        return "urn"
    return "name" if instance_id else "none"


def walk_body(subject_urn: str, platform_scope: dict, entitled_domains, caller_email) -> dict | None:
    """Build the JSON body of the platform-filtered lineage walk, or None.

    None means no walk: a platform was mentioned but none was recognised, so
    walking would answer a question nobody asked. Otherwise the body carries
    the subject, the platform filter (empty means every platform), the
    caller's entitled domains and the caller's email.
    """
    if platform_scope["platform_mentioned"] and not platform_scope["platforms"]:
        return None
    return {
        "subject_urn": subject_urn,
        "platforms": platform_scope["platforms"],
        "entitled_domains": entitled_domains,
        "caller_email": caller_email,
    }
