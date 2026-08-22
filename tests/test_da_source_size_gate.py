"""ENGINE DA MUST REFUSE, NOT DIE — the source-size gate.

WHAT WENT WRONG (filed 2026-08-22 as engine-da-ooms-on-a-plausible-question,
still crashlooping at 6 restarts when this was written). `get_dataframe` returns
a LAZY frame (`pl.scan_parquet`), and the next line threw that laziness away:

    lazy_df = client.get_dataframe(urn)
    dataset = lazy_df.collect()          # <- the ENTIRE source table, in memory
    con.register("dataset", dataset)     # <- only NOW does the GROUP BY run

So `SELECT company, ARRAY_AGG(DISTINCT cage_code) ... GROUP BY company` over a
wide publog table materialised everything before the aggregation that would have
shrunk it. 2Gi container, kernel kills the pod, exit 137, CrashLoopBackOff.

WHY IT OUTRANKS ITS SIZE, and why an exception is the FIX rather than a
consolation: the failure was SILENT FROM THE UI. Routing resolved with high
confidence, the answer card rendered its title, and the body was empty with
"No citations yet. Evidence appears as engines return matches." — literally true
and reads like patience rather than death. A confident blank is worse than an
error, because nobody knows to go looking.

THE GATE COUNTS CELLS, NOT ROWS. The memory a load costs is a property of the
TABLE's shape, not of the question, so a row-only cap leaves the next WIDER table
finding the same cliff — which is also why raising the container limit only MOVES
the cliff instead of removing it.

Run: uv run --frozen --with pytest --with polars pytest tests/test_da_source_size_gate.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "agent_fleet" / "data_analyst" / "main.py"


def _source() -> str:
    return _SRC.read_text(encoding="utf-8")


# ── the shape of the fix, pinned at the source ─────────────────────────────

def test_the_source_table_is_NOT_collected_before_the_query():
    """THE REGRESSION ARM. `lazy_df.collect()` here is the OOM: it materialises
    the whole table one line after the laziness was acquired."""
    # Comments are excluded deliberately: the fix DOCUMENTS the removed line
    # verbatim, and an assertion that cannot tell code from its own explanation
    # would go red on the commentary that makes the fix legible — punishing the
    # thing that helps the next reader.
    code = [
        ln for ln in _source().splitlines()
        if not ln.lstrip().startswith("#")
    ]
    offenders = [ln for ln in code if "lazy_df.collect()" in ln]
    assert not offenders, (
        f"the source table is being materialised before the query runs — the "
        f"exact line that OOMs the container: {offenders[:1]}"
    )


def test_the_lazy_frame_is_what_gets_registered():
    """DuckDB consumes a polars LazyFrame directly (verified duckdb 1.5.5 /
    polars 1.43), so registering the LAZY frame lets it push work down."""
    src = _source()
    assert 'con.register("dataset", lazy_df)' in src


def test_a_size_gate_runs_BEFORE_the_query():
    """The gate is the protection; laziness is opportunistic. Whether DuckDB
    streams or collects internally is its business, so the bound must not depend
    on it."""
    src = _source()
    gate_at = src.index("_MAX_SOURCE_CELLS")
    register_at = src.index('con.register("dataset", lazy_df)')
    assert gate_at < register_at, "the size gate must precede the query"


def test_the_gate_measures_CELLS_not_rows():
    """A row-only cap leaves the next wider table finding the same cliff."""
    src = _source()
    assert "collect_schema()" in src, "the gate ignores table WIDTH"
    assert "n_rows * max(n_cols or 1, 1)" in src


def test_the_refusal_NAMES_the_limit_and_forbids_retry():
    """An agent that retries an oversized query just OOMs again. The refusal has
    to carry both the cause and the remedy."""
    src = _source()
    assert "SOURCE_TOO_LARGE" in src
    assert "Do NOT retry" in src
    assert "narrow it first" in src


def test_a_precheck_that_cannot_run_is_LOUD_not_a_silent_bypass():
    """If the gate cannot measure, it proceeds — but says so. A guard that
    silently stops guarding is worse than no guard, because it is trusted."""
    src = _source()
    assert "DA_SIZE_PRECHECK_FAILED" in src
    assert "UNGATED" in src


# ── the measurement itself, executed ───────────────────────────────────────

def test_the_row_count_is_computed_lazily_and_is_correct():
    """`select(pl.len())` pushes down to parquet metadata rather than reading the
    table — the gate must not cost what it is preventing."""
    lf = pl.LazyFrame({"company": ["a", "b", "a"], "cage": ["1", "2", "3"]})
    assert int(lf.select(pl.len()).collect().item()) == 3


def test_the_schema_is_readable_without_collecting():
    lf = pl.LazyFrame({"company": ["a"], "cage": ["1"], "x": [2]})
    assert len(lf.collect_schema().names()) == 3


@pytest.mark.parametrize("rows,cols,limit,refused", [
    (1_000, 10, 40_000_000, False),          # ordinary table: allowed
    (2_000_000, 20, 40_000_000, False),      # exactly at the limit: allowed
    (2_000_001, 20, 40_000_000, True),       # one row over: refused
    (1_000, 1_000_000, 40_000_000, True),    # NARROW BUT ENORMOUSLY WIDE: refused
])
def test_the_cell_arithmetic_discriminates_by_shape(rows, cols, limit, refused):
    """THE WIDTH ARM. The fourth case is the one a row cap misses entirely: few
    rows, absurd width, same memory disaster."""
    assert ((rows * max(cols, 1)) > limit) is refused


def test_duckdb_can_consume_a_lazyframe_at_all():
    """The assumption the fix rests on, executed rather than trusted. If a future
    duckdb drops LazyFrame support this goes red HERE rather than in a pod."""
    duckdb = pytest.importorskip("duckdb")
    lf = pl.LazyFrame({"company": ["a", "b", "a"], "cage": ["1", "2", "3"]})
    con = duckdb.connect()
    try:
        con.register("dataset", lf)
        out = con.execute(
            "SELECT company, count(*) AS n FROM dataset GROUP BY company"
        ).pl()
        assert out.height == 2
    finally:
        con.close()
