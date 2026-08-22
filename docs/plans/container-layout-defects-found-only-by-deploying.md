---
id:         container-layout-defects-found-only-by-deploying
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  .github/workflows/build-containers.yml
repo:       invincible-agent
summary:    FOUND 2026-08-22 by deploying Engine P FOUR times. The agent image is built with `COPY ${AGENT_DIR}/ /app/` under `WORKDIR /app`, so agent modules run FLAT — a layout the repo's 1679-test suite cannot exercise, because in the repo they are a package. THREE defects of this class shipped: `types.py` shadowing the stdlib (interpreter died before main.py), bare relative imports (`attempted relative import with no known parent package`), and — the important one — a GUARDED `agent_fleet.*` import that failed to ImportError and set the helper to None, so twelve registrations were skipped in SILENCE while the pod stayed healthy. Both are now sealed statically by tests/test_agent_modules_survive_flat_layout.py, but the seals enumerate KNOWN failure modes; a third is not covered by construction. The fourth defect was predicted BY THIS PACKET an hour before it was found, and the seals written for the first two could not catch it. PROPOSAL: run `python -c "import <main_module>"` inside the built image before pushing it. Needs care — an agent whose import path touches the network or requires env vars would start failing its build, and whether that is a defect or a deliberate design is per-agent.
---

# Three deploys to find defects a one-line smoke test would have caught

Engine P went to the cluster three times on 2026-08-22. Each roll found one defect, each
defect took a full build-and-roll cycle to surface, and **none of them were visible to the
test suite** — 1679 tests passed over all three.

## What the layout is

`.github/workflows/build-containers.yml` builds every agent with:

```
WORKDIR /app
ARG AGENT_DIR
COPY ${AGENT_DIR}/ /app/
```

So `agent_fleet/planning_agent/*.py` become `/app/*.py` — top-level modules at the head of
`sys.path`, with **no parent package**. In the repo the same files are
`agent_fleet.planning_agent.*` — namespaced and unambiguous.

Every property that depends on that difference is a **stamp-axis fact**: true of where the
code runs, not of what it says. The unit suite cannot see them by construction.

## What it cost, concretely

| roll | defect | symptom | visible to tests? |
|---|---|---|---|
| 1 | `image.tag: ""` → chart appVersion | `ImagePullBackOff` | no — chart values |
| 2 | `types.py` shadows stdlib `types` | interpreter died before `main.py` | no — package layout |
| 3 | `from . import measures` | `attempted relative import with no known parent package` | no — package layout |
| 4 | `from agent_fleet.utils… import` — guarded, no flat arm | **none.** Pod healthy, probes green, zero verbs registered | no — package layout |

Rolls 2, 3 and 4 are the **same root cause** and were fixed one deploy apart each, because
every fix addressed the instance rather than the class.

**Roll 4 is the one that matters**, and it was predicted by an earlier draft of this packet
before it was found. It had no symptom at all: the import was wrapped in `try/except
ImportError`, so the crash became a `None` and twelve registrations were skipped without a
log line. The engine served `/health`, passed every probe, and the Predicate count sat at 52
across two settled reads. **A try/except makes the crash go away without making the import
work** — which converts a loud boot failure into a healthy-looking engine that answers
nothing.

That is why the static seals are not the fix. They were written after defects 2 and 3, they
are good, and they were blind to 4 by construction — 4 is well-formed Python that resolves
in the repo. Each new mode needs a new rule, written after the deploy that found it.

## Now sealed — and the limit of that

`tests/test_agent_modules_survive_flat_layout.py` covers both known modes, reads the
workflow's own build matrix so new agents are included automatically, and asserts the matrix
still parses so it cannot silently match nothing.

**The limit is worth stating.** Those seals enumerate failure modes *already observed*. A
fourth way the flat layout bites — a `sys.path` assumption, a data file resolved relative to
`__file__`, a namespace-package edge — is not covered, and would again be found by rolling.

Writing the relative-import rule also took **three attempts**, and the two wrong ones were
each caught by a false positive against a deployed, working engine:

- grep `from .` flagged four modules in `neo4j_expert` (guarded fallback arm — fine);
- "must be in the except arm" flagged `presentation_agent/capability_registry.py:112`
  (inverse ordering, relative first — also fine).

Two idioms coexist in the fleet and the seal must not prefer one. That is an argument that
static rules about this layout are **harder to get right than they look**, which strengthens
the case for testing the artefact instead of the source.

## Proposal — smoke the built image

After `docker buildx build`, before push:

```
docker run --rm <image> python -c "import ${MAIN_MODULE}"
```

This catches every member of the class at once, including modes nobody has enumerated,
because it exercises the real artefact in the real layout.

**Why this is a proposal and not a commit.** It changes the build for all twelve agents. An
agent that opens a connection, reads a required env var, or contacts the mesh **at import
time** would begin failing its build — and whether that is a latent defect or a deliberate
design is a per-agent question that must be answered before the gate goes on, not after it
starts blocking pushes. Enabling it broadly without that survey would be the same species of
error as the probe sweep that nearly replaced eleven deliberate TCP liveness checks.

Multi-arch adds a wrinkle: `buildx --push` does not leave a local image to run, so the smoke
needs either a `--load` single-arch pass or a `docker run` against the pushed digest.

## Disposal

1. Survey what each agent's `main` does at import time — cheap, and the answer is useful on
   its own.
2. If the survey is clean, add the smoke step for all agents at once.
3. If some agents are not import-safe, gate it per-agent via a matrix flag, defaulting ON,
   and record next to each opt-out WHY that agent cannot be imported cold.
