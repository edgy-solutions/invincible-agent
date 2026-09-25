"""THE STORE MUST NEVER HOLD A BEARER TOKEN, AND THE FIRST ARM HERE PROVES IT ONCE DID.

Measured 2026-09-23 against the live Postgres checkpointer: five distinct bearer tokens in
**fifteen plaintext copies** — `checkpoint_blobs` on the `identity` channel (5), `checkpoint_blobs`
on `__start__` (5), and `checkpoint_writes.blob` (5 of 66). Clean in `checkpoints.metadata` (0 of
30, control `source` 30/30) and in `checkpoints.checkpoint` (0 of 30, control `identity` 25/30).
A thread named for 2026-09-19 was still at rest four days later; there is no TTL.

── THE ARM ORDER IS THE ARGUMENT ────────────────────────────────────────────────────────────
`test_an_UNSCRUBBED_saver_DOES_store_the_credential` runs first and is not a courtesy. Every
other arm asserts an ABSENCE, and an absence is worth exactly its positive control: a fixture
whose graph never carried a token, a matcher with a typo, a run that silently did nothing — all
three produce a clean scan indistinguishable from a working scrub. So the SAME graph, the SAME
token and the SAME matcher run through a saver differing in one thing, and that arm must find
`eyJ`. If it ever stops finding it, nothing below this line means anything and the file says so.

── WHAT THIS SEAL CAN AND CANNOT REACH ──────────────────────────────────────────────────────
It asserts what the saver is HANDED, by recording at the boundary, plus what an in-process saver
reads back. The step from "the argument is clean" to "the Postgres row is clean" is the saver's
own serialization, and no in-process double executes that — the same gap the referent seal names
for Cypher's null semantics. The live half of the claim is the fifteen-row census above and the
re-census owed after Chris's purge; this file is the mechanism, not the deployment.

── AND THE HAZARD THAT IS NOT THE CREDENTIAL ────────────────────────────────────────────────
`put` is handed the live checkpoint of a run that is still executing, and `channel_values` holds
the same dict object the next node will read. A scrub that redacted in place would strip the
credential out from under node 2 — a graph that works at node 1 and refuses at node 2, which is a
worse defect than the one being fixed and would look like an authorization bug anywhere but here.
`test_the_running_graph_still_holds_the_credential` is that arm; it reds if the scrub ever stops
copying, and it is the reason a two-node graph is used where one node would have been shorter.

Run: uv run --frozen pytest tests/graph_host/test_the_checkpointer_never_stores_the_credential.py -v
"""
from __future__ import annotations

import copy
import operator
import re
import sys
from pathlib import Path
from typing import Annotated, TypedDict

import pytest

from tests.graph_host._engine_deps import needs_langgraph

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.graph_host import identity_scrub as scrub_mod  # noqa: E402

#: A SYNTHETIC token, never a captured one. Three segments and a `eyJ` prefix — the shape a real
#: one has — so the shape predicate is exercised by the same form production carries. The payload
#: segment decodes to nothing meaningful on purpose: a fixture indistinguishable from its subject
#: is not a fixture, and a real token in a tracked file is the finding it is testing for.
TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzZWFsLWZpeHR1cmUifQ.c2lnbmF0dXJl"
BEARER = f"Bearer {TOKEN}"

#: The tell the architect's seal is written against, and deliberately BROADER than the token: it
#: asks whether anything base64url-encoding a JSON object reached the store, not whether this
#: particular fixture did.
_EYJ = re.compile(r"eyJ")

_IDENTITY = {"authorization": BEARER,
             "x-originator-sub": "seal-fixture-sub",
             "x-originator-email": "seal@fixture.invalid"}


class _SealState(TypedDict):
    """Module scope, not function scope. `from __future__ import annotations` defers these
    strings and langgraph resolves them against the DEFINING module's globals, so a TypedDict
    declared inside a test body raises `NameError: Annotated` at compile time — a lesson already
    paid for in `test_a_stateful_row_compiles_and_invokes.py` and not re-learned here."""

    identity: dict
    seen: Annotated[list, operator.add]


def _first(state: _SealState) -> dict:
    """Node 1. Reports the credential it was given, which is also how it lands in a channel."""
    return {"seen": [("first", state["identity"].get("authorization"))]}


def _second(state: _SealState) -> dict:
    """Node 2. RUNS AFTER A CHECKPOINT HAS BEEN WRITTEN, which is the whole reason it exists: an
    in-place scrub would leave it reading a redaction marker instead of the caller's credential."""
    return {"seen": [("second", state["identity"].get("authorization"))]}


def _recording_saver_class(base: type) -> type:
    """Record every payload the saver is HANDED, then behave exactly like `base`.

    Recording at the boundary rather than reading the store back is what makes the census
    complete: `put_writes` payloads are pending writes that a `list()` read of a finished thread
    need not surface, and `checkpoint_writes.blob` is one of the three sites the live count found.
    An arm over the read-back alone would have been blind to a third of the finding.
    """

    class _Recorder(base):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            self.received: list = []

        def put(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
            self.received.append(("put", copy.deepcopy(checkpoint), copy.deepcopy(metadata)))
            return super().put(config, checkpoint, metadata, new_versions)

        async def aput(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
            self.received.append(("aput", copy.deepcopy(checkpoint), copy.deepcopy(metadata)))
            return await super().aput(config, checkpoint, metadata, new_versions)

        def put_writes(self, config, writes, task_id, task_path=""):  # type: ignore[no-untyped-def]
            self.received.append(("put_writes", copy.deepcopy(list(writes)), None))
            return super().put_writes(config, writes, task_id, task_path)

        async def aput_writes(self, config, writes, task_id, task_path=""):  # type: ignore[no-untyped-def]
            self.received.append(("aput_writes", copy.deepcopy(list(writes)), None))
            return await super().aput_writes(config, writes, task_id, task_path)

    _Recorder.__name__ = f"Recording{base.__name__}"
    return _Recorder


def _run(saver, thread: str) -> tuple[dict, list]:
    """Compile and invoke the two-node graph against `saver`. Returns the final state and the
    payloads the saver received.

    DEEP-COPIED AT CAPTURE, because the recorder is measuring an object the run still owns. A
    later mutation by the runtime would rewrite the evidence after the fact, and a census taken
    of a moving subject is not a census.
    """
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(_SealState)
    builder.add_node("first", _first)
    builder.add_node("second", _second)
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    graph = builder.compile(checkpointer=saver)

    out = graph.invoke({"identity": dict(_IDENTITY), "seen": []},
                       config={"configurable": {"thread_id": thread}})
    return out, saver.received


def _hits(payloads: list) -> list[str]:
    """Every recorded payload whose text carries `eyJ`, named by entry point.

    `repr` as the flattener: total over every shape a payload takes, and VALIDATED rather than
    assumed — the positive control below reads the fixture's token out of exactly this text, so
    the instrument is known to see what it is looking for before any arm trusts a zero from it.
    """
    found = []
    for kind, payload, metadata in payloads:
        text = repr(payload) + repr(metadata)
        if _EYJ.search(text):
            found.append(kind)
    return found


@pytest.fixture()
def savers():
    """The two savers that differ in ONE thing, built from one base so nothing else can."""
    from langgraph.checkpoint.memory import InMemorySaver

    recording = _recording_saver_class(InMemorySaver)
    plain = recording()
    scrubbing = scrub_mod.scrubbing_saver_class(recording)()
    return plain, scrubbing


@needs_langgraph
def test_an_UNSCRUBBED_saver_DOES_store_the_credential(savers):
    """POSITIVE CONTROL, AND THE FILE'S LOAD-BEARING ARM. Read it as: the fixture really carries a
    credential, the run really writes, and the matcher really fires. Every absence asserted below
    is worth precisely this much and no more."""
    plain, _ = savers
    out, payloads = _run(plain, "seal-unscrubbed")

    assert payloads, (
        "THE RUN WROTE NOTHING, so no arm in this file measured anything. Asserted before the "
        "scan because an empty census and a clean census produce the same zero, and a matcher "
        "reporting no hits over no payloads is how a broken fixture reads as a working scrub."
    )
    assert out["seen"], "the graph did not execute its nodes"

    hits = _hits(payloads)
    assert hits, (
        f"THE CONTROL DID NOT FIRE over {len(payloads)} payload(s) from an UNSCRUBBED saver. "
        f"Either the fixture token no longer reaches the store, the graph no longer threads "
        f"identity through a channel, or the matcher is broken — and in all three cases the "
        f"absences asserted below are vacuous."
    )


@needs_langgraph
def test_no_payload_the_scrubbing_saver_writes_CONTAINS_eyJ(savers):
    """THE SEAL AS SPECIFIED: any checkpoint payload containing `eyJ` reds.

    A census over every write entry point the runtime touched, not a sample of the last one."""
    _, scrubbing = savers
    out, payloads = _run(scrubbing, "seal-scrubbed")

    assert payloads, (
        "THE SCRUBBING SAVER RECEIVED NOTHING. Asserted before the scan for the same reason as "
        "the control: a clean scan of an empty list is not evidence."
    )
    assert out["seen"], "the graph did not execute its nodes"

    hits = _hits(payloads)
    assert not hits, (
        f"A CREDENTIAL REACHED THE STORE via {hits} — the finding of 2026-09-23, reintroduced. "
        f"{len(payloads)} payload(s) scanned."
    )


@needs_langgraph
def test_the_running_graph_still_holds_the_credential(savers):
    """SCRUB BEFORE WRITE, NOT INSTEAD OF RUNNING. Node 2 executes after a checkpoint was written
    and must still see the caller's real credential; an in-place redaction reds here.

    This arm is why the graph has two nodes. With one, the scrub could destroy the credential
    outright and every other arm in this file would still pass."""
    _, scrubbing = savers
    out, payloads = _run(scrubbing, "seal-inflight")

    seen = dict(out["seen"])
    assert set(seen) == {"first", "second"}, (
        f"BOTH NODES MUST HAVE RUN for this arm to mean anything — a graph that stopped after "
        f"node 1 cannot tell a copying scrub from a mutating one. Saw: {sorted(seen)}"
    )
    assert seen["first"] == BEARER, "node 1 did not receive the credential it was given"
    assert seen["second"] == BEARER, (
        "NODE 2 LOST THE CREDENTIAL BETWEEN SUPER-STEPS. The scrub is mutating the live "
        "checkpoint rather than copying it, so the fix has become a mid-run authorization "
        "failure: this graph works at node 1 and would refuse at node 2."
    )
    assert out["identity"]["authorization"] == BEARER, (
        "the caller's own returned state was redacted; the scrub reaches beyond the store"
    )
    assert not _hits(payloads), "and the store must still be clean while all of that is true"


@needs_langgraph
def test_a_RESUMED_run_finds_no_credential_and_that_IS_the_contract(savers):
    """THE CONSEQUENCE, SEALED AS INTENDED RATHER THAN DISCOVERED LATER.

    A resumed thread's `identity` is the redaction marker, so a graph resuming without a freshly
    supplied identity refuses at its own check (`fin_program_brief.py:112`,
    `cost_lot_costing_review.py:99`). Under ADR-0049 Ruling 1 that is the CORRECT answer — the
    host holds no standing credential and cannot re-authorize work for a caller who has left.

    Written down because the obvious "fix" for it is to persist the credential, which is the
    finding. Anyone arriving here from a resume bug should change the caller, not this."""
    _, scrubbing = savers
    _run(scrubbing, "seal-resume")

    stored = scrubbing.get_tuple({"configurable": {"thread_id": "seal-resume"}})
    assert stored is not None, "nothing was checkpointed, so this arm measured nothing"

    restored = (stored.checkpoint.get("channel_values") or {}).get("identity")
    assert restored is not None, (
        "the `identity` channel vanished from the checkpoint entirely. A MARKER, NOT A DELETION: "
        "an absent key cannot tell 'this run carried no identity' from 'this run's identity was "
        "not written down', and the two are different findings."
    )
    assert restored.get("authorization") == scrub_mod.REDACTED, (
        f"a resumed run would inherit something other than the marker: {restored!r}"
    )
    assert not _EYJ.search(repr(stored.checkpoint)), "and the read-back row must be clean too"


@needs_langgraph
def test_BOTH_savers_the_host_can_hand_a_graph_are_scrubbing(monkeypatch):
    """THE DURABLE PATH AND THE IN-PROCESS FALLBACK, because a scrub you lose by unsetting an
    environment variable is not a scrub — and worse, every offline test would then be exercising
    an unscrubbed saver while reporting coverage of the scrubbed one."""
    import importlib

    from agent_fleet.graph_host import main as host

    monkeypatch.delenv(host._CHECKPOINT_DSN_ENV, raising=False)
    monkeypatch.delenv("MESH_REGISTER_ON_STARTUP", raising=False)
    importlib.reload(host)

    from iagent_mesh.graph_manifest import GraphManifest

    rows = [r for r in host.load_manifests()] if hasattr(host, "load_manifests") else []
    stateful = next((r for r in rows if getattr(r, "checkpointer", False)), None)
    if stateful is None:  # pragma: no cover - derived from policy, not hard-coded
        stateful = GraphManifest.model_construct(graph_id="seal", checkpointer=True)

    assert host._SAVER is None, "no DSN was set, so the fallback is the path under test"
    fallback = host._saver_for(stateful)
    assert getattr(fallback, "scrubs_identity", False), (
        f"THE IN-PROCESS FALLBACK IS NOT SCRUBBING ({type(fallback).__name__}). Unset the DSN and "
        f"the host reverts to storing credentials — in memory today, and in whatever the next "
        f"fallback is tomorrow."
    )


@needs_langgraph
def test_the_HOST_WRAPS_the_durable_saver_IT_opens(monkeypatch):
    """THE PRODUCTION PATH, THROUGH `_open_saver` ITSELF.

    ── WHY THIS ARM EXISTS AT ALL ───────────────────────────────────────────────────────────
    It replaced one that built `scrubbing_saver_class(AsyncPostgresSaver)` in the test body and
    asserted `issubclass`. That arm passed, and MEASURED BY MUTATION IT WAS WORTHLESS: stripping
    the wrapping out of `_open_saver` — the only place it matters, and the only path production
    takes — killed nothing. The arm had constructed its own subject and then verified it. A
    precondition checked on the wrong subject is true on both sides of the change.

    So `_open_saver` is invoked for real with a DSN set, and the SAVER IT ASSIGNED is the subject.

    ── THE ASSUMPTION THE DOUBLE ENCODES, PINNED ────────────────────────────────────────────
    Subclassing the concrete saver is only safe because `from_conn_string` constructs `cls(...)`
    rather than the class by name — with a hard-coded `AsyncPostgresSaver(...)` the subclass would
    be silently discarded and the scrub would vanish with it. The double reproduces `cls(...)`, so
    it cannot notice if the real one stops doing that; the first assertion reads the real source
    and refuses that rewrite. Same shape as the Cypher-construct arm in the referent seal: the
    offline form of a property an in-process double cannot execute.
    """
    import importlib
    import inspect
    from contextlib import AsyncExitStack, asynccontextmanager

    from langgraph.checkpoint.postgres import aio as pg_aio

    from agent_fleet.graph_host import main as host

    src = inspect.getsource(pg_aio.AsyncPostgresSaver.from_conn_string)
    assert "cls(" in src, (
        "`AsyncPostgresSaver.from_conn_string` NO LONGER CONSTRUCTS `cls(...)`, so a scrubbing "
        "subclass is silently downgraded to the base class and every credential is stored again. "
        f"The fix is not here. Source read:\n{src}"
    )

    class _FakePostgres:
        """Stands in for the real saver so `_open_saver` can run without Postgres. Mirrors the two
        things that function touches — a `from_conn_string` async context manager that yields
        `cls(...)`, and an awaitable `setup()`."""

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        @classmethod
        @asynccontextmanager
        async def from_conn_string(cls, dsn):  # type: ignore[no-untyped-def]
            yield cls(dsn=dsn)

        async def setup(self) -> None:
            return None

    monkeypatch.setattr(pg_aio, "AsyncPostgresSaver", _FakePostgres)
    monkeypatch.setenv(host._CHECKPOINT_DSN_ENV, "postgresql://seal/fixture")
    monkeypatch.delenv("MESH_REGISTER_ON_STARTUP", raising=False)
    importlib.reload(host)
    monkeypatch.setattr(pg_aio, "AsyncPostgresSaver", _FakePostgres)

    async def _open():
        async with AsyncExitStack() as stack:
            await host._open_saver(stack)
            return host._SAVER, dict(host._SAVER_STATUS)

    import asyncio

    saver, status = asyncio.run(_open())

    # ASSERTED FIRST, BECAUSE `_open_saver` SWALLOWS ITS FAILURE INTO `open_error` AND SETS
    # `_SAVER = None`. Without this, a broken double makes `getattr(None, "scrubs_identity", False)`
    # false and the arm reds naming the scrub — a red for a reason that is not the subject.
    assert status["open_error"] is None, f"`_open_saver` failed rather than opening: {status}"
    assert status["durable"] is True and saver is not None, (
        f"the durable path was not taken, so this arm measured nothing: {status}"
    )

    assert getattr(saver, "scrubs_identity", False), (
        f"THE HOST OPENED AN UNSCRUBBED DURABLE SAVER ({type(saver).__name__}). This is the path "
        f"production takes and the one the fifteen stored tokens came from."
    )
    assert isinstance(saver, _FakePostgres), (
        "the opened saver must still BE the concrete saver class: LangGraph isinstance-checks the "
        "checkpointer (measured — `compile()` refuses a delegating wrapper with \"Expected an "
        "instance of BaseCheckpointSaver\"), and the readiness check compares the compiled graph's "
        "checkpointer against `_SAVER` by `is`."
    )


@needs_langgraph
def test_EACH_write_entry_point_SCRUBS_WHEN_CALLED_DIRECTLY():
    """ALL FOUR OVERRIDES, DRIVEN DIRECTLY, BECAUSE A GRAPH RUN REACHES ONLY SOME OF THEM.

    Measured by mutation: removing the scrub from `aput_writes` killed NOTHING through the graph
    arms. `InMemorySaver.aput_writes` delegates to the sync `put_writes`, which the scrubbing
    subclass has already overridden — so the async override was unreachable in every offline arm
    while being the ONLY one `AsyncPostgresSaver` actually calls. A guard covered solely by a path
    that cannot reach it is a guard nothing tests.

    So the base here is a bare recorder that implements each of the four independently, and each is
    invoked and asserted on its own. The exercised set is then compared against the write surface
    DERIVED from `BaseCheckpointSaver`, so a fifth write method arriving in an upgrade reds this
    arm for being unexercised rather than passing silently."""
    import asyncio

    from langgraph.checkpoint.base import BaseCheckpointSaver

    class _Recording(BaseCheckpointSaver):
        def __init__(self) -> None:
            super().__init__()
            self.got: dict = {}

        def put(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
            self.got["put"] = (checkpoint, metadata)
            return config

        async def aput(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
            self.got["aput"] = (checkpoint, metadata)
            return config

        def put_writes(self, config, writes, task_id, task_path=""):  # type: ignore[no-untyped-def]
            self.got["put_writes"] = list(writes)

        async def aput_writes(self, config, writes, task_id, task_path=""):  # type: ignore[no-untyped-def]
            self.got["aput_writes"] = list(writes)

    saver = scrub_mod.scrubbing_saver_class(_Recording)()
    cfg = {"configurable": {"thread_id": "seal-direct"}}
    checkpoint = {"channel_values": {"identity": dict(_IDENTITY), "seen": [("first", BEARER)]}}
    metadata = {"source": "loop", "writes": {"identity": dict(_IDENTITY)}}
    writes = [("identity", dict(_IDENTITY)), ("seen", [("second", BEARER)])]

    saver.put(cfg, copy.deepcopy(checkpoint), copy.deepcopy(metadata), {})
    saver.put_writes(cfg, copy.deepcopy(writes), "task-1")
    asyncio.run(saver.aput(cfg, copy.deepcopy(checkpoint), copy.deepcopy(metadata), {}))
    asyncio.run(saver.aput_writes(cfg, copy.deepcopy(writes), "task-2"))

    surface = {n for n in dir(BaseCheckpointSaver)
               if not n.startswith("_") and n.lstrip("a").startswith("put")}
    assert set(saver.got) == surface, (
        f"exercised {sorted(saver.got)} but the base declares {sorted(surface)}. An entry point "
        f"this arm does not call is an entry point no arm covers."
    )
    for entry, payload in sorted(saver.got.items()):
        assert not _EYJ.search(repr(payload)), (
            f"`{entry}` PASSED A CREDENTIAL THROUGH UNSCRUBBED: {payload!r}"
        )


@needs_langgraph
def test_EVERY_write_entry_point_on_the_base_is_overridden():
    """DERIVED, NOT LISTED. The four names are not typed here as a hand-written set — they are read
    off `BaseCheckpointSaver`, so a fifth write method arriving in a langgraph upgrade reds this
    arm instead of quietly opening a path around the scrub. A hand-written list of a population is
    a sample, and this one would age silently."""
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.checkpoint.memory import InMemorySaver

    writes = {n for n in dir(BaseCheckpointSaver)
              if not n.startswith("_") and n.lstrip("a").startswith("put")}
    assert writes, "no write surface was derived, so this arm cannot fail — instrument defect"

    scrubbing = scrub_mod.scrubbing_saver_class(InMemorySaver)
    missed = sorted(n for n in writes if n not in vars(scrubbing))
    assert not missed, (
        f"{missed} reach the store WITHOUT passing through the scrub. Every public `put*`/`aput*` "
        f"on the base is a write path, and one left un-overridden is the whole hole."
    )


def test_the_scrub_returns_a_COPY_and_mutates_NOTHING():
    """The module-level property the in-flight arm depends on, asserted directly so a failure
    names the cause rather than the symptom. Run without langgraph: this is pure."""
    original = {"identity": dict(_IDENTITY),
                "notes": [{"quoted": BEARER}, "plain text"],
                "nested": ({"authorization": BEARER},)}
    before = copy.deepcopy(original)

    scrubbed = scrub_mod.scrub(original)

    assert original == before, (
        "THE SCRUB MUTATED ITS ARGUMENT. Every other property can hold and this alone turns the "
        "storage fix into a mid-run authorization failure — see the in-flight arm."
    )
    assert scrubbed is not original, "a scrub that returns its argument has not copied anything"
    assert not _EYJ.search(repr(scrubbed)), f"the copy still carries a credential: {scrubbed!r}"


def test_a_credential_under_a_key_NOBODY_LISTED_is_still_caught():
    """THE SHAPE ARM, AND WHY THE KEY LIST IS NOT THE WHOLE PREDICATE.

    A key list can only see the keys someone enumerated, and the finding's second site was the
    `__start__` channel — a name no identity list would ever have contained. Both halves of the
    predicate are exercised here, and the arm fails if EITHER stops working."""
    by_name = scrub_mod.scrub({"identity": dict(_IDENTITY)})
    assert by_name["identity"]["authorization"] == scrub_mod.REDACTED, "the name arm is dead"

    for shape in ({"__start__": {"whatever": BEARER}},
                  {"audit_trail": f"called with {BEARER} at 12:01"},
                  {"blob": BEARER.encode("utf-8")},
                  {"args": [[{"deeply": {"nested": TOKEN}}]]}):
        cleaned = scrub_mod.scrub(shape)
        assert not _EYJ.search(repr(cleaned)), (
            f"THE SHAPE ARM MISSED {shape!r} -> {cleaned!r}. A credential reaching the store under "
            f"an unenumerated key is the case the name arm structurally cannot see."
        )

    kept = scrub_mod.scrub({"notes": "nothing sensitive here", "count": 3})
    assert kept == {"notes": "nothing sensitive here", "count": 3}, (
        "NEGATIVE CONTROL: the scrub redacted a value with no credential in it. A redactor that "
        "rewrites everything passes every absence arm above while destroying the checkpoint."
    )


def test_the_MARKER_cannot_trip_the_seal_it_serves():
    """A redaction whose own text matched the tell would make every scrubbed row red and the seal
    unusable — self-defeating in a way no other arm would name. Cheap, and it guards the
    instrument rather than the subject."""
    assert not _EYJ.search(scrub_mod.REDACTED), (
        f"the redaction marker itself contains the tell: {scrub_mod.REDACTED!r}"
    )
    assert "identity_scrub" in scrub_mod.REDACTED, (
        "the marker must name where the redaction came from — whoever finds one in a checkpoint "
        "should reach the reasoning, not file a data-loss bug"
    )


def test_the_HOST_and_the_SCRUB_share_ONE_declaration():
    """THE INVARIANT BETWEEN TWO FILES, which no per-file check can see.

    `main.py` accepts identity headers and writes an identity channel; `identity_scrub` redacts
    exactly those. Each file is correct on its own with a fourth header added to one of them, and
    the credential would flow to the store with every arm green. So the relation is asserted:
    one tuple object, and the channel key read from the scrub rather than spelled again."""
    import ast

    from agent_fleet.graph_host import main as host

    assert host._IDENTITY_HEADERS is scrub_mod.IDENTITY_HEADERS, (
        "TWO TUPLES, ONE MEANING. The host forwards headers the scrub may not redact; asserted by "
        "IDENTITY (`is`) rather than equality, because two equal tuples today drift tomorrow and "
        "equality is exactly the check that would not notice."
    )

    src = (Path(host.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    writes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "state"):
                writes.append(target.slice)

    assert writes, (
        "no `state[...] = ...` assignment was found in the host at all. Asserted before the shape "
        "check because an empty list satisfies an all() vacuously, and this arm would then be "
        "green on a host that had stopped threading identity entirely."
    )
    literals = [ast.unparse(s) for s in writes if isinstance(s, ast.Constant)]
    assert not literals, (
        f"the host writes state channel(s) by LITERAL: {literals}. The identity channel must be "
        f"`_scrub.IDENTITY_CHANNEL`, or a rename on either side leaves the scrub redacting a "
        f"channel nobody writes — a pass on every arm in this file, and the finding restored."
    )
