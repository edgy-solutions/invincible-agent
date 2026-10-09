"""scripts/rebuild_cost_package_from_duckdb.py is deterministic: the same .duckdb, sha and date
give the same page, byte for byte, twice.

The page's two non-data inputs (the date and the algorithm commit) are ARGUMENTS, so nothing in
the output is read from a clock. If this goes red, something time- or run-dependent entered the
page (a timestamp, a dict-order, a uuid), and a package could no longer be re-derived.
Skipped, by name, where `duckdb` or the pinned Pyodide runtime is not on the box.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pytest.importorskip("duckdb", reason="duckdb is declared by cost_agent, not the root venv")
RUNTIME = ROOT / ".pyodide-cache"
pytestmark = pytest.mark.skipif(not (RUNTIME / "pyodide.asm.wasm").exists(),
                                reason="the pinned Pyodide runtime is not fetched")

from scripts import rebuild_cost_package_from_duckdb as R  # noqa: E402
from scripts.build_cost_dataset import build as build_dataset  # noqa: E402

SCOPE = "notional-customer-alpha"
SHA = "0" * 40
AS_OF = "2026-01-02"


@pytest.fixture(scope="module")
def duckdb_file(tmp_path_factory):
    return build_dataset(SCOPE, tmp_path_factory.mktemp("db") / f"cost-{SCOPE}.duckdb")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_the_dataset_page_is_identical_on_a_second_build(duckdb_file):
    a = R.rebuild(duckdb_file, SCOPE, RUNTIME, sha=SHA, as_of=AS_OF)
    b = R.rebuild(duckdb_file, SCOPE, RUNTIME, sha=SHA, as_of=AS_OF)
    assert _h(a) == _h(b)


def test_the_one_file_page_is_identical_on_a_second_build(duckdb_file):
    a = R.rebuild(duckdb_file, SCOPE, RUNTIME, sha=SHA, as_of=AS_OF, slice1=True)
    b = R.rebuild(duckdb_file, SCOPE, RUNTIME, sha=SHA, as_of=AS_OF, slice1=True)
    assert _h(a) == _h(b)


def test_the_date_is_an_input_not_a_clock(duckdb_file):
    a = R.rebuild(duckdb_file, SCOPE, RUNTIME, sha=SHA, as_of=AS_OF)
    c = R.rebuild(duckdb_file, SCOPE, RUNTIME, sha=SHA, as_of="2026-01-03")
    assert _h(a) != _h(c) and R.package_data(c)["as_of"] == "2026-01-03"


def test_the_recipient_is_read_from_the_file_name_and_refused_when_unknown(tmp_path):
    assert R.recipient_from_name(pathlib.Path(f"cost-{SCOPE}.duckdb")) == SCOPE
    with pytest.raises(SystemExit):
        R.recipient_from_name(pathlib.Path("cost-nobody.duckdb"))
