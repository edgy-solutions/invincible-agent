# ADR-0067 — One identity per thing (a reference to openddil ADR-0056)

**Status:** Reference. Accepted 2026-11-07 (architect, via Chris). The decision is not made here and is not
restated here. This record holds only what iagent builds from it. Nothing below is built yet.
**Decided in:** `openddil-contracts/decisions/ADR-0056-one-identity-per-thing-every-other-id-is-an-alias.md` at `2894f0c`
**Date:** 2026-11-07
**Deciders:** architect; Chris (ADR-0056's four edits and its five rulings are his, 2026-11-07)
**Related:**
  - openddil: ADR-0056 at `2894f0c` is the one text. Both sides cite it, and neither keeps a second copy (its Status).
  - openddil: ADR-0055, for labels; ADR-0056 §7 closes its §6 gap.
  - iagent: [ADR-0064](ADR-0064-classification-propagates-through-derivation.md). Its asset of record (the physical
    platform's URN) is a locator under ADR-0056 §7. Here it becomes an alias row of the platform's identity.
  - iagent: ADR-0065 (the where-used graph, obsolescence), which ADR-0056 §8 cites ahead of time. It is drafted
    separately.
  - iagent: `invincible-agent#283`, the case's `episode_id`, which this record realigns (below).

---

## Where the decision is

- **The text.** It is `decisions/ADR-0056-one-identity-per-thing-every-other-id-is-an-alias.md` in
  `edgy-solutions/openddil-contracts`, at commit `2894f0c6030696c72ea38d72626af4281fd97958` ("ADR-0056: accepted as
  proposed with Chris's four edits").
- **Where that commit lives.** It is the head of openddil-contracts PR #4. When this record was written
  (2026-11-07), that PR was open, stacked on `docs/adr-labels-draft`, and not on `main`.
  - GitHub keeps `refs/pull/4/head`, so the sha stays fetchable.
  - The pin is the commit, not a branch. A later commit to that branch changes nothing here until the pin moves.
- **What the pin guarantees.** The index check (below) proves that the sha exists in that repository and holds that
  file. It does not prove the text is unchanged on `main` after a merge. A merge that rewrites the text is a new
  commit, and moving the pin to it is a deliberate edit to this record.

## What iagent builds from it

Each item names the ADR-0056 section it realises. iagent adds no rule of its own.

1. **Alias rows and binding rows live in the graph, written through `graph_mapping`** (§2, §6, §7).
   - An alias is a row `{scheme, value, authority, valid_from[, valid_to]}`.
   - A binding is a row `{asset_id, identity, bound_at, bound_by, declaration}`.
   - `graph_mapping` is the registry entry that takes a column to an alias lookup and then to a node. It is iagent's
     to build. ADR-0056 names it and does not decide it ("What this does not establish").
   - A new connected system adds rows. It never adds a column or a property on the node.
2. **The catalog URN is an alias row, never minted as an identity** (§7).
   - A dataset keeps its URN, and the URN is a locator.
   - The platform's URN is an alias of the platform's identity, under the catalog's scheme.
   - Nothing parses it (§2, ADR-0047), and no identity is derived from its text.
   - The identity is a UUID v7, `urn:uuid:<uuid>` (§1). It is minted by the authority that owns the thing, only after
     a lookup has failed. An observation never mints.
3. **Events across the seam carry both `asset_id` and the identity** (§2).
   - iagent reads both, and parses neither.
   - An event whose lookup key finds no binding row is kept under its `asset_id` (§3).
4. **Episode and occurrence ids are scoped to the entity** (§5).
   - **Episode:** a uuid5 over (identity, component, fault code).
   - **Occurrence:** the episode plus `detected_at_ns`.
   - Kind and owning tier are attributes of the record, never part of the id (ruling 1).
5. **The era is read from the binding row, never from the id** (§6).
   - An episode keeps its era-1 id until its asset has a bound identity.
   - An episode that is open at the binding keeps its id until it closes (ruling 2).

## #283's derivation, aligned

**What #283 serves today (0.4.81, rev 228).**
- When the event carries the source's own episode id, the case serves it, with `episode_id_source: event`. CM's id is
  the episode id (ruling 1), so this arm already agrees with ADR-0056 and does not change.
- When the event carries none, the case serves the platform's derived key, with `episode_id_source: derived`. That key
  is `ep-` plus 32 hex of a sha256 over `[trigger, [the trigger's episode facts]]` (`case_routing.episode_key`).
  This arm departs from ADR-0056 in two places:
  - **The trigger name is in the seed.** It is the platform's analogue of kind, which ruling 1 takes out.
  - **It is not a uuid5.** For the same fault, it cannot equal the id CM issues (Check 8).

**What the alignment builds (a code PR after this record).**
- **The derived episode id becomes CM's function.**
  - It is a uuid5 under `uuid.NAMESPACE_URL` over `episode|<fact>|<fact>|<fact>`, with no trigger name in it.
  - The facts are the trigger's declared `episode` list, in order. The overlay row names them, and the code names no
    fact (the 10-30 rule).
  - For a fault CM has seen, the derived id then equals CM's id.
- **Era 1.** The first fact is `asset_id`. This is CM's seed today (finding 1): `episode|{asset_id}|{component}|{fault_code}`.
- **Era 2.** The first fact is the identity.
  - ADR-0056 §5 states the tuple and not the seed string. iagent takes the string from openddil's era-2 minter when
    it lands, and does not guess it.
  - Until then the derivation builds era 1 only. It refuses era 2 by name; it does not produce an id that may disagree.
- **The open-episode rule (ruling 2).**
  - An event whose era-1 id matches an open case attaches to that case, even when the event now carries an identity.
  - The next episode opens under the era-2 id.
- **The occurrence.** iagent serves the occurrence id the event carries. When the event carries none, iagent derives
  it by the same rule, as the episode plus `detected_at_ns`.

**The ids already issued.** These are the `ep-` keys served since 0.4.81 rolled.
- They stay as issued. They are read as issued and never re-derived (ADR-0056 §6's first-occurrence rule).
- They keep `episode_id_source: derived`.
- How many exist has not been read. The decision ledger is not read without approval.

**So there are two eras, and an iagent-local prefix ahead of them.**
- **Era 1 and era 2** are ADR-0056's eras.
- **The `ep-` keys** are not an era. They are iagent's derived names from before this alignment, and their `ep-`
  prefix tells them apart from a uuid by form. That is not a parse: no field is read from the key's text, and the key
  is compared and stored only.

## Deltas

**Nil.** iagent adopts ADR-0056 as written, at `2894f0c`. If a delta is ever needed, it goes to openddil as a proposal
against ADR-0056. It is not written here.

## Check

- **The index check pins the sha** (`tests/test_reference_adrs_pin_their_source.py`, and the workflow
  `.github/workflows/reference-adr-pins.yml`).
  - A reference ADR's `**Decided in:**` line names a repository, a path and a short sha.
  - The short sha must prefix the full sha in `.github/<repo>.ref`.
  - The workflow fetches that commit from the other repository and asserts the path exists in it.
  - It runs on every PR that touches `docs/adr/**` or a `.ref` pin, and daily, because a PR ref can be force-pushed
    off a commit.
  - A run that finds no reference ADR fails, and does not pass as empty.
- **The alignment PR's seals.**
  - An era-1 derivation equals CM's pinned seed for one fixture fault.
  - No trigger name appears in the seed.
  - An `ep-` key already issued is served unchanged.
  - An open case keeps its era-1 id across a binding.

## What this does not establish

- Nothing is built: no alias row, no binding row and no `graph_mapping`.
- It decides nothing that ADR-0056 leaves to openddil, such as era 2's seed string and who mints which identity.
- It does not move any id already issued.
