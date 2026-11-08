"""ONE REFERENCE PER RUN, REDEEMED PER CALL (ruling 2026-11-03; supersedes the per-fan-out-slot
rule that this file used to pin).

The supervisor half. The vault's own rules are in ``test_identity_vault.py`` and the HTTP
surface's in ``test_redemption_endpoint.py``; this file proves what the SUPERVISOR does:

  * every outbound call that speaks for a person redeems the vault once, under a call id of
    its own (``<step>/<leg>/<uuid>``), through one helper gated by ``_run_has_a_person``;
  * the nine legs each carry the person's token, and carry none of it for a run with no person;
  * a vault refusal FAILS the step on every leg -- it is never absorbed into a fallback answer
    (the silent service-identity fallback this whole class exists to prevent);
  * ``awaiting_reauth`` is a pause the supervisor polls through, with no timer of its own, and
    ``not_found`` ends the polling loudly;
  * no token reaches any log, at DEBUG, on any of those paths.

Every vault answer here is a REAL ``httpx.Response``, so the status / json / text the supervisor
reads are the ones a wire would give it.

Run:  uv run --frozen python -m pytest tests/identity/test_a_reference_per_call.py -q
"""
from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import httpx
import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

ALICE = "alice@example.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-PING-ROOTED.signature"
SERVICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.SVC-SUPERVISOR.signature"
RUN = "0f1e2d3c-run"
REDEEM = "/internal/identity/redeem"


class _Ctx:
    """The slice of a Dagster context the supervisor reads."""
    run_id = RUN

    def __init__(self) -> None:
        self.log = logging.getLogger("test.supervisor.context")

        class _Op:
            name = "execute_subtask"
        self.op = _Op()

    def get_mapping_key(self):
        return "task_0"

    def add_output_metadata(self, *_a, **_k) -> None:
        pass

    def log_event(self, *_a, **_k) -> None:
        pass


def _config(email=ALICE):
    return ds.SupervisorQueryConfig(
        user_query="what failures are recorded for part 5530-184",
        thread_id="thread-1",
        user_email=email,
        user_persona="SAFETY_ENGINEER",
        entitled_domains=["SUSTAINMENT"],
        trace_id="trace-1",
        session_id="session-1",
    )


def _response(status, body, url="http://x.invalid/"):
    return httpx.Response(status, json=body, request=httpx.Request("POST", url))


class _Net:
    """Stands in for ``requests.post``. Vault redemptions are answered from ``script`` (a
    list of (status, body), the last one repeating); every other URL gets ``body_for``."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.script: list = [(200, {"token": TOKEN, "subject": ALICE})]

    def __call__(self, url, json=None, headers=None, timeout=None, **_kw):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if url.endswith(REDEEM):
            status, body = self.script.pop(0) if len(self.script) > 1 else self.script[0]
            return _response(status, body, url)
        return _response(200, self.body_for(url), url)

    @staticmethod
    def body_for(url):
        if url.endswith("/plan"):
            return {"tasks": [], "domain": "MAINTENANCE"}
        if url.endswith("/fill_slots"):
            return {"slots": {}}
        if "enumerate" in url:
            return {"outcome": "ok", "members": [], "count": 0}
        if url.endswith("/analyze"):
            return {"execution_trace": None}
        return {}

    @property
    def redemptions(self):
        return [c for c in self.calls if c["url"].endswith(REDEEM)]

    def outbound(self, fragment):
        return [c for c in self.calls if fragment in c["url"] and not c["url"].endswith(REDEEM)]


@pytest.fixture
def net(monkeypatch):
    n = _Net()
    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token",
        lambda *a, **k: SERVICE_TOKEN, raising=False,
    )
    monkeypatch.setattr(ds.requests, "post", n)
    monkeypatch.setattr(ds, "_ENUMERATE_URL", "http://engine-o.invalid/enumerate_instances")
    monkeypatch.setattr(ds, "_resolve_serialized", lambda ctx: _null())
    monkeypatch.setattr(ds.time, "sleep", lambda s: None)
    return n


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ── the nine legs: (name, URL fragment, driver) ──────────────────────────────────────

def _drive_plan(ctx, email):
    list(ds.create_task_plan.compute_fn.decorated_fn(ctx, _config(email)))


def _drive_resolve(ctx, email):
    ds._resolve_subject(ctx, "q", "MAINTENANCE", user_email=email)


def _drive_classify(ctx, email):
    # The earlier stages are not the subject here; /classify_predicate is.
    ds._resolve_subject, _saved = (
        lambda *a, **k: ("urn:x:Subject", 0.9, "r", "", [], None, "", []), ds._resolve_subject)
    try:
        orig_find = ds._find_compatible_verbs
        ds._find_compatible_verbs = lambda *a, **k: (
            [{"verb_iri": "urn:v:one", "required_args": []}], None)
        try:
            ds._classify_route(ctx, "q", ["SUSTAINMENT"], "MAINTENANCE", user_email=email)
        finally:
            ds._find_compatible_verbs = orig_find
    finally:
        ds._resolve_subject = _saved


def _drive_analyze(ctx, email):
    ds._call_engine_a_fallback(ctx, "q", _config(email), "no_match", 0.0, None)


def _drive_enumerate(ctx, email):
    ds._make_enumerator(ctx, user_email=email)("urn:cost:RateTable")


def _drive_fill_slots(ctx, email):
    ds._fill_slots_from_query(ctx, query="q", verb_iri="urn:v:one", declarations=[],
                              user_email=email)


def _drive_support(ctx, email):
    ds.synthesize_stateful.compute_fn.decorated_fn(ctx, _config(email), [])


def _drive_render_ui(ctx, email):
    list(ds.generate_ui_payload.compute_fn.decorated_fn(ctx, [], _config(email)))


LEGS = [
    ("plan", "/plan", _drive_plan),
    ("resolve", "/resolve", _drive_resolve),
    ("classify_predicate", "/classify_predicate", _drive_classify),
    ("analyze", "/analyze", _drive_analyze),
    ("enumerate", "enumerate", _drive_enumerate),
    ("fill_slots", "/fill_slots", _drive_fill_slots),
    ("support", "/support", _drive_support),
    ("render_ui", "/render_ui", _drive_render_ui),
]


@pytest.mark.parametrize("leg,fragment,drive", LEGS, ids=[l[0] for l in LEGS])
def test_a_leg_sends_the_persons_token_under_a_call_id_of_its_own(net, leg, fragment, drive):
    drive(_Ctx(), ALICE)
    sent = net.outbound(fragment)
    assert sent, f"the {leg} leg made no call"
    assert sent[0]["headers"]["Authorization"] == f"Bearer {TOKEN}", (
        f"the {leg} leg did not carry the person's own token"
    )
    red = [r for r in net.redemptions if (r["json"] or {}).get("leg") == leg]
    assert len(red) == 1, "one redemption for one call"
    body = red[0]["json"]
    assert body["run_id"] == RUN and body["claimed_launcher"] == ALICE
    assert "slot" not in body
    assert body["call_id"].split("/")[1] == leg and len(body["call_id"].split("/")[2]) == 32
    assert red[0]["headers"]["Authorization"] == f"Bearer {SERVICE_TOKEN}", (
        "the supervisor redeems AS ITSELF"
    )


@pytest.mark.parametrize("leg,fragment,drive", LEGS, ids=[l[0] for l in LEGS])
def test_a_leg_for_a_run_with_no_person_redeems_nothing_and_sends_no_persons_token(
        net, leg, fragment, drive):
    for email in ("", "svc:supervisor"):
        net.calls.clear()
        drive(_Ctx(), email)
        assert net.redemptions == [], "no person, so nothing to redeem"
        assert TOKEN not in repr(net.calls)


@pytest.mark.parametrize("leg,fragment,drive", LEGS, ids=[l[0] for l in LEGS])
@pytest.mark.parametrize("cause,status", [("not_found", 404), ("already_redeemed", 409),
                                           ("launcher_mismatch", 404)])
def test_a_vault_refusal_fails_the_step_on_every_leg_and_nothing_is_sent(
        net, leg, fragment, drive, cause, status):
    """THE TRAP: several legs catch ``Exception`` and degrade to a fallback answer. A vault
    refusal absorbed there is the silent service-identity fallback."""
    net.script = [(status, {"detail": {"error": cause, "message": "m"}})]
    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        drive(_Ctx(), ALICE)
    assert exc.value.cause == cause
    assert net.outbound(fragment) == [], "the call must not go out under any other identity"


def test_two_calls_of_one_leg_use_two_call_ids(net):
    ctx = _Ctx()
    _drive_fill_slots(ctx, ALICE)
    _drive_fill_slots(ctx, ALICE)
    ids = [r["json"]["call_id"] for r in net.redemptions]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_the_enumerator_refusal_survives_a_consumer_that_swallows_it(net):
    """``slot_disposition`` wraps the enumerator in ``except Exception`` and turns it into a
    no-provider ask. The refusal is also recorded, and the step re-raises it afterwards."""
    net.script = [(404, {"detail": {"error": "not_found", "message": "m"}})]
    enum = ds._make_enumerator(_Ctx(), user_email=ALICE)
    try:
        enum("urn:cost:RateTable")
    except Exception:  # noqa: BLE001 -- exactly what the consumer does
        pass
    with pytest.raises(ds.CallerIdentityUnavailable):
        ds._raise_if_identity_failed(enum)


def test_every_enumerator_is_checked_after_its_consumer_returns():
    tree = ast.parse((_ROOT / "src/iagent/defs/dynamic_supervisor.py").read_text(encoding="utf-8"))
    made = checked = 0
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            made += n.func.id == "_make_enumerator"
            checked += n.func.id == "_raise_if_identity_failed"
    assert made >= 2 and checked == made


# ── awaiting_reauth is a pause; not_found ends it ────────────────────────────────────

def test_the_supervisor_polls_through_awaiting_reauth_then_proceeds(net, monkeypatch):
    paused = (409, {"detail": {"error": "awaiting_reauth", "message": "m"}})
    net.script = [paused, paused, paused, (200, {"token": TOKEN, "subject": ALICE})]
    sleeps = []
    monkeypatch.setattr(ds.time, "sleep", sleeps.append)
    monkeypatch.setenv("IDENTITY_REAUTH_POLL_SECONDS", "7")
    assert ds._redeem_caller_token(_Ctx(), ALICE, "dispatch") == TOKEN
    assert sleeps == [7.0, 7.0, 7.0]
    ids = [r["json"]["call_id"] for r in net.redemptions]
    assert len(ids) == 4 and len(set(ids)) == 4, "each ask is a fresh call id"


def test_the_poll_default_is_ten_seconds_and_has_no_timer_of_its_own(net, monkeypatch):
    paused = (409, {"detail": {"error": "awaiting_reauth", "message": "m"}})
    net.script = [paused] * 200 + [(200, {"token": TOKEN, "subject": ALICE})]
    sleeps = []
    monkeypatch.setattr(ds.time, "sleep", sleeps.append)
    monkeypatch.delenv("IDENTITY_REAUTH_POLL_SECONDS", raising=False)
    assert ds._redeem_caller_token(_Ctx(), ALICE, "plan") == TOKEN
    assert len(sleeps) == 200 and set(sleeps) == {10.0}, "it waits as long as the run does"


def test_polling_stops_at_not_found_and_says_so(net, monkeypatch, caplog):
    paused = (409, {"detail": {"error": "awaiting_reauth", "message": "m"}})
    gone = (404, {"detail": {"error": "not_found", "message": "m"}})
    net.script = [paused, paused, gone]
    sleeps = []
    monkeypatch.setattr(ds.time, "sleep", sleeps.append)
    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        ds._redeem_caller_token(_Ctx(), ALICE, "dispatch")
    assert exc.value.cause == "not_found" and len(sleeps) == 2


# ── nothing identifying escapes into a log ───────────────────────────────────────────

@pytest.mark.parametrize("leg,fragment,drive", LEGS, ids=[l[0] for l in LEGS])
def test_no_token_reaches_a_log_at_debug_on_any_path(net, caplog, leg, fragment, drive):
    with caplog.at_level(logging.DEBUG):
        drive(_Ctx(), ALICE)
        net.script = [(409, {"detail": {"error": "awaiting_reauth", "message": "m"}}),
                      (404, {"detail": {"error": "not_found", "message": "m"}})]
        with pytest.raises(ds.CallerIdentityUnavailable):
            drive(_Ctx(), ALICE)
    assert TOKEN not in caplog.text and SERVICE_TOKEN not in caplog.text


# ── the helper's contract ────────────────────────────────────────────────────────────

def test_the_gate_takes_a_config_or_the_email_itself():
    assert ds._run_has_a_person(_config(ALICE)) and ds._run_has_a_person(ALICE)
    assert not ds._run_has_a_person(_config("")) and not ds._run_has_a_person("svc:x")
    assert not ds._run_has_a_person(None)


def test_no_slot_survives_in_the_supervisor():
    src = (_ROOT / "src/iagent/defs/dynamic_supervisor.py").read_text(encoding="utf-8")
    assert '"slot"' not in src and "no_slot" not in src and "task_(\\d+)" not in src
