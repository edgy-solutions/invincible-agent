"""Per-frontend capability registry + decision-time menu lookup (ADR-0017 amendment).

THE COUPLING THIS SOLVES. Registration made the archetype decision valid ONLY against the
render menu of the client that will render it. Choose CHART_WIDGET because cortex-ui
registered it, deliver to an OpenDDIL session that never did, and the result is a CORRECT
ANSWER WITH AN UNRENDERABLE PRESENTATION. That is not misdelivery -- the session already
knows the way home -- it is a decision made against the wrong capability set.

So the decision resolves the REQUESTING CLIENT's registered contracts AT DECISION TIME.
That is a lookup key, not an affinity system: no stickiness, no routing state, no
origin-tracking machinery. The only thing that changes is WHICH MENU the picker consults.

THREE STATES, AND THE MIDDLE ONE IS THE POINT:
  * `registered`   -- the caller has a menu; the archetype came from it.
  * `default-menu` -- the caller has NO menu; the archetype came from the universal
                      fallback and IS LABELLED SO. An unlabelled fallback would be
                      indistinguishable from a registered caller's decision, which is the
                      same-observation-opposite-reasons shape this project keeps burying.
  * `unrenderable` -- the caller has a menu and the wanted archetype is not in it. The
                      caller gets a labelled miss, never a silent substitution.

VERSIONED, because a client registers at startup and an answer may compose twenty minutes
later, after a redeploy. The registration version is stamped into the decision so a
mismatch at render reads "decided against menu v3, rendered by v4" -- diagnosable --
instead of a silent wrong shape. Same freshness problem the engines have, same fix.

IN-MEMORY, DELIBERATELY, AND THAT IS A NAMED STATE. Presentation capabilities are RUNTIME
state, exactly like verb edges: a restart empties this registry and every answer falls to
the default menu until frontends re-register. That is survivable only because the
honest-degradation work shipped, and it belongs in the runbook as a named state rather
than being discovered in a demo. See [[bootstrap-state-debt]] for the same species one
layer down.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

# Archetypes renderable by ANY surface that can display text. The default menu is
# deliberately tiny: it is what we can promise an unknown client, not what we hope it has.
UNIVERSAL_ARCHETYPES = ("KNOWLEDGE_DOCUMENT",)

_LOCK = threading.Lock()
_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register(frontend_id: str, frontend_version: str, capabilities: List[Dict[str, Any]]) -> int:
    """Record a frontend's ADMITTED capabilities. Returns the stored count.

    REPLACES rather than merges: a frontend's registration is the whole truth about what it
    can render right now. Merging would let a capability removed in a redeploy survive as a
    ghost, and the backend would keep choosing an archetype the client dropped.
    """
    fid = (frontend_id or "").strip()
    if not fid:
        return 0
    with _LOCK:
        _REGISTRY[fid] = {
            "frontend_id": fid,
            "frontend_version": (frontend_version or "unknown").strip() or "unknown",
            "capabilities": list(capabilities or []),
        }
        return len(_REGISTRY[fid]["capabilities"])


def union_menu() -> Dict[str, Any]:
    """The union of every currently-registered menu — the ANONYMOUS caller's menu.

    WHY A UNION IS HONEST HERE, when it was fatal as a design. The amendment rejected a
    union SCHEMA because it lets the backend pick an archetype a SPECIFIC caller cannot
    render — the union lies about that caller. An anonymous caller has no menu to
    contradict, so the union is simply the best available statement of "what any registered
    surface could render", which is the most that can be said about a caller who did not
    say who it is.

    WHY NOT `capabilities.py`. That backend copy was the fallback's source until 2026-08-20
    and it resurrected the two-masters defect the migration killed: every row it held is now
    DERIVED on the UI side, so keeping it meant the fallback drifted the day a contract
    changed, with nothing pinning them equal. Computed from the registry, the fallback reads
    the same source everything else reads.

    Deduped by (subject_uri, archetype): two surfaces registering the same capability is
    agreement, not two options.
    """
    with _LOCK:
        entries = list(_REGISTRY.values())
    seen, caps = set(), []
    for e in entries:
        for c in e.get("capabilities") or []:
            key = (str(c.get("subject_uri") or ""), str(c.get("archetype") or ""))
            if key in seen:
                continue
            seen.add(key)
            caps.append(c)
    return {
        "frontend_id": None,
        "frontend_version": "union",
        "capabilities": caps,
    }


def menu_for(frontend_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The caller's registered menu, or None when the caller never registered."""
    if not frontend_id:
        return None
    with _LOCK:
        entry = _REGISTRY.get(frontend_id.strip())
        return dict(entry) if entry else None


def clear() -> None:
    """Test hook. Never called by request paths."""
    with _LOCK:
        _REGISTRY.clear()


def _canonical(iri: str) -> str:
    """Compact/full IRI folding, mirroring capabilities.canonical_iri_for_lookup.

    Duplicated deliberately to keep this module dep-free and unit-testable; the folding is
    three lines and the alternative is importing the table this module exists to replace.
    """
    s = (iri or "").strip()
    if "#" in s:
        s = s.rsplit("#", 1)[-1]
    elif "/" in s and ":" not in s:
        s = s.rsplit("/", 1)[-1]
    if ":" in s:
        s = s.split(":", 1)[-1]
    return s


def select_archetype(
    frontend_id: Optional[str],
    output_uri: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Resolve (capability, provenance) for this caller and output type.

    The provenance dict is STAMPED INTO THE ANSWER ENVELOPE and always carries
    `presentation_source`. Never returns a capability without saying which menu it came
    from -- that labelling is the whole point of the middle state.
    """
    menu = menu_for(frontend_id)
    target = _canonical(output_uri)

    if menu is None:
        # UNREGISTERED CALLER -- a curl, a script, a UI mid-onboarding. A NAMED
        # degradation, never an error: the API stays usable by non-UI consumers without
        # special-casing them.
        return None, {
            "presentation_source": "default-menu",
            "presentation_menu": list(UNIVERSAL_ARCHETYPES),
            "frontend_id": frontend_id or None,
            "reason": "caller has no registered capability menu",
        }

    for cap in menu["capabilities"]:
        if _canonical(str(cap.get("subject_uri") or "")) == target:
            return cap, {
                "presentation_source": "registered",
                "frontend_id": menu["frontend_id"],
                "registration_version": menu["frontend_version"],
                "archetype": cap.get("archetype"),
            }

    # REGISTERED BUT CANNOT RENDER THIS. Distinct from unregistered, and labelled as such:
    # folding the two would hide that this client HAS a menu and this output is not on it,
    # which is the actionable half.
    return None, {
        "presentation_source": "unrenderable",
        "frontend_id": menu["frontend_id"],
        "registration_version": menu["frontend_version"],
        "reason": "output_uri " + repr(output_uri) + " is not in this frontend's registered menu",
    }


# ══════════════════════════════════════════════════════════════════════════════
# SLICE 4 — selection from DATA SHAPE. `output_uri` is a candidate filter, not a verdict.
# ══════════════════════════════════════════════════════════════════════════════
#
# WHAT THIS CLOSES. `archetype-chosen-before-data`: the archetype was resolved from
# `output_uri` alone, BEFORE anyone looked at the rows. That is how a list of two
# identifiers got CHART_WIDGET -- the output type said "analysis report", nothing asked
# whether the payload could be drawn, and the viewer got an undrawable widget. The
# degradation half shipped (the viewer now sees the honest text), but the system still
# CHOSE WRONG and then recovered.
#
# Selection now runs: filter by output_uri -> keep only what the PAYLOAD SATISFIES ->
# rank by the already-published persona/domain affinities. The archetype returned is one
# whose contract this payload meets, so `unrenderable` stops being reachable as a
# DECISION: the picker cannot choose something the caller cannot draw.
#
# `unrenderable` REMAINS in the vocabulary, deliberately. It is still the honest answer
# when a caller's menu contains nothing this payload satisfies -- but it is now a fact
# about the MENU meeting the DATA, not a decision made in ignorance of the data.


def _satisfies(cap: Dict[str, Any], payload: Optional[Dict[str, Any]]) -> Optional[str]:
    """None when `payload` satisfies this capability's contract, else the refusal reason.

    Dispatches by archetype because that is where the shape rules live. An archetype with
    no typed contract is treated as SATISFIED: migration is row-by-row, and refusing the
    nine not-yet-converted rows would make slice 4 a regression for every archetype except
    the one that happens to be finished.
    """
    if payload is None:
        return None
    archetype = str(cap.get("archetype") or "")
    if archetype == "CHART_WIDGET":
        # Imported here rather than at module scope to keep this module importable by the
        # pure unit tests without dragging the validator's json/typing chain into every
        # registry test.
        try:
            from capability_validator import validate_chart_payload  # type: ignore[no-redef]
        except ImportError:
            from agent_fleet.presentation_agent.capability_validator import (
                validate_chart_payload,
            )
        return validate_chart_payload(
            payload.get("chart_data"),
            payload.get("chart_type"),
            cap.get("contract"),
        )
    return None


def select_presentation(
    frontend_id: Optional[str],
    output_uri: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    persona: Optional[str] = None,
    domain: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Choose an archetype the caller can render AND this payload can fill.

    Returns (capability, provenance). Provenance always carries `presentation_source`, and
    now also `selection_basis` so a reader can tell WHY this archetype won -- the
    discriminant that was missing when the choice was made from a type annotation alone.
    """
    menu = menu_for(frontend_id)
    anonymous = menu is None
    if anonymous:
        # ANONYMOUS CALLER -- curl, a script, a UI mid-onboarding. It gets the DERIVED UNION
        # of registered menus, not a collapse to text: these are consumers of the ANSWER,
        # and the answer's presentation metadata is part of its truth. A script receiving
        # CHART_WIDGET plus shaped data can render or forward it; collapsing every non-UI
        # caller to prose would make the API strictly less useful to exactly the consumers
        # who cannot register. Still LABELLED `default-menu`, so the state stays named.
        menu = union_menu()
        if not menu["capabilities"]:
            # EMPTY REGISTRY -> empty union -> the universal floor. This is the
            # post-restart state: presentation capabilities are runtime state, so a
            # restart empties the registry until frontends re-register.
            return None, {
                "presentation_source": "default-menu",
                "presentation_menu": list(UNIVERSAL_ARCHETYPES),
                "frontend_id": frontend_id or None,
                "reason": "no frontend has registered — union is empty",
            }

    target = _canonical(output_uri)
    caps: List[Dict[str, Any]] = menu["capabilities"]

    # 1. FILTER (not decide). output_uri narrows the field; it no longer picks the winner.
    candidates = [c for c in caps if _canonical(str(c.get("subject_uri") or "")) == target]
    basis = "output_uri+payload"
    if not candidates:
        # output_uri matched nothing. It is a HINT, so a miss widens the field rather than
        # ending the search -- the payload may still satisfy something on this menu.
        candidates = list(caps)
        basis = "payload-only (output_uri matched no capability)"

    # 2. KEEP ONLY WHAT THE PAYLOAD SATISFIES. This is the step whose absence produced
    #    CHART_WIDGET for two identifiers.
    satisfied, refusals = [], []
    for c in candidates:
        reason = _satisfies(c, payload)
        if reason is None:
            satisfied.append(c)
        else:
            refusals.append({"archetype": c.get("archetype"), "reason": reason})

    if not satisfied:
        # Nothing on this menu can draw this payload. Honest, and now EXPLAINED: the
        # refusals name which requirement each candidate missed.
        return None, {
            "presentation_source": "default-menu" if anonymous else "unrenderable",
            "frontend_id": menu["frontend_id"],
            "registration_version": menu["frontend_version"],
            "selection_basis": basis,
            "refusals": refusals,
            "reason": "no registered capability's contract is satisfied by this payload",
        }

    # 3. RANK by the affinities already published. Ranking only -- it breaks ties among
    #    archetypes that can ALL render the payload, and never overrides satisfaction.
    def _affinity(c: Dict[str, Any]) -> int:
        score = 0
        if persona and persona in (c.get("persona_fit") or []):
            score += 2
        if domain and domain in (c.get("domain_fit") or []):
            score += 1
        return score

    winner = max(satisfied, key=_affinity)
    return winner, {
        "presentation_source": "default-menu" if anonymous else "registered",
        "frontend_id": menu["frontend_id"],
        "registration_version": menu["frontend_version"],
        "archetype": winner.get("archetype"),
        "selection_basis": basis,
        "candidates_considered": len(candidates),
        "candidates_satisfied": len(satisfied),
        "refusals": refusals,
    }
