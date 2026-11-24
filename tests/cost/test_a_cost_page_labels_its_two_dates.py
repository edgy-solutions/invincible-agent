"""A cost package page labels its two dates (architect ruling, 2026-11-21; fin did this in #508).

`as_of` in a cost package is the GENERATION date (the request date unless the caller pins it). The
page used to show it as "as of", which reads as the data's date. Engine-cost reads only its seed,
so the data has no as-of of its own: the page now reads `data as of <sample wording>` and
`generated <as_of>`. The key `as_of` keeps its name (the body, the response, the audit line, the
CLI's --as-of, the BFF); `data_as_of` is the one new key.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import cost_package_identities as I  # noqa: E402

from agent_fleet.cost_agent import export as X  # noqa: E402
from agent_fleet.cost_agent import measures as M  # noqa: E402
from agent_fleet.cost_agent.seed import build_state  # noqa: E402

# Spelled out here, not read from the module: the seal says what the field must read.
SAMPLE = "sample data (notional seed): no as-of"
ALPHA = "notional-customer-alpha"
_ONE_ANSWER = {"answers": [{"id": "only", "verb_iri": "mesh:costLaborComposition",
                            "subject_instance_id": 3}]}
PINNED = "2031-03-04"


@pytest.fixture(scope="module")
def state():
    return build_state()


def _needs_the_runtime():
    pytest.importorskip("duckdb", reason="duckdb is not installed in this venv")
    if not (ROOT / ".pyodide-cache" / "pyodide.js").exists():
        pytest.skip("the pinned Pyodide runtime is not fetched here")


def _export(state, isolated_dist, monkeypatch, *, canvas=None, as_of=None):
    if as_of is not None:
        monkeypatch.setattr(M, "_request_date", lambda: as_of)
    out = M.package_export(state, recipient_scope=ALPHA, canvas=canvas)
    html = (isolated_dist / out["artifact_filename"]).read_text(encoding="utf-8")
    return out, html


@pytest.mark.parametrize("canvas", [None, _ONE_ANSWER], ids=["fixed-page", "dataset-page"])
def test_the_page_carries_both_labelled_dates(state, isolated_dist, monkeypatch, canvas):
    _needs_the_runtime()
    out, html = _export(state, isolated_dist, monkeypatch, canvas=canvas)
    assert f"data as of {SAMPLE}" in html
    assert f"generated {out['as_of']}" in html
    assert "&middot; as of " not in html


@pytest.mark.parametrize("canvas", [None, _ONE_ANSWER], ids=["fixed-page", "dataset-page"])
def test_a_pinned_as_of_is_the_generated_date_never_the_data_date(state, isolated_dist, monkeypatch, canvas):
    _needs_the_runtime()
    _, html = _export(state, isolated_dist, monkeypatch, canvas=canvas, as_of=PINNED)
    meta = next(ln for ln in html.splitlines() if 'class="meta"' in ln and "algorithm" in ln)
    data_part, generated_part = meta.split("generated", 1)
    assert PINNED not in data_part
    assert PINNED in generated_part
    assert f"data as of {SAMPLE}" in data_part


@pytest.mark.parametrize("canvas", [None, _ONE_ANSWER], ids=["fixed-page", "dataset-page"])
def test_the_response_and_the_package_carry_data_as_of(state, isolated_dist, monkeypatch, canvas):
    _needs_the_runtime()
    out, html = _export(state, isolated_dist, monkeypatch, canvas=canvas, as_of=PINNED)
    assert out["data_as_of"] == SAMPLE
    assert out["as_of"] == PINNED
    pkg = I.package_from_html(html)
    assert pkg["data_as_of"] == SAMPLE
    assert pkg["as_of"] == PINNED


def test_the_package_body_carries_data_as_of_without_a_runtime(state):
    pkg = X.build_package(state, recipient_scope=ALPHA, algorithm_sha="test", as_of=PINNED)
    assert pkg["data_as_of"] == SAMPLE and pkg["as_of"] == PINNED


def test_cost_and_finance_spell_the_sample_string_alike():
    from agent_fleet.finance_agent import export_dates
    assert X.SAMPLE_DATA_AS_OF == export_dates.SAMPLE_DATA_AS_OF == SAMPLE
