"""THE SHARED DATASET-CONTRACT READER (ADR-0066, provisional; ruled 2026-11-11). A dataset CONTRACT
is data: what an asset must carry for a governed read to accept it. A dataset measure row names its
contract (`inputs.dataset.contract`), the loader joins the two at load, and the engine enforces the
contract on every read of the row's asset. Engine-fin reads this module, and the next engine will
too. No engine keeps a copy: `tests/test_one_dataset_contract_reader.py` seals that.

THE CONTRACT DECLARES, THE READER ENFORCES. Which columns are required, each column's type, the key
(`grain`) and the dependencies (`dependencies`: each value of `by` carries one value of each
`determines` column) are the contract's; the reader holds the generic rules that enforce them and
names no column of any contract. Ruled 2026-11-10.

ONE FILE PER CONTRACT SET, READ BY NAME. A contract `<set>` lives in `<set>.yaml` as its only
document. A contract `<set>.<table>` lives in `<set>.yaml` among the set's documents, the
multi-document form dag-tools' template is written in. `<contract dir>/<set>.yaml` is read when a
row names a contract of the set, and no other file is: a contract another engine reads in another
shape is never parsed here. `load_contracts` is THE parser, the template check's and the engine's.

SCOPE. The scope is the column a read filters to one value of, and which values a caller may read
is the deployment's mapping, a row, never this module's. Every contract declares its scope column,
or `scope: none`, which declares there is none. Under `scope: none` no value filter applies, and
the read is decided on the asset grant alone. An engine whose reads need a scope refuses such a
contract at its join, as engine-fin does.

RULES. Refusal rules live here, once (`RULES`), and apply to every contract. A contract's `rules`
block carries messages for them (and for an engine's own rules); leaving a rule out of it disables
nothing. Naming a rule nobody raises is refused at the engine's join (`unknown_rules`), because a
rule that nothing raises would read as enforced. The one exception is `PRODUCER_CHECKED`: rules the
producer checks before it publishes. A block may name them, and no reader raises them.

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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: The column types a contract may declare, as the reader checks them on a polars dtype.
#: `array<string>` is ONE token: there is no general `array<T>`.
TYPES = frozenset({"string", "numeric", "integer", "float", "boolean", "timestamp", "date",
                   "array<string>"})
_DIR_ENV = "DATASET_CONTRACT_DIR"
_ID = re.compile(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)?")

#: The refusal rules the shared reader raises, each id -> what it refuses on. They apply to every
#: contract, named in its `rules` block or not (ruled 2026-11-14).
RULES = {
    "missing_column": "a required column, or a column the reading row names, is absent",
    "wrong_type": "a column is not of the type the contract declares",
    "duplicate_key": "more than one row for one grain tuple",
    "not_determined_by": "one value of a dependency's `by` column carries two values of a column "
                         "it determines",
}
#: Rules the PRODUCER checks before it publishes (ruled 2026-11-14). A contract's block may name
#: them, and carry their messages; no reader raises them, and a seal holds that it never does.
PRODUCER_CHECKED = frozenset({"interval_overlap", "orphan_reference"})


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
    types: dict[str, str]                                    # column -> one of TYPES
    required: tuple[str, ...]
    key: tuple[str, ...]                                     # `grain`: one row per tuple
    scope: str | None                                        # a read filters on it; None: `scope: none`
    dependencies: tuple[tuple[str, tuple[str, ...]], ...]    # (by, the columns it determines)
    rules: dict[str, str] = field(default_factory=dict)      # rule id -> the contract's message for it

    @property
    def scoped(self) -> bool:
        return self.scope is not None

    def determined_by(self, column: str) -> frozenset[str]:
        """The columns `column` is declared determined by."""
        return frozenset(by for by, cols in self.dependencies if column in cols)


def unknown_rules(contract: DatasetContract, also=()) -> list[str]:
    """The rule ids the contract's `rules` block names that neither this reader nor `also` (the
    ids the reading engine raises itself) raises, and the producer does not check
    (`PRODUCER_CHECKED`), sorted. A contract carries messages for rules; it cannot add one, so an
    engine refuses a contract this is not empty for at its join."""
    return sorted(set(contract.rules) - set(RULES) - PRODUCER_CHECKED - set(also))


def load_contracts(path: Path) -> dict[str, DatasetContract]:
    """Every contract in the file `path`, in document order, each validated. THE parser: a file is
    one set, so one bad document refuses the whole file. ValueError names what is wrong, and the file."""
    stem = path.stem
    docs = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d is not None]
    if not docs:
        raise ValueError(f"{path.name} holds no contract")
    multi = len(docs) > 1
    out: dict[str, DatasetContract] = {}
    for raw in docs:
        cid = raw.get("contract_id") if isinstance(raw, dict) else None
        label = f"{cid}: " if multi and isinstance(cid, str) else ""
        try:
            belongs = cid == stem or (isinstance(cid, str) and cid.startswith(f"{stem}.")
                                      and _ID.fullmatch(cid) is not None)
            if not belongs:
                raise ValueError(f"declares contract_id {cid!r}, which is not {stem!r} or {stem!r}.<name>")
            if cid in out:
                raise ValueError(f"declares contract_id {cid!r} twice")
            if multi and cid == stem:
                raise ValueError(f"declares the bare contract_id {cid!r} in a file of several contracts")
            out[cid] = _parse(raw)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(
                f"{path.name} is not a dataset contract: {label}{type(exc).__name__} {exc}") from None
        except ValueError as exc:
            raise ValueError(f"{path.name}: {label}{exc}") from None
    return out


def load_contract(contract_id: str, directory: Path | None = None) -> DatasetContract:
    """The contract `contract_id`, validated. ValueError names what is wrong, and the file."""
    if not isinstance(contract_id, str) or not _ID.fullmatch(contract_id):
        raise ValueError(f"contract {contract_id!r} must be a contract id, not a path")
    path = (directory or contract_dir()) / f"{contract_id.split('.')[0]}.yaml"
    if not path.is_file():
        raise ValueError(f"contract {contract_id!r} has no file {path.name} in {path.parent}")
    contracts = load_contracts(path)
    if contract_id not in contracts:
        if len(contracts) == 1:
            (only,) = contracts
            raise ValueError(f"{path.name}: declares contract_id {only!r}, not {contract_id!r}")
        raise ValueError(f"{path.name} holds no contract {contract_id!r}; it holds {sorted(contracts)}")
    return contracts[contract_id]


def _parse(raw: dict) -> DatasetContract:
    contract_id = raw["contract_id"]
    types: dict[str, str] = {}
    required = []
    for col in raw["columns"]:
        name, kind = col["name"], col["type"]
        if kind not in TYPES:
            raise ValueError(f"column {name!r} has type {kind!r}; a contract declares one of {sorted(TYPES)}")
        if name in types:
            raise ValueError(f"column {name!r} is declared twice")
        types[name] = kind
        req = col.get("required", False)
        if not isinstance(req, bool):
            raise ValueError(f"column {name!r} has required {req!r}; it is true or false")
        if req:
            required.append(name)
    key, scope = tuple(raw["grain"]), raw.get("scope")
    if scope is None:
        raise ValueError("declares no scope: a contract names its scope column, "
                         "or `none` when it has none")
    if scope == "none":
        if "none" in types:
            raise ValueError("declares `scope: none` and a column named `none`: "
                             "which is meant is ambiguous")
        scope = None
    scoped = () if scope is None else (scope,)
    dependencies = tuple((d["by"], tuple(d["determines"])) for d in raw.get("dependencies") or ())
    named = {*key, *scoped, *(c for by, cols in dependencies for c in (by, *cols))}
    undeclared = sorted(named - set(types))
    if undeclared:
        raise ValueError(f"grain, scope or dependencies name {undeclared}, which no column declares")
    for by, cols in dependencies:
        if not cols or by in cols:
            raise ValueError(f"the dependency on {by!r} must determine at least one column other than itself")
    # A check over a column the asset may lack would pass by skipping, so what the checks key on is required.
    optional = sorted({*key, *scoped, *(by for by, _ in dependencies)} - set(required))
    if optional:
        raise ValueError(f"grain, scope and every dependency's `by` must be required columns; {optional} are not")
    rules = raw.get("rules")
    if rules is None:
        rules = {}
    if not isinstance(rules, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v for k, v in rules.items()):
        raise ValueError(f"rules maps a rule id to its message; {rules!r} is not")
    return DatasetContract(contract_id=contract_id, types=types, required=tuple(required),
                           key=key, scope=scope, dependencies=dependencies, rules=dict(rules))


class ContractViolation(Exception):
    """The asset's rows break the column contract. Carries the rule, never a row's value."""

    def __init__(self, rule: str, message: str):
        super().__init__(message)
        self.rule = rule
        self.message = message


def _type_checks():
    import polars as pl

    return {
        "string": lambda d: d == pl.String,
        "numeric": lambda d: d.is_numeric(),
        "integer": lambda d: d.is_integer(),
        "float": lambda d: d.is_float(),
        "boolean": lambda d: d == pl.Boolean,
        "date": lambda d: d == pl.Date,
        # an instant, always UTC: a naive datetime is the wrong type, never assumed to be UTC
        "timestamp": lambda d: isinstance(d, pl.Datetime) and d.time_zone in ("UTC", "Etc/UTC"),
        "array<string>": lambda d: isinstance(d, (pl.List, pl.Array)) and d.inner == pl.String,
    }


def _is_type(dtype: Any, kind: str) -> bool:
    return _type_checks()[kind](dtype)


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
    """The key and the dependencies, over the rows of one read: one scope value's rows, or the whole
    asset under `scope: none`. A message names the columns, never a value."""
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
NUMBER_TYPES = frozenset({"numeric", "integer", "float"})


def undeclared(contract: DatasetContract, columns) -> list[str]:
    """The columns of `columns` the contract does not declare, sorted."""
    return sorted(c for c in columns if c not in contract.types)


def not_of(contract: DatasetContract, columns, kinds) -> list[str]:
    """The declared columns of `columns` whose declared type is not one of `kinds`, sorted."""
    return sorted(c for c in columns if c in contract.types and contract.types[c] not in kinds)
