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
