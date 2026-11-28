"""THE SHARED DATASET-CONTRACT READER (ADR-0066, provisional; ruled 2026-11-11). A dataset CONTRACT
is data: what an asset must carry for a governed read to accept it. A dataset measure row names its
contract (`inputs.dataset.contract`), the loader joins the two at load, and the engine enforces the
contract on every read of the row's asset. Engine-fin reads this module, and the next engine will
too. No engine keeps a copy: `tests/test_one_dataset_contract_reader.py` seals that.

THE CONTRACT DECLARES, THE READER ENFORCES. Which columns are required, each column's type, each
column's nullability (`nullable: false`), the key (`grain`) and the dependencies (`dependencies`:
each value of `by` carries one value of each `determines` column) are the contract's; the reader
holds the generic rules that enforce them and names no column of any contract. Ruled 2026-11-10;
nullability 2026-11-16.

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

PERIOD CALENDAR. `period.calendar` (optional) names the declared period calendar the dataset's
period values are drawn from. The reader resolves it, not this module.

STATUS PERIOD. `status_period` (optional, top level) names the column that carries the period the
scope's data is reported through. It must be a declared string column, `nullable: false`, and
declared determined by the scope (a dependency on the scope determines it), so a scope's rows
carry one value of it; `scope: none` refuses it. The reader holds the shape only: what the value
marks is the engine's.

HIERARCHY. `hierarchy` (optional, top level) names the breakdown's level columns, top first, below
the scope: a list of at least two distinct string columns, each `nullable: false`, none the scope or
personal data, and the LAST declared to determine every other. Nothing more is enforced: a middle
level's name may repeat under different parents (a work package still has one path). The reader
holds the shape only. What each level IS (the roles) is the engine's.

VERSION DIMENSION. `version_dimension` (optional) declares `{column, values}`: the versions
(baselines, estimates) the dataset's rows carry in `column`, in declared order; the column must be in grain. It is NOT the
top-level `version`, which is the contract's own revision and is not read here. The values are
strings, ever: an identifier of this kind is never read as a number. A reader refuses a row whose
version is not in the list (`version_outside_list`), and a row compares or filters on versions
only as this list names them.

PERSONAL DATA. A column marked `personal_data: true` records a FACT about the column; the
classification level and who may see it are the deployment's, applied through its dimensions
(gov's rail), never written in a contract. This reader holds the fact: a personal column is
withheld from every read unless the reading engine releases it (`released`), so by default
nothing personal is read. Because the broker may project it away for a caller not entitled to
it, nothing every read needs may be one: a personal column is never required, in the grain, the
scope, or a dependency.

RULES. Refusal rules live here, once (`RULES`), and apply to every contract. A contract's `rules`
block carries messages for them (and for an engine's own rules); leaving a rule out of it disables
nothing. Naming a rule nobody raises is refused at the engine's join (`unknown_rules`), because a
rule that nothing raises would read as enforced. The one exception is `PRODUCER_CHECKED`: rules the
producer checks before it publishes. A block may name them, and no reader raises them.

WHAT LIVES HERE: loading and validating a contract; the read-time checks (`missing_column`,
`wrong_type`, `null_value`, `non_finite`, `personal_data`, `duplicate_key`, `not_determined_by`),
which raise `ContractViolation`; and the generic load-time hold of a row's named columns (declared,
of a type in the role's set, declared `nullable: false`: `undeclared`, `not_of`, `nullable`).

WHAT DOES NOT LIVE HERE: a row's ROLES (level, scope, period, status; "a series row's status is
determined by the scope"). They are each engine's, e.g. `finance_agent/measure_verbs._join_contract`.

In the image this file is `/app/utils/dataset_contracts.py` (`COPY agent_fleet/utils/ /app/utils/`),
and `_default_dir`'s walk-up reaches `/app/contracts`.
"""
from __future__ import annotations

import datetime
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
    "personal_data": "a reading row names a personal_data column the reading engine did not release",
    "duplicate_key": "more than one row for one grain tuple",
    "not_determined_by": "one value of a dependency's `by` column carries two values of a column "
                         "it determines",
    "null_value": "a column the contract declares nullable: false carries a null",
    "non_finite": "a column the contract declares numeric or float carries a NaN or an infinity",
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
    non_nullable: tuple[str, ...] = ()                       # the columns declared nullable: false
    personal: frozenset[str] = frozenset()                   # the columns marked personal_data
    calendar: str | None = None                              # `period.calendar`, else None
    version_column: str | None = None                        # `version_dimension.column`, else None
    versions: tuple[str, ...] = ()                           # `version_dimension.values`, in order
    period_column: str | None = None                         # `period.column`, else None
    additive_over: dict[str, tuple[str, ...]] = field(default_factory=dict)  # column -> its `additive_over`
    status_column: str | None = None                         # top-level `status_period`, else None
    hierarchy: tuple[str, ...] = ()                          # top-level `hierarchy`, top first, else ()

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


def withheld(contract: DatasetContract, released=frozenset()) -> list[str]:
    """The personal_data columns a read withholds: every one the reading engine did not release, sorted."""
    return sorted(contract.personal - set(released))


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
    non_nullable = []
    personal = []
    additive: dict[str, tuple[str, ...]] = {}
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
        nullable = col.get("nullable", True)
        if not isinstance(nullable, bool):
            raise ValueError(f"column {name!r} has nullable {nullable!r}; it is true or false")
        if nullable is False:
            non_nullable.append(name)
        pd = col.get("personal_data", False)
        if not isinstance(pd, bool):
            raise ValueError(f"column {name!r} has personal_data {pd!r}; it is true or false")
        if pd:
            personal.append(name)
        over = col.get("additive_over")
        if over is not None:
            if not isinstance(over, list) or not all(isinstance(a, str) for a in over):
                raise ValueError(f"column {name!r} has additive_over {over!r}; it is a list of column names")
            additive[name] = tuple(over)
    for name, over in additive.items():
        undeclared_axes = sorted(a for a in over if a not in types)
        if undeclared_axes:
            raise ValueError(f"column {name!r} is additive over {undeclared_axes}, which no column declares")
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
    # A personal column may be projected away for a caller not entitled to it, so nothing every
    # read needs may be one. Checked first: the remedy is to unmark it, never to make it required.
    bad = sorted(set(personal) & {*required, *named})
    if bad:
        raise ValueError(f"personal_data column(s) {bad} are required, or a grain, scope or dependency "
                         f"column; a personal column is read only by a caller entitled to it, so nothing "
                         f"every read needs may be one")
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
    period = raw.get("period")
    calendar = None
    period_column = None
    if period is not None:
        if not isinstance(period, dict):
            raise ValueError(f"period is a mapping; {period!r} is not")
        if "calendar" in period:
            calendar = period["calendar"]
            if not isinstance(calendar, str) or not calendar.strip():
                raise ValueError(f"period.calendar is a non-empty string; {calendar!r} is not")
        if "column" in period:
            period_column = period["column"]
            if not isinstance(period_column, str) or period_column not in types:
                raise ValueError(f"period.column {period_column!r} is not a declared column")
            if types[period_column] != "string":
                raise ValueError(f"period.column {period_column!r} is declared {types[period_column]!r}; "
                                 f"a period column is a string")
            if period_column not in non_nullable:
                raise ValueError(f"period.column {period_column!r} is nullable; a period column is declared "
                                 f"nullable: false")
    version_column, versions = _parse_version(raw.get("version_dimension"), types, key)
    status_column = _parse_status_period(raw.get("status_period"), types, non_nullable, scope, dependencies)
    hierarchy = _parse_hierarchy(raw.get("hierarchy"), types, non_nullable, scope, set(personal), dependencies)
    return DatasetContract(contract_id=contract_id, types=types, required=tuple(required),
                           key=key, scope=scope, dependencies=dependencies, rules=dict(rules),
                           non_nullable=tuple(non_nullable), personal=frozenset(personal),
                           calendar=calendar, version_column=version_column, versions=versions,
                           period_column=period_column, additive_over=additive,
                           status_column=status_column, hierarchy=hierarchy)


def _determined_by(dependencies: tuple[tuple[str, tuple[str, ...]], ...], column: str) -> frozenset[str]:
    return frozenset(by for by, cols in dependencies if column in cols)


def _parse_status_period(value: Any, types: dict[str, str], non_nullable: list[str], scope: str | None,
                         dependencies: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    """The optional top-level `status_period`: the column naming the period the scope's data is
    reported through, else None. ValueError names the key and the column."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in types:
        raise ValueError(f"status_period {value!r} is not a declared column")
    if types[value] != "string":
        raise ValueError(f"status_period {value!r} is declared {types[value]!r}; a status period column is a string")
    if value not in non_nullable:
        raise ValueError(f"status_period {value!r} is nullable; a status period column is declared nullable: false")
    if scope is None:
        raise ValueError(f"status_period {value!r} is declared under `scope: none`; a status period is "
                         f"one value of a scope, so the contract names its scope")
    if scope not in _determined_by(dependencies, value):
        raise ValueError(f"status_period {value!r} is not declared determined by the scope {scope!r}; "
                         f"a dependency on the scope must determine it")
    return value


def _parse_hierarchy(value: Any, types: dict[str, str], non_nullable: list[str], scope: str | None,
                     personal: set[str],
                     dependencies: tuple[tuple[str, tuple[str, ...]], ...]) -> tuple[str, ...]:
    """The optional top-level `hierarchy`: the breakdown's level columns, top first, below the
    scope; else `()`. ValueError names the key and the column."""
    if value is None:
        return ()
    if (not isinstance(value, list) or len(value) < 2 or not all(isinstance(c, str) for c in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"hierarchy is a list of at least 2 distinct column names; {value!r} is not")
    for col in value:
        if col not in types:
            raise ValueError(f"hierarchy column {col!r} is not a declared column")
        if types[col] != "string":
            raise ValueError(f"hierarchy column {col!r} is declared {types[col]!r}; a level column is a string")
        if col not in non_nullable:
            raise ValueError(f"hierarchy column {col!r} is nullable; a level column is declared nullable: false")
        if col == scope:
            raise ValueError(f"hierarchy column {col!r} is the scope; the levels are below the scope")
        if col in personal:  # cannot fire today: the reader refuses a personal column in a dependency first
            # (test_a_nullable_or_personal_hierarchy_column_is_refused); kept as defence.
            raise ValueError(f"hierarchy column {col!r} is personal data; a level column is never personal")
    last = value[-1]
    undetermined = [c for c in value[:-1] if last not in _determined_by(dependencies, c)]
    if undetermined:
        raise ValueError(f"hierarchy column {last!r} (the last) is not declared to determine {undetermined}; "
                         f"the last level determines every other; a middle level's name may repeat under different parents")
    return tuple(value)


def _parse_version(version: Any, types: dict[str, str], key: Any) -> tuple[str | None, tuple[str, ...]]:
    """`(column, values)` of the optional `version_dimension` block, else `(None, ())`. ValueError."""
    if version is None:
        return None, ()
    if not isinstance(version, dict):
        raise ValueError(f"version_dimension is a mapping of column and values; {version!r} is not")
    unknown = sorted(str(k) for k in set(version) - {"column", "values"})
    if unknown:
        raise ValueError(f"version_dimension carries {unknown}; it holds column and values only")
    column, values = version.get("column"), version.get("values")
    if not isinstance(column, str) or column not in types:
        raise ValueError(f"version_dimension.column {column!r} is not a declared column")
    if types[column] != "string":
        raise ValueError(f"version_dimension.column {column!r} is declared {types[column]!r}; a version column is a string")
    if column not in key:
        raise ValueError(f"version_dimension.column {column!r} is not in grain; each version's rows are one grain "
                         f"apart, so the key holds the version column")
    if not isinstance(values, list) or not values:
        raise ValueError("version_dimension.values is a non-empty list of strings")
    for v in values:
        if isinstance(v, bool):
            raise ValueError(f"version_dimension.values holds the boolean {v!r}; a version is a string, so quote it")
        if isinstance(v, int):
            raise ValueError(f"version_dimension.values holds the number {v!r}; a version is a string, so quote it")
        if isinstance(v, float):
            raise ValueError(f"version_dimension.values holds the float {v!r}; a version is a string, so quote it")
        if isinstance(v, datetime.date):
            raise ValueError(f"version_dimension.values holds the date {v.isoformat()}; a version is a string, so quote it")
        if not isinstance(v, str) or not v.strip():
            raise ValueError("version_dimension.values holds only non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError("version_dimension.values repeats a value")
    return column, tuple(values)


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


def check_contract_schema(schema: Any, contract: Any, named: tuple[str, ...],
                          released=frozenset()) -> list[str]:
    """The columns a read selects: every column the contract declares that the asset carries, less
    the personal_data columns withheld (every one the reading engine did not name in `released`).

    Every required column, and every column the row `named`, must be present (`missing_column`),
    and every declared column the asset carries must be of its declared type (`wrong_type`), whether
    or not the row reads it: the key and the dependencies are checked over columns the row may never
    name. The type check still covers a withheld column (a dtype is schema metadata, not a value). A
    row naming a withheld personal column is refused `personal_data`; a release names only personal
    columns (ValueError), and nothing in this module releases one (ruled 2026-11-14)."""
    released = frozenset(released)
    if released - contract.personal:
        raise ValueError(f"released {sorted(released - contract.personal)} are not personal_data columns "
                         f"of {contract.contract_id!r}")
    hidden = set(withheld(contract, released))
    personal = [c for c in dict.fromkeys(named) if c in hidden]
    if personal:
        raise ContractViolation("personal_data", "the row names personal_data column(s) not released: "
                                + ", ".join(personal))
    missing = [c for c in dict.fromkeys((*contract.required, *named)) if c not in schema]
    if missing:
        raise ContractViolation("missing_column", "missing column(s): " + ", ".join(missing))
    present = [c for c in contract.types if c in schema]
    bad = [c for c in present if not _is_type(schema[c], contract.types[c])]
    if bad:
        raise ContractViolation("wrong_type", "column(s) of the wrong type: " + ", ".join(bad))
    return [c for c in present if c not in hidden]


def check_contract_values(df: Any, contract: Any) -> None:
    """The values of one read's rows: a null in a column declared `nullable: false` is `null_value`;
    a NaN or infinity in a column declared `numeric` or `float` is `non_finite`. Checked over every
    such column the frame carries, whether or not the reading row names it (ruled 2026-11-10 and
    2026-11-16). A message names the column, never a value."""
    for c in contract.non_nullable:
        if c in df.columns and df[c].null_count():
            raise ContractViolation("null_value", f"null value(s) in column {c}")
    for c, kind in contract.types.items():
        if kind in ("numeric", "float") and c in df.columns:
            # a numeric column may arrive as an integer or decimal dtype, which holds no NaN
            if df[c].dtype.is_float() and not df[c].is_finite().all():
                raise ContractViolation("non_finite", f"non-finite number(s) in column {c}")


def check_contract_rows(df: Any, contract: Any, *, projected: bool = False) -> None:
    """The values (`check_contract_values`) first, then the key and the dependencies, over the rows
    of one read: one scope value's rows, or the whole asset under `scope: none`. A message names the
    columns, never a value.

    `projected=True` is for a read that selected only the columns it names (engine-fin's lookups).
    Such a frame may lack the whole key, or a dependency's `by`; those checks then hold over the
    columns it carries. The default is the whole-row read: a missing key column is an error there,
    never a skipped check."""
    import polars as pl

    check_contract_values(df, contract)
    whole_key = not projected or all(k in df.columns for k in contract.key)
    if whole_key and df.select(list(contract.key)).is_duplicated().any():
        raise ContractViolation("duplicate_key", f"more than one row for one ({', '.join(contract.key)})")
    for by, determined in contract.dependencies:
        present = [c for c in determined if c in df.columns]
        if not present or (projected and by not in df.columns):
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


def nullable(contract: DatasetContract, columns) -> list[str]:
    """The declared columns of `columns` the contract does not declare `nullable: false`, sorted."""
    return sorted(c for c in columns if c in contract.types and c not in contract.non_nullable)
