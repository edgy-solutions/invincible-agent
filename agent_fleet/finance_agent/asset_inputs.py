"""The finance inputs resolver: a declared measure computed over rows read, as the caller, from
ONE catalogued asset. Design: docs/plans/fin-inputs-resolver.md.

Everything here is inert until `FIN_DATASET_URN` is set. Unset, this module imports nothing heavy
(polars and the client are imported inside functions), reads nothing, and `main` answers from
the in-process seed exactly as before.

THE SHAPE. `read_rows` takes the reader (`main.mesh_ticketed_read`), asks it for a LazyFrame,
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

import logging
import os
import time
from contextvars import ContextVar
from decimal import Decimal
from typing import Any, Callable, Optional

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

#: Entity fields `run_declared` never reads. They hold these so the dataclasses are whole;
#: `check_consistency` does not run on an asset state.
_PLACEHOLDER_TECHNIQUE = "LEVEL_OF_EFFORT"

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


#: ADR-0065:133 rules that `data_provenance` carries the dataset URN, an as-of and a ticket id. It
#: is unmet: the broker's ticket carries neither an id nor an as-of, and the client discards the
#: ticket. Until it does, the string says the ticket is pending rather than inventing one (ruled
#: 2026-11-08). The URN stays last: the live leg reads `Source: <urn>` as the suffix.
TICKET_PENDING = "(ticket: pending)"


def provenance(urn: str) -> str:
    """The `data_provenance` an asset answer carries: the operator's banner, the pending ticket and the URN."""
    return f"{dataset_banner()} {TICKET_PENDING} Source: {urn}"


def dataset_provenance(banner: str, urn: str) -> str:
    """`provenance` for a dataset-kind row, whose banner is the row's own, not the environment's."""
    return f"{banner} {TICKET_PENDING} Source: {urn}"


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
    state = FinanceState()
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
                ca_id=ca, name=ca, program_id=program_id, wbs_id="", obs_id="", bac=0.0))
    for wp, ca in accounts.items():
        state.work_packages.append(WorkPackage(
            wp_id=wp, name=wp, ca_id=ca, bac=0.0, technique=_PLACEHOLDER_TECHNIQUE))
    return state


# ── the read ────────────────────────────────────────────────────────────────────────────

def read_rows(read: Callable[[str], Any], urn: str, program_id: str,
              periods: Optional[list[str]]) -> Any:
    """The program's rows (and the window's, if `periods` is given) as a collected frame.

    `read` is `main.mesh_ticketed_read`: it returns the caller's LazyFrame, or raises
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
                      program_id: str) -> list[tuple[tuple[str, ...], Any]]:
    """`read_rows` for a dataset-kind row: the rows of ONE program of the ROW'S columns.

    The contract is the row's own columns, not the fixed finance ones. All of `levels` and
    `value_columns` must be present and every value column numeric (checked on the schema, before a
    row is collected); the level columns are read as strings, and the filter keeps the rows whose
    `levels[0]` is `program_id`. Only those columns are selected, and the row cap is applied before
    collect, so it counts rows read, before any reduction. Every outcome maps as `read_rows` maps it. An empty frame raises `NotInModel`, as `state_from_rows`
    does for a program the asset does not hold. Nulls and non-finite values are checked on the
    collected frame; a message names the rule and the column, never a row's value.

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
    missing = [c for c in (*levels, *value_columns) if c not in schema]
    if missing:
        raise ContractViolation("missing_column", "missing column(s): " + ", ".join(missing))
    bad = [c for c in value_columns if not schema[c].is_numeric()]
    if bad:
        raise ContractViolation("wrong_type", "column(s) of the wrong type: " + ", ".join(bad))
    cap = max_rows()
    as_text = [pl.col(c).cast(pl.String) for c in levels]
    q = lf.filter(pl.col(levels[0]).cast(pl.String) == program_id)
    try:
        df = q.select([*as_text, *(pl.col(c) for c in value_columns)]).head(cap + 1).collect()
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


def require_grant(read: Callable[[str], Any], urn: str) -> None:
    """Refuse unless the caller may read `urn`: the ticket `read_rows` takes first (the client's
    `get_dataframe` asks the gateway's `/authorize` before it returns a frame), and nothing
    scanned. `read` is `main.mesh_ticketed_read`; its `HTTPException` passes through untouched."""
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
