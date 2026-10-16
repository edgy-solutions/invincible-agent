"""A re-resolve runs as a PERSON or is refused — ruling (b), 2026-10-10.

    "(b) scripts and restate_analyst send a real test persona or get refused — a domains list
     is never an entitlement"

Two callers of Engine O's `/resolve` sent a domains list with no person:

  1. Engine A's `_resolve_ontology` (the legacy re-resolve, taken when no supervisor subject
     arrived) posted a blank caller as "honest-absent" while still carrying the request's
     `entitled_domains`;
  2. `scripts/run_resolver_corpus.py` posted `{query, domain, domains}` at all four of its
     `/resolve` sites and never named anyone.

Both now refuse before sending anything. Each arm asserts on what is SENT (or that nothing is),
not on a log line.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ANALYST = _REPO / "agent_fleet" / "restate_analyst" / "main.py"
_SCRIPT = _REPO / "scripts" / "run_resolver_corpus.py"
PERSON = "alice@example.com"


# ── 1. Engine A's re-resolve ────────────────────────────────────────────────────────────────


class _Terminal(Exception):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.status_code = status_code


class _Restate:
    TerminalError = _Terminal


def _load_resolve():
    """Engine A's real `_resolve_ontology`, loaded by path (the package drags Restate and
    smolagents in), with its HTTP hop recorded and a stand-in `restate.TerminalError`."""
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_resolve_ontology")
    sent: list = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"resolved_uri": "http://x#Thing", "confidence_score": 0.9}

    class _Requests:
        @staticmethod
        def post(url, json=None, timeout=None, headers=None):  # noqa: A002
            sent.append(json)
            return _Resp()

    ns = {"requests": _Requests, "restate": _Restate,
          "ONTOLOGY_RESOLVE_URL": "http://engine-o/resolve", "ONTOLOGY_TIMEOUT": 30,
          "outbound_auth_headers": lambda **k: {}}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<resolve>", "exec"), ns)
    return ns["_resolve_ontology"], sent


@pytest.mark.parametrize("who", ["", "   ", None])
@pytest.mark.parametrize("domains", [["SUSTAINMENT"], []])
def test_no_person_is_a_422_no_person_and_nothing_is_sent(who, domains):
    """The domains list is present in one case on purpose: it must NOT stand in for a person."""
    resolve, sent = _load_resolve()
    with pytest.raises(_Terminal) as e:
        resolve("which parts does IPCN25300X impact", who, domains)
    assert e.value.status_code == 422
    assert str(e.value).startswith("no_person")
    assert sent == [], f"a re-resolve with no person reached Engine O: {sent!r}"


def test_a_person_is_sent_as_the_caller():
    resolve, sent = _load_resolve()
    resolve("which parts does IPCN25300X impact", PERSON, ["SUSTAINMENT"])
    assert len(sent) == 1
    assert sent[0]["user_email"] == PERSON
    assert sent[0]["domains"] == ["SUSTAINMENT"]


def test_the_legacy_path_hands_the_requests_person_to_the_re_resolve():
    """The call site, not just the function: the `ctx.run("resolve_ontology", ...)` lambda
    passes the request's `user_email` binding as the second argument."""
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "_resolve_ontology"]
    assert len(calls) == 1, f"expected ONE call site, found {len(calls)}"
    arg = calls[0].args[1]
    assert isinstance(arg, ast.Name) and arg.id == "resolve_caller_email"
    binds = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and any(getattr(t, "id", None) == "resolve_caller_email" for t in n.targets)]
    assert binds and all("user_email" in ast.unparse(b.value) for b in binds), \
        [ast.unparse(b.value) for b in binds]


# ── 2. the resolver corpus script ───────────────────────────────────────────────────────────


@pytest.fixture
def corpus(monkeypatch):
    spec = importlib.util.spec_from_file_location("run_resolver_corpus_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sent: list = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"uri": "idp#Table", "score": 0.9}], "provenance": {},
                    "verbs": []}

    def _post(url, json=None, **kw):  # noqa: A002
        sent.append((url.rsplit("/", 1)[-1], json))
        return _Resp()

    monkeypatch.setattr(mod.requests, "post", _post)
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp())
    return mod, sent


META = {"domain": "DATA_ENGINEERING", "requires_pool": ["idp#Table"],
        "requires_instances": ["p_cage"]}


def test_unset_persona_refuses_to_run_before_sending_anything(corpus, monkeypatch, capsys):
    mod, sent = corpus
    monkeypatch.delenv("IA_CORPUS_ON_BEHALF_OF", raising=False)
    monkeypatch.setattr("sys.argv", ["run_resolver_corpus.py", "--base-url", "http://o"])
    assert mod.main() == 2
    assert sent == []
    assert "no person" in capsys.readouterr().err


def test_every_resolve_and_verbs_call_carries_the_persona(corpus, monkeypatch):
    """All four `/resolve` sites (probe, stamp's two loops, check_pool) and `/find_compatible_verbs`."""
    mod, sent = corpus
    monkeypatch.setenv("IA_CORPUS_ON_BEHALF_OF", f"  {PERSON} ")
    mod.check_pool("http://o", META, 5)
    mod.stamp("http://o", META, 5)
    mod.probe("http://o", {"id": "r1", "query": "the p_cage table"}, META, 5)
    mod._verbs("http://o", "idp#Table", ["DATA_ENGINEERING"], 5)
    resolves = [b for ep, b in sent if ep == "resolve"]
    verbs = [b for ep, b in sent if ep == "find_compatible_verbs"]
    # check_pool 3 + stamp 3 + stamp's instance 1 + probe 1
    assert len(resolves) >= 8, sent
    assert all(b.get("user_email") == PERSON for b in resolves), resolves
    assert verbs and all(b.get("on_behalf_of") == PERSON for b in verbs), verbs


def test_a_blank_persona_sends_nothing_from_any_site(corpus, monkeypatch):
    """Called directly (not through main), a site with no person posts nothing: the probe records
    the refusal as its error, the pool gate sees an empty pool, `_verbs` reads -1."""
    mod, sent = corpus
    monkeypatch.setenv("IA_CORPUS_ON_BEHALF_OF", "   ")
    out = mod.probe("http://o", {"id": "r1", "query": "q"}, META, 5)
    ok, missing = mod.check_pool("http://o", META, 5)
    st = mod.stamp("http://o", META, 5)
    assert "no_person" in out.get("error", "")
    assert (ok, missing) == (False, ["idp#Table"])
    assert st["pool_size"] == 0
    assert mod._verbs("http://o", "idp#Table", [], 5) == -1
    assert sent == []
