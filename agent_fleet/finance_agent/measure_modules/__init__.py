"""Measure modules for engine-fin — ADR-0053 §1.

A measure module declares its inputs and outputs with types, carries its own VERSION, performs
NO I/O, and is deterministic. The version is the module's own rather than the engine's: bumping
it is a claim that the figures may change.

── WHY THIS DIRECTORY IS UNDER finance_agent AND NOT SHARED ────────────────────────────────
ADR-0053 §2 makes a module pluggable and explicitly contemplates a customer's module living
outside this repo. That argues for a shared location. It is HERE anyway, for one mechanical
reason stated so the next author does not read it as a considered architectural preference:
the engine images flatten `agent_fleet/<engine>/` to `/app`, so this tree is already carried
into the image, and a new top-level package needs image plumbing in every engine's build. The
shared location is §2's question and is not answered here.

── WHAT IS NOT DONE, so this is not read as §2 complete ────────────────────────────────────
THERE IS NO POLICY REGISTRY ROW. §2 says a method is a row in `policy/`, and that "a module on
disk with no row is INVISIBLE". That is true of this module: nothing selects it, and it is
reachable only because `measures.py` imports it by name. The registry, its seeding and its
validation are §2's build.

They are deliberately not in this commit. §7 requires the extraction to stand alone with the
seal green before and after, and adding a registry in the same change would make the green
cover the conjunction — the exact error §7 exists to prevent, committed while following §7.
"""
