"""The access-grant path through engine-r (ADR-0062 s5/s6; rulings D5-D8, 2026-11-16). Doubles only.

  1. TARGET     comes from configuration only; nothing names a repository, org or URL in code.
  2. EXCLUSION  {proposer, requester, grantee} by authz_id is carried by propose and refused at merge.
  3. QUORUM     two distinct approvers on asset_grants.yaml, one holding each changed row's audience.
  4. BACKFILL   ledger decisions not in policy become service-filed proposals; original approver named.
  5. APPLY      the merge-time sync is add-only and only when the grants file changed.
  6. END TO END propose -> two reviews -> merge -> add-only apply.
"""
from __future__ import annotations

import ast
import re
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pygit2
import pytest

from agent_fleet.repository_agent import grant_flow as gf
from agent_fleet.repository_agent import repo_core, sshsig
from agent_fleet.repository_agent.repo_core import Caller, RepoRefusal
from engine_r_fixtures import COMPLETER, approval, commit_files, state_of

ROOT = Path(__file__).resolve().parents[2]
REF = "refs/heads/trunk"
DATASET = "urn:li:dataset:(a,asset-a,PROD)"
OTHER = "urn:li:dataset:(a,asset-b,PROD)"
HEADER = (
    "# header comment kept\ngrants:\n  - subject: carol\n    asset: urn:li:dataset:(a,asset-c,PROD)\n"
    "    granted_by: seed\n    reason: seed\n"
)
RAIL = {
    "policy/asset_grants.yaml": {
        "review": "access_grant:<DOMAIN>", "unmatched_review": "repo_review:POLICY", "approvers": 2,
    },
    "policy/": {"review": "repo_review:POLICY", "approvers": 2},
}
HOLDERS = {"access_grant:ENG": {"dana", "erin"}, "repo_review:POLICY": {"pat", "quinn"}}
DOMAINS = {DATASET: "ENG", OTHER: None}
SERVICE = Caller("engine-r-requests", "service")
CFG = gf.TargetConfig("any-repo-id", "unused", REF)


def holders(aud):
    return set(HOLDERS.get(aud, ()))


def domain_of(row):
    return DOMAINS.get(row["asset"])


@pytest.fixture
def w(tmp_path):
    src = pygit2.init_repository(str(tmp_path / "src.git"), bare=True, initial_head="trunk")
    commit_files(src, {"policy/asset_grants.yaml": HEADER.encode(), "policy/x.yaml": b"a: 1\n"}, [], REF)
    signer = sshsig.Signer.generate()
    policy = repo_core.Policy(
        governed=dict(RAIL), customer_terms=["zz-acme-test"], signer=signer, committer_name="engine-r",
        committer_email="engine-r@engine-r.invalid",
        extra_checks=[gf.grant_quorum(RAIL, holders=holders, domain_of=domain_of)],
    )
    repo = repo_core.Repo.init_bare(tmp_path / "engine.git", CFG.repo_id, policy)
    repo.import_from(str(tmp_path / "src.git"))
    return SimpleNamespace(repo=repo, tmp=tmp_path)


def row(subject="alice", asset=DATASET, by="dana"):
    return {"subject": subject, "asset": asset, "granted_by": by, "reason": "need"}


def file(w, rows=None, requester="alice", proposer=SERVICE):
    return gf.propose_grants(
        w.repo, cfg=CFG, rows=rows or [row()], requester=requester, proposer=proposer, intent="why"
    )


def merge(w, meta, who):
    return w.repo.merge(
        proposal_id=meta["id"], reviewed_sha=meta["head_sha"],
        approvals=[approval(meta["head_sha"], p, "t-" + p) for p in who], completes=COMPLETER,
    )


def refuses(w, meta, who, status, error):
    before = state_of(w.repo, REF)
    with pytest.raises(RepoRefusal) as ei:
        merge(w, meta, who)
    assert (ei.value.status, ei.value.error) == (status, error)
    assert state_of(w.repo, REF) == before
    return ei.value


# 1. target --------------------------------------------------------------------------------------

def test_1_the_target_comes_from_configuration_only():
    env = {"ENGINE_R_TARGET_REPO_ID": " r ", "ENGINE_R_TARGET_REPO_PATH": "/p", "ENGINE_R_TARGET_REF": "refs/heads/m"}
    assert gf.TargetConfig.from_env(env) == gf.TargetConfig("r", "/p", "refs/heads/m")


@pytest.mark.parametrize("drop", list(gf.TargetConfig.ENV.values()))
def test_1_a_missing_setting_is_refused_and_named_never_defaulted(drop):
    env = {"ENGINE_R_TARGET_REPO_ID": "r", "ENGINE_R_TARGET_REPO_PATH": "/p", "ENGINE_R_TARGET_REF": "x"}
    del env[drop]
    with pytest.raises(gf.TargetNotConfigured, match=drop):
        gf.TargetConfig.from_env(env)
    env[drop] = "   "
    with pytest.raises(gf.TargetNotConfigured, match=drop):
        gf.TargetConfig.from_env(env)


NAMES = re.compile(r"invincible-agent|edgy|github\.com|https?://|\.git\b", re.I)


def _string_literals(src: str) -> list[str]:
    return [n.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_1_no_repository_org_or_url_is_named_in_code():
    src = (ROOT / "agent_fleet/repository_agent/grant_flow.py").read_text(encoding="utf-8")
    assert [s for s in _string_literals(src) if NAMES.search(s)] == []


def test_1_control_the_detector_fires_on_a_named_repository():
    bad = 'REPO = "invincible-agent-mirror"\nURL = "https://example.invalid/x"\n'
    assert len([s for s in _string_literals(bad) if NAMES.search(s)]) == 2


# 2. exclusion -----------------------------------------------------------------------------------

def test_2_propose_carries_proposer_requester_and_grantee(w):
    m = file(w, rows=[row("alice"), row("bob")], requester="rita")
    assert m["excluded"] == sorted({SERVICE.authz_id, "rita", "alice", "bob"})
    assert m["proposer"] == SERVICE.authz_id and m["auth_via"] == "service"


@pytest.mark.parametrize("who", ["rita", "alice"])
def test_2_the_requester_and_the_grantee_cannot_approve_even_when_filed_by_a_service(w, who):
    m = file(w, requester="rita")
    refuses(w, m, [who, "dana"], 403, "approver_is_excluded")


def test_2_control_two_other_people_approve(w):
    m = file(w, requester="rita")
    out = merge(w, m, ["dana", "pat"])
    assert out["note"]["approvers"] == ["dana", "pat"]


# 3. quorum --------------------------------------------------------------------------------------

def test_3_one_approver_is_not_enough_on_the_grants_file(w):
    refuses(w, file(w), ["dana"], 409, "too_few_approvers")


def test_3_the_same_person_twice_is_one_approver(w):
    refuses(w, file(w), ["dana", "dana"], 409, "too_few_approvers")


def test_3_two_approvers_none_in_the_rows_audience_is_refused(w):
    refuses(w, file(w), ["pat", "quinn"], 403, "no_approver_in_audience")   # policy reviewers, not ENG


def test_3_control_one_in_the_audience_plus_any_second_reviewer_merges(w):
    merge(w, file(w), ["erin", "zed"])


def test_3_a_row_with_no_domain_falls_to_the_unmatched_audience(w):
    m = file(w, rows=[row("alice", OTHER)])
    refuses(w, m, ["dana", "erin"], 403, "no_approver_in_audience")         # ENG holders; row has no domain
    merge(w, m, ["dana", "pat"])                                             # pat holds repo_review:POLICY


def test_3_every_changed_row_needs_its_own_audience_member(w):
    m = file(w, rows=[row("alice", DATASET), row("bob", OTHER)])
    refuses(w, m, ["dana", "erin"], 403, "no_approver_in_audience")         # nobody for the unmatched row
    merge(w, m, ["dana", "pat"])


def test_3_append_keeps_the_header_and_is_idempotent():
    out = gf.append_grants(HEADER, [row()])
    assert out.startswith("# header comment kept") and len(gf._grants_of(out)) == 2
    assert gf.append_grants(out, [row()]) == out


def test_3_append_refuses_a_file_whose_grants_are_not_last():
    with pytest.raises(ValueError):
        gf.append_grants("grants:\n  - subject: c\n    asset: a\nother: 1\n", [row()])


# 4. backfill ------------------------------------------------------------------------------------

LEDGER = [
    {"subject": "alice", "asset": DATASET, "kind": "dataset", "granted_by": "dana", "reason": "r"},
    {"subject": "carol", "asset": "urn:li:dataset:(a,asset-c,PROD)", "kind": "dataset", "granted_by": "x",
     "reason": "r"},
]


def test_4_only_ledger_rows_policy_does_not_name_are_proposed(w):
    out = gf.backfill_ledger(w.repo, cfg=CFG, ledger=LEDGER, service=SERVICE)
    assert len(out) == 1 and out[0]["excluded"] == sorted({"alice", SERVICE.authz_id})


def test_4_a_backfill_is_filed_by_service_and_names_the_original_approver(w):
    (m,) = gf.backfill_ledger(w.repo, cfg=CFG, ledger=LEDGER, service=SERVICE)
    assert m["auth_via"] == "service" and "approved by dana" in m["intent"]
    commit = w.repo._r[m["head_sha"]]
    assert repo_core.parse_trailers(commit.message)["Auth-Via"] == "service"


def test_4_the_original_approver_is_not_an_approval(w):
    (m,) = gf.backfill_ledger(w.repo, cfg=CFG, ledger=LEDGER, service=SERVICE)
    refuses(w, m, ["dana"], 409, "too_few_approvers")                        # reviewed like any proposal


def test_4_a_backfill_by_a_person_is_refused(w):
    with pytest.raises(ValueError):
        gf.backfill_ledger(w.repo, cfg=CFG, ledger=LEDGER, service=Caller("someone", "local"))


def test_4_once_merged_the_backfill_finds_nothing_left(w):
    (m,) = gf.backfill_ledger(w.repo, cfg=CFG, ledger=LEDGER, service=SERVICE)
    merge(w, m, ["dana", "pat"])
    assert gf.backfill_ledger(w.repo, cfg=CFG, ledger=LEDGER, service=SERVICE) == []


# 5. apply ---------------------------------------------------------------------------------------

def _fake_grant_sync(tmp, with_prune):
    sig = "*, prune=True" if with_prune else ""
    rec = "prune" if with_prune else "None"
    p = tmp / "gs.py"
    p.write_text(textwrap.dedent(f"""
        CALLS = []
        def run(raw, topaz_url, {sig}):
            CALLS.append((raw, topaz_url, {rec}))
            return 0
    """), encoding="utf-8")
    return p


def test_5_the_bound_sync_passes_prune_false(w):
    run = gf.make_sync_run("topaz.invalid:1", _fake_grant_sync(w.tmp, True))
    run({"grants": []})
    (call,) = sys.modules["_engine_r_grant_sync"].CALLS
    assert call == ({"grants": []}, "topaz.invalid:1", False)


def test_5_a_grant_sync_with_no_prune_switch_is_refused_not_called(w):
    with pytest.raises(RuntimeError, match="prune"):
        gf.make_sync_run("topaz.invalid:1", _fake_grant_sync(w.tmp, False))


def test_5_the_real_grant_sync_is_add_only_or_refused():
    p = ROOT / "policy/sync/grant_sync.py"
    text = p.read_text(encoding="utf-8")
    has_prune = "def run(" in text and "prune" in text.split("def run(", 1)[1].split(")", 1)[0]
    if has_prune:
        gf.make_sync_run("topaz.invalid:1", p)
    else:
        with pytest.raises(RuntimeError):
            gf.make_sync_run("topaz.invalid:1", p)


def test_5_a_merge_that_leaves_the_grants_file_alone_applies_nothing(w):
    m = w.repo.propose(caller=SERVICE, target_ref=REF, changes={"policy/x.yaml": b"a: 2\n"}, intent="i", message="m")
    out = merge(w, m, ["pat", "quinn"])
    calls = []
    assert gf.apply_on_merge(w.repo, out, calls.append) is None and calls == []


# 6. end to end ----------------------------------------------------------------------------------

def test_6_propose_review_merge_apply(w):
    m = file(w, requester="rita")
    out = merge(w, m, ["dana", "pat"])
    seen = []
    gf.apply_on_merge(w.repo, out, lambda raw: seen.append(raw) or 0)
    (raw,) = seen
    assert {(g["subject"], g["asset"]) for g in raw["grants"]} == {
        ("carol", "urn:li:dataset:(a,asset-c,PROD)"), ("alice", DATASET)}
    assert w.repo.audit(path=gf.GRANTS_PATH)[0]["approvers"] == ["dana", "pat"]
