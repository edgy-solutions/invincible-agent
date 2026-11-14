"""A dataset CONTRACT as data (ADR-0066, provisional): what an asset must carry for a governed read to
accept it. A dataset measure row names its contract (`inputs.dataset.contract`), the loader joins the
two at load, and `asset_inputs` enforces the contract on every read of the row's asset.

THE CONTRACT DECLARES, THE READER ENFORCES. Which columns are required, each column's type, the key
(`grain`) and the dependencies (`dependencies`: each value of `by` carries one value of each
`determines` column) are the contract's; the reader holds the generic rules that enforce them and
names no column of any contract. Ruled 2026-11-10.

ONE FILE PER CONTRACT, READ BY NAME. `<contract dir>/<contract_id>.yaml` is read when a row names it,
and no other file is: a contract another engine reads in another shape is never parsed here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

#: The column types a contract may declare, as the reader checks them on a polars dtype.
TYPES = frozenset({"string", "numeric", "integer"})
_DIR_ENV = "DATASET_CONTRACT_DIR"


def _default_dir() -> Path:
    """`<repo>/contracts`, found by walking up (the flattened image puts this file at `/app/`)."""
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
