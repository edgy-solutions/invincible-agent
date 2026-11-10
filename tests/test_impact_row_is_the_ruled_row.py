"""`ImpactRow` is ADR-0065 ruling 4's row: its fields come from the ADR text, not a copy of them.

Run: uv run pytest tests/test_impact_row_is_the_ruled_row.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_fleet.ontology_service import where_used as w
from agent_fleet.ontology_service.where_used import ImpactRow

ADR = next((Path(__file__).resolve().parents[1] / "docs/adr").glob("ADR-0065-*.md"))


def _ruled_fields() -> list[str]:
    text = re.sub(r"\s+", " ", ADR.read_text(encoding="utf-8"))
    m = re.search(r"`ImpactRow = \{([^}]+)\}`", text)
    assert m, "ruling 4's ImpactRow line moved; update this reader"
    return [f.strip() for f in m.group(1).split(",")]


def _row(**over):
    base = dict(end_item="e", program="p", component="c", qty_per=1, configuration="as_designed",
                as_of=None, data_provenance={})
    return ImpactRow(**{**base, **over})


def test_THE_FIELDS_ARE_THE_RULED_LIST_IN_ORDER():
    assert list(ImpactRow.model_fields) == _ruled_fields()


def test_AN_EXTRA_FIELD_IS_REFUSED_AND_THE_ROW_IS_FROZEN():
    with pytest.raises(ValidationError):
        _row(part_ref="x")
    with pytest.raises(ValidationError):
        _row().qty_per = 2


def test_ABSENT_POPULATION_AND_STOCK_DEFAULT_TO_NONE_NOT_ZERO():
    r = _row()
    assert r.population is None and r.stock is None


def _sdk_impact_row():
    sdk = None
    for mod in ("iagent_mesh", "iagent_mesh.contracts"):
        try:
            m = __import__(mod, fromlist=["ImpactRow"])
        except ImportError:
            continue
        sdk = getattr(m, "ImpactRow", None) or sdk
    return sdk


def _served_rows():
    """The rows the shipped fixture serves, every program visible."""
    ds = w.load_dataset(Path(__file__).resolve().parents[1] / w.SHIPPED_LOCATOR)
    part = next(i for i, v in ds.identities.items()
                if any(str(a.get("value", "")).endswith("PN-1001") for a in v.get("aliases", [])))
    got = w.where_used(ds, part, caller_id="t", can_view_program=lambda p, c: True)
    assert got["status"] == "ok", got
    return got["where_used"]


def test_THE_SDKS_IMPACT_ROW_HAS_THE_RULED_FIELDS():
    sdk = _sdk_impact_row()
    if sdk is None:
        pytest.skip("the SDK has no ImpactRow")
    assert list(sdk.model_fields) == _ruled_fields()


def test_TRIPWIRE_THE_SDKS_ROW_CANNOT_CARRY_A_SERVED_ROW_AND_ONLY_ITS_PROVENANCE_IS_WHY():
    """v0.9.17's `DataProvenance` is one `{dataset_urn, as_of, ticket_id}` triple, each a required
    string. A served row has one provenance entry per input, and the shipped fixture states no
    dataset URN (no catalogue entry) and no ticket (no broker read). Re-exporting would mean
    inventing those values, so the local row stays. When the SDK's row accepts a served row as
    it is, this fails: re-export it then. A refusal outside `data_provenance` fails too."""
    sdk = _sdk_impact_row()
    if sdk is None:
        pytest.skip("the SDK has no ImpactRow")
    rows = _served_rows()
    assert rows
    for row in rows:
        try:
            sdk(**row)
        except ValidationError as e:
            outside = [x["loc"] for x in e.errors() if x["loc"][:1] != ("data_provenance",)]
            assert not outside, f"the SDK row refuses a served row outside its provenance: {outside}"
        else:
            pytest.fail("the SDK's ImpactRow now carries a served row: re-export it")
