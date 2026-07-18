"""Refuse-to-run guard for the bootstrap-state-debt law.

See docs/principles/bootstrap-state-debt.md. EVERY scripts/ file that MUTATES a durable
store (Neo4j / Weaviate / Jena / Postgres / DataHub) calls ``refuse_unless_throwaway()``
at entry. Read-only diagnostics never call it (they are always fine — the law's exception).

Two gates, in order:
  1. WORK-SHAPED target -> refused OUTRIGHT. No flag overrides. The reliable signal is an
     explicit env the work overlay sets (IAGENT_ENV / CLUSTER_ENV / DEPLOY_ENV /
     ENVIRONMENT in {work, prod, production, staging, stage}); plus a best-effort scan of
     the connection targets for real-cluster markers. A direct durable-store mutation of a
     real cluster is NEVER a fix (the law), so no acknowledgement can permit it.
  2. Otherwise (sandbox / ambiguous) -> require an explicit ack env-flag AND print that the
     reproducible fix must land THIS session (never hand-run-then-fold-later).

NOTE for the work overlay: set IAGENT_ENV=work so gate 1 fires deterministically — the
target-string scan is a backstop, not the primary signal.
"""
from __future__ import annotations

import os
import sys
from typing import Iterable, Optional

_WORK_ENV_KEYS = ("IAGENT_ENV", "CLUSTER_ENV", "DEPLOY_ENV", "ENVIRONMENT")
_WORK_ENV_VALUES = {"work", "prod", "production", "staging", "stage"}

# Best-effort markers that a connection target is a REAL cluster, not a throwaway sandbox.
# Conservative + extensible; the deterministic signal is IAGENT_ENV (above).
_WORK_TARGET_MARKERS = ("work", "prod", "corp", "internal.", ".mil", ".gov", "employee")

# Connection env vars a durable-mutating script typically resolves its target from.
_TARGET_ENV_KEYS = (
    "NEO4J_URI", "NEO4J_HOST", "WEAVIATE_URL", "WEAVIATE_HOST", "JENA_SPARQL_ENDPOINT",
    "DATABASE_URL", "POSTGRES_HOST", "DATAHUB_GMS_URL", "DATAHUB_GMS", "CENTRAL_GATEWAY_URL",
)


def _work_signal(targets: Iterable[str]) -> Optional[str]:
    for k in _WORK_ENV_KEYS:
        v = os.environ.get(k, "").strip().lower()
        if v in _WORK_ENV_VALUES:
            return f"{k}={os.environ.get(k)}"
    haystack = " ".join(
        [str(t) for t in (targets or [])]
        + [os.environ.get(k, "") for k in _TARGET_ENV_KEYS]
    ).lower()
    for m in _WORK_TARGET_MARKERS:
        if m in haystack:
            return f"target contains {m!r}"
    return None


def refuse_unless_throwaway(
    store: str,
    *,
    ack_env: str,
    reproducible_home: str,
    targets: Iterable[str] = (),
) -> None:
    """Enforce the bootstrap-state-debt law at a durable-mutating script's entry.

    ``store``            — human name of what gets mutated (e.g. "Weaviate Predicate collection").
    ``ack_env``          — the ack env-flag that must equal "1" for a sandbox run.
    ``reproducible_home``— where the reproducible fix belongs (asset / helm Job / CI).
    ``targets``          — resolved connection strings this run will mutate (for the work scan).
    Exits the process (non-zero) on refusal; returns None when the run is permitted.
    """
    work = _work_signal(targets)
    if work:
        sys.exit(
            f"REFUSING ({store}): work-shaped target [{work}]. bootstrap-state-debt law — a "
            f"direct durable-store mutation of a real cluster is NEVER a fix. Put it in "
            f"{reproducible_home}. No flag overrides this. (docs/principles/bootstrap-state-debt.md)"
        )
    if os.environ.get(ack_env) != "1":
        sys.exit(
            f"REFUSING ({store}): a durable-store mutation from scripts/ is a NON-REPRODUCIBLE "
            f"manual action (bootstrap-state-debt law). Set {ack_env}=1 ONLY for a THROWAWAY "
            f"sandbox, AND land the reproducible fix in {reproducible_home} THIS session — never "
            f"hand-run-then-fold-later, the revert lives in 'later'. (docs/principles/bootstrap-state-debt.md)"
        )
    sys.stderr.write(
        f"[bootstrap-guard] {store}: acked throwaway run ({ack_env}=1). REMINDER: the reproducible "
        f"fix belongs in {reproducible_home} and must land THIS session, or this is debt, not a fix.\n"
    )
