---
id:         suite-unrunnable-on-windows-native
status:     closed
owner:      unassigned
blocked-on:
closed-by:  20a7e00
closed-by-note: NO COMMIT CLOSED THIS — a measurement did, and the seal is right to ask. Nothing in the tree changed; `uv run --frozen --extra agent-fleet python -m pytest tests/` returned 1538 passed / 0 failed / 0 collection errors on the same tree that produced the original finding. The packet was a wrong conclusion drawn from a right observation, and the correction is a re-measurement rather than a fix. Citing an unrelated sha to satisfy the field would have been the borrowed-attribution shape this seal exists to refuse.
code-site:  .venv.wsl, pyproject.toml, tests/test_lock_coherence.py
repo:       invincible-agent
summary:    CLOSED 2026-08-21, and the finding was MY INVOCATION, not the tree. `uv run --frozen --extra agent-fleet python -m pytest tests/` gives 1538 passed / 167 skipped / 0 failed / ZERO collection errors in 12:08 — all three named causes gone (rdflib and smolagents come from the extra; WinError 1920 never fires). `.venv.wsl` still exists and is still untraversable by a bare Windows interpreter, so the observation was real; the conclusion that the SUITE was unrunnable was wrong. The repo's own test docstrings already prescribed the uv form. The N-minus-7 qualifier this packet asked people to attach to local results is WITHDRAWN — it would have made every correct green read as provisional.
---

# CLOSED — the suite runs fine; I was invoking it wrong

**Resolution 2026-08-21.** Everything below was measured accurately and concluded wrongly, and
the correction is worth more than the original finding.

```
uv run --frozen --extra agent-fleet python -m pytest tests/ -q
1538 passed, 167 skipped, 8 warnings in 728.34s (0:12:08)
```

Zero failures. **Zero collection errors** — all seven collectors that broke under the bare
interpreter load here. `rdflib` and `smolagents` come from the `agent-fleet` extra, and
`WinError 1920` never fires even though `.venv.wsl` is still present and still untraversable
by `py.exe`.

**The observation was real; the diagnosis was not.** I measured a bare `py -m pytest`, found
seven broken collectors and 33 failures, and concluded the ENVIRONMENT was structurally
narrow. The actual fact was narrower and duller: I used an invocation the repo does not use.
`tests/test_archetypes_are_declared.py`'s own docstring prescribes the uv form verbatim, and
so does the guidance in AGENTS.md's neighbourhood. I read neither before generalising from my
own run.

**The rule this packet asked for is WITHDRAWN.** It told readers to attach "N-minus-7
collectors; rdflib and smolagents absent" to any local suite result. That qualifier is now
false, and worse than false — it would make every correct green read as provisional, which is
the precise cost of an over-broad honesty caveat. Quote a `uv run` result plainly. Quote a
bare `py -m pytest` result not at all, because it is measuring the wrong environment.

**What survives, and it is small but real:** a bare Windows interpreter cannot walk this tree
because of `.venv.wsl`, and `tests/test_lock_coherence.py` / `test_no_floating_git_dependencies.py`
die at COLLECTION on it rather than skipping. Disposal option 3 below — teaching those two
tree-walks to skip reparse points — remains independently worth doing, because a tree-walk
that dies on a symlink is a latent defect on any machine that grows one. It is not filed as
blocking anything.

---

## Correction 2026-08-22 — two things the closure got wrong

**1. THE CLASS WAS FOUND 16 DAYS EARLIER AND I RE-DISCOVERED IT AS NEW.**
[`suite-signal-session.md`](suite-signal-session.md) §"instrument defects", 2026-08-05:

> the main tree had `agent_fleet/restate_analyst/.venv.wsl`, whose `lib64` symlink Windows
> cannot stat, crashing three tree-walking tests with `OSError: [WinError 1920]` before they
> asserted anything.

Same symlink class, same error number, same three-ish tests. That session banked it as an
**instrument-defect lesson** ("a baseline in a different filesystem state is not a baseline")
and did not convert it into a guard — so the walks stayed unfixed and the defect fired again on
2026-08-21 against a different reader. `agent_fleet/restate_analyst/.venv.wsl` is STILL in the
tree today.

That is the finding worth more than the fix: **a banked lesson that is not converted into a
guard recurs on schedule.** `tests/_treewalk.py` is the conversion this class was owed in
August, and the prior instance is what earns it rather than my own re-discovery.

**2. "THE SUITE RUNS FINE" IS TRUE OF AN ENVIRONMENT THAT IS NOT CI'S.**
The closure quoted 1538 passed and implied the environment question was settled. It was not —
there are THREE environments here, not two, and I measured the one that matches CI least:

| environment | interpreter | matches CI? |
|---|---|---|
| bare `py` | Windows, CPython 3.11 | no |
| `uv run` → `.venv` | **Windows**, CPython 3.11 | no — this is what I measured |
| `.venv.wsl` | **Linux, CPython 3.12** | **yes** — ubuntu-latest / 3.12 per the workflows |

`.venv.wsl` is a Linux venv living in the shared tree (its `pyvenv.cfg` points at
`/home/…/cpython-3.12-linux-x86_64-gnu`). It is the CI-matching environment, and I could not
run the suite in it: **it has 251 packages and no pytest** — a runtime venv without dev
dependencies. Populating it is a write to a developer's environment and was not mine to make
unasked.

So the honest scope of every green quoted in this arc: **Windows, CPython 3.11, via `uv run`.**
That is a real signal and it is not a CI signal. A Linux/3.12 run remains unmeasured by me.

---

## The original finding, kept for the record

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
