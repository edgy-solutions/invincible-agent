"""A GATE THAT REMOVES A CANDIDATE MUST LEAVE EVIDENCE.

THE CLASS OF FAILURE. Eligibility gates — domain, arity, argument-fit, permission, the
productive-option gate — each delete candidates, and the record afterwards shows only what
SURVIVED. So an abstention over a pool of one reads as *"the classifier wasn't sure"* when the
truth is *"the gate deleted the answer before the classifier saw it"*. Those need opposite
remedies and nothing downstream could tell them apart.

MEASURED 2026-09-04, and the specific case is why "starved of options" is the wrong mental
model. `idp#Capability` carries TWO verbs under PORTFOLIO_PLANNING. The arity gate removed
`planCapabilityPath`, leaving `planMaturityGrid` — which does not answer "what is the
capability path". The classifier was handed one WRONG candidate and honestly returned UNKNOWN,
and the HUD said "no confident action". **A pool of one looks healthy.** That is the failure
this trace exists to make visible.

WHAT IS ASSERTED HERE IS THE JOIN, not the existence of the halves. Every provenance defect in
this repo has one shape: a producer writes, a consumer reads a different key, both sides pass
their own tests. So the supervisor's emitted key and the gateway's read key are compared against
each other, and every routing return site is counted against the ones that carry the trace —
because a key present on four branches and missing on the fifth is silent exactly there.

DISPOSAL IS TWO-VALUED ON PURPOSE. The arity gate stopped REMOVING on 2026-09-04 — it flags
`needs_instance` and keeps the verb. A trace with only `removed` could not describe the very
gate that motivated it.

Run: uv run --frozen pytest tests/routing/test_eligibility_trace.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
_EO = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")

_KEY = "eligibility_excluded"


# ── the record shape ────────────────────────────────────────────────────────

def test_the_record_carries_gate_reason_and_disposal():
    from iagent.defs.dynamic_supervisor import _eligibility_record

    r = _eligibility_record("mesh:planCapabilityPath", "arity", "needs_instance",
                            disposal="flagged")
    assert r == {
        "kind": "verb",
        "uri": "mesh:planCapabilityPath",
        "gate": "arity",
        "disposal": "flagged",
        "reason": "needs_instance",
    }


def test_it_defaults_to_a_removed_verb():
    from iagent.defs.dynamic_supervisor import _eligibility_record

    r = _eligibility_record("mesh:x", "argument_fit", "missing_required_args:tag")
    assert r["disposal"] == "removed" and r["kind"] == "verb"


def test_the_vocabulary_spans_BOTH_layers():
    """engine-o removes CLASSES, the supervisor removes VERBS, and a reader asking 'why is
    there no answer' does not know which layer ate the option. One vocabulary, or the trace
    sends them to the wrong place with confidence."""
    from iagent.defs.dynamic_supervisor import _eligibility_record

    c = _eligibility_record("idp#Job", "productive_option", "no_verb_in_scope", kind="class")
    assert c["kind"] == "class"
    assert '"kind": "class"' in _EO, "engine-o must emit the same shape it is joined against"


# ── the message distinction, which is the user-facing half ──────────────────

def test_a_clean_abstention_keeps_its_exact_wording():
    """Empty string when nothing was excluded, so callers concatenate unconditionally and
    a genuine 'nothing fit' is not decorated with an explanation it does not have."""
    from iagent.defs.dynamic_supervisor import _abstention_note

    assert _abstention_note([]) == ""
    assert _abstention_note(None) == ""


def test_a_FLAGGED_candidate_is_not_reported_as_removed():
    """The arity gate flags rather than removes. Reporting a kept candidate as excluded
    would send the caller chasing a gate that let it through."""
    from iagent.defs.dynamic_supervisor import _abstention_note

    assert _abstention_note([
        {"uri": "mesh:planCapabilityPath", "gate": "arity",
         "disposal": "flagged", "reason": "needs_instance"},
    ]) == ""


def test_a_removed_candidate_names_the_gate_and_the_reason():
    from iagent.defs.dynamic_supervisor import _abstention_note

    note = _abstention_note([
        {"uri": "http://x/mesh#describeAsset", "gate": "argument_fit",
         "disposal": "removed", "reason": "missing_required_args:tag"},
    ])
    assert "describeAsset" in note
    assert "argument_fit" in note and "missing_required_args:tag" in note
    assert "http://x/mesh#" not in note, "the URI prefix is noise in a sentence a person reads"


def test_many_removals_are_summarised_not_dumped():
    from iagent.defs.dynamic_supervisor import _abstention_note

    note = _abstention_note([
        {"uri": f"mesh:v{i}", "gate": "domain", "disposal": "removed", "reason": "r"}
        for i in range(6)
    ])
    assert "and 3 more" in note


# ── the join: producer key == consumer key ──────────────────────────────────

def test_the_supervisor_emits_the_key_the_gateway_reads():
    assert f'"{_KEY}": MetadataValue.text(' in _SUP, "supervisor does not emit the trace"
    assert f'md.get("{_KEY}")' in _GW, "gateway does not read the trace"


def test_the_gateway_carries_it_wherever_it_carries_the_pool():
    """`candidates` is what survived and `excluded` is what did not. A projection carrying
    one and not the other reintroduces the ambiguity at the render seam."""
    pool = len(re.findall(r'"candidates": candidates,', _GW))
    trace = len(re.findall(r'"excluded": excluded,', _GW))
    assert pool >= 1 and trace == pool, (
        f"{pool} site(s) carry the pool but {trace} carry the trace"
    )


# ── the enumeration: EVERY routing return, not most ─────────────────────────

def _routing_returns() -> int:
    return len(re.findall(r"return _ROUTING_(?:NO_MATCH|MATCHED|INFRA_ERROR), ", _SUP))


def _returns_missing_the_trace() -> list[str]:
    """Every routing return that neither sets the key inline nor reuses the shared dict.

    CHECKED PER SITE, NOT AS A FLOOR. My first version asserted `count >= 4`, and deleting
    the key from the no-compatible-verbs branch left four and stayed GREEN — a mutation that
    passed, which is the aggregate-floor defect inside the test written to prevent it. A
    count cannot say WHICH site is covered, and "which" is the whole question.
    """
    nl = chr(10)
    close = nl + "        }"
    missing = []
    for m in re.finditer(r"return _ROUTING_(?:NO_MATCH|MATCHED|INFRA_ERROR), ", _SUP):
        tail = _SUP[m.start():m.start() + 1600]
        head = tail[: tail.index(nl)] if nl in tail else tail
        # A return handing back the shared `telemetry` dict inherits the key from it.
        if head.rstrip().endswith("telemetry"):
            continue
        body = tail[: tail.index(close) + len(close)] if close in tail else tail
        if _KEY not in body:
            missing.append(head.strip())
    return missing


def test_every_routing_return_carries_the_trace():
    """THE PART THAT BREAKS. Three of the five return sites build their OWN telemetry dict
    rather than using the shared one, and the abstention branches are among them — so a key
    added only to the happy path is missing exactly where it explains the most."""
    assert _routing_returns() == 5, (
        f"expected 5 routing returns, found {_routing_returns()} — if a path was added, it "
        f"needs the trace deliberately"
    )
    missing = _returns_missing_the_trace()
    assert not missing, f"routing return(s) with no eligibility trace: {missing}"


def test_the_shared_telemetry_dict_really_has_it():
    """The per-site check above SKIPS returns that hand back `telemetry`, so that skip must
    be earned — otherwise two of five sites are exempted by an assumption."""
    i = _SUP.index("    telemetry = {")
    assert _KEY in _SUP[i:i + 3000]


def test_the_subject_UNKNOWN_branch_carries_the_CLASS_removals():
    """The verb gates have not run there — but the productive-option gate has, and a class
    it removed is a live reason grounding failed. Blind on the branch that most needs it."""
    i = _SUP.index('"subject_uri": "UNKNOWN",')
    window = _SUP[i:i + 1200]
    assert _KEY in window
    assert "subject_excluded" in window


# ── engine-o's half ─────────────────────────────────────────────────────────

def test_engine_o_returns_the_trace_on_every_resolve_that_returns_a_pool():
    pool = len(re.findall(r"candidates=candidates,", _EO))
    trace = len(re.findall(r"excluded=_gate_excluded,", _EO))
    assert trace >= 1
    assert trace == pool - 1 or trace == pool, (
        f"{pool} return(s) carry candidates but {trace} carry the trace"
    )


def test_engine_o_declares_the_field_on_the_response_model():
    assert "excluded: list[dict] = Field(default_factory=list)" in _EO


def test_the_supervisor_actually_reads_engine_os_half():
    """A field returned and never consumed is the orphan shape. This is the cross-service
    hop, and it is the one nobody's own tests cover."""
    assert 'data.get("excluded")' in _SUP
    assert "subject_excluded" in _SUP
