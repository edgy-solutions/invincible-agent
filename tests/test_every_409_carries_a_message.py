"""Spec 204, Part E (architect: "Every 409 carries `message`. Make it a seal."): every
`HTTPException(status_code=409, ...)` / `JSONResponse(status_code=409, ...)` in `src/iagent/gateway.py`
(and any call whose status is not a constant, which may be 409) has a dict detail with a non-empty
`"message"`. A STATIC check over the AST. The checker is positive-controlled inside this file."""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "iagent"
GATEWAY = SRC / "gateway.py"


def _callee(call: ast.Call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _status(call: ast.Call):
    for kw in call.keywords:
        if kw.arg == "status_code":
            return kw.value
    return call.args[0] if call.args else None


def _detail(call: ast.Call):
    name = "content" if _callee(call) == "JSONResponse" else "detail"
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _has_message(node) -> bool:
    # A relayed status/detail (an engine's refusal, a helper's parameter) cannot be a literal: it must
    # go through `_detail_with_message`, whose behaviour is pinned by the arms at the foot of this file.
    if isinstance(node, ast.Call) and _callee(node) == "_detail_with_message":
        return True
    if not isinstance(node, ast.Dict):
        return False
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and k.value == "message":
            return not (isinstance(v, ast.Constant) and (v.value is None or v.value == ""))
    return False


def _enclosing_function(tree, target):
    best = None
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(n is target for n in ast.walk(fn)):
                best = fn  # ast.walk is outer-first, so the last match is the innermost
    return best


def _resolves_to_message_dict(tree, call, name: str) -> bool:
    fn = _enclosing_function(tree, call)
    scope = fn if fn is not None else tree
    best = None
    for n in ast.walk(scope):
        # AN ANNOTATION IS STILL AN ASSIGNMENT. `d: dict = {..., "message": ...}` binds the same
        # value as `d = {...}`; reading only `ast.Assign` redded a 409 that carried its message
        # (#97's canvas-seed body). A bare annotation (`d: dict`, no value) binds nothing.
        if (isinstance(n, ast.Assign) and n.lineno < call.lineno
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)) or (
                isinstance(n, ast.AnnAssign) and n.value is not None and n.lineno < call.lineno
                and isinstance(n.target, ast.Name) and n.target.id == name):
            if best is None or n.lineno > best.lineno:
                best = n
    return best is not None and _has_message(best.value)


def check_source(source: str):
    """Return (in_scope_count, [lineno of each in-scope call that lacks a message])."""
    tree = ast.parse(source)
    in_scope, bad = 0, []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _callee(call) not in ("HTTPException", "JSONResponse"):
            continue
        st = _status(call)
        if st is None:
            continue
        if isinstance(st, ast.Constant) and st.value != 409:
            continue
        in_scope += 1
        d = _detail(call)
        ok = _has_message(d) or (isinstance(d, ast.Name)
                                 and _resolves_to_message_dict(tree, call, d.id))
        if not ok:
            bad.append(call.lineno)
    return in_scope, bad


def test_every_409_in_the_gateway_carries_a_message():
    n, bad = check_source(GATEWAY.read_text(encoding="utf-8"))
    assert n >= 30, f"the checker matched only {n} sites; it has gone blind"
    assert not bad, "409 (or non-constant status) without a message at gateway.py lines " + \
        ", ".join(map(str, bad))


def test_no_other_module_in_src_answers_409():
    others = [p.name for p in SRC.rglob("*.py")
              if p != GATEWAY and "status_code=409" in p.read_text(encoding="utf-8", errors="ignore")]
    assert not others, f"widen this seal's file list to cover: {others}"


# ---- positive controls: the checker must see each defect and pass the compliant form ------------
def test_control_a_string_detail_is_reported():
    assert check_source('raise HTTPException(status_code=409, detail="nope")')[1] == [1]


def test_control_a_dict_without_message_is_reported():
    assert check_source('raise HTTPException(status_code=409, detail={"error": "x"})')[1] == [1]


def test_control_an_empty_message_is_reported():
    assert check_source(
        'raise HTTPException(status_code=409, detail={"error": "x", "message": ""})')[1] == [1]


def test_control_a_non_constant_status_is_in_scope():
    n, bad = check_source('JSONResponse(status_code=st, content={"error": "x"})')
    assert n == 1 and bad == [1]


def test_control_a_compliant_snippet_is_not_reported():
    src = ('def f():\n'
           '    d = {"error": "x", "message": "m"}\n'
           '    raise HTTPException(status_code=409, detail=d)\n'
           'raise HTTPException(status_code=409, detail={"error": "x", "message": "m"})\n'
           'raise HTTPException(status_code=404, detail="other statuses are out of scope")\n')
    n, bad = check_source(src)
    assert n == 2 and bad == []


def test_control_an_annotated_detail_is_read_like_a_plain_one():
    ok = ('def f():\n'
          '    d: dict = {"error": "x", "message": "m"}\n'
          '    raise HTTPException(status_code=409, detail=d)\n')
    missing = ('def f():\n'
               '    d: dict = {"error": "x"}\n'
               '    raise HTTPException(status_code=409, detail=d)\n')
    # The bare annotation comes AFTER a compliant binding, so it is the latest candidate: if it
    # counted, it would shadow the binding that carries the message and report a false red.
    bare = ('def f():\n'
            '    d = {"error": "x", "message": "m"}\n'
            '    d: dict\n'
            '    raise HTTPException(status_code=409, detail=d)\n')
    assert check_source(ok)[1] == []
    assert check_source(missing)[1] == [3]
    assert check_source(bare)[1] == [], "an annotation with no value rebinds nothing"


def test_control_a_relayed_detail_must_go_through_the_helper():
    assert check_source('raise HTTPException(status_code=rr.status_code, detail=rr.json())')[1] == [1]
    assert check_source('raise HTTPException(status_code=rr.status_code, '
                        'detail=_detail_with_message(rr.status_code, rr.json()))')[1] == []


def test_the_helper_gives_every_409_shape_a_message_and_leaves_other_statuses_alone():
    import sys
    sys.path.insert(0, str(SRC.parents[1]))
    from src.iagent import gateway
    f = gateway._detail_with_message
    assert f(404, "x") == "x" and f(422, {"a": 1}) == {"a": 1}
    for raw in ("text", {"error": "e"}, {"error": "e", "message": ""}, ["l"], None):
        d = f(409, raw)
        assert isinstance(d, dict) and str(d["message"]).strip(), raw
    assert f(409, {"error": "e", "message": "kept"})["message"] == "kept"
    assert f(409, "text")["message"] == "text"
