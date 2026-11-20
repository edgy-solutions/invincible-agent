"""Engine A's /resolve fallback relays the task's own bearer (ruled 2026-11-19, Q2, part 3).

"Engine A's `/resolve` fallback relays the task's `user_jwt`." Engine A's `_resolve_ontology` is
loaded by path (the pattern of `test_a_timed_out_reresolve_refuses.py`) with a fake `requests`; the
caller's `user_jwt` keyword must reach the Authorization header of the one post to engine O, and no
printed text may carry it.

Run: uv run --frozen pytest tests/routing/test_engine_a_resolve_relays_the_task_token.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import requests as real_requests

_ANALYST = Path(__file__).resolve().parents[2] / "agent_fleet" / "restate_analyst" / "main.py"
PERSON = "alice@example.com"
TOKEN = "tok-alice-0123456789-secret"
SERVICE = {"Authorization": "Bearer service-token"}


class _Terminal(Exception):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.status_code = status_code


class _Restate:
    TerminalError = _Terminal


class _Resp:
    def __init__(self, status_code=200, text="", body=None):
        self.status_code, self.text = status_code, text
        self._body = body if body is not None else {
            "resolved_uri": "UNKNOWN", "confidence_score": 0.0, "reasoning": "", "provenance": {}}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise real_requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._body


class _Exc:
    ReadTimeout = type("ReadTimeout", (Exception,), {})
    ConnectionError = type("ConnectionError", (Exception,), {})


def _load(resp=None):
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_resolve_ontology")
    helpers = [n for n in tree.body
               if (isinstance(n, ast.FunctionDef) and n.name == "_person_token_refusal")
               or (isinstance(n, ast.Assign)
                   and any(getattr(t, "id", "") == "_PERSON_TOKEN_REFUSALS" for t in n.targets))]
    seen: list = []

    class _Requests:
        exceptions = _Exc

        @staticmethod
        def post(url, json=None, timeout=None, headers=None):  # noqa: A002
            seen.append({"url": url, "json": json, "headers": headers})
            return resp if resp is not None else _Resp()

    ns = {"requests": _Requests, "restate": _Restate,
          "ONTOLOGY_RESOLVE_URL": "http://engine-o/resolve", "ONTOLOGY_TIMEOUT": 30,
          "outbound_auth_headers": lambda **k: dict(SERVICE)}
    exec(compile(ast.Module(body=[*helpers, fn], type_ignores=[]), "<resolve>", "exec"), ns)
    return ns["_resolve_ontology"], seen


def test_11_the_task_token_is_the_authorization_header_in_place_of_the_service_token():
    resolve, seen = _load()
    resolve("which parts does X impact", PERSON, [], user_jwt=TOKEN)
    (post,) = seen
    assert post["headers"] == {"Authorization": f"Bearer {TOKEN}"}


def test_11b_a_bearer_prefixed_token_is_not_double_prefixed():
    resolve, seen = _load()
    resolve("which parts does X impact", PERSON, [], user_jwt=f"Bearer {TOKEN}")
    assert seen[0]["headers"] == {"Authorization": f"Bearer {TOKEN}"}


def test_11c_no_task_token_keeps_the_service_token_as_before():
    for blank in ("", "   ", "Bearer "):
        resolve, seen = _load()
        resolve("which parts does X impact", PERSON, [], user_jwt=blank)
        assert seen[0]["headers"] == SERVICE
    resolve, seen = _load()
    resolve("which parts does X impact", PERSON, [])
    assert seen[0]["headers"] == SERVICE


def test_11d_the_token_is_never_printed(capsys):
    resolve, _ = _load()
    resolve("which parts does X impact", PERSON, [], user_jwt=TOKEN)
    out = capsys.readouterr()
    assert TOKEN not in out.out and TOKEN not in out.err


# =========================================================================================
# 12. A REFUSED PERSON TOKEN IS TERMINAL (gov hold 2026-11-20, Q2 condition 3)
# =========================================================================================

EXPIRED_403 = '{"detail": "transport auth failed: invalid: ExpiredSignatureError"}'
AUD_403 = '{"detail": "transport auth failed: invalid: InvalidAudienceError"}'
SESSION_MSG = "session_expired: the person's session has expired; sign in again"
REFUSED_MSG = "caller_refused: Engine O refused the person's token; sign in again"


def _engine_o_refusals():
    tree = ast.parse((_ANALYST.parents[1] / "ontology_service" / "main.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "_PERSON_TOKEN_REFUSALS" for t in n.targets))
    return ast.literal_eval(node.value)


def _engine_a_refusals():
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "_PERSON_TOKEN_REFUSALS" for t in n.targets))
    return ast.literal_eval(node.value)


def test_g6_engine_a_and_engine_o_name_the_same_refusals():
    assert _engine_a_refusals() == _engine_o_refusals() == ("session_expired", "caller_refused")


@pytest.mark.parametrize("resp,status,msg", [
    (_Resp(403, EXPIRED_403), 401, SESSION_MSG),
    (_Resp(401, ""), 401, SESSION_MSG),
    (_Resp(403, AUD_403), 403, REFUSED_MSG),
])
def test_g7_a_relayed_refusal_is_terminal_not_retryable(resp, status, msg, capsys):
    resolve, _ = _load(resp)
    with pytest.raises(_Terminal) as ei:
        resolve("q", PERSON, [], user_jwt=TOKEN)
    assert ei.value.status_code == status and str(ei.value) == msg
    assert not isinstance(ei.value, real_requests.HTTPError)
    out = capsys.readouterr()                                    # G10
    assert TOKEN not in str(ei.value) and TOKEN not in out.out and TOKEN not in out.err


def test_g8_the_service_path_keeps_raise_for_status():
    resolve, _ = _load(_Resp(403, EXPIRED_403))
    with pytest.raises(real_requests.HTTPError):
        resolve("q", PERSON, [])


@pytest.mark.parametrize("jwt_", [TOKEN, ""])
@pytest.mark.parametrize("match,status,msg", [
    ("session_expired", 401, SESSION_MSG), ("caller_refused", 403, REFUSED_MSG)])
def test_g9_an_answer_naming_a_refused_session_is_never_answered(jwt_, match, status, msg, capsys):
    body = {"resolved_uri": "UNKNOWN", "provenance": {"instance_match": match}}
    resolve, _ = _load(_Resp(200, body=body))
    with pytest.raises(_Terminal) as ei:
        resolve("q", PERSON, [], user_jwt=jwt_)
    assert ei.value.status_code == status and str(ei.value) == msg
    out = capsys.readouterr()                                    # G10
    assert TOKEN not in str(ei.value) and TOKEN not in out.out and TOKEN not in out.err


def test_g9_control_an_ordinary_answer_is_returned_unchanged():
    body = {"resolved_uri": "UNKNOWN", "provenance": {"instance_match": "empty"}}
    resolve, _ = _load(_Resp(200, body=body))
    assert resolve("q", PERSON, [], user_jwt=TOKEN) is body


# G12: the journal shape of `analyze`, up to the first await that is not a ctx.run. Hard-coded from
# origin/master's agent_fleet/restate_analyst/main.py (`git show`, 2026-11-20). A write added before
# a wait point breaks every suspended workflow's replay (RULED 11-19; #471): H3 adds no ctx call.
MASTER_JOURNAL_SHAPE = [("ctx.run", "resolve_ontology")]


def _journal_shape():
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "analyze")
    events = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "ctx":
            name = n.args[0].value if n.args and isinstance(n.args[0], ast.Constant) else None
            events.append((n.lineno, n.col_offset, f"ctx.{n.func.attr}", name))
        elif isinstance(n, ast.Await):
            v = n.value
            is_run = (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                      and isinstance(v.func.value, ast.Name) and v.func.value.id == "ctx"
                      and v.func.attr == "run")
            if not is_run:
                events.append((n.lineno, n.col_offset, "await", None))
    events.sort()
    out = []
    for _, _, kind, name in events:
        if kind == "await":
            break
        out.append((kind, name))
    return out


def test_g12_engine_a_journal_shape_is_the_one_on_master():
    assert _journal_shape() == MASTER_JOURNAL_SHAPE
