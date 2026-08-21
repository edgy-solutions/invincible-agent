"""The honest-degradation text extractor (relocated 2026-08-20, slice 2c).

WHY IT MOVED. This function lived in `chart_normalizer.py`, which slice 2c deletes. It was
never chart normalization: it extracts the agent's already-written honest TEXT so an
unrenderable chart can fall back to a KNOWLEDGE_DOCUMENT instead of an empty widget reading
as a malfunction. It sat in that file only because the empty-chart fallback was its first
caller.

THE DISSOLUTION HAD TWO BUCKETS AND THIS FUNCTION NEEDED A THIRD. The rule was: anything the
normalizer did is either a missing contract fact (fix the export) or dead compensation
(delete it). This is neither -- it is CORRECT CODE IN THE WRONG FILE. Relocating rather than
deleting is the disposition, and the rule is unchanged for actual normalizer BEHAVIOUR: the
coercion was dead compensation and is gone.

SYNTHESIS IS THEATRE. The text is returned VERBATIM -- it already exists, so render it
rather than re-deriving it. Joining a list of scalars is FORMATTING, not synthesis: every
value carried in order, nothing summarised, computed or dropped.
"""
from __future__ import annotations

from typing import Any


def honest_text_from_response(agent_response: Any) -> str:
    """Extract the agent's honest TEXT answer for the empty-chart fallback.

    Engine DA returns ``{status, data, sources}`` where ``data`` is the
    agent_result — a text ``final_answer`` when the query couldn't be charted
    (e.g. no such column). Other engines carry it as ``summary`` /
    ``summary_text``. Returns the text VERBATIM (synthesis-is-theater — the honest
    text already exists; render it, don't re-derive), or ``""`` when there's no
    text (the caller then keeps the empty chart — nothing to fall back to).
    """
    if not isinstance(agent_response, dict):
        return ""
    for key in ("summary", "summary_text"):
        v = agent_response.get(key)
        if isinstance(v, str) and v.strip():
            return v
    data = agent_response.get("data")
    if isinstance(data, str) and data.strip():
        return data
    # A LIST OF VALUES IS AN ANSWER TOO. DA returns `data` as a list when the query
    # produced rows — e.g. ["00000", "00001"] for a couple of CAGE codes. Those are
    # IDENTIFIERS, not measures, so no chart can be drawn from them; before this the
    # fallback found no string, returned "", and a correct answer was discarded by the
    # presentation layer while the UI showed "CHART DATA NOT RENDERABLE" (witnessed at
    # work 2026-08-15).
    #
    # Joining scalars is FORMATTING, not synthesis: every value is carried verbatim and
    # in order, nothing is summarised, computed, or dropped. Lists of dicts are left
    # alone — those are chart-shaped and belong to the normalizer above, so a failure
    # there is a real normalization gap and must not be papered over as text.
    if isinstance(data, list) and data:
        scalars = [d for d in data if isinstance(d, (str, int, float, bool))]
        if len(scalars) == len(data):
            return ", ".join(str(d) for d in scalars)
    return ""
