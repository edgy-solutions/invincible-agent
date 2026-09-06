---
status: BUILT AND SEALED — awaiting a prime for the response shape
date: 2026-09-05
engine: engine-cost
---

# `package_export` — packaging as a governed emit

ADR-0047 says a computation export is a **governed emit**. Until now it was a script, which is
the difference between *"we built a package"* and *"the platform produces packages"*.

## Why a verb and not a script

A script leaves no trace. Run it twice, or run it for the wrong party, and afterwards the two
are indistinguishable from each other **and from never having run at all**. As a verb it is
entitlement-scoped at the point of production, emits an audit line naming what went to whom
under which algorithm version, and is refusable by the machinery that refuses every other verb.

## Contract D

| end | class | |
|---|---|---|
| input | `cost:DisclosureRecipient` | `subClassOf prov:Agent` |
| output | `cost:ExportPackage` | `subClassOf mesh:Response` |

**The subject is the RECIPIENT, not a lot.** The verb is asked *"what may this party be shown"*,
so the entitlement scope is the question rather than a filter applied to an answer computed for
someone else. Getting this wrong would have made the verb a report with an access check bolted
on, which is the shape that leaks.

`recipient_scope` is **spoken-mandatory**, derived from the signature. There is no default party
and no all-lots fallback: a disclosure verb invocable without naming its recipient is one
keystroke from the wrong programme reaching the wrong party, and the output looks correct either
way.

Refusals stay typed (ADR-0049 Ruling 4): a missing scope is `NotInModel`, an **unknown** scope is
`Unentitled`, an absent Pyodide runtime is `SourceUnavailable`. A caller must not be able to read
*"we do not disclose to you"* as *"we have no data"*.

## Same-algorithm applies to the packager

The verb imports `build_cost_package.build_html` and calls it. It does not reimplement the
build. A faithful copy would still make **every seal in the export suite a statement about a
different artifact than the one a recipient opens** — and the JavaScript gate and the manifest
hashing are load-bearing here precisely because they are the same code. Sealed by replacing
`build_html` with a sentinel and requiring the verb to fail there; a copy sails past.

The verb also runs `check_javascript` before writing. A verb that skipped it could report
success over a page that is blank on open.

## The blind axis: four tables checked, six that must agree

The engine's boot check compared `VERBS`, `OUTPUT_URI`, `INPUT_URI` and the slot declarations —
and let **`CATALOGUE`** and **`_DESCRIPTIONS`** drift.

> A verb present in `VERBS` and absent from `CATALOGUE` is servable by direct call and
> **invisible to the mesh**: the engine boots, reports healthy, answers when addressed by name,
> and is never routed to.

That is the same shape as the reregister hook's hand-kept directory map, which stopped at one
engine and hid every engine added after it. The boot check now reads all six, and two seals hold
it there — one comparing the tables, one asserting the boot check itself still reads all six.

**The second of those was asserting on the neighbour.** It sliced `main.py` from the boot check
to the next `class`, which swallowed the registration loop below it — and that loop also mentions
`CATALOGUE`, so the seal passed with the boot check gutted. Caught by a mutation that should have
gone red and did not. Now scoped to the function via the AST.

## Verified end to end

    output_uri         http://invincible-agent/cost#ExportPackage
    recipient_scope    notional-customer-alpha
    lot_count          5        verified_lots 5
    artifact           cost-validation-notional-customer-alpha.html   18,464,858 bytes
    dataset            cost-notional-customer-alpha.duckdb
    module_hashes      {'pricing.py': 'sha256:21e61050...'}
    audit              disclosed_to / disclosed_by / at / algorithm_sha / locator / lots

The response carries the commit, the locator, both dataset hashes and the module hash, so a
caller holding it can say which package this was **without reopening the artifact**.

## Bite-checks

| mutation | red |
|---|---|
| the verb skips the JavaScript gate | 1 |
| an unknown recipient becomes `NotInModel` | 1 |
| `recipient_scope` gets a default | 1 |
| the emission discloses every lot | 1 |
| a verb absent from `CATALOGUE` | 2 |
| the boot check narrowed back to four | 1 (**0 before the slice was scoped**) |

**104 seals green.**

## Owed

The **prime** for `cost:ExportPackage` and `cost:DisclosureRecipient`. Held until the cluster is
quiet — Lane 1's enumerate fan-out may roll engine-o. Until it runs, the verb is servable by
direct call and not yet routable.
