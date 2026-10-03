# `policy/triggers/` -- the SEED half of the case triggers (ADR-0039)

A trigger row names the selection table an event is decided by, the fact a case is keyed on, and
the facts that make two events one episode. Two lists refuse an event at intake. `requires`
refuses a fact that is absent OR null, because a later table matches on it. `carries` refuses
only an absent key: a null, a list or an empty mapping is an answer. Use it where the null is
itself the business state, such as `nearest_spare` when no site has stock.
`case_routing.load_triggers` composes this directory with every `policy/overlays/<name>/triggers/`
through the shared composer.

**This directory is STRUCTURAL.** A programme's trigger lives in an overlay. The directory is
baked into the image, so a platform trigger added here ships with the image on arrival instead of
failing at intake in production only.

**The first platform trigger is `origin_suggestion`** (ruled platform-generic 2026-10-02). Every
deployment confirms the origin of an artifact nobody can read yet. What differs per deployment is
who stewards a domain, and that is a grant on `origin_confirmation:<domain>`, not a row here.

No two overlays may declare one trigger; the loader refuses it.
