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
GS = gf.load_grant_sync(Path(__file__).resolve().parents[2] / "policy/sync/grant_sync.py")
GONE = "urn:li:dataset:(a,asset-gone,PROD)"
EXISTING = {DATASET, OTHER, "urn:li:dataset:(a,asset-c,PROD)"}
CFG = gf.TargetConfig("any-repo-id", "unused", REF)


def holders(aud):
    return set(HOLDERS.get(aud, ()))


def domain_of(row):
    return DOMAINS.get(row["asset"])


def asset_exists(asset):
    return asset in EXISTING


def production_policy(signer, rail=None):
    return gf.grant_policy(
        rail or RAIL, holders=holders, domain_of=domain_of, signer=signer, committer_name="engine-r",
        committer_email="engine-r@engine-r.invalid", customer_terms=["zz-acme-test"],
        grant_sync=GS, asset_exists=asset_exists,
    )


@pytest.fixture
def w(tmp_path):
    src = pygit2.init_repository(str(tmp_path / "src.git"), bare=True, initial_head="trunk")
    commit_files(src, {"policy/asset_grants.yaml": HEADER.encode(), "policy/x.yaml": b"a: 1\n"}, [], REF)
    signer = sshsig.Signer.generate()
    policy = production_policy(signer)
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
    {"subject": "alice", "asset": DATASET, "kind": "dataset", "entry": "grant", "granted_by": "dana",
     "requested_by": "alice", "reason": "r"},
    {"subject": "carol", "asset": "urn:li:dataset:(a,asset-c,PROD)", "kind": "dataset", "entry": "grant",
     "granted_by": "x", "requested_by": "carol", "reason": "r"},
]


def backfill(w, ledger=None, service=SERVICE, exists=asset_exists):
    return gf.backfill_ledger(
        w.repo, cfg=CFG, ledger=LEDGER if ledger is None else ledger, service=service,
        grant_sync=GS, asset_exists=exists,
    )


def revoke_row(subject="alice", asset=DATASET, by="rita"):
    return {"subject": subject, "asset": asset, "kind": "dataset", "entry": "revoke", "granted_by": by,
            "requested_by": by, "reason": "gone"}


def test_4_only_ledger_rows_policy_does_not_name_are_proposed(w):
    out = backfill(w)
    assert len(out) == 1 and out[0]["excluded"] == sorted({"alice", SERVICE.authz_id})


def test_4_a_backfill_is_filed_by_service_and_names_the_original_approver(w):
    (m,) = backfill(w)
    assert m["auth_via"] == "service" and "approved by dana" in m["intent"]
    commit = w.repo._r[m["head_sha"]]
    assert repo_core.parse_trailers(commit.message)["Auth-Via"] == "service"


def test_4_the_original_approver_is_not_an_approval(w):
    (m,) = backfill(w)
    refuses(w, m, ["dana"], 409, "too_few_approvers")                        # reviewed like any proposal


def test_4_a_backfill_by_a_person_is_refused(w):
    with pytest.raises(ValueError):
        backfill(w, service=Caller("someone", "local"))


def test_4_once_merged_the_backfill_finds_nothing_left(w):
    (m,) = backfill(w)
    merge(w, m, ["dana", "pat"])
    assert backfill(w) == []


# 5. apply ---------------------------------------------------------------------------------------

def _fake_grant_sync(tmp, with_prune):
    sig = "*, prune=True" if with_prune else "*"
    rec = "prune" if with_prune else "None"
    p = tmp / "gs.py"
    p.write_text(textwrap.dedent(f"""
        CALLS = []
        def run(raw, topaz_url, {sig}, ledger_keys=frozenset()):
            CALLS.append((raw, topaz_url, {rec}))
            return 0
        def union_grants(committed, ledger):
            return list(committed)
        def find_dangling(*a, **k):
            return []
        def ledger_grant_keys(ledger):
            return frozenset()
        def load_grants(raw):
            return [], []
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
    assert "prune" in text.split("def run(", 1)[1].split(")", 1)[0], "grant_sync.run must carry the prune switch"
    gf.make_sync_run("topaz.invalid:1", p)                       # loads: it is not refused


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


# 7. the production constructor and the fail-closed rail -------------------------------------------

def _world(tmp_path, rail):
    src = pygit2.init_repository(str(tmp_path / "s2.git"), bare=True, initial_head="trunk")
    commit_files(src, {"policy/asset_grants.yaml": HEADER.encode(), "policy/x.yaml": b"a: 1\n"}, [], REF)
    repo = repo_core.Repo.init_bare(tmp_path / "e2.git", CFG.repo_id, production_policy(sshsig.Signer.generate(), rail))
    repo.import_from(str(tmp_path / "s2.git"))
    return SimpleNamespace(repo=repo, tmp=tmp_path)


def test_7_a_policy_built_by_the_constructor_refuses_a_one_approver_grant_merge(tmp_path):
    w2 = _world(tmp_path, RAIL)
    refuses(w2, file(w2), ["dana"], 409, "too_few_approvers")


def test_7_extra_checks_can_add_but_not_remove_the_quorum():
    pol = production_policy(sshsig.Signer.generate())
    assert [f.__name__ for f in pol.extra_checks] == ["grant_quorum_check", "grant_rows_appliable_check"]


def test_7_a_matching_row_without_approvers_fails_closed(tmp_path):
    rail = {"policy/asset_grants.yaml": {"review": "access_grant:<DOMAIN>", "unmatched_review": "repo_review:POLICY"},
            "policy/": {"review": "repo_review:POLICY", "approvers": 2}}
    w2 = _world(tmp_path, rail)
    refuses(w2, file(w2), ["dana"], 409, "rail_row_without_approvers")
    refuses(w2, file(w2), ["dana", "pat"], 409, "rail_row_without_approvers")   # even a full quorum


def test_7_control_the_same_row_with_approvers_merges_two(tmp_path):
    w2 = _world(tmp_path, RAIL)
    merge(w2, file(w2), ["dana", "pat"])


# 8. revocations: the effective set, never the raw ledger (gov, #414 finding 2) -------------------

CAROL = "urn:li:dataset:(a,asset-c,PROD)"           # committed in HEADER


def test_8_a_revocation_row_is_never_proposed_as_a_grant(w):
    out = backfill(w, ledger=[revoke_row("alice", DATASET)])
    assert out == []


def test_8_a_grant_its_own_ledger_revokes_is_not_proposed(w):
    out = backfill(w, ledger=[LEDGER[0], revoke_row("alice", DATASET)])
    assert out == []


def test_8_control_a_revocation_of_another_grant_leaves_this_one_proposed(w):
    out = backfill(w, ledger=[LEDGER[0], revoke_row("bob", OTHER)])
    assert len(out) == 1 and "ledger row alice" in out[0]["intent"]


def _bound(w, ledger, monkeypatch):
    seen = []
    sync = gf.make_sync_run("topaz.invalid:1", ROOT / "policy/sync/grant_sync.py", ledger=lambda: ledger)

    def fake_run(raw, url, *, prune=True, ledger_keys=frozenset(), **k):
        seen.append((raw, prune, ledger_keys))
        return 0

    monkeypatch.setattr(sys.modules["_engine_r_grant_sync"], "run", fake_run)
    return sync, seen


def test_8_a_merge_does_not_re_add_a_committed_grant_the_ledger_revoked(w, monkeypatch):
    out = merge(w, file(w, requester="rita"), ["dana", "pat"])
    sync, seen = _bound(w, [revoke_row("carol", CAROL)], monkeypatch)
    gf.apply_on_merge(w.repo, out, sync)
    (raw, prune, _keys), = seen
    assert prune is False
    assert {(g["subject"], g["asset"]) for g in raw["grants"]} == {("alice", DATASET)}      # carol is gone


def test_8_control_with_no_revocation_the_committed_grant_applies_and_ledger_keys_are_passed(w, monkeypatch):
    out = merge(w, file(w, requester="rita"), ["dana", "pat"])
    sync, seen = _bound(w, [LEDGER[1]], monkeypatch)           # carol: a ledger grant already committed
    gf.apply_on_merge(w.repo, out, sync)
    (raw, _prune, keys), = seen
    assert {(g["subject"], g["asset"]) for g in raw["grants"]} == {("alice", DATASET), ("carol", CAROL)}
    assert keys == frozenset({("carol", CAROL, "dataset")})


def test_8_a_grant_sync_without_union_is_refused_not_called(w):
    p = _fake_grant_sync(w.tmp, True)
    p.write_text(p.read_text(encoding="utf-8").replace("def union_grants", "def not_union"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="union_grants"):
        gf.make_sync_run("topaz.invalid:1", p)


def test_8_the_requester_on_the_ledger_row_is_excluded_not_only_the_subject(w):
    row_ = {**LEDGER[0], "requested_by": "rita"}
    (m,) = backfill(w, ledger=[row_])
    assert m["excluded"] == sorted({"alice", "rita", SERVICE.authz_id})


# 9. a row that could never apply does not merge (gov, #414 finding 1) ----------------------------

def test_9_a_grant_row_whose_asset_is_not_in_the_directory_is_refused_at_merge(w):
    m = file(w, rows=[row(asset=GONE)], requester="rita")
    err = refuses(w, m, ["dana", "pat"], 409, "grant_row_unappliable")
    assert "asset-gone" in str(err.message) or "asset-gone" in str(err)


def test_9_control_the_same_row_on_an_existing_asset_merges(w):
    merge(w, file(w, rows=[row(asset=OTHER)], requester="rita"), ["pat", "quinn"])


def test_9_a_malformed_grant_row_is_refused_at_merge(w):
    m = file(w, rows=[{"subject": "alice", "asset": DATASET, "reason": "no granted_by"}], requester="rita")
    refuses(w, m, ["dana", "pat"], 409, "grant_row_unappliable")


NL = chr(10)


def test_9_a_committed_dangling_row_does_not_block_a_good_row_added_later(w):
    src_policy = production_policy(sshsig.Signer.generate())
    # a repo whose committed file already holds the dangling row (it predates the check)
    s2 = pygit2.init_repository(str(w.tmp / "s3.git"), bare=True, initial_head="trunk")
    text = HEADER + "  - subject: dan" + NL + "    asset: " + GONE + NL + "    granted_by: x" + NL + "    reason: r" + NL
    commit_files(s2, {"policy/asset_grants.yaml": text.encode(), "policy/x.yaml": b"a: 1" + NL.encode()}, [], REF)
    repo = repo_core.Repo.init_bare(w.tmp / "e3.git", CFG.repo_id, src_policy)
    repo.import_from(str(w.tmp / "s3.git"))
    w3 = SimpleNamespace(repo=repo, tmp=w.tmp)
    merge(w3, file(w3, rows=[row(asset=OTHER)], requester="rita"), ["pat", "quinn"])


def test_9_a_backfill_skips_a_ledger_grant_whose_asset_is_gone_and_proposes_the_rest(w):
    gone = {**LEDGER[0], "subject": "erin", "asset": GONE}
    out = backfill(w, ledger=[gone, LEDGER[0]])
    assert len(out) == 1 and "ledger row alice" in out[0]["intent"]
