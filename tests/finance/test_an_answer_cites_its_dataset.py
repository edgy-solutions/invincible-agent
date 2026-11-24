"""A finance answer names the dataset it came from (architect, 2026-11-23).

cortex shows "No external sources cited" when the artifact has no `sources`; engine-fin never set
them. Each envelope builder now serves ONE `catalog_asset` source: the dataset's URN, its name as
the label, and its as-of (`export_dates.data_as_of`) as `data_as_of` and in the snippet. A
seed-sourced answer read no asset and carries no `sources` key.

The fixtures are the existing ones: `test_fin_inputs_resolver` (the built-in path, through the
ticketed-read seam) and `test_a_dataset_series_row_draws_from_the_asset` (the dataset-series path).

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -o addopts= -q tests/finance/test_an_answer_cites_its_dataset.py
"""
from __future__ import annotations

import json

import pytest

pl = pytest.importorskip("polars")

from agent_fleet.finance_agent import asset_inputs, export_dates  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_a_dataset_series_row_draws_from_the_asset import (  # noqa: E402,F401
    CUM, ROW_URN, PROGRAM, gate, post, series_rows,
)
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    ALICE, AS_OF, URN, _clean_env, client, declared, flag, frame_of, measure, on, seam,
)
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402,F401
    ALLOWED as FLOW_CALLER, FN as FLOW_FN, Gate, ROW_URN as FLOW_URN, flow_rows, token,
)


@pytest.fixture
def members(monkeypatch):
    """One `members` for both imported fixture families (the resolver's and the series file's)."""
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == PROGRAM and caller_id == ALICE)
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))


@pytest.fixture
def flow_post(flow_rows, members, tmp_path, monkeypatch):
    """The shipped flow row `fin_flow_acwp` (a contribution ranking, NOT a series) through `/measure`."""
    from fastapi.testclient import TestClient
    path = tmp_path / "ev.parquet"
    frame_of().write_parquet(path)
    monkeypatch.setattr(engine.asset_inputs, "_load_client", Gate(pl.scan_parquet(path)).load)
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")   # FIN_DATASET_URN stays UNSET
    with TestClient(engine.app) as c:
        r = c.post(f"/measure/{FLOW_FN}", json={"params": {"program_id": PROGRAM}, "user_email": FLOW_CALLER},
                   headers={"Authorization": f"Bearer {token(FLOW_CALLER)}"})
        yield r.status_code, r.json()


NAME = "fin_test_asset"  # the NAME PART of the resolver's URN, asserted against the label below


def _builtin(client, seam, tmp_path, **ticket):
    path = tmp_path / "fin.parquet"
    frame_of().write_parquet(path)
    seam.frame = pl.scan_parquet(path)
    seam.ticket = ticket
    r = measure(client, "fin_tcpi")
    assert r.status_code == 200, r.text
    return r.json(), seam.issued[-1]


def _one_source(env, urn, receipt):
    assert len(env["sources"]) == 1
    src = env["sources"][0]
    as_of = export_dates.data_as_of(receipt)
    assert src["type"] == "catalog_asset"
    assert src["uri"] == urn
    assert src["label"] == urn.split(",")[1] != urn
    assert src["data_as_of"] == as_of
    assert as_of in src["snippet"]
    assert asset_inputs.ticket_clause(receipt) in src["snippet"]
    assert len(src["snippet"]) < 240
    return src


# 1. an asset-sourced answer carries one source

def test_a_builtin_answer_cites_its_dataset(client, seam, tmp_path):
    env, receipt = _builtin(client, seam, tmp_path)
    src = _one_source(env, URN, receipt)
    assert src["label"] == NAME
    assert env["data_provenance"].endswith(f"Source: {URN}")  # the same read as the provenance


def test_a_dataset_series_answer_cites_its_dataset(post, gate):
    status, env = post()
    assert status == 200, env
    src = env["sources"][0]
    assert len(env["sources"]) == 1
    assert (src["type"], src["uri"]) == ("catalog_asset", ROW_URN)
    assert src["label"] == ROW_URN.split(",")[1]
    assert src["data_as_of"] in src["snippet"]
    assert AS_OF in src["data_as_of"]
    assert "tkt-0001" in src["snippet"]


def test_a_dataset_row_answer_cites_its_dataset(flow_post):
    """Gov's mutant: `_dataset_envelope` dropped its `sources` line and the series row alone was driven."""
    status, env = flow_post
    assert status == 200, env
    assert "series" not in env  # the NON-series dataset envelope: a contribution ranking, not `_dataset_series_envelope`
    assert len(env["sources"]) == 1
    src = env["sources"][0]
    assert (src["type"], src["uri"]) == ("catalog_asset", FLOW_URN)
    assert src["label"] == FLOW_URN.split(",")[1] == "ev_fixture"
    assert "Data as of:" in src["snippet"]
    assert src["data_as_of"] in src["snippet"]


# 2. the as-of cases, through the answer's source

def test_a_receipt_without_an_as_of_says_why(client, seam, tmp_path):
    env, receipt = _builtin(client, seam, tmp_path, as_of=None, as_of_unavailable="no_reader_for_source_type")
    assert not receipt.get("as_of")
    src = _one_source(env, URN, receipt)
    assert src["data_as_of"].startswith(export_dates.AS_OF_UNAVAILABLE)


def test_a_receipt_advertising_an_as_of_says_so(client, seam, tmp_path):
    env, receipt = _builtin(client, seam, tmp_path, as_of_source=export_dates.ADVERTISED_AT_LOAD)
    src = _one_source(env, URN, receipt)
    assert "advertised at load" in src["data_as_of"]
    assert receipt["as_of"] in src["data_as_of"]


# 3. a seed-sourced answer has no `sources`

def test_a_seed_answer_has_no_sources_key(declared, members, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")  # FIN_DATASET_URN unset: the seed
    with TestClient(engine.app) as c:
        r = measure(c, "fin_tcpi")
    assert r.status_code == 200, r.text
    assert "sources" not in r.json()
    assert "data_source" not in r.json()


def test_the_helper_is_empty_for_no_asset_and_names_an_odd_urn_whole():
    assert engine._answer_sources(None, None) == []
    odd = engine._answer_sources("not-a-dataset-urn", {"as_of": "2026-01-01"})
    assert odd[0]["label"] == "not-a-dataset-urn"


def test_the_sandbox_snippet_fits_the_gateways_cap():
    urn = "urn:li:dataset:(urn:li:dataPlatform:s3,ev_fixture,PROD)"
    (src,) = engine._answer_sources(urn, {"urn": urn, "ticket_id": "tkt-0123456789abcdef",
                                          "as_of_unavailable": "no_reader_for_source_type"})
    assert src["label"] == "ev_fixture"
    assert len(src["snippet"]) < 240


# 4. the consumer: the gateway projects the source

def test_the_gateway_keeps_a_fin_source(client, seam, tmp_path):
    from src.iagent import gateway as gw
    env, receipt = _builtin(client, seam, tmp_path)
    mat = {"metadataEntries": [{"label": "sources_json", "text": json.dumps(env["sources"])}]}
    (out,) = gw._project_sources(mat)
    want = env["sources"][0]
    for k in ("uri", "label", "type", "snippet"):
        assert out[k] == want[k], k
