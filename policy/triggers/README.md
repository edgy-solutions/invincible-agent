# `policy/triggers/` -- the SEED half of the case triggers (ADR-0039)

A trigger row names the selection table an event is decided by, the fact a case is keyed on, and
the facts that make two events one episode. `case_routing.load_triggers` composes this directory
with every `policy/overlays/<name>/triggers/` through the shared composer.

**This directory is STRUCTURAL, and empty on purpose.** Every trigger in the repo today is a
programme's, so it lives in an overlay. The directory exists, and is baked into the image, so the
loader's seed path is a real place rather than an absence: a platform trigger added here later
ships with the image on arrival instead of failing at intake in production only.

No two overlays may declare one trigger; the loader refuses it.
