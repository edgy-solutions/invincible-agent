---
# EXPLAINS IS EMPTY, FOR THE REASON rolling-a-service.md ESTABLISHED (register R-015). A fleet pin
# is an infrastructure act. The mesh declares four lowercase verbs and 72 classes and NOT ONE of
# them concerns versions, packages or dependency resolution, so there is no contract-depth target
# and minting `mesh:pinSdk` is exactly the move the invented-IRI gate (ADR-0037 §1) refuses.
iri: docs:runbook-pinning-the-fleet-sdk
explains: []
doc_kind: how-to
audience_hint: ARCHITECT
---

# Runbook — pinning the fleet to an SDK release

**You want this when** the `iagent-mesh` SDK has a release the fleet should be on. Worked from two
pins done back to back on 2026-09-15/16 — `v0.8.1 → v0.9.1` and `v0.9.1 → v0.9.2` — and every
**DISCOVERED** line below cost somebody something.

> **THE PIN IS ONE VALUE BY CONSTRUCTION. You cannot pin one engine.** `test_lock_coherence`
> asserts the fleet's SDK pins are a single value and that the broker's `meshSdkVersion` equals
> it. **DISCOVERED** — a lane tried "bump engine-o only, a fleet change is not a lane's", which
> sounds like restraint, and the seal refused it. Bumping one engine is not a smaller version of
> the act; it *is* the act, done wrongly (R-071).

---

## 0. The tag must exist before you touch a pyproject

The pin points at a **tag**, and `uv lock` resolves it from the remote.

    git -C <sdk> fetch origin --tags
    git -C <sdk> rev-parse --short v<VERSION>^{commit}

**DISCOVERED:** pinning a tag that is not yet published fails during lock resolution *looking like
a network problem*. Sixteen locks failing that way is a diagnosis you do not want to start from.

**DISCOVERED — a dispatched version number is a claim about the world, and the world may already
have acted on it.** `v0.9.0` was dispatched as the release to pin. It already existed, was an
ancestor of the SDK's master, was on PyPI, and **did not contain the guard the pin was for**. Five
commits had landed on top of it. Pre-flight before cutting or pinning:

| check | why |
|---|---|
| tag resolves locally and on origin | it exists at all |
| `merge-base --is-ancestor <tag> origin/master` | already cut, or the tip? |
| PyPI **version-specific** endpoint | see below |

**DISCOVERED:** query `pypi.org/pypi/<pkg>/<version>/json`, **not** the package index. The index
endpoint is cached ~15 minutes and reported a release as failed when it had succeeded.

## 1. Move every declaration in one commit

    git ls-files | grep 'pyproject.toml$' | xargs grep -l 'iagent-mesh-sdk.git@v<OLD>'

Sixteen pyprojects at the time of writing, plus:

* `helm/invincible-agent/values.yaml` → `domainBroker.meshSdkVersion`
* `helm/invincible-agent/Chart.yaml` → **bump `version:`**

**DISCOVERED:** the chart bump is not optional and is easy to forget, because the thing you edited
was `values.yaml`. R-070's working-tree arm catches it *before the commit*; the release workflow
catches it after the push, when R-030 has already made the remedy a follow-up commit.

Then verify the absence, not just the presence:

    git ls-files | xargs grep -ln 'iagent-mesh-sdk.git@v<OLD>\|meshSdkVersion: "v<OLD>"'

## 2. Regenerate every lock

One `uv lock` per directory holding a pinned pyproject. Report `ok`/`fail` counts rather than
assuming — a single failure in the middle of sixteen is silent if you only look at the last line.

    git ls-files | grep uv.lock$ | xargs grep -ln 'v<OLD>'      # must be empty

## 3. The gate

    uv run --frozen pytest tests/test_lock_coherence.py tests/test_chart_version_tracks_chart_content.py

This is what makes it one commit rather than sixteen.

## 4. Verify at the CONSUMER, not the pin string

A pin string is a claim. The resolved artifact is the fact. Read the installed package:

    uv run --frozen python -c "import iagent_mesh, pathlib, inspect; \
      d = pathlib.Path(inspect.getfile(iagent_mesh)).parent; \
      print((d/'transport_auth.py').read_text().count('_FASTAPI_MISSING'))"

Assert the thing the pin is **for** — the symbol, the guard, the contract shape — is present in
the installed tree.

> ### **AND THE CHECK THE VERSION NUMBER CANNOT MAKE**
>
> **Pinning forward must not lose what the previous pin was for.**
>
> A higher version number is not evidence that the last pin's content survived. Assert the
> PREVIOUS pin's reason still holds in the new artifact, by name. Moving `v0.9.1 → v0.9.2`, the
> check was `_FASTAPI_MISSING` still at 4 occurrences — 0.9.2 was cut for a rename and had no
> reason to touch the guard, which is exactly why nothing else would have noticed if it had.
>
> This is the one line of this page that no version comparison, changelog or lockfile diff
> replaces, because both artifacts are internally consistent and only their *pair* is wrong.

## 5. Roll, and do not split the fleet

A pin that is committed and not rolled is a fleet running the old SDK with a repo that says
otherwise. Roll with hooks if the release changes anything the prime loads.

Census after settle, with its **real exit code** — `$?` after a pipe is the pipe's.

---

## What this page does not cover

* **Cutting the tag** — the SDK lane's. Ask for the sha; do not cut one to unblock yourself.
* **Deprecation intervals.** A rename ships as expand/contract: new name plus a delegating alias
  raising `DeprecationWarning`. **The alias contracts in a LATER release, once no in-fleet caller
  uses it** — so a pin that introduces an alias also starts a clock, and the callers move inside
  the same window or the misleading name stays readable.
* **Which release to pin.** Three lanes each held one reason `v0.9.0` was wrong and none could
  have produced the other two (R-074). Ask; do not infer from the number.
