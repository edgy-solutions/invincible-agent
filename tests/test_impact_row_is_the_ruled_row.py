"""`ImpactRow` is ADR-0065 ruling 4's row: its fields come from the ADR text, not a copy of them.

Since SDK v0.9.26 the served row IS the SDK's row (its fields, its provenance entries, its
validators), with `qty_per` widened to take the fraction the dataset loader accepts. The ruled
field list is the ADR's LAST `ImpactRow = {...}` line, so an amendment supersedes the original.

Run: uv run pytest tests/test_impact_row_is_the_ruled_row.py -q
"""
from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_fleet.ontology_service import where_used as w
from agent_fleet.ontology_service.where_used import ImpactRow

ADR = next((Path(__file__).resolve().parents[1] / "docs/adr").glob("ADR-0065-*.md"))


def _ruled_fields() -> list[str]:
    text = re.sub(r"\s+", " ", ADR.read_text(encoding="utf-8"))
    found = re.findall(r"`ImpactRow = \{([^}]+)\}`", text)
    assert found, "ruling 4's ImpactRow line moved; update this reader"
    return [f.strip() for f in found[-1].split(",")]


def _row(**over):
    base = dict(end_item="e", program="p", component="c", qty_per=1, configuration="as_designed",
                as_of=None, data_provenance=[{"as_of": None}])
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


def test_THE_ROW_IS_THE_SDKS_AND_ONLY_QTY_PER_DIFFERS():
    """The local row is the SDK's class with one field re-annotated, nothing else of its own."""
    sdk = _sdk_impact_row()
    assert sdk is not None, "v0.9.26 is pinned; the SDK has an ImpactRow"
    assert issubclass(ImpactRow, sdk)
    assert w.DataProvenance is _sdk_provenance_entry(sdk)
    differ = [n for n, f in ImpactRow.model_fields.items()
              if f.annotation != sdk.model_fields[n].annotation]
    assert differ == ["qty_per"], differ
    assert set(vars(ImpactRow).get("__annotations__", {})) == {"qty_per"}


def test_EVERY_SERVED_ROW_IS_A_VALID_SDK_ROW():
    """The served rows, dumped to the wire, validate through the SDK's own row unchanged."""
    sdk = _sdk_impact_row()
    rows = _served_rows()
    assert rows
    for row in rows:
        assert sdk(**row).model_dump() == row


def test_A_SERVED_ENTRY_STATES_EACH_ABSENCE_AND_ONLY_ABSENCES():
    for row in _served_rows():
        assert row["absent_reason"]["population"] and row["absent_reason"]["stock"]
        for entry in row["data_provenance"]:
            reasons = entry["absent_reason"] or {}
            absent = {k for k in ("dataset_urn", "as_of", "ticket_id", "locator", "classification",
                                  "notional") if entry[k] is None}
            assert set(reasons) == absent, (entry["name"], reasons, absent)


def test_TRIPWIRE_A_FRACTIONAL_QTY_PER_IS_THE_ONLY_REASON_THE_ROW_IS_NOT_A_RE_EXPORT():
    """The loader takes any positive number as a usage quantity, and the SDK's `qty_per` is `int`.
    So a served row that rolls up to a fraction is refused by the SDK row, on `qty_per` alone. When
    the SDK takes the fraction, or the loader stops accepting one, this fails: re-export the SDK
    row as it is then, and delete the subclass."""
    sdk = _sdk_impact_row()
    assert w._positive_number(2.5), "the loader now refuses a fraction: re-export the SDK row"
    row = {**_served_rows()[0], "qty_per": 2.5}
    assert ImpactRow(**row).qty_per == 2.5
    try:
        sdk(**row)
    except ValidationError as e:
        assert [x["loc"] for x in e.errors()] == [("qty_per",)], e.errors()
    else:
        pytest.fail("the SDK's ImpactRow now takes a fractional qty_per: re-export it")


def _sdk_provenance_entry(sdk):
    ann = sdk.model_fields["data_provenance"].annotation
    args = typing.get_args(ann)
    return args[0] if len(args) == 1 else ann


#: v0.9.26's provenance, as read from the installed tag: the container, each entry's
#: (field, annotation, required), and whether an entry refuses unknown keys.
_V0926_PROVENANCE = {
    "container": "list",
    "entry": [("name", "typing.Optional[str]", False), ("dataset_urn", "typing.Optional[str]", False),
              ("as_of", "typing.Optional[str]", True), ("ticket_id", "typing.Optional[str]", False),
              ("locator", "typing.Optional[str]", False),
              ("classification", "typing.Optional[str]", False),
              ("notional", "typing.Optional[bool]", False),
              ("absent_reason", "typing.Optional[dict[str, str]]", False)],
    "extra": "forbid",
}


def _annotation(a) -> str:
    return a.__name__ if isinstance(a, type) else str(a)


def test_TRIPWIRE_THE_SDKS_PROVENANCE_IS_STILL_V0926S_ENTRY():
    """Ruled 11-19: the provenance entry must carry what is served, and the served row is pinned to
    v0.9.26. It fails on ANY change to v0.9.26's provenance: read the new shape, and see whether
    the served entries still fit it before re-pinning."""
    sdk = _sdk_impact_row()
    assert sdk is not None, "v0.9.26 is pinned; the SDK has an ImpactRow"
    ann = sdk.model_fields["data_provenance"].annotation
    origin = typing.get_origin(ann)
    entry = _sdk_provenance_entry(sdk)
    got = {
        "container": _annotation(origin) if origin is not None else _annotation(ann),
        "entry": [(n, _annotation(f.annotation), f.is_required())
                  for n, f in getattr(entry, "model_fields", {}).items()],
        "extra": getattr(entry, "model_config", {}).get("extra"),
    }
    assert got == _V0926_PROVENANCE, (
        f"the SDK's provenance changed ({got}); see whether a served row fits it, and re-pin")
