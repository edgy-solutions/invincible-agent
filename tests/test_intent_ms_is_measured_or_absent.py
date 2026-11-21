"""`intent_ms` is the `/route_intent` call's own time, or it is nothing (2026-11-20).

RULING (architect via Chris, 11-20): "intent_ms comes from 74 as a new field. The footer stays
dormant until then." The field rides the answer artifact through to `answer_artifact_projection`.

MEANS: the wall time of the one `/route_intent` POST for THIS artifact's turn, taken with
`time.monotonic()` immediately before the POST and immediately after `resp.json()`. ABSENT
(None / NULL) when the turn ran no such call: an interview turn, or `_pre_resolved` (a pick
after an ask card). 0 is a legal measurement and is not absence.

`duration_ms` is UNCHANGED and is NOT increased by this: its operands are pinned by
`test_duration_ms_is_measured_or_absent.py`; a reader who wants both adds them.

SCOPE. IN: the model default, the clock's bracket around the POST, the single bundle key,
the None-only paths, the writer, the projector, both SQL files, the read-back. OUT: that a live
run yields a plausible number.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib
import sys
from unittest.mock import MagicMock

_REPO = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GATEWAY = _REPO / "src" / "iagent" / "gateway.py"
_WRITER = _REPO / "src" / "iagent" / "answer_artifact_writer.py"
_PROJECTOR = _REPO / "src" / "iagent" / "projector" / "apply_loop.py"
_READS = _REPO / "src" / "iagent" / "artifact_reads.py"
_SQL = _REPO / "sql" / "create_answer_artifact_projection.sql"
_SQL_HELM = (_REPO / "helm" / "invincible-agent" / "files" / "sql"
             / "create_answer_artifact_projection.sql")

_TREE = ast.parse(_GATEWAY.read_text(encoding="utf-8"))


def _is_monotonic_call(n: ast.AST) -> bool:
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "monotonic")


def _is_route_intent_post(n: ast.AST) -> bool:
    """A `.post(...)` whose first argument mentions the literal `/route_intent`. By FORM."""
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "post" and bool(n.args)
            and "/route_intent" in ast.unparse(n.args[0]))


def _function_with_the_post() -> ast.AST:
    found = [f for f in ast.walk(_TREE)
             if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
             and any(_is_route_intent_post(n) for n in ast.walk(f))
             and any(isinstance(n, ast.Name) and n.id == "_pre_resolved" for n in ast.walk(f))]
    # Innermost: the one that is not an ancestor of another match.
    inner = [f for f in found
             if not any(g is not f and any(n is g for n in ast.walk(f)) for g in found)]
    assert len(inner) == 1, f"expected ONE function making the /route_intent POST, got {len(inner)}"
    return inner[0]


def _bundle_literals_with_intent_ms() -> list[ast.Dict]:
    """The artifact bundle literal, by FORM: the dict that carries `intent_ms` AND
    `question_text`/`valid_as_of` (the failure-record dict beside the dispatch also carries
    an intent_ms key, and is a diagnostic copy, not a bundle)."""
    def keys(d):
        return {k.value for k in d.keys if isinstance(k, ast.Constant)}
    return [d for d in ast.walk(_TREE) if isinstance(d, ast.Dict)
            and {"intent_ms", "question_text", "valid_as_of"} <= keys(d)]


# ── the model: absence is the default ───────────────────────────────────────
def test_the_field_defaults_to_None_never_zero():
    from iagent.answer_artifact_writer import AnswerArtifactBundle

    flds = {f.name: f for f in dataclasses.fields(AnswerArtifactBundle)}
    assert "intent_ms" in flds, "AnswerArtifactBundle has no intent_ms"
    assert flds["intent_ms"].default is None


# ── the bundle key: one, and its value is a Name fed only by None and the clock ──
def _intent_name() -> str:
    lits = _bundle_literals_with_intent_ms()
    assert len(lits) == 1, f"expected exactly ONE bundle dict with an intent_ms key, got {len(lits)}"
    d = lits[0]
    keys = [k.value for k in d.keys if isinstance(k, ast.Constant)]
    assert keys.count("intent_ms") == 1
    val = d.values[[getattr(k, "value", None) for k in d.keys].index("intent_ms")]
    assert isinstance(val, ast.Name), (
        f"the bundle's intent_ms is {ast.unparse(val)!r}, not a bare Name: it must carry the "
        "value measured at the call and nothing derived from valid_as_of or the wire")
    return val.id


def test_the_bundle_carries_one_intent_ms_key_whose_value_is_a_Name():
    _intent_name()


def test_the_Name_is_assigned_only_None_and_a_monotonic_difference():
    name = _intent_name()
    fn = _function_with_the_post()
    assigns = [n for n in ast.walk(fn)
               if (isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
               or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                   and n.target.id == name and n.value is not None)]
    assert len(assigns) == 2, f"{name} must be assigned exactly twice (None, then the clock), got {len(assigns)}"
    values = [a.value for a in assigns]
    nones = [v for v in values if isinstance(v, ast.Constant) and v.value is None]
    others = [v for v in values if v not in nones]
    assert len(nones) == 1 and len(others) == 1, [ast.unparse(v) for v in values]
    # The computed one reads two monotonic() stamps by name, and nothing wall-clock.
    stamps = {n.id for n in ast.walk(others[0]) if isinstance(n, ast.Name)}
    src = ast.unparse(others[0])
    assert "valid_as_of" not in src and "time.time" not in src, src
    clock_names = {t.id for a in ast.walk(fn)
                   if isinstance(a, ast.Assign) and _is_monotonic_call(a.value)
                   for t in a.targets if isinstance(t, ast.Name)}
    assert len(stamps & clock_names) == 2, (
        f"intent_ms is not the difference of two monotonic() stamps: {src!r}")


# ── the bracket: first read before the POST, second after resp.json() ───────
def test_the_monotonic_pair_brackets_the_POST():
    fn = _function_with_the_post()
    post = next(n for n in ast.walk(fn) if _is_route_intent_post(n))
    json_call = min((n for n in ast.walk(fn)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "json" and n.lineno > post.lineno),
                    key=lambda n: n.lineno)
    name = _intent_name()
    reads = sorted(
        (a.lineno, a.targets[0].id) for a in ast.walk(fn)
        if isinstance(a, ast.Assign) and _is_monotonic_call(a.value)
        and isinstance(a.targets[0], ast.Name))
    assert len(reads) == 2, f"expected exactly two monotonic() stamps in the function, got {reads}"
    (t0_line, _), (t1_line, _) = reads
    assert t0_line < post.lineno, "the first monotonic() read is not before the POST"
    assert t1_line > json_call.lineno, "the second monotonic() read is not after resp.json()"
    # ... and before the bundle that carries it is built.
    bundle = _bundle_literals_with_intent_ms()[0]
    assert t1_line < bundle.lineno, f"the second read comes after the bundle ({name}) is built"
    # ... and the subtraction itself sits right after the second read, not later.
    assign = next(a for a in ast.walk(fn) if isinstance(a, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == name for t in a.targets)
                  and not isinstance(a.value, ast.Constant))
    assert assign.lineno >= t1_line and assign.lineno < bundle.lineno


# ── None paths: initialised before the chain, assigned only in the POST's else ──
def test_interview_and_pre_resolved_paths_leave_it_None():
    name = _intent_name()
    fn = _function_with_the_post()
    chain = next(n for n in ast.walk(fn) if isinstance(n, ast.If)
                 and isinstance(n.test, ast.Name) and n.test.id == "is_interview_active")
    init = next(n for n in ast.walk(fn)
                if (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                    and n.target.id == name)
                or (isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                    and n.value.value is None
                    and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)))
    assert init.lineno < chain.lineno, "intent_ms is not initialised before the `if is_interview_active:` chain"
    # chain: if interview / elif _pre_resolved / else (POST)
    elif_ = chain.orelse[0]
    assert isinstance(elif_, ast.If) and ast.unparse(elif_.test) == "_pre_resolved"
    else_ = elif_.orelse
    assert else_, "no else branch after the _pre_resolved arm"

    def assigns_in(stmts) -> int:
        return sum(1 for s in stmts for n in ast.walk(s)
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))

    assert assigns_in(chain.body) == 0, "the interview arm assigns intent_ms"
    assert assigns_in(elif_.body) == 0, "the _pre_resolved arm assigns intent_ms"
    assert assigns_in(else_) == 1, "intent_ms is not assigned exactly once, in the POST's else"
    assert any(_is_route_intent_post(n) for s in else_ for n in ast.walk(s))


# ── the writer ───────────────────────────────────────────────────────────────
def _write_kwargs(intent_ms):
    from iagent.answer_artifact_writer import AnswerArtifactBundle, AnswerArtifactWriter

    b = AnswerArtifactBundle(id="a1", status="complete", question_text="q",
                             valid_as_of=1000, intent_ms=intent_ms, message_id="m",
                             produced_by=None, produced_for=None, resolved_intent=None,
                             routing=None)
    tx = MagicMock()
    tx.run.return_value.single.return_value = {"watermark": 1}
    AnswerArtifactWriter._tx_merge(tx, b, "durable")
    for c in tx.run.call_args_list:
        if "a.intent_ms = $intent_ms" in (c.args[0] if c.args else ""):
            return c.kwargs
    raise AssertionError("no write sets a.intent_ms = $intent_ms")


def test_the_writer_sets_the_property():
    assert "a.intent_ms = $intent_ms" in _WRITER.read_text(encoding="utf-8")


def test_zero_survives_the_write_and_none_stays_none():
    assert _write_kwargs(0)["intent_ms"] == 0
    assert _write_kwargs(0)["intent_ms"] is not None
    assert _write_kwargs(None)["intent_ms"] is None
    assert _write_kwargs(250)["intent_ms"] == 250


def test_the_writer_never_derives_it():
    src = _WRITER.read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if l.strip().startswith("intent_ms=bundle"))
    assert "or " not in line and "valid_as_of" not in line, line


# ── the projector ────────────────────────────────────────────────────────────
def test_the_projector_carries_it_through_insert_upsert_and_params():
    proj = _PROJECTOR.read_text(encoding="utf-8")
    for frag in (".intent_ms,", "summary, duration_ms, intent_ms,", "%(intent_ms)s",
                 "intent_ms = EXCLUDED.intent_ms", '"intent_ms": art.get("intent_ms")'):
        assert frag in proj, f"projector missing {frag!r}"
    line = next(l for l in proj.splitlines() if '"intent_ms":' in l)
    assert "or 0" not in line.replace(" ", " ") and " or " not in line, line


# ── the SQL, both copies ─────────────────────────────────────────────────────
def test_both_sql_files_add_the_column_and_stay_identical():
    a = _SQL.read_text(encoding="utf-8")
    b = _SQL_HELM.read_text(encoding="utf-8")
    for t in (a, b):
        assert "ADD COLUMN IF NOT EXISTS intent_ms BIGINT" in t
    assert a == b, "the chart's SQL copy has drifted from sql/"


# ── the read-back ────────────────────────────────────────────────────────────
def test_the_read_back_carries_it():
    assert "a.intent_ms" in _READS.read_text(encoding="utf-8")
    assert "AS intent_ms" in _READS.read_text(encoding="utf-8")


def test_the_read_model_has_the_field():
    cls = next(c for c in ast.walk(_TREE) if isinstance(c, ast.ClassDef)
               and c.name == "ArtifactResponse")
    flds = [n for n in cls.body if isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name) and n.target.id == "intent_ms"]
    assert len(flds) == 1 and "Optional[int]" in ast.unparse(flds[0].annotation)
    assert any(isinstance(k, ast.keyword) and k.arg == "intent_ms"
               and ast.unparse(k.value).replace("'", '"') == 'rec.get("intent_ms")'
               for k in ast.walk(_TREE))
