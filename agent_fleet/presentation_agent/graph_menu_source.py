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

    READS THE CLUSTER'S OWN CONVENTION. `WEAVIATE_HTTP_HOST` is published as a
    COMBINED ``host:port`` string (e.g.
    ``iagent-weaviate.sandbox.svc.cluster.local:8080``) and is what every other
    consumer in this repo parses — see agent_fleet/utils/weaviate_utils.py.

    An earlier version of this function looked for `WEAVIATE_HOST` / `WEAVIATE_URL`,
    names INVENTED rather than read. Nothing sets them, so the graph menu source
    logged "inactive" and silently fell back to an empty in-process registry: every
    row correct, every test green, and the read path reading NOTHING in the
    cluster. The same guessed-vs-read miss as assuming the frontend id was
    "cortex" when the UI declares "cortex-ui-desktop".

    Unconfigured is still NOT an error: it means this deployment has no graph
    source, and returning None keeps a missing env var from turning /render_ui
    into a 500.
    """
    raw = (
        os.getenv("WEAVIATE_HTTP_HOST")
        or os.getenv("WEAVIATE_URL")
        or os.getenv("WEAVIATE_HOST")
    )
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/")
    if ":" in raw:
        return f"http://{raw}"
    return f"http://{raw}:{os.getenv('WEAVIATE_PORT', '8080')}"


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


def _schema_has(base: str, prop: str, timeout: float) -> bool:
    """Is `prop` a property of the collection YET?

    Weaviate creates a property when something first WRITES it, so selecting one
    that has never been written is an ERROR rather than a null column. Every
    optional field this reader wants must be probed, not assumed.
    """
    try:
        with urllib.request.urlopen(f"{base}/v1/schema/{_COLLECTION}", timeout=timeout) as r:
            names = {p.get("name") for p in (json.load(r).get("properties") or [])}
        return prop in names
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read %s schema (%s); treating %r as absent",
                       _COLLECTION, type(exc).__name__, prop)
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
    if _schema_has(base, "recomputes", timeout):
        fields.append("recomputes")

    # THE COMPLETENESS FILTER IS SELF-ACTIVATING. Until the registrar has marked
    # its first row the property does not exist, and filtering on it would empty
    # every menu -- so the filter turns on exactly when there is something to
    # filter by. Rows registered BEFORE the marker shipped are complete but
    # unmarked, so they drop out of menus until their next registration; that is
    # a real transition, and it is LOGGED WITH A COUNT rather than silently
    # shrinking the menu, because a menu that quietly loses entries presents as
    # "that shape cannot render" at the far end of the pipeline.
    _filter_on_complete = _schema_has(base, "registration_complete", timeout)
    if _filter_on_complete:
        fields.append("registration_complete")

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
    incomplete = 0
    for row in rows:
        if (row.get("tool_kind") or "") != "Presentation":
            continue  # verb rows share this collection; they are not menu entries
        if _RENDERS_AS_LOCAL not in (row.get("verb_iri") or ""):
            continue
        if _filter_on_complete and not row.get("registration_complete"):
            # DEBRIS, not a menu entry: the write landed and the registration
            # never finished. This is the half-write the conjunctive invariant
            # protects against everywhere else in the system.
            incomplete += 1
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

    if incomplete:
        logger.warning(
            "graph menu source skipped %d row(s) with no completion marker — either "
            "debris from a failed registration, or rows registered before the marker "
            "shipped, which re-register into visibility. They are NOT served.",
            incomplete,
        )
    if orphans:
        logger.warning(
            "graph menu source skipped %d payload-less presentation row(s) with no "
            "frontend_id — these belong to no menu and are cleanup candidates "
            "(sweep_stale_weaviate_predicate_rows)", orphans,
        )
    logger.info("graph menu source: %d frontend(s), %d capability row(s)",
                len(entries), sum(len(e["capabilities"]) for e in entries.values()))
    return entries
