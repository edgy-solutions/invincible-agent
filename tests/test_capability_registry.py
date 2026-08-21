"""ADR-0017 amendment: the archetype decision binds to the CALLER'S menu, and every
decision says which menu it came from.

The failure this prevents is not misdelivery -- the session already knows the way home. It
is a CORRECT ANSWER WITH AN UNRENDERABLE PRESENTATION: choosing CHART_WIDGET because
cortex-ui registered it, then handing it to an OpenDDIL session that never did.

THE PIN THAT MATTERS MOST is `default-menu is LABELLED, never silent`. An unlabelled
fallback is indistinguishable from a registered caller's decision -- the
same-observation-opposite-reasons shape, and the reason the honest-outcome work exists at
all. Pinned here before the code has a chance to grow a quiet path.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_capability_registry.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.presentation_agent import capability_registry as reg  # noqa: E402

_CHART = {
    "subject_uri": "mesh:DatasetAnalysisReport",
    "object_uri": "mesh:ChartWidget",
    "archetype": "CHART_WIDGET",
}
_DOC = {
    "subject_uri": "mesh:OwnershipFact",
    "object_uri": "mesh:KnowledgeDocument",
    "archetype": "KNOWLEDGE_DOCUMENT",
}


@pytest.fixture(autouse=True)
def _clean():
    reg.clear()
    yield
    reg.clear()


def test_a_registered_caller_selects_from_ITS_OWN_menu():
    reg.register("cortex-ui-desktop", "1.2.3", [_CHART, _DOC])
    cap, prov = reg.select_archetype("cortex-ui-desktop", "mesh:DatasetAnalysisReport")
    assert cap is not None and cap["archetype"] == "CHART_WIDGET"
    assert prov["presentation_source"] == "registered"


def test_the_registration_version_is_stamped_into_the_decision():
    """A client registers at startup; an answer may compose twenty minutes later, after a
    redeploy. The stamp makes a mismatch read 'decided against v3, rendered by v4' instead
    of a silent wrong shape."""
    reg.register("cortex-ui-desktop", "1.2.3", [_CHART])
    _, prov = reg.select_archetype("cortex-ui-desktop", "mesh:DatasetAnalysisReport")
    assert prov["registration_version"] == "1.2.3"


def test_an_UNREGISTERED_caller_gets_the_default_menu_and_it_is_LABELLED():
    """THE LOAD-BEARING PIN. An unlabelled fallback is indistinguishable from a registered
    caller's decision. curl, scripts and UIs mid-onboarding must stay usable, and the
    envelope must say the answer came from the universal menu."""
    cap, prov = reg.select_archetype("nobody-registered-this", "mesh:DatasetAnalysisReport")
    assert cap is None
    assert prov["presentation_source"] == "default-menu"
    assert "KNOWLEDGE_DOCUMENT" in prov["presentation_menu"]


def test_a_missing_frontend_id_is_ALSO_the_labelled_default_not_a_crash():
    cap, prov = reg.select_archetype(None, "mesh:DatasetAnalysisReport")
    assert cap is None and prov["presentation_source"] == "default-menu"


def test_registered_but_unrenderable_is_DISTINCT_from_unregistered():
    """Folding the two would hide the actionable half: this client HAS a menu and this
    output is not on it. Different causes must not share an observation."""
    reg.register("opendil", "0.9", [_DOC])
    cap, prov = reg.select_archetype("opendil", "mesh:DatasetAnalysisReport")
    assert cap is None
    assert prov["presentation_source"] == "unrenderable"
    assert prov["registration_version"] == "0.9"


def test_two_frontends_get_DIFFERENT_answers_for_the_same_output_uri():
    """The multi-UI case the whole ruling exists for. cortex-ui renders the chart;
    OpenDDIL never registered it and must not be handed one."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART, _DOC])
    reg.register("opendil", "1.0", [_DOC])
    a, pa = reg.select_archetype("cortex-ui-desktop", "mesh:DatasetAnalysisReport")
    b, pb = reg.select_archetype("opendil", "mesh:DatasetAnalysisReport")
    assert a is not None and pa["presentation_source"] == "registered"
    assert b is None and pb["presentation_source"] == "unrenderable"


def test_every_decision_carries_a_presentation_source():
    """No path returns a decision without saying which menu produced it."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART])
    for fid, uri in (("cortex-ui-desktop", "mesh:DatasetAnalysisReport"),
                     ("cortex-ui-desktop", "mesh:Unknown"),
                     ("ghost", "mesh:DatasetAnalysisReport"),
                     (None, "mesh:DatasetAnalysisReport")):
        _, prov = reg.select_archetype(fid, uri)
        assert prov.get("presentation_source") in {"registered", "default-menu", "unrenderable"}


def test_full_iri_and_compact_forms_both_match():
    """The supervisor injects full-IRI form; registrations store compact. Exact == misses
    every match -- the compact-vs-full hazard, at the presentation boundary."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART])
    cap, _ = reg.select_archetype(
        "cortex-ui-desktop", "http://invincible-agent/mesh#DatasetAnalysisReport")
    assert cap is not None and cap["archetype"] == "CHART_WIDGET"


def test_re_registration_REPLACES_rather_than_merges():
    """A capability dropped in a redeploy must not survive as a ghost the backend keeps
    choosing."""
    reg.register("cortex-ui-desktop", "1.0", [_CHART, _DOC])
    reg.register("cortex-ui-desktop", "2.0", [_DOC])
    cap, prov = reg.select_archetype("cortex-ui-desktop", "mesh:DatasetAnalysisReport")
    assert cap is None
    assert prov["presentation_source"] == "unrenderable"
    assert prov["registration_version"] == "2.0"


def test_an_empty_frontend_id_registers_nothing():
    assert reg.register("", "1.0", [_CHART]) == 0
    assert reg.menu_for("") is None
