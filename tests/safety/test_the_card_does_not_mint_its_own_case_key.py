"""KNOWN DEFECT (strict xfail): Engine S still mints the acceptance case key and task id itself.

Standing-rule audit item I3 (lane/saf, 2026-10-30). `measures.py` builds
`risk-acceptance-{hazard}-{slug}` (`_case_id`) and `risk-acceptance-{hazard}` (`task_id`) as a
MIRROR of `iagent_pure.acceptance_request.acceptance_workflow_id`, because the engine image does
not ship `iagent_pure`. The gateway already mints the real key from the payload
(`acceptance_trigger` -> `acceptance_id`) and never reads the card's `case_id` or `task_id`; the
only reader of the card's `case_id` is the frontend. So the format lives in two places, sealed
equal by tests/safety/test_the_card_case_id_equals_the_minted_case_key.py rather than made one.

THE FIX IS NOT IN THIS FILE'S REACH. The engine may not import `iagent_pure` (image), so the key
has to be stamped by the code that owns it, where the engine's response is read:
`gateway.py` (`review_request_of` at the direct-dispatch consumer) or `acceptance_request`.
That is Lane 1's. Packet: sessions/2026-10-30-packet-to-lane-01-the-card-mints-its-own-case-key.md.

When the owner stamps the ids and Engine S stops building them, this test passes, strict xfail
turns it red, and whoever sees it deletes the marker and the mirror seal.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_MEASURES = Path(__file__).resolve().parents[2] / "agent_fleet" / "safety_agent" / "measures.py"


def _string_heads_in_code():
    """Every literal string head (constants and f-string heads) in code, docstrings excluded."""
    tree = ast.parse(_MEASURES.read_text(encoding="utf-8"))
    docstrings = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            docstrings.add(id(n.body[0].value))
    heads = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            heads.append((n.lineno, n.value))
    return heads


@pytest.mark.xfail(strict=True, reason=(
    "I3: measures.py mints the case key / task id (`risk-acceptance-...`) instead of the owner "
    "stamping them; needs a change in Lane 1's gateway/acceptance_request, see the packet"))
def test_engine_s_builds_no_case_key_or_task_id():
    hits = [(ln, v) for ln, v in _string_heads_in_code() if v.startswith("risk-acceptance-")]
    assert not hits, hits
