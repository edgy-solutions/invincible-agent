"""THE JOIN: what the origin writers WRITE is what the notice read check READS.

Each piece is sealed alone: the origin case (tests/test_an_origin_suggestion_runs_as_a_case.py),
the origin writer (src/iagent/origin_writer.py), the promotion's steward attestation
(promotion_stores.Neo4jIngestGraph.attest_origin), the read check (notice_parts.source_visibility
/ read_notice_parts) and the status read (ingest_status.get_status_for). NOTHING asserted the join
between them: a property renamed on either side left every per-piece test green and silently
withheld (or opened) everything.

This file chains the REAL functions through ONE stateful in-memory graph (`FakeGraph`):

  * writers  -- `Neo4jIngestGraph.create_node / attest_origin / write_fact` (real store class over
    the fake driver + writer) and `origin_writer.write_origin`, all writing through
    `FakeGraph.write_node`, which MERGEs the payload into `nodes[ingest_id]`;
  * reader   -- `notice_parts.read_notice_parts` over a fake driver whose row is BUILT FROM
    `nodes` / `facts` by READING THE RETURN CLAUSE OF `NOTICE_PARTS_CYPHER`: each alias, and the
    node property it reads (`a.<prop> AS <alias>`), is derived from the statement, never typed
    here. A property rename in the cypher is therefore read from the node under its new name, and
    the join fails visibly.

`FakeGraph.write_node` mirrors `Neo4jGraphWriter.write_node`
(agent_fleet/utils/mesh_writers/neo4j_graph.py:237; its statement `_WRITE_NODE`, :127-131, is
`MERGE (n:{label} {key: $id}) SET n += $props`): create-or-update the node at its id, merge the
payload's properties over it, a None value removes the property, outcome "written". (The spec
named iagent_mesh/ as the home; the concrete writer is in this repo, the SDK has only the
Protocol, iagent_mesh/interfaces.py:1118.)

Run: uv run --frozen pytest tests/security/test_steward_origin_case_end_to_end.py -q
"""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
from pathlib import Path
from unittest import mock

import pytest
from iagent_mesh.interfaces import Initiator
from iagent_mesh.write_results import MeshWriteResult

from agent_fleet.ontology_service import notice_parts as np_mod
from src.iagent import origin_writer, promotion, promotion_stores
from src.iagent.promotion_stores import INGEST_FACT_FAMILY, Neo4jIngestGraph

# The case-run harness of the per-piece file: its fixtures and drivers, not a second copy.
from tests.test_an_origin_suggestion_runs_as_a_case import (  # noqa: F401 -- fixtures
    CONFIRM, _real_policy, _run, _suggestion, registered, writer, _emitted)
from tests.test_ingest_status_projection import (
    _SqliteConnCm, _status_columns, ist)

ALICE = "alice@example.com"      # the dropper
BOB = "bob@example.com"          # SUSTAINMENT, member of every program
CAROL = "carol@example.com"
DAVE = "dave@example.com"        # SUSTAINMENT, member of NO program
HEX = "e" * 64
INGEST_ID = "sha256:" + HEX
HEX_F = "f" * 64
INGEST_ID_F = "sha256:" + HEX_F
NOTICE = "PCN-E2E"
NOTICE_F = "PCN-E2E-F"
PARTS = ["5530-182", "5530-183"]
AUDIENCE = "document_promotion:SUSTAINMENT"
GOVERNING = {"ruleset_ref": "task_kind:document_promotion@x", "trust_table_ref": "trust@t"}
#: Consumption table: SUSTAINMENT consumed by {SUSTAINMENT}; FINANCE consumed by {FINANCE}.
TABLE = {"SUSTAINMENT": frozenset({"SUSTAINMENT"}), "FINANCE": frozenset({"FINANCE"})}


def _notice_node(notice_id, ingest_id):
    """A drop-derived notice: the `provenance_*` keys of tests/test_notice_parts_provenance.py's
    `_NOTICE` (PCN26-182 on rev 180), key for key, with this notice's id and ingest_id."""
    return {
        "id": notice_id, "type": "PCN", "needs_review": True, "mfr": "", "pub_date": "",
        "revision": "",
        "provenance_obtained_via": "user-drop",
        "provenance_ingest_id": ingest_id,
        "provenance_ingest_run": f"user-drop:{ingest_id}",
        "provenance_standing": "supervised",
        "provenance_authoritative_source": "unconfirmed-at-intake",
        "provenance_as_of": "unknown",
        "provenance_ingested_at": "2026-10-08T21:41:51Z",
        "provenance_derived_from": "",
    }


# ── the one stateful graph ────────────────────────────────────────────────────────────────────

class FakeGraph:
    """`nodes`: ingest_id -> IngestArtifact property map. `facts`: ingest_id -> PROMOTION edge
    payloads, oldest first. `notices`: notice id -> SustainmentNotice property map."""

    def __init__(self):
        self.nodes: dict = {}
        self.facts: dict = {}
        self.notices: dict = {}
        self.write_node_calls: list = []

    # -- the SDK writer surface the stores use (Neo4jGraphWriter.write_node, see module doc) --
    def write_node(self, initiator, *, label, id, payload=None):
        self.write_node_calls.append((initiator.subject, label, id, dict(payload or {})))
        node = self.nodes.setdefault(id, {INGEST_FACT_FAMILY["node_key"]: id})   # MERGE
        for k, v in dict(payload or {}).items():                                  # SET n += $props
            if v is None:
                node.pop(k, None)
            else:
                node[k] = v
        return MeshWriteResult.written()

    def write_edge(self, initiator, *, identity, payload):
        assert identity.verb == promotion_stores.PROMOTION_VERB
        assert identity.subject == identity.object == identity.key
        self.facts.setdefault(identity.subject, []).append(dict(payload))
        return MeshWriteResult.written()

    # -- the store's own reads, answered from `nodes` by the module's cypher OBJECTS ----------
    def store_driver(self):
        return _StoreDriver(self)

    def store(self, who):
        return Neo4jIngestGraph(driver=self.store_driver(),
                                initiator=Initiator(subject=who, kind="person"),
                                writer_factory=lambda **kw: self)

    # -- the reader's driver -------------------------------------------------------------------
    def notice_driver(self):
        return _NoticeDriver(self)

    def origin_props(self, ingest_id):
        return {k: v for k, v in self.nodes.get(ingest_id, {}).items() if k.startswith("origin_")}


class _Single:
    def __init__(self, row):
        self._row = row

    def single(self):
        return self._row


class _StoreSession:
    def __init__(self, g):
        self.g = g

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        node = self.g.nodes.get(params["ingest_id"])
        if cypher is promotion_stores._NODE_EXISTS_CYPHER:
            return _Single({"n": 1 if node is not None else 0})
        if cypher is promotion_stores._ORIGIN_RUNG_CYPHER:
            return _Single(None if node is None else {"rung": node.get("origin_resolved_by")})
        raise AssertionError(f"the store ran a statement this graph does not model: {cypher!r}")


class _StoreDriver:
    def __init__(self, g):
        self.g = g

    def session(self, **kw):
        return _StoreSession(self.g)


def _split_top_level(text):
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return [c for c in out if c]


def return_items(cypher):
    """[(expression, alias)] from the RETURN clause of the statement itself."""
    clause = cypher.rsplit("RETURN", 1)[1]
    items = []
    for part in _split_top_level(clause):
        expr, sep, alias = part.rpartition(" AS ")
        items.append((expr.strip(), alias.strip()) if sep else (part, part))
    return items


#: alias -> the IngestArtifact property it reads (`a.<prop> AS <alias>`), DERIVED from the cypher.
ARTIFACT_PROP_OF = {alias: m.group(1) for expr, alias in return_items(np_mod.NOTICE_PARTS_CYPHER)
                    if (m := re.fullmatch(r"a\.(\w+)", expr))}
ORIGIN_ALIASES = ("origin_owner_domain", "origin_program", "origin_resolved_by")
#: What the origin writers must write, per alias.
ORIGIN_PROP_OF = {a: ARTIFACT_PROP_OF.get(a) for a in ORIGIN_ALIASES}


def test_the_return_clause_parse_is_positive_controlled():
    """The mapping every arm leans on is READ off the statement: prove the parse found it."""
    aliases = [a for _, a in return_items(np_mod.NOTICE_PARTS_CYPHER)]
    assert aliases == ["notice", "mpns", "dropped_by", "has_artifact", "origin_owner_domain",
                       "origin_program", "origin_resolved_by", "promoted", "promoted_by"], aliases
    assert all(ORIGIN_PROP_OF.values()) and set(ORIGIN_PROP_OF) == set(ORIGIN_ALIASES), \
        ORIGIN_PROP_OF
    assert ARTIFACT_PROP_OF["dropped_by"] == "dropped_by_authz_id"


class _Rec:
    def __init__(self, d):
        self._d = d

    def data(self):
        return dict(self._d)


class _NoticeSession:
    def __init__(self, g):
        self.g = g

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, params):
        assert cypher is np_mod.NOTICE_PARTS_CYPHER, cypher
        notice = self.g.notices.get(params["notice_id"])
        if notice is None:
            return []                               # MATCH (n ...) first: an unknown id, no row
        iid = notice.get("provenance_ingest_id")
        art = self.g.nodes.get(iid)
        facts = self.g.facts.get(iid, [])
        row = {}
        for expr, alias in return_items(np_mod.NOTICE_PARTS_CYPHER):
            if expr == "properties(n)":
                row[alias] = dict(notice)
            elif expr == alias == "mpns":
                row[alias] = list(PARTS)
            elif (m := re.fullmatch(r"a\.(\w+)", expr)):
                row[alias] = None if art is None else art.get(m.group(1))
            elif expr == "a IS NOT NULL":
                row[alias] = art is not None
            elif expr == "count(p) > 0":
                row[alias] = len(facts) > 0
            elif (m := re.fullmatch(r"head\(collect\(p\.(\w+)\)\)", expr)):
                row[alias] = facts[-1].get(m.group(1)) if facts else None
            else:
                raise AssertionError(f"RETURN item {expr!r} AS {alias!r} is not modelled")
        return [_Rec(row)]


class _NoticeDriver:
    def __init__(self, g):
        self.g = g

    def session(self, **kw):
        assert kw.get("default_access_mode") == "READ"
        return _NoticeSession(self.g)


# ── the world, the read, the comparisons ──────────────────────────────────────────────────────

class Program:
    """`can_view_program`: a recording fake answering from a membership dict."""

    def __init__(self, members):
        self.members, self.calls = set(members), []

    def __call__(self, program, caller_id):
        self.calls.append((program, caller_id))
        return (program, caller_id) in self.members


def _world(*, ingest_id=INGEST_ID, notice=NOTICE, dropper=ALICE):
    """A graph holding the drop-derived notice and its IngestArtifact node, the node created by
    the REAL `create_node` as the dropper."""
    g = FakeGraph()
    g.notices[notice] = _notice_node(notice, ingest_id)
    assert g.store(dropper).create_node(
        ingest_id, kind="pdf", sha256=ingest_id.split(":", 1)[1],
        object_ref=f"ingress-user/pdf/{ingest_id.split(':', 1)[1]}/pcn.pdf",
        ingested_at="2026-10-08T21:41:51Z", dropped_by_authz_id=dropper) is True
    return g


def _read(g, notice, caller, domains, program):
    return np_mod.read_notice_parts(
        g.notice_driver(), notice, caller_id=caller, viewer_domains=domains, table=TABLE,
        can_view_program=program)


def _normalised(body, notice):
    return json.loads(json.dumps(body).replace(notice, "<ID>"))


def _assert_unknown(g, notice, caller, domains, program=None):
    """The answer IS the unknown-notice body: byte-for-byte, the echoed id normalised."""
    got = _read(g, notice, caller, domains, program or Program([]))
    unknown = _read(g, "PCN-NO-SUCH", caller, domains, Program([]))
    assert unknown["reason"] == "unknown_notice" and unknown["sources"] == [], unknown
    assert _normalised(got, notice) == _normalised(unknown, "PCN-NO-SUCH"), got


def _assert_visible(g, notice, caller, domains, program):
    got = _read(g, notice, caller, domains, program)
    assert got["status"] == "ok" and [s["mpn"] for s in got["sources"]] == PARTS, got
    return got


def _promote(g, ingest_id, who="bob@example.com"):
    """The promotion's fact, written by the REAL store from `promotion.promotion_fact`."""
    g.store(who).write_fact(ingest_id, promotion.promotion_fact(
        acted_by=who, record_id="dr-e2e", promoted_at=1_000))


async def _accepted_resolution(*, suggested, artifact_id, sid="SG-E2E"):
    ev = _suggestion(sid=sid, dropper=ALICE)
    ev["artifact_id"] = artifact_id
    ev["suggested"] = dict(suggested)
    out, c = await _run(ev, [(CONFIRM, "accepted")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "resolved"), out
    [rec] = _emitted(c)
    return rec


RECORD_ORIGIN = {"owner_domain": "SUSTAINMENT", "program": "prog-x",
                 "obtained_via": "authoritative_source"}


def _write(g, resolution, who="steward@x"):
    return origin_writer.write_origin(
        resolution, graph_writer=g, initiator=Initiator(subject=who, kind="person"),
        dropper_is_program_member=True)


# ── 1. a rejection never widens ───────────────────────────────────────────────────────────────

@pytest.fixture
def status_row():
    """`get_status_for` over a real sqlite WHERE clause (the per-piece file's own harness)."""
    db = sqlite3.connect(":memory:")
    cols = _status_columns()
    db.execute("CREATE TABLE ingest_status_projection (%s)" % ", ".join(f"{c} TEXT" for c in cols))
    vals = {"id": INGEST_ID, "submitted_by": ALICE, "on_behalf_of": None,
            "status": ist.AWAITING_ORIGIN, "origin_suggestion": None}
    db.execute("INSERT INTO ingest_status_projection (%s) VALUES (%s)"
               % (", ".join(vals), ", ".join("?" for _ in vals)), tuple(vals.values()))

    def call(caller):
        with mock.patch.object(ist, "_pg_connect", return_value=_SqliteConnCm(db)):
            return ist.get_status_for(INGEST_ID, caller_id=caller)

    yield call
    db.close()


@pytest.mark.asyncio
async def test_arm1_a_REJECTION_never_widens(registered, writer, status_row):
    g = _world()
    before = list(g.write_node_calls)
    ev = _suggestion(dropper=ALICE)
    ev["artifact_id"] = INGEST_ID
    ev["suggested"] = dict(RECORD_ORIGIN)
    out, c = await _run(ev, [(CONFIRM, "rejected")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "unresolved"), out
    assert _emitted(c) == [] and writer["posts"] == [], "a rejection reached the writer"
    assert g.write_node_calls == before, "a rejection wrote to the graph"
    assert g.origin_props(INGEST_ID) == {}, g.nodes[INGEST_ID]
    # bob (SUSTAINMENT, a member of every program) is a non-dropper: the unknown-notice body.
    prog = Program([("prog-x", BOB)])
    _assert_unknown(g, NOTICE, BOB, ["SUSTAINMENT"], prog)
    got = _assert_visible(g, NOTICE, ALICE, ["SUSTAINMENT"], prog)     # the dropper sees it
    assert "origin" not in got["sources"][0], got["sources"][0]
    assert prog.calls == [], prog.calls
    # the status read: awaiting_origin is the dropper's alone.
    assert status_row(BOB) is None
    row = status_row(ALICE)
    assert row is not None and row["status"] == ist.AWAITING_ORIGIN, row


# ── 2. accepted, not promoted: still the dropper's alone ──────────────────────────────────────

@pytest.mark.asyncio
async def test_arm2_ACCEPTED_but_not_promoted_is_still_dropper_only(registered, writer):
    g = _world()
    res = await _accepted_resolution(suggested=RECORD_ORIGIN, artifact_id=INGEST_ID)
    assert _write(g, res) == {"status": "written", "reason": None}
    # The node carries the origin under the names the cypher READS (derived mapping).
    node = g.nodes[INGEST_ID]
    assert node.get(ORIGIN_PROP_OF["origin_owner_domain"]) == "SUSTAINMENT", node
    assert node.get(ORIGIN_PROP_OF["origin_program"]) == "prog-x", node
    assert node.get(ORIGIN_PROP_OF["origin_resolved_by"]) == "record", node
    prog = Program([("prog-x", BOB)])
    _assert_unknown(g, NOTICE, BOB, ["SUSTAINMENT"], prog)            # no PROMOTION fact yet
    _assert_visible(g, NOTICE, ALICE, ["SUSTAINMENT"], prog)
    assert prog.calls == [], prog.calls


# ── 3. accepted then promoted: the consumer reads it, the non-consumer does not ───────────────

@pytest.mark.asyncio
async def test_arm3_ACCEPTED_then_PROMOTED_the_consumer_reads_it(registered, writer):
    g = _world()
    res = await _accepted_resolution(suggested=RECORD_ORIGIN, artifact_id=INGEST_ID)
    assert _write(g, res)["status"] == "written"
    _promote(g, INGEST_ID)
    members = [("prog-x", BOB)]
    # bob: SUSTAINMENT, a member of prog-x.
    prog = Program(members)
    got = _assert_visible(g, NOTICE, BOB, ["SUSTAINMENT"], prog)
    assert got["sources"][0]["origin"] == {
        "owner_domain": "SUSTAINMENT", "program": "prog-x", "resolved_by": "record"}, got["sources"][0]
    assert prog.calls == [("prog-x", BOB)], prog.calls
    # bob NOT a member of prog-x: unknown-identical.
    prog = Program([])
    _assert_unknown(g, NOTICE, BOB, ["SUSTAINMENT"], prog)
    assert prog.calls == [("prog-x", BOB)], prog.calls


@pytest.mark.asyncio
async def test_arm3_a_FINANCE_owned_origin_is_not_read_by_a_SUSTAINMENT_caller(registered, writer):
    g = _world()
    res_f = await _accepted_resolution(
        suggested={"owner_domain": "FINANCE", "program": "prog-f",
                   "obtained_via": "authoritative_source"},
        artifact_id=INGEST_ID_F, sid="SG-E2E-F")
    g.notices[NOTICE_F] = _notice_node(NOTICE_F, INGEST_ID_F)
    assert g.store(ALICE).create_node(
        INGEST_ID_F, kind="pdf", sha256=HEX_F, object_ref=f"ingress-user/pdf/{HEX_F}/pcn.pdf",
        ingested_at="2026-10-08T21:41:51Z", dropped_by_authz_id=ALICE) is True
    assert _write(g, res_f)["status"] == "written"
    _promote(g, INGEST_ID_F)
    prog = Program([("prog-f", CAROL)])
    _assert_unknown(g, NOTICE_F, CAROL, ["SUSTAINMENT"], prog)
    assert prog.calls == [], "the pure domain check comes first; the program was asked anyway"
    # CONTROL: the same pair is readable by a FINANCE caller who is a member -- the unknown above
    # is the origin's owner deciding, not an empty graph.
    _assert_visible(g, NOTICE_F, CAROL, ["FINANCE"], prog)
    assert prog.calls == [("prog-f", CAROL)], prog.calls


# ── 4. no-origin drop promoted by a steward (Friday's shape) ──────────────────────────────────

class _Ledger:
    def __init__(self):
        self.appends = []

    def append(self, record, *, acted_by, acted_at):
        self.appends.append(record)
        return {"ok": True}


class _Quiet:
    def delete_carrying(self, iid):
        return 0

    def quarantine(self, iid, ref):
        return []


def _payload(dropped_by=ALICE):
    return {
        "ingest_id": INGEST_ID,
        "object_ref": f"ingress-user/pdf/{HEX}/pcn.pdf",
        "content_kind": "work-instructions", "pipeline_version": "doc-tools@7f-33",
        "format_fingerprint": "pdf:pcn:v1", "standing": "supervised",
        "extraction_ref": "s3://extractions/pcn-e2e/review.json", "notice_id": NOTICE,
        "dropped_by": {"authz_id": dropped_by},
    }


def _act(g, ledger, *, acted_by):
    return promotion.act(
        _payload(), decision="promoted", acted_by=acted_by, audience=AUDIENCE, comment="why",
        can_act=lambda a, c: True,
        stores=promotion.PromotionStores(ledger=ledger, graph=g.store(acted_by),
                                         indexes=_Quiet(), objects=_Quiet()),
        governing=GOVERNING, era="commissioning", now_ms=1_000)


def test_arm4_a_STEWARD_promoting_a_no_origin_drop_opens_it_to_the_domain():
    g = _world()
    ledger = _Ledger()
    out = _act(g, ledger, acted_by=BOB)
    assert out["origin"] == "written", out
    node = g.nodes[INGEST_ID]
    assert node.get(ORIGIN_PROP_OF["origin_owner_domain"]) == "SUSTAINMENT", node
    assert node.get(ORIGIN_PROP_OF["origin_resolved_by"]) == "steward", node
    prog = Program([])                                    # dave is a member of NO program
    got = _assert_visible(g, NOTICE, DAVE, ["SUSTAINMENT"], prog)
    origin = got["sources"][0]["origin"]
    assert origin["resolved_by"] == "steward" and origin["owner_domain"] == "SUSTAINMENT", origin
    assert origin["program"] is None, origin
    assert prog.calls == [], "the origin names no program, so none was asked"
    # a caller whose domains cannot consume SUSTAINMENT:
    _assert_unknown(g, NOTICE, DAVE, ["FINANCE"], Program([]))


# ── 5. the dropper cannot attest ──────────────────────────────────────────────────────────────

def test_arm5_the_DROPPER_cannot_attest_and_nothing_opens():
    g = _world()
    ledger = _Ledger()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(g, ledger, acted_by=ALICE)
    assert ei.value.error == "dropper_cannot_attest_origin" and ei.value.status == 403
    assert ledger.appends == [], "a record was written for a refused attestation"
    assert g.origin_props(INGEST_ID) == {}, g.nodes[INGEST_ID]
    assert g.facts == {}, g.facts
    _assert_unknown(g, NOTICE, DAVE, ["SUSTAINMENT"], Program([]))


# ── 6. the backfill writes what the reader reads ──────────────────────────────────────────────

def _backfill_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_promotion_origin.py"
    spec = importlib.util.spec_from_file_location("backfill_promotion_origin_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_arm6_the_BACKFILL_writes_what_the_reader_reads_and_is_a_no_op_twice():
    g = _world()
    _promote(g, INGEST_ID)                                  # promoted, no origin
    assert g.origin_props(INGEST_ID) == {}
    _assert_unknown(g, NOTICE, DAVE, ["SUSTAINMENT"], Program([]))   # control: closed before
    records = [{"record_id": "dr-e2e", "ingest_id": INGEST_ID,
                "record": {"checks": [{"inputs": {"audience": AUDIENCE}}]}}]
    mod = _backfill_module()
    graph = g.store(BOB)
    before = len(g.write_node_calls)
    first = mod.backfill(records, graph, apply=True)
    assert first["written"] == 1 and len(g.write_node_calls) == before + 1, first
    prog = Program([])
    got = _assert_visible(g, NOTICE, DAVE, ["SUSTAINMENT"], prog)
    assert got["sources"][0]["origin"]["resolved_by"] == "steward", got["sources"][0]
    assert prog.calls == []
    second = mod.backfill(records, graph, apply=True)
    assert second["written"] == 0 and second["kept_steward"] == 1, second
    assert len(g.write_node_calls) == before + 1, "the second run wrote"
