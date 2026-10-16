"""A SafetyCriticalItem is spoken by its part number (`part_number` on the entity), not only by
its CSI id. Matched exactly first, then normalised (casefold, trim, space/hyphen/underscore
equivalent); a normalised tie is returned whole, never picked from."""
from __future__ import annotations

from dataclasses import replace

import pytest

from agent_fleet.safety_agent import entities, instances

CSI = instances.SAFETY + "SafetyCriticalItem"


def _ids(q):
    return [c["instance_id"] for c in instances.resolve(q, CSI)]


def test_fixture_holds_pn_8802_on_csi_5002():
    assert {c.csi_id: c.part_number for c in entities.CRITICAL_ITEMS}["CSI-5002"] == "PN-8802"


def test_exact_part_number_resolves():
    assert _ids("PN-8802") == ["CSI-5002"]


@pytest.mark.parametrize("spoken", ["pn 8802", "Pn_8802", "  PN-8802 ", "pn - 8802", "  pn 8802 "])
def test_normalised_spelling_resolves_to_the_same_csi(spoken):
    assert _ids(spoken) == ["CSI-5002"]


def test_candidate_shape_is_the_id_hit_shape():
    by_pn = instances.resolve("pn 8802", CSI)[0]
    by_id = instances.resolve("CSI-5002", CSI)[0]
    assert set(by_pn) == set(by_id) == {"class_uri", "instance_id", "label", "score"}
    assert by_pn["instance_id"] == by_id["instance_id"]


def test_csi_id_still_resolves():
    assert _ids("CSI-5002") == ["CSI-5002"]


@pytest.mark.parametrize("spoken", ["PN-9999", "8802", "PN-880", ""])
def test_unknown_or_bare_part_number_does_not_resolve(spoken):
    assert _ids(spoken) == []


def _two(monkeypatch, a, b):
    base = entities.CRITICAL_ITEMS[0]
    items = (replace(base, csi_id="CSI-7001", part_number=a), replace(base, csi_id="CSI-7002", part_number=b))
    monkeypatch.setattr(instances, "CRITICAL_ITEMS", items)


def test_normalised_collision_returns_both_at_one_score_never_one(monkeypatch):
    _two(monkeypatch, "PN-9001", "pn 9001")
    got = instances.resolve("PN_9001", CSI)
    assert sorted(c["instance_id"] for c in got) == ["CSI-7001", "CSI-7002"]
    assert len({c["score"] for c in got}) == 1


def test_exact_beats_normalised(monkeypatch):
    _two(monkeypatch, "PN-9001", "pn 9001")
    assert _ids("PN-9001") == ["CSI-7001"]
