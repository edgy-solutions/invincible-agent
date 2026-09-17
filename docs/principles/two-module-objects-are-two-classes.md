# The two-module-objects-are-two-classes law

> **This fleet's flatten-first dual import loads one file as TWO module objects. That is invisible
> for functions and data, and silently fatal for anything named in an `except` or an `isinstance` —
> because two module objects mean two distinct classes with the same name, and a handler written
> against one does not catch the other.**

## The convention, and why it exists

34 modules in this repo import their siblings flat-name-first with a package fallback:

```python
try:
    from state_sparql import sparql_lit          # the deployed container flattens the package
except ImportError:                              # pragma: no cover - import path differs by runtime
    from agent_fleet.ontology_service.state_sparql import sparql_lit
```

The reason is real: the image flattens `agent_fleet/ontology_service/` and has no `agent_fleet`
package, so the flat name is the only one that resolves there. **Nothing about this is wrong.**

## What it costs when both paths resolve

In a test run, a tool, or any process where the package IS importable, both spellings work — and
Python caches them as **separate entries in `sys.modules`**. The file executes twice. Two module
objects. Every class defined in it exists twice.

For a function that is harmless: two equal functions compute the same answer. For a **class**, and
above all an **exception class**, it is a defect with no symptom at the point of failure:

> `read_outcome.SubstrateUnavailable` and
> `agent_fleet.ontology_service.read_outcome.SubstrateUnavailable` are **different classes**. A
> caller writing `except SubstrateUnavailable` against one path **does not catch** the one raised
> through the other. The refusal sails past the handler written to receive it and surfaces as an
> unhandled error — the exact opposite of the outcome the refusal existed to produce.

## The instance — 2026-09-17, and it read as a test-isolation nuisance

Engine O's `execute_sparql` was changed to refuse rather than return `[]` when a substrate could
not be asked. Three arms driving the real function passed standalone and **failed in the full
suite**, with the refusal raised and its detail string exactly correct:

```
MeshResult(outcome='failed', mode='rdflib',
           detail='execute_sparql: jena: ConnectionError: connect timeout; ...')
read_outcome.SubstrateUnavailable: execute_sparql: jena: ConnectionError: connect timeout; ...
```

`pytest.raises(SubstrateUnavailable)` simply did not match it. `main.py` had bound the class by the
flat path; the test had imported it by the package path; the full suite put both on `sys.path` and
the standalone run did not.

**It looked like flaky test isolation and it was a production bug.** Any consumer of that refusal
would miss it the same way, in the same conditions, with nothing in the logs saying why.

## The rule

- **A module defining an exception type — or any class used in `isinstance` — imports
  package-path FIRST**, with the flat name as the fallback. This costs nothing where the package is
  absent (it falls straight through) and guarantees one canonical class where the package exists.
  Deviating from the surrounding flat-first blocks is correct here, so **say why at the site**: the
  next reader copies the neighbours.
- **Pin it with an arm** asserting the package import appears before the flat one — and key that arm
  on the **module paths**, not the imported names. A first version keyed on
  `read_outcome import StoreAttempt` broke the moment another name joined the import, and *a check
  that reds when formatting moves is a check nobody keeps.*
- **The hazard is identity, not exceptions.** Anything whose identity crosses the boundary carries
  it: exception classes, sentinels, `Enum` members, registry keys, `dataclass` types used with
  `isinstance`. Equality of **value** survives dual import; **identity** does not.

## Why it hides

A handler that never fires looks exactly like a handler that never needed to fire, and the failure
only appears where *both* import paths resolve — which is tests and tooling, the places whose
verdict gets dismissed as environment noise.

It belongs beside [naming-a-class-is-not-a-guard](naming-a-class-is-not-a-guard.md), from the other
side: there, a class is named and guards nothing; here, a class IS the guard and the name resolves
to the wrong one. And beside
[a-surviving-mutation-means-you-cannot-tell-yet](a-surviving-mutation-means-you-cannot-tell-yet.md)
— **no mutation of the handler can find this, because the handler is not what is wrong.** It is
correct, reachable, and simply not the class that was thrown.
