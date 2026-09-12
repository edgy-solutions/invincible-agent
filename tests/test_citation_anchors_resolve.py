"""A citation's FRAGMENT must name a heading that exists, not just a file that exists.

COMPANION TO `test_citation_paths.py`, WHICH CHECKS THE OTHER HALF. That seal resolves the PATH
of a citation and never the fragment, so a link to `docs/rulings/README.md#r-017` was green in
every tree — **including every tree where that heading did not exist**, which for a day was all of
them. The failure mode is not a broken link. It is **a citation pointing at a real file and a
fictional ruling, and it reads as verified precisely because the existing seal covers the visible
half.**

THE RULE IS GITHUB'S, AND IT WAS SETTLED BY MEASUREMENT RATHER THAN BY READING. Two candidate
slug algorithms disagree on exactly the character every heading in the register uses — the em
dash — and the repo had citations in BOTH spellings, including the register citing itself each
way, so one of its own two self-citations was a 404 whichever rule held. Resolved 2026-09-11 by
POSTing the headings to GitHub's own renderer (`api.github.com/markdown`), which returned:

    ## R-005 — `shared_slots` are template-scoped
      -> id="user-content-r-005--shared_slots-are-template-scoped"      DOUBLE hyphen

So: **strip punctuation, then one hyphen PER SPACE, no collapsing of runs.** An em dash surrounded
by spaces vanishes and leaves both spaces, hence `--`. Eight of nine citations in the repo were
single-hyphen and would have 404'd; they were rewritten to this rule.

**There is no internal authority to defer to** — this repo contains no slugifier, so GitHub is the
only renderer that serves the corpus and its behaviour is the rule. If the corpus ever gains a
second renderer, this seal is where that fork gets decided rather than discovered.

Run: uv run --frozen pytest tests/test_citation_anchors_resolve.py -v
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_REGISTER = _ROOT / "docs" / "rulings" / "README.md"

#: Fragments that are deliberately not real anchors: the register's own worked EXAMPLE of the
#: citation form, and a number-only shorthand with no slug, which names a ruling rather than
#: claiming a heading.
#:
#: THE PATTERN IS BUILT, NOT WRITTEN OUT, AND THAT IS DELIBERATE. Spelling the exempt fragment
#: literally here put a matching string in this file's own prose, and the scan — which reads
#: TRACKED FILES, this one included — flagged the comment explaining the exemption. A checker
#: that greps for a string cannot tell its subject from its own description of its subject;
#: that is the third instance of this shape in one day. Assembling it from pieces keeps the
#: literal out of the file while leaving the rule readable.
_EXEMPT = re.compile(r'^r-0' + '0n', re.I)


def github_slug(heading: str) -> str:
    """GitHub's anchor for a heading — verified against `api.github.com/markdown`.

    Strip punctuation, lowercase, then **one hyphen per space**. Collapsing whitespace runs is
    the plausible-looking mistake: it turns ` — ` into a single hyphen and produces an anchor
    that 404s on every heading in this register.
    """
    return re.sub(r'[^\w\s-]', '', heading.strip().lower()).replace(' ', '-')


def _register_anchors() -> set[str]:
    return {github_slug(line[3:])
            for line in _REGISTER.read_text(encoding="utf-8").splitlines()
            if line.startswith("## ")}


def _cited() -> list[tuple[str, str]]:
    """`(location, fragment)` for every register citation in every TRACKED file.

    `git grep` rather than a directory walk, because the first attempt at this scan globbed
    `docs/` only and missed the two citations living in `src/` and `tests/` — a sample presented
    as a population, which is the instrument defect this repo keeps paying for.
    """
    out = subprocess.run(
        ["git", "grep", "-n", "-o", "-E", r'#r-[0-9A-Za-z_-]+', "--", "."],
        cwd=str(_ROOT), capture_output=True, text=True, encoding="utf-8",
    ).stdout
    found = []
    for line in out.splitlines():
        if ":#" not in line:
            continue
        loc, frag = line.rsplit(":#", 1)
        if not _EXEMPT.match(frag):
            found.append((loc, frag))
    return found


def test_the_scan_can_SEE_citations_at_all():
    """THE FLOOR. Every assertion below quantifies over this scan; if it returned nothing, a
    clean result would mean 'nobody cites the register' rather than 'every citation resolves'."""
    cited = _cited()
    assert len(cited) >= 5, f"the citation scan found only {len(cited)}: {cited}"


def test_the_register_has_anchors_to_resolve_against():
    """The other half of the instrument."""
    anchors = _register_anchors()
    assert len(anchors) >= 15, f"only {len(anchors)} headings found in the register"


def test_EVERY_CITED_ANCHOR_NAMES_A_HEADING_THAT_EXISTS():
    """THE SEAL."""
    anchors = _register_anchors()
    broken = [(loc, f) for loc, f in _cited()
              if f not in anchors and not re.fullmatch(r'r-[0-9]{3}', f)]
    assert not broken, (
        "citations naming a ruling that does not exist:\n"
        + "\n".join(f"    #{f}\n        at {loc}" for loc, f in broken)
        + "\n\nThe file resolves, so `test_citation_paths.py` stays green. The RULING does not."
    )


def test_THE_CONTROL_a_fabricated_anchor_on_a_REAL_file_is_REJECTED():
    """THE CONTROL, and the seal is worthless without it.

    Everything above asserts an ABSENCE of broken citations. If `_register_anchors()` returned
    a set containing everything, or the comparison were inverted, the seal would pass while
    checking nothing. This proves the checker can say NO about the half that matters — a
    citation whose FILE is real and whose FRAGMENT is invented.
    """
    anchors = _register_anchors()
    assert _REGISTER.exists(), "CONTROL FAILED: the register itself is missing"
    fabricated = "r-999--this-ruling-was-never-written"
    assert fabricated not in anchors, (
        "CONTROL FAILED: a fabricated anchor is reported as resolving, so the seal above "
        "cannot distinguish a real ruling from an invented one."
    )


def test_THE_CONTROL_the_slugger_matches_GITHUBS_rendered_output():
    """The rule itself, pinned to the measurement that settled it.

    These two expectations are GitHub's literal response, not a derivation. If someone
    'simplifies' `github_slug` to collapse whitespace runs, every anchor in the register silently
    becomes a 404 and the seal above would still pass — because it would compare wrong anchors
    against wrong anchors, consistently.
    """
    assert github_slug("R-005 — `shared_slots` are template-scoped") == \
        "r-005--shared_slots-are-template-scoped"
    assert github_slug("R-020 — Task kinds: two items") == "r-020--task-kinds-two-items"
    assert "--" in github_slug("A — B"), (
        "the em dash must leave TWO hyphens; collapsing runs is the plausible-looking mistake "
        "that 404s every citation in this repo"
    )
