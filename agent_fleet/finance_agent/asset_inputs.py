"""The finance inputs resolver: a declared measure computed over rows read, as the caller, from
ONE catalogued asset. Design: docs/plans/fin-inputs-resolver.md.

Everything here is inert until `FIN_DATASET_URN` is set. Unset, this module imports nothing heavy
(polars and the client are imported inside functions), reads nothing, and `main` answers from
the in-process seed exactly as before.

THE SHAPE. `read_rows` takes the reader (`main`'s ticketed reader), asks it for a LazyFrame,
filters it to the one program (and the window, if one was asked for), selects the fixed columns
and caps the row count, all before a row is collected. `state_from_rows` is PURE over the
collected frame: it enforces the column contract and builds a real `FinanceState`, so
`measure_verbs.run_declared` runs over it unchanged.

NOTHING HERE NAMES A PROGRAM, CUSTOMER OR DOMAIN. The asset is a URN from the environment and
the columns are the contract's fixed names.

NO MESSAGE HERE CARRIES A ROW'S VALUE. A contract violation names the rule and the column, never
the money or the identifier that broke it.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import time
from contextvars import ContextVar
from decimal import Decimal
from typing import Any, Callable, Mapping, NamedTuple, Optional

from fastapi import HTTPException, Request

try:  # flat in the image (/app), packaged in the repo — the same two-way import `main` uses
    from entities import (
        FISCAL_PERIODS, ControlAccount, FinanceState, NotInModel, PeriodFact, Program, WorkPackage,
    )
except ImportError:
    from agent_fleet.finance_agent.entities import (
        FISCAL_PERIODS, ControlAccount, FinanceState, NotInModel, PeriodFact, Program, WorkPackage,
    )

URN_ENV = "FIN_DATASET_URN"
BANNER_ENV = "FIN_DATASET_BANNER"
GATEWAY_ENV = "CENTRAL_GATEWAY_URL"
MAX_ROWS_ENV = "FIN_ASSET_MAX_ROWS"
DEFAULT_MAX_ROWS = 100_000
URN_PREFIX = "urn:li:dataset:"

#: The contract's fixed column names. The set the read selects, so a column outside it is never
#: collected.
STRING_COLUMNS: tuple[str, ...] = (
    "program_id", "program_name", "control_account", "work_package", "period",
)
NUMERIC_COLUMNS: tuple[str, ...] = ("program_bac", "bcws", "bcwp", "acwp")
COLUMNS: tuple[str, ...] = STRING_COLUMNS + NUMERIC_COLUMNS

#: The `FinanceState` collections the contract's columns fill. Every other one is `uncarried`, and
#: so is every entity field no column names (account and package BAC, WBS, OBS, technique): those
#: are None, never a placeholder, because the built-ins read this state too (ruled 2026-11-08) and
#: show those fields. `check_consistency` does not run on an asset state.
CARRIED: tuple[str, ...] = ("programs", "control_accounts", "work_packages", "facts")


class AssetState(FinanceState):
    """A `FinanceState` the contract's columns filled. The collections they do not fill are `uncarried`."""
    uncarried = frozenset(f.name for f in dataclasses.fields(FinanceState) if f.name not in CARRIED)


def with_uncarried_from(state: AssetState, seed: FinanceState) -> FinanceState:
    """`state`'s carried collections with every `uncarried` one taken from `seed` (one program's
    narrowed seed): the one state a mixed export computes over, where a `source: seed` measure
    (ruled 2026-11-09) reads what the contract does not carry. A plain `FinanceState`, so nothing
    in it is uncarried any more; the carried collections are the asset's, never the seed's."""
    return FinanceState(**{f.name: getattr(seed if f.name in state.uncarried else state, f.name)
                           for f in dataclasses.fields(FinanceState)})

# ── the logger ──────────────────────────────────────────────────────────────────────────
# engine-fin configures no logging, so a bare `logging.getLogger(...).info(...)` is dropped at
# the root's WARNING level. This logger carries its own INFO handler so the timing line prints
# with no root configuration. `propagate` is off so a deployment that DOES configure the root
# does not print every line twice.
log = logging.getLogger("engine_fin.asset_inputs")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


# ── outcomes ────────────────────────────────────────────────────────────────────────────

class ContractViolation(Exception):
    """The asset's rows break the column contract. Carries the rule, never a row's value."""

    def __init__(self, rule: str, message: str):
        super().__init__(message)
        self.rule = rule
        self.message = message


class AssetDenied(Exception):
    """The gate refused this caller the asset."""


class AssetUnavailable(Exception):
    """The read could not be completed: the mesh was unreachable or the scan failed."""


class AssetTooLarge(Exception):
    def __init__(self, max_rows: int):
        super().__init__(f"the asset holds more than {max_rows} rows for this request")
        self.max_rows = max_rows


# ── configuration ───────────────────────────────────────────────────────────────────────

def dataset_urn() -> Optional[str]:
    """The asset to read, or None: unset (or blank) means the seed answers."""
    return (os.environ.get(URN_ENV) or "").strip() or None


def dataset_banner() -> str:
    return (os.environ.get(BANNER_ENV) or "").strip()


def max_rows() -> int:
    raw = (os.environ.get(MAX_ROWS_ENV) or "").strip()
    return int(raw) if raw else DEFAULT_MAX_ROWS


#: ADR-0065:133 rules that `data_provenance` carries the dataset URN, an as-of and a ticket id.
#: The broker's ticket carries `ticket_id`, `issued_at` and `as_of` (dag-tools 0.13.0, #31), and
#: `get_dataframe_with_ticket` hands back its receipt beside the frame. `main.mesh_ticketed_read`
#: returns that pair, and every asset answer cites the receipt of the read it computed over. A
#: receipt that names neither (a broker that stamps no as-of and issues no id) still says the
#: ticket is pending rather than inventing one (ruled 2026-11-08), byte for byte this text. The
#: URN stays last: the live leg reads `Source: <urn>` as the suffix.
TICKET_PENDING = "(ticket: pending)"


def ticket_clause(receipt: Mapping[str, Any]) -> str:
    """The receipt as the provenance clause: its as-of and its ticket id, each only if the receipt
    carries it. Nothing is claimed that the receipt does not say: no as-of without one, and an
    absent id is `pending`. A receipt with neither is exactly `TICKET_PENDING`."""
    as_of, ticket_id = receipt.get("as_of"), receipt.get("ticket_id")
    ticket = f"ticket: {ticket_id}" if ticket_id else "ticket: pending"
    return f"(as of {as_of}, {ticket})" if as_of else f"({ticket})"


def provenance(urn: str, receipt: Mapping[str, Any]) -> str:
    """The `data_provenance` an asset answer carries: the operator's banner, the ticket of the read
    the answer computed over (`receipt`, the client's) and the URN."""
    return f"{dataset_banner()} {ticket_clause(receipt)} Source: {urn}"


def dataset_provenance(banner: str, urn: str, receipt: Mapping[str, Any]) -> str:
    """`provenance` for a dataset-kind row, whose banner is the row's own, not the environment's."""
    return f"{banner} {ticket_clause(receipt)} Source: {urn}"


def _load_client() -> tuple[Any, type, type]:
    """THE SEAM: `(CortexDataClient, NotEntitled, MeshUnavailable)`. Tests replace this function;
    nothing replaces a module in `sys.modules`. Imported here and nowhere else, so an unset
    flag imports neither the client nor polars."""
    from dag_tools.cortex_data.client import CortexDataClient
    from dag_tools.cortex_data.identity import MeshUnavailable, NotEntitled
    return CortexDataClient, NotEntitled, MeshUnavailable


def check_config() -> None:
    """Raise at boot when the flag is set and the deployment cannot honour it.

    Unset is the common case and costs nothing. Set, everything the read needs must already be
    true, because the alternative is a first request that fails (or, worse, answers from
    somewhere else) in front of a user."""
    urn = dataset_urn()
    if urn is None:
        return
    problems: list[str] = []
    if not urn.startswith(URN_PREFIX) or len(urn) == len(URN_PREFIX):
        problems.append(f"{URN_ENV} is not a '{URN_PREFIX}...' URN")
    if not dataset_banner():
        problems.append(f"{BANNER_ENV} is required: it is what stops a synthetic asset reading as real")
    if not (os.environ.get(GATEWAY_ENV) or "").strip():
        problems.append(f"{GATEWAY_ENV} is required")
    raw = (os.environ.get(MAX_ROWS_ENV) or "").strip()
    if raw:
        try:
            if int(raw) < 1:
                raise ValueError
        except ValueError:
            problems.append(f"{MAX_ROWS_ENV} must be a positive integer")
    try:
        _load_client()
    except Exception as exc:  # ImportError, or a transitive import failing
        problems.append(f"the mesh read client cannot be imported ({type(exc).__name__})")
    if problems:
        raise RuntimeError(f"{URN_ENV} is set but the deployment cannot honour it: " + "; ".join(problems))


# ── the caller's bearer ─────────────────────────────────────────────────────────────────

_BEARER: "ContextVar[Optional[str]]" = ContextVar("engine_fin_asset_bearer", default=None)


def current_bearer() -> Optional[str]:
    """The inbound request's bearer token, or None when there is none or no request."""
    return _BEARER.get()


async def capture_bearer(request: Request) -> None:
    """App dependency: publish the request's bearer so a read three frames down can pass it on
    (the SDK's technique for the caller). Set on EVERY request, to None when absent, so a value
    can never outlive the request that carried it. Never logged."""
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    _BEARER.set(token.strip() or None if scheme.lower() == "bearer" else None)


# ── the contract ────────────────────────────────────────────────────────────────────────

def check_schema(schema: Any) -> None:
    """Every contract column is present, string columns are strings, numeric columns numeric.
    `schema` is a polars Schema (lazy or eager)."""
    import polars as pl

    missing = [c for c in COLUMNS if c not in schema]
    if missing:
        raise ContractViolation("missing_column", "missing column(s): " + ", ".join(missing))
    bad = [c for c in STRING_COLUMNS if schema[c] != pl.String]
    bad += [c for c in NUMERIC_COLUMNS if not schema[c].is_numeric()]
    if bad:
        raise ContractViolation("wrong_type", "column(s) of the wrong type: " + ", ".join(bad))


def state_from_rows(df: Any, program_id: str) -> FinanceState:
    """A real `FinanceState` from one program's rows. PURE over the frame.

    Raises `NotInModel` for an empty frame, `ContractViolation` for any rule broken. The frame
    is expected to hold the asked program ONLY; a row of another program is a violation, so a
    read that forgot its filter fails loudly rather than blending programs."""
    import polars as pl

    check_schema(df.schema)
    for c in COLUMNS:
        if df[c].null_count():
            raise ContractViolation("null_value", f"null value(s) in column {c}")
    for c in NUMERIC_COLUMNS:
        if df[c].dtype.is_float() and not df[c].is_finite().all():
            raise ContractViolation("non_finite", f"non-finite number(s) in column {c}")
    if df.height == 0:
        raise NotInModel(f"the asset holds no rows for program {program_id!r} in this window")
    if (df["program_id"] != program_id).any():
        raise ContractViolation("other_program_rows", "rows of another program in the read")
    if df["program_name"].n_unique() > 1:
        raise ContractViolation("program_name_not_unique", "more than one program_name for the program")
    if df["program_bac"].n_unique() > 1:
        raise ContractViolation("program_bac_not_unique", "program_bac differs between rows")
    per_wp = df.group_by("work_package").agg(pl.col("control_account").n_unique().alias("n"))
    if (per_wp["n"] > 1).any():
        raise ContractViolation("work_package_in_two_accounts",
                                "a work_package appears under more than one control_account")
    if df.select(["work_package", "period"]).is_duplicated().any():
        raise ContractViolation("duplicate_work_package_period",
                                "more than one row for a (work_package, period)")
    if not df["period"].is_in(list(FISCAL_PERIODS)).all():
        raise ContractViolation("period_outside_calendar",
                                "a period outside the fiscal calendar")

    first = df.row(0, named=True)
    state = AssetState()
    state.programs.append(Program(program_id=program_id, name=first["program_name"],
                                  bac=first["program_bac"]))
    accounts: dict[str, str] = {}   # work_package -> control_account, first appearance order
    for r in df.iter_rows(named=True):
        wp, ca = r["work_package"], r["control_account"]
        if wp not in accounts:
            accounts[wp] = ca
        state.facts.append(PeriodFact(wp_id=wp, period=r["period"],
                                      bcws=r["bcws"], bcwp=r["bcwp"], acwp=r["acwp"]))
    seen: set[str] = set()
    for ca in accounts.values():
        if ca not in seen:
            seen.add(ca)
            state.control_accounts.append(ControlAccount(
                ca_id=ca, name=ca, program_id=program_id, wbs_id=None, obs_id=None, bac=None))
    for wp, ca in accounts.items():
        state.work_packages.append(WorkPackage(
            wp_id=wp, name=wp, ca_id=ca, bac=None, technique=None))
    return state


# ── a dataset row's contract ────────────────────────────────────────────────────────────
# A dataset row's read is held to the contract the row names (`dataset_contracts.DatasetContract`):
# the contract declares the columns, their types, the key and the dependencies, and these two
# functions enforce them. They name no column of any contract (ruled 2026-11-10).

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


# ── the read ────────────────────────────────────────────────────────────────────────────

def read_rows(read: Callable[[str], Any], urn: str, program_id: str,
              periods: Optional[list[str]]) -> Any:
    """The program's rows (and the window's, if `periods` is given) as a collected frame.

    `read` is `main`'s ticketed reader: it returns the caller's LazyFrame (keeping the read's
    receipt for the answer's provenance), or raises
    `HTTPException` for an identity it will not read as (passed through untouched). The filter,
    the column select and the row cap are all applied to the lazy frame, so a row of another
    program, or a column outside the contract, is never collected. One timing line per read."""
    import polars as pl

    t0 = time.perf_counter()
    try:
        lf = read(urn)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_for_read_failure(exc)
    t1 = time.perf_counter()
    try:
        schema = lf.collect_schema()
    except Exception as exc:
        log.warning("asset scan failed: %s", type(exc).__name__)  # type only: text may hold a credential
        raise AssetUnavailable("the asset could not be scanned") from None
    check_schema(schema)
    cap = max_rows()
    q = lf.filter(pl.col("program_id") == program_id)
    if periods is not None:
        q = q.filter(pl.col("period").is_in(periods))
    try:
        df = q.select(list(COLUMNS)).head(cap + 1).collect()
    except Exception as exc:
        log.warning("asset scan failed: %s", type(exc).__name__)
        raise AssetUnavailable("the asset could not be scanned") from None
    t2 = time.perf_counter()
    log.info("asset read ticket_ms=%d scan_ms=%d sql_ms=0 rows=%d bytes=%d urn=%s",
             round((t1 - t0) * 1000), round((t2 - t1) * 1000), df.height, df.estimated_size(), urn)
    if df.height > cap:
        raise AssetTooLarge(cap)
    return df


def read_dataset_rows(read: Callable[[str], Any], urn: str, levels: tuple[str, ...],
                      value_columns: tuple[str, ...], value_op: str, per_path: str,
                      program_id: str, contract: Any) -> list[tuple[tuple[str, ...], Any]]:
    """`read_rows` for a dataset-kind row: the rows of ONE program, held to the row's `contract`.

    The schema is checked against the contract before a row is collected (`check_contract_schema`;
    that the row's `levels` are string contract columns and its `value_columns` numeric ones is held
    at load). The filter keeps the rows whose `levels[0]` (the contract's scope) is `program_id`;
    every contract column the asset carries is selected, and the row cap is applied before collect,
    so it counts rows read, before any reduction. Every outcome maps as `read_rows` maps it. An
    empty frame raises `NotInModel`, as `state_from_rows` does for a program the asset does not
    hold. Nulls and non-finite values are checked in the row's columns, then the contract's key and
    dependencies (`check_contract_rows`); a message names the rule and the column, never a row's
    value.

    RETURNS the `(path below the root, Decimal amount)` list `run_dataset` takes. A row's amount is
    `Decimal(str(x))`, or for `value_op == "minus"` `Decimal(str(a)) - Decimal(str(b))`. Under
    `per_path == "once"` the rows are grouped by the full level tuple, every row of a group must
    carry the same amount (else `varies_within_path`, naming the column(s), never a value), and the
    amount is taken once per group; under `"sum"` every row stays."""
    import polars as pl

    t0 = time.perf_counter()
    try:
        lf = read(urn)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_for_read_failure(exc)
    t1 = time.perf_counter()
    try:
        schema = lf.collect_schema()
    except Exception as exc:
        log.warning("asset scan failed: %s", type(exc).__name__)
        raise AssetUnavailable("the asset could not be scanned") from None
    selected = check_contract_schema(schema, contract, (*levels, *value_columns))
    cap = max_rows()
    q = lf.filter(pl.col(levels[0]) == program_id)
    try:
        df = q.select(selected).head(cap + 1).collect()
    except Exception as exc:
        log.warning("asset scan failed: %s", type(exc).__name__)
        raise AssetUnavailable("the asset could not be scanned") from None
    t2 = time.perf_counter()
    log.info("asset read ticket_ms=%d scan_ms=%d sql_ms=0 rows=%d bytes=%d urn=%s",
             round((t1 - t0) * 1000), round((t2 - t1) * 1000), df.height, df.estimated_size(), urn)
    if df.height > cap:
        raise AssetTooLarge(cap)
    for c in (*levels, *value_columns):
        if df[c].null_count():
            raise ContractViolation("null_value", f"null value(s) in column {c}")
    for c in value_columns:
        if df[c].dtype.is_float() and not df[c].is_finite().all():
            raise ContractViolation("non_finite", f"non-finite number(s) in column {c}")
    if df.height == 0:
        raise NotInModel(f"the asset holds no rows for program {program_id!r}")
    check_contract_rows(df, contract)
    n = len(levels) - 1
    paths: list[tuple[tuple[str, ...], Any]] = []
    for r in df.select([*levels[1:], *value_columns]).iter_rows():
        amount = Decimal(str(r[n]))
        if value_op == "minus":
            amount -= Decimal(str(r[n + 1]))
        paths.append((tuple(str(v) for v in r[:n]), amount))
    if per_path == "once":
        seen: dict[tuple[str, ...], Any] = {}
        for path, amount in paths:
            if seen.setdefault(path, amount) != amount:
                raise ContractViolation(
                    "varies_within_path",
                    ", ".join(value_columns) + " vary within one terminal path")
        paths = list(seen.items())
    return paths


class SeriesRead(NamedTuple):
    """What `read_dataset_series` returns, and `measure_verbs.run_dataset_series` takes."""
    periods: list[tuple[str, dict[str, Decimal]]]   # in period order: (period, {column: sum})
    constants: dict[str, Decimal]                   # {column: the program's one value}
    status: Optional[str]                           # the status column's one value, or None


def read_dataset_series(read: Callable[[str], Any], urn: str, *, scope: str, period: str,
                        status: str, per_period: tuple[str, ...], per_program: tuple[str, ...],
                        program_id: str, contract: Any) -> SeriesRead:
    """`read_rows` for a dataset row drawn as MULTI_SERIES: the rows of ONE program of the ROW'S
    columns, reduced the two ways the row may ask and no other.

    The schema is checked against the row's `contract` before a row is collected, as
    `read_dataset_rows` checks it. The filter keeps the rows whose `scope` column is `program_id`;
    every contract column the asset carries is selected, and the row cap applies before collect.
    Every outcome maps as `read_rows` maps it, and an empty frame raises `NotInModel`. Nulls and
    non-finite values are checked in the row's columns, then the contract's key and dependencies.

    A `per_period` column is summed over the program's rows at each period (exactly, as Decimal).
    A `per_program` column, and the `status` column when the row names one, is declared determined
    by the scope (held at load), so the dependency check leaves it one value across the program's
    rows. A period, or the status, outside the fiscal calendar is `period_outside_calendar`. A
    message names the rule and the column, never a row's value."""
    import polars as pl

    t0 = time.perf_counter()
    try:
        lf = read(urn)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_for_read_failure(exc)
    t1 = time.perf_counter()
    try:
        schema = lf.collect_schema()
    except Exception as exc:
        log.warning("asset scan failed: %s", type(exc).__name__)
        raise AssetUnavailable("the asset could not be scanned") from None
    text = [scope, period, *((status,) if status else ())]
    numeric = [*per_period, *per_program]
    selected = check_contract_schema(schema, contract, (*text, *numeric))
    cap = max_rows()
    q = lf.filter(pl.col(scope) == program_id)
    try:
        df = q.select(selected).head(cap + 1).collect()
    except Exception as exc:
        log.warning("asset scan failed: %s", type(exc).__name__)
        raise AssetUnavailable("the asset could not be scanned") from None
    t2 = time.perf_counter()
    log.info("asset read ticket_ms=%d scan_ms=%d sql_ms=0 rows=%d bytes=%d urn=%s",
             round((t1 - t0) * 1000), round((t2 - t1) * 1000), df.height, df.estimated_size(), urn)
    if df.height > cap:
        raise AssetTooLarge(cap)
    for c in (*text, *numeric):
        if df[c].null_count():
            raise ContractViolation("null_value", f"null value(s) in column {c}")
    for c in numeric:
        if df[c].dtype.is_float() and not df[c].is_finite().all():
            raise ContractViolation("non_finite", f"non-finite number(s) in column {c}")
    if df.height == 0:
        raise NotInModel(f"the asset holds no rows for program {program_id!r}")
    check_contract_rows(df, contract)
    calendar = list(FISCAL_PERIODS)
    if not df[period].is_in(calendar).all() or (status and df[status][0] not in calendar):
        raise ContractViolation("period_outside_calendar", "a period outside the fiscal calendar")
    sums: dict[str, dict[str, Decimal]] = {}
    for r in df.select([period, *per_period]).iter_rows():
        at = sums.setdefault(r[0], {c: Decimal(0) for c in per_period})
        for c, x in zip(per_period, r[1:]):
            at[c] += Decimal(str(x))
    first = df.row(0, named=True)
    return SeriesRead(
        periods=sorted(sums.items(), key=lambda kv: calendar.index(kv[0])),
        constants={c: Decimal(str(first[c])) for c in per_program},
        status=first[status] if status else None)


def require_grant(read: Callable[[str], Any], urn: str) -> None:
    """Refuse unless the caller may read `urn`: the ticket `read_rows` takes first (the client's
    `get_dataframe_with_ticket` asks the gateway's `/authorize` before it returns a frame), and
    nothing scanned. `read` is `main`'s ticketed reader; its `HTTPException` passes through
    untouched."""
    try:
        read(urn)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_for_read_failure(exc)


def _raise_for_read_failure(exc: Exception) -> None:
    """Map the client's outcome to ours. Unknown failures are unavailable, logged by TYPE only."""
    _client, not_entitled, mesh_unavailable = _load_client()
    if isinstance(exc, not_entitled):
        raise AssetDenied() from None
    if isinstance(exc, mesh_unavailable):
        log.warning("asset read unavailable: %s", type(exc).__name__)
        raise AssetUnavailable("the mesh could not serve the read") from None
    log.warning("asset read failed: %s", type(exc).__name__)
    raise AssetUnavailable("the read failed") from None
