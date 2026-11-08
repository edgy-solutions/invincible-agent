"""An authorizer outage is 503 at every site, including the ones that already fail closed.

Architect ruling 2026-11-02, fork 22: "a malformed PDP answer is 503 at every site, including the
ones that already fail closed — same class as 16." Fork 16 (2026-10-31) gave the reason: "a 403
asserts policy said no". #190 made the reader strict; `MalformedPdpAnswer` is an
`httpx.DecodingError`, so each site's broad fail-closed handler read it as a no.

Fork 24, ruled yes the same day: a transport outage at those sites is 503 too. So is a non-2xx, with
one exception: a 404 from a DIRECTORY check stays a no, as `can_invoke_or_unavailable` and
`export_capability` already read it. An authorizer DECISION has no not-found form, so any non-2xx
there is an outage. The broad arm stays a deny for a defect, and an unset URL or an empty identity
stays a no. Read live against the sandbox's Topaz, an ungranted or unknown subject answers 200
`check: false`, so none of this turns an ordinary "no" into a 503. That is one Topaz version.

Two legs:
  1. the CLASS, found by form: every function that reads a PDP answer, and every caller of it,
     walked by first-matching handler. Nothing swallows the answer and nothing translates it to
     anything but a 503. Undecided forms fail, and the detector has its own positive controls;
  2. the sites, driven: a malformed answer, an unreachable Topaz and a non-2xx, each against a control
     that the same double can admit, and a real no that stays a no.

What "503" means differs by surface, and each surface is driven as what it is:
  - a route answers an HTTP 503;
  - a Restate engine fails terminally carrying 503. The double speaks the SDK's `ctx.run` as read
    from `restate/server_context.py`: a TerminalError is terminal, anything else is retried. That
    the ingress turns the code into an HTTP 503 is not measured here;
  - a tool inside a smolagents loop cannot raise out of it (`execute_tool_call` wraps the raise and
    the loop feeds it to the model), so engines W and E latch it and fail after the loop,
    discarding the model's answer. A retrieval failure in the same `try` is not latched.

Run:  uv run python -m pytest tests/security/test_a_malformed_pdp_answer_is_503_at_every_site.py -q
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import re
import subprocess
import sys
import types
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
_RA = REPO / "agent_fleet" / "restate_analyst"
# Not agent_fleet/ itself: with it on the path `utils` imports flat, and any file collected after this
# one gets a second origin_entitlement. Every engine here falls back to the repo layout.
for _p in (str(REPO / "src"), str(_RA), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.conftest import stub_modules  # noqa: E402

READERS = {"check_answer", "decision_answer"}
SCANNED = ("agent_fleet", "src")
READER_HOME = "agent_fleet/utils/pdp_answer.py"

# ── leg 1: the class, by form ──────────────────────────────────────────────────────────────────

DECODING = "DecodingError"
CONNECT = "ConnectError"
BAD_STATUS = "HTTPStatusError"
# One per way of being out, walked separately so that an arm catching only one of them cannot hide
# the other two.
OUTAGES = (DECODING, CONNECT, BAD_STATUS)
# What each class is caught by, beyond its own name. The httpx ladder is DecodingError < RequestError
# < HTTPError and ConnectError < TransportError < RequestError; HTTPStatusError < HTTPError alone.
# MalformedPdpAnswer is also a ValueError, and TransportError is a sibling of DecodingError.
_ALWAYS = {"Exception", "BaseException", "<bare>"}
_CAUGHT_BY = {DECODING: {DECODING, "MalformedPdpAnswer", "RequestError", "HTTPError", "ValueError"},
              CONNECT: {CONNECT, "TransportError", "RequestError", "HTTPError"},
              BAD_STATUS: {BAD_STATUS, "HTTPError"},
              "PromotionRefused": {"PromotionRefused", "RuntimeError"}}
# The classes a translation may land on. Anything else is undecided, and undecided fails.
TRANSLATIONS = {"HTTPException", "TerminalError", "StepFailAndRelease", "AuthorizationUnavailable",
                "PromotionRefused", "ProgramAuthorizationUnavailable", "_AuthorizerUnavailable"}
# The ones that carry a status, and must name it: an unnamed TerminalError is a 500. Where a positional
# status is the class's own signature, the position.
_CARRIES_STATUS = {"HTTPException": 0, "TerminalError": 1, "StepFailAndRelease": None, "PromotionRefused": None}
# What a handler may RETURN and still have answered: `_decide`'s refusal, safety's JSONResponse.
_RETURNED_ANSWERS = {"HTTPException": 0, "JSONResponse": None}
# A function that builds what a site raises, read by hand: name -> the class. `_picker_unavailable`
# hands back the HTTPException it was given, keeping its status.
FACTORIES = {"_picker_unavailable": "HTTPException"}
# The classes that ARE an answer when they leave the last function: a route's 503 and a terminal
# failure. Everything else leaving a route would be a 500, or a retry at a Restate handler.
# ProgramAuthorizationUnavailable is one too: safety's dispatch reaches its measures by `getattr`, which
# no walk can follow, so `test_the_safety_dispatch_answers_503` reads the arm instead.
ANSWERS = {"HTTPException", "TerminalError", "PromotionRefused", "ProgramAuthorizationUnavailable"}
# What runs a function it is handed, on the spot and inside the caller's try: a value given to one of
# these is a call. `ctx.run` also decides what a raise means: only a TerminalError is terminal, so any
# other class leaving it is retried rather than answered.
_RUNS_ITS_ARGUMENT = {"run_in_threadpool", "to_thread"}
_CTX_RUN = "ctx.run"
# These start another invocation: what it raises is that handler's own answer, walked from there, and
# handing it over is neither a call nor a value anybody here runs.
_INVOKES = {"workflow_send", "workflow_call", "service_send", "service_call", "object_send", "object_call"}
# A file named this says nothing by being imported: every engine has one.
_GENERIC_MODULES = {"main", "service"}


def _names(t) -> list[str]:
    if t is None:
        return ["<bare>"]
    if isinstance(t, ast.Tuple):
        return [n for e in t.elts for n in _names(e)]
    if isinstance(t, ast.Attribute):
        return [t.attr]
    if isinstance(t, ast.Name):
        return [t.id]
    return ["?"]


class _Fn:
    def __init__(self, path, qual, node=None):
        self.path, self.qual, self.node = path, qual, node
        self.leaf = qual.split(".")[-1]
        self.key = f"{path}::{qual}"


def _receiver(f) -> str | None:
    """What `x.fn` is called on, by name; None for a bare `fn`, "?" for an expression."""
    if not isinstance(f, ast.Attribute):
        return None
    return f.value.id if isinstance(f.value, ast.Name) else "?"


class _Walk(ast.NodeVisitor):
    """Every call and every name used as a value, with the tries lexically around it. A `def` starts
    a new function, because its body does not run where it is written; a lambda does not, because
    the sites here pass one straight to a threadpool, inside the same try."""

    def __init__(self, path):
        self.path, self.stack, self.tries, self.boundary = path, [], [], None
        self.calls, self.values, self.imports, self.fns = [], [], set(), {}
        self.stores: dict[str, set] = {}
        self.aliases: dict[str, str] = {}
        self.modules: dict[str, str] = {}  # a name this file imports a module as -> the module's basename
        self.methods: set[str] = set()
        self.tuples: dict[str, list] = {}  # a module-level `NAME = (ExcA, ExcB)`, for `except NAME:`

    def _here(self):
        return ".".join(self.stack) or "<module>"

    def _tuple(self, target, value):
        if not self.stack and isinstance(target, ast.Name) and isinstance(value, ast.Tuple):
            self.tuples[target.id] = _names(value)

    def visit_Assign(self, n):
        if len(n.targets) == 1:
            self._tuple(n.targets[0], n.value)
        self.generic_visit(n)

    def visit_AnnAssign(self, n):
        self._tuple(n.target, n.value)
        self.generic_visit(n)

    def visit_ClassDef(self, n):
        self.stack.append(n.name)
        for s in n.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.methods.add(f"{self._here()}.{s.name}")
        self.generic_visit(n)
        self.stack.pop()

    def _fn(self, n):
        self.stack.append(n.name)
        self.fns[self._here()] = n
        self.stores.setdefault(self._here(), set()).update(a.arg for a in ast.walk(n.args)
                                                           if isinstance(a, ast.arg))
        keep, self.tries, keep_b, self.boundary = self.tries, [], self.boundary, None
        self.generic_visit(n)
        self.tries, self.boundary = keep, keep_b
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _fn

    def visit_Import(self, n):
        for a in n.names:
            self.imports.update(a.name.split("."))
            self.modules[a.asname or a.name.split(".")[0]] = a.name.split(".")[-1]

    def visit_ImportFrom(self, n):
        self.imports.update((n.module or "").split("."))
        self.imports.update(a.name for a in n.names)
        self.aliases.update({a.asname: a.name for a in n.names if a.asname})
        # `from pkg import mod [as m]` may name a module; a receiver only counts if it is one.
        self.modules.update({a.asname or a.name: a.name for a in n.names})

    def visit_Try(self, n):
        self.tries.append(n)
        for b in n.body:
            self.visit(b)
        self.tries.pop()
        for part in n.handlers + n.orelse + n.finalbody:
            self.visit(part)

    def visit_Call(self, n):
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        name = self.aliases.get(name, name)
        if name:
            self.calls.append((name, self._here(), n.lineno, list(self.tries), self.boundary,
                               _receiver(f)))
        if isinstance(f, ast.Attribute):
            self.visit(f.value)
        elif not isinstance(f, ast.Name):
            self.visit(f)
        is_ctx_run = _receiver(f) == "ctx" and f.attr == "run"
        runner = _CTX_RUN if is_ctx_run else None
        parts = n.args + n.keywords
        if _receiver(f) == "ctx" and f.attr in _INVOKES:
            parts = n.args[1:] + n.keywords
        # The one function it runs: `ctx.run(name, action)` and `to_thread(fn, ...)`. A later argument
        # goes to that function, so it is a value like any other, which somebody has to follow.
        runs = n.args[1:2] if is_ctx_run else n.args[:1] if name in _RUNS_ITS_ARGUMENT else []
        runs = runs + [k.value for k in n.keywords if is_ctx_run and k.arg == "action"]
        for part in parts:
            arg = part.value if isinstance(part, ast.keyword) else part
            if arg in runs and isinstance(arg, (ast.Name, ast.Attribute)):
                handed = arg.attr if isinstance(arg, ast.Attribute) else arg.id
                self.calls.append((self.aliases.get(handed, handed), self._here(), arg.lineno,
                                   list(self.tries), runner, _receiver(arg)))
            keep, self.boundary = self.boundary, runner or self.boundary
            self.visit(part)
            self.boundary = keep

    def visit_Attribute(self, n):
        self.values.append((n.attr, self._here(), n.lineno, _receiver(n)))
        self.visit(n.value)

    def visit_Name(self, n):
        if isinstance(n.ctx, ast.Load):
            self.values.append((self.aliases.get(n.id, n.id), self._here(), n.lineno, None))
        else:
            self.stores.setdefault(self._here(), set()).add(n.id)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".py")


class Census:
    """`latched`, `answered_later`, `conditional` and `followed` are the hand-read tables; each row is
    a fact a person checked, each is asserted to still be there, and a form outside them fails."""

    def __init__(self, sources: dict[str, str], latched=(), conditional=(), followed=None,
                 answered_later=()):
        self.latched, self.conditional = set(latched), dict(conditional)
        self.answered_later = set(answered_later)
        self.followed = dict(followed or {})
        self.walks = {}
        for path, text in sources.items():
            w = _Walk(path)
            w.visit(ast.parse(text))
            self.walks[path] = w
        self.used_tables: set = set()

    def _related(self, caller_path: str, fn: _Fn) -> bool:
        if caller_path == fn.path:
            return True
        base = _basename(fn.path)
        imports = self.walks[caller_path].imports
        if base not in imports:
            return False
        parent = fn.path.rsplit("/", 2)[-2]
        return (base not in _GENERIC_MODULES or parent in imports
                or caller_path.rsplit("/", 1)[0] == fn.path.rsplit("/", 1)[0])

    def _is(self, w: _Walk, name: str, qual: str, receiver, fn: _Fn) -> bool:
        """Does this use of `name` in `w` mean `fn`? Bare: not if the name is local to the caller, and
        a nested def only from inside what encloses it. `mod.fn`: only if `mod` is fn's own module.
        `obj.fn`: only if fn is a method. Names repeat across this tree (`run`, `signal`, `visible`),
        so a walk by bare name alone reads `ctx.run` as a workflow's `run`."""
        if name != fn.leaf:
            return False
        home = self.walks.get(fn.path)
        if home is not None and fn.qual in home.methods:
            return receiver is not None
        if receiver is None:
            scopes = qual.split(".")
            if any(name in w.stores.get(".".join(scopes[:i + 1]), ()) for i in range(len(scopes))):
                return False
            parent = fn.qual.rpartition(".")[0]
            return not parent or (w.path == fn.path and (qual == parent or qual.startswith(parent + ".")))
        return w.modules.get(receiver) == _basename(fn.path)

    def roots(self) -> list[tuple[_Fn, list, int]]:
        out = []
        for path, w in self.walks.items():
            for name, qual, line, tries, _b, _r in w.calls:
                if name in READERS and qual != "<module>":
                    out.append((_Fn(path, qual, w.fns.get(qual)), tries, line))
        return out

    def _through(self, fn: _Fn, tries: list, cls: str, seen: set, bad: list, line: int):
        """The class that leaves `tries`, innermost first, with the first matching arm deciding."""
        for i in range(len(tries) - 1, -1, -1):
            tuples = self.walks[fn.path].tuples
            arm = next((h for h in tries[i].handlers
                        if {x for n in _names(h.type) for x in tuples.get(n, [n])}
                        & (_CAUGHT_BY.get(cls, {cls}) | _ALWAYS)), None)
            if arm is None:
                continue
            at = f"{fn.key}:{arm.lineno}"
            top = [s for s in arm.body if isinstance(s, ast.Raise)]
            returned = [s.value for s in arm.body if isinstance(s, ast.Return)
                        and isinstance(s.value, ast.Call) and _names(s.value.func)[0] in _RETURNED_ANSWERS]
            if not top and returned:
                for call in returned:
                    wrong = self._status_problem(call, _RETURNED_ANSWERS[_names(call.func)[0]], arm)
                    if wrong:
                        bad.append(f"{at}: `{cls}` is returned as {wrong}")
                return
            if not top:
                if any(isinstance(n, ast.Raise) for n in ast.walk(arm)):
                    if fn.key not in self.conditional:
                        bad.append(f"{at}: `{cls}` meets a conditional raise (undecided)")
                        return
                    self.used_tables.add(("conditional", fn.key))
                    first = arm.body[0]
                    if not (isinstance(first, ast.If) and ast.unparse(first.test) == self.conditional[fn.key]
                            and isinstance(first.body[0], ast.Raise) and first.body[0].exc is None):
                        bad.append(f"{at}: `{cls}` no longer meets `if {self.conditional[fn.key]}: raise`")
                        return
                    self._through(fn, tries[:i], cls, seen, bad, line)
                    return
                if fn.key in self.latched:
                    self.used_tables.add(("latched", fn.key))
                    return
                if fn.key in self.answered_later:
                    self.used_tables.add(("answered_later", fn.key))
                    return
                bad.append(f"{at}: `{cls}` is swallowed, so an outage reads as something else")
                return
            for raised in top:
                next_cls = self._raised(raised, arm, cls, at, bad)
                if next_cls:
                    self._through(fn, tries[:i], next_cls, seen, bad, line)
            return
        self._leaves(fn, cls, seen, bad)

    def _raised(self, raised: ast.Raise, arm, cls: str, at: str, bad: list):
        exc = raised.exc
        if exc is None or (isinstance(exc, ast.Name) and exc.id == arm.name):
            return cls
        if isinstance(exc, ast.Call):
            name = _names(exc.func)[0]
            if name in FACTORIES:
                return FACTORIES[name]
            if name not in TRANSLATIONS:
                bad.append(f"{at}: `{cls}` becomes `{name}`, which is undecided")
                return None
            if name in _CARRIES_STATUS:
                wrong = self._status_problem(exc, _CARRIES_STATUS[name], arm)
                if wrong:
                    bad.append(f"{at}: `{cls}` becomes `{name}` as {wrong}")
                    return None
            return name
        bad.append(f"{at}: `{cls}` is raised in a form this census cannot read")
        return None

    @staticmethod
    def _status_problem(call: ast.Call, position, arm) -> str | None:
        """None for a literal 503, or a status carried from the exception this arm caught (which
        is itself a translation the walk already asserted). Anything else is named."""
        kw = {k.arg: k.value for k in call.keywords}
        code = kw.get("status_code", kw.get("status"))
        if code is None and position is not None and len(call.args) > position:
            code = call.args[position]
        if code is None:
            return "no status"
        if isinstance(code, ast.Constant):
            return None if code.value == 503 else f"a {code.value}, not a 503"
        if (isinstance(code, ast.Attribute) and code.attr in {"status_code", "status"}
                and isinstance(code.value, ast.Name) and code.value.id == arm.name):
            return None
        return "a status this census cannot read"

    def _leaves(self, fn: _Fn, cls: str, seen: set, bad: list):
        if (fn.key, cls) in seen:
            return
        seen.add((fn.key, cls))
        reached = False
        for path, w in self.walks.items():
            if not self._related(path, fn):
                continue
            for name, qual, line, tries, boundary, receiver in w.calls:
                if (self._is(w, name, qual, receiver, fn) and qual != "<module>"
                        and f"{path}::{qual}" != fn.key):
                    reached = True
                    if boundary == _CTX_RUN and cls != "TerminalError":
                        bad.append(f"{path}:{line}: `{cls}` leaves ctx.run, which retries it")
                        continue
                    self._through(_Fn(path, qual, w.fns.get(qual)), tries, cls, seen, bad, line)
            called = {(q, ln) for n, q, ln, _t, _b, _r in w.calls if n == fn.leaf}
            for name, qual, line, receiver in w.values:
                if (not self._is(w, name, qual, receiver, fn) or (qual, line) in called
                        or qual == fn.qual):
                    continue
                row = self.followed.get((path, name))
                if row is None:
                    bad.append(f"{path}:{line}: `{name}` is passed as a value and nobody followed it")
                    continue
                self.used_tables.add(("followed", (path, name)))
                reached = True
                target_path, param, *within = row
                if param is None:  # hand-read: the value is the terminal step itself
                    if cls not in ANSWERS:
                        bad.append(f"{path}:{line}: `{cls}` leaves `{name}` as an unanswered {cls}")
                    continue
                for pname, pqual, pline, ptries, _b, _r in self.walks[target_path].calls:
                    if pname == param and (not within or pqual == within[0]):
                        self._through(_Fn(target_path, pqual, self.walks[target_path].fns.get(pqual)),
                                      ptries, cls, seen, bad, pline)
        if not reached and cls not in ANSWERS:
            bad.append(f"{fn.key}: `{cls}` leaves the last function unanswered (a 500, or a retry)")

    def problems(self, root: tuple[_Fn, list, int]) -> list[str]:
        fn, tries, line = root
        bad: list[str] = []
        for cls in OUTAGES:
            self._through(fn, tries, cls, set(), bad, line)
        return sorted(set(bad))


def _tracked() -> dict[str, str]:
    listed = subprocess.run(["git", "ls-files", "--", *SCANNED], cwd=REPO, capture_output=True,
                            text=True, check=True).stdout.splitlines()
    return {p: (REPO / p).read_text(encoding="utf-8") for p in listed
            if p.endswith(".py") and "baml_client" not in p}


# The tool's raise cannot leave the agent loop, so these three swallow by design and latch; the
# handler fails after the loop. Each is asserted below to append to the latch.
LATCHED = {
    "agent_fleet/weaviate_expert/service.py::query_knowledge.search_knowledge_base",
    "agent_fleet/weaviate_expert/service.py::query_knowledge.run_smolagent.search_knowledge_base_local",
    "agent_fleet/neo4j_expert/service.py::query_graph._may_read",
}
# The first two omit a rail's answer from the 409's listing of options, and the door answers 503 below:
# `cost_recipients is None` for cost's scopes, `_plan_may_export` unwrapped for plan's. A listing, never
# the decision, which is what `_plan_exportable_or_none`'s docstring says.
ANSWERED_LATER = {
    "src/iagent/gateway.py::_plan_exportable_or_none",
    "src/iagent/gateway.py::export_package",
    # A background tick, with nobody to answer: a non-403 leaves the row untouched for the next tick,
    # and only a 403 holds it. A malformed answer therefore moves nothing.
    "src/iagent/gateway.py::_apply_manifest_leaf_block",
}
# Each of these arms re-raises the case that matters and turns the rest into something else, so the
# row holds the guard a person read: any other raise in the arm would pass for this one.
CONDITIONAL = {
    # `except AuthorizationUnavailable` re-raises everything but the directory's not-found.
    "src/iagent/human_tasks.py::check_can_act":
        "not (isinstance(exc.__cause__, httpx.HTTPStatusError) and exc.__cause__.response.status_code == 404)",
    # `except HTTPException` re-raises everything but a 403, so a 503 passes.
    "src/iagent/gateway.py::ingest_export_route": "exc.status_code != 403",
}
# A name passed as a value, read by hand: (file, name) -> (file that calls it, the name it calls it
# by[, the one function it does so in]), or None where the value is the terminal step itself.
FOLLOWED = {
    ("src/iagent/gateway.py", "check_can_act"): ("src/iagent/promotion.py", "can_act"),
    ("src/iagent/gateway.py", "_export_recipients_for"): ("src/iagent/gateway.py", "recipients_fn"),
    ("src/iagent/gateway.py", "_fin_export_recipients_for"): ("src/iagent/gateway.py", "recipients_fn"),
    ("agent_fleet/restate_analyst/grouped_review_workflow.py", "check_can_act"):
        ("agent_fleet/restate_analyst/grouped_review_workflow.py", "_gate_helpers", "_check_can_act"),
    ("agent_fleet/ontology_service/main.py", "visible"):
        ("agent_fleet/ontology_service/input_declared.py", "visible"),
    ("agent_fleet/ontology_service/main.py", "_notice_parts_can_view_program"):
        ("agent_fleet/ontology_service/notice_parts.py", "can_view_program"),
}

SOURCES = _tracked()
CENSUS = Census(SOURCES, LATCHED, CONDITIONAL, FOLLOWED, ANSWERED_LATER)
ROOTS = {f"{r[0].key}:{r[2]}": r for r in CENSUS.roots() if r[0].path != READER_HOME}


def test_the_parse_saw_every_read_of_an_answer():
    """Parsed against text: a read in a form the walker does not see would leave a site unwalked."""
    text = sum(len(re.findall(r"\b(?:check_answer|decision_answer)\(", t))
               for p, t in SOURCES.items() if p != READER_HOME)
    assert text == len(ROOTS), "a reader call the parse did not see, or a mention in a comment"
    assert {r[0].path for r in ROOTS.values()} >= {"src/iagent/human_tasks.py",
                                                   "agent_fleet/datahub_wrapper/main.py"}


@pytest.mark.parametrize("root", sorted(ROOTS))
def test_no_reader_or_caller_reads_a_malformed_answer_as_anything_but_503(root):
    assert CENSUS.problems(ROOTS[root]) == []


def test_every_hand_read_row_is_still_there():
    """A table row whose code moved has stopped proving anything, so it fails rather than decays."""
    for root in ROOTS.values():
        CENSUS.problems(root)
    want = ({("latched", k) for k in LATCHED} | {("conditional", k) for k in CONDITIONAL}
            | {("answered_later", k) for k in ANSWERED_LATER} | {("followed", k) for k in FOLLOWED})
    assert want - CENSUS.used_tables == set()


@pytest.mark.parametrize("key", sorted(LATCHED))
def test_a_latched_row_appends_to_the_latch(key):
    path, qual = key.split("::")
    fn = CENSUS.walks[path].fns[qual]
    arms = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers
            if {"HTTPError", "_AuthorizerUnavailable"} & set(_names(h.type))]
    assert arms, f"{key} has no arm for an outage"
    assert "pdp_unavailable.append" in ast.unparse(arms[0]), f"{key} swallows without latching"


@pytest.mark.parametrize("path", sorted({k.split("::")[0] for k in LATCHED}))
def test_a_latching_engine_fails_after_the_loop(path):
    """The latch is only worth what reads it: `if pdp_unavailable: raise TerminalError(... 503)`.
    The one other reading allowed is the exact short-circuit that stops asking once the run is lost,
    which can only withhold; anything else reading the latch is red."""
    tree = ast.parse(SOURCES[path])
    tests = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.If)
             and isinstance(n.test, ast.Name) and n.test.id == "pdp_unavailable"]
    assert tests, f"{path} latches and never reads the latch"
    terminal = [t for t in tests if "TerminalError" in t and "status_code=503" in t]
    assert terminal, f"{path} reads the latch and never fails the run"
    assert [t for t in tests if t not in terminal and t != "if pdp_unavailable:\n    return False"] == []


def test_the_safety_dispatch_answers_503():
    """Safety reaches its measures by `getattr`, so the walk stops at the class; the arm is read here."""
    tree = ast.parse(SOURCES["agent_fleet/safety_agent/main.py"])
    arms = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)
            if "ProgramAuthorizationUnavailable" in _names(n.type)]
    assert arms, "nothing answers ProgramAuthorizationUnavailable"
    for arm in arms:
        assert "JSONResponse(status_code=503" in ast.unparse(arm)


def _synthetic(body: str, **tables):
    return Census({"pkg/site.py": body}, **tables)


_DEFECTS = {
    "a swallow": ("""
def gate():
    try:
        return check_answer(r)
    except Exception:
        return False
""", "swallowed"),
    "an arm after the broad one": ("""
def gate():
    try:
        return check_answer(r)
    except Exception:
        return False
    except httpx.DecodingError:
        raise HTTPException(status_code=503)
""", "swallowed"),
    "a non-503 translation": ("""
def gate():
    try:
        return check_answer(r)
    except httpx.DecodingError:
        raise HTTPException(status_code=403)
""", "not a 503"),
    "an unknown translation": ("""
def gate():
    try:
        return check_answer(r)
    except httpx.DecodingError:
        raise Boom("x")
""", "undecided"),
    "a conditional raise nobody read": ("""
def gate():
    try:
        return check_answer(r)
    except httpx.DecodingError as e:
        if e.request:
            raise
        return False
""", "conditional"),
    "a caller that swallows": ("""
def gate():
    return check_answer(r)

def route():
    try:
        return gate()
    except httpx.HTTPError:
        return None
""", "swallowed"),
    "a value nobody followed": ("""
def gate():
    return check_answer(r)

def route():
    return run(can_act=gate)
""", "nobody followed"),
    "a route with no arm": ("""
def gate():
    return check_answer(r)

def route():
    return gate()
""", "unanswered"),
    "a raise that leaves ctx.run": ("""
def gate():
    return check_answer(r)

async def handler(ctx):
    return await ctx.run("gate", gate)
""", "retries"),
    "a raise that leaves a lambda in ctx.run": ("""
def gate():
    return check_answer(r)

async def handler(ctx):
    return await ctx.run("gate", lambda: gate())
""", "retries"),
    "a threadpool run whose try swallows it": ("""
def gate():
    return check_answer(r)

async def route():
    try:
        return await run_in_threadpool(gate)
    except httpx.DecodingError:
        return None
""", "swallowed"),
    "a returned refusal that is not a 503": ("""
def gate():
    try:
        return check_answer(r)
    except httpx.DecodingError:
        return HTTPException(status_code=403)
""", "not a 503"),
    "a positional 403": ("""
def gate():
    try:
        return check_answer(r)
    except httpx.DecodingError:
        raise HTTPException(403, "no")
""", "not a 503"),
    "a terminal failure with no status": ("""
def gate():
    try:
        return check_answer(r)
    except httpx.DecodingError:
        raise TerminalError("x")
""", "no status"),
    "a status nobody can read": ("""
def gate():
    try:
        return check_answer(r)
    except httpx.DecodingError:
        raise HTTPException(status_code=pick())
""", "cannot read"),
    "an arm for a malformed answer alone, so an outage is a no": ("""
def gate():
    try:
        return check_answer(r)
    except httpx.DecodingError as e:
        raise HTTPException(status_code=503) from e
    except Exception:
        return False
""", "`ConnectError` is swallowed"),
    "an arm for a transport failure alone, so a 5xx is a no": ("""
def gate():
    try:
        return check_answer(r)
    except (httpx.RequestError) as e:
        raise HTTPException(status_code=503) from e
    except Exception:
        return False
""", "`HTTPStatusError` is swallowed"),
    "an arm for a status alone, so an unreachable Topaz is a no": ("""
def gate():
    try:
        return check_answer(r)
    except (httpx.HTTPStatusError, httpx.DecodingError) as e:
        raise HTTPException(status_code=503) from e
    except Exception:
        return False
""", "`ConnectError` is swallowed"),
    "an imported alias whose caller swallows": ("""
from pkg.other import gate as _g

def gate():
    return check_answer(r)

def route():
    try:
        return _g()
    except Exception:
        return None
""", "swallowed"),
}
_CLEAN = {
    "a terminal failure translated inside ctx.run": """
def gate():
    try:
        return check_answer(r)
    except httpx.HTTPError as e:
        raise TerminalError("x", status_code=503) from e

async def handler(ctx):
    return await ctx.run("gate", gate)
""",
    "a threadpool run whose arm answers": """
def gate():
    return check_answer(r)

async def route():
    try:
        return await run_in_threadpool(gate)
    except httpx.HTTPError:
        raise HTTPException(status_code=503)
""",
    "a door that returns its 503": """
def gate():
    try:
        return check_answer(r)
    except httpx.HTTPError:
        return HTTPException(status_code=503)
""",
    "a positional 503": """
def gate():
    try:
        return check_answer(r)
    except httpx.HTTPError:
        raise HTTPException(503, "no")
""",
    "a local that shares a walked name": """
def gate():
    try:
        return check_answer(r)
    except httpx.HTTPError:
        raise HTTPException(status_code=503)

def other():
    gate = 1
    return gate
""",
    "a translated answer": """
def gate():
    try:
        return check_answer(r)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503) from e
    except Exception:
        return False
""",
    "an arm ahead of a caller's broad one": """
def gate():
    return check_answer(r)

def route():
    try:
        return gate()
    except httpx.HTTPError as e:
        raise TerminalError("x", status_code=503) from e
    except Exception:
        return None
""",
    "a sibling arm that cannot catch it": """
def gate():
    try:
        return check_answer(r)
    except KeyError:
        return False
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503) from e
""",
}


@pytest.mark.parametrize("name", sorted(_DEFECTS))
def test_the_detector_sees_each_defect(name):
    src, word = _DEFECTS[name]
    c = _synthetic(src)
    found = [p for r in c.roots() for p in c.problems(r)]
    assert any(word in p for p in found), found


@pytest.mark.parametrize("guard, word", [("e.request", None), ("not e.request", "no longer meets")])
def test_a_conditional_row_holds_the_guard_a_person_read(guard, word):
    src = f"""
def gate():
    try:
        return check_answer(r)
    except httpx.HTTPError as e:
        if {guard}:
            raise
        return False

def door():
    try:
        return gate()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503) from e
"""
    c = Census({"x.py": src}, conditional={"x.py::gate": "e.request"})
    found = [p for r in c.roots() for p in c.problems(r)]
    assert any(word in p for p in found) if word else found == [], found


@pytest.mark.parametrize("name", sorted(_CLEAN))
def test_the_detector_passes_a_clean_site(name):
    c = _synthetic(_CLEAN[name])
    assert [p for r in c.roots() for p in c.problems(r)] == []


# ── leg 2: the sites, driven ───────────────────────────────────────────────────────────────────

URL = "http://topaz.test"
CHECK_MALFORMED = [{"check": "false"}, {"check": "0"}, {"check": None}, {"check": 1}, [], b"<html>"]
DECISION_MALFORMED = [{"decisions": [{"decision": "allowed", "is": "false"}]},
                      {"decisions": "allowed"}, {"decisions": [1]}, [], b"<html>"]


class _Outage:
    def __repr__(self):
        return "unreachable"


class _Status:
    def __init__(self, code: int):
        self.code = code

    def __repr__(self):
        return f"HTTP {self.code}"


OUTAGE = _Outage()
# Not an answer, by any client: what the sites read as an outage, on either form.
UNANSWERED = [OUTAGE, _Status(500), _Status(503), _Status(401)]
ADMIT = {"check": {"check": True},
         "decision": {"decisions": [{"decision": "allowed", "is": True}]}}
DENY = {"check": {"check": False},
        "decision": {"decisions": [{"decision": "allowed", "is": False}]}}


@pytest.fixture
def pdp(monkeypatch):
    """One answer behind every client a site uses, so a control and its case share a double. It sits
    under httpx's own client, at the transport, so `httpx.post`, `httpx.Client` and `AsyncClient` all
    run for real, and `TestClient`, which brings its own transport, is untouched."""
    state = {"body": None, "asks": 0}

    def _answer(request):
        state["asks"] += 1
        if state["body"] is OUTAGE:
            raise httpx.ConnectError("down", request=request)
        body = state["body"]
        if isinstance(body, _Status):
            return httpx.Response(body.code, json={"message": "x"}, request=request)
        if isinstance(body, bytes):
            return httpx.Response(200, content=body, request=request)
        return httpx.Response(200, json=body, request=request)

    async def _async_answer(request):
        return _answer(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: _answer(request))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request",
                        lambda _self, request: _async_answer(request))
    return state


def _status(exc) -> int | None:
    return getattr(exc, "status_code", getattr(exc, "status", None))


def _docs(mp):
    from agent_fleet.docs_agent import entitlement
    mp.setattr(entitlement, "TOPAZ_DIRECTORY_URL", URL)
    return lambda: entitlement.can_invoke("a@x", "cap")


def _datahub(mp):
    from agent_fleet.datahub_wrapper import main as dh
    mp.setattr(dh, "TOPAZ_AUTHORIZER_URL", URL)
    return lambda: asyncio.run(dh._topaz_can_view("a@x", "DOMAIN"))


def _ontology():
    return pytest.importorskip("agent_fleet.ontology_service.main",
                               reason="the ontology service's imports are not installed here")


def _ontology_view(mp):
    eo = _ontology()
    mp.setattr(eo, "ENABLE_AGENTIC_AUTH", True)
    mp.setattr(eo, "TOPAZ_AUTHORIZER_URL", URL)
    return lambda: eo._can_view_class("a@x", "urn:x")


def _ontology_invoke(mp):
    eo = _ontology()
    mp.setattr(eo, "ENABLE_AGENTIC_AUTH", True)
    mp.setattr(eo, "TOPAZ_DIRECTORY_URL", URL)
    return lambda: eo._can_invoke_capability("a@x", "cap")


def _review_starter(mp):
    from agent_fleet.restate_analyst import review_starter as rs
    mp.setattr(rs, "ENABLE_DISPOSITION_AUTHZ", True)
    mp.setattr(rs, "TOPAZ_DIRECTORY_URL", URL)
    return lambda: rs.can_invoke_start_review("a@x")


def _spo():
    pytest.importorskip("restate")
    import spo_step_executor as spo
    return spo


def _spo_urls(mp, spo):
    mp.setitem(spo.check_can_act.__kwdefaults__, "topaz_url", URL)
    mp.setitem(spo.check_can_invoke.__kwdefaults__, "topaz_url", URL)


def _spo_invoke(mp):
    spo = _spo()
    _spo_urls(mp, spo)
    return lambda: spo.check_can_invoke("cap", "a@x")


def _spo_act(mp):
    spo = _spo()
    _spo_urls(mp, spo)
    return lambda: spo.check_can_act("aud", "a@x")


def _main_act(mp):
    _spo_urls(mp, _spo())
    import main
    return lambda: main._check_can_act("aud", "a@x")


def _grouped_act(mp):
    _spo_urls(mp, _spo())
    import grouped_review_workflow as grouped
    return lambda: grouped._check_can_act("aud", "a@x")


def _human_tasks(mp):
    from src.iagent import human_tasks
    mp.setattr(human_tasks, "_TOPAZ_DIRECTORY_URL", URL)
    return human_tasks


def _ht_act(mp):
    ht = _human_tasks(mp)
    return lambda: ht.check_can_act("aud", "a@x")


def _ht_invoke(mp):
    ht = _human_tasks(mp)
    return lambda: ht.check_can_invoke("cap", "a@x")


def _promotion(mp):
    from src.iagent import promotion
    ht = _human_tasks(mp)
    return lambda: promotion._may_act(ht.check_can_act, "aud", "a@x")


def _is_http_503(exc):
    from fastapi import HTTPException
    return isinstance(exc, HTTPException) and exc.status_code == 503


def _is_terminal_503(exc):
    import restate
    return isinstance(exc, restate.TerminalError) and exc.status_code == 503


def _is_step_503(exc):
    return isinstance(exc, _spo().StepFailAndRelease) and exc.status_code == 503


def _is_http_error(exc):
    return isinstance(exc, httpx.HTTPError)


def _is_unavailable(exc):
    from iagent.authz import AuthorizationUnavailable
    return isinstance(exc, AuthorizationUnavailable)


def _is_refused_503(exc):
    from src.iagent.promotion import PromotionRefused
    return isinstance(exc, PromotionRefused) and exc.status == 503


# name: (answer form, the site, what an outage must raise there)
SITES = {
    "docs.can_invoke": ("check", _docs, _is_http_503),
    "datahub._topaz_can_view": ("decision", _datahub, _is_http_503),
    "ontology._can_view_class": ("decision", _ontology_view, _is_http_503),
    "ontology._can_invoke_capability": ("check", _ontology_invoke, _is_http_503),
    "review_starter.can_invoke_start_review": ("check", _review_starter, _is_terminal_503),
    "spo.check_can_invoke": ("check", _spo_invoke, _is_step_503),
    "spo.check_can_act": ("check", _spo_act, _is_http_error),
    "main._check_can_act": ("check", _main_act, _is_terminal_503),
    "grouped._check_can_act": ("check", _grouped_act, _is_terminal_503),
    "human_tasks.check_can_act": ("check", _ht_act, _is_unavailable),
    "human_tasks.check_can_invoke": ("check", _ht_invoke, _is_unavailable),
    "promotion._may_act": ("check", _promotion, _is_refused_503),
}
_CASES = [(s, b) for s, (form, *_r) in SITES.items()
          for b in (CHECK_MALFORMED if form == "check" else DECISION_MALFORMED)]


@pytest.mark.parametrize("site, body", _CASES, ids=[f"{s}-{b!r}" for s, b in _CASES])
def test_a_malformed_answer_is_the_outage_class_here(pdp, monkeypatch, site, body):
    form, make, is_expected = SITES[site]
    call = make(monkeypatch)
    pdp["body"] = ADMIT[form]
    assert call() is True, "control: the same double admits"
    pdp["body"] = body
    with pytest.raises(BaseException) as raised:
        call()
    assert is_expected(raised.value), repr(raised.value)


@pytest.mark.parametrize("site", sorted(SITES))
def test_a_real_no_is_still_a_no_here(pdp, monkeypatch, site):
    form, make, _ = SITES[site]
    call = make(monkeypatch)
    pdp["body"] = DENY[form]
    assert call() is False


_OUTAGE_CASES = [(s, b) for s in SITES for b in UNANSWERED]


@pytest.mark.parametrize("site, body", _OUTAGE_CASES, ids=[f"{s}-{b!r}" for s, b in _OUTAGE_CASES])
def test_an_outage_is_the_outage_class_here(pdp, monkeypatch, site, body):
    """Ruled yes: a 403 asserts policy said no, and policy said nothing."""
    form, make, is_expected = SITES[site]
    call = make(monkeypatch)
    pdp["body"] = ADMIT[form]
    assert call() is True, "control: the same double admits"
    pdp["body"] = body
    with pytest.raises(BaseException) as raised:
        call()
    assert is_expected(raised.value), repr(raised.value)


@pytest.mark.parametrize("site", sorted(s for s, (form, *_r) in SITES.items() if form == "check"))
def test_a_directory_not_found_is_still_a_no_here(pdp, monkeypatch, site):
    """The reading `can_invoke_or_unavailable` and `export_capability` already have. The sandbox's
    Topaz answers an absent object as 200 `check: false`, so this is parity and a guard for another
    version, and a misrouted proxy's 404 reads as a no too. That choice is the PR's to state."""
    _form, make, _ = SITES[site]
    call = make(monkeypatch)
    pdp["body"] = _Status(404)
    assert call() is False


@pytest.mark.parametrize("code", [404, 400], ids=repr)
@pytest.mark.parametrize("site", sorted(s for s, (form, *_r) in SITES.items() if form == "decision"))
def test_a_decision_has_no_not_found(pdp, monkeypatch, site, code):
    """A policy path the authorizer does not know answers 400 when read live: misconfiguration, not
    a no. A decision's "no" is a 200."""
    _form, make, is_expected = SITES[site]
    call = make(monkeypatch)
    pdp["body"] = _Status(code)
    with pytest.raises(BaseException) as raised:
        call()
    assert is_expected(raised.value), repr(raised.value)


# ── the routes ─────────────────────────────────────────────────────────────────────────────────

class _User:
    def __init__(self, authz_id):
        self.authz_id = self.sub = self.email = authz_id
        self.persona = "TEST"
        self.entitled_domains: list = []
        self.is_authenticated = True


class _FakeRestate:
    """Stands in for `httpx.AsyncClient` at the Restate ingress, past the gate."""

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        return types.SimpleNamespace(status_code=200, json=lambda: {})


@pytest.fixture
def client(pdp, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from src.iagent import gateway, human_tasks

    monkeypatch.setattr(human_tasks, "_TOPAZ_DIRECTORY_URL", URL)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User("a@x")
    with TestClient(gateway.app) as c:
        yield c, gateway, human_tasks, pdp
    gateway.app.dependency_overrides.clear()


def _act(c):
    return c.post("/human_tasks/t-1/act", json={"decision": "approved", "comment": ""})


@pytest.fixture
def act_world(client, monkeypatch):
    c, gateway, ht, state = client
    row = {"task_id": "t-1", "kind": "seal_kind", "audience": "seal:ORG", "workflow_id": "wf-1",
           "workflow_service": "BPMNWorkflowRunner", "promise_name": "approval_wf-1", "payload": {}}
    monkeypatch.setattr(ht, "_SEED_ROWS_CACHE", None, raising=False)
    monkeypatch.setattr(ht, "validate_decision", lambda *a, **k: None)
    monkeypatch.setattr(ht, "mark_task_resolved", lambda tid, **k: 1)
    monkeypatch.setattr(ht, "get_task_resolution", lambda tid, *, caller_id: None)
    monkeypatch.setattr(ht, "list_tasks_for", lambda caller, *, status="pending": [row])
    monkeypatch.setattr(httpx, "AsyncClient", _FakeRestate())
    return c, state


def test_the_act_route(act_world):
    c, state = act_world
    state["body"] = ADMIT["check"]
    assert _act(c).status_code == 200, "control: the same double admits"
    state["body"] = DENY["check"]
    assert _act(c).status_code == 403
    state["body"] = _Status(404)
    assert _act(c).status_code == 403, "the directory's not-found is a no"


@pytest.mark.parametrize("body", [*CHECK_MALFORMED, *UNANSWERED], ids=repr)
def test_the_act_route_answers_503_on_an_outage(act_world, body):
    c, state = act_world
    state["body"] = body
    r = _act(c)
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "authorization_unavailable"


TRIAGE = {"subject_ref": "s3://x", "title": "t", "summary": "s"}


@pytest.mark.parametrize("body", [*CHECK_MALFORMED, *UNANSWERED], ids=repr)
def test_the_triage_route_answers_503_on_an_outage(client, monkeypatch, body):
    c, _gateway, ht, state = client
    monkeypatch.setattr(ht, "task_exists", lambda tid: True)
    state["body"] = ADMIT["check"]
    assert c.post("/triage_tasks", json=TRIAGE).status_code == 200, "control: the same double admits"
    state["body"] = DENY["check"]
    assert c.post("/triage_tasks", json=TRIAGE).status_code == 403
    state["body"] = body
    r = c.post("/triage_tasks", json=TRIAGE)
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "authorization_unavailable"


ORIGIN = {"artifact_id": "a-1", "dropped_by": {"authz_id": "d@x"}, "origin": {"program": "p"},
          "evidence": {}, "approval_chain": [{"role": "steward", "approver_sub": "s@x"}],
          "case_id": "C-1"}


@pytest.fixture
def origin_world(client, monkeypatch):
    c, gateway, _ht, state = client
    import agent_fleet.utils.mesh_writers.neo4j_graph as ng

    def _no_store(**_k):
        raise RuntimeError("past the membership check")

    monkeypatch.setattr(gateway, "_CASE_RUNNER_SERVICE_AUTHZ_ID", "a@x")
    # the route admits the named steward on the case; the real holder lookup is Postgres
    monkeypatch.setattr("src.iagent.human_tasks.holds_task_on_case", lambda case_id, who: True)
    monkeypatch.setattr(ng, "Neo4jGraphWriter", _no_store)
    return c, state


@pytest.mark.parametrize("body", CHECK_MALFORMED, ids=repr)
def test_the_origin_route_answers_503_on_a_malformed_answer(origin_world, body):
    c, state = origin_world
    state["body"] = ADMIT["check"]
    control = c.post("/internal/origin/write", json=ORIGIN)
    assert control.status_code == 200 and control.json()["status"] == "write_refused", control.text
    state["body"] = body
    r = c.post("/internal/origin/write", json=ORIGIN)
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "authorization_unavailable"


def test_the_origin_route_answers_503_on_an_outage(origin_world):
    """This route had no arm, so an outage was a 500; `check_can_view_program`'s own docstring says
    the route tells "unreachable" (503) from "not a member"."""
    c, state = origin_world
    state["body"] = OUTAGE
    r = c.post("/internal/origin/write", json=ORIGIN)
    assert r.status_code == 503, r.text


# ── a Restate step: ctx.run decides what a raise means ─────────────────────────────────────────

class _Retried(BaseException):
    """What the SDK's `ctx.run` does with anything but a TerminalError: it retries."""


class _Past(BaseException):
    """The step this test was driving has finished; stop the handler here."""


class _SdkCtx:
    """`ctx.run` as `restate/server_context.py` writes it: a TerminalError is journaled terminal,
    any other Exception is proposed as transient and retried. Both markers are BaseExceptions so
    that no handler in the code under test can absorb what the SDK would have done."""

    def __init__(self, stop_at):
        self.stop_at, self.results, self.state = stop_at, {}, {}

    def key(self):
        return "seal-key"

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn, **_k):
        import restate

        if name.startswith(self.stop_at):
            if self.stop_at != "gate_":
                raise _Past
        try:
            out = fn()
            if inspect.isawaitable(out):
                out = await out
        except restate.TerminalError:
            raise
        except Exception as exc:
            raise _Retried(repr(exc)) from exc
        self.results[name] = out
        if name.startswith(self.stop_at):
            raise _Past
        return out


def _fanout_definition():
    return {
        "id": "seal_fanout", "name": "seal", "classification": None,
        "participants": [{"role": "initiator"}], "domain_stages": ["open", "closed"],
        "steps": [{"kind": "dispatch_fanout", "id": "dispatch_seal", "capability": "mesh:seal"}],
        "observable_state": {"visible": ["domain_stages"], "internal": []},
    }


def _drive_gate(monkeypatch):
    _spo_urls(monkeypatch, _spo())
    import main
    ctx = _SdkCtx("gate_")
    asyncio.run(main._run_definition(ctx, "wf-seal", _fanout_definition(),
                                     {"subject": "S-1", "authz_id": "a@x"}))
    return ctx


def test_the_autonomous_gate_grants(pdp, monkeypatch):
    pdp["body"] = ADMIT["check"]
    with pytest.raises(_Past):
        _drive_gate(monkeypatch)


def test_the_autonomous_gate_denies_terminally(pdp, monkeypatch):
    """A deny used to be raised inside `ctx.run` and caught outside it, so the SDK retried it. The
    comment beside it always said terminal; the translation now sits inside the action."""
    import restate
    pdp["body"] = DENY["check"]
    with pytest.raises(restate.TerminalError) as raised:
        _drive_gate(monkeypatch)
    assert raised.value.status_code == 403


@pytest.mark.parametrize("body", [*CHECK_MALFORMED, *UNANSWERED], ids=repr)
def test_the_autonomous_gate_fails_terminally_with_503(pdp, monkeypatch, body):
    import restate
    pdp["body"] = body
    with pytest.raises(restate.TerminalError) as raised:
        _drive_gate(monkeypatch)
    assert raised.value.status_code == 503


# ── the tool-loop engines: the answer is discarded ─────────────────────────────────────────────

def _stubbed():
    """`baml_client` is generated and not importable from a checkout. Stubbed for the import ONLY,
    and restored, so no later file in the session sees the stub."""
    stub = types.ModuleType("baml_client")
    stub.b = types.SimpleNamespace(with_options=lambda **_k: None)
    return stub_modules({"baml_client": stub})


def _agent_double(calls: dict, seen: list):
    """smolagents' loop as `agents.py` writes it: a tool's raise is fed back to the model and the
    run still ends with an answer, which is why W and E must latch."""

    class _Agent:
        memory = types.SimpleNamespace(steps=[])

        def __init__(self, tools, **_k):
            self.tools = {t.name: t for t in tools}

        def run(self, _prompt):
            for name, kwargs in calls.items():
                try:
                    seen.append(self.tools[name](**kwargs))
                except Exception as exc:  # noqa: BLE001 -- what the loop does
                    seen.append(f"TOOL ERROR {exc!r}")
            return "THE MODEL'S ANSWER"

    return _Agent


def _engine_w(monkeypatch, seen, search=None):
    with _stubbed():
        import agent_fleet.weaviate_expert.service as w
    hit = types.SimpleNamespace(uuid="u-1", metadata=types.SimpleNamespace(score=1.0, distance=None),
                                properties={"source_url": "doc-1", "text": "SECRET", "doc_id": "d"})
    monkeypatch.setattr(w, "ENABLE_AGENTIC_AUTH", True)
    monkeypatch.setattr(w, "TOPAZ_DIRECTORY_URL", URL)
    monkeypatch.setattr(w, "KNOWLEDGE_SEARCH_VIA_MESH", False)
    monkeypatch.setattr(w, "_search_direct", search or (lambda *a, **k: [hit]))
    monkeypatch.setattr(w, "get_weaviate_client", lambda: object())
    monkeypatch.setattr(w, "fetch_weaviate_schema", lambda *a: "schema")
    monkeypatch.setattr(w, "get_smolagent_model", lambda *a, **k: object())
    monkeypatch.setattr(w, "ToolCallingAgent", _agent_double(
        {"search_knowledge_base_local": {"semantic_query": "q"}}, seen))
    ctx = _SdkCtx("format-baml")
    asyncio.run(w.query_knowledge(ctx, {"user_query": "q", "domain": "X", "user_email": "a@x"}))
    return ctx


def _engine_e(monkeypatch, seen, uris=("u-1",)):
    pytest.importorskip("baml_py")
    with _stubbed():
        import agent_fleet.neo4j_expert.service as e

    async def _mem0():
        return object()

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def execute_read(self, _fn):
            return [{"props": {"text": "SECRET"}}]

    monkeypatch.setattr(e, "ENABLE_AGENTIC_AUTH", True)
    monkeypatch.setattr(e, "TOPAZ_DIRECTORY_URL", URL)
    monkeypatch.setattr(e, "fetch_dynamic_schema_from_neo4j", lambda: "schema")
    monkeypatch.setattr(e, "get_weaviate_client", lambda: object())
    monkeypatch.setattr(e, "get_mem0_memory", _mem0)
    monkeypatch.setattr(e, "fetch_weaviate_schema", lambda *a: "schema")
    monkeypatch.setattr(e, "get_neo4j_driver",
                        lambda: types.SimpleNamespace(session=lambda: _Session()))
    monkeypatch.setattr(e, "get_smolagent_model", lambda *a, **k: object())
    monkeypatch.setattr(e, "ToolCallingAgent", _agent_double({"fetch_content": {"uris": list(uris)}}, seen))
    monkeypatch.setattr(e, "emit_boundary", lambda *a, **k: None)
    ctx = _SdkCtx("emit-engine-e-boundary")
    asyncio.run(e.query_graph(ctx, {"user_query": "q", "domain": "X", "user_email": "a@x"}))
    return ctx


ENGINES = {"W": _engine_w, "E": _engine_e}


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_a_tool_loop_engine_reaches_the_model_on_a_grant(pdp, monkeypatch, engine):
    seen: list = []
    pdp["body"] = ADMIT["check"]
    with pytest.raises(_Past):
        ENGINES[engine](monkeypatch, seen)
    assert "SECRET" in str(seen), "control: the same double lets the chunk through"


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_a_tool_loop_engine_drops_the_chunk_on_a_no(pdp, monkeypatch, engine):
    seen: list = []
    pdp["body"] = DENY["check"]
    with pytest.raises(_Past):
        ENGINES[engine](monkeypatch, seen)
    assert "SECRET" not in str(seen)


@pytest.mark.parametrize("body", [*CHECK_MALFORMED, *UNANSWERED], ids=repr)
@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_a_tool_loop_engine_discards_the_answer_on_an_outage(pdp, monkeypatch, engine, body):
    import restate
    seen: list = []
    pdp["body"] = body
    with pytest.raises(restate.TerminalError) as raised:
        ENGINES[engine](monkeypatch, seen)
    assert raised.value.status_code == 503
    assert "SECRET" not in str(seen)


def test_engine_w_does_not_blame_the_authorizer_for_retrieval(pdp, monkeypatch):
    """W's tool `try` also encloses retrieval, so its arm catches the gate's own class. A retrieval
    `httpx.ConnectError` stays what it was, the tool's error text, and fails no run."""
    def _down(*_a, **_k):
        raise httpx.ConnectError("the store is down")

    seen: list = []
    pdp["body"] = ADMIT["check"]
    with pytest.raises(_Past):
        _engine_w(monkeypatch, seen, search=_down)
    assert "Error executing semantic search" in str(seen), seen
    assert pdp["asks"] == 0, "control: the authorizer was never reached"


def test_engine_e_stops_asking_once_the_run_is_lost(pdp, monkeypatch):
    """Latched, the run fails whatever the rest answer, so no later chunk waits out a timeout."""
    import restate
    seen: list = []
    pdp["body"] = OUTAGE
    with pytest.raises(restate.TerminalError):
        _engine_e(monkeypatch, seen, uris=("u-1", "u-2", "u-3"))
    assert pdp["asks"] == 1
