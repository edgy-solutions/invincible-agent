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
    lot         INTEGER PRIMARY KEY,
    quantity    INTEGER      NOT NULL,
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

    lot_rows, result_rows, rate_rows = [], [], []
    seen_rates: set[tuple[str, int, str]] = set()

    for n in lots:
        lot = state.lot(n)
        vintage = state.vintages(lot.fiscal_year)[0]
        rates = state.rates[(lot.fiscal_year, vintage)]
        lot_rows.append((n, lot.quantity, lot.fiscal_year, False))

        # Labour, by KIND -- the Labor tab's sub_config axis.
        for line in lot.labor:
            result_rows.append((n, "labor", line.kind, str(lot.fiscal_year),
                                line.hours, line.cost))
        for cat, price, hours in (
            ("material", lot.material, None),
            ("other_direct", lot.other_direct, None),
            ("warranty", lot.warranty, lot.warranty_hours),
            ("contracts", lot.contracts, None),
        ):
            result_rows.append((n, cat, None, str(lot.fiscal_year), hours, price))

        # The composed price and its steps -- stored as RESULTS, computed by pricing.py.
        build_up = compose_price(
            direct_labor=lot.direct_labor, material=lot.material,
            other_direct=lot.other_direct + lot.warranty + lot.contracts, rates=rates)
        for s in build_up.steps:
            result_rows.append((n, "composition", s.name, str(lot.fiscal_year), None, s.amount))
        result_rows.append((n, "price", None, str(lot.fiscal_year), None, build_up.price))
        result_rows.append((n, "unit_price", None, str(lot.fiscal_year), None,
                            unit_price(build_up, lot.quantity)))

        for field in ("fringe", "overhead", "g_and_a", "cost_of_money", "profit", "escalation"):
            key = (vintage, lot.fiscal_year, field)
            if key not in seen_rates:
                seen_rates.add(key)
                rate_rows.append((vintage, lot.fiscal_year, field,
                                  Decimal(str(getattr(rates, field)))))

    con.executemany("INSERT INTO lots VALUES (?,?,?,?)", lot_rows)
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
