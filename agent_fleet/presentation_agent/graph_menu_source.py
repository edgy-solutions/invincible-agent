"""The registered menus, read from the GRAPH instead of a module-local dict.

WHY THIS EXISTS. `capability_registry._REGISTRY` is a module-level dict, and
registration and selection run in DIFFERENT PODS: `/register_frontend_capabilities`
is served by cortex-bff, `/render_ui` by presentation-agent. Registration could
therefore never reach the selector — every caller looked anonymous, the union was
always empty, and every answer fell to the labelled floor. 71 green tests proved
the LOGIC and never touched the TOPOLOGY.

ADR-0017's own mechanism was always the answer: `rendersAs` triples in the shared
Predicate collection, written by the mesh-registrar (sole writer, ADR-0006
Addendum) and read here. This module is that read, and NOTHING ELSE — it returns
entries in exactly the shape `_REGISTRY` held, so every consumer's logic is
untouched and menu-source-agnostic.

TWO HARD-WON TOLERANCES, both found by checking the cluster before writing this:

1. PAYLOAD-LESS PRESENTATION ROWS ARE NOT MENU ENTRIES. A presentation row with
   no `frontend_id` cannot belong to anyone's menu, and returning it would widen
   every anonymous union with a ghost duplicate of a real capability. Ten such
   rows existed after the row key gained its frontend component (the old-key rows
   were superseded, not updated). They were swept — but the skip is STRUCTURAL
   and permanent, because the next partial write, failed migration or interrupted
   re-register mints fresh ones, and a reader whose correctness depends on a clean
   substrate is a reader with a poisoned population. Orphans are counted and
   logged so they announce themselves instead of accumulating quietly.

2. KNOWN GAP — THIS READ IS NOT CONJUNCTIVE. The registrar writes BOTH stores
   and the system's stated invariant is that `/classify_predicate` "only sees
   verbs present in BOTH stores", which is what makes a half-written
   registration harmless everywhere else: benignly orphaned, therefore unrouted.
   This reader consults WEAVIATE ONLY, so a row whose Neo4j edge is missing --
   the exact debris a failed-and-compensated registration leaves -- is served as
   a valid menu entry.

   Observed 2026-08-21, not hypothesised: a saga bug compensated ten good writes,
   the Weaviate compensation addressed the wrong uuid and left the rows standing,
   and those ten orphans WOULD have been served to cortex-ui-desktop as its menu.
   The reader would have treated the debris of a failure as a registration.

   Not closed here, and deliberately so: honouring the invariant means a second
   round trip per read, and the right shape (a completeness marker written last,
   or a Neo4j-side confirm) is a design decision rather than a patch. It is
   STATED because an unstated gap becomes an assumed guarantee.

3. `recomputes` MAY NOT EXIST AS A PROPERTY AT ALL. Weaviate's auto-schema
   creates a property when something first WRITES it, and `recomputes` is
   tri-state: omitted when a component never declared it (ADR-0042 Ruling 9's
   honest default, per `_is_live_view` in ab0bcfd). So until the first live view
   registers, selecting that field is a GraphQL ERROR, not a null column —
   "absent means nothing" was designed one level too shallow, covering absent on
   the ROW and not absent from the SCHEMA. Property-not-exists reads as
   not-a-live-view, which is the same answer absence-on-the-row gives.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional

try:
    from agent_fleet.utils.uvicorn_safe_logging import ensure_stdout_logger
except ImportError:  # flattened image layout (/app/utils/...)
    try:
        from utils.uvicorn_safe_logging import ensure_stdout_logger  # type: ignore
    except ImportError:  # last resort — never leave the module unimportable
        def ensure_stdout_logger(name, **_):  # type: ignore
            return logging.getLogger(name)

logger = ensure_stdout_logger("presentation_graph_menu")

_COLLECTION = "Predicate"
_RENDERS_AS_LOCAL = "rendersAs"

#: Fields every presentation row must supply for the menu. `recomputes` is
#: deliberately NOT here — see tolerance 2 above.
_BASE_FIELDS = (
    "verb_iri",
    "input_uri",
    "output_uri",
    "tool_kind",
    "frontend_id",
    "archetype",
    "expected_fields",
    "description",
)


def _weaviate_http() -> Optional[str]:
    """Base URL for Weaviate's REST/GraphQL surface, or None when unconfigured.

    Unconfigured is NOT an error: it means this deployment has no graph source
    and the caller falls back to whatever it held before. Returning None rather
    than raising keeps a missing env var from turning /render_ui into a 500.
    """
    host = os.getenv("WEAVIATE_HOST") or os.getenv("WEAVIATE_URL")
    if not host:
        return None
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    port = os.getenv("WEAVIATE_PORT", "8080")
    return f"http://{host}:{port}" if ":" not in host else f"http://{host}"


def _gql(base: str, query: str, timeout: float) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(
        f"{base}/v1/graphql",
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.load(resp)
    if body.get("errors"):
        # Surfaced, not swallowed: a schema drift here silently empties every
        # menu, which reads exactly like "nobody has registered".
        logger.warning("graph menu query returned GraphQL errors: %s", body["errors"])
        return None
    return body.get("data") or None


def _schema_has_recomputes(base: str, timeout: float) -> bool:
    """Does the collection have the `recomputes` property YET?

    Selecting a property Weaviate has never had written is an ERROR, not a null.
    The property materialises the first time any registration declares
    `recomputes: true`; until then its absence and a row's absence mean the same
    thing — not a live view.
    """
    try:
        with urllib.request.urlopen(f"{base}/v1/schema/{_COLLECTION}", timeout=timeout) as r:
            names = {p.get("name") for p in (json.load(r).get("properties") or [])}
        return "recomputes" in names
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read %s schema (%s); treating recomputes as absent",
                       _COLLECTION, type(exc).__name__)
        return False


def fetch_registered_entries(*, timeout: float = 5.0, limit: int = 500) -> Optional[Dict[str, Dict[str, Any]]]:
    """Read every registered presentation menu from the graph.

    Returns ``{frontend_id: {frontend_id, frontend_version, capabilities[]}}`` —
    the SAME shape `_REGISTRY` held, so consumers need no new vocabulary — or
    ``None`` when the graph cannot be reached, which is distinct from "reached it
    and nobody has registered" (an empty dict). Collapsing those two would make a
    network blip indistinguishable from an empty registry, and they have opposite
    repairs.
    """
    base = _weaviate_http()
    if not base:
        logger.info("no WEAVIATE_HOST configured; graph menu source is inactive")
        return None

    fields = list(_BASE_FIELDS)
    if _schema_has_recomputes(base, timeout):
        fields.append("recomputes")

    query = "{Get{%s(limit:%d){%s}}}" % (_COLLECTION, int(limit), " ".join(fields))
    try:
        data = _gql(base, query, timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph menu source unreachable (%s: %s); caller falls back",
                       type(exc).__name__, exc)
        return None
    if data is None:
        return None

    rows = (data.get("Get") or {}).get(_COLLECTION) or []
    if len(rows) >= limit:
        # ANY RESULT SET EQUAL TO ITS LIMIT IS UNVERIFIED UNTIL COUNTED. A menu
        # silently truncated at the limit looks like a smaller menu, not a broken
        # read, and the missing capability presents as "that shape can't render".
        logger.warning(
            "graph menu read returned exactly its limit (%d) — the menu may be "
            "TRUNCATED and some registered capabilities invisible", limit,
        )

    entries: Dict[str, Dict[str, Any]] = {}
    orphans = 0
    for row in rows:
        if (row.get("tool_kind") or "") != "Presentation":
            continue  # verb rows share this collection; they are not menu entries
        if _RENDERS_AS_LOCAL not in (row.get("verb_iri") or ""):
            continue
        fid = (row.get("frontend_id") or "").strip()
        if not fid:
            # STRUCTURAL SKIP, not a cleanup detail — see module docstring.
            orphans += 1
            continue
        cap: Dict[str, Any] = {
            "subject_uri": row.get("input_uri") or "",
            "archetype": row.get("archetype") or "",
            "expected_fields": list(row.get("expected_fields") or []),
            "description": row.get("description") or "",
        }
        # `contract` mirrors the in-memory registry's shape so `_is_live_view()`
        # reads it identically from either source. `recomputes` is set ONLY when
        # the row actually declared it: absence must keep saying nothing.
        rec = row.get("recomputes")
        if rec is not None:
            cap["contract"] = {"recomputes": bool(rec)}
        entries.setdefault(fid, {
            "frontend_id": fid,
            "frontend_version": "graph",
            "capabilities": [],
        })["capabilities"].append(cap)

    if orphans:
        logger.warning(
            "graph menu source skipped %d payload-less presentation row(s) with no "
            "frontend_id — these belong to no menu and are cleanup candidates "
            "(sweep_stale_weaviate_predicate_rows)", orphans,
        )
    logger.info("graph menu source: %d frontend(s), %d capability row(s)",
                len(entries), sum(len(e["capabilities"]) for e in entries.values()))
    return entries
