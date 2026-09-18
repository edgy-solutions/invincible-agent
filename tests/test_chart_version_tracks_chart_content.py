"""A chart change must bump the chart version. Two contents cannot share one label.

WHY THIS EXISTS. On 2026-08-27 `478c866` changed `templates/configmap.yaml` and `values.yaml`
— templating engine-p's URLs and removing three shadowing literals — and did NOT bump
`Chart.yaml`. The chart was then deployed three times from the local tree. The cluster ended up
running a release LABELLED `invincible-agent-0.3.48` whose content was not `0.3.48`.

That is the same defect the previous bump commit was written to repair, arriving from the other
direction. Its message records the first direction:

    "The cluster runs invincible-agent-0.3.47 at revision 86, and NOTHING in the repo produces
     that version — someone bumped and deployed from an unpushed tree."

Then: a label with no content. Now: content with a stale label. **Both make the version useless
for the only question anyone asks it** — *does this cluster have the fix?* — and both are
invisible to `helm list`, which shows a plausible version either way.

THE VERSION IS AN EVENT LABEL UNLESS SOMETHING MAKES IT A FACT ABOUT CONTENT. Nothing did.
Every other artifact in this repo that carries an identity has a seal keeping the identity
honest; the chart did not, so the discipline lasted exactly as long as people remembered it.

WHAT THIS DOES NOT CHECK, AND THE CORRECTION THAT EARNED THAT PARAGRAPH A REWRITE.

This file first said the "is the version already taken" half was a CLUSTER fact belonging in a
runbook. That was wrong, and CI proved it within the hour: the bump this seal demanded went to
`0.3.49`, which was ALREADY PUBLISHED, and the release workflow refused it —

    helm/** changed but Chart.yaml is still at 0.3.49, which is already published as
    invincible-agent-0.3.49. Publishing nothing here means a deployment installing 'the latest
    chart' silently gets the OLD contents — the failure mode that left engines unregistered.

The published INDEX is a registry fact, not a cluster fact, and it is perfectly checkable in CI
without touching a cluster. I had conflated "deployed in a cluster" with "published in the chart
repo" and used the former to excuse skipping the latter.

THE TWO GUARDS ARE NOT REDUNDANT, and neither implies the other:

  * CI fires when helm/** changed AND the version is already published. It cannot see a change
    made in a LATER commit than the last bump if that version happens to be unpublished.
  * This seal fires when chart content moved after the last Chart.yaml edit, published or not.

The case only this one catches: someone bumps in commit A, then edits a template in commit B and
never touches Chart.yaml again. The version is unpublished, so CI is content, and the chart drifts
away from its label inside the tree. That is exactly what 478c866 did.

Keep both. The runbook keeps only the part that IS a cluster fact — "bump above the DEPLOYED
label" — which neither guard can see.
"""
from __future__ import annotations

import subprocess

import pytest

_CHART = "helm/invincible-agent/Chart.yaml"
_CHART_DIR = "helm/"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def _have_git_history() -> bool:
    return bool(_git("rev-parse", "--is-inside-work-tree") == "true" and _git("log", "-1", "--format=%H"))


pytestmark = pytest.mark.skipif(
    not _have_git_history(), reason="no git history available (shallow or exported tree)"
)


def test_the_inputs_are_readable():
    """Positive control. If neither query returns a commit, every assertion below is vacuous —
    which is exactly how a seal goes quiet without anyone noticing."""
    assert _git("log", "-1", "--format=%H", "--", _CHART), "no commit ever touched Chart.yaml"
    assert _git("log", "-1", "--format=%H", "--", _CHART_DIR), "no commit ever touched helm/"


def test_a_chart_change_bumped_the_chart_version():
    """THE SEAL.

    The newest commit touching ANY chart file other than Chart.yaml must be an ancestor of (or
    the same as) the newest commit touching Chart.yaml. If a template or values change is NEWER
    than the last Chart.yaml edit, the chart moved and its version did not.
    """
    last_chart_yaml = _git("log", "-1", "--format=%H", "--", _CHART)
    last_other = _git(
        "log", "-1", "--format=%H", "--", _CHART_DIR, f":!{_CHART}"
    )
    if not last_other:
        pytest.skip("no non-Chart.yaml chart files in history")

    # is_ancestor(A, B) is true when A is reachable from B — i.e. B is at least as new.
    same_or_older = subprocess.run(
        ["git", "merge-base", "--is-ancestor", last_other, last_chart_yaml],
        capture_output=True, check=False,
    ).returncode == 0

    if not same_or_older:
        subject = _git("log", "-1", "--format=%s", last_other)
        files = _git("show", "--stat", "--format=", last_other)
        pytest.fail(
            "Chart content changed AFTER the last Chart.yaml edit — the version did not move.\n"
            f"  offending commit: {last_other[:9]}  {subject}\n"
            f"{files}\n"
            "Two different chart contents now share one version number, and `helm list` shows a\n"
            "plausible version for both. Bump `version:` in helm/invincible-agent/Chart.yaml —\n"
            "above the deployed label, per the runbook — in the same commit as the change."
        )


def _porcelain_paths(text: str) -> set[str]:
    """Paths out of `git status --porcelain`, parsed by SEPARATOR rather than by offset.

    A fixed `line[3:]` slice is correct only while nobody has trimmed the line — and the `_git`
    helper above `.strip()`s stdout, which eats the leading space of the two-column status on
    the FIRST line only. That produced `elm/invincible-agent/Chart.yaml`: still path-SHAPED, so
    the resulting failure read as a real finding rather than as a broken instrument.
    """
    paths = set()
    for line in text.splitlines():
        parts = line.strip().split(" ", 1)
        path = parts[1] if len(parts) == 2 else ""
        # A rename reports `old -> new`; the NEW path is the one that is in the tree.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path:
            paths.add(path)
    return paths


def _unbumped_chart_paths(text: str) -> list[str]:
    """Chart content changed in the working tree with Chart.yaml left alone — the offending set,
    empty when there is nothing to say."""
    changed = _porcelain_paths(text)
    if _CHART in changed:
        return []
    return sorted(p for p in changed if p != _CHART)


@pytest.mark.parametrize(
    "porcelain,expected",
    [
        # THE FAILING CASE, written exactly as git emits it — leading space and all. This is the
        # shape of e36aa55's working tree at the moment its suite ran green.
        (" M helm/invincible-agent/values.yaml", ["helm/invincible-agent/values.yaml"]),
        # A LEADING SPACE ALREADY TRIMMED, which is what the stripping helper handed over. The
        # offset parse turned this into `elm/...` and reported the tree as unbumped while it
        # was correctly bumped.
        ("M  helm/invincible-agent/Chart.yaml", []),
        # The bump present alongside the content: nothing to say.
        (
            " M helm/invincible-agent/values.yaml" + chr(10) + " M helm/invincible-agent/Chart.yaml",
            [],
        ),
        # Staged rename of a template, no bump: the NEW path is the one that is in the tree.
        (
            "R  helm/invincible-agent/templates/a.yaml -> helm/invincible-agent/templates/b.yaml",
            ["helm/invincible-agent/templates/b.yaml"],
        ),
        # Untracked template, no bump — a new file is chart content too.
        ("?? helm/invincible-agent/templates/new.yaml", ["helm/invincible-agent/templates/new.yaml"]),
        ("", []),
    ],
)
def test_THE_WORKING_TREE_RULE_DISCRIMINATES(porcelain: str, expected: list[str]):
    """THE FIXTURE, because the arm below is silent in a tree that has nothing dirty — and a
    green that means "nothing to look at" is indistinguishable from a green that means "the rule
    fires correctly". Synthetic porcelain rather than a touched file: a run that MUTATES the tree
    it is measuring cannot be trusted in either direction.
    """
    assert _unbumped_chart_paths(porcelain) == expected


def test_an_UNCOMMITTED_chart_change_is_caught_before_it_is_committed():
    """THE ARM THAT FIRES IN TIME, and the gap it closes cost a red release on 2026-09-15.

    The seal above reads COMMITTED history, so it is blind to precisely the moment it is needed.
    `e36aa55` added `GRAPH_HOST_POSTGRES_DSN` to values.yaml; the full suite ran GREEN against
    that working tree — because at that instant the newest commit touching helm/ was still an
    ancestor of the newest commit touching Chart.yaml — and the release workflow refused the
    push minutes later.

    > **The check ran, its premise was true, and it answered a question about a state that had
    > already been published.** The person who can still fix it cheaply is the one who has not
    > committed yet, and that is the only person the committed-history arm cannot speak to.

    The remedy was therefore always a FOLLOW-UP commit — the same "a check that can only report
    is a check whose remedy is always record-it-and-move-on" shape that put the Lane trailer in
    a pre-push hook rather than leaving it to a post-hoc seal (R-058.1).

    SKIPS WITH A CLEAN TREE, and that is not fail-open: CI always has a clean tree and is
    covered by the committed arm plus the release workflow's published-index check. This arm
    exists for the working copy those two cannot see.
    """
    # NOT `_git` HERE, and the reason is worth keeping. That helper `.strip()`s stdout, which
    # eats the leading space of porcelain's two-column status on the FIRST LINE ONLY — so a
    # fixed `line[3:]` slice reported `elm/invincible-agent/Chart.yaml` and this arm failed
    # against a correctly-bumped tree. A path mangled by one character still LOOKS like a path
    # in a failure message, which is why it read as a real finding rather than as an
    # instrument defect.
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", _CHART_DIR],
        capture_output=True, text=True, check=False,
    )
    if not proc.stdout.strip():
        pytest.skip("no uncommitted chart changes in this working tree")

    others = _unbumped_chart_paths(proc.stdout)
    if others:
        pytest.fail(
            "Uncommitted chart content with no Chart.yaml bump — commit this and the version is\n"
            "stale the moment it lands, and the release workflow refuses the push.\n"
            "  changed: " + ", ".join(others) + "\n"
            "Bump `version:` in " + _CHART + " IN THIS COMMIT. The deployed label is what to\n"
            "clear: `helm list -n sandbox` shows what the cluster is running."
        )
