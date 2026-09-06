"""`selection_basis` must reach the response, not die in a log line.

RULED 2026-09-05. The selector already distinguishes the two cases that matter:

    "output_uri+payload"                              the declared output matched a capability
    "payload-only (output_uri matched no capability)"  it did not, and the PAYLOAD chose the card

That difference is exactly LEGITIMATE SHAPE VARIATION versus FELL THROUGH TO A PLAUSIBLE CARD,
and it existed only inside a `logger.info`. Three picks from one menu drew three different cards
and nobody could say which of those two things had happened.

THE FAILURE IT NAMES IS ON THE RECORD: `mesh:PeriodCostSeries` matched no capability, a
`[{period,total}]` series satisfied CHART_WIDGET, and a plausible bar chart drew — and
`selection_basis` was the only field that said so.

ADDITIVE, NOT A SUBSTITUTION, and that is pinned below: the log line is untouched. A log is read
by a person and a payload by a renderer; one string cannot serve both, so nothing that greps the
log has to change.
"""
from __future__ import annotations

import re
from pathlib import Path

from agent_fleet.presentation_agent.capabilities import _with_selection_provenance

_ROOT = Path(__file__).resolve().parents[1]
_MAIN = _ROOT / "agent_fleet" / "presentation_agent" / "main.py"

_PROV = {
    "presentation_source": "registered",
    "frontend_id": "cortex-ui-desktop",
    "archetype": "PERIOD_SERIES",
    "selection_basis": "payload-only (output_uri matched no capability)",
}


def test_the_basis_reaches_the_payload():
    out = _with_selection_provenance({"components": [{"archetype": "PERIOD_SERIES"}]}, _PROV)
    assert out["presentation_provenance"]["selection_basis"] == _PROV["selection_basis"], (
        "the one field that separates a legitimate shape difference from a fall-through did "
        "not reach the response"
    )


def test_the_original_payload_is_preserved():
    """Additive. A consumer reading `components` must not notice this change."""
    payload = {"components": [{"archetype": "X"}], "other": 1}
    out = _with_selection_provenance(payload, _PROV)
    assert out["components"] == [{"archetype": "X"}] and out["other"] == 1


def test_absence_is_SILENT_rather_than_null():
    """⛔ NO KEY, not a null one — the reader is absence-silent.

    A `presentation_provenance: null` would make "no selection ran" indistinguishable from "a
    selection ran and reported nothing", which is the one-field-for-two-outcomes defect this
    whole change exists to remove. Paths that return before a selection — a declared
    non-answer, an absent output_uri — legitimately have no provenance.
    """
    for prov in (None, {}, {"presentation_source": None, "selection_basis": None}):
        out = _with_selection_provenance({"components": []}, prov)
        assert "presentation_provenance" not in out, f"emitted an empty key for {prov!r}"


def test_null_members_are_dropped_but_real_ones_survive():
    out = _with_selection_provenance({"c": 1}, {"selection_basis": "output_uri+payload",
                                                "registration_version": None})
    assert out["presentation_provenance"] == {"selection_basis": "output_uri+payload"}


def test_a_non_dict_payload_is_returned_untouched():
    """The BAML paths return model dumps; a defensive shape check must not corrupt one."""
    assert _with_selection_provenance("not-a-dict", _PROV) == "not-a-dict"
    assert _with_selection_provenance(None, _PROV) is None


# ── THE TWO STRUCTURAL SEALS ──────────────────────────────────────────────────────────

def _render_ui_returns() -> list[str]:
    src = _MAIN.read_text(encoding="utf-8")
    body = src[src.index("async def render_ui("):src.index("def health(")]
    return [ln.strip() for ln in body.splitlines() if re.match(r"\s*return ", ln)]


#: Returns that legitimately carry no provenance, each with the reason. These run BEFORE any
#: selection happens, so `_sel_prov` does not exist at that point — referencing it would be a
#: NameError, which makes this an allowlist of FACTS rather than of preferences.
_PRE_SELECTION_RETURNS = {
    "_render_declared_ungrounded": "the producer declared it could not ground; no selection ran",
    "baml_response.model_dump()": "the fallback-no-output-uri path; there is nothing to select on",
}


def test_every_POST_SELECTION_return_carries_the_provenance():
    """Enumerated from the source, so a SEVENTH return path fails here rather than silently
    dropping the field — which is how `reference` and `verdict` were lost one layer down."""
    unstamped = []
    for ret in _render_ui_returns():
        if "_with_selection_provenance" in ret:
            continue
        if any(k in ret for k in _PRE_SELECTION_RETURNS):
            continue
        unstamped.append(ret)
    assert not unstamped, (
        "return path(s) in render_ui that neither stamp the provenance nor are declared "
        f"pre-selection: {unstamped}. Stamp it, or add the path to _PRE_SELECTION_RETURNS "
        "with the reason no selection has run there."
    )


def test_the_stamping_is_actually_used_and_this_file_is_not_vacuous():
    stamped = [r for r in _render_ui_returns() if "_with_selection_provenance" in r]
    assert len(stamped) >= 4, (
        f"only {len(stamped)} stamped return(s) — if render_ui was restructured this seal may "
        "be passing over a function that no longer selects anything"
    )


def test_the_LOG_LINE_is_untouched():
    """The change is additive. Anything that greps for this line still finds it."""
    src = _MAIN.read_text(encoding="utf-8")
    assert "render_ui: menu-scoped selection frontend_id=%s source=%s basis=%s" in src, (
        "the selection log line changed. A log is read by a person and a payload by a "
        "renderer; carrying the field to the payload must not cost the operator their line."
    )
