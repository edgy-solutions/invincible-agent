"""Fixtures for engine-r core: a source repository built with pygit2 (never the git binary)."""
from __future__ import annotations

from types import SimpleNamespace

import pygit2

from agent_fleet.repository_agent import repo_core, sshsig

SIG = pygit2.Signature("Fixture", "fixture@example.invalid", 1_700_000_000, 0)

BASE_FILES = {
    "policy/x.yaml": b"a: 1\n",
    "sessions/a.md": b"packet a\n",
    "src/app.py": b"print('app')\n",
}


def commit_files(repo, files: dict, parents: list, ref: str | None, message: str = "fixture") -> pygit2.Oid:
    index = pygit2.Index()
    for path, data in files.items():
        index.add(pygit2.IndexEntry(path, repo.create_blob(data), pygit2.GIT_FILEMODE_BLOB))
    tree = index.write_tree(repo)
    return repo.create_commit(ref, SIG, SIG, message, tree, parents)


def build_source(path):
    """c1 -> c2 (master) and c1 -> c3 (side), merged by M on master. Four commits, one merge, one tag."""
    src = pygit2.init_repository(str(path), bare=True, initial_head="master")
    c1 = commit_files(src, BASE_FILES, [], "refs/heads/master", "c1")
    c2 = commit_files(src, {**BASE_FILES, "src/app.py": b"print('two')\n"}, [c1], "refs/heads/master", "c2")
    c3 = commit_files(src, {**BASE_FILES, "sessions/b.md": b"packet b\n"}, [c1], "refs/heads/side", "c3")
    m = commit_files(
        src,
        {**BASE_FILES, "src/app.py": b"print('two')\n", "sessions/b.md": b"packet b\n"},
        [c2, c3],
        "refs/heads/master",
        "M",
    )
    src.create_reference("refs/tags/v0", c1)
    return SimpleNamespace(repo=src, c1=str(c1), c2=str(c2), c3=str(c3), merge=str(m))


GOVERNED = {"policy/": {"review": "repo_review:POLICY", "approvers": 2}, "sessions/": {"review": "owning_lane"}}

PROPOSER = repo_core.Caller("lane-a", "local")
COMPLETER = repo_core.Caller("engine-r", "service")


def approval(sha: str, who: str = "reviewer-1", task: str = "task-1") -> repo_core.Approval:
    return repo_core.Approval(who, sha, task, "2026-10-28T00:00:00Z")


def make_policy(signer, **kw) -> repo_core.Policy:
    args = dict(
        governed=dict(GOVERNED),
        customer_terms=["zz-acme-test"],
        signer=signer,
        committer_name="engine-r",
        committer_email="engine-r@engine-r.invalid",
    )
    args.update(kw)
    return repo_core.Policy(**args)


def state_of(repo: repo_core.Repo, ref: str = "refs/heads/master") -> tuple:
    """(target tip, audit-notes tip): what a refusal must leave untouched."""
    return repo._read_tip(ref), repo._read_tip(repo_core.AUDIT_REF)
