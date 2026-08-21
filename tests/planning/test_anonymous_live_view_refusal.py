"""ADR-0042 Ruling 9 — a live view refuses an anonymous caller. The selector's half.

THE RULING, and why the refusal lives HERE rather than in a component contract. A one-shot
answer delivered to an anonymous caller is a complete artifact whose rendering is a courtesy:
the union menu is the honest best-effort, and if the shape lands imperfectly the payload is
still intact and true. A live view is a STANDING CONTRACT — a subscription that recomputes
against moving state. Honouring it for a caller the backend cannot name means an ongoing
obligation to an unknown identity against a menu that is a guess, and when that caller's real
capabilities diverge from the union the one-shot's failure is BOUNDED (once, one payload)
while the subscription's COMPOUNDS for as long as it lives.

WHERE IT FIRES. At menu-scoping time, BEFORE any payload is evaluated. It is therefore not a
member of any component's `refusalReasons`: the component never reaches it, and publishing an
unemittable reason leaves the backend waiting on a discriminant that never arrives — the
defect `ChartWidget.contract.ts` already records for its unreachable scatter branch.

THE VOCABULARY. `presentation_source: "refused"` — a CATEGORY, like the three beside it —
carrying `refusal_code` for the cause. Not `refused-anonymous-live`: the existing states are
cause-agnostic and carry specifics in adjacent fields, and a state named after one cause
invites a fifth the next time a selector-level refusal appears.

THE DISCRIMINANT. `recomputes: true` on the contract — a contract FIELD like `layout`, never
a refusal reason. Without it this ruling is unimplementable, which is how it was first drafted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PRESENTATION = Path(__file__).resolve().parents[2] / "agent_fleet" / "presentation_agent"
sys.path.insert(0, str(_PRESENTATION))

import capability_registry as cr  # noqa: E402

FRONTEND = "cortex-ui-desktop"

LIVE = {
    "subject_uri": "mesh:PeriodCostSeries", "archetype": "PERIOD_SERIES",
    "component": "PeriodSeries", "persona_fit": [], "domain_fit": [],
    "contract": {"archetype": "PERIOD_SERIES", "recomputes": True, "fields": {"rows": {}}},
}
STATIC = {
    "subject_uri": "mesh:OwnershipFact", "archetype": "KNOWLEDGE_DOCUMENT",
    "component": "MarkdownRenderer", "persona_fit": [], "domain_fit": [],
    "contract": {"archetype": "KNOWLEDGE_DOCUMENT", "fields": {}},
}

LIVE_URI = "http://invincible-agent/mesh#PeriodCostSeries"
STATIC_URI = "http://invincible-agent/mesh#OwnershipFact"


@pytest.fixture(autouse=True)
def _clean():
    cr.clear()
    yield
    cr.clear()


# ─────────────────────────────────────────────────────────────────────────────
# The refusal
# ─────────────────────────────────────────────────────────────────────────────

def test_an_anonymous_caller_asking_for_a_live_view_is_REFUSED():
    """The ruling. An identified caller registered it; an unidentified one may not have it."""
    cr.register(FRONTEND, "1.0", [LIVE, STATIC])
    cap, prov = cr.select_presentation(None, LIVE_URI, {"rows": [{"period": "FY26-Q3"}]})
    assert cap is None
    assert prov["presentation_source"] == "refused"
    assert prov["refusal_code"] == "live_view_requires_registration"
    assert prov.get("reason"), "a refusal with no prose reason is a verdict with no explanation"


def test_the_refusal_is_a_CATEGORY_carrying_its_cause_in_a_field():
    """Not `refused-anonymous-live`. The three existing states are cause-agnostic categories
    with specifics in adjacent fields; a state named after one cause would be the only one
    that is, and invites a fifth next time."""
    cr.register(FRONTEND, "1.0", [LIVE, STATIC])
    _, prov = cr.select_presentation(None, LIVE_URI, {"rows": []})
    assert prov["presentation_source"] == "refused"
    assert "anonymous" not in prov["presentation_source"]
    assert "live" not in prov["presentation_source"]


def test_refusal_code_is_not_confused_with_the_plural_refusals_list():
    """`refusals` (plural) already means PER-CANDIDATE CONTRACT MISSES. They must not
    co-populate: `refused` fires before candidate evaluation, so there is no per-candidate
    list to report."""
    cr.register(FRONTEND, "1.0", [LIVE, STATIC])
    _, prov = cr.select_presentation(None, LIVE_URI, {"rows": []})
    assert "refusal_code" in prov
    assert not prov.get("refusals"), "refused fires before candidates are evaluated"


# ─────────────────────────────────────────────────────────────────────────────
# What must NOT change
# ─────────────────────────────────────────────────────────────────────────────

def test_an_anonymous_caller_asking_for_a_STATIC_answer_still_gets_the_union():
    """The ruling is narrow on purpose. A one-shot's rendering is a courtesy and the union is
    the honest best-effort — collapsing every anonymous caller to prose would make the API
    strictly less useful to exactly the consumers who cannot register."""
    cr.register(FRONTEND, "1.0", [LIVE, STATIC])
    cap, prov = cr.select_presentation(None, STATIC_URI, {"content": "x"})
    assert cap is not None
    assert cap["archetype"] == "KNOWLEDGE_DOCUMENT"
    assert prov["presentation_source"] == "default-menu"


def test_an_IDENTIFIED_caller_gets_its_live_view():
    """The whole point. Registration is what buys the subscription."""
    cr.register(FRONTEND, "1.0", [LIVE, STATIC])
    cap, prov = cr.select_presentation(FRONTEND, LIVE_URI, {"rows": [{"period": "FY26-Q3"}]})
    assert cap["archetype"] == "PERIOD_SERIES"
    assert prov["presentation_source"] == "registered"
    assert prov["selection_basis"] == "output_uri+payload"


def test_a_live_archetype_is_excluded_from_the_union_even_when_the_uri_misses():
    """The subtle half. `output_uri` is a HINT, so a miss WIDENS the search to the whole menu —
    and a live archetype sitting in that widened field would be selectable by an anonymous
    caller through the back door, defeating the ruling while appearing to honour it."""
    cr.register(FRONTEND, "1.0", [LIVE, STATIC])
    cap, prov = cr.select_presentation(None, "http://invincible-agent/mesh#NotAThing",
                                       {"rows": [{"period": "FY26-Q3"}]})
    assert (cap or {}).get("archetype") != "PERIOD_SERIES", "a live view leaked into the union"


def test_an_empty_registry_still_floors_rather_than_refusing():
    """Post-restart, the union is empty and the honest answer is the universal floor. That is
    a DIFFERENT state from `refused` and must not be folded into it: one says 'nothing has
    registered', the other says 'policy declined'. Different first question, different fix."""
    cap, prov = cr.select_presentation(None, LIVE_URI, {"rows": []})
    assert cap is None
    assert prov["presentation_source"] == "default-menu"
    assert "refusal_code" not in prov


def test_a_contract_without_recomputes_is_not_treated_as_live():
    """Absence is the honest default. A contract that never declared the flag says NOTHING,
    and must not be read as False-meaning-live or True-meaning-live by accident."""
    cr.register(FRONTEND, "1.0", [STATIC])
    cap, prov = cr.select_presentation(None, STATIC_URI, {"content": "x"})
    assert prov["presentation_source"] == "default-menu"
    assert cap is not None
