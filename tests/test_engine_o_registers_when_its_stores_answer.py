"""AN ENGINE REGISTERS WHEN ITS STORES ANSWER, NOT WHEN ITS POD STARTS (for roll #17).

engine-o's lifespan logged a failed store connection and registered its verb anyway, so the
first boot decided the pod's routing for its whole life: a Weaviate missed at boot stayed None
until a restart, and `mesh:resolveInstance` was advertised whatever its store said. This is
the same supervised retry a refused registration takes (2c7b85cf, engine-f, 2026-09-25), keyed
on the STORES: `mesh_registration.when_stores_answer`.

WHICH STORE GATES THE REGISTRATION IS THE ONE THE VERB READS. `/resolve_instance` reads Jena,
through `execute_sparql`, whose rdflib fallback answers when Jena does not -- so registered
while Jena is down, the provider abstains confidently. Weaviate is gated too, under its own
name, as a reconnect: the verb does not read it, so it does not hold the registration.

The retry thread is never started here: `_start_retry` is replaced by a recorder, and each arm
runs the captured attempt itself, so no arm sleeps and none leaves a thread behind.

Run: uv run --frozen pytest tests/test_engine_o_registers_when_its_stores_answer.py -v
"""
from __future__ import annotations

import copy
import types

import pytest


def _eo():
    from agent_fleet.ontology_service import main as eo
    return eo


@pytest.fixture()
def mr(monkeypatch):
    """The registration module engine-o's lifespan reads, with its state restored after, and
    the retry thread replaced by a list of the attempts it would have run."""
    mod = _eo()._mesh_registration()
    saved = copy.deepcopy(mod._REG_STATE)
    armed: list = []

    def start_retry(component, attempt):
        mod._record(component, mod._REG_RETRYING)
        armed.append((component, attempt))

    monkeypatch.setattr(mod, "_start_retry", start_retry)
    mod.armed = armed
    yield mod
    with mod._REG_LOCK:
        mod._REG_STATE.clear()
        mod._REG_STATE.update(saved)
    del mod.armed


def _gate(mr, name):
    return mr.registration_status()["components"].get(name)


# ── the helper ──────────────────────────────────────────────────────────────────────────────

def test_STORES_THAT_ANSWER_ACT_AT_ONCE(mr):
    ran = []
    assert mr.when_stores_answer("t:up", {"a": lambda: True}, lambda: ran.append(1)) is True
    assert ran == [1] and mr.armed == []
    assert _gate(mr, "t:up") == mr._REG_OK


def test_NO_STORES_ACT_AT_ONCE(mr):
    ran = []
    assert mr.when_stores_answer("t:none", {}, lambda: ran.append(1)) is True
    assert ran == [1] and mr.armed == []


def test_A_SILENT_STORE_HOLDS_THE_ACT_AND_IS_NAMED_UNTIL_IT_ANSWERS(mr):
    up = {"b": False}
    ran = []
    assert mr.when_stores_answer("t:wait", {"a": lambda: True, "b": lambda: up["b"]},
                                 lambda: ran.append(1)) is False
    assert ran == [] and [c for c, _ in mr.armed] == ["t:wait"]
    st = mr.registration_status()
    assert st["components"]["t:wait"] == mr._REG_RETRYING
    assert st["last_error"] == "t:wait: no answer from b", st
    assert not mr.registration_is_ready()

    attempt = mr.armed[0][1]
    assert attempt() is False and ran == []
    up["b"] = True
    assert attempt() is True and ran == [1]


@pytest.mark.parametrize("probe", [lambda: None, lambda: 0, lambda: 1 / 0],
                         ids=["none", "falsy", "raises"])
def test_A_FALSY_OR_RAISING_PROBE_IS_NO_ANSWER(mr, probe):
    ran = []
    assert mr.when_stores_answer("t:bad", {"s": probe}, lambda: ran.append(1)) is False
    assert ran == [] and mr.registration_status()["last_error"] == "t:bad: no answer from s"


def test_EVERY_SILENT_STORE_IS_NAMED(mr):
    mr.when_stores_answer("t:two", {"a": lambda: False, "b": lambda: True, "c": lambda: False},
                          lambda: None)
    assert mr.registration_status()["last_error"] == "t:two: no answer from a, c"


# ── engine-o's lifespan ─────────────────────────────────────────────────────────────────────

class _Weaviate:
    """A Weaviate whose class index holds one class. A read that reaches the index returns it,
    and nothing else can: the cold-start fallback answers from the maintenance ontology."""
    INDEXED = {"uri": "urn:test#FromTheIndex", "label": "FromTheIndex", "definition": "d"}

    def __init__(self):
        def answer(**kw):
            hit = types.SimpleNamespace(properties=self.INDEXED,
                                        metadata=types.SimpleNamespace(score=0.9))
            return types.SimpleNamespace(objects=[hit])
        index = types.SimpleNamespace(query=types.SimpleNamespace(hybrid=answer, bm25=answer))
        self.collections = types.SimpleNamespace(exists=lambda name: name == "OntologyClass",
                                                 get=lambda name: index)

    def is_ready(self):
        return True

    def close(self):
        pass


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture()
def boot(mr, monkeypatch):
    """engine-o's lifespan with every store a switch. Neo4j is a stub that connects; Jena is
    configured and answers the ASK only while ``world["jena"]``; Weaviate connects only while
    ``world["weaviate"]``."""
    eo = _eo()
    world = {"jena": True, "weaviate": True, "registered": []}

    def make():
        if not world["weaviate"]:
            raise ConnectionError("weaviate refused")
        return _Weaviate()

    def jena_post(url, *, data, headers):
        if not world["jena"]:
            raise ConnectionError("jena refused")
        return _Resp(200, {"head": {}, "boolean": True})

    class _Neo:
        def verify_connectivity(self):
            pass

        def close(self):
            pass

    async def _populated():
        return None

    monkeypatch.setattr(eo, "_WEAVIATE_CLIENT", None)
    monkeypatch.setattr(eo, "create_weaviate_client", make)
    monkeypatch.setattr(eo, "embed_query", lambda q: [0.0, 1.0])
    monkeypatch.setattr(eo.GraphDatabase, "driver", lambda *a, **k: _Neo())
    monkeypatch.setattr(eo, "_check_jena_populated", _populated)
    monkeypatch.setattr(eo, "_jena_ontology_post", jena_post)
    monkeypatch.setattr(eo, "_JENA_ENDPOINT", "http://jena.test/ds/query")
    monkeypatch.setattr(mr, "engine_mint", lambda **k: None)
    monkeypatch.setattr(mr, "register_engine_to_mesh",
                        lambda **k: world["registered"].append(k["verb"]))

    async def run():
        async with eo.lifespan(eo.app):
            pass
    world["run"] = run
    return eo, world


def _armed(mr, name):
    hits = [a for c, a in mr.armed if c == name]
    assert len(hits) == 1, mr.armed
    return hits[0]


@pytest.mark.asyncio
async def test_STORES_UP_AT_BOOT_REGISTER_AT_BOOT(boot, mr):
    eo, world = boot
    await world["run"]()
    assert world["registered"] == ["mesh:resolveInstance"] and mr.armed == []


@pytest.mark.asyncio
async def test_WEAVIATE_UNREACHABLE_AT_BOOT_IS_RECONNECTED_WHEN_IT_RETURNS(boot, mr):
    """The seal as dispatched: start with Weaviate unreachable; when it returns, it is used."""
    eo, world = boot
    world["weaviate"] = False
    await world["run"]()
    assert eo._WEAVIATE_CLIENT is None
    assert _gate(mr, "engine-o:weaviate") == mr._REG_RETRYING
    reconnect = _armed(mr, "engine-o:weaviate")
    assert reconnect() is False and eo._WEAVIATE_CLIENT is None
    world["weaviate"] = True
    assert reconnect() is True
    assert _uris(_read(eo)) == [_Weaviate.INDEXED["uri"]]
    # ...and it does not hold the verb, which never reads Weaviate.
    assert world["registered"] == ["mesh:resolveInstance"]


def _read(eo):
    """A read the way `/resolve` makes one: through the class index."""
    return eo._weaviate_hybrid_search_sync("pump")


def _uris(read):
    return [r["uri"] for r in read[0]]


@pytest.mark.asyncio
async def test_A_POD_BOOTED_WITHOUT_WEAVIATE_READS_THE_INDEX_WHEN_IT_RETURNS(boot, mr):
    """ROLL #16 (packet 2026-10-04): engine-o started with no Weaviate and sat cold until a
    restart. Here there is no restart: the read is made inside the same lifespan that booted
    without Weaviate.

    THE RETRY THREAD'S NEXT TICK IS EVERY ATTEMPT THE BOOT ARMED, run once. No gate is named,
    so the arm stands against a lifespan that arms nothing -- the one-shot connect it replaced,
    which leaves the client None and every reader on its no-Weaviate branch.

    IT ASSERTS A READ. A client object existing is not an answer from the index; the class only
    the index holds is."""
    eo, world = boot
    world["weaviate"] = False
    async with eo.lifespan(eo.app):
        assert _read(eo) == ([], None)  # the shape `/resolve` takes for a cold start
        world["weaviate"] = True
        for _, attempt in list(mr.armed):
            attempt()
        rows, mode = _read(eo)
        assert _uris((rows, mode)) == [_Weaviate.INDEXED["uri"]], (
            "booted without Weaviate, the pod never read the index after Weaviate returned")
        assert mode == "hybrid"


@pytest.mark.asyncio
async def test_JENA_UNREACHABLE_AT_BOOT_REGISTERS_ONCE_WHEN_IT_RETURNS(boot, mr):
    eo, world = boot
    world["jena"] = False
    await world["run"]()
    assert world["registered"] == []
    assert not mr.registration_is_ready()
    assert mr.registration_status()["last_error"] == (
        "engine_o_sustainment_resolve_instance:stores: no answer from jena")
    register = _armed(mr, "engine_o_sustainment_resolve_instance:stores")
    assert register() is False and world["registered"] == []
    world["jena"] = True
    assert register() is True
    assert world["registered"] == ["mesh:resolveInstance"]


@pytest.mark.asyncio
async def test_THE_JENA_PROBE_IS_NOT_ANSWERED_BY_THE_RDFLIB_FALLBACK(boot, mr, monkeypatch):
    """`execute_sparql` answers from rdflib when Jena is down; a probe built on it would never
    close the gate. Here it answers everything, and Jena is down: the verb still waits."""
    eo, world = boot
    world["jena"] = False

    async def answers(*a, **k):
        return [{"s": "x"}]
    monkeypatch.setattr(eo, "execute_sparql", answers)
    await world["run"]()
    assert world["registered"] == []


#: Each differs from an answer in ONE thing: a 503 whose body would otherwise pass, and a 200
#: whose body is not an ASK result.
@pytest.mark.parametrize("resp", [_Resp(503, {"boolean": True}), _Resp(200, {"results": {"bindings": []}})],
                         ids=["not-200", "not-an-ask-answer"])
@pytest.mark.asyncio
async def test_A_JENA_THAT_DOES_NOT_ANSWER_THE_ASK_IS_SILENT(boot, mr, monkeypatch, resp):
    eo, world = boot
    monkeypatch.setattr(eo, "_jena_ontology_post", lambda url, *, data, headers: resp)
    await world["run"]()
    assert world["registered"] == []


@pytest.mark.asyncio
async def test_A_DEPLOYMENT_WITHOUT_JENA_REGISTERS_AT_BOOT(boot, mr, monkeypatch):
    """No Jena declared means rdflib by design, not a store that is down: nothing to wait on."""
    eo, world = boot
    world["jena"] = False
    monkeypatch.setattr(eo, "_JENA_ENDPOINT", None)
    await world["run"]()
    assert world["registered"] == ["mesh:resolveInstance"]
    assert "engine_o_sustainment_resolve_instance:stores" not in [c for c, _ in mr.armed]
