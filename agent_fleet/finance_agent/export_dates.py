"""The two dates an export carries, each labelled.

Ruling (architect, 2026-11-21): an export carries two separate dates -- when the data is as of,
and when the export was generated. The generation time is never shown as the data date. The
data's as-of comes from the source's own as-of (the asset read's ticket receipt), the same value
the answer shows. When the as-of is unavailable the export says so in that field; it is never
blank and never filled with the generation time.

The strings here match the answer's `ticket_clause` wording in PR #496 (not on master yet).
`asset_inputs` is deliberately not imported: this module needs nothing from the fleet.
"""
from __future__ import annotations

AS_OF_UNAVAILABLE = "as-of unavailable"
ADVERTISED_AT_LOAD = "advertised_at_load"
SAMPLE_DATA_AS_OF = "sample data (notional seed): no as-of"


def data_as_of(receipt: dict | None) -> str:
    """The data's as-of, as the export shows it. Never blank, never the generation date.

    A seed-sourced export (no receipt) says the data is sample data (ruling, architect,
    2026-11-21 night): the field never shows a date that reads as real.
    """
    if receipt is None:  # a seed-sourced export reads no asset
        return SAMPLE_DATA_AS_OF
    as_of = receipt.get("as_of")
    if not as_of:
        reason = receipt.get("as_of_unavailable")
        return f"{AS_OF_UNAVAILABLE}: {reason}" if reason else AS_OF_UNAVAILABLE
    if receipt.get("as_of_source") == ADVERTISED_AT_LOAD:
        return f"{as_of} (advertised at load, not read for this export)"
    return str(as_of)
