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


def render(items):
    L = ["# BOARD — invincible-agent", "",
         "**Generated — do not hand-edit.** Status lives in each item's packet header;",
         "`scripts/generate_board.py` re-indexes them and a drift test asserts this file matches.",
         "Hand-editing here is a lie the next regeneration silently reverts.", ""]
    for s in VOCAB:
        rows = [i for i in items if i.get("status") == s]
        if not rows:
            continue
        L += [f"## {s}", ""]
        for i in sorted(rows, key=lambda r: r["id"]):
            L.append(f"- **{i['id']}** — {i.get('summary','')}")
            bits = [f"status: {i['status']}", f"owner: {i.get('owner','') or 'unassigned'}"]
            if i.get("blocked-on"):
                bits.append(f"blocked-on: {i['blocked-on']}")
            if i.get("closed-by"):
                bits.append(f"closed-by: {i['closed-by']}")
            L.append(f"  {' · '.join(bits)}")
            L.append(f"  → [{i['_file']}]({i['_file'].replace('docs/','')})")
            L.append("")
    return "\n".join(L).rstrip() + "\n"


def main():
    items = headers()
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
        r = subprocess.run(["git", "cat-file", "-t", sha], cwd=ROOT, capture_output=True)
        if r.returncode != 0:
            print(f"UNRESOLVABLE: {i['id']} closed-by {sha} does not resolve"); return 1
    text = render(items)
    if "--check" in sys.argv:
        cur = BOARD.read_text(encoding="utf-8") if BOARD.exists() else ""
        if cur != text:
            print("DRIFT: docs/BOARD.md does not match the packet headers. Regenerate."); return 1
        if "?" in cur:
            print("UNRECONCILED: a '?' marker survives in the committed board."); return 1
        print(f"board is current ({len(items)} items)"); return 0
    BOARD.write_text(text, encoding="utf-8")
    print(f"wrote {BOARD.relative_to(ROOT)} — {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
