"""A chaining table is bound to the definition it follows, and decides exactly what it can emit.

Every chaining table now DECLARES `after:` -- the definition whose termination it decides. That
makes a link the safety seal (tests/safety/test_the_chaining_domain_matches_the_declared_verbs.py)
had to keep by hand, as a map from table to task kind, DERIVABLE: the table names the definition,
the definition names its last disposing step, the step names its vocabulary. So this seal walks
every table in the seed and every overlay, and the map stops being a list somebody must extend.

WHAT A DEFINITION CAN EMIT, as the executor computes it (`main._run_definition`): the outcome is
the disposition of the LAST disposing record -- a human verb, a signal status, a timer elapsing --
and an expiry anywhere ends the definition as `timed_out`. So the outcome domain is

    vocabulary(last disposing step)  plus  timed_out iff any step declares a deadline

and a table whose `domain.outcome` differs in either direction is wrong: smaller falls through
on a verb a human can emit, larger carries rows that can never fire.

EVERY STEP KIND IS CLASSIFIED as disposing or silent, against the step union the model declares,
so a new kind fails here until somebody decides what it emits -- an unclassified kind is the
undecided bucket, and undecided must fail.

EVERY CYCLE PASSES THROUGH A GATE. The runner bounds a case at MAX_INSTANCES and fails it with
"a chaining cycle with no human in it". That is the runtime catching a policy defect after a
case has burned its instances; this is the same defect caught where it is written. A gate is a
definition holding a human_await or a wait: with the gates removed, the chaining graph must be
acyclic.

THE DECLARATIONS COMPOSE AS THE RUNTIME READS THEM: two overlays declaring one table or one
definition are refused at load (name order is not a precedence anyone chose), a seed and one
overlay still compose, and every seed directory a loader reads exists and is baked into the
agent image.

Run: uv run --frozen pytest tests/test_a_chaining_table_is_bound_to_its_definition.py -v
"""
from __future__ import annotations

import os
import re
import typing
from pathlib import Path

import pytest
import yaml

from agent_fleet.restate_analyst import case_routing as R
from agent_fleet.restate_analyst import decision_table as dt
from agent_fleet.restate_analyst import workflow_definition as wd

_REPO = Path(__file__).resolve().parents[1]
_POLICY = _REPO / "policy"
_DOCKERFILE = _REPO / ".github" / "docker" / "Dockerfile.agent"

#: Steps whose result record carries a `disposition` (main._run_definition), and steps whose
#: record never does. Their union must be the model's step union -- see the partition arm.
_DISPOSING = {"human_await", "signal_await", "wait"}
_SILENT = {"spo_operation", "direct_call", "dispatch_fanout", "render", "emit"}

_ENVS = ("WORKFLOW_DEFINITIONS_DIR", "DECISION_TABLE_DIR", "CASE_TRIGGER_DIR")


@pytest.fixture(autouse=True)
def _repo_paths(monkeypatch):
    for e in _ENVS:
        monkeypatch.delenv(e, raising=False)


def _yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _tables() -> "dict[str, dict]":
    return dt.load_tables()


def _chaining() -> "list[tuple[str, dict]]":
    for e in _ENVS:  # collection runs before the fixture
        os.environ.pop(e, None)
    return sorted((k, t) for k, t in _tables().items() if t.get("after"))


def _kinds() -> "dict[str, dict]":
    """Every declared task kind, seed then every overlay, keyed by its `kind`."""
    out: dict = {}
    for d in [_POLICY / "task_kinds", *sorted((_POLICY / "overlays").glob("*/task_kinds"))]:
        for p in sorted(d.glob("*.yaml")):
            raw = _yaml(p)
            if raw.get("kind"):
                out[str(raw["kind"])] = raw
    return out


def _kinds_for(task_kind: str, kinds: dict) -> "list[str]":
    """The kinds a step's task_kind can name. A literal names itself; a template such as
    `risk_acceptance_{level_slug}` names every kind its placeholders can fill, a placeholder
    filling one slug segment (no underscore, so `risk_acceptance_{level_slug}` does not swallow
    `risk_acceptance_concurrence_high`)."""
    if "{" not in task_kind:
        return [task_kind] if task_kind in kinds else []
    rx = re.compile("".join(
        "[A-Za-z0-9-]+" if part.startswith("{") else re.escape(part)
        for part in re.split(r"(\{[^}]+\})", task_kind)))
    return sorted(k for k in kinds if rx.fullmatch(k))


def _emits(definition_id: str) -> "set[str]":
    """The outcome domain a definition can terminate with, as the executor computes it."""
    wf = wd.get_workflow_definition(definition_id)
    disposing = [s for s in wf.steps if s.kind in _DISPOSING]
    assert disposing, f"{definition_id} has no disposing step, so its outcome is always None"
    last = disposing[-1]
    if last.kind == "human_await":
        assert last.completion.mode != "grouped", (
            f"{definition_id}: the last disposing step is GROUPED; this seal does not yet derive a "
            "grouped vocabulary, and an undecided case must fail rather than pass")
        kinds = _kinds()
        named = _kinds_for(last.task_kind or "", kinds)
        assert named, f"{definition_id}: task_kind {last.task_kind!r} names no declared kind"
        sets = {tuple(sorted(kinds[k].get("accepts") or [])) for k in named}
        assert len(sets) == 1, (
            f"{definition_id}: task_kind {last.task_kind!r} names kinds {named} that declare "
            f"DIFFERENT verbs {sorted(sets)}; one table cannot be total for all of them")
        verbs = set(sets.pop())
    elif last.kind == "signal_await":
        verbs = set(last.accepts)
    else:
        verbs = {"elapsed"}
    if any(getattr(s, "deadline_seconds", None) for s in wf.steps):
        verbs.add("timed_out")
    return verbs


# -- FLOORS AND PARTITIONS ------------------------------------------------------------------

def test_EVERY_STEP_KIND_IS_CLASSIFIED():
    union = typing.get_args(typing.get_args(wd.Step)[0])
    declared = {typing.get_args(c.model_fields["kind"].annotation)[0] for c in union}
    assert not (_DISPOSING & _SILENT)
    assert _DISPOSING | _SILENT == declared, (
        f"unclassified step kinds {sorted(declared - _DISPOSING - _SILENT)}, or classified kinds "
        f"the model no longer declares {sorted((_DISPOSING | _SILENT) - declared)}")


def test_EVERY_TABLE_IS_A_SELECTION_OR_A_CHAINING_TABLE():
    """The partition, with no third bucket: a table neither named by a trigger nor `after:` a
    definition is consulted by nothing, and one that is both is decided twice."""
    selections = {t.selection for t in R.load_triggers().values()}
    for key, table in _tables().items():
        chaining, selecting = bool(table.get("after")), key in selections
        assert chaining != selecting, (
            f"{key}: chaining={chaining} selection={selecting}; exactly one must hold")


def test_AT_LEAST_THE_KNOWN_CHAINING_TABLES_ARE_FOUND():
    """The floor: the walk below quantifies over this, and over nothing it passes."""
    found = {k for k, _ in _chaining()}
    assert {"safety_concurrence_chaining", "safety_acceptance_chaining",
            "safety_redraft_chaining", "maint_fault_propose_chaining",
            "maint_release_chaining"} <= found, sorted(found)


# -- THE DOMAIN ------------------------------------------------------------------------------

@pytest.mark.parametrize("key", [k for k, _ in _chaining()])
def test_THE_DOMAIN_IS_WHAT_THE_DEFINITION_CAN_EMIT(key):
    table = _tables()[key]
    emits = _emits(table["after"])
    domain = set((table.get("domain") or {}).get("outcome") or [])
    assert "outcome" in (table.get("matches") or []), f"{key} does not match on outcome"
    assert not emits - domain, (
        f"{key}: {table['after']} can emit {sorted(emits - domain)} and the domain omits them -- "
        "that outcome FALLS THROUGH at the moment it is emitted")
    assert not domain - emits, (
        f"{key}: the domain declares {sorted(domain - emits)}, which {table['after']} can never "
        "emit -- rows for them look like coverage and never fire")


_TWO_DISPOSERS = (
    "id: two\nname: two\nsteps:\n"
    "  - {kind: wait, id: first, seconds: 1}\n"
    "  - {kind: signal_await, id: ack, signal: ack, audience: a, accepts: [fine, refused]}\n")
_SIGNAL_ONLY = (
    "id: sig\nname: sig\nsteps:\n"
    "  - {kind: signal_await, id: ack, signal: ack, audience: a, accepts: [fine]}\n")
_EARLY_DEADLINE = (
    "id: early\nname: early\nsteps:\n"
    "  - {kind: signal_await, id: ack, signal: ack, audience: a, accepts: [fine],"
    " deadline_seconds: 5}\n"
    "  - {kind: wait, id: after, seconds: 1}\n")


def test_THE_LAST_DISPOSER_DECIDES_AND_ANY_DEADLINE_ADDS_TIMED_OUT(tmp_path, monkeypatch):
    """THE DERIVATION, on shapes no committed definition has yet: every real definition has one
    disposing step, with its deadline on it, so `first` against `last` and `any step` against
    `the last step` would both pass over the real tree."""
    d = _write(tmp_path / "defs", {"two.yaml": _TWO_DISPOSERS, "early.yaml": _EARLY_DEADLINE})
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR", str(d))
    assert _emits("two") == {"fine", "refused"}
    assert _emits("early") == {"elapsed", "timed_out"}


def test_A_TEMPLATED_KIND_NAMES_ONLY_ITS_OWN_TIER():
    """THE CONTROL on the template match: too narrow names nothing and the domain arm fails on
    an empty kind set; too wide pulls the concurrence kinds into the acceptance template, and
    the verb sets disagree. Asserted directly so a widening shows as itself."""
    kinds = _kinds()
    acc = _kinds_for("risk_acceptance_{level_slug}", kinds)
    con = _kinds_for("risk_acceptance_concurrence_{level_slug}", kinds)
    assert acc and con and not set(acc) & set(con), (acc, con)


# -- CYCLES ----------------------------------------------------------------------------------

def _gates(definition_ids) -> "set[str]":
    return {d for d in definition_ids
            if any(s.kind in ("human_await", "wait") for s in wd.get_workflow_definition(d).steps)}


def _ungated_cycle(edges: "dict[str, set[str]]", gates: "set[str]"):
    """A cycle among non-gate nodes, or None."""
    graph = {n: {m for m in ms if m not in gates} for n, ms in edges.items() if n not in gates}
    state: dict = {}

    def visit(n, path):
        state[n] = 1
        for m in sorted(graph.get(n, ())):
            if state.get(m) == 1:
                return path + [n, m]
            if m not in state:
                found = visit(m, path + [n])
                if found:
                    return found
        state[n] = 2
        return None

    for n in sorted(graph):
        if n not in state:
            found = visit(n, [])
            if found:
                return found
    return None


def _chaining_edges() -> "dict[str, set[str]]":
    edges: dict = {}
    for _key, table in _chaining():
        terminals = set(table.get("terminals") or [])
        edges.setdefault(table["after"], set()).update(
            r["then"] for r in table.get("rows") or [] if r["then"] not in terminals)
    return edges


def test_EVERY_CYCLE_PASSES_THROUGH_A_HUMAN_OR_A_WAIT():
    edges = _chaining_edges()
    nodes = set(edges) | {m for ms in edges.values() for m in ms}
    cycle = _ungated_cycle(edges, _gates(nodes))
    assert cycle is None, (
        f"chaining cycle {cycle} has no human_await and no wait in it -- a case on it opens "
        "instances until MAX_INSTANCES and fails")


def test_CONTROL_an_ungated_cycle_is_found():
    edges = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "h": {"a"}}
    assert _ungated_cycle(edges, gates={"h"}) is not None
    assert _ungated_cycle(edges, gates={"b"}) is None
    # The gate must be ON the cycle: a gate beside it gates nothing.
    assert _ungated_cycle({"a": {"a"}, "h": {"a"}}, gates={"h"}) == ["a", "a"]


def test_A_WAIT_IS_A_GATE_AND_A_SIGNAL_IS_NOT(tmp_path, monkeypatch):
    """Every real cycle also passes through a human, so dropping `wait` from the gates passes
    over the real tree; the classification is pinned here instead. A signal is a system answering,
    which can come back as fast as the runner asks, so it gates nothing."""
    d = _write(tmp_path / "defs", {"two.yaml": _TWO_DISPOSERS, "sig.yaml": _SIGNAL_ONLY})
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR", str(d))
    assert _gates({"two", "sig"}) == {"two"}


def test_THE_REAL_GRAPH_HAS_CYCLES_FOR_THE_GATE_TO_BREAK():
    """Without a cycle in the real graph the arm above passes over nothing; with every gate
    removed, it must find one."""
    assert _ungated_cycle(_chaining_edges(), gates=set()) is not None


# -- COMPOSITION -----------------------------------------------------------------------------

def _write(d: Path, files: dict) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    return d


_TABLE = ("decision: same\nmatches: [outcome]\ndomain: {outcome: [x]}\n"
          "rows: [{when: {outcome: x}, then: %s}]\n")
_DEF = "id: same\nname: %s\nsteps:\n  - {kind: wait, id: w, seconds: 1}\n"


def test_TWO_OVERLAYS_DECLARING_ONE_TABLE_ARE_REFUSED(tmp_path, monkeypatch):
    seed = _write(tmp_path / "seed", {})
    a = _write(tmp_path / "a", {"t.yaml": _TABLE % "one"})
    b = _write(tmp_path / "b", {"t.yaml": _TABLE % "two"})
    monkeypatch.setenv("DECISION_TABLE_DIR", os.pathsep.join(map(str, (seed, a, b))))
    with pytest.raises(dt.DecisionError, match="two overlays"):
        dt.load_tables()


def test_A_SEED_TABLE_AN_OVERLAY_REPLACES_STILL_COMPOSES(tmp_path, monkeypatch):
    """THE ACCEPTING SIDE: replacement of the seed by one overlay is the documented rule."""
    seed = _write(tmp_path / "seed", {"t.yaml": _TABLE % "seed"})
    a = _write(tmp_path / "a", {"t.yaml": _TABLE % "overlay"})
    monkeypatch.setenv("DECISION_TABLE_DIR", os.pathsep.join(map(str, (seed, a))))
    try:
        tables = dt.load_tables()
    except dt.DecisionError as exc:
        raise AssertionError(f"the guard refuses the documented seed replacement: {exc}") from exc
    assert tables["same"]["rows"][0]["then"] == "overlay"


def test_TWO_OVERLAYS_DECLARING_ONE_DEFINITION_ARE_REFUSED(tmp_path, monkeypatch):
    seed = _write(tmp_path / "seed", {})
    a = _write(tmp_path / "a", {"same.yaml": _DEF % "one"})
    b = _write(tmp_path / "b", {"same.yaml": _DEF % "two"})
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR", os.pathsep.join(map(str, (seed, a, b))))
    with pytest.raises(wd.WorkflowDefinitionError, match="two overlays"):
        wd.get_workflow_definition("same")


def test_A_SEED_DEFINITION_AN_OVERLAY_REPLACES_STILL_LOADS(tmp_path, monkeypatch):
    seed = _write(tmp_path / "seed", {"same.yaml": _DEF % "seed"})
    a = _write(tmp_path / "a", {"same.yaml": _DEF % "overlay"})
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR", os.pathsep.join(map(str, (seed, a))))
    try:
        wf = wd.get_workflow_definition("same")
    except wd.WorkflowDefinitionError as exc:
        raise AssertionError(f"the guard refuses the documented seed replacement: {exc}") from exc
    assert wf.name == "overlay"


def _seed_dirs() -> "list[Path]":
    """Every seed directory a case-runner loader reads, from the loaders themselves."""
    return [wd.definition_dirs()[0], dt.decision_dirs()[0], R.trigger_dirs()[0], wd.verb_dirs()[0]]


def test_EVERY_SEED_DIRECTORY_A_LOADER_READS_IS_BAKED():
    copies = {ln.strip() for ln in _DOCKERFILE.read_text(encoding="utf-8").splitlines()
              if ln.startswith("COPY ")}
    for d in [*_seed_dirs(), _POLICY / "overlays"]:
        rel = d.resolve().relative_to(_REPO).as_posix()
        assert d.is_dir(), f"{rel} does not exist; the loader's seed path is an absence"
        assert f"COPY {rel}/ /app/{rel}/" in copies, (
            f"{rel} is read by a case-runner loader and not baked into the agent image")


def test_THE_SEED_DIRECTORIES_ARE_DISTINCT():
    """THE CONTROL: four loaders that all resolved to one directory would pass the arm above
    with one COPY line."""
    assert len({d.resolve() for d in _seed_dirs()}) == 4
