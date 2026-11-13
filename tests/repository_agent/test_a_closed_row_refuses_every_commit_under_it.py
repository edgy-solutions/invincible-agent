"""engine-r check 6, `review: closed` (ruled 2026-11-12/13: session files are placed, never
committed; the sessions/ row stays as a guard that refuses a commit there).

Each refusal arm has a control that differs ONLY in the row the decision reads: the same diff under
an open row merges. The row that governs a path is its longest matching prefix, so a narrower open
row inside a closed root merges, and a narrower closed row inside an open root refuses."""
from __future__ import annotations

import pytest

from agent_fleet.repository_agent import repo_core
from agent_fleet.repository_agent.repo_core import RepoRefusal
from engine_r_fixtures import COMPLETER, PROPOSER, approval, state_of

MASTER = "refs/heads/master"
OPEN = {"review": "repo_review:POLICY", "approvers": 1}
CLOSED = {"review": repo_core.CLOSED_REVIEW}


def _govern(w, rows):
    w.repo.policy.governed = dict(rows)


def _propose(w, changes):
    return w.repo.propose(caller=PROPOSER, target_ref=MASTER, changes=changes, intent="why", message="change")


def _merge(w, meta):
    return w.repo.merge(proposal_id=meta["id"], reviewed_sha=meta["head_sha"],
                        approvals=[approval(meta["head_sha"])], completes=COMPLETER)


def _refused(w, meta):
    before = state_of(w.repo)
    with pytest.raises(RepoRefusal) as ei:
        _merge(w, meta)
    assert state_of(w.repo) == before, "a refusal moved a ref or wrote a note"
    return ei.value


def _merges(w, meta):
    _merge(w, meta)
    assert w.repo.proposal(meta["id"])["state"] == "merged"


def test_the_constant_is_the_rails_word():
    assert repo_core.CLOSED_REVIEW == "closed"


def test_a_file_under_a_closed_row_is_refused(world):
    _govern(world, {"policy/": OPEN, "sessions/": CLOSED})
    e = _refused(world, _propose(world, {"sessions/p.md": b"packet\n"}))
    assert (e.status, e.error, e.check) == (403, "path_closed", "check6")
    assert "sessions/p.md" in e.message


def test_control_the_same_file_under_an_open_row_merges(world):
    _govern(world, {"policy/": OPEN, "sessions/": OPEN})
    _merges(world, _propose(world, {"sessions/p.md": b"packet\n"}))


def test_a_delete_under_a_closed_row_is_refused(world):
    """The fixture source already tracks sessions/b.md: removing it is a commit under the row too."""
    _govern(world, {"policy/": OPEN, "sessions/": CLOSED})
    assert _refused(world, _propose(world, {"sessions/b.md": None})).error == "path_closed"


def test_one_closed_path_refuses_a_mixed_diff(world):
    _govern(world, {"policy/": OPEN, "sessions/": CLOSED})
    meta = _propose(world, {"policy/x.yaml": b"a: 2\n", "sessions/p.md": b"packet\n"})
    assert _refused(world, meta).error == "path_closed"


def test_control_the_open_half_alone_merges(world):
    _govern(world, {"policy/": OPEN, "sessions/": CLOSED})
    _merges(world, _propose(world, {"policy/x.yaml": b"a: 2\n"}))


def test_a_narrower_open_row_inside_a_closed_root_merges(world):
    _govern(world, {"policy/": OPEN, "sessions/": CLOSED, "sessions/open/": OPEN})
    _merges(world, _propose(world, {"sessions/open/a.md": b"x\n"}))


def test_a_narrower_closed_row_inside_an_open_root_refuses(world):
    _govern(world, {"policy/": OPEN, "policy/frozen/": CLOSED})
    assert _refused(world, _propose(world, {"policy/frozen/a.yaml": b"a: 1\n"})).error == "path_closed"


def test_a_path_no_row_governs_is_still_not_governed(world):
    """The closed check runs only on a governed path: an ungoverned one keeps its own refusal."""
    _govern(world, {"policy/": OPEN, "sessions/": CLOSED})
    assert _refused(world, _propose(world, {"src/app.py": b"x\n"})).error == "path_not_governed"
