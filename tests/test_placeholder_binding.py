"""EVERY PLACEHOLDER BINDS AT ADMISSION — asserted against the REAL definitions and the RUNTIME.

THE DEFECT (2026-08-09, first-ever execution of the autonomous dispatch path):

    [500 Internal] Invalid URL '{dispatch_endpoint}': No scheme supplied.   retry_count 16

`policy/workflows/autonomous_review.yaml` declared a templated endpoint and NOTHING bound it. Three
independent failures had to line up, and this file exists to break all three:

  1. NOTHING BOUND IT — `direct_call` passed `step.endpoint` through raw.
  2. NOTHING NOTICED — both existing tests (`test_definition_driven`, `test_promise_name_seal`)
     INJECT `dispatch_endpoint` into their bindings and then assert the workflow used it. Transport
     proven, sourcing never. **This file therefore takes its placeholders from the SHIPPED YAML and
     its bindings from the RUNTIME**, and injects neither.
  3. NOTHING RAN IT — the step sat behind a capability granted to nobody, so it had executed ZERO
     times. Every expected-deny is a lid over virgin code; a fixture cannot substitute for that, but
     a seal that reads the real definition can.

Run:  uv run --frozen python -m pytest tests/test_placeholder_binding.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.restate_analyst.workflow_definition import (  # noqa: E402
    UnboundPlaceholder, bind_placeholders, collect_placeholders, config_bindings,
)

_WORKFLOWS = _ROOT / "policy" / "workflows"


def _definitions():
    out = []
    for f in sorted(_WORKFLOWS.glob("*.yaml")):
        out.append((f.name, yaml.safe_load(f.read_text(encoding="utf-8"))))
    assert out, "no workflow definitions found — this seal would pass over an empty set"
    return out


# ===========================================================================
# THE CLAIM — the SHIPPED definitions, against the RUNTIME's own bindings
# ===========================================================================
@pytest.mark.parametrize("name,defn", _definitions())
def test_every_shipped_definition_binds_with_runtime_values_only(name, defn):
    """No fixture bindings. Config comes from `config_bindings()` — the runtime's real source — and
    trigger keys are supplied as the *names* a trigger can carry, not as invented values.

    A definition that needs a placeholder nobody provides fails HERE, at build time, instead of at
    an HTTP client sixteen retries into a live autonomous run.
    """
    # The keys a real trigger carries on these paths. Named explicitly so that ADDING a placeholder
    # to a definition without teaching the runtime about it goes RED rather than silently relying
    # on whatever a test happened to pass in.
    trigger = {"compartment": "SUSTAINMENT", "notice_id": "N-1", "notice_ref": "ref",
               "artifact_urn": "urn:x", "artifact_label": "label", "id": "i", "n": 1}
    bound = bind_placeholders(defn, trigger)
    leftover = collect_placeholders(bound)
    assert not leftover, f"{name}: placeholders survived substitution: {sorted(leftover)}"


def test_the_exact_defect_is_now_STRUCTURALLY_IMPOSSIBLE_on_the_autonomous_path():
    """THE BUG, re-pinned at its stronger form (2026-08-09).

    This originally asserted that `autonomous_review.yaml` DECLARES `dispatch_endpoint` and that the
    runtime BINDS it — the defect being that only the first was true. The step has since been
    renamed `direct_call` -> `dispatch_fanout`, a kind with NO endpoint field at all: it dispatches
    the review's own batch through the sealed fan-out, so there is no URL for a definition author to
    supply or for the runtime to leave unbound.

    The pin is therefore re-pointed rather than deleted, at the stronger property: the autonomous
    definition declares NO endpoint placeholder, so this class of defect is now unexpressible there.
    The runtime binding is still asserted because generic `direct_call` survives and can still use
    it."""
    defn = yaml.safe_load((_WORKFLOWS / "autonomous_review.yaml").read_text(encoding="utf-8"))
    assert "dispatch_endpoint" not in collect_placeholders(defn), (
        "an endpoint placeholder is back on the autonomous path — the false generality that hid the "
        "unbound literal for months")
    assert "dispatch_endpoint" in config_bindings(), (
        "the runtime must still bind it for generic direct_call callers")


def test_the_endpoint_binds_to_the_SAME_target_the_supervised_path_uses():
    """ONE VALUE, ONE HOME. The autonomous path must dispatch to the endpoint the working
    supervised path already writes to; a second declaration is a second thing to drift."""
    got = config_bindings()["dispatch_endpoint"]
    import os  # noqa: PLC0415
    engine_o = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084").rstrip("/")
    assert got == f"{engine_o}/write_item_state", (
        f"dispatch_endpoint={got!r} does not match the supervised path's target — the two paths "
        f"can now disagree about where engine-o lives")


# ===========================================================================
# THE FAILURE MODE — loud, at admission, naming what is missing
# ===========================================================================
def test_an_unbound_placeholder_RAISES_at_admission():
    """Not a silent pass-through, not a retryable transport error later."""
    defn = {"id": "x", "steps": [{"kind": "direct_call", "endpoint": "{nowhere_defined}"}]}
    with pytest.raises(UnboundPlaceholder) as ei:
        bind_placeholders(defn, {})
    msg = str(ei.value)
    assert "nowhere_defined" in msg, "the refusal must NAME the unbound placeholder"
    assert "DEPLOYMENT defect" in msg, (
        "the refusal must say this is true of EVERY run, not of this notice — that distinction is "
        "what routes a reader to config instead of to the input")


def test_the_literal_never_reaches_a_client():
    """The regression in its exact original shape: a raw `{dispatch_endpoint}` surviving into an
    endpoint value is what produced 'Invalid URL ... No scheme supplied' sixteen retries deep."""
    defn = {"id": "autonomous_review",
            "steps": [{"kind": "direct_call", "endpoint": "{dispatch_endpoint}"}]}
    bound = bind_placeholders(defn, {})
    ep = bound["steps"][0]["endpoint"]
    assert "{" not in ep and "}" not in ep, f"an unsubstituted literal survived: {ep!r}"
    assert ep.startswith("http"), f"endpoint has no scheme: {ep!r}"


def test_comments_and_prose_cannot_manufacture_a_requirement():
    """Placeholders are collected from the PARSED definition, so `{...}` inside YAML comments is
    already gone. Guards against a seal that fails on documentation."""
    raw = "# see {placeholders} in the docs\nid: x\nsteps: []\n"
    assert collect_placeholders(yaml.safe_load(raw)) == set()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
