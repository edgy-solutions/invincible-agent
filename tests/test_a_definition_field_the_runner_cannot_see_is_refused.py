"""A definition field the runner cannot see is refused at load; a declared task kind is honoured.

TWO HALVES OF ONE DEFECT CLASS -- a YAML that reads as declaring something the executor never does.

1. pydantic's default `extra="ignore"` validated a misspelled or unimplemented field and dropped
   it. `deadline_secs: 3600` loaded cleanly and waited forever. Every model a definition author
   writes now inherits `_Declared` (`extra="forbid"`); the population is DERIVED from the
   module's models, so a new step kind that forgets the base is a red here, not a quiet hole.

2. The task kind -- what `/act` keys a decision's vocabulary and reason requirement on -- was an
   argument the SERVICE passed for every step of a run. `safety_concurrence` therefore registered
   the user representative's concurrence under the ACCEPTANCE kind, whose `accepts` has no
   `concurred`. It is now declared per step (`task_kind`, bindable, strict) and honoured ONLY when
   the definition came from the registry: BPMNWorkflowRunner still runs a caller-supplied
   definition, and a kind read from one would let the caller choose its own gate.

Run: uv run --frozen pytest tests/test_a_definition_field_the_runner_cannot_see_is_refused.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

yaml = pytest.importorskip("yaml")
pytest.importorskip("restate")
import restate  # noqa: E402
import main  # noqa: E402  — the real executor, imported as its siblings import it
import workflow_definition as wd  # noqa: E402  — the SAME module object main validates with

from pydantic import ValidationError  # noqa: E402

_POLICY = _REPO / "policy"


# ── 1. UNKNOWN FIELDS ───────────────────────────────────────────────────────────────────────

def _committed_definitions():
    dirs = [_POLICY / "workflows", *sorted((_POLICY / "overlays").glob("*/workflows"))]
    return [p for d in dirs for p in sorted(d.glob("*.yaml"))]


_DEFS = _committed_definitions()


def test_THE_POPULATION_IS_NOT_EMPTY():
    assert len(_DEFS) >= 6, [p.name for p in _DEFS]


@pytest.mark.parametrize("path", _DEFS, ids=[f"{p.parent.parent.name}/{p.name}" for p in _DEFS])
def test_every_committed_definition_loads_strictly(path):
    """The strictness is not allowed to land by breaking a shipped definition."""
    wd.load_workflow_definition(path)


# A minimal VALID instance of each declared model. The refusal arm adds exactly one bogus key to
# it, so the control below proves the refusal is the key's and nothing else's.
_MINIMAL = {
    "CompletionPolicy": {},
    "HumanAwaitStep": {"kind": "human_await", "id": "a", "audience": "k:D"},
    "SpoOperationStep": {"kind": "spo_operation", "id": "s", "subject": "urn:x", "verb": "urn:v"},
    "DirectCallStep": {"kind": "direct_call", "id": "d", "endpoint": "http://e", "capability": "c"},
    "DispatchFanoutStep": {"kind": "dispatch_fanout", "id": "f", "capability": "c"},
    "WorkflowDefinition": {"id": "w", "name": "w",
                           "steps": [{"kind": "human_await", "id": "a", "audience": "k:D"}]},
}


def _declared_models():
    """Every pydantic model DEFINED in the definitions module -- the population an author writes.
    Derived from the module, not from the strict base, so a model that forgets the base is IN the
    population and reds below rather than falling out of it."""
    from pydantic import BaseModel
    return sorted(
        (v for v in vars(wd).values()
         if isinstance(v, type) and issubclass(v, BaseModel) and v is not BaseModel
         and v.__module__ == wd.__name__ and not v.__name__.startswith("_")),
        key=lambda c: c.__name__)


def test_EVERY_STEP_KIND_IS_A_DECLARED_MODEL():
    """Every step kind in the discriminated union is in the population, and every member of the
    population has a minimal instance here -- or the arms below cannot reach it."""
    union = wd.Step.__args__[0].__args__  # Annotated[Union[...], Field] -> the members
    names = {c.__name__ for c in _declared_models()}
    assert {c.__name__ for c in union} <= names
    assert names == set(_MINIMAL), (
        f"models without a minimal instance here: {sorted(names - set(_MINIMAL))}; "
        f"stale entries: {sorted(set(_MINIMAL) - names)}")


@pytest.mark.parametrize("model", _declared_models(), ids=lambda c: c.__name__)
def test_CONTROL_the_minimal_instance_is_valid(model):
    model.model_validate(_MINIMAL[model.__name__])


@pytest.mark.parametrize("model", _declared_models(), ids=lambda c: c.__name__)
def test_A_MISSPELLED_FIELD_IS_REFUSED(model):
    raw = dict(_MINIMAL[model.__name__], deadline_secs=3600)
    with pytest.raises(ValidationError) as exc:
        model.model_validate(raw)
    assert "deadline_secs" in str(exc.value) and "xtra" in str(exc.value), str(exc.value)


def test_A_NESTED_MISSPELLING_IS_REFUSED_THROUGH_THE_FILE_LOADER(tmp_path):
    """Through the loader the runtime uses, on a field two levels down."""
    raw = yaml.safe_load(_DEFS[0].read_text(encoding="utf-8"))
    raw["steps"][0]["completion"] = {"mode": "single", "quorom": "any_of"}
    p = tmp_path / "typo.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(wd.WorkflowDefinitionError) as exc:
        wd.load_workflow_definition(p)
    assert "quorom" in str(exc.value)


# ── 2. THE DECLARED TASK KIND ───────────────────────────────────────────────────────────────

class _Promise:
    def value(self):
        async def _v():
            return {"status": "concurred", "acted_by": "u@x"}
        return _v()


class _Ctx:
    def __init__(self):
        self.state: dict = {}

    def key(self):
        return "seal-key"

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn):
        return fn()

    def promise(self, name, type_hint=None):
        return _Promise()


@pytest.fixture
def registered(monkeypatch):
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": rows.append((task["id"], kind)) or {})
    return rows


def _definition(**step_extra):
    step = {"kind": "human_await", "id": "concurrence", "audience": "conc_{level_slug}:D",
            "completion": {"mode": "single"}, **step_extra}
    return {"id": "seal_kind", "name": "seal", "steps": [step]}


async def _drive(definition, **kw):
    return await main._run_definition(
        _Ctx(), "wf-seal", definition, {"level_slug": "high", "authz_id": "a@x"}, **kw)


@pytest.mark.asyncio
async def test_A_DECLARED_KIND_IS_THE_KIND_REGISTERED(registered):
    await _drive(_definition(task_kind="risk_acceptance_concurrence_{level_slug}"),
                 task_kind="risk_acceptance_high", from_registry=True)
    assert registered == [("wf-seal:concurrence", "risk_acceptance_concurrence_high")], registered


@pytest.mark.asyncio
async def test_A_DECLARED_KIND_ON_A_CALLER_SUPPLIED_DEFINITION_IS_REFUSED(registered):
    with pytest.raises(restate.TerminalError) as exc:
        await _drive(_definition(task_kind="risk_acceptance_concurrence_{level_slug}"))
    assert "honoured only from the registry" in str(exc.value)
    assert registered == [], "refused AFTER registering -- a row exists under the caller's kind"


@pytest.mark.asyncio
async def test_AN_UNBOUND_KIND_PLACEHOLDER_IS_REFUSED(registered):
    with pytest.raises(Exception) as exc:
        await _drive(_definition(task_kind="risk_{tier}"), from_registry=True)
    assert "tier" in str(exc.value)
    assert registered == []


@pytest.mark.asyncio
async def test_A_KIND_ON_A_GROUPED_AWAIT_IS_REFUSED(registered):
    """Without the refusal the grouped path runs on and dies of something unrelated, which is not
    the refusal this arm claims -- so any other exception is a named failure, not a pass."""
    try:
        await _drive(_definition(task_kind="k", completion={"mode": "grouped"}), from_registry=True)
    except restate.TerminalError as exc:
        assert "grouped" in str(exc) and "task_kind" in str(exc), str(exc)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"the grouped path ran past a declared kind and died of {type(exc).__name__}: {exc}"
        ) from exc
    else:
        raise AssertionError("a grouped await with a declared kind ran to completion")


@pytest.mark.asyncio
async def test_CONTROL_no_declared_kind_keeps_the_callers_argument(registered):
    await _drive(_definition(), task_kind="risk_acceptance_high")
    assert registered == [("wf-seal:concurrence", "risk_acceptance_high")], registered
