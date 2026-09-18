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

#: NO REFERENT ON `subject`, AND THIS IS A CONSIDERED NEGATIVE RATHER THAN AN OMISSION.
#:
#: Rule 3 of §4 says declare a referent class URI on every spoken `*_id` slot, because without one
#: the filler emits the NAME into an id slot — `site_id="Aurora"` at 0.92 confidence, answered
#: `422 unknown site`, the largest single failure class in the planning corpus. `subject` is not an
#: `*_id` slot, so the rule's letter does not bind; its SPIRIT does, and the same failure is
#: available here — a filler can put `"adding an engine"` where an IRI belongs.
#:
#: A referent cannot be declared because the verb is deliberately polymorphic: it explains ANY
#: resolvable IRI, and the classes it ranges over are every class in the graph. Naming one would
#: be false, and naming `mesh:DocPage` would be worse than false — that is the class of the PAGE,
#: not of the thing the page is about, and a consumer comparing `class_uri == referent` would then
#: only ever accept questions about pages.
#:
#: The mitigation is at the other end and is asserted in the engine's tests: a `subject` that does
#: not resolve produces an ABSTAIN THAT NAMES WHAT IT RECEIVED, never a guess and never a 422
#: blaming the caller. A name arriving where an IRI belongs is then a legible answer rather than an
#: error about characters.
REFERENTS: Dict[str, str] = {}


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
