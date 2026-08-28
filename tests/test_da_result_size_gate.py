"""ENGINE DA MUST REFUSE ON THE WAY OUT TOO — the result-size gate.

THE SIBLING OF `test_da_source_size_gate.py`, AND DELIBERATELY IN A DIFFERENT
UNIT. That gate counts CELLS because its constraint is RAM, and memory is a
property of a table's width x length. This one counts BYTES because the result
is serialised, printed, and becomes the CodeAgent's OBSERVATION — part of the
next model prompt — so its constraint is the CONTEXT WINDOW.

THE TWO CEILINGS DO NOT CONVERT INTO EACH OTHER, which is the whole point and is
executed below rather than argued. The question that failed at work:

    SELECT company, ARRAY_AGG(DISTINCT cage_code) FROM dataset GROUP BY company

returns a few hundred rows, each carrying a LIST of every code for its company.
The row COUNT collapses under the GROUP BY; the DATA VOLUME does not. Measured
on a 500k-row x 2-col source: source 1,000,000 cells (passes), result 400 CELLS
(passes by five orders of magnitude), payload 4.0 MB — about a million tokens.
A cell gate on the result side would be the RAM mistake relocated one stage
downstream.

REFUSE, NOT TRUNCATE. A truncated aggregate is not a partial answer, it is a
FALSE one: a distinct-codes list cut off at the limit reads as complete. The
refusal names the result's own numbers so the agent can narrow the question
itself — the same discipline as SOURCE_TOO_LARGE's "narrow it first".

Run: uv run --frozen --with pytest --with polars --with duckdb pytest tests/test_da_result_size_gate.py -v
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "agent_fleet" / "data_analyst" / "main.py"


def _source() -> str:
    return _SRC.read_text(encoding="utf-8")


def _code() -> list[str]:
    """Source with comment lines dropped.

    The fix DOCUMENTS what it replaced, so an assertion that cannot tell code
    from its own explanation would go red on the commentary that makes the fix
    legible — punishing the thing that helps the next reader. Same convention as
    the source-gate suite.
    """
    return [ln for ln in _source().splitlines() if not ln.lstrip().startswith("#")]


# -- LAYER 1: the result gate, pinned at the source -------------------------

def test_a_result_gate_exists_and_is_measured_in_BYTES():
    src = _source()
    assert "_MAX_RESULT_BYTES" in src, "nothing bounds the answer we RETURN"
    assert "DA_MAX_RESULT_BYTES" in src, "the bound must be tunable per deployment"
    joined = "\n".join(_code())
    assert 'encode("utf-8")' in joined, (
        "the bound must be in BYTES of the serialised payload — a character "
        "count is not what enters the prompt"
    )


def test_the_gate_runs_AFTER_the_query_and_BEFORE_the_return():
    """It bounds what crosses into the prompt, not what DuckDB computes."""
    joined = "\n".join(_code())
    query_at = joined.index("con.execute(sql_query)")
    # ANCHORED ON THE GUARD, not on the identifier: `_MAX_RESULT_BYTES` first
    # appears at the top of the file as the constant's declaration, which is
    # above everything and would make this assertion pass on position alone.
    gate_at = joined.index("if n_bytes > _MAX_RESULT_BYTES:")
    assert query_at < gate_at, "the result cannot be measured before it exists"
    assert joined.index("return payload") > gate_at, (
        "the payload must not be returnable before it has been measured"
    )


def test_the_result_is_serialised_EXACTLY_ONCE():
    """`write_json` IS the cost being bounded. Paying it in the gate and again
    in the return would double the very thing the gate exists to limit."""
    calls = [ln for ln in _code() if "write_json()" in ln]
    assert len(calls) == 1, (
        f"the result is serialised {len(calls)} times; measuring and returning "
        f"must share one payload: {calls}"
    )


def test_the_refusal_NAMES_rows_columns_and_bytes_and_forbids_retry():
    """An agent that retries an oversized answer produces the same oversized
    answer. The refusal has to carry both the cause and the remedy — the same
    text discipline the source gate already ships."""
    src = _source()
    assert "RESULT_TOO_LARGE" in src
    assert "Do NOT retry" in src
    assert "narrow it first" in src
    for number in ("result_df.height", "result_df.width", "n_bytes"):
        assert number in src, f"the refusal must name {number}"


def test_the_remedy_names_the_AGGREGATE_escape_not_just_fewer_columns():
    """The failing shape is ARRAY_AGG, and 'select fewer columns' does not fix
    it — the fix is counting instead of listing. A remedy that does not apply to
    the failure that motivated the gate teaches the agent nothing."""
    src = _source()
    assert "COUNT(DISTINCT" in src and "ARRAY_AGG" in src


def test_the_gate_REFUSES_rather_than_TRUNCATING():
    """A truncated aggregate reads as complete. If truncation is ever wanted it
    is opt-in per call with the marker riding IN the payload."""
    joined = "\n".join(_code())
    assert "RESULT_TOO_LARGE" in joined, (
        "the refusal text must be in CODE, not only in commentary"
    )
    guard_at = joined.index("if n_bytes > _MAX_RESULT_BYTES:")
    body = joined[guard_at:guard_at + 400]
    assert "raise ValueError(" in body, (
        f"the oversized path must raise, not return a shortened payload: {body[:200]}"
    )
    assert "payload[:" not in joined, "the payload is being silently sliced"


def test_the_guard_does_not_PAY_for_what_it_refuses():
    """THE GUARD'S OWN COST ARM. Serialising first means a 2Gi container
    allocates the whole oversized payload in order to discover it is oversized —
    the guard reinstating the failure it exists to prevent. Measured on the real
    sandbox p_cage: `write_json` 5.5s and a 251 MB string, `estimated_size` 45ms
    and frame metadata."""
    joined = "\n".join(_code())
    pre_at = joined.index("est_bytes = result_df.estimated_size()")
    ser_at = joined.index("payload = result_df.write_json()")
    assert pre_at < ser_at, "the cheap check must run before the expensive one"
    assert "raise ValueError(" in joined[pre_at:ser_at], (
        "the pre-check must be able to REFUSE on its own — otherwise it is a "
        "measurement taken and thrown away, and the serialisation is still paid"
    )


def test_BOTH_checks_are_load_bearing_and_neither_subsumes_the_other():
    """THE TWO-TIER ARM, executed. The pre-check is conservative BY
    CONSTRUCTION, so a borderline result slips past it and is caught only by the
    exact one. Deleting either leaves a real hole:

      * drop the exact check  -> this fixture (202,000 packed / 323,701 JSON)
        passes the gate and enters the prompt over budget
      * drop the pre-check    -> the 251 MB p_cage payload is built in full
        before anyone is allowed to say no
    """
    _, res = _aggregate(n_groups=100, per_group=400)
    est = res.estimated_size()
    n_bytes = len(res.write_json().encode("utf-8"))

    assert est <= 256_000, (
        f"fixture must sit UNDER the pre-check for this arm to mean anything "
        f"(est={est:,})"
    )
    assert n_bytes > 256_000, (
        f"...and OVER the exact one, so only the exact check catches it "
        f"(json={n_bytes:,})"
    )


def test_the_pre_check_is_NOT_a_json_size_estimator():
    """The code refuses to rely on a json/est ratio. This is why: it moves by
    2.5x across ordinary shapes, so any multiplier picked here would be a guess
    dressed as a measurement."""
    ratios = {}
    for name, df in {
        "small_int": pl.DataFrame({"a": list(range(1_000))}),
        "large_int": pl.DataFrame({"a": [10 ** 17 + i for i in range(1_000)]}),
        "text_lists": pl.DataFrame({
            "company": [f"COMPANY_{i:03d}" for i in range(20)],
            "codes": [[f"{j:05X}" for j in range(200)] for _ in range(20)],
        }),
    }.items():
        ratios[name] = len(df.write_json().encode("utf-8")) / df.estimated_size()

    spread = max(ratios.values()) / min(ratios.values())
    assert spread > 2.0, (
        f"if the ratio were stable a multiplier would be defensible; it is not: "
        f"{ {k: round(v, 2) for k, v in ratios.items()} }"
    )


# -- LAYER 1: the measurement itself, executed ------------------------------

def _aggregate(n_groups: int, per_group: int):
    """The exact shape that failed at work, at test scale."""
    duckdb = pytest.importorskip("duckdb")
    rows = n_groups * per_group
    src = pl.DataFrame({
        "company": [f"COMPANY_{i % n_groups:04d}" for i in range(rows)],
        "cage_code": [f"{i:05X}" for i in range(rows)],
    }).lazy()
    con = duckdb.connect()
    try:
        con.register("dataset", src)
        res = con.execute(
            "SELECT company, ARRAY_AGG(DISTINCT cage_code) AS codes "
            "FROM dataset GROUP BY company"
        ).pl()
    finally:
        con.close()
    n_rows = int(src.select(pl.len()).collect().item())
    n_cols = len(src.collect_schema().names())
    return (n_rows * n_cols, res)


def test_the_cell_gates_BOTH_pass_while_the_payload_is_enormous():
    """THE DIMENSION-NOBODY-MEASURES ARM, and the reason this file exists.

    Source passes the shipped 40M-cell gate. Result passes it by orders of
    magnitude. The payload is still far over any sane prompt budget.
    """
    source_cells, res = _aggregate(n_groups=100, per_group=400)
    result_cells = res.height * res.width
    n_bytes = len(res.write_json().encode("utf-8"))

    assert source_cells < 40_000_000, "fixture must PASS the source gate"
    assert result_cells < 40_000_000, "fixture must PASS a cell gate on the result"
    assert result_cells < 1_000, "the row count collapses under the GROUP BY..."
    assert n_bytes > 256_000, "...while the data volume does not"


def test_CELLS_and_BYTES_order_two_results_OPPOSITELY():
    """The claim that the units do not convert, executed. Frame A has far more
    cells than frame B and a fraction of the bytes. Any single-unit gate ranks
    these two backwards for the other unit's purpose."""
    a = pl.DataFrame({f"c{c}": list(range(1, 2001)) for c in range(10)})
    b = pl.DataFrame({
        "company": [f"COMPANY_{i:03d}" for i in range(20)],
        "codes": [[f"{j:05X}" for j in range(5_000)] for _ in range(20)],
    })
    a_cells, b_cells = a.height * a.width, b.height * b.width
    a_bytes = len(a.write_json().encode("utf-8"))
    b_bytes = len(b.write_json().encode("utf-8"))

    assert a_cells > b_cells, (a_cells, b_cells)
    assert a_bytes < b_bytes, (a_bytes, b_bytes)   # <- the orderings invert


def test_an_ordinary_result_is_NOT_refused():
    """The gate must not fail the questions the engine exists to answer."""
    _, res = _aggregate(n_groups=5, per_group=10)
    assert len(res.write_json().encode("utf-8")) < 256_000


@pytest.mark.parametrize("n_bytes,limit,refused", [
    (1_024, 256_000, False),
    (256_000, 256_000, False),      # exactly at the limit: allowed
    (256_001, 256_000, True),       # one byte over: refused
    (4_007_401, 256_000, True),     # the measured publog-shape payload
])
def test_the_byte_arithmetic(n_bytes, limit, refused):
    assert (n_bytes > limit) is refused


# -- LAYER 2: the step bound -----------------------------------------------

def test_the_agent_step_has_a_wall_clock_bound():
    src = _source()
    assert "_AGENT_TIMEOUT_S" in src
    assert "DA_AGENT_TIMEOUT_S" in src
    assert "asyncio.wait_for(" in "\n".join(_code()), (
        "agent.run is unbounded — a 12-minute question returns an empty card "
        "while it is still running"
    )


def test_a_timeout_returns_DATA_and_is_never_re_raised():
    """An agent failure is a RESULT of this engine, not an infrastructure fault.
    Re-raising makes Restate retry the whole LLM loop for a deterministic
    failure — burning the run again to reach the same answer."""
    src = _source()
    assert '"reason": "agent_timeout"' in src
    # THE ARM ITSELF, not a fixed-size window after it: a character budget runs
    # into the NEXT handler, whose commentary argues about "re-raising" — and a
    # substring search cannot tell that prose from a `raise` statement.
    arm = src.split("except (asyncio.TimeoutError, TimeoutError)")[1]
    arm = arm.split("except Exception as e:")[0]
    statements = [ln.strip() for ln in arm.splitlines()
                  if not ln.lstrip().startswith("#")]
    assert any(ln.startswith("return {") for ln in statements)
    assert not [ln for ln in statements if ln.startswith("raise")], (
        "a timeout must be returned as DATA — re-raising makes Restate retry "
        "the whole LLM loop for a deterministic failure"
    )


def test_the_timeout_arm_precedes_the_broad_except():
    """Since 3.11 `asyncio.TimeoutError` IS the builtin `TimeoutError`, an
    OSError subclass — so a later broad `except Exception` would swallow it and
    label a timeout as an indistinguishable crash."""
    src = _source()
    assert (src.index("except (asyncio.TimeoutError, TimeoutError)")
            < src.index("except Exception as e:  # noqa: BLE001"))


def test_a_timeout_is_COUNTED_distinctly_in_the_metric():
    """`raised` and `timeout` have different remedies; averaging them into one
    fumble rate makes the metric unable to tell them apart."""
    assert '_emit_fumble_metric("timeout")' in _source()


def test_wait_for_bounds_the_AWAIT_and_NOT_the_thread():
    """THE HONEST-LIMIT ARM, executed rather than promised in a comment.

    Python cannot kill a running thread, so `agent.run` keeps burning its worker
    after the timeout fires. What the bound buys is a bounded RESPONSE, not
    bounded WORK — and a future reader who assumes otherwise finds out here
    rather than from a cost report.
    """
    started, finished = threading.Event(), threading.Event()

    def slow():
        started.set()
        time.sleep(1.5)
        finished.set()
        return "too late"

    async def drive():
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(asyncio.to_thread(slow), timeout=0.2)
        # SAMPLED HERE, at the moment the timeout fires, because that is the
        # claim. Sampling after `asyncio.run` returns would measure something
        # else entirely: loop shutdown JOINS the default executor, so the thread
        # is always finished by then and the assertion would read as a refutation
        # of a claim it never tested. Engine DA's loop is long-lived (hypercorn),
        # so nothing joins the orphan there — it simply runs on.
        return finished.is_set()

    finished_at_timeout = asyncio.run(drive())

    assert started.is_set()
    assert not finished_at_timeout, (
        "the await returned while the worker was still running — this is the "
        "bound being on the RESPONSE, not on the work"
    )
    assert finished.is_set(), (
        "the worker thread SURVIVED the timeout and ran to completion; "
        "`agent.run` keeps burning its worker after the caller has given up"
    )
