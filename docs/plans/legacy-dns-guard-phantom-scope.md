---
id:         legacy-dns-guard-phantom-scope
status:     open
owner:      unassigned
blocked-on: 
closed-by:  
code-site:  tests/routing/test_no_legacy_dns_references.py
repo:       invincible-agent
summary:    DISPROVED guard — `SCANNED_DIRS` lists "doc-tools", which is a SIBLING REPO not a subdirectory, so the walker skips it silently and passes green while the forbidden pattern is live in the unscanned tree.
---

# A guard that has never scanned one of its declared targets — and passes green

> ## FIXED 2026-08-11
>
> **The status read was "described or committed?" — the answer was described.** `SCANNED_DIRS`
> still listed `doc-tools` and the walker still did `if not base.exists(): continue`.
>
> Three changes, and the third is the one that makes it a repair rather than an edit:
>
> 1. **`doc-tools` removed** from `SCANNED_DIRS` — it is `../doc-tools`, a sibling repo. Scanning
>    a sibling needs it checked out at a known path and revision; that is a different mechanism
>    and is not bought by naming a string in a tuple.
> 2. **A missing scan root now FAILS** instead of being skipped, in the guard itself and in a
>    standalone `test_every_declared_scan_root_EXISTS` — split out so the failure names the right
>    defect. *"The guard cannot see what it claims to cover"* and *"the forbidden pattern is
>    present"* are different problems, and a reader who confuses them fixes the wrong one.
> 3. **Break-on-purpose**: `test_a_phantom_scan_root_FAILS_the_guard` injects an impossible root
>    and asserts **both** the existence check and the scan refuse. Without this leg the repair
>    would be unproven — and the old `continue` would have made such a test pass by doing nothing,
>    which is exactly how `doc-tools` stayed declared-and-unread.
>
> Plus `test_no_scan_root_names_a_sibling_repo`, which pins the mistake **by shape**: `doc-tools`
> was not a typo, it was a real tree one level up, which is why it looked right to everyone who
> read the list. The check is on the relationship, not on the string.
>
> **What this does NOT do:** it does not scan doc-tools. The coverage that was falsely claimed is
> now honestly absent, which is the correct intermediate state — `[[check-from-the-consumers-side]]`
> is where the cross-repo mechanism belongs.
>
> **ONE GUARD, not one file I happened to open.** An unfiltered whole-tree search (not the
> gitignore-respecting one) finds `SCANNED_DIRS` in exactly one file — no second copy, no vendored
> duplicate carrying the same phantom root. Run because "I fixed the instance I was looking at" is
> the weak form of a repair.
>
> **The limit of that claim, stated so it is not over-read:** it bounds *this* guard, keyed on the
> name `SCANNED_DIRS`. It says nothing about whether OTHER guards declare scopes they never read
> under different variable names. That is the general question — *which guards assert coverage
> they cannot deliver?* — and it is unasked, not answered.

**This is a disproved guard, not a missing one**, which is why it is filed above the sweep row that
found it. A missing guard is a known gap. A disproved guard is a *claim of coverage* that is false,
and it has been reported green on every run.

## The defect

`tests/routing/test_no_legacy_dns_references.py` declares its scope:

```python
SCANNED_DIRS = ("agent_fleet", "src", "scripts", "helm", "doc-tools", "tests", "setup")
```

and walks it:

```python
for d in SCANNED_DIRS:
    base = root / d
    if not base.exists():
        continue          # <-- doc-tools lands here, every run, silently
```

**`doc-tools` is a sibling repository, not a subdirectory.** It lives at `../doc-tools`, so
`invincible-agent/doc-tools` does not exist, `base.exists()` is `False`, and the entry is skipped
without a word. The guard believes it covers doc-tools. It has never read a byte of it.

## And the forbidden pattern is live in the unscanned tree

Found by the repo-4 sweep, `doc_tools/assets/semantic_linker.py:8`:

```python
ONTOLOGY_SVC_URL = os.getenv("ONTOLOGY_SERVICE_URL",
                             "http://ontology-agent-svc.default.svc.cluster.local:8084")
```

`.default.svc.cluster.local` is exactly the pattern this guard exists to forbid, sitting as a
**fallback default** — the failure mode the guard's own docstring describes: a fresh bootstrap where
the env var is unset, the service registers an unreachable URL, and dispatch silently fails for that
route.

So the guard is not merely uninformative about doc-tools. **It is green while its target is
violated, in the one tree it names and cannot see.**

## The family — third instance, same shape

*Green because the population is empty; empty because the scope is wrong.*

| instance | how the population emptied |
|---|---|
| the SDK's `git+`-matching tests | subjects evacuated by an index migration |
| the litany's `/health` probe | exempted by its own fix |
| **this** | scanned path does not exist |

Each passed. Each was measuring nothing. The through-line is that **an absence-check cannot
distinguish "nothing forbidden here" from "nothing here"** — and neither can its reader, because both
render as a green dot.

## The fix — both halves; the second is the durable one

1. **Drop `"doc-tools"` from `SCANNED_DIRS`.** It is the honest half: a test in this repo cannot scan
   a sibling repo, and claiming otherwise is the lie. (If doc-tools genuinely needs this guard, it
   needs its *own* copy, in its own repo, where the path resolves — that is a separate decision and
   the same one ADR-0040's `repo:` field exists to route.)

2. **Make a missing scanned path FAIL, not `continue`.** This is what prevents the next entry rotting
   the same way. A scanned directory that does not exist is a *configuration defect in the test*, and
   it should say so rather than quietly shrinking its own scope:

   ```
   assert base.exists(), f"SCANNED_DIRS names {d!r}, which does not exist — the guard's scope is
                           silently smaller than it claims"
   ```

   **A scan asserts its scope is inhabited.** Same rule as `_KNOWN_UNPINNED` being empty by
   construction, and the reason the `??` board sentinel is absence-checked.

3. Seal it break-on-purpose: add a nonexistent directory to `SCANNED_DIRS` and confirm the suite goes
   **red** rather than passing with a smaller scope.

## Scope note — read, not assumed

The other six entries (`agent_fleet`, `src`, `scripts`, `helm`, `tests`, `setup`) **do** exist in this
repo, so the guard's coverage of the platform tree is real and its green there means something. The
defect is confined to the one entry that names another repository. Stated so the fix is not
over-scoped into "the guard is worthless" — it is one entry wrong, and one structural weakness that
let the wrongness stay silent.
