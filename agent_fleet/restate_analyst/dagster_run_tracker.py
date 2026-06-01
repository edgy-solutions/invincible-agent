"""DagsterRunTracker — dedupes Dagster job launches per session_id.

Lives in its own module so the handler logic can be unit-tested without
importing the rest of ``agent_fleet.restate_analyst.main`` (which pulls in
heavy engine dependencies like smolagents and baml_client).

Background — the bug this fixes:

    The previous tracker only checked "did we record a run_id for this
    session_id?" and returned the cached id unconditionally. That meant
    every session could only ever run ONE Dagster job in its lifetime, AND
    a UI that re-fired the same submission could still launch duplicate
    runs when paired with the gateway's per-request UUID minting (see
    gateway.py:535).

    The fix: on every call, look up the cached run_id's CURRENT status from
    Dagster's GraphQL. Treat ``SUCCESS / FAILURE / CANCELED`` as terminal —
    clear the slot and launch a fresh run. Treat everything else (including
    "Dagster unreachable, status unknown") as still-active — return the
    cached id and dedupe.

The "unknown → dedupe" choice is deliberate: a transient Dagster outage
must not multiply runs. The next attempt that succeeds in reaching Dagster
will correctly observe the run's state and either continue to dedupe or
relaunch.
"""

from __future__ import annotations

import httpx
from restate import ObjectContext, VirtualObject


# Dagster RunStatus values that mean "this run is over, allow a new one."
# Per Dagster GraphQL schema. CANCELING is excluded because the run is
# still being torn down at that point and we don't want a duplicate to
# race the cancel.
DAGSTER_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"SUCCESS", "FAILURE", "CANCELED"}
)


async def fetch_dagster_run_status(
    dagster_url: str, run_id: str
) -> str | None:
    """Return Dagster's RunStatus string for a run, or None on error.

    A ``None`` return means "unknown — keep dedupe behavior" so a transient
    Dagster outage cannot cause spurious relaunches.

    Special case: if Dagster reports ``RunNotFoundError`` (the run was
    purged or the id is stale), we map it to ``CANCELED`` so the caller
    treats it as terminal and launches a fresh run.
    """
    query = """
    query GetRunStatus($runId: ID!) {
      runOrError(runId: $runId) {
        __typename
        ... on Run { status }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{dagster_url}/graphql",
                json={"query": query, "variables": {"runId": run_id}},
            )
            resp.raise_for_status()
            data = resp.json()
            ror = data.get("data", {}).get("runOrError", {})
            if ror.get("__typename") == "Run":
                return ror.get("status")
            if ror.get("__typename") == "RunNotFoundError":
                return "CANCELED"
            return None
    except Exception:
        return None


async def _launch_dagster_run(
    dagster_url: str, mutation: str, variables: dict
) -> str | None:
    """POST the launchRun mutation to Dagster, return runId on success."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{dagster_url}/graphql",
            json={"query": mutation, "variables": variables},
        )
        resp.raise_for_status()
        data = resp.json()
        run_data = data.get("data", {}).get("launchRun", {})
        if run_data.get("__typename") == "LaunchRunSuccess":
            return run_data["run"]["runId"]
        return None


run_tracker = VirtualObject("DagsterRunTracker")


@run_tracker.handler()
async def get_or_launch_run(ctx: ObjectContext, payload: dict) -> str | None:
    dagster_url = payload.get("dagster_url")
    mutation = payload.get("mutation")
    variables = payload.get("variables")

    if not dagster_url or not mutation:
        return None

    # 1. If we already have a cached run for this session, consult Dagster
    # for its current status. Only relaunch if terminal.
    existing_run_id = await ctx.get("dagster_run_id")
    if existing_run_id:
        # ctx.run needs a callable that the SDK awaits — a lambda that
        # *returns* a coroutine object fails because the SDK tries to
        # JSON-serialize the coroutine itself. Inline async closure works.
        async def _check_status():
            return await fetch_dagster_run_status(dagster_url, existing_run_id)

        status = await ctx.run("fetch_status", _check_status)
        if status not in DAGSTER_TERMINAL_STATUSES:
            # Non-terminal OR unknown — dedupe.
            return existing_run_id
        ctx.clear("dagster_run_id")

    # 2. Launch a fresh run, durably journaled by ctx.run.
    async def _launch():
        return await _launch_dagster_run(dagster_url, mutation, variables)

    new_run_id = await ctx.run("launch_dagster", _launch)

    if new_run_id:
        ctx.set("dagster_run_id", new_run_id)

    return new_run_id
