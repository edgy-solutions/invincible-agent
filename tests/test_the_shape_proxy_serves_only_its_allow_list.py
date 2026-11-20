"""ADR-0068 s8: the BFF's `/electric/shape` proxy streams only the tables a row of
`policy/electric_shapes.yaml` names, and never the task table, whatever the client sends.

Why: a shape's WHERE cannot evaluate a label, so a streamed task would bypass the read-time match
(`GET /me/queue`, `GET /me/needs_you`). These seals do not depend on any UI build.

The control is the same proxy, the same caller and the same upstream double serving the two listed
tables with their server-injected WHERE: the refusals differ from it only in the table asked for.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

import sys

for _p in (str(Path(__file__).resolve().parents[1] / "policy" / "sync"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import iagent.gateway as gw  # noqa: E402
from iagent import electric_shapes as es  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
_SHIPPED = _REPO / "policy" / "electric_shapes.yaml"
_ROW = {"granted_by": "architect", "reason": "r", "ratified_by": "owner"}


class _User:
    id = "11111111-1111-4111-8111-111111111111"
    authz_id = "alice@example.com"
    email = "alice@example.com"


class _Resp:
    headers: dict = {}
    content = b"[]"
    status_code = 200


@pytest.fixture
def upstream(monkeypatch):
    """The upstream double: records every request it is sent."""
    calls: list[dict] = []

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, url, params=None, **k):
            calls.append(dict(params or {}))
            return _Resp()

    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    monkeypatch.setenv(es.ELECTRIC_SHAPES_FILE_ENV, str(_SHIPPED))
    return calls


def _ask(items):
    class _Req:
        class query_params:
            @staticmethod
            def multi_items():
                return list(items)

    return asyncio.run(gw.electric_shape_proxy(_Req(), _User()))


def _refusal(items) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        _ask(items)
    return e.value


# -- control: what is on the list still streams, with the server's WHERE -----------------------

def test_control_the_listed_tables_still_stream_with_their_where(upstream):
    _ask([("table", "answer_artifact_projection")])
    _ask([("table", "ingest_status_projection")])
    assert upstream[0]["where"] == "produced_for_user_id = '11111111-1111-4111-8111-111111111111' AND archived_at IS NULL"
    assert upstream[1]["where"] == ("(submitted_by = 'alice@example.com' "
                                    "OR on_behalf_of = 'alice@example.com')")


def test_control_a_client_where_is_still_ignored(upstream):
    _ask([("table", "answer_artifact_projection"), ("where", "1=1"), ("WHERE", "true")])
    assert upstream[0]["where"] == "produced_for_user_id = '11111111-1111-4111-8111-111111111111' AND archived_at IS NULL"


def test_control_no_table_defaults_to_the_answers(upstream):
    _ask([])
    assert upstream[0]["table"] == "answer_artifact_projection"


# -- the task table is never served, whatever the client sends --------------------------------

_VARIANTS = [
    [("table", "human_task_projection")],
    [("table", "HUMAN_TASK_PROJECTION")],
    [("table", "human_task_projection ")],
    [("table", " human_task_projection")],
    [("table", "public.human_task_projection")],
    [("table", '"human_task_projection"')],
    [("table", "human_task_projection\x00")],
    [("table", "human_task_projection"), ("where", "true")],
    [("table", "answer_artifact_projection"), ("table", "human_task_projection")],
]


@pytest.mark.parametrize("items", _VARIANTS)
def test_no_shape_request_for_the_task_table_is_served(upstream, items):
    e = _refusal(items)
    assert e.status_code == 403
    assert e.detail["refusal"]["policy_id"] == "electric_shapes"
    assert upstream == []


def test_a_stray_upper_case_table_key_never_carries_the_task_table_upstream(upstream):
    # `TABLE=` is an unrelated param to the proxy; the table served is the default one, and the
    # stray param must not make the upstream stream the task table.
    _ask([("TABLE", "human_task_projection")])
    assert upstream[-1]["table"] == "answer_artifact_projection"


@pytest.mark.parametrize("table", ["ANSWER_ARTIFACT_PROJECTION", "Answer_Artifact_Projection",
                                   "answer_artifact_projection ", "public.answer_artifact_projection",
                                   '"answer_artifact_projection"', "INGEST_STATUS_PROJECTION"])
def test_a_listed_table_is_matched_exactly_not_folded_trimmed_or_qualified(upstream, table):
    # the refusal must come from the ALLOW-LIST (not only from the proxy's own filter branches)
    e = _refusal([("table", table)])
    assert e.status_code == 403
    assert e.detail["refusal"]["missing_binding"] == f"electric_shape({table})"
    assert upstream == []


@pytest.mark.parametrize("table", ["human_task_projection", "routing_fault", "no_such_table",
                                   "pg_authid"])
def test_a_refusal_names_the_policy_and_the_binding_and_never_reaches_upstream(upstream, table):
    e = _refusal([("table", table)])
    assert e.status_code == 403
    r = e.detail["refusal"]
    assert r["policy_id"] == "electric_shapes"
    assert r["missing_binding"] == f"electric_shape({table})"
    assert upstream == []


def test_a_table_the_list_names_but_the_proxy_cannot_filter_is_refused(upstream, tmp_path,
                                                                       monkeypatch):
    # a row is permission, not a filter: re-listing the task table opens nothing
    f = tmp_path / "es.yaml"
    f.write_text(yaml.safe_dump({"electric_shapes": [
        {"table": "human_task_projection", **_ROW}, {"table": "routing_fault", **_ROW}]}))
    monkeypatch.setenv(es.ELECTRIC_SHAPES_FILE_ENV, str(f))
    for t in ("human_task_projection", "routing_fault"):
        e = _refusal([("table", t)])
        assert e.detail["refusal"]["missing_binding"] == f"electric_shape_filter({t})"
    assert upstream == []


# -- deny by default --------------------------------------------------------------------------

def test_an_absent_file_serves_nothing(upstream, tmp_path, monkeypatch):
    monkeypatch.setenv(es.ELECTRIC_SHAPES_FILE_ENV, str(tmp_path / "missing.yaml"))
    assert _refusal([("table", "answer_artifact_projection")]).status_code == 403
    assert upstream == []


def test_an_empty_list_serves_nothing(upstream, tmp_path, monkeypatch):
    f = tmp_path / "es.yaml"
    f.write_text("electric_shapes: []\n")
    monkeypatch.setenv(es.ELECTRIC_SHAPES_FILE_ENV, str(f))
    assert _refusal([("table", "answer_artifact_projection")]).status_code == 403
    assert upstream == []


@pytest.mark.parametrize("text", ["electric_shapes: [unclosed", "electric_shapes: nope\n",
                                  "electric_shapes: [1, 2]\n", "- a\n- b\n"])
def test_an_unreadable_file_is_503_never_a_served_shape(upstream, tmp_path, monkeypatch, text):
    f = tmp_path / "es.yaml"
    f.write_text(text)
    monkeypatch.setenv(es.ELECTRIC_SHAPES_FILE_ENV, str(f))
    e = _refusal([("table", "answer_artifact_projection")])
    assert e.status_code == 503 and e.detail["error"] == "authorization_unavailable"
    assert upstream == []


# -- the shipped file ------------------------------------------------------------------------

def test_the_shipped_list_names_exactly_the_two_streamed_tables():
    rows = yaml.safe_load(_SHIPPED.read_text(encoding="utf-8"))["electric_shapes"]
    assert sorted(r["table"] for r in rows) == ["answer_artifact_projection",
                                                "ingest_status_projection"]


def test_the_shipped_file_validates():
    from validate_policy import electric_shapes_errors
    raw = yaml.safe_load(_SHIPPED.read_text(encoding="utf-8"))
    users = yaml.safe_load((_REPO / "policy" / "users.yaml").read_text(encoding="utf-8"))
    assert electric_shapes_errors(raw, users.get("users") or []) == []


def test_the_grantor_map_names_the_family():
    g = yaml.safe_load(
        (_REPO / "policy" / "grantors" / "electric_shapes.yaml").read_text(encoding="utf-8"))
    assert g["family"] == "electric_shapes" and g["rail_file"] == "policy/electric_shapes.yaml"


# -- the validator ----------------------------------------------------------------------------

def _v(rows=None, raw=None, users=()):
    from validate_policy import electric_shapes_errors
    return electric_shapes_errors(raw if raw is not None else {"electric_shapes": rows}, list(users))


def _row(**kw):
    r = {"table": "t_one", **_ROW}
    r.update(kw)
    return r


def test_validator_accepts_a_good_row_and_an_empty_list():
    assert _v([_row()]) == [] and _v([]) == []


@pytest.mark.parametrize("bad", [
    _row(table="public.t"), _row(table='"t"'), _row(table="t "), _row(table=""), _row(table=3),
    _row(granted_by=""), _row(reason=" "), _row(ratified_by=None), _row(extra="x"),
])
def test_validator_refuses_a_bad_row(bad):
    assert _v([bad])


def test_validator_refuses_a_duplicate_table_and_a_non_mapping_row():
    assert any("more than once" in m for m in _v([_row(), _row()]))
    assert _v(["x"])


def test_validator_refuses_an_identity_as_ratifier_and_a_bad_top_level():
    assert any("seat" in m for m in _v([_row(ratified_by="a@b.c")], users=[{"id": "a@b.c"}]))
    assert _v(raw={"other": []}) and _v(raw={"electric_shapes": "x"}) and _v(raw=[])


# -- the PARAMETERS: an allow-list, not a deny-list (the Electric secret, 0.4.91) --------------------
#
# Off-list keys are DROPPED, not answered 400 (decision recorded in the PR body, "Open questions"):
# @electric-sql/client's ShapeStream adds protocol params across versions (`cache-buster`,
# `expired_handle`, `log`, `live_sse`), and a 400 on a new one would break the UI's real request.
# Dropping loses nothing: the dropped key never reaches Electric, which is what these seals assert,
# on the RECORDED upstream request.

_SERVER_SECRET = "server-side-secret-for-the-test"
# What @electric-sql/client's ShapeStream really sends (cortex-ui src/lib/electric.ts: `table`, and
# `columns` in summaries mode; the rest are the client's protocol params).
_UI_REQUEST = [("table", "answer_artifact_projection"), ("columns", "id,created_at"),
               ("offset", "-1"), ("handle", "h-1"), ("live", "true"), ("cursor", "7")]
_OFF_LIST = [("where", "1=1"), ("WHERE", "true"), ("replica", "full"), ("secret", "client-secret"),
             ("api_secret", "client-secret"), ("SECRET", "client-secret"), ("params", "{}"),
             ("subset__where", "true"), ("unknown_param", "x"), ("TABLE", "human_task_projection")]


# The EXACT set the proxy may forward, stated here on purpose: the seals above read the live constant, so
# widening the constant alone would pass them (the instrument would share a surface with its subject).
# Widening the list is a change to THIS test too, on purpose.
_PINNED_PARAMS = frozenset({
    "table", "columns", "offset", "handle", "live", "cursor", "expired_handle", "log",
    "live_sse", "experimental_live_sse", "cache-buster",
})


def test_the_forwarded_parameter_set_is_exactly_the_pinned_literal():
    assert gw._ELECTRIC_FORWARD_PARAMS == _PINNED_PARAMS


def _allowed_values():
    # one value per listed key, the key set READ from the proxy's own constant (never restated)
    vals = {"table": "answer_artifact_projection", "columns": "id", "offset": "-1"}
    return [(k, vals.get(k, "v")) for k in sorted(gw._ELECTRIC_FORWARD_PARAMS)]


def test_control_every_listed_parameter_reaches_upstream_with_its_value(upstream):
    _ask(_allowed_values())
    sent = upstream[0]
    for k, v in _allowed_values():
        assert sent[k] == v, k


def test_control_the_uis_real_request_is_served_unchanged(upstream, monkeypatch):
    monkeypatch.setenv(gw._ELECTRIC_SHAPE_SECRET_ENV, _SERVER_SECRET)
    _ask(_UI_REQUEST)
    sent = upstream[0]
    assert {k: sent[k] for k, _ in _UI_REQUEST} == dict(_UI_REQUEST)


@pytest.mark.parametrize("pair", _OFF_LIST)
def test_no_off_list_parameter_reaches_upstream(upstream, monkeypatch, pair):
    monkeypatch.setenv(gw._ELECTRIC_SHAPE_SECRET_ENV, _SERVER_SECRET)
    _ask([("table", "answer_artifact_projection"), pair])
    sent = upstream[0]
    # every key sent upstream is a listed one, or the two the SERVER sets (`where`, `secret`)
    assert set(sent) <= _PINNED_PARAMS | {"where", "secret"}      # a literal, not the live constant
    assert pair not in sent.items()                                # the client's own pair never rides in
    assert sent["where"] == "produced_for_user_id = '11111111-1111-4111-8111-111111111111' AND archived_at IS NULL"
    assert sent["secret"] == _SERVER_SECRET            # never the client's
    assert sent["table"] == "answer_artifact_projection"


def test_a_client_secret_never_reaches_upstream_whether_or_not_the_server_has_one(upstream, monkeypatch):
    monkeypatch.delenv(gw._ELECTRIC_SHAPE_SECRET_ENV, raising=False)
    _ask([("secret", "client-secret"), ("api_secret", "client-secret")])
    assert "secret" not in upstream[0] and "api_secret" not in upstream[0]


def test_control_the_servers_own_secret_reaches_upstream(upstream, monkeypatch):
    monkeypatch.setenv(gw._ELECTRIC_SHAPE_SECRET_ENV, _SERVER_SECRET)
    _ask([("table", "ingest_status_projection")])
    assert upstream[0]["secret"] == _SERVER_SECRET


def test_the_table_is_forwarded_only_after_the_table_allow_list(upstream):
    # `table` is on the parameter list, and still refused when the table list does not name it
    e = _refusal([("table", "human_task_projection"), ("offset", "-1")])
    assert e.status_code == 403 and upstream == []


# -- the secret must not reach a log line on the BFF side ------------------------------------------------
# httpx logs "HTTP Request: GET <full url>" at INFO and the upstream URL carries `secret=`. Nothing leaked
# only because boot-time basicConfig() leaves the root at WARNING; the loggers are now pinned explicitly.

@pytest.mark.parametrize("name", ["httpx", "httpcore"])
def test_the_http_client_loggers_are_pinned_to_warning_whatever_the_root_does(name, caplog):
    import logging
    assert logging.getLogger(name).level >= logging.WARNING        # the logger's OWN level, not inherited
    with caplog.at_level(logging.DEBUG):                           # a root at DEBUG, the accident undone
        logging.getLogger(name).info("HTTP Request: GET http://e/v1/shape?secret=abc")
    assert "secret=abc" not in caplog.text


def test_a_failed_upstream_call_logs_the_class_not_the_url(monkeypatch, caplog):
    import logging
    import httpx

    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, **k):
            raise httpx.ConnectError(f"failed to reach {url}?secret={params['secret']}")

    monkeypatch.setattr(gw.httpx, "AsyncClient", _Boom)
    monkeypatch.setenv(es.ELECTRIC_SHAPES_FILE_ENV, str(_SHIPPED))
    monkeypatch.setenv(gw._ELECTRIC_SHAPE_SECRET_ENV, _SERVER_SECRET)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(HTTPException) as e:
            _ask([("table", "answer_artifact_projection")])
    assert e.value.status_code == 502
    assert "ConnectError" in caplog.text                           # control: the line arrived
    assert _SERVER_SECRET not in caplog.text
