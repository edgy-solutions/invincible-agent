---
id:         suite-unrunnable-on-windows-native
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  .venv.wsl, pyproject.toml, tests/test_lock_coherence.py
repo:       invincible-agent
summary:    A Windows-native `py -m pytest tests/` run STRUCTURALLY EXCLUDES 7 collectors before any change is made — `.venv.wsl/lib64` is a WSL symlink Windows cannot traverse (WinError 1920) and two optional extras are absent (rdflib, smolagents). Measured 2026-08-20: 33 failed / 1277 passed / 178 skipped / 7 collection errors, every failure attributable to those three causes. This is a STAMP-AXIS fact about where tests run: a green from this environment is a green over N-minus-7 collectors, and that qualifier belongs wherever a suite result from this machine is cited, until the venv is rebuilt native or the runs move to WSL.
---

# The suite cannot run on the Windows-native interpreter, and its results look like ordinary failures

Running `py -m pytest tests/` under Windows-native Python 3.11 produces a result that reads
like a broken tree. It is not. The failures have three named, environmental causes and none of
them is a defect in the code under test.

Measured 2026-08-20 on `5066909` plus an unrelated docs change:

```
33 failed, 1277 passed, 178 skipped, 7 errors in 322s
```

The same tree is recorded as **1377 passed / 0 failed** in-order under WSL/Linux — and again
under `--random-order-seed=8817` — in the 2026-08-17 suite-signal session handoff. That handoff
lives in the cross-agent session log **outside this repo**, which is why it is named here rather
than linked: a repo-relative path to it would be a citation the tree can never satisfy. (The
first draft of this packet cited it as `docs/../sessions/…` and `test_citation_paths.py` refused
it — the seal working on the packet that exists to describe seals working.)

## The three causes

| cause | count (sampled) | shape |
|---|---|---|
| `ModuleNotFoundError: No module named 'rdflib'` | 22 | optional extra absent from this interpreter |
| `ModuleNotFoundError: No module named 'smolagents'` | 8 | optional extra absent from this interpreter |
| `OSError: [WinError 1920]` on `.venv.wsl/lib64` | 6 (+ collection errors) | WSL symlink; Windows cannot traverse the reparse point |

The seven collection errors are the sharpest part. `tests/test_lock_coherence.py` and
`tests/test_no_floating_git_dependencies.py` walk the tree looking for `uv.lock` files and hit
`.venv.wsl/lib64` — **at import time, during collection.** Their tests never run at all. Five
more collectors fail on the absent extras.

## Why this is filed rather than shrugged at

**A collection error removes a test file from the population silently.** `-q` reports it in a
line that reads much like a failure, and the run still prints a large green count. Anyone
citing "the suite passes on my machine" from this environment is making a claim over a
population that is missing seven files' worth of tests — including two that exist specifically
to police dependency hygiene.

That is the same species as
[`a-green-check-proves-only-its-scope`](../principles/a-green-check-proves-only-its-scope.md),
arriving through the environment rather than through the assertion. The check is honest; its
*scope* is silently smaller than the reader assumes.

It is also a **stamp-axis fact** — a property of *where* the run happened, not of what it
tested. Stamp-axis facts have to travel with the result or they evaporate, which is why this
packet exists rather than a comment somewhere.

## The rule until this closes

Any suite result quoted from a Windows-native run carries the qualifier: **"N-minus-7
collectors; rdflib and smolagents absent; `.venv.wsl` untraversable."** A result without that
qualifier is over-claiming.

Targeted runs of files that do not import the missing extras are unaffected and may be quoted
plainly — that is what makes the environment usable at all for documentation and
single-subsystem work.

## Disposal options (not yet chosen)

1. **Rebuild the venv native on Windows** with the full extras — closes it for local runs, but
   the extras' own Windows support is unverified.
2. **Move local runs into WSL** — matches CI exactly, and the `.venv.wsl` name suggests this was
   the original intent. Cheapest correct answer if WSL is already provisioned.
3. **Teach the two tree-walking tests to skip reparse points** — narrows the blast radius from
   seven collectors to five, and is worth doing regardless of 1 or 2 because a tree-walk that
   dies on a symlink is a latent defect on any machine that grows one.

Option 3 is independently useful and does not depend on choosing between 1 and 2.
