"""AN ANSWERED ASK MUST NOT RE-DERIVE WHAT THE ASK ALREADY ESTABLISHED.

MEASURED 2026-09-07, on a pair a user actually walked:

    artifact-1-...058552   verb_iri=mesh:planCapabilityPath  disposition=ask
    artifact-2-...429144   verb_iri=mesh:planCapabilityPath  disposition=route
                           accepted_slots={"capability_id": "C8"}  outcome=bound

Clicking one option on a menu cost the whole pipeline -- /plan, /resolve and
/classify_predicate, three model calls -- to arrive at the same verb the ask had already
chosen. The user's report was that a follow-up "takes full time as 1st question", and it did,
because the second turn was not treated as a second turn at all.

WHAT THIS FILE PINS, in the two halves the ruling named:

    1. the route is CARRIED, byte-equal, not recomputed; and
    2. eligibility is still VERIFIED, because a remembered verb is a cache and entitlements,
       registrations and the TTL all change underneath one.

AND THE AUTHORIZATION SEAM, which is new and is the part worth being nervous about.
`answering_artifact_id` has until now only ever drawn a provenance arrow, so a false claim
cost a wrong edge. The moment a named ask steers ROUTING, a caller who could name any
artifact would inherit whatever subject and verb that artifact resolved to. So the client
posts an id and nothing else, and the route is read from the graph under the caller's own
ownership edge. That property is asserted here, not merely intended.

Run: uv run --frozen pytest tests/routing/test_a_pick_is_not_a_new_question.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    fn = next(
        (n for n in ast.walk(ast.parse(src))
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
        None,
    )
    assert fn is not None, f"{name} not found"
    return fn


def _skip_block() -> ast.If:
    """The `if pre_resolved and ...` branch inside the router.

    Found by its TEST EXPRESSION rather than by position or character span -- the fourth
    magic-span rot in this repo happened in the very file that seals this one, and it was
    caused by adding a comment.
    """
    fn = _fn(_SUP, "_classify_route")
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and "pre_resolved" in ast.unparse(n.test):
            return n
    raise AssertionError("_classify_route has no pre_resolved branch")


def _calls(node: ast.AST) -> set[str]:
    return {
        getattr(c.func, "id", getattr(c.func, "attr", ""))
        for c in ast.walk(node) if isinstance(c, ast.Call)
    }


# ── the route is carried, not recomputed ────────────────────────────────────

def test_the_router_accepts_a_pre_resolved_route():
    assert "pre_resolved" in [a.arg for a in _fn(_SUP, "_classify_route").args.args]


def test_the_skip_returns_without_resolving_the_subject_again():
    """/resolve is ~18s of BAML answering a question the ask already answered."""
    block = _skip_block()
    assert any(isinstance(n, ast.Return) for n in ast.walk(block)), (
        "the pre-resolved branch never returns — it would fall through and resolve anyway"
    )
    assert "_resolve_subject" not in _calls(block), (
        "the pre-resolved branch calls _resolve_subject; nothing has been skipped"
    )


def test_the_skip_makes_NO_HTTP_CALL_BUT_THE_VERIFIER():
    """The second model call, choosing a verb that was already chosen.

    ASSERTED ON THE CALLS, NOT ON THE TEXT. The first version of this checked that
    "classify_predicate" did not appear in the branch's source -- and it matched the
    branch's own log line, which says "/resolve and /classify_predicate skipped". An
    absence assertion satisfied by the comment describing the absence is the same defect
    this repo filed when a `requests.post`-absence check matched the note explaining why
    there was no `requests.post`. Prose describing a defect satisfies a text grep.
    """
    calls = _calls(_skip_block())
    assert "post" not in calls, f"the pre-resolved branch makes an HTTP call: {sorted(calls)}"
    assert "_find_compatible_verbs" in calls, "the verifier is the one call that must remain"


def test_the_subject_and_verb_are_carried_BYTE_EQUAL():
    """THE RULING'S FIRST HALF. Not "a subject is present" — the SAME subject. Any
    normalisation, prefix-expansion or re-casing here would silently route somewhere else
    while every other assertion in this file still passed, and this repo has already shipped
    a prefix bug that registered fine and never matched."""
    # EXACT VALUE EXPRESSION, NOT A SUBSTRING. The first version asserted the assignment text
    # was `in` the block's source, and a mutation appending `.lower()` SURVIVED it -- the
    # substring is still present in `str(pre_resolved['subject_uri']).lower()`. A survivor on
    # healthy code is a fact about the test's reach, and this one would have missed exactly
    # the class of change it exists to catch: a silent normalisation that routes elsewhere.
    #
    # Single quotes throughout: `ast.unparse` normalises string literals.
    expected = {
        "_pre_subject": "str(pre_resolved['subject_uri'])",
        "_pre_verb": "str(pre_resolved['verb_iri'])",
    }
    seen = {}
    for n in ast.walk(_skip_block()):
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            t = n.targets[0]
            if isinstance(t, ast.Name) and t.id in expected:
                seen[t.id] = ast.unparse(n.value)
    assert seen == expected, (
        f"the subject/verb are not carried unchanged: {seen} != {expected} — any transform "
        f"here routes somewhere the ask did not choose"
    )


# ── but eligibility is still verified ───────────────────────────────────────

def test_the_ELIGIBILITY_VERIFIER_still_runs():
    """THE RULING'S SECOND HALF, and the positive control for every assertion above: a
    branch that skipped everything would satisfy all of them. /find_compatible_verbs is a
    graph read, not a model call, and it is the authority on dispatch coordinates. Skipping
    it would make the ask's verb a cache with no invalidation — entitlements are revoked,
    engines are retired, the TTL is re-primed."""
    assert "_find_compatible_verbs" in _calls(_skip_block())


def test_a_verb_that_is_no_longer_compatible_FALLS_THROUGH():
    """It must route the full path, not abstain. The worst outcome of a miss is a slow
    answer, which is exactly today's behaviour; refusing would be a regression."""
    fn = _fn(_SUP, "_classify_route")
    resolves = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "_resolve_subject"
    ]
    assert resolves, "the full path is gone — a rejected pre-resolved route has nowhere to go"
    assert "_resolve_subject" not in _calls(_skip_block())


def test_the_predicate_is_built_by_the_ONE_shared_builder():
    """Two dicts that agree on today's fields drift on the next field added to one. This
    repo has already paid for that exact shape once, with two rules for picking the primary
    subtask that agreed in a docstring and disagreed in production."""
    assert "_predicate_from_compat_record" in _calls(_skip_block())
    assert _SUP.count("_predicate_from_compat_record(") >= 3, (
        "expected the definition plus both callers"
    )


def test_the_record_SAYS_it_was_pre_resolved():
    """A confident route with a one-verb candidate pool is indistinguishable from a
    classifier that considered one option. Unlabelled, the decision panel would read as a
    deliberate narrow choice — the reads-as-deliberate shape this repo keeps finding."""
    assert "'pre_resolved': True" in ast.unparse(_skip_block())


# ── the authorization seam ──────────────────────────────────────────────────

def test_the_route_is_READ_from_the_graph_not_POSTED_by_the_client():
    """THE SECURITY PROPERTY. A client that could post a verb could route anywhere."""
    # THE ADMISSION DOOR, not every request model in the file. The first version of this
    # scanned everything ending in "Request" and flagged `DecisionSubgraphRequest.subject_uri`
    # -- which is correct code: that endpoint walks a subClassOf chain to RENDER the decision
    # map, and a caller naming the subject it wants drawn dispatches nothing.
    #
    # Narrowed to the property actually being defended rather than deleted, because the two
    # are genuinely different: reading structure a caller names is safe, DISPATCHING a verb a
    # caller names is not. `InterviewRequest` is the only model that reaches
    # `_launch_supervisor_job`, so it is the only one where a posted route would become a
    # route taken.
    door = next(
        c for c in ast.walk(ast.parse(_GW))
        if isinstance(c, ast.ClassDef) and c.name == "InterviewRequest"
    )
    offenders = [
        stmt.target.id for stmt in door.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        and stmt.target.id in ("verb_iri", "subject_uri", "pre_resolved", "resolved_intent")
    ]
    assert not offenders, (
        f"InterviewRequest declares a route: {offenders} — a client that can post a verb can "
        f"route anywhere, and the ask id would stop being the only thing it names"
    )


def test_the_admission_door_still_takes_only_an_ID():
    """Non-vacuity for the assertion above, and the positive half of it: the lineage claim
    must still be there. A model with no `answering_artifact_id` would satisfy the
    forbidden-field check perfectly while having removed the feature."""
    door = next(
        c for c in ast.walk(ast.parse(_GW))
        if isinstance(c, ast.ClassDef) and c.name == "InterviewRequest"
    )
    fields = {
        stmt.target.id for stmt in door.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    }
    assert "answering_artifact_id" in fields, "the ask id is gone; nothing can be pre-resolved"
    assert "bound_slots" in fields, "the pick is gone"


def test_there_ARE_request_models_to_have_checked():
    """Non-vacuity: zero request models would satisfy the assertion above and prove nothing."""
    names = [
        c.name for c in ast.walk(ast.parse(_GW))
        if isinstance(c, ast.ClassDef) and c.name.endswith("Request")
    ]
    assert len(names) >= 3, f"only found {names}"
    assert "InterviewRequest" in names, "the admission door is not among the models checked"


def test_the_lookup_is_scoped_to_the_CALLER_S_OWN_ARTIFACT():
    """Scoped in the MATCH itself rather than fetched-then-checked: a filter applied after
    the read is one early return away from being skipped."""
    i = _GW.index("_PRE_RESOLVED_CYPHER")
    cypher = _GW[i:i + 400]
    assert "PRODUCED_FOR" in cypher, "the lookup does not join the ownership edge"
    assert "$user_id" in cypher, "the lookup is not parameterised by the caller"


def test_an_unknown_or_foreign_ask_yields_no_route():
    """Every uncertainty routes the ordinary way. There is no failure mode here that should
    produce a ROUTE — a half-known route dispatches a verb against a subject nobody
    confirmed, which is the one outcome worse than a slow answer."""
    fn = _fn(_GW, "_pre_resolved_from_ask")
    src = ast.unparse(fn)
    assert src.count("return {}") >= 4, (
        "the lookup does not degrade to 'no route' on every failure path"
    )
    assert "subject == 'UNKNOWN'" in src, "an UNKNOWN subject is treated as a usable route"


def test_BOTH_halves_or_neither():
    """A verb without its subject is not a dispatchable route (ADR-0019 Contract B), and an
    artifact written before the subject was captured must land on the full path rather than
    dispatching a verb against nothing."""
    src = ast.unparse(_fn(_GW, "_pre_resolved_from_ask"))
    assert "if not subject or not verb" in src


# ── the plan is not re-decomposed either ────────────────────────────────────

def test_a_pre_resolved_turn_does_not_call_the_planner():
    """/plan is the third model call. An answered ask is not a new question and has nothing
    to decompose."""
    assert "if _pre_resolved:" in _GW
    i = _GW.index("if _pre_resolved:\n        task_plan_json = json.dumps(")
    assert '"sub_query": user_query,' in _GW[i:i + 600], (
        "the synthesized task does not carry the user's phrase verbatim"
    )


def test_the_synthesized_phrase_is_NOT_composed():
    """The rewrite fold: the phrase the router sees stays byte-equal to what the person
    asked, and the answer rides beside it in bound_slots. A composed
    'question (slot: value)' string is machine syntax rendered as the user's words."""
    i = _GW.index("if _pre_resolved:\n        task_plan_json = json.dumps(")
    window = _GW[i:i + 600]
    for bad in ("f\"", "+ user_query", "user_query +", ".format("):
        assert bad not in window, f"the sub_query is being composed ({bad})"


def test_the_roster_still_has_a_cast():
    """Skipping /plan must not silently empty the HUD's plan step. The gateway consumes
    `active_agent_roster` to fire it, so the persona is carried rather than dropped — a
    visible regression traded for a latency win is not a trade to make silently."""
    i = _GW.index("if _pre_resolved:\n        task_plan_json = json.dumps(")
    assert '"target_persona": _pre_resolved.get("owner_persona")' in _GW[i:i + 600]


def test_the_ARITY_GATE_runs_on_the_pre_resolved_path_too():
    """FOUND BY READING THE CODE I HAD JUST WRITTEN, not by a failing test.

    `needs_instance` is not a property of the verb record as Neo4j returns it —
    `_filter_verbs_by_arity` puts it there. The pre-resolved branch read
    `_pre_truth.get("needs_instance")` without running the filter, so the flag was never set
    and the dispatch precondition that ABSTAINS on a single-asset verb with no askable slot
    could not fire. A set query would have dispatched a verb needing an instance, on this
    path only, while the full path correctly asked.

    The enumeration law, biting a site I added myself: a registration property must be named
    at every site, and a missed one is silent by construction.
    """
    assert "_filter_verbs_by_arity" in _calls(_skip_block()), (
        "the pre-resolved path never flags needs_instance, so the arity precondition "
        "downstream cannot fire"
    )


def test_the_arity_flag_is_applied_BEFORE_the_verb_is_chosen():
    """Ordering, not just presence. Filtering after the lookup would leave `_pre_truth`
    pointing at the unflagged record — the filter would run and change nothing."""
    src = ast.unparse(_skip_block())
    assert src.index("_filter_verbs_by_arity") < src.index("_pre_truth = next"), (
        "the arity filter runs after the verb is selected; the flag never reaches it"
    )


# ── the fourth model call, which the first pass missed ──────────────────────

def _handler() -> ast.AST:
    """The streaming interview handler — located by the route it serves."""
    tree = ast.parse(_GW)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            src = ast.unparse(n)
            if "/route_intent" in src and "_pre_resolved_from_ask" in src:
                return n
    raise AssertionError("no handler calls both /route_intent and the pre-resolved lookup")


def test_the_pre_resolved_LOOKUP_precedes_the_intent_EXTRACTION():
    """MEASURED 2026-09-08: 5.4s of a 40s pick, gone before anything could decide it was
    unwanted. `/route_intent` runs ExtractIntent — a model call — and it sat AHEAD of the
    lookup that would have said this turn already knows its subject and verb.

    ORDERING IS THE WHOLE PROPERTY. A skip placed after the thing it skips is not a skip; it
    is a discard. The three-calls-skipped claim in the previous commit was true and
    incomplete for exactly this reason.
    """
    src = ast.unparse(_handler())
    lookup = src.index("_pre_resolved_from_ask")
    extract = src.index("/route_intent")
    assert lookup < extract, (
        "the intent extraction runs before the pre-resolved lookup — a pick pays for a model "
        "call whose output this path then discards"
    )


def test_a_pre_resolved_turn_SKIPS_the_intent_extraction():
    """The branch itself. Asserted on the AST so prose about skipping cannot satisfy it —
    an absence check over source text was satisfied by its own comment once already today.

    THE FIRST VERSION OF THIS SURVIVED ITS OWN MUTATION. It looked for any `If` testing
    `_pre_resolved` whose body lacked `route_intent` — and the LOGGING branch a few lines
    above (`if _pre_resolved: logger.info(...)`) satisfies that perfectly. Replacing the real
    branch with `elif False:` left the test green. Asserting on the neighbour rather than the
    claim, which is the defect I have filed against myself twice before.

    Pinned to the CHAIN now: the branch must skip the call while its own alternative makes
    it. That is a property only the real if/elif can have.
    """
    fn = _handler()
    guarded = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.If)
        and "_pre_resolved" in ast.unparse(n.test)
        and "route_intent" not in ast.unparse(n.body)
        and "route_intent" in ast.unparse(n.orelse)
    ]
    assert guarded, (
        "no branch skips /route_intent when the route is already known — a branch that "
        "merely logs is not a skip"
    )


def test_the_extraction_still_runs_for_an_ORDINARY_question():
    """THE CONTROL. A handler that never extracts intent would satisfy the assertions above
    while breaking every first question — which is the majority of traffic."""
    src = ast.unparse(_handler())
    assert "/route_intent" in src, "the intent extraction is gone entirely"
    assert "ExtractIntent" in _GW or "intent_extraction" in src, (
        "nothing consumes an extraction any more — the control is vacuous"
    )
