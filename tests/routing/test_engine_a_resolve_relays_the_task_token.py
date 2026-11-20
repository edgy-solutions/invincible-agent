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
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"resolved_uri": "UNKNOWN", "confidence_score": 0.0, "reasoning": "", "provenance": {}}


class _Exc:
    ReadTimeout = type("ReadTimeout", (Exception,), {})
    ConnectionError = type("ConnectionError", (Exception,), {})


def _load():
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_resolve_ontology")
    seen: list = []

    class _Requests:
        exceptions = _Exc

        @staticmethod
        def post(url, json=None, timeout=None, headers=None):  # noqa: A002
            seen.append({"url": url, "json": json, "headers": headers})
            return _Resp()

    ns = {"requests": _Requests, "restate": _Restate,
          "ONTOLOGY_RESOLVE_URL": "http://engine-o/resolve", "ONTOLOGY_TIMEOUT": 30,
          "outbound_auth_headers": lambda **k: dict(SERVICE)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<resolve>", "exec"), ns)
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
