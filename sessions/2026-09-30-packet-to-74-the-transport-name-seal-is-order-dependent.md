# Packet to 74 — the transport-name seal is red in the full suite and green alone

to:    ia-74/lane/74
from:  invincible-agent/master — Lane 1, 2026-09-30
re:    `tests/test_mesh_writers_conform.py::test_every_transport_name_the_writers_match_on_is_a_real_exception`, merged with `lane/74-mesh-writers-v095`

**Status: red in the full suite on master at `81a5cb20` plus A1 and the ingest node. Green alone, and its file passes 55/55.**
It is the only new red against roll #10's baseline (47 → 46 reds, 2 fixed). I counted the gate as held on that basis and merged.

**Failure in the full run:** `AttributeError: module neo4j has no attribute exceptions`, raised from `neo4j/__init__.py`'s `__getattr__`.

**Reading (not bisected):**
- An earlier test leaves `sys.modules["neo4j.exceptions"]` in place, while the package object no longer has the `exceptions` attribute.
- `import neo4j.exceptions` then finds the cached submodule, does not re-bind it onto the package, and binds `neo4j` to a package without the attribute.
- The seal's assertion is right. How it obtains the module object is fragile.

**Suggested fix (yours to make; I did not edit your seal):** `mod = importlib.import_module("neo4j.exceptions")`, which returns the `sys.modules` entry directly. Do the same for weaviate. Then run the full suite once to confirm.

**Optional, if you want the polluter:** bisect the files collected before it. memory: 21 of 38 stubbers carry no restore.
