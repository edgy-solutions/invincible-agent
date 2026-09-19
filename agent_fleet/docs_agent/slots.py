"""Slot declarations for `mesh:explain`, DERIVED from the handler signature.

DERIVED, NEVER HAND-TRANSCRIBED (runbook §4). A declaration typed out beside a signature agrees
with it exactly once — on the day it was written — and the router then refuses with a message
that blames the engine for the declaration's lie. `agent_fleet/utils/slot_declarations.py` is the
shared derivation, and this engine IMPORTS it rather than forking it: the runbook's own FILED-NOT
-FIXED said the third engine is where a second copy stops being a cost and becomes the defect, and
the extraction has since landed. Using it is the runbook working.

ALL FOUR KINDS ARE ACCOUNTED FOR, INCLUDING THE TWO NOT USED. A reader who finds two of four kinds
cannot otherwise tell whether the others were considered or forgotten. `engine-docs` has no handle
(there is no scenario to inject — the corpus is the same for every caller) and no ceremony (the
verb reads and answers; nothing is supplied to it out of band).
"""
from __future__ import annotations

from typing import Any, Dict, List

try:  # flat in the image (/app) — runbook §5, FLAT FIRST.
    from utils.slot_declarations import derive_slots
except ImportError:  # packaged in the repo
    from agent_fleet.utils.slot_declarations import derive_slots

#: Declared explicitly rather than omitted. See the module docstring.
HANDLE_SLOTS: Dict[str, str] = {}
CEREMONY_VERBS: set[str] = set()

#: `subject` TAKES THE UNIVERSAL REFERENT, and the first version of this block refused one.
#:
#: §4 rule 3 wants a referent class URI on every spoken slot that identifies something, because
#: without one the filler emits the NAME into the slot — `site_id="Aurora"` at 0.92 confidence,
#: the largest single failure class in the planning corpus. `subject` has exactly that exposure.
#:
#: WHAT THIS BLOCK USED TO SAY, kept because the reasoning was sound and stopped one step early:
#: that no referent could be declared, because the verb is polymorphic over every class in the
#: graph and naming one would be false. Both halves are true. **The conclusion does not follow** —
#: it skips the universal class, and a universal referent was always the answer. The only real
#: question was WHOSE, and that took a measurement: `owl:Thing` is outside this system's routable
#: pool by deliberate design (zero `w3.org` classes in the graph, 2026-09-19), so a referent
#: pointing there registers cleanly and reaches nothing.
#:
#: `mesh:Thing` is ours, is primed, and carries `mesh:universalReferent true` — which is what the
#: parameterisation pool reads. It is NOT a parent of anything: nothing is `subClassOf` it, so it
#: costs no edges and widens no class-chain query. The flag is the universality.
REFERENTS: Dict[str, str] = {
    "subject": "http://invincible-agent/mesh#Thing",
}


def explain_handler(subject: str) -> Dict[str, Any]:
    """The signature the slots are derived FROM. Its body lives in `explain.py`.

    Kept here as the declaration's source so `inspect.signature` has one thing to read and the
    transport cannot drift from it: a handler whose parameters changed without this being re-run
    is the drift the derivation exists to make impossible.
    """
    raise NotImplementedError("declaration source only — see explain.explain()")


def slots_for(fn: str) -> List[dict]:
    """Slot declarations for a verb's function name."""
    if fn != "explain":
        raise KeyError(f"engine-docs serves one verb; {fn!r} is not it")
    return derive_slots(
        explain_handler,
        handles=HANDLE_SLOTS,
        ceremony="explain" in CEREMONY_VERBS,
        referents=REFERENTS,
    )
