"""Serve one of the two built-in lookups the way a deployment does: from a declared dataset, read as
the caller. The lookups are asset-only (ruled 2026-11-25) and answer nothing on the seed, so a
census that posts every verb with `program_id` alone and no dataset reaches them through here.

Not a test module. Imported by the censuses that walk every `OUTPUT_URI` verb.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

REPO = Path(__file__).resolve().parents[2]
SAMPLE_CAL = REPO / "policy" / "overlays" / "sample" / "fin_calendar"


def lookup_params(fn: str) -> dict:
    """The parameters the lookup needs beyond `program_id`."""
    from tests.finance.test_fin_inputs_resolver import frame_of
    if fn == "fin_hierarchy_children":
        return {"element": frame_of()["control_account"][0]}
    return {}


def dataset_frame():
    from tests.finance.test_fin_inputs_resolver import frame_of
    return frame_of().with_columns(pl.lit("FY26-06").alias("status_period"))


def post_lookup(fn: str, params: dict, who: str):
    """POST `/measure/<fn>` with the EV fixture's contract and a one-grant asset. Returns the response."""
    from fastapi.testclient import TestClient

    from agent_fleet.finance_agent import fiscal_calendar
    from agent_fleet.finance_agent import main as engine
    from tests.finance.test_fin_inputs_resolver import token
    from tests.finance.test_variance_decomposition_over_the_ev_fixture import Gate, ROW_URN

    with pytest.MonkeyPatch.context() as mp, tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ev.parquet"
        dataset_frame().write_parquet(path)
        gate = Gate(pl.scan_parquet(path))
        gate.granted.add(who)
        mp.setattr(engine.asset_inputs, "_load_client", gate.load)
        mp.setenv("FIN_DATASET_URN", ROW_URN)
        mp.setenv("FIN_DATASET_BANNER", "SYNTHETIC TEST ASSET - not a real program.")
        mp.setenv("FIN_DATASET_CONTRACT", "ev_fixture")
        mp.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
        mp.setenv("FIN_CALENDAR_OVERLAY_DIRS", str(SAMPLE_CAL))
        fiscal_calendar._cache.clear()
        try:
            with TestClient(engine.app) as c:
                return c.post(f"/measure/{fn}", json={"params": {**params, **lookup_params(fn)}, "user_email": who},
                              headers={"Authorization": f"Bearer {token(who)}"})
        finally:
            fiscal_calendar._cache.clear()
