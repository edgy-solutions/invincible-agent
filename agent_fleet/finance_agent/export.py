"""Packaging: the verification manifest, and the governed emit that carries it (item 3).

Mirrors `agent_fleet/cost_agent/export.py`'s shape — ADR-0047/0048 carried into engine-fin.
What is different here, and deliberately: a finance disclosure is scoped to ONE PROGRAM, not
a set of lots, and its panels are not six fixed verb calls chosen by this module — they are
whatever `canvas_template.panel_dispatch` produced for a ratified template's panels, handed in
by the caller (`main.py`'s `package_export` route). This module does not know about canvases;
it only manifests and audits what it is given, same separation cost's `export.py` draws
between packaging and the canvas it was asked to carry.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import date
from typing import Any, Optional

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import FinanceState, Unentitled
    from seed import build_seed
except ImportError:
    from agent_fleet.finance_agent.entities import FinanceState, Unentitled
    from agent_fleet.finance_agent.seed import build_seed

#: Bumped when the manifest's SHAPE changes, so an old package cannot be silently checked by
#: new rules or the reverse. Not the algorithm's version — that is the pinned commit SHA.
MANIFEST_SCHEMA = "fin-export/1"

#: The one disclosure audience this engine packages for today. MUST equal
#: `canvas_template.Package.audience`'s `Literal` args — sealed in
#: `tests/finance/test_fin_package_export.py`, because a tuple kept beside a `Literal` is a
#: second population of the same fact and the two can drift silently.
AUDIENCES: tuple[str, ...] = ("program_office",)


def _canonical(obj: Any) -> str:
    """Stable JSON for hashing. Sorted keys, no whitespace drift. Same pin as cost's
    `_canonical` and `canvas_template._canonical` — one serialisation, three callers."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    """`"sha256:" + hex`, over `_canonical(obj)`. Per ADR-0034's `ruleset_ref` discipline."""
    return "sha256:" + hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# The entitlement surface — DERIVED, never hand-listed beside what it is derived from
# ─────────────────────────────────────────────────────────────────────────────

#: scope -> program_id. DERIVED from `build_seed().programs` crossed with `AUDIENCES`, so a
#: program added to the seed is packageable from the commit that adds it, and this map cannot
#: itself name a program the seed does not hold — the same "hand-kept list is a second
#: population" defect `canvas_template.ratified_template_ids` exists to close, here for scopes.
RECIPIENT_SCOPES: dict[str, str] = {
    f"{audience}.{program.program_id}": program.program_id
    for program in build_seed().programs
    for audience in AUDIENCES
}

#: WHO MAY FETCH A PRODUCED PACKAGE, keyed on the mint-contract `authz_id`. NOTIONAL: this
#: engine has no ratified reader yet, and this map awaits one — the same posture cost's
#: `RECIPIENT_READERS` states for its own two notional customers. No service identity is
#: listed, for the identical confused-deputy reason cost's docstring gives.
RECIPIENT_READERS: dict[str, tuple[str, ...]] = {
    "program_office.NP-MERIDIAN": ("alice@example.com",),
}


def readers_for_recipient(recipient_scope: str) -> tuple[str, ...]:
    """The callers entitled to fetch this recipient's package. EMPTY IS A REFUSAL — an
    unknown scope and a scope with no readers answer a 403 route the same way."""
    return RECIPIENT_READERS.get(recipient_scope, ())


def program_for_recipient(recipient_scope: str) -> str:
    """The program a recipient scope discloses. RAISES on an unknown scope rather than
    returning empty — "this recipient has no program" and "this is not a recipient" must not
    look alike (ADR-0049 Ruling 4, carried from cost's `lots_for_recipient`)."""
    try:
        return RECIPIENT_SCOPES[recipient_scope]
    except KeyError:
        raise Unentitled(
            f"{recipient_scope!r} is not a recipient this engine packages for; known scopes "
            f"are {sorted(RECIPIENT_SCOPES)}"
        ) from None


def artifact_filenames(recipient_scope: str) -> tuple[str, str]:
    """(html, duckdb) — the two files `package_export` writes for one recipient. THE ONE
    PLACE THE NAMING RULE IS SPELLED, mirroring cost's `artifact_filenames` for the identical
    reason: a second spelling would drift, and an authorization check reading the stale one
    fails open."""
    return (f"fin-package-{recipient_scope}.html", f"fin-{recipient_scope}.duckdb")


def scope_of_artifact(filename: str) -> Optional[str]:
    """Which recipient's package `filename` is, or None if no recipient's. Derived from
    `RECIPIENT_SCOPES` and `artifact_filenames`, never parsed out of the string."""
    for scope in RECIPIENT_SCOPES:
        if filename in artifact_filenames(scope):
            return scope
    return None


# ─────────────────────────────────────────────────────────────────────────────
# The manifest — every module the page embeds, hashed over the EMBEDDED text
# ─────────────────────────────────────────────────────────────────────────────

def module_hashes() -> dict[str, str]:
    """SHA-256 of the embedded text of every module the exported page carries.

    Hashed over the STRING the page embeds (`read_text(encoding="utf-8")`, which normalizes
    CRLF to LF), never over the file's raw bytes — the identical reasoning cost's
    `module_hashes` gives: a platform-dependent hash reads as tampering, not as a difference in
    checkout.

    Finance embeds more than cost does, because this engine's algorithm is not one module: the
    page also carries `state_codec` (to rebuild `FinanceState`) and `page` itself (the
    verification harness), and every `measure_modules/*` file the six verbs delegate to.
    """
    try:  # pragma: no cover - import path differs by runtime
        import entities as _entities
        import measure_modules as _measure_modules
        import measures as _measures
        import page as _page
        import state_codec as _state_codec
    except ImportError:  # pragma: no cover
        from agent_fleet.finance_agent import entities as _entities
        from agent_fleet.finance_agent import measure_modules as _measure_modules
        from agent_fleet.finance_agent import measures as _measures
        from agent_fleet.finance_agent import page as _page
        from agent_fleet.finance_agent import state_codec as _state_codec

    def _hash_text(text: str) -> str:
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    out: dict[str, str] = {}
    for mod, name in (
        (_entities, "entities.py"), (_state_codec, "state_codec.py"),
        (_measures, "measures.py"), (_page, "page.py"),
    ):
        out[name] = _hash_text(pathlib.Path(mod.__file__).read_text(encoding="utf-8"))

    mm_dir = pathlib.Path(_measure_modules.__file__).parent
    for sub in sorted(mm_dir.glob("*.py")):
        if sub.name == "__init__.py":
            continue
        out[f"measure_modules/{sub.name}"] = _hash_text(sub.read_text(encoding="utf-8"))
    return out


def build_manifest(
    state: FinanceState,
    *,
    recipient_scope: str,
    program_id: str,
    algorithm_sha: str,
    template_id: str,
    template_hash: str,
    panels: list[dict[str, Any]],
    duckdb_sha256: Optional[str] = None,
    as_of: Optional[str] = None,
) -> dict[str, Any]:
    """Capture one disclosure's identity, inputs and panels from the PRODUCING engine.

    `panels` arrives already computed — each `{panel, verb, fn, params, artifact_id, rows}`,
    the exact envelope `/measure/{fn}` would have served (item 3's rule: packageExport reads
    the SAME envelope function, `_measure_envelope`, that the ordinary route does). This
    function reduces `rows` to `rows_sha256` and does not recompute anything: recomputation
    belongs to `page.verify`, on the recipient's side, against the SAME served rows.

    `state_sha256` hashes the state the panels were actually computed from — the one this
    disclosure's `.duckdb` and embedded rows both carry (narrowed to `program_id`), so a
    recipient can confirm the manifest describes the data they received rather than the
    engine's whole notional model.
    """
    try:
        import state_codec as _state_codec
    except ImportError:
        from agent_fleet.finance_agent import state_codec as _state_codec

    panel_entries = []
    for p in panels:
        panel_entries.append({
            "panel": p["panel"],
            "verb": p["verb"],
            "fn": p["fn"],
            "params": p["params"],
            "artifact_id": p["artifact_id"],
            "rows_sha256": content_hash(p["rows"]),
        })

    return {
        "schema": MANIFEST_SCHEMA,
        "recipient_scope": recipient_scope,
        "program_id": program_id,
        "algorithm_sha": algorithm_sha,
        "template_id": template_id,
        "template_hash": template_hash,
        "panels": panel_entries,
        "state_sha256": content_hash(_state_codec.state_to_dict(state)),
        "duckdb_sha256": duckdb_sha256,
        "modules": module_hashes(),
        "as_of": as_of or date.today().isoformat(),
    }


def audit_line(manifest: dict[str, Any], *, disclosed_by: str) -> dict[str, Any]:
    """What was disclosed, to whom, when, and by which algorithm version.

    Mirrors cost's `audit_line`. Names the panels' `artifact_id`s rather than the rows
    themselves — a disclosure leaves a trace of WHAT WAS ANSWERED, checkable against
    `/measure/{fn}`, without the audit line itself becoming a second copy of the data.
    """
    return {
        "disclosed_to": manifest["recipient_scope"],
        "disclosed_by": disclosed_by,
        "at": manifest["as_of"],
        "algorithm_sha": manifest["algorithm_sha"],
        "template_id": manifest["template_id"],
        "template_hash": manifest["template_hash"],
        "panel_artifact_ids": [p["artifact_id"] for p in manifest["panels"]],
    }
