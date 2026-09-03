---
id:         board-attribution-cannot-match-a-line-numbered-code-site
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
ruled-by:   ADR-0040 (BOARD as generated index) — this item is a DEFECT in the generator's seal, not a change to the board's model
code-site:  scripts/generate_board.py
summary:    generate_board.py's ATTRIBUTION check compares the commit's touched paths against `code-site` VERBATIM, so a site written with line numbers (`src/iagent/defs/agent_routers.py:110-117`) can never equal the touched path (`src/iagent/defs/agent_routers.py`). A commit that edits EXACTLY the declared site is reported as touching "neither the packet nor any declared code-site" and forced to carry `closed-by-note:`. 15 of 95 items with a code-site have EVERY site line-numbered, so for those the attribution seal cannot fire on the true positive and its escape hatch becomes mandatory paperwork. Found 2026-09-02 closing engine-b-trigger-asset-cannot-succeed, whose commit touched the declared file and was still UNATTRIBUTED.
---

# The board's attribution seal cannot match a code-site that carries line numbers

**Found 2026-09-02**, closing [[engine-b-trigger-asset-cannot-succeed]]. Its `code-site` names
`src/iagent/defs/agent_routers.py:110-117`; the closing commit edited that exact file; the seal
reported it as touching **neither** the packet nor any declared code-site.

## The defect

`scripts/generate_board.py:165-168` builds the target set by splitting `code-site` on commas and
stripping whitespace only:

```python
targets = {i["_file"]}
if i.get("code-site"):
    targets |= {t.strip() for t in i["code-site"].split(",") if t.strip()}
if not (touched & targets):
```

`touched` comes from `git show --name-only`, which emits repository paths. `targets` may contain
`path:110-117`. The intersection is empty for every line-numbered site, whatever the commit did.

## Why it is worse than a cosmetic mismatch

**The seal's own comment states the stakes:** *"a seal that produces false failures on legitimate
closures gets overridden, and an overridden seal is a dead one."* This is that false failure, and
the override is already built in — `closed-by-note:` — so the failure mode is silent. The note was
designed as the honest escape for a closure that legitimately touched neither target. Here it is
demanded for a closure that touched the target precisely, which converts a deliberate exception
into routine paperwork and trains the next author to fill it in without reading it.

**Measured, not estimated.** 95 plan items declare a `code-site`. **25** have at least one
line-numbered site; **15** have every site line-numbered, so for those the attribution check can
only ever pass via `_file` — the plan file itself — and a fix that lands before the packet is closed
never touches that.

## The fix, and the reason it is filed rather than done

One line: compare on the path prefix, e.g. strip a trailing `:<digits>...` from each target before
intersecting. But **this tightens a seal for every packet on the board at once** — items currently
passing on `closed-by-note` would start being checked for real, and some may not survive it. That is
a ruling for the board's owner, not a drive-by from a lane that happened to trip it.

**Do not verify by watching the generator print `wrote docs/BOARD.md`.** It printed that with the
defect present. Verify by closing a packet whose commit touches a line-numbered code-site and
nothing else, with `closed-by-note` ABSENT, and confirming it passes.

## Related

- [[engine-b-trigger-asset-cannot-succeed]] — the closure that tripped it.
