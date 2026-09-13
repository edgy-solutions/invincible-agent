"""DERIVE the population of task-kind hardcodes. Never hand-list it.

Feature 4's audit. A hand-written list of a population is a SAMPLE — the registry-sites packet
was resampled four times and is still wrong — so the enumeration is computed here and the
disposition of each site lives beside it in ``policy/kind_hardcode_audit.yaml``.

TWO PATTERNS, because "hardcode" covers two different sins:

  ``kind:<literal>``  code that NAMES a task species
  ``next:<token>``    code that CHOOSES A NEXT STEP

A site is keyed by ``(path, pattern)`` and NOT by line number, because line numbers churn on
every edit above them and a key that churns turns the audit into a diff exercise. The count is
reported but is not part of the key: three occurrences of one literal in one file share one
disposition, and if they ever do not, the file needs splitting rather than the key needing
line numbers.

Run:  uv run --frozen python scripts/audit_kind_hardcodes.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOTS = ("src", "agent_fleet", "scripts", "setup", "tests")

#: The species vocabulary is NOT hardcoded here either — `pcn|pdn` catches domain species that
#: by design never appear in `policy/task_kinds/`, and the structural names are read from the
#: seed so a new seeded species enters the population without editing this file.
_DOMAIN = r"(?:pcn|pdn)_[a-z_]+"

KIND_TEMPLATE = r"""['"]({alts})['"]"""
NEXT = re.compile(r"""\b(next_step|next_state|dispatch_next|then_step|_TRANSITIONS|chaining)\b""")


def _seeded_kinds(repo: pathlib.Path) -> list[str]:
    d = repo / "policy" / "task_kinds"
    return sorted(p.stem for p in d.glob("*.yaml")) if d.is_dir() else []


def _tracked_py(repo: pathlib.Path) -> list[str]:
    """Enumerate via ``git ls-files`` rather than a directory walk.

    TRACKED FILES ARE THE POPULATION. A walk also sees build output, virtualenvs and stray
    scratch copies — which inflates the audit with sites nobody can fix — and on this
    filesystem a naive `rglob` over the source roots does not finish inside two minutes, so
    the walk was also the reason the first derivation produced nothing at all.
    """
    import subprocess

    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--", *[f"{r}/**/*.py" for r in ROOTS],
         *[f"{r}/*.py" for r in ROOTS]],
        capture_output=True, text=True, check=True,
    ).stdout.split("\n")
    return sorted({p for p in out if p.endswith(".py")})


def population(repo: pathlib.Path) -> dict[tuple[str, str], int]:
    alts = "|".join([_DOMAIN, *(re.escape(k) for k in _seeded_kinds(repo))])
    kind = re.compile(KIND_TEMPLATE.format(alts=alts))
    pop: dict[tuple[str, str], int] = {}
    for _ in (0,):
        for rel in _tracked_py(repo):
            p = repo / rel
            try:
                txt = p.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001 — an unreadable file is not a silent zero
                print(f"UNREADABLE: {p}", file=sys.stderr)
                continue
            for m in kind.finditer(txt):
                k = (rel, "kind:" + m.group(1))
                pop[k] = pop.get(k, 0) + 1
            for m in NEXT.finditer(txt):
                k = (rel, "next:" + m.group(1))
                pop[k] = pop.get(k, 0) + 1
    return pop


def main() -> int:
    repo = pathlib.Path(__file__).resolve().parents[1]
    pop = population(repo)
    if not pop:
        # A DERIVATION THAT FINDS NOTHING IS A BROKEN DERIVATION, not a clean repo. The audit
        # would then be trivially complete and would stay complete through any regression.
        print("EMPTY POPULATION — the derivation is broken, not the repo clean", file=sys.stderr)
        return 2
    rows = [{"site": f, "pattern": p, "count": n} for (f, p), n in sorted(pop.items())]
    print(json.dumps(rows, indent=2))
    prod = [r for r in rows if not r["site"].startswith("tests/")]
    print(f"\n# {len(rows)} sites, {len(prod)} non-test, "
          f"{len({r['site'] for r in rows})} files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
