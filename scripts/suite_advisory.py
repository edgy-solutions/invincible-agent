"""Split a pytest log's reds into KNOWN (tests/known_reds.txt) and NEW. Advisory only.

Usage: suite_advisory.py <pytest-log> <known-reds-file> --exit <int> [--merged-ref REF]

Markdown goes to stdout, workflow annotations to stderr. Always exits 0, except 2 for a
malformed known file or unreadable inputs.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

# A parametrized id can hold spaces ("test_x[how is it used]"), so the id runs to pytest's " - "
# message separator, not to the first space.
_RED = re.compile(r"^(FAILED|ERROR) (.+?)(?: - .*)?$")


def parse_reds(text: str) -> list[str]:
    seen: list[str] = []
    for line in text.splitlines():
        m = _RED.match(line)
        red = m.group(2).rstrip() if m else ""
        if red and red not in seen:
            seen.append(red)
    return seen


def parse_known(text: str) -> dict[str, str]:
    known: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entry, sep, comment = line.partition("# ")
        entry, comment = entry.strip(), comment.strip()
        if not sep or not entry or not comment:
            raise ValueError(f"line {n}: entry has no '# <group>: <cause> (<owner>)' comment: {raw!r}")
        known[entry] = comment
    return known

_FIX_CITE = re.compile(r"\bfixed by (?:PR\s*#?|#)(\d+)\b", re.IGNORECASE)
_MERGE_COMMIT = re.compile(r"^Merge pull request #(\d+) ")
_SQUASH = re.compile(r"\(#(\d+)\)\s*$")


def cited_fix(comment: str) -> int | None:
    """The PR a comment names as its fix ("fixed by PR 434"); a bare "PR 434" is not a citation."""
    m = _FIX_CITE.search(comment)
    return int(m.group(1)) if m else None


def merged_prs(subjects) -> set[int]:
    """PR numbers merged per commit subjects: a merge commit or a squash subject ending "(#n)"."""
    merged: set[int] = set()
    for subject in subjects:
        m = _MERGE_COMMIT.match(subject) or _SQUASH.search(subject)
        if m:
            merged.add(int(m.group(1)))
    return merged


def matches(red: str, entry: str) -> bool:
    return red == entry or red.startswith(entry + "[") or red.startswith(entry + "::")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("known")
    ap.add_argument("--exit", dest="code", type=int, required=True)
    ap.add_argument("--merged-ref", dest="merged_ref", default=None)
    args = ap.parse_args(argv)
    try:
        with open(args.log, encoding="utf-8", errors="replace") as f:
            reds = parse_reds(f.read())
        with open(args.known, encoding="utf-8") as f:
            known = parse_known(f.read())
    except (OSError, ValueError) as exc:
        print(f"suite_advisory: {exc}", file=sys.stderr)
        return 2
    merged: set[int] = set()
    if args.merged_ref:
        try:
            log = subprocess.run(["git", "log", "--format=%s", args.merged_ref],
                                 capture_output=True, text=True, check=True,
                                 encoding="utf-8", errors="replace")
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"suite_advisory: {exc}", file=sys.stderr)
            return 2
        merged = merged_prs(log.stdout.splitlines())

    new, known_hits = [], []
    hit_entries: set[str] = set()
    for red in reds:
        entry = next((e for e in known if matches(red, e)), None)
        if entry is None:
            new.append(red)
        else:
            known_hits.append((red, known[entry]))
            hit_entries.add(entry)
    stale = [e for e in known if e not in hit_entries]
    cited = [(e, n) for e in known if (n := cited_fix(known[e])) is not None and n in merged]

    out: list[str] = []
    if args.code not in (0, 1):
        msg = f"The suite did not run to completion (pytest exit {args.code}): the lists below are not the whole story."
        out.append(f"**{msg}**\n")
        print(f"::warning title=suite incomplete::{msg}", file=sys.stderr)
    out.append("## Suite advisory\n")
    out.append(f"new {len(new)}, known {len(known_hits)}, known entries not red in this run {len(stale)}\n")
    out.append("### New reds (not in tests/known_reds.txt)\n")
    out.extend([f"- `{r}`" for r in new] or ["none"])
    out.append("\n### Known reds\n")
    out.extend([f"- `{r}` - {c}" for r, c in known_hits] or ["none"])
    out.append("\n### Known entries not red in this run\n")
    out.append("Each of these passed or was skipped in this run, so it is a candidate to delete. "
               "That is not proof it is fixed.\n")
    out.extend([f"- `{e}` - {known[e]}" for e in stale] or ["none"])
    out.append("\n### Known entries whose cited fix is merged\n")
    if args.merged_ref:
        out.append(f"Each cites a PR merged on {args.merged_ref} as its fix. "
                   "That PR should have deleted the line; delete it.\n")
        out.extend([f"- `{e}` - PR {n}: {known[e]}" for e, n in cited] or ["none"])
    else:
        out.append("not checked (no --merged-ref)")
    print("\n".join(out))

    for r in new:
        print(f"::warning file={r.split('::', 1)[0]},title=new red::{r}", file=sys.stderr)
    for e in stale:
        print(f"::notice title=known red not seen::{e}", file=sys.stderr)
    for e, n in cited:
        print(f"::warning title=stale known red::{e} cites merged PR {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
