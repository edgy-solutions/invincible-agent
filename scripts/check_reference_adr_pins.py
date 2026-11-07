#!/usr/bin/env python3
"""Check that every reference ADR pins the commit it cites.

A reference ADR (docs/adr/) records a decision made in ANOTHER repository. Its header carries:

    **Status:** Reference. ...
    **Decided in:** `<repo>/<path>` at `<sha>`

and .github/<repo>.ref holds the one full 40-hex sha this tree pins that repo at. This script
checks the local half, hermetically: both directions of Status <-> Decided-in, the pin file's
shape, and that the cited sha is a prefix of the pin. The workflow then fetches each line of
stdout and checks the file exists at the sha. An empty list is an error, not a pass.

Usage: python3 scripts/check_reference_adr_pins.py [--root DIR]
Stdout: `<adr-file> <repo> <full-pin-sha> <path>` per reference ADR. Errors go to stderr, exit 1.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

DECIDED_IN = re.compile(
    r"^\*\*Decided in:\*\* `([a-z0-9][a-z0-9-]*)/([^`]+)` at `([0-9a-f]{7,40})`\s*$", re.M
)
DECIDED_IN_ANY = re.compile(r"^\*\*Decided in:\*\*", re.M)
STATUS_REFERENCE = re.compile(r"^\*\*Status:\*\* Reference\b", re.M)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class Row(NamedTuple):
    adr: str
    repo: str
    pin: str
    path: str


def _pin(root: Path, repo: str) -> tuple[str | None, str | None]:
    ref = root / ".github" / f"{repo}.ref"
    if not ref.is_file():
        return None, f".github/{repo}.ref is missing (cited as a source repo)"
    body = [
        ln.strip()
        for ln in ref.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    if len(body) != 1 or not FULL_SHA.match(body[0]):
        return None, f".github/{repo}.ref must hold exactly one full 40-hex sha, got {body!r}"
    return body[0], None


def check(root: Path) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    errors: list[str] = []
    for adr in sorted((root / "docs" / "adr").glob("ADR-[0-9][0-9][0-9][0-9]-*.md")):
        text = adr.read_text(encoding="utf-8")
        is_ref = bool(STATUS_REFERENCE.search(text))
        m = DECIDED_IN.search(text)
        if is_ref and not m:
            if DECIDED_IN_ANY.search(text):
                errors.append(f"{adr.name}: Reference status but its Decided-in line is malformed")
            else:
                errors.append(f"{adr.name}: Reference status but no Decided-in line")
            continue
        if m and not is_ref:
            errors.append(f"{adr.name}: has a Decided-in line but its Status is not Reference")
            continue
        if not m:
            if DECIDED_IN_ANY.search(text):
                errors.append(f"{adr.name}: Decided-in line is malformed")
            continue
        repo, path, cited = m.groups()
        pin, err = _pin(root, repo)
        if err:
            errors.append(f"{adr.name}: {err}")
            continue
        if not pin.startswith(cited):
            errors.append(
                f"{adr.name}: cites {repo} at {cited}, which is not a prefix of the pin {pin} "
                f"in .github/{repo}.ref"
            )
            continue
        rows.append(Row(adr.name, repo, pin, path))
    if not rows and not errors:
        errors.append("no reference ADR found; an empty list is not a pass")
    elif not rows:
        errors.append("no reference ADR passed; an empty list is not a pass")
    return rows, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args(argv)
    rows, errors = check(args.root)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1
    for r in rows:
        print(f"{r.adr} {r.repo} {r.pin} {r.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
