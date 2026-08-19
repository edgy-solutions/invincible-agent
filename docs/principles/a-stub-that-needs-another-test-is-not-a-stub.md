# The a-stub-that-needs-another-test-is-not-a-stub law

> **A test double that installs itself only when `sys.modules` doesn't already hold the
> name is not a double — it is a bet on collection order. The suite's green becomes a
> property of the order it was collected in, not of the code it claims to test.**

The line was already written in this repo, in the comment on the dagster stub fix
(`5a2d5c9`): *"A stub that works by depending on another test having run is not a stub."*
It was stated about one file. It is a class, with twelve files in it.

## The mechanism

Three spellings, one defect — the double is applied **conditionally on import order**:

```python
if "dagster" not in sys.modules:   # skipped entirely when anything imported it first
    sys.modules["dagster"] = stub
sys.modules.setdefault(name, MagicMock())          # same semantics, terser
_mod = sys.modules.get(name)
if _mod is not None:                               # silently patches NOTHING when absent
    monkeypatch.setattr(_mod, "mint_service_token", stub, raising=False)
```

Compounded by **module identity via a generic name**: 155 files in this repo are named
`main.py`. `import main` returns whatever `sys.modules["main"]` holds and never consults
`sys.path` again, so the winner is decided by whoever imported first — and one file
`del`s the slot to install its own.

## The instances

Ordered by polarity: the ones that fail **silently** first, because a green that proves
nothing outranks a red that announces itself.

| member | spelling | polarity | evidence |
|---|---|---|---|
| `test_ontology_routing.py` | `setdefault` + `del sys.modules["main"]` | **silent, and the polluter** | MagicMocked the real `agent_fleet` while never covering `agent_fleet.utils.embed`, which engine-o imports. **11/11 errors standalone.** It went green only when its own `setdefault`s were no-ops because a prior file had loaded the real package — and its `del` of the `main` slot is what broke the gate below. Its leaked MagicMocks are why the conditional stubs in the other files no-op. |
| the `mint_service_token` family — `test_promise_name_seal.py`, `test_dispatch_driver.py`, `test_expired_token_seal.py`, `test_grouped_review_workflow.py` | `sys.modules.get()` + `if is not None` | **silent** | Byte-identical copy-paste. When the module isn't loaded yet the seal patches nothing and the test passes having sealed nothing. `test_promise_name_seal.py`'s own docstring names the hazard — *"that module object may not exist yet when this fixture runs"* — twenty lines below a sibling fixture, `_allow_can_act`, that does it correctly with `importlib.import_module`. The correct form was already in the file. |
| `test_effect_write_gate.py` | `import main as eo` | loud | Nine security-gate tests: **passed alone, failed in-suite**, `module 'main' has no attribute '_require_capability'`. Its skip-guard could not catch it — the guard fires when the module is *unimportable*, and a polluted cache yields a module that imports fine and is the **wrong one**. |
| `test_adr0019_contracts.py` (dagster) | `if not in sys.modules` | loud | `Failure`/`Nothing` absent from the stub while `dynamic_supervisor` had imported both since `9d57a23`. Invisible for five months because the stub was skipped whenever real dagster was already loaded. Fixed `5a2d5c9`; the class was not. |

The two silent members are the reason this is a law and not a bug report. The loud ones
were found by a red. The silent ones cannot be found by a red — only by asking whether
the double was applied at all.

## The policy

1. **Bind unconditionally, or fail loudly.** A double installs itself, or the fixture
   raises naming what it could not patch. Never a silent skip.
2. **Import the target, don't hope for it.** `importlib.import_module(name)` +
   `except ImportError`, never `sys.modules.get(name)` + `if is not None`.
3. **Never key a module on a generic name.** Load by path under a unique name:
   `spec_from_file_location("engine_o_main__<test>_test", path)`. Never `main`.
4. **Never `del` a module slot you did not create.** Eviction is pollution with a delay.
5. **A stub must cover every name the module imports**, not the ones needed the day it
   was written — the import list drifts and the gap stays invisible.
6. **Clean up what you install.** A `sys.modules` entry that outlives its test is the
   next file's silent no-op.

## What follows — the guard, not the naming

Per [[naming-a-class-is-not-a-guard]], stating this closes nothing. The guard is the
**shuffled-order run**: the only check whose scope is isolation rather than passing. A
suite that has never been collected in a different order has no evidence that any of its
greens are its own.

## What this does not license

It does not license removing doubles in favour of real heavy dependencies — the point is
that the double is applied *deterministically*, not that it is unnecessary. Nor does it
license a shared `conftest.py` for every stub: `test_adr0019_contracts.py` duplicates
`_install_stubs` deliberately so a gate file fails for its own reasons. Duplication that
buys independence is not the defect. **Conditionality is.**
