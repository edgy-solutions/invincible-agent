"""Every read through the broker carries a principal, in the TICKET and in the QUERY TAG, and
the two agree (ADR-0064 step 2: "every read is attributed"; an unattributed read is a defect).

PINNED SOURCES (derived, not typed here):
  * "#6" is dag-tools#6 (`lane/01-gateway-verified-identity`, merged), the gateway's verified
    `on_behalf_of` with posture `observe` by default. Not invincible-agent#6.
  * the TAG: `dag_tools.audit.tag` (principal grammar `<kind>:<value>`, kinds `KINDS`, JSON key
    `principal`) written by `dag_tools.resources.warehouse.TaggedWarehouseResource`.
  * the TICKET: the gateway's `/authorize` hands the broker `subject`
    (`dag_tools.domain_broker.main.ResolveRequest.subject`), the identity the credential is
    minted for. The returned ticket carries no principal field of its own.

THE CODE LIVES IN dag-tools, not here. The version this repo pins (edgy-dag-tools 0.11.0) predates
the tag module and the tagged warehouse resource, so every arm below is a STRICT xfail while that is
true, and the body is run against a dag-tools checkout (PYTHONPATH) to prove it. When the pin moves
to a release that carries them the xfail goes XPASS and the strict marker FAILS the run: remove the
marker then, which turns the seal on. Nothing in dag-tools is edited from here. Fixtures are
synthetic: no real database, schema, table, program or level names (ADR-0064's standing rule).

Arms:
  tag      a pipeline read and an on-behalf-of read each put a decodable principal of a known
           kind on the query; a resource with no principal REFUSES instead of sending;
  ticket   a gateway authorize that names a person hands the broker that person; one that names
           nobody hands the broker an identity too: today it hands None (strict xfail on the
           code, with a packet);
  agree    the principal's value in the tag is the ticket's subject for the same read.
  identity the ticket the broker mints and the gateway relays carries `ticket_id`, `issued_at` and
           `as_of` (dag-tools 62581a65, #31: `dag_tools.domain_broker.ticket_identity`, stamped at
           `resolve_asset`; the names are `TicketIdentity.fields()`'s, read from that code). The
           gateway's TICKET_ISSUED line names the ticket id against the principal it minted for,
           and that principal is the tag's. `as_of` is the data's version and `issued_at` the
           time we looked: never the same field, and an absent as_of is None, never the clock.
"""
from __future__ import annotations

import importlib.util
import time
from types import SimpleNamespace

import pytest


def _present(dotted: str) -> bool:
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ValueError):
        return False


_HAVE_TAG = _present("dag_tools.audit.tag") and _present("dag_tools.resources.warehouse")
_HAVE_GATEWAY = _present("dag_tools.central_gateway.identity")
_HAVE_IDENTITY = _present("dag_tools.domain_broker.ticket_identity")

_PIN = ("the pinned edgy-dag-tools predates dag_tools.audit.tag / the tagged warehouse resource / "
        "the gateway identity module; the body is proven against a dag-tools checkout")
needs_tag = pytest.mark.xfail(condition=not _HAVE_TAG, strict=True, reason=_PIN)
needs_gateway = pytest.mark.xfail(condition=not _HAVE_GATEWAY, strict=True, reason=_PIN)
needs_identity = pytest.mark.xfail(condition=not _HAVE_IDENTITY, strict=True, reason=(
    "the pinned edgy-dag-tools predates dag_tools.domain_broker.ticket_identity (dag-tools#31); "
    "the body is proven against a dag-tools checkout"))

PIPE = "synthetic-pipeline"
PERSON = "person-1@example.test"


# --------------------------------------------------------------------------- the tag carrier
def _resource(**kw):
    from dag_tools.resources.warehouse import TaggedWarehouseResource
    return TaggedWarehouseResource(tag_placement="comment", **kw)


def _tag_on_the_wire(plan) -> str:
    """The tag as the WAREHOUSE would receive it: read out of the query step's own text, never
    from `plan.tag` (the plan's say-so is what is being checked)."""
    from dag_tools.audit.warehouse import COMMENT_CLOSE, COMMENT_OPEN
    sql = plan.query.sql
    assert sql.startswith(COMMENT_OPEN), f"the query step carries no tag comment: {sql[:40]!r}"
    return sql[len(COMMENT_OPEN):sql.index(COMMENT_CLOSE)].strip()


def _principal_on_the_wire(plan):
    from dag_tools.audit.tag import KINDS, decode, parse_principal
    attribution = decode(_tag_on_the_wire(plan))
    assert attribution is not None, "the tag on the wire does not decode: the read is unattributed"
    kind, value = parse_principal(attribution.principal)
    assert kind in KINDS and value, f"principal {attribution.principal!r} is not a known shape"
    return attribution.principal, kind, value


@needs_tag
def test_a_pipeline_read_carries_the_pipeline_principal_in_the_query_tag():
    from dag_tools.audit.tag import PIPELINE, pipeline_principal
    principal, kind, value = _principal_on_the_wire(_resource(pipeline_name=PIPE).plan("SELECT 1"))
    assert (principal, kind, value) == (pipeline_principal(PIPE), PIPELINE, PIPE)


@needs_tag
def test_an_on_behalf_of_read_carries_the_verified_caller_in_the_query_tag():
    from dag_tools.audit.tag import ON_BEHALF_OF, on_behalf_of_principal
    bound = _resource(pipeline_name=PIPE).for_user(PERSON)
    principal, kind, value = _principal_on_the_wire(bound.plan("SELECT 1"))
    assert (principal, kind, value) == (on_behalf_of_principal(PERSON), ON_BEHALF_OF, PERSON)


@needs_tag
def test_a_resource_with_no_principal_refuses_rather_than_sends_an_unattributed_read():
    from dag_tools.audit.warehouse import UntaggedQuery
    with pytest.raises(UntaggedQuery):
        _resource().plan("SELECT 1")
    with pytest.raises(UntaggedQuery):
        _resource().fetch_rows("SELECT 1")


# --------------------------------------------------------------------------- the ticket carrier
def _gateway_world(monkeypatch, broker_reply=None):
    """The real `/authorize` route, observe posture (the default), fake Redis/Topaz/broker.

    `broker_reply(json) -> awaitable ticket` stands in for the broker's resolve door; the default
    is a fixed synthetic body."""
    import sys
    import types
    if not _present("redis"):  # the [broker] extra: the route never opens it (no lifespan here)
        pkg, sub = types.ModuleType("redis"), types.ModuleType("redis.asyncio")
        sub.Redis, sub.from_url = type("Redis", (), {}), lambda *a, **k: None
        pkg.asyncio = sub
        monkeypatch.setitem(sys.modules, "redis", pkg)
        monkeypatch.setitem(sys.modules, "redis.asyncio", sub)
    from dag_tools.central_gateway import main as gateway
    for k in ("GATEWAY_IDENTITY_POSTURE", "GATEWAY_JWT_ISSUER", "GATEWAY_JWKS_URL",
              "GATEWAY_JWT_PUBLIC_KEY", "KEYCLOAK_PUBLIC_KEY", "USER_ENTITLEMENT_CLAIM"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(gateway, "DENIED_USER_SUBS", set())
    sent = SimpleNamespace(broker=[])

    class _Redis:
        async def get(self, key):
            return "http://broker.invalid"

    class _Resp:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, ""

        def json(self):
            return self._b

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            if "/authz/is" in url:
                return _Resp(200, {"decisions": [{"is": True}]})
            sent.broker.append(json)
            if broker_reply is not None:
                return _Resp(200, await broker_reply(json))
            return _Resp(200, {"source_type": "synthetic", "physical_uri": "synthetic://x"})

    monkeypatch.setattr(gateway, "redis_client", _Redis())
    monkeypatch.setattr(gateway.httpx, "AsyncClient", lambda *a, **k: _Client())
    from fastapi.testclient import TestClient
    return sent, TestClient(gateway.app)


def _token(email):
    jwt = pytest.importorskip("jwt")
    return jwt.encode({"sub": "kc-1", "email": email, "iss": "https://idp.example/realms/mesh",
                       "exp": int(time.time()) + 300}, "unverified-under-observe", algorithm="HS256")


_URN = "urn:synthetic:dataset:one"


def _authorize(client, caller_email, **headers):
    return client.post(f"/api/v1/assets/{_URN}/authorize",
                       headers={"Authorization": f"Bearer {_token(caller_email)}", **headers})


@needs_gateway
def test_an_authorize_naming_a_person_hands_the_broker_that_person(monkeypatch):
    sent, client = _gateway_world(monkeypatch)
    r = _authorize(client, "svc-reader@example.test", on_behalf_of=PERSON)
    assert r.status_code == 200, r.text
    assert sent.broker[0]["subject"] == PERSON


@pytest.mark.xfail(strict=True, reason=(
    "observe posture: an authorize naming nobody hands the broker subject=None, so the ticket is "
    "minted for no principal. Packet to dag-tools lane/01; not fixed here."))
def test_an_authorize_naming_nobody_still_hands_the_broker_a_principal(monkeypatch):
    sent, client = _gateway_world(monkeypatch)
    r = _authorize(client, "svc-reader@example.test")
    assert r.status_code == 200, r.text
    assert sent.broker[0]["subject"], "the ticket was minted for no principal"


# --------------------------------------------------------------------------- the two agree
@needs_tag
@needs_gateway
def test_the_tags_principal_value_is_the_tickets_subject_for_the_same_read(monkeypatch):
    sent, client = _gateway_world(monkeypatch)
    assert _authorize(client, "svc-reader@example.test", on_behalf_of=PERSON).status_code == 200
    subject = sent.broker[0]["subject"]
    _, _kind, value = _principal_on_the_wire(
        _resource(pipeline_name=PIPE).for_user(subject).plan("SELECT 1"))
    assert value == subject == PERSON


# --------------------------------------------------------------------------- the ticket's identity
_ADVERTISED_VERSION = "synthetic-version-7"
# Advertised under `snapshot_id`, not `as_of`: the stamp must be what puts `as_of` on the ticket,
# else a producer's own `as_of` key would make the field look stamped when it is not.


def _real_broker(monkeypatch, **coords):
    """The broker's real `resolve_asset` (the one seam every ticket leaves through), with only the
    coordinate resolution replaced by a synthetic ticket. Returns the `broker_reply` for the world."""
    from dag_tools.domain_broker import main as broker

    async def _synthetic(request):
        return {"source_type": "synthetic", "physical_uri": "synthetic://x", **coords}

    monkeypatch.setattr(broker, "_resolve_ticket", _synthetic)

    async def reply(body):
        return await broker.resolve_asset(broker.ResolveRequest(**body))

    return reply


def _issued_line(caplog) -> dict:
    """The gateway's TICKET_ISSUED line, parsed to its key=value pairs."""
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("TICKET_ISSUED")]
    assert len(lines) == 1, f"expected one TICKET_ISSUED line, got {lines}"
    return dict(p.split("=", 1) for p in lines[0].split()[1:])


@needs_identity
@needs_gateway
@pytest.mark.parametrize("field", ["ticket_id", "issued_at", "as_of"])
def test_a_brokered_ticket_the_gateway_relays_carries_the_identity_field(monkeypatch, field):
    sent, client = _gateway_world(monkeypatch, _real_broker(monkeypatch, snapshot_id=_ADVERTISED_VERSION))
    r = _authorize(client, "svc-reader@example.test", on_behalf_of=PERSON)
    assert r.status_code == 200, r.text
    ticket = r.json()
    assert field in ticket, f"the relayed ticket has no `{field}`: {sorted(ticket)}"
    assert ticket[field], f"`{field}` is empty"


@needs_identity
@needs_gateway
def test_the_identity_fields_say_which_read_when_and_over_what_version(monkeypatch):
    from datetime import datetime
    sent, client = _gateway_world(monkeypatch, _real_broker(monkeypatch, snapshot_id=_ADVERTISED_VERSION))
    first = _authorize(client, "svc-reader@example.test", on_behalf_of=PERSON).json()
    second = _authorize(client, "svc-reader@example.test", on_behalf_of=PERSON).json()
    assert first["ticket_id"] != second["ticket_id"], "two reads share a ticket id"
    assert datetime.fromisoformat(first["issued_at"]).utcoffset() is not None
    assert first["as_of"] == _ADVERTISED_VERSION  # carried as the source wrote it
    assert first["as_of"] != first["issued_at"]  # the data's version is not the clock


@needs_identity
@needs_gateway
def test_an_absent_as_of_is_none_never_the_issue_time(monkeypatch):
    sent, client = _gateway_world(monkeypatch, _real_broker(monkeypatch))
    ticket = _authorize(client, "svc-reader@example.test", on_behalf_of=PERSON).json()
    assert "as_of" in ticket and ticket["as_of"] is None, ticket.get("as_of")
    assert ticket["issued_at"], "the issue time is still stamped"


@needs_identity
@needs_tag
@needs_gateway
def test_the_principal_the_ticket_is_minted_for_is_the_tags_principal_for_the_same_read(
        monkeypatch, caplog):
    """The ticket carries no principal field; the principal it is minted for is the `subject` the
    gateway handed the broker, and the gateway's TICKET_ISSUED line names that subject against this
    ticket's id. That, the broker's subject and the query tag's principal value are one person."""
    import logging
    sent, client = _gateway_world(monkeypatch, _real_broker(monkeypatch, snapshot_id=_ADVERTISED_VERSION))
    with caplog.at_level(logging.INFO):
        r = _authorize(client, "svc-reader@example.test", on_behalf_of=PERSON)
    assert r.status_code == 200, r.text
    issued = _issued_line(caplog)
    assert issued["ticket_id"] == r.json()["ticket_id"], "the line names another ticket"
    _, _kind, tag_value = _principal_on_the_wire(
        _resource(pipeline_name=PIPE).for_user(sent.broker[0]["subject"]).plan("SELECT 1"))
    assert issued["subject"] == sent.broker[0]["subject"] == tag_value == PERSON
