"""THE SHARED DATASET-CONTRACT READER (ADR-0066, provisional; ruled 2026-11-11). A dataset CONTRACT
is data: what an asset must carry for a governed read to accept it. A dataset measure row names its
contract (`inputs.dataset.contract`), the loader joins the two at load, and the engine enforces the
contract on every read of the row's asset. Engine-fin reads this module, and the next engine will
too. No engine keeps a copy: `tests/test_one_dataset_contract_reader.py` seals that.

THE CONTRACT DECLARES, THE READER ENFORCES. Which columns are required, each column's type, the key
(`grain`) and the dependencies (`dependencies`: each value of `by` carries one value of each
`determines` column) are the contract's; the reader holds the generic rules that enforce them and
names no column of any contract. Ruled 2026-11-10.

ONE FILE PER CONTRACT, READ BY NAME. `<contract dir>/<contract_id>.yaml` is read when a row names it,
and no other file is: a contract another engine reads in another shape is never parsed here.

WHAT LIVES HERE: loading and validating a contract; the read-time checks (`missing_column`,
`wrong_type`, `duplicate_key`, `not_determined_by`), which raise `ContractViolation`; and the generic
load-time hold of a row's named columns (declared, and of a type in the role's set: `undeclared`,
`not_of`).

WHAT DOES NOT LIVE HERE: a row's ROLES (level, scope, period, status; "a series row's status is
determined by the scope"). They are each engine's, e.g. `finance_agent/measure_verbs._join_contract`.

In the image this file is `/app/utils/dataset_contracts.py` (`COPY agent_fleet/utils/ /app/utils/`),
and `_default_dir`'s walk-up reaches `/app/contracts`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: The column types a contract may declare, as the reader checks them on a polars dtype.
TYPES = frozenset({"string", "numeric", "integer"})
_DIR_ENV = "DATASET_CONTRACT_DIR"


def _default_dir() -> Path:
    """`<repo>/contracts`, found by walking up (the image puts this file at `/app/utils/`)."""
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "contracts"
        if candidate.is_dir():
            return candidate
    return Path("/app/contracts")


def contract_dir() -> Path:
    """Read from the environment at CALL time, as `measure_verbs` reads its directories."""
    return Path(os.getenv(_DIR_ENV) or str(_default_dir()))


@dataclass(frozen=True)
class DatasetContract:
    contract_id: str
    types: dict[str, str]                                    # column -> string | numeric | integer
    required: tuple[str, ...]
    key: tuple[str, ...]                                     # `grain`: one row per tuple
    scope: str                                               # the column a read filters on
    dependencies: tuple[tuple[str, tuple[str, ...]], ...]    # (by, the columns it determines)

    def determined_by(self, column: str) -> frozenset[str]:
        """The columns `column` is declared determined by."""
        return frozenset(by for by, cols in self.dependencies if column in cols)


def load_contract(contract_id: str, directory: Path | None = None) -> DatasetContract:
    """The contract `contract_id`, validated. ValueError names what is wrong, and the file."""
    if not isinstance(contract_id, str) or not contract_id.strip() or "/" in contract_id or "\\" in contract_id:
        raise ValueError(f"contract {contract_id!r} must be a contract id, not a path")
    path = (directory or contract_dir()) / f"{contract_id}.yaml"
    if not path.is_file():
        raise ValueError(f"contract {contract_id!r} has no file {path.name} in {path.parent}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return _parse(raw, contract_id)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"{path.name} is not a dataset contract: {type(exc).__name__} {exc}") from None
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from None


def _parse(raw: dict, contract_id: str) -> DatasetContract:
    if raw["contract_id"] != contract_id:
        raise ValueError(f"declares contract_id {raw['contract_id']!r}, not {contract_id!r}")
    types: dict[str, str] = {}
    required = []
    for col in raw["columns"]:
        name, kind = col["name"], col["type"]
        if kind not in TYPES:
            raise ValueError(f"column {name!r} has type {kind!r}; a contract declares one of {sorted(TYPES)}")
        if name in types:
            raise ValueError(f"column {name!r} is declared twice")
        types[name] = kind
        if col["required"]:
            required.append(name)
    key, scope = tuple(raw["grain"]), raw["scope"]
    dependencies = tuple((d["by"], tuple(d["determines"])) for d in raw.get("dependencies") or ())
    named = {*key, scope, *(c for by, cols in dependencies for c in (by, *cols))}
    undeclared = sorted(named - set(types))
    if undeclared:
        raise ValueError(f"grain, scope or dependencies name {undeclared}, which no column declares")
    for by, cols in dependencies:
        if not cols or by in cols:
            raise ValueError(f"the dependency on {by!r} must determine at least one column other than itself")
    # A check over a column the asset may lack would pass by skipping, so what the checks key on is required.
    optional = sorted({*key, scope, *(by for by, _ in dependencies)} - set(required))
    if optional:
        raise ValueError(f"grain, scope and every dependency's `by` must be required columns; {optional} are not")
    return DatasetContract(contract_id=contract_id, types=types, required=tuple(required),
                           key=key, scope=scope, dependencies=dependencies)


class ContractViolation(Exception):
    """The asset's rows break the column contract. Carries the rule, never a row's value."""

    def __init__(self, rule: str, message: str):
        super().__init__(message)
        self.rule = rule
        self.message = message


def _is_type(dtype: Any, kind: str) -> bool:
    import polars as pl

    if kind == "string":
        return dtype == pl.String
    return dtype.is_integer() if kind == "integer" else dtype.is_numeric()


def check_contract_schema(schema: Any, contract: Any, named: tuple[str, ...]) -> list[str]:
    """The columns a read selects: every column the contract declares that the asset carries.

    Every required column, and every column the row `named`, must be present (`missing_column`),
    and every selected column must be of its declared type (`wrong_type`), whether or not the row
    reads it: the key and the dependencies are checked over columns the row may never name."""
    missing = [c for c in dict.fromkeys((*contract.required, *named)) if c not in schema]
    if missing:
        raise ContractViolation("missing_column", "missing column(s): " + ", ".join(missing))
    selected = [c for c in contract.types if c in schema]
    bad = [c for c in selected if not _is_type(schema[c], contract.types[c])]
    if bad:
        raise ContractViolation("wrong_type", "column(s) of the wrong type: " + ", ".join(bad))
    return selected


def check_contract_rows(df: Any, contract: Any) -> None:
    """The key and the dependencies, over one program's collected rows. A message names the
    columns, never a value."""
    import polars as pl

    if df.select(list(contract.key)).is_duplicated().any():
        raise ContractViolation("duplicate_key", f"more than one row for one ({', '.join(contract.key)})")
    for by, determined in contract.dependencies:
        present = [c for c in determined if c in df.columns]
        if not present:
            continue
        counts = df.group_by(by).agg(pl.col(c).n_unique() for c in present)
        for c in present:
            if (counts[c] > 1).any():
                raise ContractViolation("not_determined_by",
                                        f"{c} is not determined by {by}: one {by} carries more than one {c}")


#: The declared types a value (numeric) role accepts. A string role accepts "string" only.
NUMBER_TYPES = frozenset({"numeric", "integer"})


def undeclared(contract: DatasetContract, columns) -> list[str]:
    """The columns of `columns` the contract does not declare, sorted."""
    return sorted(c for c in columns if c not in contract.types)


def not_of(contract: DatasetContract, columns, kinds) -> list[str]:
    """The declared columns of `columns` whose declared type is not one of `kinds`, sorted."""
    return sorted(c for c in columns if c in contract.types and contract.types[c] not in kinds)
