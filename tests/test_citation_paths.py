"""Every `docs/…` path cited anywhere in the repo must resolve to a file that exists.

WHY THIS IS A SEALED TEST AND NOT A ONE-TIME GREP. The 2026-08-15 taxonomy move relocated 40
files out of `docs/plans/`. A careful grep protects that move and nothing after it. The reason
it has to be standing is what the census found:

    tests/test_dispatch_driver.py       f"(docs/plans/<moved-packet>.md)"   <- assertion message
    tests/test_cross_repo_contracts.py  module docstring
    tests/test_sustainment_instance_match.py  module docstring
    tests/fixtures/failure_path/cropfail_review.py  module docstring

Those are docstrings and assertion messages — prose, never opened. **Move the file and no test
fails.** The first is the sharpest instance: the path sits inside an ASSERTION FAILURE MESSAGE,
so the dead link surfaces only to someone already debugging a failure, who then follows it
nowhere. Citation rot invisible to every check, appearing exclusively at the worst moment.

TWO SPECIES, AND THEY ARE NOT THE SAME DEFECT — this test separates them:

  ROT      the file existed and a move or delete broke the link. Fixable by repair; this is
           what the test fails on, and what the taxonomy move could have caused.
  PHANTOM  the file NEVER existed. The citation was aspirational when written and has read as
           a statement of fact ever since. Nothing to restore, so failing on it would only
           teach people to ignore the check — see PHANTOM_CITATIONS below.

WHAT IT CAUGHT ON ITS FIRST RUN, and a correction it forced. The move-day claim was that "the
baseline is clean" — that was verified over `docs/plans/` paths only. Anchoring the pattern at
`docs/` instead surfaced two phantoms that predate the move by months. The narrower claim was
true; the broader one was never checked. Recorded because the check's own scope was the thing
that made a real gap invisible.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git", ".venv", ".venv.wsl", "node_modules", "__pycache__", ".pytest_cache",
    ".tmp_dagster_home_kc27j3_2", "htmlcov", ".mypy_cache", ".ruff_cache",
}
TEXT_EXT = {
    ".md", ".py", ".yaml", ".yml", ".txt", ".sql", ".json", ".toml", ".tpl", ".baml",
    ".ts", ".tsx", ".sh", ".cfg", ".ini",
}

# Absolute-from-root citations. Deliberately anchored to `docs/` rather than to any single
# subdirectory: the move that motivated this test created `docs/plans/archive/` and
# `docs/reference/`, and a pattern hard-coded to `docs/plans/` would have gone blind to exactly
# the paths it was written to protect.
DOC_PATH = re.compile(r"docs/[A-Za-z0-9._/-]+\.md")

# `<name>` placeholders in prose that documents the citation SHAPE rather than citing a file.
PLACEHOLDER = re.compile(r"[<>]")

# PHANTOM CITATIONS — paths that were specified but NEVER WRITTEN.
#
# An escape hatch, and this repo has already watched one degrade (`closed-by-note`, see
# docs/plans/board-migration.md), so the admission rule is narrow and MECHANICALLY ENFORCED by
# test_phantom_allowlist_is_honest below: an entry is legal only if `git log --diff-filter=A`
# shows the path was never added. That makes it structurally impossible to use this list to
# silence a real deletion — the failure mode an unchecked allowlist always drifts into.
#
# These are DEBT, not exemptions. Both are filed as phase-2 candidates in
# docs/plans/board-migration.md: the seal found them mechanically, which is the phase-2 method
# working (an arc with no artifact, surfaced by a grep rather than by memory).
PHANTOM_CITATIONS = {
    "docs/adr/namespace-prefixes.md":
        "ADR-0005 names it as a COST ('we need a registry mirroring this ADR's table'), not as "
        "an existing artifact. Never created (citation added 191cb63). Reads as a fact.",
    "docs/routing/recipe_v2_instance_resolution.md":
        "tests/routing/test_classify_route.py cites it as THE SPEC for rows that are "
        "deliberately RED. Never created (citation added d454a64); docs/routing/ has never "
        "existed. Load-bearing: a reader asking why the rows are red is sent nowhere.",
    "docs/adr/ADR-0006-datahub-proposal-inbox.md":
        "Linked as an ADR by ADR-0019 and ADR-0021. Never created — the 0006 slot went to "
        "'registry location' instead. Two ADRs cross-reference a decision record that does "
        "not exist.",
    "docs/adr/ADR-0016-memory-boundary-revised.md":
        "Linked by ADR-0019. Never created. Same shape as 0006: a numbered ADR referenced as "
        "though it were on file.",
}

# Cross-repo relative links (../../../sibling-repo/...) — resolvable only when the sibling is
# checked out beside this repo, which is an environment fact, not a repo defect. Skipped by
# path shape rather than allowlisted by name, so a new sibling reference needs no maintenance.
def _is_cross_repo(target: str) -> bool:
    return target.startswith("../../../")


def _iter_text_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = pathlib.Path(dirpath) / fn
            if p.suffix.lower() in TEXT_EXT:
                yield p


def _collect_citations():
    """-> {cited_path: [citing_site, ...]}"""
    found: dict[str, list[str]] = {}
    for path in _iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError, OSError):
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in DOC_PATH.finditer(line):
                cited = m.group(0)
                if PLACEHOLDER.search(cited):
                    continue
                found.setdefault(cited, []).append(f"{rel}:{lineno}")
    return found


def test_every_cited_docs_path_resolves():
    """A moved file with a dangling citation is worse than a mis-shelved one."""
    citations = _collect_citations()
    assert citations, "collected no docs/ citations at all — the scanner is broken, not the repo"

    dangling = {
        cited: sites for cited, sites in sorted(citations.items())
        if not (ROOT / cited).is_file() and cited not in PHANTOM_CITATIONS
    }
    if dangling:
        report = "\n".join(
            f"  {cited}\n" + "".join(f"      cited by {s}\n" for s in sites)
            for cited, sites in dangling.items()
        )
        pytest.fail(
            f"{len(dangling)} docs/ path(s) cited but absent — a rename or move left a dead "
            f"link.\nThe citing SITE is named so the fix does not require a repo-wide grep:\n\n"
            f"{report}"
        )


MD_LINK = re.compile(r"\]\(([^)\s]+\.md)(?:#[^)]*)?\)")


def _iter_relative_links():
    """-> (citing_file, lineno, raw_target, repo_relative_target) for in-repo markdown links."""
    for path in _iter_text_files():
        if path.suffix.lower() != ".md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError, OSError):
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in MD_LINK.finditer(line):
                target = m.group(1)
                if (target.startswith(("http://", "https://", "mailto:"))
                        or PLACEHOLDER.search(target)
                        or _is_cross_repo(target)):
                    continue
                resolved = (path.parent / target).resolve()
                try:
                    repo_rel = str(resolved.relative_to(ROOT)).replace("\\", "/")
                except ValueError:
                    continue  # escapes the repo entirely
                yield rel, lineno, target, repo_rel


# A markdown target naming a MACHINE path: a drive letter (`C:/…`, `C:\\…`) or a POSIX
# absolute (`/home/…`). Neither is ever a valid relative link in a repo — they resolve only on
# the machine that wrote them, if there.
_MACHINE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/(?!/))")


def _iter_machine_path_links():
    """-> (citing_file, lineno, target) for markdown links naming an absolute machine path."""
    for path in _iter_text_files():
        if path.suffix.lower() != ".md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError, OSError):
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in MD_LINK.finditer(line):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:")) or PLACEHOLDER.search(target):
                    continue
                if _MACHINE_PATH.match(target):
                    yield rel, lineno, target


def test_no_markdown_link_targets_an_absolute_machine_path():
    """A link that resolves on ONE OPERATOR'S LAPTOP, and the OS decided whether anyone noticed.

    MEASURED 2026-08-22. `tests/routing/STATE_GATEWAY_V02.md` linked twice into
    `C:/Users/<user>/.claude/projects/…/memory/*.md` — another repo's agent auto-memory,
    outside this repo and outside any repo. The link was broken for every reader from the day
    it was written. Whether a TEST said so depended entirely on the operating system:

      Windows   `path.parent / "C:/Users/…"` -> pathlib sees an ABSOLUTE path, discards the
                left side, `relative_to(ROOT)` raises ValueError, and the iterator's
                `continue  # escapes the repo entirely` skips it. GREEN.
      Linux     `C:/Users/…` has no leading slash, so it is RELATIVE: it joins to
                `tests/routing/C:/Users/…`, stays under ROOT, gets checked, and FAILS.

    So the suite was green on Windows and red on Linux for the same commit, and the red one is
    the one that matches CI. `test_relative_markdown_links_resolve` cannot cover this by
    itself — its own escape hatch is what hides it on half the machines.

    This test is OS-INVARIANT by construction: it matches the SHAPE of the target string and
    never asks the filesystem anything. A check whose verdict depends on which machine ran it
    is not a check.
    """
    offenders = [f"  {rel}:{lineno}  ->  {target}" for rel, lineno, target in _iter_machine_path_links()]
    assert not offenders, (
        "markdown link(s) target an absolute machine path — they resolve only on the machine "
        "that wrote them. Name the thing instead of linking it:\n" + "\n".join(sorted(offenders))
    )


def _collect_relative_link_targets() -> set[str]:
    return {repo_rel for _, _, _, repo_rel in _iter_relative_links()}


def test_relative_markdown_links_resolve():
    """The OTHER citation shape — and the one that caught this test out.

    `test_every_cited_docs_path_resolves` matches absolute `docs/…` strings. A markdown link
    whose TARGET is relative (`](../adr/X.md)`, `](demo-script.md)`) is invisible to it, and
    the 2026-08-15 move broke four of them at once: files relocated to `docs/plans/archive/`
    went one level deeper, so their `../adr/…` targets needed `../../adr/…`. The absolute-path
    check passed the whole time.

    That is the same defect as legacy-dns-guard-phantom-scope and as the move-day "baseline is
    clean" claim: **a check whose scope excludes the failure reports green over it.** Written
    down here because it has now happened three times in one repo, twice in one day.
    """
    broken = [
        f"  {rel}:{lineno}  ->  {target}   (resolves to {repo_rel})"
        for rel, lineno, target, repo_rel in _iter_relative_links()
        if repo_rel not in PHANTOM_CITATIONS and not (ROOT / repo_rel).is_file()
    ]
    assert not broken, (
        "markdown link target(s) do not resolve — a move changed the file's DEPTH and its "
        "relative links were not re-based:\n" + "\n".join(sorted(broken))
    )


@pytest.mark.parametrize("path", sorted(PHANTOM_CITATIONS))
def test_phantom_allowlist_is_honest(path):
    """An entry is legal ONLY if the path was never added to git history.

    Without this, PHANTOM_CITATIONS is a place to hide a deletion: move or delete a real file,
    add it here, and the seal goes quiet about the exact thing it was built to catch. The
    escape hatch has to prove its own precondition, or it becomes the defect.
    """
    import subprocess

    r = subprocess.run(
        ["git", "log", "--all", "--diff-filter=A", "--format=%h", "--", path],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"git log failed for {path}: {r.stderr.strip()}"
    assert not r.stdout.strip(), (
        f"{path} IS in git history (added by {r.stdout.split()[0]}) — so it is ROT, not a "
        f"phantom. Restore it or repair the citing site; do not allowlist a real deletion."
    )


def test_phantom_allowlist_entries_are_still_cited():
    """Remove the entry when the citation goes away, or the list accumulates dead exemptions.

    Same discipline as the runbook's §E rule: a workaround cites what retires it. An allowlist
    nobody prunes stops describing the repo and starts describing its history.
    """
    # BOTH shapes, or the ADR entries (cited only as relative links) would read as stale and
    # get deleted — after which the seal would fail on them again. An allowlist pruner that
    # cannot see every citation shape prunes live entries.
    cited = set(_collect_citations()) | _collect_relative_link_targets()
    stale = sorted(set(PHANTOM_CITATIONS) - cited)
    assert not stale, (
        f"PHANTOM_CITATIONS entries no longer cited anywhere — delete them: {stale}"
    )


def test_the_scan_reaches_code_not_only_docs():
    """The rot this seals against lives in docstrings and assertion messages.

    A scanner accidentally narrowed to `docs/**` would pass forever while the code citations
    rotted silently — the precise failure being guarded. So assert the population, not just
    the verdict.
    """
    citations = _collect_citations()
    code_sites = [
        site
        for sites in citations.values()
        for site in sites
        if site.endswith(tuple(f"{ext}:{n}" for ext in (".py", ".yaml", ".baml") for n in "0123456789"))
        or re.match(r".*\.(py|yaml|yml|baml|sql|tpl):\d+$", site)
    ]
    assert code_sites, (
        "no docs/ citations found in code files. Either every code citation was removed "
        "(then delete this assertion deliberately) or the scanner stopped reaching code — "
        "which is the silent-rot case this suite exists to prevent."
    )


def test_the_moved_population_is_where_the_ruling_put_it():
    """Break-on-purpose anchor for the 2026-08-15 three-way taxonomy move.

    Asserts the three directories exist and are non-empty in the shape the ruling specified,
    so a future 'tidy-up' that collapses them back trips here rather than silently undoing a
    ruling recorded in docs/plans/board-migration.md.
    """
    plans = sorted((ROOT / "docs" / "plans").glob("*.md"))
    archive = sorted((ROOT / "docs" / "plans" / "archive").glob("*.md"))
    reference = sorted((ROOT / "docs" / "reference").glob("*.md"))

    assert archive, "docs/plans/archive/ is empty — the taxonomy move was undone"
    assert reference, "docs/reference/ is empty — the taxonomy move was undone"
    assert plans, "docs/plans/ is empty"

    # The board generator globs docs/plans/*.md non-recursively, so archive/ must NOT be
    # reachable as a packet. This is what makes the coverage denominator reachable at all.
    assert not any(p.parent.name == "archive" for p in plans), (
        "archive packets are being globbed as live packets — the coverage line can never "
        "reach N of N"
    )
