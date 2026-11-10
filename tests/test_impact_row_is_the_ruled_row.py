"""`ImpactRow` is ADR-0065 ruling 4's row: its fields come from the ADR text, not a copy of them.

Run: uv run pytest tests/test_impact_row_is_the_ruled_row.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_TRIPWIRE_THE_SDKS_IMPACT_ROW_ONCE_IT_IS_THE_RULED_ONE_REPLACES_THE_LOCAL_COPY():
    sdk = None
    for mod in ("iagent_mesh", "iagent_mesh.contracts"):
        try:
            m = __import__(mod, fromlist=["ImpactRow"])
        except ImportError:
            continue
        sdk = getattr(m, "ImpactRow", None) or sdk
    fields = list(getattr(sdk, "model_fields", {})) if sdk is not None else []
    if fields != _ruled_fields():
        pytest.skip("the SDK has no ImpactRow, or one of the old shape")
    pytest.fail("re-export the SDK's ImpactRow")
