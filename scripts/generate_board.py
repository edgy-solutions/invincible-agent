#!/usr/bin/env python3
"""Generate docs/BOARD.md from docs/plans/*.md YAML headers (ADR-0040).

THE BOARD IS A PROJECTION, NEVER A SOURCE. Status lives in each packet's own header; this
script only re-indexes it. That is the entire reason it will not rot — nobody maintains it,
and a drift test asserts the committed file matches what these headers produce.

Run:  python scripts/generate_board.py            # rewrite docs/BOARD.md
      python scripts/generate_board.py --check    # exit 1 if committed board is stale
"""
from __future__ import annotations
import pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLANS, BOARD = ROOT / "docs" / "plans", ROOT / "docs" / "BOARD.md"
VOCAB = ["in-flight", "blocked-on-human", "open", "parked", "closed"]


def headers():
    out = []
    for p in sorted(PLANS.glob("*.md")):
        t = p.read_text(encoding="utf-8")
        if not t.startswith("---\n"):
            continue
        blk = t.split("---\n", 2)[1]
        # Match spaces/tabs only, NEVER newlines. With \s* an EMPTY `closed-by:` consumed the
        # line break and captured the following line, so the value read
        # "repo: invincible-agent" and the sha check reported it unresolvable — a parser bug
        # masquerading as a data error, which is the most expensive kind to read.
        h = dict(re.findall(r"^([a-z-]+):[ \t]*(.*)$", blk, re.M))
        if not h.get("id"):
            continue
        h["_file"] = f"docs/plans/{p.name}"
        out.append(h)
    return out


def coverage_line():
    """The board must disclose its OWN incompleteness, in the artifact rather than around it.

    Six items read as the whole board unless the board says otherwise. The honesty previously
    lived in a conversation report — which is exactly the location ADR-0040 exists to evacuate.
    """
    total = len(list(PLANS.glob("*.md")))
    headered, legacy = 0, 0
    for p in sorted(PLANS.glob("*.md")):
        t = p.read_text(encoding="utf-8")
        if not t.startswith("---\n"):
            continue
        blk = t.split("---\n", 2)[1]
        if any(l.startswith("id:") and l.split(":", 1)[1].strip() for l in blk.splitlines()):
            headered += 1
        else:
            legacy += 1
    return (f"_Coverage: **{headered} of {total} packets indexed** — {legacy} carry pre-ADR-0040 "
            f"legacy frontmatter, {total - headered - legacy} are unheadered. "
            f"Closing that gap is the migration._")


def render(items):
    coverage = coverage_line()
    L = ["# BOARD — invincible-agent", "",
         "**Generated — do not hand-edit.** Status lives in each item's packet header;",
         "`scripts/generate_board.py` re-indexes them and a drift test asserts this file matches.",
         "Hand-editing here is a lie the next regeneration silently reverts.", "",
         coverage, ""]
    for s in VOCAB:
        rows = [i for i in items if i.get("status") == s]
        if not rows:
            continue
        L += [f"## {s}", ""]
        for i in sorted(rows, key=lambda r: r["id"]):
            L.append(f"- **{i['id']}** — {i.get('summary','')}")
            bits = [f"status: {i['status']}", f"owner: {i.get('owner','') or 'unassigned'}"]
            # WHICH REPO. The field has always been parsed and never rendered, so a reader
            # scanning the board could not tell that a third of the open work lives in
            # dag-tools and doc-tools rather than here. That mattered little while findings
            # were mostly platform-side; the work deploy inverted the ratio. Rendered only
            # when it is NOT this repo — the common case stays quiet, the exception is loud.
            if (i.get("repo") or "").strip() not in ("", "invincible-agent"):
                bits.append(f"repo: {i['repo'].strip()}")
            if i.get("blocked-on"):
                bits.append(f"blocked-on: {i['blocked-on']}")
            # A trigger is rendered because a parked item whose firing condition is invisible
            # is a parked item nobody will un-park.
            if i.get("trigger"):
                bits.append(f"trigger: {i['trigger']}")
            if i.get("closed-by"):
                bits.append(f"closed-by: {i['closed-by']}")
            L.append(f"  {' · '.join(bits)}")
            L.append(f"  → [{i['_file']}]({i['_file'].replace('docs/','')})")
            L.append("")
    return "\n".join(L).rstrip() + "\n"


def main():
    # AN UNRECOGNISED FLAG MUST NEVER FALL THROUGH TO A WRITE.
    #
    # This script's only arg test used to be `if "--check" in sys.argv`, so EVERY other
    # invocation took the write path — including `--help`. `tests/test_board_drift.py`'s
    # positive control runs exactly that (`generate_board.py --help`) to prove the generator is
    # runnable, and so REWROTE docs/BOARD.md on every suite run. Two consequences, both silent:
    #
    #   1. It destroyed uncommitted board edits in the working tree. Observed 2026-08-27: a
    #      hand-added entry present at session start was gone after one pytest run.
    #   2. It made the drift seal VACUOUS as a suite. The positive control regenerates the
    #      board, so `test_board_matches_the_packet_headers` compares the board against the
    #      headers its SIBLING just projected it from, and cannot go red however far the
    #      committed board had drifted.
    #
    # (2) is the same "aspirational seal" that file's own docstring was written to diagnose,
    # reintroduced by the file itself. The write is now reachable ONLY by a bare invocation.
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        print(__doc__ or ""); return 0
    unknown = [a for a in argv if a != "--check"]
    if unknown:
        print(f"unknown argument(s): {' '.join(unknown)}\n", file=sys.stderr)
        print(__doc__ or "", file=sys.stderr)
        return 1

    items = headers()
    # A PARKED item must name what would un-park it. `blocked-on` is a dependency; `trigger`
    # is a firing condition (something becomes true, possibly with nobody working on it).
    # Neither present means "parked forever with an empty field", which is indistinguishable
    # from forgotten — the July bank-rule, finally indexed.
    stale = [i["id"] for i in items
             if i.get("status") == "parked"
             and not (i.get("blocked-on") or "").strip()
             and not (i.get("trigger") or "").strip()]
    if stale:
        print("UNTRIGGERED: parked with neither blocked-on nor trigger: " + ", ".join(stale))
        return 1
    bad = [i for i in items if i.get("status") not in VOCAB]
    if bad:
        print("VOCABULARY: not one of " + "|".join(VOCAB) + ": " +
              ", ".join(f"{i['id']}={i.get('status')!r}" for i in bad)); return 1
    # closed-by must RESOLVE **and** touch the packet — a resolving sha is not a correct sha.
    for i in items:
        sha = (i.get("closed-by") or "").strip()
        if not sha:
            if i["status"] == "closed":
                print(f"UNBACKED: {i['id']} is closed with no closed-by sha"); return 1
            continue
        # A FOREIGN-REPO SHA IS NOT RESOLVABLE HERE, AND THAT IS NOT A DEFECT. The board now
        # indexes work in dag-tools and doc-tools (the work deploy inverted the ratio), and
        # `git cat-file` in THIS repo cannot see those commits. Failing on them would force
        # the honest choice — record the sha that actually closed it — to be spelled as a
        # lie or omitted. So the sha checks (resolution AND attribution) apply only to
        # packets whose work landed here; a foreign sha is recorded, rendered, and trusted,
        # because this repo has no standing to verify it.
        if (i.get("repo") or "").strip() not in ("", "invincible-agent"):
            continue
        r = subprocess.run(["git", "cat-file", "-t", sha], cwd=ROOT, capture_output=True)
        if r.returncode != 0:
            print(f"UNRESOLVABLE: {i['id']} closed-by {sha} does not resolve"); return 1
        # ATTRIBUTION, not merely existence. A resolving sha is not a correct sha: the seed
        # board cited a sha that resolved cleanly and was the WRONG COMMIT (a follow-up fix,
        # not the closure). It passed every seal while claiming evidence for another change.
        # So the commit must TOUCH the packet or its declared code site.
        files = subprocess.run(["git", "show", "--name-only", "--format=", sha],
                               cwd=ROOT, capture_output=True, text=True).stdout
        touched = {ln.strip().replace("\\", "/") for ln in files.splitlines() if ln.strip()}
        targets = {i["_file"]}
        if i.get("code-site"):
            targets |= {t.strip() for t in i["code-site"].split(",") if t.strip()}
        if not (touched & targets):
            # HONEST ESCAPE HATCH. A real closure can legitimately touch neither — the work
            # landed elsewhere, or the packet was written after the fact. Requiring a stated
            # reason keeps that case legal WITHOUT letting the seal be silently ignored; a
            # seal that produces false failures on legitimate closures gets overridden, and
            # an overridden seal is a dead one.
            if not i.get("closed-by-note"):
                print(f"UNATTRIBUTED: {i['id']} closed-by {sha} touches neither "
                      f"{i['_file']} nor any declared code-site. Add `closed-by-note:` "
                      f"explaining why, or cite the commit that did the work."); return 1
    text = render(items)
    if "--check" in sys.argv:
        cur = BOARD.read_text(encoding="utf-8") if BOARD.exists() else ""
        if cur != text:
            print("DRIFT: docs/BOARD.md does not match the packet headers. Regenerate."); return 1
        # `??`, not a bare `?`: a lone question mark is legitimate prose ("retire the loader?")
        # and checking for it would booby-trap every summary. The sentinel must be a string
        # nobody writes by accident.
        if "??" in cur or "<unreconciled>" in cur:
            print("UNRECONCILED: a '??'/<unreconciled> marker survives in the committed board.")
            return 1
        print(f"board is current ({len(items)} items)"); return 0
    BOARD.write_text(text, encoding="utf-8")
    print(f"wrote {BOARD.relative_to(ROOT)} — {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
