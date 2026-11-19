"""The access-grant path through engine-r (ADR-0062 section 5/6; architect rulings D5-D8, 2026-11-16).

An approved access grant becomes a proposal against ``policy/asset_grants.yaml`` in the deployment's
CONFIGURED policy repository, is reviewed by two people, merges, and the merge applies the grant to
the directory ADD-ONLY. Nothing here names a repository, an organisation or a URL: the target comes
from configuration (``TargetConfig.from_env``), so the sandbox proves the path against its mirror and
a deployment whose grants live in a private repository changes values, not code.

  * ``TargetConfig``         where proposals land (env only; refuses to guess).
  * ``propose_grants``       one proposal carrying the exclusion set {proposer, requester, grantee}.
  * ``backfill_ledger``      ledger decisions not yet in policy become service-filed proposals (D8).
  * ``grant_quorum``         the merge-time check: distinct approvers per the rail, one of them in each
                             changed row's audience; the excluded set is refused by the core itself.
  * ``apply_on_merge``       the merge-time directory sync, add-only (D1/D2: the seed is the one pruner).

Doubles-only: the directory write and the audience/domain lookups are injected.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from agent_fleet.repository_agent import repo_core
from agent_fleet.repository_agent.repo_core import Caller, RepoRefusal

GRANTS_PATH = "policy/asset_grants.yaml"
DOMAIN_MARK = "<DOMAIN>"


class TargetNotConfigured(RuntimeError):
    """The deployment did not say which repository engine-r writes grants to."""


@dataclass(frozen=True)
class TargetConfig:
    repo_id: str
    repo_path: str
    target_ref: str

    ENV = {
        "repo_id": "ENGINE_R_TARGET_REPO_ID",
        "repo_path": "ENGINE_R_TARGET_REPO_PATH",
        "target_ref": "ENGINE_R_TARGET_REF",
    }

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "TargetConfig":
        missing = [v for k, v in cls.ENV.items() if not (env.get(v) or "").strip()]
        if missing:
            raise TargetNotConfigured(
                "engine-r has no grant target: set " + ", ".join(missing)
                + " (the deployment's configured policy repository; there is no default)"
            )
        return cls(**{k: env[v].strip() for k, v in cls.ENV.items()})


# --------------------------------------------------------------------------- text helpers


def _blob_text(repo: "repo_core.Repo", sha: str, path: str) -> str | None:
    try:
        entry = repo._r[sha].tree[path]
    except KeyError:
        return None
    return repo._r[entry.id].data.decode("utf-8")


def _row_key(g: Mapping) -> tuple:
    return (g.get("subject"), g.get("asset"), g.get("kind") or "dataset")


def load_grant_sync(path: Path):
    """Load ``policy/sync/grant_sync.py`` by path. It is the ONE place the effective grant set
    (``union_grants``), the dangling proof (``find_dangling``) and the apply (``run``) live; engine-r
    calls them and holds no second copy. Fails closed when the file lacks any of them or ``run`` has no
    ``prune`` / ``ledger_keys`` switch (an old grant_sync cannot be told to stay add-only or to skip a
    stale ledger row alone)."""
    spec = importlib.util.spec_from_file_location("_engine_r_grant_sync", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(Path(path).parent))
    try:
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(Path(path).parent))
    run = getattr(mod, "run", None)
    params = inspect.signature(run).parameters if run is not None else {}
    if "prune" not in params:
        raise RuntimeError("grant_sync.run has no prune switch: engine-r will not apply grants without it")
    for need in ("union_grants", "find_dangling", "ledger_grant_keys", "load_grants"):
        if not callable(getattr(mod, need, None)):
            raise RuntimeError(f"grant_sync has no {need}: engine-r will not apply grants without it")
    if "ledger_keys" not in params:
        raise RuntimeError("grant_sync.run has no ledger_keys switch: engine-r will not apply grants without it")
    return mod


class _ExistsClient:
    """The one method ``find_dangling`` asks of a Topaz client, answered by ``asset_exists``."""

    def __init__(self, asset_exists: Callable[[str], bool]):
        self._exists = asset_exists

    def object_exists(self, kind: str, asset: str) -> bool:
        return bool(self._exists(asset))


def _dangling(grant_sync, asset_exists: Callable[[str], bool], rows: Iterable[Mapping]) -> tuple[list[str], list[str]]:
    """(dangling descriptions, malformed descriptions) for ``rows``, by grant_sync's own judgement."""
    grants, malformed = grant_sync.load_grants({"grants": [dict(r) for r in rows]})
    return grant_sync.find_dangling(_ExistsClient(asset_exists), grants), list(malformed)


def _grants_of(text: str | None) -> list[dict]:
    doc = yaml.safe_load(text or "") or {}
    g = doc.get("grants") or []
    return [x for x in g if isinstance(x, dict)]


def append_grants(text: str, rows: Iterable[Mapping]) -> str:
    """``text`` with ``rows`` appended to its ``grants:`` list, comments and order untouched.

    Refuses (ValueError) when the result does not parse to exactly the old grants plus the new rows:
    a file whose ``grants`` list is not its last block must be edited by a person.
    """
    rows = [dict(r) for r in rows]
    old = _grants_of(text)
    have = {_row_key(g) for g in old}
    rows = [r for r in rows if _row_key(r) not in have]
    if not rows:
        return text
    block = yaml.safe_dump(rows, sort_keys=False, default_flow_style=False, width=1000)
    out = text if text.endswith("\n") else text + "\n"
    out += "".join(("  " + ln if ln else ln) + "\n" for ln in block.splitlines())
    try:
        ok = _grants_of(out) == old + rows
    except yaml.YAMLError:
        ok = False
    if not ok:
        raise ValueError("asset_grants.yaml: the grants list is not the file's last block; edit by hand")
    return out


# --------------------------------------------------------------------------- propose


def propose_grants(
    repo: "repo_core.Repo",
    *,
    cfg: TargetConfig,
    rows: list[Mapping],
    requester: str,
    proposer: Caller,
    intent: str,
) -> dict:
    """File ONE proposal adding ``rows`` to the grants file.

    The exclusion set is {proposer, requester, every grantee} by authz_id, whoever files it
    (ruled D6): a grant filed by a service on a person's behalf still keeps that person from approving.
    """
    tip = repo._read_tip(cfg.target_ref)
    if tip is None:
        raise ValueError(f"target_ref {cfg.target_ref} does not exist")
    new = append_grants(_blob_text(repo, tip, GRANTS_PATH) or "grants: []\n", rows)
    excluded = {requester, *(str(r["subject"]) for r in rows)}
    return repo.propose(
        caller=proposer,
        target_ref=cfg.target_ref,
        changes={GRANTS_PATH: new.encode("utf-8")},
        intent=intent,
        message="Grant access: " + ", ".join(f"{r['subject']} -> {r['asset']}" for r in rows),
        excluded=sorted(excluded),
    )


def backfill_ledger(
    repo: "repo_core.Repo",
    *,
    cfg: TargetConfig,
    ledger: Iterable[Mapping],
    service: Caller,
    grant_sync,
    asset_exists: Callable[[str], bool],
) -> list[dict]:
    """One service-filed proposal per ledger decision that policy does not yet name (ruled D8).

    ``service`` must be ``Auth-Via: service``. The original approver is named in the intent; it is
    not an approval of the proposal, which is reviewed like any other. The requester (the row's
    ``requested_by``) and the grantee are excluded.

    The proposals are the EFFECTIVE set's ledger-only grants, by ``grant_sync.union_grants``: a
    revocation row is never proposed as a grant, a grant its own ledger revokes is not proposed, and
    a revoked committed grant is not re-proposed. A grant whose asset is not in the directory
    (``asset_exists``) is skipped, since the merge check would refuse it and it could never apply.
    """
    if service.auth_via != "service":
        raise ValueError("a backfill is filed by a service identity (Auth-Via: service)")
    tip = repo._read_tip(cfg.target_ref)
    if tip is None:
        raise ValueError(f"target_ref {cfg.target_ref} does not exist")
    ledger = [dict(r) for r in ledger]
    committed_rows = _grants_of(_blob_text(repo, tip, GRANTS_PATH))
    committed = {_row_key(g) for g in committed_rows}
    effective = {_row_key(g) for g in grant_sync.union_grants(committed_rows, ledger)}
    by_key = {_row_key(r): r for r in ledger if (r.get("entry") or "grant") == "grant"}
    out = []
    for key, row in by_key.items():
        if key in committed or key not in effective:
            continue
        if _dangling(grant_sync, asset_exists, [row])[0]:
            continue
        grant = {k: row[k] for k in ("subject", "asset", "granted_by", "reason") if row.get(k) is not None}
        if row.get("kind") and row["kind"] != "dataset":
            grant["kind"] = row["kind"]
        out.append(
            propose_grants(
                repo,
                cfg=cfg,
                rows=[grant],
                requester=str(row.get("requested_by") or row["subject"]),
                proposer=service,
                intent=(
                    f"Backfill of a decision already applied to the directory: approved by "
                    f"{row.get('granted_by')} (ledger row {row['subject']} / {row['asset']})"
                ),
            )
        )
    return out


# --------------------------------------------------------------------------- the merge-time check


def grant_rows_appliable(
    grant_sync, *, asset_exists: Callable[[str], bool]
) -> Callable[["repo_core.Repo", dict], None]:
    """An extra check for ``Policy.extra_checks``: a grant row that could never apply does not merge.

    ``grant_sync.run`` refuses the WHOLE file (exit 3) on one committed row whose asset is not in the
    directory, and (exit 2) on one malformed row, so such a row would stop every later apply, add-only
    or not. Each ADDED row is judged by grant_sync's own ``find_dangling`` / ``load_grants``; rows
    already committed are not re-judged here (the seed CronJob names them).
    """

    def grant_rows_appliable_check(repo: "repo_core.Repo", ctx: dict) -> None:
        meta = ctx["proposal"]
        for path in ctx["paths"]:
            if path != GRANTS_PATH:
                continue
            before = {_row_key(g) for g in _grants_of(_blob_text(repo, meta["base_sha"], path))}
            added = [g for g in _grants_of(_blob_text(repo, meta["head_sha"], path)) if _row_key(g) not in before]
            dangling, malformed = _dangling(grant_sync, asset_exists, added)
            if dangling or malformed:
                raise RepoRefusal(
                    409, "grant_row_unappliable", policy_id="repository_paths",
                    missing_binding="grant rows whose asset is in the directory and that are well formed",
                    message="the grants file would stop every apply: " + "; ".join([*dangling, *malformed]),
                    check="grant_rows",
                )

    return grant_rows_appliable_check


def _longest_row(path: str, governed: Mapping[str, dict]) -> dict | None:
    best = max((p for p in governed if path.startswith(p)), key=len, default=None)
    return governed[best] if best else None


def grant_quorum(
    governed: Mapping[str, dict],
    *,
    holders: Callable[[str], set[str]],
    domain_of: Callable[[Mapping], str | None],
) -> Callable[["repo_core.Repo", dict], None]:
    """An extra check for ``Policy.extra_checks``: the approvers the rail asks for, no fewer.

    * each touched path takes its longest-prefix row; the DISTINCT approvers must reach the largest
      ``approvers`` among them (several rows means all of them);
    * on a ``:<DOMAIN>`` row, each changed grant row names an audience (``access_grant:<its domain>``,
      else ``unmatched_review``) and at least one approver must hold it.
    The excluded set (proposer, requester, grantee) is refused by the core before this runs.
    """

    def grant_quorum_check(repo: "repo_core.Repo", ctx: dict) -> None:
        approvals = ctx["approvals"]
        meta = ctx["proposal"]
        who = {a.authz_id for a in approvals}
        rows = {p: _longest_row(p, governed) for p in ctx["paths"]}
        for path, r in rows.items():
            n = (r or {}).get("approvers")
            if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                raise RepoRefusal(
                    409, "rail_row_without_approvers", policy_id="repository_paths",
                    missing_binding=f"an `approvers` count on the rail row governing {path}",
                    message=f"the rail row governing {path} names no approvers count; refusing rather than guessing",
                    check="quorum",
                )
        need = max(int(r["approvers"]) for r in rows.values()) if rows else 1
        if len(who) < need:
            raise RepoRefusal(
                409, "too_few_approvers", policy_id="repository_paths",
                missing_binding=f"{need} distinct approvers",
                message=f"the rail asks {need} distinct approvers, got {len(who)}", check="quorum",
            )
        for path, row in rows.items():
            review = (row or {}).get("review", "")
            if not review.endswith(DOMAIN_MARK):
                continue
            before = {_row_key(g) for g in _grants_of(_blob_text(repo, meta["base_sha"], path))}
            for g in _grants_of(_blob_text(repo, meta["head_sha"], path)):
                if _row_key(g) in before:
                    continue
                dom = domain_of(g)
                audience = review.replace(DOMAIN_MARK, dom) if dom else row.get("unmatched_review", "")
                held = holders(audience) if audience else set()
                if not (who & held):
                    raise RepoRefusal(
                        403, "no_approver_in_audience", policy_id="repository_paths",
                        missing_binding=f"an approver in {audience or 'an audience'}",
                        message=f"no approver holds the audience for the grant of {g.get('asset')}",
                        check="quorum",
                    )

    return grant_quorum_check


def grant_policy(
    governed: Mapping[str, dict],
    *,
    holders: Callable[[str], set[str]],
    domain_of: Callable[[Mapping], str | None],
    signer,
    committer_name: str,
    committer_email: str,
    customer_terms: list[str] | None,
    grant_sync,
    asset_exists: Callable[[str], bool],
    extra_checks: Iterable[Callable[["repo_core.Repo", dict], None]] = (),
) -> "repo_core.Policy":
    """The ONE way the service builds its Policy: the grant quorum and the appliable-rows check are
    always in it (ruled D5). ``extra_checks`` may add checks; none can remove those two.
    """
    return repo_core.Policy(
        governed=dict(governed),
        customer_terms=customer_terms,
        signer=signer,
        committer_name=committer_name,
        committer_email=committer_email,
        extra_checks=[
            grant_quorum(governed, holders=holders, domain_of=domain_of),
            grant_rows_appliable(grant_sync, asset_exists=asset_exists),
            *extra_checks,
        ],
    )


# --------------------------------------------------------------------------- the merge-time sync


def make_sync_run(
    topaz_url: str, grant_sync_path: Path, *, ledger: Callable[[], Iterable[Mapping]]
) -> Callable[[dict], object]:
    """``policy/sync/grant_sync.run`` bound to the directory, ADD-ONLY (``prune=False``).

    The set it applies is the EFFECTIVE one: the committed rows it is handed plus the ledger's grants
    minus the ledger's revocations (``grant_sync.union_grants``), read through ``ledger()`` at each
    apply. A stale ledger grant is skipped alone (``ledger_keys``); a dangling committed row still
    refuses (exit 3), which ``grant_rows_appliable`` keeps from merging.

    ``ledger`` is REQUIRED, with no default: an empty default would apply the committed rows alone and
    re-add every revoked grant, silently. A caller with no ledger says so (``ledger=lambda: ()``).

    Fails closed (``load_grant_sync``): a grant_sync that cannot be told to stay add-only is refused
    rather than called (the seed CronJob is the one pruner).
    """
    mod = load_grant_sync(grant_sync_path)

    def sync(raw: dict):
        rows = [dict(r) for r in ledger()]
        effective = mod.union_grants(list(raw.get("grants") or []), rows)
        return mod.run(
            {**raw, "grants": effective}, topaz_url, prune=False, ledger_keys=mod.ledger_grant_keys(rows)
        )

    return sync


def apply_on_merge(repo: "repo_core.Repo", merged: Mapping, sync_run: Callable[[dict], object]) -> object | None:
    """After a merge that touched the grants file, apply the file at the merge sha, add-only.

    Returns the sync's result, or None when the merge did not touch the grants file.

    ``sync_run`` must be the one ``make_sync_run`` built with the ledger (it applies the EFFECTIVE set: committed
    rows plus ledger grants minus ledger revocations). A bare callable that ignores the ledger re-adds revoked grants.
    """
    new = merged["new"]
    old = merged["old"]
    diff = repo._r[old].tree.diff_to_tree(repo._r[new].tree)
    if GRANTS_PATH not in repo._paths_of(diff):
        return None
    text = _blob_text(repo, new, GRANTS_PATH)
    return sync_run({"grants": _grants_of(text)})
