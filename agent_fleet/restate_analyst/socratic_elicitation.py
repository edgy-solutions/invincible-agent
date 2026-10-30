"""PROTOTYPE for ADR-0061, unregistered, no route.
Case checks bind only definitions reachable from a selection table, the population chain() acts on.

SOCRATIC WORKFLOW ELICITATION: a dialogue whose product is an overlay bundle.

The spec a user's dialogue produces IS the bundle the case runner already loads --
``triggers/*.yaml``, ``decisions/*.yaml``, ``workflows/*.yaml``, ``task_kinds/*.yaml`` -- so there
is no intermediate spec format and no new runtime. The loop's state is a PARTIAL bundle (a
``Draft``). Each user utterance becomes a PATCH, made by an extractor (an oracle reading a fixture's
annotation, or a model). After every patch a validator lists GAPS: things missing, or contradictory
(an overwrite of a value already stated, or a cross-check the runtime or the seals would refuse).
The agent restates the draft and asks about exactly ONE gap per turn, highest priority first. The
loop ends when no gap remains (or at ``max_turns``).

PATCH GRAMMAR::

    set:
      - {file: workflows/x.yaml, path: "steps[id=review].excludes", value: ["{trigger.who}"]}
    defer:
      - {gap: "approvals.x.review.deadline", reason: "turnaround not agreed yet"}

A path is dotted keys; ``name[k=v]`` selects the element of list ``name`` whose mapping has key
``k`` equal to ``v`` (string compare), appending ``{k: v}`` when absent; ``""`` is the file root. A
mapping value is applied leaf by leaf (so a contradiction is found per leaf); a list is a leaf.
``None`` is a value: ``deadline_seconds: null`` is "explicitly no deadline".

THREE DEPARTURES FROM THE WRITTEN SPEC, each small and each removable (see the hand-back):

* ``Gap.revises`` -- the (file, leaf) pairs an answer to THAT gap may overwrite. The spec lets an
  answer overwrite only the path of an overwrite-contradiction gap. A cross-check contradiction
  ("the table says SMEs can defer, the task kind does not") and a ``next.<verb>`` gap are answered
  precisely by REVISING a list (``accepts``, a table's ``rows``/``domain``), and a list is a leaf,
  so without this every such answer would itself raise a fresh overwrite contradiction.
* ``Draft.kept_earlier`` -- where the loop records an overwrite contradiction resolved in favour of
  the earlier value.
* ``apply_patch`` also applies the patch's ``defer`` entries (the loop would otherwise do it).
"""
from __future__ import annotations

import copy
from collections import Counter
import itertools
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import yaml
from pydantic import ValidationError

try:  # package-first: one module object per class (an exception type needs one module)
    from agent_fleet.restate_analyst import case_routing as _cr
    from agent_fleet.restate_analyst import decision_table as _dt
    from agent_fleet.restate_analyst import workflow_definition as _wd
except ImportError:  # pragma: no cover -- flattened container layout
    import case_routing as _cr  # type: ignore[no-redef]
    import decision_table as _dt  # type: ignore[no-redef]
    import workflow_definition as _wd  # type: ignore[no-redef]

FACETS = ("trigger", "actors", "steps", "approvals", "outputs")
_FACET_RANK = {f: i for i, f in enumerate(FACETS)}

_DISPOSING = {"human_await", "signal_await", "wait"}
_ACTOR_FIELDS = {"audience", "excludes"}
_APPROVAL_FIELDS = {"task_kind", "deadline_seconds", "approves", "role"}
_FOLDERS = ("triggers", "decisions", "workflows", "task_kinds")
#: The trigger's list of every stage (definition id) a case can pass through, in the person's
#: order (architect, 2026-10-30). DRAFT-ONLY: the runner's Trigger refuses an unknown field, so
#: ``finalize`` drops it; the loop reads it to ask for each stage not yet drafted.
_STAGES = "stages"

_LEAF_WORDS = {
    "excludes": "who may not decide",
    "deadline_seconds": "the time limit",
    "audience": "who answers",
    "accepts": "the possible answers",
    "reason_required": "which answers need a reason",
    "approves": "which answers count as approval",
    "role": "the approver's role",
    "task_kind": "the kind of answer",
    "terminals": "where it ends",
    "rows": "the routing",
    "domain.outcome": "the possible outcomes",
}


# ═════════════════════════════════════════════════════════════════════════════════════════════
# DATA
# ═════════════════════════════════════════════════════════════════════════════════════════════

@dataclass
class Gap:
    key: str          # stable string, the fixture bank's lookup key
    facet: str        # one of: trigger, actors, steps, approvals, outputs
    kind: str         # "missing" | "contradiction" | "confirm"
    question: str     # user-facing text (templated; names the stage/step in plain words)
    proposed: Any = None                       # an overwrite contradiction: the value not applied
    revises: Tuple[Tuple[str, str], ...] = ()  # (file, leaf path) pairs an answer may overwrite


@dataclass
class Draft:
    files: Dict[str, dict] = field(default_factory=dict)      # "workflows/x.yaml" -> mapping
    deferrals: Dict[str, str] = field(default_factory=dict)   # gap key -> reason
    set_at: Dict[Tuple[str, str], int] = field(default_factory=dict)  # (file, leaf) -> turn
    pending: List[Gap] = field(default_factory=list)          # overwrite contradictions awaiting
    kept_earlier: List[str] = field(default_factory=list)     # contradictions resolved to the earlier
    open: Dict[str, str] = field(default_factory=dict)        # NON-deferrable gap key -> why it is open
    asked: Counter = field(default_factory=Counter)           # gap key -> times asked
    answered: Dict[str, int] = field(default_factory=dict)    # gap key -> last turn it was answered
    vouched: Dict[Tuple[str, str], int] = field(default_factory=dict)  # (file, leaf) -> turn the
    #   person answered a question naming that leaf (a confirm or an overwrite contradiction)


class PatchError(ValueError):
    """A patch entry that cannot be applied at all (malformed path or shape)."""


# ═════════════════════════════════════════════════════════════════════════════════════════════
# PATHS
# ═════════════════════════════════════════════════════════════════════════════════════════════

_SEG = re.compile(r"^([A-Za-z0-9_\-]+)(?:\[([A-Za-z0-9_\-]+)=([^\]]*)\])?$")


def parse_path(path: str) -> List[Tuple[str, Optional[Tuple[str, str]]]]:
    """``"steps[id=a].excludes"`` -> ``[("steps", ("id", "a")), ("excludes", None)]``."""
    if path == "":
        return []
    parts: List[str] = []
    buf, depth = "", 0
    for ch in path:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "." and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    out = []
    for p in parts:
        m = _SEG.match(p)
        if not m:
            raise PatchError(f"cannot parse path segment {p!r} in {path!r}")
        out.append((m.group(1), (m.group(2), m.group(3)) if m.group(2) else None))
    return out


def _locate(root: dict, segs, create: bool) -> Optional[Tuple[dict, str]]:
    """``(container mapping, key)`` of the leaf the path addresses; None if absent and not creating."""
    node = root
    for i, (name, sel) in enumerate(segs):
        last = i == len(segs) - 1
        if sel is None:
            if last:
                return node, name
            nxt = node.get(name)
            if nxt is None:
                if not create:
                    return None
                nxt = node[name] = {}
            if not isinstance(nxt, dict):
                raise PatchError(f"{name!r} holds a {type(nxt).__name__}, not a mapping")
            node = nxt
        else:
            if last:
                raise PatchError(f"a path may not end on a list selector ({name}[...]); address a key")
            lst = node.get(name)
            if lst is None:
                if not create:
                    return None
                lst = node[name] = []
            if not isinstance(lst, list):
                raise PatchError(f"{name!r} holds a {type(lst).__name__}, not a list")
            k, v = sel
            found = next((e for e in lst if isinstance(e, dict) and str(e.get(k)) == v), None)
            if found is None:
                if not create:
                    return None
                found = {k: v}
                lst.append(found)
            node = found
    raise PatchError("an empty path addresses the file root, not a leaf")


def _get(files: Dict[str, dict], file: str, path: str) -> Tuple[bool, Any]:
    root = files.get(file)
    if root is None:
        return False, None
    loc = _locate(root, parse_path(path), create=False)
    if loc is None:
        return False, None
    container, key = loc
    return (key in container), container.get(key)


def _leaves(prefix: str, value: Any) -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict) and value:
        for k, v in value.items():
            yield from _leaves(f"{prefix}.{k}" if prefix else str(k), v)
    else:
        yield prefix, value


# ═════════════════════════════════════════════════════════════════════════════════════════════
# WORDS
# ═════════════════════════════════════════════════════════════════════════════════════════════

def _words(s: Any) -> str:
    return re.sub(r"[_\-]+", " ", str(s)).strip()


def _fmt(v: Any, leaf: str = "") -> str:
    if v is None:
        return "none"
    if leaf.endswith("deadline_seconds") and isinstance(v, int) and not isinstance(v, bool):
        if v % 86400 == 0:
            return f"{v // 86400} days"
        if v % 3600 == 0:
            return f"{v // 3600} hours"
        return f"{v} seconds"
    if isinstance(v, list):
        return ", ".join(_fmt(x) for x in v) if v else "nobody (empty)"
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True)
    return str(v)


def _describe(file: str, path: str) -> str:
    segs = parse_path(path)
    leaf = ".".join(n for n, _ in segs if True)
    phrase = _LEAF_WORDS.get(segs[-1][0] if segs else "", _words(segs[-1][0]) if segs else "the whole row")
    if len(segs) >= 2 and ".".join(n for n, _ in segs[-2:]) in _LEAF_WORDS:
        phrase = _LEAF_WORDS[".".join(n for n, _ in segs[-2:])]
    sel = next((s for _, s in segs if s), None)
    stem = _words(Path(file).stem)
    del leaf
    if sel:
        return f"{phrase} for {_words(sel[1])} in {stem}"
    return f"{phrase} of {stem}"


# ═════════════════════════════════════════════════════════════════════════════════════════════
# BUNDLE INDEX
# ═════════════════════════════════════════════════════════════════════════════════════════════

def _stem(file: str) -> str:
    return Path(file).stem


def _of(files: Dict[str, dict], folder: str) -> List[Tuple[str, dict]]:
    return [(f, d) for f, d in files.items() if f.startswith(folder + "/") and isinstance(d, dict)]


def _decisions(files) -> Dict[str, Tuple[str, dict]]:
    return {str(d.get("decision") or _stem(f)): (f, d) for f, d in _of(files, "decisions")}


def _workflows(files) -> Dict[str, Tuple[str, dict]]:
    return {str(d.get("id") or _stem(f)): (f, d) for f, d in _of(files, "workflows")}


def _kinds(files) -> Dict[str, Tuple[str, dict]]:
    return {str(d.get("kind") or _stem(f)): (f, d) for f, d in _of(files, "task_kinds")}


def _steps(d: dict) -> List[dict]:
    s = d.get("steps")
    return [x for x in s if isinstance(x, dict)] if isinstance(s, list) else []


def _kinds_for(task_kind: str, kinds: Dict[str, Any]) -> List[str]:
    """The kinds a step's ``task_kind`` can name; a template names every kind it can fill (one
    slug segment per placeholder), as ``tests/test_a_chaining_table_is_bound_to_its_definition``."""
    if not task_kind:
        return []
    if "{" not in task_kind:
        return [task_kind] if task_kind in kinds else []
    rx = re.compile("".join(
        "[A-Za-z0-9-]+" if part.startswith("{") else re.escape(part)
        for part in re.split(r"(\{[^}]+\})", task_kind)))
    return sorted(k for k in kinds if rx.fullmatch(k))


def _disposes(step: dict) -> bool:
    return step.get("kind") in _DISPOSING or (
        step.get("kind") == "direct_call" and step.get("outcome_from") is not None)


def _emits(wf: dict, kinds: Dict[str, Tuple[str, dict]]) -> Tuple[Optional[List[str]], Optional[dict]]:
    """``(the outcome verbs the definition can end with, its last disposing step)``. Verbs None
    when the vocabulary is the callee's, a grouped batch's, or not yet derivable; the step None
    when nothing disposes. As ``_emits`` in the chaining seal, but a gap instead of an assert."""
    steps = _steps(wf)
    disposing = [s for s in steps if _disposes(s)]
    if not disposing:
        return None, None
    last = disposing[-1]
    k = last.get("kind")
    if k == "direct_call":
        return None, last
    if k == "human_await":
        if (last.get("completion") or {}).get("mode") == "grouped":
            return None, last
        named = _kinds_for(str(last.get("task_kind") or ""), kinds)
        if not named:
            return None, last
        sets = {tuple(kinds[n][1].get("accepts") or []) for n in named}
        if len(sets) != 1:
            return None, last
        verbs = list(sets.pop())
    elif k == "signal_await":
        verbs = list(last.get("accepts") or [])
    else:
        verbs = ["elapsed"]
    if any(s.get("deadline_seconds") for s in steps) and "timed_out" not in verbs:
        verbs.append("timed_out")
    return verbs, last


def _decide_all(table: dict) -> Optional[str]:
    """Run the REAL ``decide`` over the whole declared input space; the first refusal, or None."""
    matches = list(table.get("matches") or [])
    domain = table.get("domain") or {}
    if not matches:
        return "declares no `matches`"
    spaces = [list(domain.get(a) or []) for a in matches]
    if any(not s for s in spaces):
        missing = [a for a, s in zip(matches, spaces) if not s]
        return f"declares no domain for {missing}"
    for combo in itertools.product(*spaces):
        try:
            _dt.decide(table, dict(zip(matches, combo)))
        except _dt.DecisionError as exc:
            return str(exc)
    return None


def _first_line(s: str, n: int = 160) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "..."


# ═════════════════════════════════════════════════════════════════════════════════════════════
# FACET OF A LEAF
# ═════════════════════════════════════════════════════════════════════════════════════════════

def _leaf_facet(files: Dict[str, dict], file: str, path: str) -> str:
    if file.startswith("triggers/"):
        return "trigger"
    if file.startswith("task_kinds/"):
        return "approvals"
    if file.startswith("decisions/"):
        sel = {str(d.get("selection")) for _, d in _of(files, "triggers")}
        d = files.get(file) or {}
        return "trigger" if str(d.get("decision") or _stem(file)) in sel else "outputs"
    segs = parse_path(path)
    name = segs[-1][0] if segs else ""
    if name in _ACTOR_FIELDS:
        return "actors"
    if name in _APPROVAL_FIELDS:
        return "approvals"
    if segs and segs[0][0] == "steps" and segs[0][1]:
        ok, kind = _get(files, file, f"steps[{segs[0][1][0]}={segs[0][1][1]}].kind")
        if ok and kind in ("emit", "signal_await"):
            return "outputs"
    return "steps"


def _field_facet(field_name: str, step_kind: Optional[str]) -> str:
    if field_name in _ACTOR_FIELDS:
        return "actors"
    if field_name in _APPROVAL_FIELDS:
        return "approvals"
    if step_kind in ("emit", "signal_await"):
        return "outputs"
    return "steps"


# ═════════════════════════════════════════════════════════════════════════════════════════════
# PATCH
# ═════════════════════════════════════════════════════════════════════════════════════════════

def apply_patch(draft: Draft, patch: dict, turn: int, answering: Optional[Gap] = None) -> None:
    """Apply ``patch`` to ``draft``. A leaf already holding a deep-unequal value is NOT overwritten:
    it becomes a pending contradiction -- unless ``answering`` names that leaf in its ``revises``.
    An equal re-set is a no-op. Answering an overwrite contradiction always settles it: applied if
    the answer set the leaf, else resolved in favour of the earlier value (``draft.kept_earlier``)."""
    patch = patch or {}
    revisable = set(answering.revises) if answering is not None else set()
    for entry in patch.get("set") or []:
        if not isinstance(entry, dict) or "file" not in entry or "path" not in entry or "value" not in entry:
            raise PatchError(f"a set entry needs file, path and value; got {entry!r}")
        file, base, value = str(entry["file"]), str(entry["path"]), entry["value"]
        root = draft.files.setdefault(file, {})
        for leaf_path, leaf_value in _leaves(base, copy.deepcopy(value)):
            if leaf_path == "":
                raise PatchError(f"cannot set the root of {file} to a non-mapping")
            container, key = _locate(root, parse_path(leaf_path), create=True)  # type: ignore[misc]
            if key in container:
                old = container[key]
                if old == leaf_value:
                    continue
                if (file, leaf_path) not in revisable:
                    _pend(draft, file, leaf_path, old, leaf_value)
                    continue
            container[key] = leaf_value
            draft.set_at[(file, leaf_path)] = turn
    for d in patch.get("defer") or []:
        if not isinstance(d, dict) or "gap" not in d:
            raise PatchError(f"a defer entry needs gap and reason; got {d!r}")
        why = non_deferrable(draft, str(d["gap"]))
        if why is None:
            draft.deferrals[str(d["gap"])] = str(d.get("reason") or "deferred")
        else:
            draft.open[str(d["gap"])] = f"{why}; the user said: {d.get('reason') or 'deferred'}"
    if answering is not None and answering.kind == "contradiction":
        mine = [g for g in draft.pending if g.key == answering.key]
        for g in mine:
            draft.pending.remove(g)
            m = re.match(r"^contradiction:([^#]+)#(.*)$", g.key)
            if m:
                ok, now = _get(draft.files, m.group(1), m.group(2))
                if ok and now != g.proposed:
                    draft.kept_earlier.append(g.key)


def _pend(draft: Draft, file: str, path: str, old: Any, new: Any) -> None:
    key = f"contradiction:{file}#{path}"
    for g in draft.pending:
        if g.key == key:
            g.proposed = new
            return
    facet = _leaf_facet(draft.files, file, path)
    q = (f"Earlier you said {_fmt(old, path)}; now {_fmt(new, path)} for {_describe(file, path)}. "
         "Which holds?")
    draft.pending.append(Gap(key=key, facet=facet, kind="contradiction", question=q,
                             proposed=copy.deepcopy(new), revises=((file, path),)))


# ═════════════════════════════════════════════════════════════════════════════════════════════
# PROBLEMS -- what the runtime or the seals would refuse
# ═════════════════════════════════════════════════════════════════════════════════════════════

def _task_kind_model():
    from iagent_mesh.task_kinds import TaskKind  # the model human_tasks._declared_kinds composes
    return TaskKind


def _stub_renders_as(row: dict) -> dict:
    out = dict(row)
    out.setdefault("renders_as", {"badge": "X", "title": "x", "archetype": "APPROVAL_TASK"})
    return out


def _reachable(files: Dict[str, dict]) -> set:
    """Definitions a case can reach: from every selection table, follow each non-terminal `then`
    that names a definition, and from each reached definition the rows of its chaining table."""
    decisions = _decisions(files)
    wfs = _workflows(files)
    chain_by_after = {str(t["after"]): t for _, (f, t) in decisions.items() if t.get("after")}
    terminals = {x for _, (f, t) in decisions.items() for x in (t.get("terminals") or [])}
    todo: List[dict] = []
    for _, t in _of(files, "triggers"):
        sel = decisions.get(str(t.get("selection")))
        if sel:
            todo.append(sel[1])
    seen: set = set()
    while todo:
        table = todo.pop()
        for row in table.get("rows") or []:
            then = row.get("then") if isinstance(row, dict) else None
            if then and then not in terminals and str(then) in wfs and str(then) not in seen:
                seen.add(str(then))
                if str(then) in chain_by_after:
                    todo.append(chain_by_after[str(then)])
    return seen


def problems(files: Dict[str, dict]) -> List[Gap]:
    """STRUCTURAL and CROSS-CHECK gaps only. Usable on any bundle, shipped overlays included.
    Case checks (ends, next, chaining domain, task_kind) bind only reachable definitions."""
    out: List[Gap] = []
    reach = _reachable(files)
    triggers = _of(files, "triggers")
    decisions = _decisions(files)
    wfs = _workflows(files)
    kinds = _kinds(files)
    chain_by_after: Dict[str, Tuple[str, dict]] = {}
    for name, (f, t) in decisions.items():
        if t.get("after"):
            chain_by_after.setdefault(str(t["after"]), (name, t))

    # ── the trigger and its selection table ──────────────────────────────────────────────────
    if not triggers:
        out.append(Gap("trigger.event", "trigger", "missing",
                       "What event starts this process, and what identifies one case of it?"))
    selection_names: set = set()
    for f, t in triggers:
        tname = str(t.get("trigger") or _stem(f))
        try:
            _cr.Trigger.model_validate({k: v for k, v in t.items() if k != _STAGES})
        except ValidationError as exc:
            for e in exc.errors():
                if e["type"] == "missing":
                    fld = ".".join(str(x) for x in e["loc"])
                    out.append(Gap(f"trigger.{fld}", "trigger", "missing",
                                   f"For the event that starts {_words(tname)}: what is its {_words(fld)}?"))
                else:
                    out.append(Gap("contradiction:trigger", "trigger", "contradiction",
                                   f"The start of {_words(tname)} does not hold together: "
                                   f"{_first_line(e['msg'])}. What should it be?"))
        sel = t.get("selection")
        if sel:
            selection_names.add(str(sel))
        table = decisions.get(str(sel))[1] if sel and str(sel) in decisions else None
        if table is None or not table.get("matches") or not table.get("domain") or not table.get("rows"):
            out.append(Gap("trigger.routing", "trigger", "missing",
                           f"When {_words(tname)} happens, what decides which process it opens? "
                           "Name what you look at, its possible values, and what each one opens."))
        else:
            err = _decide_all(table)
            if err:
                out.append(Gap(f"contradiction:routing.{sel}", "trigger", "contradiction",
                               f"Deciding which process {_words(tname)} opens does not work out for "
                               f"every case: {_first_line(err)}. What should happen?"))
            req = t.get("requires")
            if req:
                for attr in table.get("matches") or []:
                    if attr not in req:
                        out.append(Gap(f"trigger.requires.{attr}", "trigger", "missing",
                                       f"The routing looks at {_words(attr)}; must every "
                                       f"{_words(tname)} event carry it?"))

    # ── a `then` that names nothing ──────────────────────────────────────────────────────────
    tables_to_check = [(n, t) for n, (f, t) in decisions.items()
                       if n in selection_names or t.get("after")]
    for n, t in tables_to_check:
        terminals = set(t.get("terminals") or [])
        for row in t.get("rows") or []:
            then = row.get("then") if isinstance(row, dict) else None
            if then and then not in terminals and str(then) not in wfs:
                out.append(Gap(f"steps.{then}", "steps", "missing",
                               f"What is {_words(then)}: a stage with its own steps, or where the "
                               "workflow ends?"))

    # ── definitions ──────────────────────────────────────────────────────────────────────────
    for wid, (f, raw) in wfs.items():
        try:
            _wd.WorkflowDefinition.model_validate(raw)
        except ValidationError as exc:
            for e in exc.errors():
                loc = e["loc"]
                if e["type"] == "missing" or (loc == ("steps",) and e["type"] == "too_short"):
                    if loc and loc[0] == "steps" and len(loc) >= 4 and isinstance(loc[1], int):
                        st = _steps(raw)
                        sid = st[loc[1]].get("id") if loc[1] < len(st) else None
                        fld = ".".join(str(x) for x in loc[3:])
                        facet = _field_facet(fld.split(".")[0], st[loc[1]].get("kind") if loc[1] < len(st) else None)
                        if fld == "audience":
                            q = f"Who answers at {_words(sid)} in {_words(wid)}?"
                        else:
                            q = f"What is the {_words(fld)} of {_words(sid)} in {_words(wid)}?"
                        out.append(Gap(f"steps.{wid}.{sid}.{fld}", facet, "missing", q))
                    else:
                        fld = ".".join(str(x) for x in loc)
                        out.append(Gap(f"steps.{wid}.{fld}", "steps", "missing",
                                       f"What is the {_words(fld)} of {_words(wid)}?"))
                else:
                    out.append(Gap(f"contradiction:workflow.{wid}", "steps", "contradiction",
                                   f"{_words(wid)} does not hold together at "
                                   f"{'.'.join(str(x) for x in loc)}: {_first_line(e['msg'])}. "
                                   "What should it be?"))

    for wid, (f, raw) in wfs.items():
        if wid not in reach:
            continue
        steps = _steps(raw)
        if steps and not any(_disposes(s) for s in steps):
            out.append(Gap(f"outputs.{wid}.ends", "outputs", "missing",
                           f"How does {_words(wid)} know it has finished -- who or what confirms it?"))

    for wid, (f, raw) in wfs.items():
        if wid not in reach:
            continue
        for s in _steps(raw):
            if s.get("kind") != "human_await":
                continue
            tk = s.get("task_kind")
            if not tk or not _kinds_for(str(tk), kinds):
                who = _words(s.get("role") or str(s.get("audience") or "the reviewers").split(":")[0])
                out.append(Gap(f"approvals.{wid}.{s.get('id')}.task_kind", "approvals", "missing",
                               f"What can {who} answer on {_words(s.get('id'))}?"))

    TaskKind = _task_kind_model()
    for kname, (f, raw) in kinds.items():
        try:
            TaskKind.model_validate(_stub_renders_as(raw))
        except ValidationError as exc:
            for e in exc.errors():
                if e["type"] == "missing" and e["loc"] == ("accepts",):
                    out.append(Gap(f"approvals.{kname}.accepts", "approvals", "missing",
                                   f"What can the person answer on {_words(kname)}?"))
                else:
                    out.append(Gap(f"contradiction:task_kind.{kname}", "approvals", "contradiction",
                                   f"The answers for {_words(kname)} do not hold together: "
                                   f"{_first_line(e['msg'])}. What should they be?"))

    # ── a definition with a disposer needs a table after it; the table must fit it ───────────
    for wid, (f, raw) in wfs.items():
        if wid not in reach:
            continue
        verbs, last = _emits(raw, kinds)
        if last is None:
            continue
        facet = "approvals" if last.get("kind") == "human_await" else "outputs"
        if wid not in chain_by_after:
            tail = (f" It can end: {', '.join(verbs)}." if verbs else "")
            out.append(Gap(f"{facet}.{wid}.next", facet, "missing",
                           f"When {_words(wid)} ends, what happens next?{tail}"))

    for wid, (f, raw) in wfs.items():
        if wid not in reach:
            continue
        if wid not in chain_by_after:
            continue
        tname, table = chain_by_after[wid]
        tfile = decisions[tname][0]
        verbs, last = _emits(raw, kinds)
        if verbs is not None and last is not None:
            facet = "approvals" if last.get("kind") == "human_await" else "outputs"
            D = list((table.get("domain") or {}).get("outcome") or [])
            step_w = _words(last.get("id"))
            revises: List[Tuple[str, str]] = [(tfile, "domain.outcome"), (tfile, "rows"), (tfile, "terminals")]
            if last.get("kind") == "human_await":
                for n in _kinds_for(str(last.get("task_kind") or ""), kinds):
                    revises += [(kinds[n][0], "accepts"), (kinds[n][0], "reason_required")]
            elif last.get("kind") == "signal_await":
                sp = f"steps[id={last.get('id')}]"
                revises += [(f, f"{sp}.accepts"), (f, f"{sp}.reason_required")]
            for v in D:
                if v not in verbs:
                    out.append(Gap(f"contradiction:chaining.{tname}.{v}", facet, "contradiction",
                                   f"You said what happens when {step_w} ends '{v}', but {step_w}'s "
                                   f"answers are {', '.join(verbs)}. Can it end '{v}'?",
                                   revises=tuple(revises)))
            for v in verbs:
                if v not in D:
                    out.append(Gap(f"{facet}.{wid}.next.{v}", facet, "missing",
                                   f"When {_words(wid)} ends '{v}', what happens next?",
                                   revises=tuple(revises)))
        err = _decide_all(table)
        # a missing value or row is a required slot asked by name; this asks only what is left
        if err and not _chain_slots(wid, "outputs", tfile, table, verbs):
            out.append(Gap(f"contradiction:chaining.{tname}", "outputs", "contradiction",
                           f"What happens after {_words(wid)} does not work out for every outcome: "
                           f"{_first_line(err)}. What should happen?"))

    if not any(t.get("terminals") for _, (f, t) in decisions.items()):
        out.append(Gap("outputs.end", "outputs", "missing",
                       "Where does a case end? Name the final states (for example approved, "
                       "rejected, withdrawn)."))
    return out


# ═════════════════════════════════════════════════════════════════════════════════════════════
# GAPS
# ═════════════════════════════════════════════════════════════════════════════════════════════

_CHAIN_INPUT = "outcome"  # the fact case_routing hands a chaining table when it reads no `matches`


def _no_row(table: dict, facts: dict) -> bool:
    """True iff the REAL ``decide`` refuses ``facts`` and one more row for exactly them would make
    it choose: the refusal is a missing row, not two rows or a row with no ``then``."""
    try:
        _dt.decide(table, facts)
        return False
    except _dt.DecisionError:
        pass
    probe = dict(table, rows=list(table.get("rows") or []) + [{"when": dict(facts), "then": "probe"}])
    try:
        _dt.decide(probe, facts)
        return True
    except _dt.DecisionError:
        return False


def _chain_slots(wid: str, facet: str, tfile: str, table: dict,
                 verbs: Optional[List[str]]) -> List[Gap]:
    """The named slots of the routing table after ``wid`` (architect, 2026-10-30): the values of
    each input it reads, then a row for each combination of them. Runs 10 to 12 (ADR-0061 §10)
    never had the model supply either unasked."""
    out: List[Gap] = []
    attrs = list(table.get("matches") or [])
    domain = table.get("domain") or {}
    revises = tuple([(tfile, "matches")] + [(tfile, f"domain.{a}") for a in attrs or [_CHAIN_INPUT]]
                    + [(tfile, "rows"), (tfile, "terminals")])
    empty = [a for a in attrs if not list(domain.get(a) or [])] if attrs else [_CHAIN_INPUT]
    for a in empty:
        tail = f" It can end: {', '.join(verbs)}." if verbs and a == _CHAIN_INPUT else ""
        out.append(Gap(f"{facet}.{wid}.next.domain.{a}", facet, "missing",
                       f"Required: every {_words(a)} the routing after {_words(wid)} decides on.{tail} "
                       "List them all.", revises=revises))
    if empty:
        return out
    for combo in itertools.product(*[list(domain[a]) for a in attrs]):
        facts = dict(zip(attrs, combo))
        if not _no_row(table, facts):
            continue
        when = (f"'{combo[0]}'" if len(attrs) == 1
                else ", ".join(f"{_words(a)} '{c}'" for a, c in facts.items()))
        listed = [str(c) for c in combo if c in (table.get("terminals") or [])]
        # run 18 listed outcomes as terminals and left them without rows (ADR-0061 §10)
        hint = (f" ('{listed[0]}' is listed as a final state, but a final state is what a row "
                f"points to: the row for '{listed[0]}' still has to name it.)" if listed else "")
        out.append(Gap(f"{facet}.{wid}.next.{'+'.join(str(c) for c in combo)}", facet, "missing",
                       f"Required: when {_words(wid)} ends {when}, what happens next?{hint}",
                       revises=revises))
    return out


def required_slots(files: Dict[str, dict]) -> List[Gap]:
    """Slots asked by name for EVERY definition in the draft, reachable or not (ADR-0061 R4): the
    trigger's stages and each stage not yet drafted, the task kind of each approval, who is barred
    from answering each approval (``excludes``), the routing table after each definition that ends
    in a verb, and the values and rows of every routing table that names a drafted definition."""
    out: List[Gap] = []
    wfs = _workflows(files)
    kinds = _kinds(files)
    decisions = _decisions(files)
    chain_by_after: Dict[str, Tuple[str, dict]] = {}
    for name, (tf, t) in decisions.items():
        if t.get("after"):
            chain_by_after.setdefault(str(t["after"]), (tf, t))
    for f, t in _of(files, "triggers"):
        stages = t.get(_STAGES)
        if not isinstance(stages, list) or not stages:
            out.append(Gap(f"trigger.{_STAGES}", "trigger", "missing",
                           f"Required: every stage a {_words(t.get('trigger') or _stem(f))} case can "
                           "pass through, in order -- each review, approval, acknowledgement or "
                           "record. Name them all.", revises=((f, _STAGES),)))
            continue
        for st in stages:
            if str(st) not in wfs:
                out.append(Gap(f"steps.{st}", "steps", "missing",
                               f"Required: the stage {_words(st)} is not described yet. What happens "
                               "in it: who acts, what they decide, and how it ends?",
                               revises=((f, _STAGES),)))
    for wid, (f, raw) in wfs.items():
        for s in _steps(raw):
            if s.get("kind") != "human_await":
                continue
            tk = s.get("task_kind")
            if not tk or not _kinds_for(str(tk), kinds):
                out.append(Gap(f"approvals.{wid}.{s.get('id')}.task_kind", "approvals", "missing",
                               f"Required: the task kind for the approval {_words(s.get('id'))} in "
                               f"{_words(wid)}. Name it and the answers a person can give there "
                               "(for example approve, reject)."))
            if "excludes" not in s:
                out.append(Gap(f"actors.{wid}.{s.get('id')}.excludes", "actors", "missing",
                               f"Required: who is barred from answering at {_words(s.get('id'))} in "
                               f"{_words(wid)} -- for example whoever submitted it? Say nobody if no "
                               "one is."))
    for wid, (f, raw) in wfs.items():
        verbs, last = _emits(raw, kinds)
        facet = "approvals" if last is not None and last.get("kind") == "human_await" else "outputs"
        if wid in chain_by_after:
            # bound to the table, not to a stage that can end: run 15's empty table after a stage
            # with no disposing step was never asked about (ADR-0061 §10)
            out += _chain_slots(wid, facet, *chain_by_after[wid], verbs)
            continue
        if last is None:
            continue
        tail = f": {', '.join(verbs)}" if verbs else ""
        out.append(Gap(f"{facet}.{wid}.next", facet, "missing",
                       f"Required: the routing table after {_words(wid)} -- for each way it can "
                       f"end{tail}, what happens next?"))
    return out


def _related(a: str, b: str) -> bool:
    """True iff dotted key or path ``a`` is ``b`` or one is the other's prefix at a segment."""
    return (a == b or a.startswith(b + ".") or a.startswith(b + "[")
            or b.startswith(a + ".") or b.startswith(a + "["))


def _set_turn(draft: Draft, file: str, path: str) -> Optional[int]:
    """The last turn that set ``path`` of ``file``, or a leaf over or under it; None if none."""
    turns = [t for (f, p), t in draft.set_at.items() if f == file and _related(p, path)]
    return max(turns) if turns else None


def _value_slots(files: Dict[str, dict]) -> List[Tuple[str, str, Tuple[Tuple[str, str], ...], str]]:
    """Each required slot the draft already HOLDS a value for, as (key, facet, leaves, what the
    draft says): the slot's key is the one ``required_slots`` asks while the value is absent."""
    out: List[Tuple[str, str, Tuple[Tuple[str, str], ...], str]] = []
    wfs, kinds, decisions = _workflows(files), _kinds(files), _decisions(files)
    chain_by_after: Dict[str, Tuple[str, dict]] = {}
    for name, (tf, t) in decisions.items():
        if t.get("after"):
            chain_by_after.setdefault(str(t["after"]), (tf, t))
    for f, t in _of(files, "triggers"):
        stages = t.get(_STAGES)
        if isinstance(stages, list) and stages:
            out.append((f"trigger.{_STAGES}", "trigger", ((f, _STAGES),),
                        f"a {_words(t.get('trigger') or _stem(f))} case passes through "
                        f"{', '.join(_words(x) for x in stages)}, in that order"))
    for wid, (f, raw) in wfs.items():
        for s in _steps(raw):
            sid = s.get("id")
            if s.get("kind") != "human_await" or not sid:
                continue
            tk = s.get("task_kind")
            named = _kinds_for(str(tk), kinds) if tk else []
            if named:
                kf, kraw = kinds[named[0]]
                acc = kraw.get("accepts")
                out.append((f"approvals.{wid}.{sid}.task_kind", "approvals",
                            ((f, f"steps[id={sid}].task_kind"), (kf, "accepts")),
                            f"{_words(sid)} in {_words(wid)} is a {_words(tk)} task"
                            + (f", answered {' or '.join(map(str, acc))}" if isinstance(acc, list) and acc
                               else "")))
            if "excludes" in s:
                ex = s["excludes"]
                said = (f"nobody is barred from answering at {_words(sid)} in {_words(wid)}"
                        if not ex else f"{_fmt(ex)} may not answer at {_words(sid)} in {_words(wid)}")
                out.append((f"actors.{wid}.{sid}.excludes", "actors",
                            ((f, f"steps[id={sid}].excludes"),), said))
    for wid, (f, raw) in wfs.items():
        if wid not in chain_by_after:
            continue
        verbs, last = _emits(raw, kinds)
        facet = "approvals" if last is not None and last.get("kind") == "human_await" else "outputs"
        tf, table = chain_by_after[wid]
        if _chain_slots(wid, facet, tf, table, verbs):
            continue  # not complete: its own slots are asked
        rows = "; ".join(f"{_fmt(r.get('when'))} -> {r.get('then')}"
                         for r in table.get("rows") or [] if isinstance(r, dict))
        out.append((f"{facet}.{wid}.next", facet,
                    tuple((tf, x) for x in ("matches", "domain", "rows", "terminals")),
                    f"after {_words(wid)}: {rows}"))
    return out


def _attributed(draft: Draft, key: str, leaves: Tuple[Tuple[str, str], ...]) -> bool:
    """True iff the person answered a question about each leaf of the slot in or after the turn
    that last set it (ADR-0061 §10, the turn check, architect 2026-10-30): a question whose key is
    the slot's or over or under it, or one naming the leaf itself (a confirm, an overwrite
    contradiction). The stage question asks what the approver decides, so it covers that stage's
    task kinds. The opening asks nothing, so it covers nothing."""
    stage = "steps." + key.split(".")[1] if key.endswith(".task_kind") else None
    for file, path in leaves:
        t = _set_turn(draft, file, path)
        if t is None:
            continue
        if any(f == file and _related(p, path) and vt >= t for (f, p), vt in draft.vouched.items()):
            continue
        if any(at >= t and (_related(k, key) or k == stage) for k, at in draft.answered.items()):
            continue
        return False
    return True


def confirms(draft: Draft) -> List[Gap]:
    """A required slot the draft holds a value for that the person was never asked about: asked
    once to confirm (ADR-0061 §10). Runs 10 to 18 drafted ``excludes: []`` on every approval
    unasked, so the planted contradiction behind that question was never reached. An answer that
    differs replaces the slot's own value; one that touches a leaf the person did state is an
    overwrite contradiction, asked like any other."""
    out: List[Gap] = []
    for key, facet, leaves, said in _value_slots(draft.files):
        if _attributed(draft, key, leaves):
            continue
        out.append(Gap(key, facet, "confirm",
                       f"Required, to confirm: the draft says {said}, but you were never asked "
                       "about it. Is that right? If not, what is it?", revises=leaves))
    return out


_BARRED_RX = re.compile(r"actors\.[^.]+\.[^.]+\.excludes")


def non_deferrable(draft: Draft, key: str) -> Optional[str]:
    """Why ``key`` may not be deferred (ADR-0061 section 5), or None when it may. A runtime refusal,
    a required slot, and who is barred from an approval are never deferred: they are left open."""
    if any(x.key == key for x in problems(draft.files)):
        return "a runtime refusal may not be deferred"
    if any(x.key == key for x in required_slots(draft.files)):
        return "a required slot may not be deferred"
    if any(x.key == key for x in confirms(draft)):
        return "a required slot the person has not confirmed may not be deferred"
    if _BARRED_RX.fullmatch(key):
        return "who is barred from an approval may not be deferred"
    return None


def _status(gaps_left: List[str], open_keys: List[str], runnable_errors: List[str]) -> str:
    """``runnable`` only when nothing is left to settle, nothing is open, and the case runner would
    not refuse the bundle. There is no "done"."""
    return "runnable" if not gaps_left and not open_keys and not runnable_errors else "cannot_run"


def _completeness(files: Dict[str, dict]) -> List[Gap]:
    out: List[Gap] = []
    for f, t in _of(files, "triggers"):
        if "requires" not in t:
            out.append(Gap("trigger.requires", "trigger", "missing",
                           f"Which details must every {_words(t.get('trigger') or _stem(f))} event "
                           "carry before you would accept it?"))
    reach = _reachable(files)
    for wid, (f, raw) in _workflows(files).items():
        if wid not in reach:
            continue
        for s in _steps(raw):
            if s.get("kind") != "human_await":
                continue
            sid = s.get("id")
            if "deadline_seconds" not in s:
                out.append(Gap(f"approvals.{wid}.{sid}.deadline", "approvals", "missing",
                               f"How long may {_words(sid)} in {_words(wid)} wait for an answer "
                               "before it counts as overdue, if at all?"))
    for kname, (f, raw) in _kinds(files).items():
        if "reason_required" not in raw:
            acc = raw.get("accepts")
            tail = f" Answers are: {', '.join(acc)}." if isinstance(acc, list) and acc else ""
            out.append(Gap(f"approvals.{kname}.reason_required", "approvals", "missing",
                           f"Which answers on {_words(kname)} must come with a stated reason?{tail}"))
    has_emit = any(s.get("kind") == "emit" for _, (f, r) in _workflows(files).items() for s in _steps(r))
    if not has_emit:
        out.append(Gap("outputs.record", "outputs", "missing",
                       "Should anything be recorded or sent out once a case is decided? If so, what "
                       "and where?"))
    return out


def gaps(draft: Draft) -> List[Gap]:
    """Everything still to settle, highest priority first: pending overwrite contradictions, then
    other contradictions, then missing items by facet (trigger, actors, steps, approvals, outputs).
    A gap whose key is deferred is settled. A confirm is asked once."""
    return [g for g in _all_gaps(draft) if draft.asked[g.key] < (1 if g.kind == "confirm" else 2)]


def _all_gaps(draft: Draft) -> List[Gap]:
    """``gaps`` before the asked-twice cut. A confirm ranks after every missing item; an open key
    ranks after every other gap."""
    rest = (required_slots(draft.files) + problems(draft.files) + _completeness(draft.files)
            + confirms(draft))
    seen: set = set()
    pend, contra, missing, confirm = [], [], [], []
    for g in list(draft.pending) + rest:
        if g.key in seen or g.key in draft.deferrals:
            continue
        seen.add(g.key)
        if any(g is p for p in draft.pending):
            pend.append(g)
        elif g.kind == "contradiction":
            contra.append(g)
        elif g.kind == "confirm":
            confirm.append(g)
        else:
            missing.append(g)
    missing.sort(key=lambda g: _FACET_RANK[g.facet])  # stable: generation order within a facet
    confirm.sort(key=lambda g: _FACET_RANK[g.facet])
    out = pend + contra + missing + confirm
    return [g for g in out if g.key not in draft.open] + [g for g in out if g.key in draft.open]


# ═════════════════════════════════════════════════════════════════════════════════════════════
# RESTATE
# ═════════════════════════════════════════════════════════════════════════════════════════════

def restate(draft: Draft) -> str:
    files = draft.files
    lines: List[str] = ["So far I have:"]
    decisions = _decisions(files)
    for f, t in _of(files, "triggers"):
        tn = t.get("trigger") or _stem(f)
        lines.append(f"- Start: {_words(tn)}; one case per {t.get('key', '?')}"
                     + (f"; same episode when {', '.join(t['episode'])} match" if t.get("episode") else "")
                     + (f"; must carry {', '.join(t['requires'])}" if t.get("requires") else "") + ".")
        sel = decisions.get(str(t.get("selection")))
        if sel:
            tab = sel[1]
            for row in tab.get("rows") or []:
                lines.append(f"  - {_fmt(row.get('when'))} opens {_words(row.get('then'))}")
    for wid, (f, raw) in _workflows(files).items():
        lines.append(f"- {_words(wid)}:")
        for s in _steps(raw):
            bits = [str(s.get("kind"))]
            if s.get("audience"):
                bits.append(f"for {str(s['audience']).split(':')[0]}")
            if s.get("task_kind"):
                k = _kinds(files).get(str(s["task_kind"]))
                if k and k[1].get("accepts"):
                    bits.append("answers " + "/".join(k[1]["accepts"]))
            if s.get("kind") == "human_await":
                if "deadline_seconds" in s:
                    bits.append("no deadline" if s["deadline_seconds"] is None
                                else f"deadline {_fmt(s['deadline_seconds'], 'deadline_seconds')}")
                elif f"approvals.{wid}.{s.get('id')}.deadline" in draft.deferrals:
                    bits.append("deadline deferred")
                if s.get("excludes"):
                    bits.append("excludes " + ", ".join(s["excludes"]))
            if s.get("kind") == "emit":
                bits.append(f"to channel {s.get('channel')}")
            lines.append(f"  - {_words(s.get('id'))}: " + "; ".join(bits))
    for name, (f, t) in decisions.items():
        if t.get("after"):
            rows = "; ".join(f"{_fmt(r.get('when'))} -> {r.get('then')}" for r in t.get("rows") or [])
            lines.append(f"- After {_words(t['after'])}: {rows}")
    if draft.deferrals:
        lines.append("- Deferred: " + "; ".join(f"{k} ({v})" for k, v in draft.deferrals.items()))
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════════════════════
# FINALIZE -- the derived parts, never asked
# ═════════════════════════════════════════════════════════════════════════════════════════════

def finalize(files: Dict[str, dict]) -> Dict[str, dict]:
    out = copy.deepcopy(files)
    for f, d in _of(out, "triggers"):
        d.pop(_STAGES, None)
    for f, d in _of(out, "workflows"):
        roles: List[str] = []
        for s in _steps(d):
            if s.get("kind") == "human_await" and s.get("role") and s["role"] not in roles:
                roles.append(s["role"])
        if roles:
            d["participants"] = [{"role": r} for r in roles]
        else:
            d.pop("participants", None)
    for f, d in _of(out, "task_kinds"):
        kind = str(d.get("kind") or _stem(f))
        d.setdefault("renders_as", {
            "badge": kind.upper().replace("_", "-")[:12],
            "title": _words(kind).capitalize(),
            "archetype": "APPROVAL_TASK",
        })
    return out


# ═════════════════════════════════════════════════════════════════════════════════════════════
# RUNNABLE -- the REAL loaders
# ═════════════════════════════════════════════════════════════════════════════════════════════

_ENV = ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR")


def runnable(files: Dict[str, dict]) -> List[str]:
    """Write ``finalize(files)`` to a temp dir and load it with the runtime's own loaders; the
    error strings, [] when the runtime would accept it.

    ENV PARSING (read, not assumed): ``CASE_TRIGGER_DIR`` and ``DECISION_TABLE_DIR`` are
    ``os.pathsep`` lists whose FIRST entry is the seed; ``WORKFLOW_DEFINITIONS_DIR`` is a list too.
    NONE OF THE LOADERS CACHES across calls (``load_tables``/``load_triggers`` re-read the
    directory each call), so nothing is cleared. Task kinds go through
    ``iagent_mesh.task_kinds.compose`` -- the composer ``human_tasks._declared_kinds`` calls --
    with the temp dir as the seed (``_declared_kinds`` itself caches in a module global and reads
    a fixed seed directory, so it is not used)."""
    errors: List[str] = []
    fin = finalize(files)
    saved = {k: os.environ.get(k) for k in _ENV}
    with tempfile.TemporaryDirectory(prefix="socratic-") as tmp:
        root = Path(tmp)
        for folder in _FOLDERS:
            (root / folder).mkdir()
        for rel, body in fin.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.environ["CASE_TRIGGER_DIR"] = str(root / "triggers")
        os.environ["DECISION_TABLE_DIR"] = str(root / "decisions")
        os.environ["WORKFLOW_DEFINITIONS_DIR"] = str(root / "workflows")
        try:
            triggers: dict = {}
            tables: dict = {}
            wfs: dict = {}
            kinds: dict = {}
            for label, fn, sink in (
                ("triggers", _cr.load_triggers, "triggers"),
                ("decision tables", _dt.load_tables, "tables"),
                ("workflows", lambda: _wd.load_all_workflows(root / "workflows"), "wfs"),
                ("task kinds", lambda: {k.kind: k for k in _task_compose(root / "task_kinds")}, "kinds"),
            ):
                try:
                    got = fn()
                    {"triggers": triggers, "tables": tables, "wfs": wfs, "kinds": kinds}[sink].update(got)
                except Exception as exc:  # noqa: BLE001 -- every loader refusal is a string
                    errors.append(f"{label}: {_first_line(exc, 300)}")
            try:
                index = _cr.chaining_index(tables) if tables else {}
            except Exception as exc:  # noqa: BLE001
                index = {}
                errors.append(f"chaining index: {_first_line(exc, 300)}")

            requires = {r for t in triggers.values() for r in t.requires}
            for tname, t in triggers.items():
                if t.selection not in tables:
                    errors.append(f"trigger {tname}: selection table {t.selection!r} is not declared")
            for tname, table in tables.items():
                err = _decide_all(table)
                if err:
                    errors.append(f"table {tname}: {_first_line(err, 300)}")
                terminals = set(table.get("terminals") or [])
                for row in table.get("rows") or []:
                    then = row.get("then")
                    if then and then not in terminals and then not in wfs:
                        errors.append(f"table {tname}: `then` {then!r} is neither a definition nor a terminal")
                after = table.get("after")
                if after:
                    if after not in wfs:
                        errors.append(f"table {tname}: `after: {after}` names no definition")
                    for attr in table.get("matches") or []:
                        if (attr not in _cr.TERMINATION_FACTS and not attr.startswith("chosen.")
                                and attr not in requires):
                            errors.append(f"table {tname}: matches {attr!r}, which no trigger requires "
                                          "and the runner does not measure at termination")
            for wid, wf in wfs.items():
                for s in wf.steps:
                    if getattr(s, "kind", None) == "human_await":
                        tk = s.task_kind or ""
                        if not _kinds_for(tk, kinds):
                            errors.append(f"definition {wid}: step {s.id} names task kind {tk!r}, "
                                          "which no row declares")
                if any(_disposes({"kind": s.kind, "outcome_from": getattr(s, "outcome_from", None)})
                       for s in wf.steps) and wid not in index:
                    errors.append(f"definition {wid}: no table declares `after: {wid}`")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return errors


def _task_compose(directory: Path, overlays: Optional[List[Path]] = None):
    from iagent_mesh.task_kinds import compose
    return compose(directory, overlays or [])


_TASK_KIND_OVERLAY_ENV = "TASK_KIND_OVERLAY_DIRS"  # the variable human_tasks composes over


def served_examples() -> Tuple[str, str]:
    """One chaining table and one task kind, as YAML, for the prompt. They are there for FORMAT ONLY.

    They come from the policy this runtime composes: the decision tables through ``load_tables``,
    and the task kinds through the seed beside them plus ``TASK_KIND_OVERLAY_DIRS``. So no code
    names a workflow's file, and a deployment's own rows can be the examples.

    The choice is the first by sorted name, so the prompt is stable for a given policy. When the
    composed policy has no chaining table or no task kind, this raises. A prompt with no examples
    would be a different prompt that nobody chose.
    """
    tables = _dt.load_tables()
    chaining = sorted(k for k, v in tables.items() if v.get("after"))
    seeds = [r / "task_kinds" for r in _dt.candidate_decision_dirs(Path(_dt.__file__))
             if (r / "task_kinds").is_dir()]
    overlays = [Path(p.strip()) for p in (os.environ.get(_TASK_KIND_OVERLAY_ENV) or "").split(os.pathsep)
                if p.strip()]
    kinds = sorted(_task_compose(seeds[0], overlays), key=lambda k: k.kind) if seeds else []
    if not chaining or not kinds:
        raise ValueError(
            "the composed policy has no chaining table or no task kind to show the model as an "
            f"example (chaining tables: {len(chaining)}, task kinds: {len(kinds)}); configure "
            f"DECISION_TABLE_DIR and {_TASK_KIND_OVERLAY_ENV}")
    dump = lambda body: yaml.safe_dump(body, sort_keys=False, allow_unicode=True)  # noqa: E731
    return dump(tables[chaining[0]]), dump(kinds[0].model_dump(mode="json", exclude_none=True))


# ═════════════════════════════════════════════════════════════════════════════════════════════
# EXTRACTORS
# ═════════════════════════════════════════════════════════════════════════════════════════════

class OracleExtractor:
    """Reads the fixture's annotation: the entry's ``facts`` ARE the patch."""

    def __call__(self, utterance_entry: dict, draft: Draft, gap: Optional[Gap]) -> dict:
        return copy.deepcopy(utterance_entry.get("facts") or {})


_LOCAL_HOSTS = ("localhost", "0.0.0.0", "::1", "[::1]")


def _refuse_local(base_url: str) -> str:
    from urllib.parse import urlparse
    if not base_url or not base_url.strip():
        raise ValueError("a model extractor needs a base_url; there is no default")
    u = urlparse(base_url if "://" in base_url else "//" + base_url)
    host = (u.hostname or "").lower()
    if not host or host in _LOCAL_HOSTS or host.startswith("127."):
        raise ValueError("no model runs on the dev box (ruled 2026-10-09): refusing a local base_url")
    return base_url.rstrip("/")


_GRAMMAR = """\
You turn ONE statement from a domain user into a PATCH of a partial configuration bundle.
Reply with JSON only: {"set": [...], "defer": [...]}.

set entry : {"file": "<folder>/<name>.yaml", "path": "<path>", "value": <json>}
defer entry: {"gap": "<gap key>", "reason": "<the user's words>"}

PATH: dotted keys. `name[k=v]` selects the element of list `name` whose mapping has key k equal
to v (string compare), created at the end if absent. "" is the file root. A MAPPING value is applied
leaf by leaf; a LIST value is one leaf (the whole list). null is a value: `deadline_seconds: null`
means "explicitly no deadline". `[]` for `excludes` means "nobody is barred".

FOLDERS and files: triggers/<trigger>.yaml, decisions/<decision>.yaml, workflows/<id>.yaml,
task_kinds/<kind>.yaml. A user's process is: a TRIGGER (the event, the case key, the facts that make
two events one episode, the facts later tables need), a SELECTION table (decision table mapping the
event's facts to the first workflow), WORKFLOWS (steps: human_await, signal_await, emit, render,
wait ...), one CHAINING table per workflow (`after: <workflow id>`, matching `outcome`, naming the
next workflow or a declared terminal), and TASK KINDS (`accepts`, `reason_required`).

RULES
- Emit ONLY facts the statement makes. Never infer, never fill a default, never add a field the user
  did not speak to.
- Use ONLY the event fields and audiences listed in the context; write an event field as
  "{trigger.<field>}" in a template or exclusion.
- When the question is a contradiction ("Which holds?"), set exactly the path the question names.
- When the user says they cannot say yet, DEFER the gap being asked, with their reason.
- REQUIRED: the trigger lists `stages`: every workflow id a case can pass through, in the user's
  order (a stage already drafted is named by its workflow id). Each stage is drafted as
  workflows/<stage>.yaml with id <stage>.
- REQUIRED: every human_await step has task_kind naming a task_kinds/<kind>.yaml you also set
  (with accepts).
- REQUIRED: every workflow has a chaining table (decisions/<x>.yaml with after: <workflow id>).
- REQUIRED: every chaining table declares matches, a domain listing every value of each input it
  matches (for outcome: every way the workflow can end), and one row for each of those values.
- A terminal is what a row points to (`then: <terminal>`), not an outcome: every value in the
  domain still needs its own row, and an outcome that ends the case has a row whose `then` names a
  terminal listed in `terminals`.
- REQUIRED: every human_await step sets excludes: the "{trigger.<field>}" of whoever may not
  answer, or [] when the user says anyone may answer or nobody is barred.
- A step with a deadline_seconds can also end timed_out (the runner's outcome when the deadline
  expires), so its workflow's chaining table routes timed_out as well.
- A row matches an event field only with one of its listed event values; map the user's words to
  the value whose label they match.
- A chaining or selection table is set whole: decision, after (chaining), matches, domain, rows,
  terminals (chaining), in one statement.
"""


class ModelExtractor:
    """An extractor that asks a model for the patch. Not exercised by pytest.

    It never sees ``facts`` or ``expected/``. It refuses a local base_url (no model runs on the dev
    box) and a model tag the server does not list. A reply that is not a well-formed patch counts in
    ``errors`` and yields an empty patch."""

    def __init__(self, base_url: str, model: str, timeout_s: float = 180):
        self.base_url = _refuse_local(base_url)
        self.model = model
        self.timeout_s = timeout_s
        self.errors = 0
        self.transport_errors: List[str] = []
        self.context: dict = {}
        self._checked = False
        self._system: Optional[str] = None

    def with_context(self, context: dict) -> "ModelExtractor":
        self.context = dict(context or {})
        return self

    def _system_prompt(self) -> str:
        if self._system is None:
            ex_chain, ex_kind = served_examples()
            wf = json.dumps(_wd.WorkflowDefinition.model_json_schema(), separators=(",", ":"))
            tr = json.dumps(_cr.Trigger.model_json_schema(), separators=(",", ":"))
            self._system = (f"{_GRAMMAR}\nWorkflowDefinition schema: {wf}\n\nTrigger schema: {tr}\n\n"
                            f"Example chaining table (format only):\n{ex_chain}\n\n"
                            f"Example task kind (format only):\n{ex_kind}\n")
        return self._system

    def _check_model(self, client) -> None:
        r = client.get(f"{self.base_url}/api/tags")
        r.raise_for_status()
        tags = {m.get("name") for m in (r.json().get("models") or [])}
        if self.model not in tags:
            raise ValueError(f"model tag {self.model!r} is not listed by the server")
        self._checked = True

    def __call__(self, utterance_entry: dict, draft: Draft, gap: Optional[Gap]) -> dict:
        import httpx
        user = (
            f"CONTEXT\nevent fields: {self.context.get('event_fields')}\n"
            f"audiences: {self.context.get('audiences')}\n"
            f"event values: {self.context.get('event_values')}\n\n"
            f"CURRENT DRAFT (files)\n{yaml.safe_dump(draft.files, sort_keys=False)}\n"
            f"QUESTION\n{('OPENING' if gap is None else gap.key + ': ' + gap.question)}\n\n"
            f"STATEMENT\n{utterance_entry.get('says', '')}\n")
        if utterance_entry.get("refused"):
            user += (f"\nREFUSED\nYour previous patch for this statement was refused: "
                     f"{utterance_entry['refused']}\nRestate the whole patch in the path grammar.\n")
        body = {"model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
                "messages": [{"role": "system", "content": self._system_prompt()},
                             {"role": "user", "content": user}]}
        with httpx.Client(timeout=self.timeout_s) as client:
            if not self._checked:
                self._check_model(client)
            # A transport failure is one counted error and an empty patch, never a crash: the loop
            # then asks again or defers, which is what the measurement should see. The exception's
            # text names the host, so only its type is kept.
            try:
                r = client.post(f"{self.base_url}/api/chat", json=body)
                r.raise_for_status()
                content = r.json().get("message", {}).get("content", "")
            except (httpx.HTTPError, ValueError) as exc:
                self.errors += 1
                self.transport_errors.append(type(exc).__name__)
                return {"set": [], "defer": []}
        return self._parse(content)

    def _parse(self, content: str) -> dict:
        try:
            obj = json.loads(content)
            ok = isinstance(obj, dict)
            sets = obj.get("set", []) if ok else []
            defers = obj.get("defer", []) if ok else []
            ok = ok and isinstance(sets, list) and isinstance(defers, list)
            ok = ok and all(isinstance(s, dict) and {"file", "path", "value"} <= set(s) for s in sets)
            ok = ok and all(isinstance(d, dict) and "gap" in d for d in defers)
        except (ValueError, AttributeError):
            ok = False
        if not ok:
            self.errors += 1
            return {"set": [], "defer": []}
        return {"set": sets, "defer": defers}


# ═════════════════════════════════════════════════════════════════════════════════════════════
# THE LOOP
# ═════════════════════════════════════════════════════════════════════════════════════════════

PATCH_RESTATES = 1  # times the model is asked to restate a refused patch before the turn moves on


def _apply_or_charge(draft: Draft, extractor: Callable[[dict, Draft, Optional[Gap]], dict],
                     entry: dict, gap: Optional[Gap], turn: int, charged: List[dict]) -> None:
    """Apply the extractor's patch for one turn. A patch the loop cannot apply is a model error
    charged to that turn (architect, 2026-10-30): it is recorded, the model is asked to restate it
    with the refusal in hand, and the loop continues. A run never crashes on model output. The
    patch is tried on a copy, so nothing of a refused patch lands in the draft."""
    ask = entry
    for _ in range(1 + PATCH_RESTATES):
        trial = copy.deepcopy(draft)
        try:
            apply_patch(trial, extractor(ask, draft, gap), turn, answering=gap)
        except PatchError as exc:
            charged.append({"turn": turn, "error": str(exc)})
            ask = {**entry, "refused": str(exc)}
            continue
        draft.__dict__.update(trial.__dict__)
        return


def run(transcript: dict, extractor: Callable[[dict, Draft, Optional[Gap]], dict],
        max_turns: int = 40,
        answer: Optional[Callable[[Gap, Draft], Optional[dict]]] = None) -> dict:
    """``answer(gap, draft)`` is the scripted user; the default is the exact-key bank lookup."""
    draft = Draft()
    if hasattr(extractor, "with_context"):
        extractor.with_context(transcript.get("context") or {})  # type: ignore[attr-defined]
    opening = transcript["opening"]
    model_errors: List[dict] = []
    _apply_or_charge(draft, extractor, opening, None, 0, model_errors)
    questions: List[dict] = []
    messages: List[dict] = []
    contradictions_asked: List[str] = []
    unanswerable = unresolved = turn = 0
    stalled: List[str] = []
    answers = transcript.get("answers") or {}
    if answer is None:
        def answer(g: Gap, d: Draft) -> Optional[dict]:  # noqa: F811
            return answers.get(g.key)
    # ADR-0061 section 5: a runtime refusal may not be deferred. MEASURED here, not enforced.
    refused: set = set()
    snap: Optional[Tuple[set, set]] = None

    def note() -> None:
        if snap is not None:
            refused.update(k for k in draft.deferrals if k not in snap[1] and k in snap[0])

    def prune_open() -> None:
        live = {x.key for x in _all_gaps(draft)}
        for k in [k for k in draft.open if k not in live]:
            del draft.open[k]

    def leave(g: Gap, reason: str) -> None:
        """A gap nobody settled: deferred when it may be, else left open."""
        why = non_deferrable(draft, g.key)
        if why is None:
            draft.deferrals[g.key] = reason
        else:
            draft.open[g.key] = f"{why}; {reason}"

    while turn < max_turns:
        note()
        prune_open()
        pending_gaps = gaps(draft)
        if not pending_gaps:
            break
        snap = ({x.key for x in problems(draft.files)}, set(draft.deferrals))
        g = pending_gaps[0]
        turn += 1
        draft.asked[g.key] += 1
        questions.append({"key": g.key, "kind": g.kind, "facet": g.facet})
        if g.kind == "contradiction":
            contradictions_asked.append(g.key)
        entry = answer(g, draft)
        messages.append({"turn": turn, "agent": restate(draft) + "\n\n" + g.question,
                         "user": (entry or {}).get("says")})
        if entry is None:
            unanswerable += 1
            leave(g, "user could not answer")
            if any(p.key == g.key for p in draft.pending):
                draft.pending = [p for p in draft.pending if p.key != g.key]
            continue
        before = copy.deepcopy((draft.files, draft.deferrals))
        _apply_or_charge(draft, extractor, entry, g, turn, model_errors)
        draft.answered[g.key] = turn
        if g.kind in ("confirm", "contradiction"):
            for leaf in g.revises:
                draft.vouched[leaf] = turn
        live = g.key not in draft.deferrals and any(x.key == g.key for x in _all_gaps(draft))
        if live and draft.asked[g.key] > 1 and (draft.files, draft.deferrals) == before:
            # asked again (a repeat is of an open key) and the answer changed nothing: run 18
            # asked ten questions twice (ADR-0061 §10)
            stalled.append(g.key)
            leave(g, "stalled: asked again and the answer changed nothing")
            draft.pending = [p for p in draft.pending if p.key != g.key]
        elif live and g.key not in draft.open:
            unresolved += 1
            leave(g, "answer did not settle it")
            draft.pending = [p for p in draft.pending if p.key != g.key]
    note()
    prune_open()
    final = finalize(draft.files)
    gaps_left = [x.key for x in gaps(draft)]
    errors = runnable(final)
    status = _status(gaps_left, sorted(draft.open), errors)
    missing = sorted(set(draft.open) | set(gaps_left) | set(errors))
    return {
        "questions": questions,
        "messages": messages,
        "unanswerable": unanswerable,
        "unresolved": unresolved,
        "stalled": stalled,
        "kept_earlier": list(draft.kept_earlier),
        "contradictions_asked": contradictions_asked,
        "deferrals": dict(draft.deferrals),
        "gaps_left": gaps_left,
        "files": final,
        "runnable": errors,
        "status": status,
        "missing": missing,
        "summary": "runnable" if status == "runnable" else "cannot run, missing " + "; ".join(missing),
        "open": dict(draft.open),
        "turns": turn,
        "deferred_refusals": sorted(refused),
        "model_errors": model_errors,
    }
