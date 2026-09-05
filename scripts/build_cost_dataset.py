"""Build the slice-2 data package: one .duckdb file, typed, hashed into the manifest.

THREE TABLES, and the shapes are the dispatch's:

  lots     (lot, quantity, fiscal_year, estimating)      one row per lot
  results  (lot, category, sub_config, period, hours, price)
  rates    (vintage, fiscal_year, category, rate)

DATA LAYER ONLY. NO ARITHMETIC IN SQL. Every figure in `results` is one the engine already
computed with `pricing.py`; the database stores and selects, it does not derive. That line is
the reason the export's equivalence claim survives adding a database at all: if SQL computed
anything, the recipient would be verifying DuckDB's arithmetic rather than ours, and a
divergence could no longer mean "data or runtime, never algorithm".

DECIMAL, NOT DOUBLE, AND MEASURED BEFORE BEING RELIED ON. A round-trip probe over 63 real
engine figures: DECIMAL(20,2) returns Python `Decimal` and is string-equal 63/63; the same
values through a DOUBLE column are string-equal 51/63. The leak is real, it is what this
column type avoids, and the probe discriminates rather than passing vacuously.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_fleet.cost_agent.pricing import compose_price, unit_price   # noqa: E402
from agent_fleet.cost_agent.seed import build_state, lots_for_recipient  # noqa: E402

DDL = """
CREATE TABLE lots (
    lot              INTEGER PRIMARY KEY,
    quantity         INTEGER NOT NULL,
    cumulative_units INTEGER NOT NULL,
    fiscal_year INTEGER      NOT NULL,
    estimating  BOOLEAN      NOT NULL
);
CREATE TABLE results (
    lot        INTEGER       NOT NULL,
    category   VARCHAR       NOT NULL,
    sub_config VARCHAR,
    period     VARCHAR,
    hours      DECIMAL(20,2),
    price      DECIMAL(20,2) NOT NULL
);
CREATE TABLE rates (
    vintage     VARCHAR       NOT NULL,
    fiscal_year INTEGER       NOT NULL,
    category    VARCHAR       NOT NULL,
    rate        DECIMAL(12,6) NOT NULL
);
"""


def file_hash(p: pathlib.Path) -> str:
    """The dataset's identity, hashed alongside the modules in the manifest.

    A package pins its ALGORITHM by commit SHA and its DATA by this hash. Without the second,
    a recipient could be handed the same code over different rows and the manifest would have
    nothing to say about it.
    """
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def build(recipient: str, out: pathlib.Path) -> pathlib.Path:
    import duckdb

    state = build_state()
    lots = lots_for_recipient(recipient)      # ENTITLEMENT FILTER, at packaging time

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = duckdb.connect(str(out))
    con.execute(DDL)

    # ONE GENERATOR, TWO CONTAINERS. The rows come from export.dataset_rows so the database
    # and the embedded page cannot hold different tables — they drifted on the first run when
    # each had its own builder (75 rows against 35), which is precisely the defect the
    # agreement check exists to catch and precisely the reason not to have two builders.
    from decimal import Decimal as _D
    from agent_fleet.cost_agent.export import dataset_rows

    rows = dataset_rows(state, lots=tuple(lots))
    lot_rows = [(r["lot"], r["quantity"], r["cumulative_units"], r["fiscal_year"],
                 r["estimating"]) for r in rows["lots"]]
    result_rows = [(r["lot"], r["category"], r["sub_config"], r["period"],
                    None if r["hours"] is None else _D(r["hours"]), _D(r["price"]))
                   for r in rows["results"]]
    rate_rows = [(r["vintage"], r["fiscal_year"], r["category"], _D(r["rate"]))
                 for r in rows["rates"]]

    con.executemany("INSERT INTO lots VALUES (?,?,?,?,?)", lot_rows)
    con.executemany("INSERT INTO results VALUES (?,?,?,?,?,?)", result_rows)
    con.executemany("INSERT INTO rates VALUES (?,?,?,?)", rate_rows)
    con.close()

    print(f"  lots={len(lot_rows)}  results={len(result_rows)}  rates={len(rate_rows)}")
    print(f"  {out}  ({out.stat().st_size/1024:.0f} KB)  {file_hash(out)[:26]}...")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recipient", required=True)
    ap.add_argument("--out", default="dist/cost.duckdb")
    a = ap.parse_args()
    build(a.recipient, pathlib.Path(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
