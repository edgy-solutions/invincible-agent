---
id:         runbook-5s-pre-build-check-fails-on-the-baseline
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    Runbook §5 tells you to verify the flat import before building an image, with `cd agent_fleet/<engine>_agent && PYTHONPATH= python -c "import main"`. That command FAILS on unmodified master — `agent_fleet/planning_agent/main.py:316` imports `agent_fleet.utils.version_endpoint` at module level, and `utils` is only a flat sibling inside the image. So the check cannot pass in a checkout for any engine importing `utils` at module level, and the first thing a lane sees when running it is a pre-existing failure they will read as their own. Fix is a check that reproduces the image's sys.path, not a ninth caveat.
---

# §5's pre-build check fails on the baseline, so nobody will run it twice

**The runbook's own words are "Check it before you build the image, because CI will not"** —
`docs/runbooks/adding-an-engine.md` §5. That instruction is right and the check behind it does not
work in the place it tells you to run it.

## Measured, 2026-09-11, on `73e308e`

| where | command | result |
|---|---|---|
| **unmodified master** | `cd agent_fleet/planning_agent && PYTHONPATH= python -c "import main"` | `ModuleNotFoundError: No module named 'agent_fleet'` at **`main.py:316`**, on `from agent_fleet.utils.version_endpoint import mount_version` |
| `lane/74` (slot extraction) | same | same error at **`main.py:34`** — earlier, because `slots.py` now imports `utils.slot_declarations` at module level |
| either tree, image layout simulated (`PYTHONPATH=…/agent_fleet`, cwd = engine dir) | `import slots` | **passes**, declarations correct |

## Why it fails, and why that is not a code defect

In the built image `/app` IS the engine directory and `utils` is a **flat sibling**, put there by
`.github/workflows/build-containers.yml:356` — `COPY agent_fleet/utils/ /app/utils/`. In a checkout
the same two modules are `agent_fleet/<engine>_agent/` and `agent_fleet/utils/`, so with `PYTHONPATH`
cleared, neither the flat name `utils` nor the packaged name `agent_fleet.utils` resolves. The
engine is fine. The **check** cannot reproduce the layout it is checking.

## Why this is worth a packet rather than a caveat

**A check that fails on the baseline for an unrelated reason is a check nobody runs twice.** The
first lane to try it reads a pre-existing failure as damage they caused, spends the time, finds it
was always there, and stops running it — which loses the real protection §5 exists for. That
protection is not hypothetical: §5 records that getting the import order backwards cost Engine P a
full roll, where **twelve registrations were skipped while the engine reported perfectly healthy.**

It also currently discriminates nothing: it fails identically whether the flat import is right or
wrong, which is the [[a-green-seal-can-be-green-for-the-wrong-reason]] shape inverted — a red that
carries no information.

## The fix, and what it must not be

**Not** a caveat added to §5 saying "this may fail, ignore line 316" — that trains a reader to
ignore the output of a check whose whole value is its output.

Reproduce the image's `sys.path` instead. The simulation used above is one line and discriminates
correctly:

```bash
cd agent_fleet/<engine>_agent && PYTHONPATH=../../agent_fleet python -c "import main; print(len(main.VERBS))"
```

`agent_fleet/` on the path makes `utils` importable by its flat name, exactly as `/app` does, while
cwd keeps the engine's own modules flat. **Verify the fixed check still goes RED on a real fault**
before trusting it — invert one engine's try/except order and require a failure — or this packet
will have replaced a red that means nothing with a green that means nothing, which is worse.

## Definition of done

1. §5's command replaced with one that passes on unmodified master.
2. The replacement shown RED against a deliberately inverted import order, and the evidence recorded
   in the runbook beside it.
3. A line in §5 naming why the naive form cannot work, so the next person does not "simplify" it
   back to `PYTHONPATH=`.
