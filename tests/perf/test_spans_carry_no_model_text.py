"""No span we export carries model or retrieval text (perf ruling 2026-11-15, "dropped").

Langfuse's decorator captures a function's arguments and return value unless told not to, and
the leaf's ``traced`` told it nothing. The shim (`baml_shared/telemetry.py`) is where the repo's
instrumented functions get their decorator, so it is where capture is turned off and kept off:

(a) BEHAVIOUR: ``safe_observe`` passes both capture flags as False whatever the caller asks;
    ``safe_update_observation`` sends sizes, never text; the environment backstop is overwritten,
    not defaulted; ``get_langgraph_callbacks`` is empty.
(b) CENSUS, decided on the FORM the code must take (AST, not grep): nothing outside the shim
    imports ``observe`` from langfuse, builds a ``CallbackHandler``, or passes ``input=`` /
    ``output=`` to ``update_current_span`` / ``update_current_generation`` / ``.update``. The
    detector is run on a planted source for each form first, so a blind detector is red.

Run: uv run pytest tests/perf/test_spans_carry_no_model_text.py -q
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("provenance_telemetry")
langfuse = pytest.importorskip("langfuse")

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "baml_shared" / "telemetry.py"
_ENV = "LANGFUSE_OBSERVE_DECORATOR_IO_CAPTURE_ENABLED"


@pytest.fixture
def shim(monkeypatch):
    """A fresh copy of the shim, imported with Langfuse keys set, `observe` and `get_client` doubled."""
    for k, v in (("LANGFUSE_SECRET_KEY", "sk-test"), ("LANGFUSE_PUBLIC_KEY", "pk-test"),
                 (_ENV, "true"),  # the control: pre-set to "true", and the import must overwrite it
                 ("LITELLM_SUCCESS_CALLBACKS", ""), ("LITELLM_FAILURE_CALLBACKS", "")):
        monkeypatch.setenv(k, v)
    seen: dict = {"observe": [], "update": []}

    def fake_observe(**kw):
        seen["observe"].append(kw)
        return lambda fn: fn

    class _Client:
        def update_current_span(self, **kw):
            seen["update"].append(kw)

    monkeypatch.setattr(langfuse, "observe", fake_observe)
    monkeypatch.setattr(langfuse, "get_client", lambda: _Client())
    spec = importlib.util.spec_from_file_location("_shim_under_test", SHIM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seen = seen
    return mod


# -- (a) behaviour -------------------------------------------------------------------------------

def test_safe_observe_turns_capture_off(shim):
    shim.safe_observe(name="x")(lambda: None)
    assert shim.seen["observe"] == [{"name": "x", "capture_input": False, "capture_output": False}]


def test_a_caller_cannot_turn_capture_back_on(shim):
    shim.safe_observe(name="x", capture_input=True, capture_output=True)(lambda: None)
    (kw,) = shim.seen["observe"]
    assert kw["capture_input"] is False and kw["capture_output"] is False


def test_update_observation_sends_sizes_not_text(shim):
    shim.safe_update_observation("q", ["m1", "m2"])
    (kw,) = shim.seen["update"]
    assert "input" not in kw and "output" not in kw
    assert kw["metadata"] == {"input_size": 1, "output_size": 2}


def test_update_observation_size_of_a_sizeless_value_is_its_str_length_and_none_is_absent(shim):
    shim.safe_update_observation(12345, None)
    (kw,) = shim.seen["update"]
    assert kw["metadata"] == {"input_size": 5}


def test_the_env_backstop_is_overwritten_not_defaulted(shim):
    import os
    assert os.environ[_ENV] == "false"


def test_langgraph_callbacks_are_empty(shim):
    assert shim.get_langgraph_callbacks() == []


# -- (b) census ----------------------------------------------------------------------------------

_TEXT_KW = {"input", "output"}


def _forms(source: str) -> list[str]:
    """The forbidden forms in one source text, by AST."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "langfuse":
            if any(a.name == "observe" for a in node.names):
                found.append("import observe from langfuse")
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name == "CallbackHandler":
                found.append("CallbackHandler(")
            if name == "observe" and isinstance(f, ast.Attribute) \
                    and isinstance(f.value, ast.Name) and f.value.id == "langfuse":
                found.append("langfuse.observe(")
            if name in {"update_current_span", "update_current_generation", "update"} \
                    and any(k.arg in _TEXT_KW for k in node.keywords):
                found.append(f"{name}(input=/output=)")
    return found


_PLANTED = {
    "import observe from langfuse": "from langfuse import observe\n",
    "langfuse.observe(": "import langfuse\n@langfuse.observe()\ndef f(): ...\nlangfuse.observe(name='x')\n",
    "CallbackHandler(": "from langfuse.langchain import CallbackHandler\nh = CallbackHandler()\n",
    "update_current_span(input=/output=)": "c.update_current_span(input=q)\n",
    "update_current_generation(input=/output=)": "c.update_current_generation(output=a)\n",
    "update(input=/output=)": "obs.update(output=a)\n",
}


@pytest.mark.parametrize("form", sorted(_PLANTED))
def test_the_detector_finds_a_planted_form(form):
    assert _forms(_PLANTED[form]), f"the detector is blind to {form}"


def test_the_detector_passes_the_allowed_shapes():
    assert _forms("c.update_current_span(metadata={'n': 1})\nobs.update(level='ERROR')\n"
                  "from langfuse import get_client\n") == []


def _scanned():
    skip = {"baml_client", "node_modules", "tests", "__pycache__"}
    for top in ("src", "agent_fleet", "baml_shared", "scripts"):
        for p in (ROOT / top).rglob("*.py"):
            rel = p.relative_to(ROOT).parts
            if skip & set(rel) or any(x.startswith(".venv") for x in rel) or p == SHIM:
                continue
            yield p


def test_no_source_outside_the_shim_records_text_into_a_span():
    files = list(_scanned())
    assert len(files) > 100, len(files)  # the walk reached the tree
    bad = {}
    for p in files:
        try:
            src = p.read_text(encoding="utf-8")
            hits = _forms(src)
        except (SyntaxError, UnicodeDecodeError):
            continue
        if hits:
            bad[str(p.relative_to(ROOT))] = hits
    assert bad == {}
