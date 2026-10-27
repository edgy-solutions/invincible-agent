"""A TIMED-OUT RE-RESOLVE REFUSES, IT IS NOT RETRIED -- architect ruling 2026-10-20.

    "a Restate retry on a timed-out model call is never automatic -- it refuses with
     `resolution_timeout` and the supervisor decides."

MEASURED 2026-10-20 (sandbox revision 199): Engine A's `_resolve_ontology` runs inside
`ctx.run("resolve_ontology")`, where an ordinary exception is retried by Restate on every read
timeout. One prompt was re-resolved 4 and 8 times, each a full model call that Engine O
completed. A ReadTimeout is now a terminal 504; other transport errors stay retryable.

Run: uv run --frozen pytest tests/routing/test_a_timed_out_reresolve_refuses.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ANALYST = _REPO / "agent_fleet" / "restate_analyst" / "main.py"
PERSON = "alice@example.com"


class _Terminal(Exception):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.status_code = status_code


class _Restate:
    TerminalError = _Terminal


class _ReadTimeout(Exception):
    pass


class _ConnectionError(Exception):
    pass


class _Exceptions:
    ReadTimeout = _ReadTimeout
    ConnectionError = _ConnectionError


def _load(post):
    """Engine A's real `_resolve_ontology`, loaded by path, with a fake `requests`."""
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_resolve_ontology")
    calls: list = []

    class _Requests:
        exceptions = _Exceptions

        @staticmethod
        def post(url, json=None, timeout=None, headers=None):  # noqa: A002
            calls.append(json)
            return post()

    ns = {"requests": _Requests, "restate": _Restate,
          "ONTOLOGY_RESOLVE_URL": "http://engine-o/resolve", "ONTOLOGY_TIMEOUT": 30,
          "outbound_auth_headers": lambda **k: {}}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<resolve>", "exec"), ns)
    return ns["_resolve_ontology"], calls


def _raiser(exc):
    def _post():
        raise exc
    return _post


def test_a_read_timeout_is_a_terminal_504_resolution_timeout_after_one_post():
    resolve, calls = _load(_raiser(_ReadTimeout("Read timed out")))
    with pytest.raises(_Terminal) as e:
        resolve("which parts does X impact", PERSON, [])
    assert e.value.status_code == 504
    assert str(e.value).startswith("resolution_timeout")
    assert len(calls) == 1


def test_control_a_connection_error_stays_retryable():
    resolve, calls = _load(_raiser(_ConnectionError("refused")))
    with pytest.raises(_ConnectionError):
        resolve("which parts does X impact", PERSON, [])
    assert len(calls) == 1


def test_control_a_normal_response_returns_the_json():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"resolved_uri": "http://x#Thing", "confidence_score": 0.9}

    resolve, _ = _load(lambda: _Resp())
    assert resolve("q", PERSON, []) == {"resolved_uri": "http://x#Thing", "confidence_score": 0.9}


def test_the_person_refusal_still_precedes_the_post():
    resolve, calls = _load(_raiser(_ReadTimeout("never reached")))
    with pytest.raises(_Terminal) as e:
        resolve("q", "  ", ["SUSTAINMENT"])
    assert e.value.status_code == 422
    assert str(e.value).startswith("no_person")
    assert calls == []
