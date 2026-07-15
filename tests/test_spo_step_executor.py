"""Unit tests for the SPO-step executor (ADR-0029 Slice 1). Pure — HTTP is mocked;
no Engine O, no Topaz, no runner, no deploy. Proves the enforcement points fire:
the verifier fail-and-releases an ineligible verb, dispatch fail-and-releases on a
permission denial, and a direct_call is gated on can_invoke BEFORE it dispatches.

Run:
    uv run --with httpx --with requests python tests/test_spo_step_executor.py
"""
import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_MOD = _REPO / "agent_fleet" / "restate_analyst" / "spo_step_executor.py"


def _load():
    spec = importlib.util.spec_from_file_location("spo_step_executor", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


ex = _load()


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Patch:
    """Save/restore module attrs so tests don't leak (script-mode, no pytest)."""

    def __init__(self, **kw):
        self.kw = kw
        self.old = {}

    def __enter__(self):
        for target, fn in self.kw.items():
            obj, attr = target.rsplit("_", 1)  # e.g. "requests_post" -> requests.post
            mod = getattr(ex, obj)
            self.old[target] = getattr(mod, attr)
            setattr(mod, attr, fn)
        return self

    def __exit__(self, *a):
        for target, val in self.old.items():
            obj, attr = target.rsplit("_", 1)
            setattr(getattr(ex, obj), attr, val)


# ── verifier ────────────────────────────────────────────────────────────────

def test_verify_eligible_returns_verb():
    verbs = {"verbs": [{"verb_iri": "mesh:analyzeDataset",
                        "endpoint_url": "http://da/analyze_data", "arity": "single"}]}
    with _Patch(requests_post=lambda *a, **k: FakeResp(200, verbs)):
        v = ex.verify_spo_step("subj", "mesh:analyzeDataset", ["DATA_ENGINEERING"])
    assert v["endpoint_url"] == "http://da/analyze_data"


def test_verify_ineligible_fails_and_releases():
    verbs = {"verbs": [{"verb_iri": "mesh:somethingElse"}]}
    with _Patch(requests_post=lambda *a, **k: FakeResp(200, verbs)):
        try:
            ex.verify_spo_step("subj", "mesh:notEligible", ["DATA_ENGINEERING"])
        except ex.StepFailAndRelease as e:
            assert e.status_code == 403
            return
    raise AssertionError("ineligible verb should fail-and-release (403)")


def test_arity_filter_set_drops_single_instance_keeps_all():
    verbs = [{"verb_iri": "a", "arity": "single"}, {"verb_iri": "b", "arity": "set"},
             {"verb_iri": "c", "arity": None}]
    kept_set = {v["verb_iri"] for v in ex._filter_verbs_by_arity(verbs, query_is_set=True)}
    assert kept_set == {"b", "c"}, kept_set  # set-query drops the single-only verb
    kept_inst = ex._filter_verbs_by_arity(verbs, query_is_set=False)
    assert len(kept_inst) == 3  # instance step keeps every verb


# ── dispatch (permission at the engine gate) ─────────────────────────────────

def test_dispatch_permission_denied_fails_and_releases():
    with _Patch(requests_post=lambda *a, **k: FakeResp(403)):
        try:
            ex.dispatch_spo_step({"verb_iri": "v", "endpoint_url": "http://e"}, "subj",
                                 {"authz_id": "a"})
        except ex.StepFailAndRelease as e:
            assert e.status_code == 403
            return
    raise AssertionError("a 403 at dispatch (permission) should fail-and-release")


def test_dispatch_ok_returns_json():
    with _Patch(requests_post=lambda *a, **k: FakeResp(200, {"result": "ok"})):
        r = ex.dispatch_spo_step({"verb_iri": "v", "endpoint_url": "http://e"}, "subj",
                                 {"authz_id": "a"})
    assert r == {"result": "ok"}


# ── can_invoke gate (RULING Q3) ──────────────────────────────────────────────

def test_can_invoke_granted_and_denied_and_deny_by_default():
    with _Patch(httpx_post=lambda *a, **k: FakeResp(200, {"check": True})):
        assert ex.check_can_invoke("cap", "alice", topaz_url="http://t") is True
    with _Patch(httpx_post=lambda *a, **k: FakeResp(200, {"check": False})):
        assert ex.check_can_invoke("cap", "alice", topaz_url="http://t") is False
    # deny-by-default: empty identity / no topaz url
    assert ex.check_can_invoke("cap", "", topaz_url="http://t") is False
    assert ex.check_can_invoke("cap", "alice", topaz_url="") is False


def test_direct_call_denied_never_dispatches():
    calls = []
    with _Patch(httpx_post=lambda *a, **k: FakeResp(200, {"check": False}),
                requests_post=lambda *a, **k: calls.append(1) or FakeResp(200)):
        try:
            ex.execute_direct_call({"id": "s", "endpoint": "http://e", "capability": "cap"},
                                   {"authz_id": "alice"}, topaz_url="http://t")
        except ex.StepFailAndRelease as e:
            assert e.status_code == 403
            assert calls == [], "denied direct_call must NOT reach the POST"
            return
    raise AssertionError("ungranted capability should fail-and-release before dispatch")


def test_direct_call_granted_dispatches():
    with _Patch(httpx_post=lambda *a, **k: FakeResp(200, {"check": True}),
                requests_post=lambda *a, **k: FakeResp(200, {"published": True})):
        r = ex.execute_direct_call({"id": "s", "endpoint": "http://e", "capability": "cap"},
                                   {"authz_id": "alice"}, topaz_url="http://t")
    assert r == {"published": True}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
