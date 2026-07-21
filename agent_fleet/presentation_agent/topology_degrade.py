"""Pure decision for ADR-0030 rule 2 — does a ``LineageTopology`` payload
degrade to a document, or go to the graph renderer?

Dep-free (``json`` + typing only) so it unit-tests without dragging the
FastAPI / BAML / uvicorn import chain — the same split ``capabilities.py`` and
``chart_normalizer.py`` use. ``main.py`` does the I/O-ish extraction (pull the
agent response out of the supervisor wrapper, JSON-decode ``structured_data``)
and logging; the decision and the document shape live here where a unit test
can pin them.

WHY THIS EXISTS. The deterministic traceLineage branch (Engine A, ADR-0030 /
D4) computes the selected upstream set in code and writes the summary FROM it,
then emits a ``LineageTopology`` whose ``structured_data`` carries an explicit
``outcome`` discriminant and — because a platform filter crosses intermediate
hops — usually **no edges**. Forcing that through ``RenderAsTopology`` is the
ORIGINAL bug: the renderer is asked to draw a graph from data with no edges,
so the model INVENTS edges and the oversized prompt times out. A list is not a
graph; rendered as the already-honest summary, it is a correct document.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def edgeless_lineage_document(
    structured_data: Any, summary: str, persona: str
) -> Optional[Dict[str, Any]]:
    """Return KNOWLEDGE_DOCUMENT components for a deterministic (edgeless)
    LineageTopology, or ``None`` when this is a real graph that belongs to the
    topology renderer.

    Keyed on the ``outcome`` DISCRIMINANT, never on "edges happens to be
    empty" — a genuine but sparse graph is also edgeless, and it must still
    render as a graph. Two conditions send the payload to the renderer
    (return None): no discriminant present (not a deterministic answer), or
    edges present (a real, non-degenerate topology). Otherwise the answer
    already chose its own honest shape — any of the six outcomes reads
    correctly as the summary that was written from the structure — so render
    that summary as a document.
    """
    sd = structured_data
    if not isinstance(sd, dict) or not isinstance(sd.get("outcome"), str):
        return None
    if sd.get("edges"):
        return None

    markdown = str(summary) if summary else "No lineage content available."
    return {
        "components": [
            {
                "archetype": "KNOWLEDGE_DOCUMENT",
                "source_persona": persona,
                "subject_concept": sd.get("asset_label"),
                "markdown_content": markdown,
            }
        ]
    }
