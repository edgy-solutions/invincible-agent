"""A REAL baml_py call's generation record names the model and the parameters it sent.

The architect, 11-26: "#544 records no model name or parameters. Perf read all 566 traces on
0.4.92: none of 2572 model calls carries a model, parameters or an effort key."

THE CAUSE. baml_py 0.219.0's `HTTPBody.raw()` returns a `bytearray`, although its stub says
`bytes`. `_body_bytes` accepted only `bytes`, so it hashed and parsed `str(raw)`, the text
`bytearray(b'...')`. That parse fails, so `model` was None and `model_parameters` was `{}` on
every call, while `prompt_sha256` was the hash of that repr. #544's seal never saw this, because
its fake body returned `bytes`, and its docstring said a real `Collector` "cannot be filled
offline". It can: this file fills one by sending a real call to a stub HTTP server on the
loopback interface. The stub returns a canned reply, and no model runs.

The coalescer read the same body the same way. Its key stayed exact (the repr is injective),
but it is fixed too, so that a record's `prompt_sha256` stays the coalescer's key without the
name prefix, as test_the_model_call_is_a_generation.py states.

Run:  uv run python -m pytest tests/routing/test_a_real_baml_call_records_its_model_and_parameters.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

bp = pytest.importorskip("baml_py.baml_py")

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "agent_fleet" / "ontology_service"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.ontology_service import model_generations as mg  # noqa: E402
from agent_fleet.ontology_service.inflight import CoalescingClient  # noqa: E402

MODEL = "seal-model-4417"
SERVED = "seal-model-4417-served"
EFFORT = "low"
MAX_TOKENS = 321
REPLY = {"id": "c1", "object": "chat.completion", "created": 1, "model": SERVED,
         "choices": [{"index": 0, "message": {"role": "assistant", "content": "\"ok\""},
                      "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}}


@pytest.fixture(scope="module")
def stub():
    """An OpenAI-shaped stub on 127.0.0.1 that records each request body it receives."""
    seen: list = []

    class _H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps(REPLY).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1], seen
    finally:
        srv.shutdown()


@pytest.fixture(scope="module")
def runtime(stub):
    port, _ = stub
    src = "\n".join([
        "client<llm> Seal {",
        '  provider "openai-generic"',
        "  options {",
        f'    base_url "http://127.0.0.1:{port}/v1"',
        f'    model "{MODEL}"',
        "    temperature 0",
        f'    reasoning_effort "{EFFORT}"',
        f"    max_tokens {MAX_TOKENS}",
        "    max_retries 0",
        "  }",
        "}",
        "",
        "function F(q: string) -> string {",
        "  client Seal",
        '  prompt #"{{ q }}"#',
        "}",
        "",
    ])
    return bp.BamlRuntime.from_files("baml_src", {"baml_src/main.baml": src}, {})


@pytest.fixture
def called(runtime, stub):
    """One real call. Returns the collector it filled and the exact bytes the stub received."""
    _, seen = stub
    before = len(seen)
    col = bp.Collector("seal")
    runtime.call_function_sync("F", {"q": "hi"}, runtime.create_context_manager(), None, None,
                               [col], {}, {}, None)
    assert len(seen) == before + 1, "the call did not reach the stub"
    return col, seen[-1]


def test_guard_the_real_body_is_not_bytes(called):
    """What makes this seal discriminate: a `bytes` body passes the old reader too. If baml_py
    starts returning `bytes`, this goes red to say the premise moved, and the fix stays harmless."""
    col, wire = called
    raw = col.last.calls[-1].http_request.body.raw()
    assert not isinstance(raw, bytes), type(raw)
    assert bytes(raw) == wire


def test_the_record_names_the_model_the_wire_carried(called):
    col, wire = called
    rec = mg.build_record("F", col)
    assert json.loads(wire)["model"] == MODEL
    assert rec["model"] == MODEL
    assert rec["model_version"] == SERVED


def test_the_record_carries_every_sent_parameter_with_the_effort(called):
    col, wire = called
    sent = json.loads(wire)
    rec = mg.build_record("F", col)
    assert rec["model_parameters"] == {k: sent[k] for k in mg._PARAM_KEYS if k in sent}
    assert rec["model_parameters"]["reasoning_effort"] == EFFORT
    assert rec["model_parameters"]["temperature"] == 0
    assert rec["model_parameters"]["max_tokens"] == MAX_TOKENS


def test_the_prompt_hash_is_the_hash_of_the_bytes_sent(called):
    col, wire = called
    assert mg.build_record("F", col)["prompt_sha256"] == hashlib.sha256(wire).hexdigest()


def test_the_token_counts_are_recorded(called):
    col, _ = called
    assert mg.build_record("F", col)["usage"] == {"input_tokens": 11, "output_tokens": 3}


def test_the_coalescers_key_is_the_prompt_hash_with_the_name_prefix(runtime, called):
    """The coalescer renders the request itself (`client.request.<name>`), and the record reads
    the collector. Both must hash the same bytes."""
    col, wire = called

    class _Inner:
        class request:  # noqa: N801 -- BAML's attribute name
            @staticmethod
            def F(*a, **k):
                return runtime.build_request_sync("F", {"q": "hi"}, runtime.create_context_manager(),
                                                  None, None, {}, False)

    key = asyncio.run(CoalescingClient(_Inner())._key("F", (), {}))
    assert key == hashlib.sha256(b"F\0" + wire).hexdigest()


def test_the_emit_hands_langfuse_the_model_and_the_parameters(called, monkeypatch):
    """The last hop: what `langfuse_emit` passes to `start_observation`, from the real record."""
    col, _ = called
    got: list = []

    class _Obs:
        def end(self):
            pass

    class _Client:
        def start_observation(self, **kw):
            got.append(kw)
            return _Obs()

    import langfuse
    monkeypatch.setattr(mg, "_langfuse_on", lambda: True)
    monkeypatch.setattr(langfuse, "get_client", lambda: _Client())
    mg.langfuse_emit(mg.build_record("F", col))
    (kw,) = got
    assert kw["as_type"] == "generation"
    assert kw["model"] == MODEL
    assert kw["model_parameters"]["reasoning_effort"] == EFFORT
    assert kw["usage_details"] == {"input": 11, "output": 3}
