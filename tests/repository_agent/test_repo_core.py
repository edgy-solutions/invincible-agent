"""engine-r core (ADR-0062 section 2): the seals. No git binary here; pygit2 is the only reader."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pygit2
import pytest

from agent_fleet.repository_agent import repo_core
from agent_fleet.repository_agent.repo_core import RepoRefusal
from engine_r_fixtures import COMPLETER, PROPOSER, approval, make_policy, state_of

MASTER = "refs/heads/master"
NOTE_KEYS = {
    "repo", "ref", "old", "new", "verb", "on_behalf_of", "auth_via", "proposal",
    "review_task_ids", "approvers", "checks", "at",
}


def propose(w, changes, caller=PROPOSER, message="change"):
    return w.repo.propose(caller=caller, target_ref=MASTER, changes=changes, intent="why", message=message)


def merge(w, meta, approvals=None, reviewed=None):
    return w.repo.merge(
        proposal_id=meta["id"],
        reviewed_sha=reviewed or meta["head_sha"],
        approvals=[approval(meta["head_sha"])] if approvals is None else approvals,
        completes=COMPLETER,
    )


def refuses(w, meta, status, error, **kw):
    before = state_of(w.repo)
    with pytest.raises(RepoRefusal) as ei:
        merge(w, meta, **kw)
    assert (ei.value.status, ei.value.error) == (status, error)
    assert state_of(w.repo) == before, "a refusal moved a ref or wrote a note"
    return ei.value


def walk_count(repo, ref):
    return sum(1 for _ in repo._r.walk(pygit2.Oid(hex=repo._read_tip(ref)), pygit2.GIT_SORT_TOPOLOGICAL))


# 1 -------------------------------------------------------------------------------------------


def test_import_keeps_every_sha_and_counts_the_history(world):
    src = world.source.repo
    want = {n: str(src.references[n].target) for n in src.references if n.startswith(("refs/heads/", "refs/tags/"))}
    assert world.imported["refs"] == want
    assert world.imported["head"] == world.source.merge
    assert world.imported["commit_count"] == 4


# 2 -------------------------------------------------------------------------------------------


def test_propose_signs_trailers_and_records_a_one_commit_meta_chain(world):
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    r = world.repo
    head = r._r[meta["head_sha"]]
    assert repo_core.parse_trailers(head.message) == {
        "On-Behalf-Of": "lane-a", "Auth-Via": "local", "Proposal": meta["id"],
    }
    assert len(head.message.strip().split("\n\n")[-1].splitlines()) == 3
    assert head.author.name == "lane-a" and head.author.email == "lane-a@users.engine-r.invalid"
    assert head.committer.name == "engine-r"
    assert r._read_tip("refs/proposals/" + meta["id"]) == meta["head_sha"]
    assert walk_count(r, "refs/proposal-meta/" + meta["id"]) == 1
    assert r.proposal(meta["id"])["state"] == "open"
    assert state_of(r)[1] is None, "proposing wrote an audit note"
    assert r._read_tip(MASTER) == world.source.merge, "proposing moved the target"


# 3 -------------------------------------------------------------------------------------------


def test_a_happy_merge_is_a_two_parent_signed_audited_commit(world):
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    old = world.repo._read_tip(MASTER)
    out = merge(world, meta)
    r = world.repo
    c = r._r[out["merge_sha"]]
    assert [str(p) for p in c.parent_ids] == [old, meta["head_sha"]]
    assert r._read_tip(MASTER) == out["merge_sha"]
    assert NOTE_KEYS <= set(out["note"])
    note = r._read_note(out["merge_sha"])
    assert note == out["note"] and NOTE_KEYS <= set(note)
    assert note["old"] == old and note["new"] == out["merge_sha"] and note["verb"] == "merge"
    assert note["review_task_ids"] == ["task-1"] and note["approvers"] == ["reviewer-1"]
    assert all(v == "pass" for v in note["checks"].values())
    assert {"check1", "check3", "check4", "check5", "check6"} <= set(note["checks"])
    assert r.audit(proposal_id=meta["id"]) == [note]
    assert r.audit(ref=MASTER)[0] == note
    assert r.audit(path="policy/x.yaml")[0] == note
    assert r.proposal(meta["id"])["state"] == "merged"
    assert r.proposal(meta["id"])["merge_sha"] == out["merge_sha"]
    assert repo_core.parse_trailers(c.message)["On-Behalf-Of"] == "engine-r"


# 4 -------------------------------------------------------------------------------------------


def test_a_closed_proposal_cannot_merge_again(world):
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    merge(world, meta)
    e = refuses(world, meta, 409, "proposal_closed")
    assert e.policy_id == "code"


def test_a_merge_names_the_head_it_reviewed(world):
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    refuses(world, meta, 409, "reviewed_sha_is_not_head", reviewed=world.source.c1)


def test_an_unknown_proposal_is_409(world):
    with pytest.raises(RepoRefusal) as ei:
        world.repo.merge(proposal_id="nope", reviewed_sha="0" * 40, approvals=[], completes=COMPLETER)
    assert (ei.value.status, ei.value.error) == (409, "unknown_proposal")


# 5 / 6 ---------------------------------------------------------------------------------------


def test_the_proposer_cannot_approve(world):
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    e = refuses(world, meta, 403, "proposer_cannot_approve", approvals=[approval(meta["head_sha"], who="lane-a")])
    assert e.missing_binding == "the dropper rule"


def test_an_approval_of_another_sha_does_not_count(world):
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    refuses(world, meta, 409, "approval_of_another_sha", approvals=[approval(world.source.c1)])


def test_a_merge_with_no_approval_is_refused(world):
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    refuses(world, meta, 409, "no_approval", approvals=[])


# 7 / 8 ---------------------------------------------------------------------------------------


def test_a_path_no_row_governs_is_refused_with_the_policy_envelope(world):
    meta = propose(world, {"src/app.py": b"print('x')\n"})
    e = refuses(world, meta, 403, "path_not_governed")
    assert e.policy_id == "repository_paths"
    assert e.message == "path not governed by engine-r"
    assert e.missing_binding == "a row covering src/app.py"


def test_a_delete_outside_the_rows_is_refused_too(world):
    meta = propose(world, {"src/app.py": None})
    refuses(world, meta, 403, "path_not_governed")


def test_the_rail_cannot_widen_check_6(signer):
    with pytest.raises(ValueError):
        make_policy(signer, governed={"src/": {"review": "x"}})
    with pytest.raises(ValueError):
        make_policy(signer, governed={"policy/../src/": {"review": "x"}})
    make_policy(signer, governed={"docs/adr/": {}, "tests/fixtures/": {}, "policy/": {}, "sessions/": {}})


# 9 -------------------------------------------------------------------------------------------

SECRET_LINES = [
    b"-----BEGIN OPENSSH PRIVATE KEY-----\n",
    b"t: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlMTIz\n",
    b"k: AKIAABCDEFGHIJKLMNOP\n",
    b"password: hunter2hunter2\n",
]


@pytest.mark.parametrize("line", SECRET_LINES)
def test_a_secret_in_the_diff_is_refused_and_not_echoed(world, line):
    meta = propose(world, {"policy/x.yaml": b"a: 1\n" + line})
    e = refuses(world, meta, 403, "secret_in_diff")
    assert line.decode().strip() not in e.message
    assert "policy/x.yaml" in e.message and "line 2" in e.message


@pytest.mark.parametrize(
    "line", [b"password: <redacted-value>\n", b"token: ${TOKEN_VALUE}\n", b"secret: changeme\n", b"password: short\n"]
)
def test_a_placeholder_is_not_a_secret(world, line):
    meta = propose(world, {"policy/x.yaml": b"a: 1\n" + line})
    merge(world, meta)


# 10 ------------------------------------------------------------------------------------------


def test_absent_customer_terms_fail_closed(world):
    world.policy.customer_terms = None
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    refuses(world, meta, 403, "customer_terms_absent")


def test_a_customer_term_in_the_diff_is_refused_and_not_echoed(world):
    meta = propose(world, {"sessions/a.md": b"packet a\nvisit ZZ-Acme-Test today\n"})
    e = refuses(world, meta, 403, "customer_context_in_diff")
    assert "zz-acme-test" not in e.message.lower()
    assert "sessions/a.md" in e.message and "line 2" in e.message


def test_a_term_on_a_removed_line_is_not_in_the_diff_additions(world):
    world.repo.policy.customer_terms = ["packet"]
    meta = propose(world, {"sessions/a.md": None})
    merge(world, meta)


# 11 ------------------------------------------------------------------------------------------


def register_foreign_proposal(w, pid, message):
    """Test-only: a proposal whose commit was NOT built by propose(), so it can lack trailers."""
    r = w.repo
    tip = r._read_tip(MASTER)
    index = pygit2.Index()
    index.read_tree(r._r[tip].tree)
    index.add(pygit2.IndexEntry("policy/x.yaml", r._r.create_blob(b"a: 9\n"), pygit2.GIT_FILEMODE_BLOB))
    sig = pygit2.Signature("Foreign", "foreign@example.invalid", 1_700_000_000, 0)
    head = r._r.create_commit(None, sig, sig, message, index.write_tree(r._r), [pygit2.Oid(hex=tip)])
    r._r.create_reference("refs/proposals/" + pid, head)
    meta = {
        "id": pid, "repo": "invincible-agent", "target_ref": MASTER, "base_sha": tip, "head_sha": str(head),
        "intent": "why", "proposer": "lane-a", "auth_via": "local", "state": "open", "created_at": "t",
    }
    r._write_meta(meta)
    return meta


def test_a_commit_without_the_trailers_is_refused(world):
    meta = register_foreign_proposal(world, "foreign000001", "no trailers at all")
    refuses(world, meta, 409, "missing_trailers")


def test_trailers_in_the_first_paragraph_do_not_count(world):
    msg = "On-Behalf-Of: x\nAuth-Via: local\nProposal: p\n\nand then prose, last\n"
    meta = register_foreign_proposal(world, "foreign000002", msg)
    refuses(world, meta, 409, "missing_trailers")


# 12 / 13 -------------------------------------------------------------------------------------


def test_a_moved_target_three_way_merges_when_nothing_conflicts(world):
    a = propose(world, {"policy/x.yaml": b"a: 2\n"})
    b = propose(world, {"sessions/a.md": b"packet a, edited\n"})
    first = merge(world, b)
    second = merge(world, a)
    r = world.repo
    c = r._r[second["merge_sha"]]
    assert [str(p) for p in c.parent_ids] == [first["merge_sha"], a["head_sha"]]
    assert c.tree["policy"]["x.yaml"].data == b"a: 2\n"
    assert c.tree["sessions"]["a.md"].data == b"packet a, edited\n"
    assert r._read_tip(MASTER) == second["merge_sha"]


def test_a_moved_target_that_conflicts_is_refused(world):
    a = propose(world, {"policy/x.yaml": b"a: 2\n"})
    b = propose(world, {"policy/x.yaml": b"a: 3\n"})
    merge(world, b)
    refuses(world, a, 409, "merge_conflict")


# 14 ------------------------------------------------------------------------------------------


def test_a_tip_that_moves_during_the_merge_is_a_cas_refusal_and_the_orphan_is_not_counted(world, monkeypatch):
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    r = world.repo
    real = r._read_tip
    reads = {"n": 0}

    def moving(ref):
        v = real(ref)
        if ref == MASTER:
            reads["n"] += 1
            if reads["n"] >= 2:  # the read in step 8 is the first; the compare before the swap is later
                return "f" * 40
        return v

    notes_before = r._read_tip(repo_core.AUDIT_REF)
    monkeypatch.setattr(r, "_read_tip", moving)
    with pytest.raises(RepoRefusal) as ei:
        merge(world, meta)
    assert (ei.value.status, ei.value.error) == (409, "target_moved")
    monkeypatch.undo()
    assert r._read_tip(MASTER) == world.source.merge
    assert r._read_tip(repo_core.AUDIT_REF) == notes_before, "a refusal writes no note, even after the CAS"
    assert r.audit(proposal_id=meta["id"]) == [], "the withdrawn note is not an audit record"
    assert r.proposal(meta["id"])["state"] == "open"
    assert r.unaudited_merges(MASTER) == [world.source.merge]


# 15 ------------------------------------------------------------------------------------------


def test_a_release_tag_never_moves_except_by_a_logged_repair(world):
    r, sha = world.repo, world.source.c1
    out = r.tag(name="invincible-agent-1.0.0", sha=sha, caller=COMPLETER, approvals=[approval(sha)], release=True)
    ref = "refs/tags/invincible-agent-1.0.0"
    assert r._read_tip(ref) == out["tag_object"]
    assert out["note"]["verb"] == "tag" and r._read_note(out["tag_object"]) == out["note"]
    body = r._r[out["tag_object"]].message.split("-----BEGIN SSH SIGNATURE-----")[0]
    assert repo_core.parse_trailers(body)["On-Behalf-Of"] == "engine-r"
    assert "-----BEGIN SSH SIGNATURE-----" in r._r[out["tag_object"]].message
    before = state_of(r, ref)
    with pytest.raises(RepoRefusal) as ei:
        r.tag(name="invincible-agent-1.0.0", sha=sha, caller=COMPLETER, approvals=[approval(sha)], release=True)
    assert (ei.value.status, ei.value.error, ei.value.check) == (409, "release_tag_immutable", "check2")
    assert state_of(r, ref) == before

    other = world.source.c2
    with pytest.raises(ValueError):
        r.repair_tag(name="invincible-agent-1.0.0", sha=other, caller=COMPLETER, approvals=[approval(other)], reason="  ")
    assert state_of(r, ref) == before
    rep = r.repair_tag(
        name="invincible-agent-1.0.0", sha=other, caller=COMPLETER, approvals=[approval(other)], reason="tagged the wrong sha"
    )
    assert r._read_tip(ref) == rep["tag_object"] != out["tag_object"]
    note = r._read_note(rep["tag_object"])
    assert note["verb"] == "repair_tag" and note["reason"] == "tagged the wrong sha"
    assert note["old"] == out["tag_object"]
    assert r._r[rep["tag_object"]].target == pygit2.Oid(hex=other)


def test_a_tag_approval_must_name_the_tagged_sha(world):
    r, sha = world.repo, world.source.c1
    with pytest.raises(RepoRefusal) as ei:
        r.tag(name="t1", sha=sha, caller=COMPLETER, approvals=[approval(world.source.c2)], release=False)
    assert ei.value.error == "approval_of_another_sha"
    with pytest.raises(RepoRefusal) as ei:
        r.tag(name="t1", sha=sha, caller=COMPLETER, approvals=[], release=False)
    assert ei.value.error == "no_approval"
    assert r._read_tip("refs/tags/t1") is None


def test_a_caller_cannot_forge_a_trailer(signer):
    from agent_fleet.repository_agent.repo_core import Caller

    for bad in ("a\nAuth-Via: local", "a<b", "", " a"):
        with pytest.raises(ValueError):
            Caller(bad, "local")
    for bad in ("remote", "brokered:", "local\n"):
        with pytest.raises(ValueError):
            Caller("a", bad)
    Caller("a", "brokered:corp-idp")


# 16 ------------------------------------------------------------------------------------------


def test_unaudited_merges_lists_only_what_predates_the_import(world):
    r = world.repo
    assert r.unaudited_merges(MASTER) == [world.source.merge]
    merge(world, propose(world, {"policy/x.yaml": b"a: 2\n"}))
    assert r.unaudited_merges(MASTER) == [world.source.merge]


def test_a_merge_with_its_note_removed_is_found(world):
    r = world.repo
    out = merge(world, propose(world, {"policy/x.yaml": b"a: 2\n"}))
    r._r.lookup_note(out["merge_sha"], repo_core.AUDIT_REF)  # exists
    sig = r._committer_sig()
    r._r.lookup_note(out["merge_sha"], repo_core.AUDIT_REF).remove(sig, sig, repo_core.AUDIT_REF)
    assert r.unaudited_merges(MASTER) == [out["merge_sha"], world.source.merge]


# 17 ------------------------------------------------------------------------------------------

_PKG = Path(repo_core.__file__).parent


def shell_outs(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] in ("subprocess", "pty")]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in ("subprocess", "pty"):
            found.append(node.module)
        elif isinstance(node, ast.Call):
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id == "os"
                and (f.attr in ("system", "popen", "posix_spawn", "spawnl") or f.attr.startswith(("exec", "spawn")))
            ):
                found.append(f"os.{f.attr}")
    return found


def test_the_package_never_shells_out():
    files = sorted(_PKG.glob("*.py"))
    assert {f.name for f in files} >= {"repo_core.py", "sshsig.py"}
    for f in files:
        assert shell_outs(f.read_text(encoding="utf-8")) == [], f.name


def test_the_shell_out_detector_fires_on_a_known_bad_snippet():
    assert shell_outs("import subprocess\n") == ["subprocess"]
    assert shell_outs("from subprocess import run\n") == ["subprocess"]
    assert shell_outs("import os\nos.system('git push')\n") == ["os.system"]
    assert shell_outs("import os\nos.execvp('git', [])\n") == ["os.execvp"]


# 18 ------------------------------------------------------------------------------------------


def test_validate_policy_check_refuses_a_policy_the_validator_rejects(world, tmp_path):
    enums = tmp_path / "enums"
    enums.mkdir()
    world.policy.extra_checks.append(repo_core.validate_policy_check(enums))
    mods = set(sys.modules)
    path = list(sys.path)
    meta = propose(world, {"policy/x.yaml": b"a: 2\n"})
    e = refuses(world, meta, 409, "policy_invalid")
    assert e.message
    assert set(sys.modules) == mods and sys.path == path, "the validator import leaked into the process"


def test_validate_policy_check_runs_only_when_the_diff_touches_policy(world, monkeypatch, tmp_path):
    calls = []

    def loader(path):
        def validate(policy_dir, enums_dir):
            calls.append(sorted(p.name for p in Path(policy_dir).iterdir()))
            return []

        return validate

    monkeypatch.setattr(repo_core, "_load_validate_policy", loader)
    world.policy.extra_checks.append(repo_core.validate_policy_check(tmp_path))
    merge(world, propose(world, {"sessions/a.md": b"packet a, edited\n"}))
    assert calls == [], "the validator ran for a sessions/-only diff"
    out = merge(world, propose(world, {"policy/x.yaml": b"a: 2\n"}))
    assert calls == [["x.yaml"]], "positive control: it must run when policy/ is touched"
    assert out["note"]["checks"]["validate_policy_check"] == "pass"
