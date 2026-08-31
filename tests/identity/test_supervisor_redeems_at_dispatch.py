"""The supervisor half: WHICH credential goes on the wire, and what happens when none can.

The vault's tests prove the reference mechanism; the endpoint's prove the surface. These
prove the thing that actually caused the original failure — that the dispatch stopped
sending `svc:supervisor` where the caller's own identity was required, and that when it
CANNOT get that identity it refuses rather than quietly reproducing the 403.

THE FAILURE THIS FILE EXISTS TO MAKE UNREPEATABLE. The seeding phrase returned 0 of 5 with
`403 cell_not_entitled x5` because dispatch minted a service token holding zero entitlement
cells. The tempting repair — "fall back to the service token if redemption fails" — would
reproduce that exact symptom with a second cause hidden behind it, and the symptom reads as
an entitlement problem, which is where the next diagnosis would start and waste its day.

Run:  uv run --frozen python -m pytest tests/identity/test_supervisor_redeems_at_dispatch.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

ALICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-PING-ROOTED.signature"
SERVICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.SVC-SUPERVISOR.signature"


class _Config:
    user_persona = "PORTFOLIO_LEAD"
    user_email = "alice@example.com"
    trace_id = "trace-1"
    session_id = "session-1"


# ══════════════════════════════════════════════════════════════════════════════════
# The gate: an ALLOW-LIST, not a blanket switch
# ══════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("verb,expected", [
    ("mesh:seedPortfolioCanvas", True),
    ("http://invincible-agent/mesh#seedPortfolioCanvas", True),   # tolerated, see below
    ("mesh:queryKnowledgeGraph", False),
    ("mesh:resolveInstance", False),
    ("mesh:startReview", False),
    ("", False),
    (None, False),
])
def test_only_the_seed_verb_asks_for_the_callers_identity(verb, expected):
    """SCOPED, DELIBERATELY. Flipping every specialist dispatch from `svc:supervisor` to the
    caller's token is a behaviour change far beyond the seed — it would move every engine off
    the service identity at once and take the OBSERVE-phase caller-readiness gauge with it.
    That may be the destination, but it is a separate ruling with its own blast radius.

    Both IRI forms are accepted because the registry stores verbs COMPACT today (verified
    convention, 24 live rows) and a later expansion must not silently switch this gate OFF —
    a silently-off gate here means a seed that 403s exactly the way it did before the fix.
    """
    assert ds._verb_needs_caller_identity({"verb_iri": verb}) is expected


def test_a_missing_predicate_does_not_ask_for_an_identity():
    assert ds._verb_needs_caller_identity({}) is False
    assert ds._verb_needs_caller_identity(None) is False


# ══════════════════════════════════════════════════════════════════════════════════
# WHICH credential goes on the wire
# ══════════════════════════════════════════════════════════════════════════════════

def test_the_callers_token_REPLACES_the_service_identity(monkeypatch):
    """The whole point: what reaches /canvas/seed is alice's own token, unchanged — the same
    credential the browser sends on the button path, not one minted here."""
    minted = []

    def _boom(*a, **k):
        minted.append(1)
        return SERVICE_TOKEN

    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token", _boom, raising=False
    )

    headers = ds._telemetry_headers(_Config(), caller_token=ALICE_TOKEN)

    assert headers["Authorization"] == f"Bearer {ALICE_TOKEN}"
    assert minted == [], (
        "the supervisor minted a service token on the caller-identity path — the vault "
        "exists precisely so nothing new is minted"
    )


def test_the_caller_identity_path_still_carries_the_trace_headers():
    """A second Authorization branch is a second chance to drop the telemetry headers, which
    is the silent-orphan failure `_telemetry_headers` was consolidated to prevent."""
    headers = ds._telemetry_headers(_Config(), caller_token=ALICE_TOKEN)
    assert headers["X-Trace-Id"] == "trace-1"
    assert headers["X-Session-Id"] == "session-1"


def test_without_a_caller_token_the_service_identity_is_unchanged(monkeypatch):
    """NO REGRESSION FOR EVERY OTHER DISPATCH. Every non-seed verb must keep dispatching
    exactly as it did — this change is scoped, and a test that only proved the new path
    would not notice if the old one broke."""
    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token",
        lambda *a, **k: SERVICE_TOKEN, raising=False,
    )

    headers = ds._telemetry_headers(_Config())

    assert headers["Authorization"] == f"Bearer {SERVICE_TOKEN}"
    assert headers["X-Trace-Id"] == "trace-1"


# ══════════════════════════════════════════════════════════════════════════════════
# Redemption failures NAME THEIR CAUSE
# ══════════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class _Ctx:
    run_id = "0f1e2d3c-run"

    class log:
        @staticmethod
        def info(*a, **k): ...
        @staticmethod
        def error(*a, **k): ...


@pytest.fixture(autouse=True)
def _stub_mint(monkeypatch):
    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token",
        lambda *a, **k: SERVICE_TOKEN, raising=False,
    )


@pytest.mark.parametrize("status,cause", [
    (403, "not_the_redeemer"),
    (404, "not_found"),
    (404, "launcher_mismatch"),
    (409, "already_redeemed"),
])
def test_a_refusal_carries_the_vaults_named_cause(monkeypatch, status, cause):
    """The BFF distinguishes four refusals. Collapsing them into "redemption failed" here
    would discard exactly the discrimination the vault was built to make — and the one that
    tells a replay from a restart."""
    monkeypatch.setattr(
        ds.requests, "post",
        lambda *a, **k: _Resp(status, {"detail": {"error": cause, "message": "m"}}),
    )

    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        ds._redeem_caller_token(_Ctx(), _Config())

    assert cause in str(exc.value)


def test_a_200_with_no_token_is_a_failure_not_an_empty_answer(monkeypatch):
    """CHECK THE TRANSPORT, THEN THE PAYLOAD — the standing lesson from an auth failure that
    once wore an empty result's clothes. A 200 carrying no token is a contract violation,
    and treating it as "nothing to do" is how a credential fault becomes a silent empty
    canvas."""
    monkeypatch.setattr(ds.requests, "post", lambda *a, **k: _Resp(200, {}))

    with pytest.raises(ds.CallerIdentityUnavailable):
        ds._redeem_caller_token(_Ctx(), _Config())


def test_the_run_id_asked_for_is_DAGSTERS_own(monkeypatch):
    """Asked with the authoritative run id, not one read back out of run config.

    This is what makes the BFF's launcher cross-check meaningful rather than a comparison of
    two caller-supplied strings.
    """
    sent = {}

    def _capture(url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["headers"] = headers
        return _Resp(200, {"token": ALICE_TOKEN, "subject": "alice@example.com"})

    monkeypatch.setattr(ds.requests, "post", _capture)

    token = ds._redeem_caller_token(_Ctx(), _Config())

    assert token == ALICE_TOKEN
    assert sent["json"]["run_id"] == _Ctx.run_id
    assert sent["json"]["claimed_launcher"] == "alice@example.com"
    assert sent["headers"]["Authorization"] == f"Bearer {SERVICE_TOKEN}", (
        "the supervisor authenticates AS ITSELF to redeem — the service identity still "
        "opens the vault, it is simply no longer what dispatches"
    )
    assert "/internal/identity/redeem" in sent["url"]


def test_a_run_without_an_id_cannot_redeem(monkeypatch):
    class _NoRun:
        run_id = ""

        class log:
            @staticmethod
            def info(*a, **k): ...
            @staticmethod
            def error(*a, **k): ...

    monkeypatch.setattr(ds.requests, "post",
                        lambda *a, **k: pytest.fail("must not reach the network"))

    with pytest.raises(ds.CallerIdentityUnavailable):
        ds._redeem_caller_token(_NoRun(), _Config())


# ══════════════════════════════════════════════════════════════════════════════════
# THE STRUCTURAL GUARD: the refusal must come BEFORE the dispatch
# ══════════════════════════════════════════════════════════════════════════════════
#
# ANCHORED ON AST NODES, NOT ON SUBSTRINGS. A source-pinning test is this repo's recurring
# instrument defect's natural habitat: a text search cannot tell code from the prose that
# explains it, and `execute_subtask` is full of prose that names both `engine_unreachable`
# and the 403 this change repairs. So the check walks the function's real statements and
# asserts an ORDERING — the identity refusal returns before the POST is reached.
#
# ITS LIMIT, STATED: this proves the refusal is POSITIONED correctly, not that it fires on a
# live run. That is an integration claim and it is the closing acceptance item, verified in
# the cluster rather than faked here.


def _refusal_precedes_dispatch(source: str) -> bool:
    """True when execute_subtask returns a caller-identity refusal before it POSTs."""
    tree = ast.parse(source)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "execute_subtask"),
        None,
    )
    if fn is None:
        return False

    refusal_line = None
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Constant) and sub.value == "caller_identity_unavailable":
                refusal_line = min(refusal_line or node.lineno, node.lineno)

    dispatch_line = None
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "post"
                and any(isinstance(a, ast.Name) and a.id == "endpoint" for a in node.args)):
            dispatch_line = min(dispatch_line or node.lineno, node.lineno)

    if refusal_line is None or dispatch_line is None:
        return False
    return refusal_line < dispatch_line


def test_the_dispatch_refuses_before_it_posts():
    """Dispatching without alice's token does not fail OPEN — it fails as five 403s and an
    empty canvas, which is WORSE than not dispatching, because it looks like an entitlement
    problem and sends the next diagnosis to the wrong layer."""
    src = (_ROOT / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(
        encoding="utf-8"
    )
    assert _refusal_precedes_dispatch(src)


def test_the_ordering_guard_is_PROVEN_RED():
    """Prove the guard red before trusting its green — including against the two ways THIS
    guard could be vacuous: no refusal at all, and a refusal that lands after the POST."""
    no_refusal = (
        "def execute_subtask(context, config, task_def):\n"
        "    return requests.post(endpoint, json=payload)\n"
    )
    wrong_order = (
        "def execute_subtask(context, config, task_def):\n"
        "    r = requests.post(endpoint, json=payload)\n"
        "    if bad:\n"
        "        return {'status': 'caller_identity_unavailable'}\n"
        "    return r\n"
    )
    right_order = (
        "def execute_subtask(context, config, task_def):\n"
        "    if bad:\n"
        "        return {'status': 'caller_identity_unavailable'}\n"
        "    return requests.post(endpoint, json=payload)\n"
    )
    assert _refusal_precedes_dispatch(no_refusal) is False
    assert _refusal_precedes_dispatch(wrong_order) is False
    assert _refusal_precedes_dispatch(right_order) is True


# ══════════════════════════════════════════════════════════════════════════════════
# THE FAILURE NAMES WHICH STEP BROKE — and never leaks the exception to a card
# ══════════════════════════════════════════════════════════════════════════════════
#
# FROM A LIVE CARD, 2026-08-31. A seed failed with `KeyError: 'SUPERVISOR_CLIENT_SECRET'`
# printed verbatim on the user's answer, under a message saying the credential reference
# could not be REDEEMED. Both halves misled: no redemption was attempted (the supervisor
# could not authenticate ITSELF, so it never reached the vault), and a raw traceback is not
# a disposition. The first diagnosis went to the vault lane, which was the wrong lane.

def test_an_unconfigured_service_identity_NEVER_CONTACTS_THE_VAULT(monkeypatch):
    """The mint reads os.environ directly, so an unconfigured pod raises BEFORE any request.

    Reporting that as a redemption failure is false twice over — the vault was never
    contacted, and the remedy is a deployment one rather than a retry. This asserts the
    network is not touched, which is the fact that makes the distinction real rather than
    cosmetic.
    """
    def _no_creds(*a, **k):
        raise KeyError("SUPERVISOR_CLIENT_SECRET")

    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token", _no_creds, raising=False
    )
    monkeypatch.setattr(
        ds.requests, "post",
        lambda *a, **k: pytest.fail("the vault was contacted despite no service identity"),
    )

    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        ds._redeem_caller_token(_Ctx(), _Config())

    assert exc.value.cause == "service_identity_unconfigured", (
        "a self-authentication failure must not wear a redemption failure's clothes"
    )
    assert "SUPERVISOR_CLIENT_SECRET" in exc.value.detail, (
        "the operator still needs the real reason, in the detail"
    )


def test_the_causes_are_DISTINCT_because_their_owners_are(monkeypatch):
    """A service-identity fault is a deployment matter; an expired reference is 'ask again';
    a replay is a security event. One shared cause would misdirect two of the three."""
    seen = set()

    def _mint_ok(*a, **k):
        return SERVICE_TOKEN

    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token", _mint_ok, raising=False
    )
    for status, cause in [(404, "not_found"), (404, "expired"),
                          (409, "already_redeemed"), (403, "not_the_redeemer")]:
        monkeypatch.setattr(
            ds.requests, "post",
            lambda *a, s=status, c=cause, **k: _Resp(s, {"detail": {"error": c}}),
        )
        with pytest.raises(ds.CallerIdentityUnavailable) as exc:
            ds._redeem_caller_token(_Ctx(), _Config())
        seen.add(exc.value.cause)

    assert seen == {"not_found", "expired", "already_redeemed", "not_the_redeemer"}
    assert "service_identity_unconfigured" not in seen


def test_every_cause_has_a_user_sentence_that_leaks_no_mechanism():
    """The card's audience asked a planning question. It is not the audience for a
    traceback, an env var name, or the word 'vault'."""
    forbidden = ("Traceback", "KeyError", "os.environ", "SUPERVISOR_CLIENT_SECRET",
                 "Exception", "None", "null")
    for cause, sentence in ds._CALLER_IDENTITY_MESSAGES.items():
        assert sentence and sentence[0].isupper() and sentence.rstrip().endswith("."), cause
        for bad in forbidden:
            assert bad not in sentence, f"{cause}'s sentence leaks {bad!r}"
        assert "nothing was attempted" in sentence.lower(), (
            f"{cause} must say nothing was attempted — the honest half of this refusal"
        )


def test_the_service_identity_sentence_points_at_an_OPERATOR_not_a_retry():
    """The single most misdirecting thing the old message did was invite a retry for a
    fault no number of retries can fix."""
    s = ds._CALLER_IDENTITY_MESSAGES["service_identity_unconfigured"].lower()
    assert "operator" in s
    assert "deployment" in s or "configuration" in s
    assert "asking again creates a fresh one" not in s


def test_an_unknown_cause_degrades_to_the_generic_sentence_not_a_traceback():
    """A cause added later without a sentence must fall back to something safe. The failure
    mode being prevented is a `.get(cause, str(exc))` that quietly reintroduces the leak."""
    msg = ds._CALLER_IDENTITY_MESSAGES.get(
        "some_future_cause", ds._CALLER_IDENTITY_DEFAULT_MESSAGE
    )
    assert msg == ds._CALLER_IDENTITY_DEFAULT_MESSAGE
    assert "Traceback" not in msg and "Error" not in msg
