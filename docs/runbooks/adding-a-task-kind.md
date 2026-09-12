---
iri: docs:runbook-adding-a-task-kind
# Every target must exist in the graph — the invented-IRI rule (ADR-0037 §1). This list is
# therefore ONE ENTRY. A task kind is a DECLARATION, not a mesh verb: nothing registers it, no
# verb creates one, and there is no `mesh:TaskKind` class. Minting an IRI so this edge looked
# fuller is exactly what the gate refuses. The one real target is the species the grouped
# disposition review IS — confirmed present at setup/ontologies/mesh_system.ttl:179.
explains:
  - mesh:DispositionReview
doc_kind: how-to
audience_hint: architect
---

# Adding a task kind

**Written 2026-09-11, from the commits that added the declaration layer** (`a51c392`,
`db9f32c`, `2b631be`, and two corrections: `05759b8`, `f00f68b`). Every step below is one I
took, and the two most useful paragraphs are things I got wrong first.

**Scope.** A *task kind* is a species of human task — what its card looks like and which verbs
it accepts. This covers adding one. It does **not** cover adding an **archetype** (a new *card
shape*); if your kind needs a rendering that does not exist, that is
[`adding-an-archetype.md`](adding-an-archetype.md) and it comes first, because the archetype
vocabulary is closed and the declaration model will refuse an unknown one.

**Order of work.** Everything here is authoring — no cluster, no seed window. That is the point:
the expensive mistakes are cheap at this stage, and §0 is the one that is expensive later.

> **⚠ THIS PAGE DESCRIBES AN INTERVAL, NOT AN ENDSTATE.** M3.3 is mid-flight. The declaration
> layer is live and the two code tables it replaces are *still standing*, gated on cortex-ui's
> parity seal. So today you write the row **and** the code table entries, and the seals force
> them to agree. When the cutover lands, sites 2 and 4 disappear and this warning goes with
> them. A page that hid the interval would read as finished and mislead on its first use.

## §0 — The kind string, claimed before anything else

**It is not the hard part and it is the expensive one.** The kind is a live value in
`human_task_projection` rows and simultaneously a UI render contract, so renaming it later needs
expand/contract with a dual-read interval. Get it right while it is free.

**A colon is forbidden, and this is not style.** Authz audience keys are
`<audience>:<compartment>`, and a task kind has been spelled identically to one before —
`pcn_disposition` the render contract versus `pcn_disposition:` the grant key. The colon is the
only thing telling them apart, which is why `tests/test_cross_repo_contracts.py` forbids the
*colon-suffixed* form and deliberately permits the bare one. The declaration model rejects a
colon outright.

**Check all three namespaces for your candidate, not one:**

```bash
ls policy/task_kinds/                                   # declared species (seed)
grep -rn "<candidate>" src/iagent/human_tasks.py        # the verb table
grep -rn "<candidate>" ../cortex-ui/src/lib/taskKindRegistry.ts   # the render table
grep -rn "<candidate>:" policy/task_grants.yaml         # DIFFERENT namespace — audience keys
```

**Seed or overlay?** A *structural* species (`access_request`, `workflow_ack`) goes in
`policy/task_kinds/`. A *domain* species goes in a work-side ADR-0036 overlay and **may not**
enter this repo — `test_no_domain_name_entered_the_platform_seed` fails the build if it does.
That boundary is structural rather than lexical on purpose: there is no row here to put a domain
name in, which is why the domain-named kind already in flight is being left alone rather than
renamed.

## The sites, each with the seal that names its absence

| # | site | what goes in | the seal that catches you |
|---|---|---|---|
| 1 | `policy/task_kinds/<kind>.yaml` (or your overlay) | `kind`, `renders_as{badge ≤12, title ≤80, archetype}`, `accepts`, optional `reason_required` | `test_declarations_validate_against_the_sdk_models` · `test_no_domain_name_entered_the_platform_seed` |
| 2 | `src/iagent/human_tasks.py` → `_VERBS_BY_KIND` | **only if** your verbs differ from `approved`/`rejected` | `test_every_code_row_is_declared_and_agrees` — and the reverse, `test_every_declared_kind_not_in_the_code_table_restates_the_default` |
| 3 | `src/iagent/human_tasks.py` → `_REASON_REQUIRED` | the verbs that are meaningless without a reason | `test_reason_required_agrees_with_the_code` · `test_reason_required_is_reachable_in_every_row` |
| 4 | `cortex-ui/src/lib/taskKindRegistry.ts` → `REGISTRY` | badge, title, archetype — must match site 1 exactly | **NONE IN THIS REPO.** cortex-ui's parity seal is pending; until it lands nothing catches a skew between sites 1 and 4 |
| 5 | whatever mints the task | the `kind` string reaching `human_task_projection` | none — a kind nothing emits is invisible, not red |

**`accepts` is required and has no default.** A row that could inherit its verbs is a row that
silently gets someone else's, and the species that needed one extra verb would grow a
`kind == "…"` branch in code instead — the exact thing the declaration layer deletes. An empty
`accepts` is legal and means *rendered, not actionable*.

## What this page cannot distinguish

**Every seal above reads a file.** They are pre-flight checks on your *edit*. Not one of them is
a post-condition on a running system, and three specific claims sit outside their reach:

**A seal over a declaration cannot see a deployment.** Green after site 1 means the row is
declared and well-formed. It is not evidence that any deployment composes your overlay, that the
UI bundle shipped with your registry row, or that a task of your kind renders at all. Those are
cluster claims and this repo has no check for them.

**Declared is not enforced.** `reason_required` on a row does *nothing at runtime today*.
`validate_decision` checks `decision in _REASON_REQUIRED` — a module-level set of verb strings,
consulted **without reference to kind**. So reason-required is currently a property *of a verb*,
global wherever it appears, while the declaration makes it a property *of a row*. Per-species is
the endstate and it arrives with the cutover; a row written in anticipation is inert until then.
I told another lane this property was "free". It is not, and for a disposition that must carry a
reason, declared-and-unenforced is the whole gap.

**And the one where the obvious repair was the harmful one.** The render table's default used to
carry a comment stating it *"now renders the card in a NO-VERB read-only mode … so an
unregistered kind degrades visibly"*. **No such mode existed.** `ApprovalTaskCard` rendered
Approve/Reject unconditionally, and `isRegisteredKind` — the predicate written to prevent exactly
this — was exported, documented, and had **no caller outside its own tests**.

I repeated that comment as fact — in a module docstring, a test name, and a commit message —
until another lane traced the render. **The tell transfers: an exported helper whose only callers
are its own tests, and a note whose subject is a cause while its claim is about an effect.** The
lane that owns a registry is the least likely to check it, precisely because it is theirs.

> **⚠ CORRECTED 2026-09-12 — the render half is FIXED, and the gap it leaves is narrower and
> one-sided.** `ApprovalTaskCard` now default-denies: `const declared = isRegisteredKind(...)`
> gates the verb block, an undeclared kind gets a refusal naming the species rather than a
> disabled button, and `isRegisteredKind` finally has a caller. **The gateway half is still
> open**: `verbs_for_kind` returns `_DEFAULT_VERBS` for any kind it does not know, so an
> undeclared kind still ACCEPTS `approved`/`rejected` over the API.
>
> So the state is now a UI that offers nothing sitting over an API that would take the answer —
> defence on the surface only, and a caller bypassing the card can still dispose a species nobody
> declared. **My cutover closes it**; until then this is the live half. Kept rather than deleted,
> because a page that quietly dropped a defect once it was half-fixed would be the same failure
> as the comment above, inverted.

> This is why site 5 is listed with **no seal** rather than omitted. Absence of a check is a fact
> about the route; a row that quietly stopped at site 4 would read as complete coverage.

## Order matters, and only for two reasons

**The archetype must exist before the row names it.** The vocabulary is closed
(`GROUPED_REVIEW`, `APPROVAL_TASK`, `TRIAGE_TASK`) and the model refuses anything else — a
deliberate refusal, because an open archetype lets a species name a rendering nobody implements,
which renders blank rather than refusing.

**Sites 1 and 2 land together.** The parity seal asserts them equal in *both directions*, so
either alone is red. That is the intended friction: containment is not equality, and one
direction would let a declaration add a species the code never had.

Everything else is order-free.

## Errors hit, and what each one teaches

| what happened | the general lesson |
|---|---|
| Believed a read-only no-verb mode existed because a comment described one; propagated it into three artifacts | **A comment asserting an effect is not evidence of the effect.** Trace the call path before repeating a note as fact |
| Told a lane `reason_required` was free; it validates but does not enforce, and its semantics change at cutover | A field that *validates* a property is not a field that *enforces* it. Ask which consumer reads it |
| Bumped the SDK pin in one `pyproject.toml`; `test_domain_broker_sdk_version_matches_the_fleet_pin` went red with *"the fleet's own SDK pins disagree"* | A coherence seal firing on **your** change is the seal working. 14 pyprojects, 16 locks and one Helm value move together, because `uv lock --check` is what the build asks via `--locked` |
| Reported my own commit as unpushed and held; a peer checked `git merge-base --is-ancestor` and it was pushed | **A lane's account of its own state is not evidence.** A lane that believes its work unpushed either redoes it or sits on it, and neither is visible from outside |
| Needed an arm that could not run until a dependency shipped, and did not want a skip | `xfail(strict=True)`: the day the dependency lands it XPASSes, strict turns that into a failure, and **the failure is what removes the marker**. A plain skip sits green forever and the rows never get validated |
| *(cortex-ui's, worth stealing)* A refusal test asserted the kind name appeared in `document.body` — but the card header prints the kind two lines above the refusal, so a mutation stripping the name **out of the refusal** still passed | **Scope the assertion to the element under test, never the page.** When the instrument and the subject share a surface, the instrument reads the subject's neighbour and reports success. Their fix asserts against `[data-undeclared-kind]`. Any seal for a card that also prints its kind in a header has this trap |

## The shortest correct sequence

1. Pick the kind string. Run the four `grep`s in §0. Decide seed vs overlay.
2. Confirm your archetype exists; if not, stop and go to
   [`adding-an-archetype.md`](adding-an-archetype.md).
3. Write `policy/task_kinds/<kind>.yaml` (or the overlay row) with its own `accepts`.
4. If your verbs are not `approved`/`rejected`, add the `_VERBS_BY_KIND` row — and
   `_REASON_REQUIRED` if a verb is empty without a reason.
5. Add the `REGISTRY` row in cortex-ui, matching badge/title/archetype **exactly**.
6. `uv run --frozen --with pytest pytest tests/test_task_kind_declarations_match_code.py -q`
   — eight arms. A red one names your missing site.
7. Wire whatever mints the task to emit your `kind`. **Nothing checks this**; verify it by
   reading a `human_task_projection` row, not by a green suite.
