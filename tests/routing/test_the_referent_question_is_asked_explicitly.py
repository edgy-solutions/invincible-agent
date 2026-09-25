"""`include_referents` is two questions, and the default must be the recoverable mistake.

WHAT THIS CHANGE DID NOT DO: change behaviour. `_served_class_uris` has exactly two callers;
the post-preemption check already passed `include_referents=False` explicitly, and the gate
relied on the default `True`. Flipping the default to `False` and making the gate explicit
leaves both of today's answers bit-identical. **Every pre-existing test therefore passes
before and after, and none of them is evidence.** That is the whole reason this file exists
and the reason it cannot be a before/after comparison at the call sites.

WHAT IT DID DO is decide what a THIRD caller gets for free. The flag selects between "may the
resolver OFFER this class?" (referents in — a declared `mesh:ResolvableReferent` grounds on
purpose) and "can this class be ANSWERED?" (referents out — a referent is precisely what
cannot). Omitting it by accident is possible in both directions and the two are not equally
survivable: too strict narrows the pool and surfaces as a refusal someone reports, too loose
widens it and surfaces as the generalist answering confidently about a dead end, which is the
failure both gates were built to remove. The strict question is the default for that reason.

THE DISCRIMINATING POPULATION DOES NOT EXIST IN THE LIVE GRAPH. Measured by lane eo on
2026-09-04 and unchanged as of this writing: the referent set is EMPTY, so both questions
return the same set for every real class and an observational test would pass against a
single shared predicate. The fixture below CREATES the state instead — one class under
`mesh:ResolvableReferent` — and `assert_fixture_discriminates` refuses the pair if it ever
stops separating the two answers.

WHERE THE DOUBLE STOPS, STATED RATHER THAN PAPERED OVER. `_served_class_uris`'s entire
contribution to the distinction is one parameter substitution: `referent_root` is the root URI
or `None`. That is sealed exactly, by capture. The step from `referent_root=None` to "the
UNION's second leg contributes no rows" is Cypher's null-comparison semantics, which no
in-process double can execute — the fixture driver ENCODES that semantic as an assumption, so
it cannot catch a Cypher rewrite that breaks it. `test_the_cypher_keeps_the_construct...`
covers that blind spot from the text side, which is the only side available offline.

Run: uv run --frozen pytest tests/routing/test_the_referent_question_is_asked_explicitly.py -v
"""
from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path

import pytest
from iagent_mesh.conformance import assert_fixture_discriminates

from agent_fleet.ontology_service import main as m

_REPO = Path(__file__).resolve().parents[2]
_SRC = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")

_FN = "_served_class_uris"

#: A class carrying a verb, and a class that only grounds. Neither needs to be real: the
#: fixture's job is to hold two classes the two questions must sort differently.
VERB_CLASS = "http://invincible-agent/fin#Program"
REFERENT_CLASS = "http://invincible-agent/fin#WBSElement"


# ── the declaration ─────────────────────────────────────────────────────────

def test_THE_DEFAULT_IS_THE_STRICT_QUESTION():
    """Read off the signature object, never restated as a literal from the source text.

    A default asserted by matching source text passes on a file that says `= False` in a
    docstring and `= True` in the signature.
    """
    default = inspect.signature(getattr(m, _FN)).parameters["include_referents"].default

    assert default is False, (
        f"{_FN} defaults include_referents to {default!r}. A caller who omits it then gets the "
        f"OFFER question, and a class that grounds-but-cannot-answer counts as served — the "
        f"generalist-on-a-dead-end failure, reached by writing less code rather than more"
    )


def _calls() -> dict[str, dict]:
    """Every call to `_served_class_uris`, keyed by the function that makes it.

    A CENSUS, NOT A SAMPLE, and that is the point of walking the AST rather than grepping two
    known lines: the hole this change closes is a FUTURE third caller, so the arm has to
    enumerate callers rather than check the two that exist today.
    """
    tree = ast.parse(_SRC)
    found: dict[str, dict] = {}

    def walk(node, enclosing: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
                continue
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id == _FN):
                kwargs = {k.arg: k.value for k in child.keywords if k.arg}
                found[enclosing] = kwargs
            walk(child, enclosing)

    walk(tree, "<module>")
    return found


def test_EVERY_CALLER_ASKS_ITS_QUESTION_EXPLICITLY():
    """No call site may rely on the default, whichever way the default points.

    With the flag explicit at every site, changing the default can never silently move a
    caller's question — and a new caller that omits it reds HERE, at the moment it is added,
    instead of at whatever routing symptom it eventually produces.
    """
    calls = _calls()

    assert len(calls) >= 2, (
        f"found {len(calls)} call sites to {_FN} ({sorted(calls)}); the two known callers are "
        f"the productive-option gate and the post-preemption check — if one has gone, this "
        f"arm is measuring a file that no longer matches its subject"
    )
    silent = sorted(fn for fn, kwargs in calls.items() if "include_referents" not in kwargs)
    assert not silent, (
        f"{silent} call {_FN} without naming include_referents, so their question is whatever "
        f"the default happens to be today"
    )


def test_THE_TWO_CALLERS_ASK_OPPOSITE_QUESTIONS():
    """And they must be opposite, or one of the two gates is asking the other's question.

    Both-True would let the post-preemption check treat a referent as answerable, which is the
    override it was ruled into existence to catch. Both-False would drop every declared
    referent out of the candidate pool, so "lot 4" stops being offerable at all.
    """
    values = {fn: ast.literal_eval(node) for fn, node in
              ((fn, kwargs["include_referents"]) for fn, kwargs in _calls().items()
               if "include_referents" in kwargs)}

    assert set(values.values()) == {True, False}, (
        f"the call sites ask {values} — the gate asks 'may we OFFER this' (True) and the "
        f"post-preemption check asks 'can this be ANSWERED' (False); if they agree, one of "
        f"them is asking a question it was not built for"
    )
    answer_side = [fn for fn, v in values.items() if v is False]
    assert any("preempt" in fn or "unanswerable" in fn for fn in answer_side), (
        f"the caller passing False is {answer_side}, which is not the post-preemption check — "
        f"the strict question belongs to the check that asks whether a subject can be answered"
    )


# ── the parameter, and then the two answers ─────────────────────────────────

class _Session:
    """Records the parameters and answers the way the store's null semantics would."""

    def __init__(self, captured: list) -> None:
        self._captured = captured

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def run(self, _cypher, **params):
        self._captured.append(params)
        rows = [{"uri": VERB_CLASS}]
        # ENCODED ASSUMPTION, NOT A MEASUREMENT: the Cypher's second leg is
        # `WHERE m.uri = $referent_root`, and comparing to a null parameter yields null rather
        # than true, so that leg contributes nothing. This double cannot execute Cypher; it
        # reproduces that one semantic so the arms below can reach the two different answers.
        if params.get("referent_root") is not None:
            rows.append({"uri": REFERENT_CLASS})
        return rows


class _Driver:
    def __init__(self) -> None:
        self.captured: list = []

    def session(self) -> _Session:
        return _Session(self.captured)


@pytest.fixture()
def driver(monkeypatch):
    """A fresh driver AND an empty cache.

    The cache key carries the flag, so a leaked entry from a previous arm would answer the
    other question and read as a pass.
    """
    d = _Driver()
    monkeypatch.setattr(m, "_NEO4J_DRIVER", d)
    monkeypatch.setattr(m, "_SERVED_CACHE", {})
    return d


def _ask(include_referents: bool) -> frozenset:
    return asyncio.run(getattr(m, _FN)(["PROGRAM_FINANCE"], include_referents=include_referents))


def test_the_flag_IS_the_cypher_parameter(driver):
    """Main.py's entire contribution to the distinction, sealed where it actually happens."""
    _ask(True)
    _ask(False)

    # ASSERTED BEFORE THE UNPACK, because a tuple unpack is not a diagnostic. Measured while
    # mutation-testing this file: dropping the flag from the cache key served the first answer
    # to the second caller, the store saw one query, and this arm died on
    # `ValueError: not enough values to unpack` — a red that names neither the cache nor the
    # flag. A mutation that dies in an arm's setup reads as the arm firing and explains nothing.
    assert len(driver.captured) == 2, (
        f"two distinct questions reached the store {len(driver.captured)} time(s) "
        f"({driver.captured}); one query for both means something served a cached answer "
        f"across the flag, and the parameters below cannot be compared"
    )
    offered, answerable = driver.captured

    assert_fixture_discriminates(
        "referent_root by flag", offered, answerable,
        describe=lambda p: p["referent_root"],
    )
    assert offered["referent_root"] == m._RESOLVABLE_REFERENT_ROOT, (
        f"the OFFER question sent referent_root={offered['referent_root']!r}; the UNION leg "
        f"matches on that value, so any other value walks to no referent at all"
    )
    assert answerable["referent_root"] is None, (
        f"the ANSWER question sent referent_root={answerable['referent_root']!r} — it must be "
        f"None, which is how the reach changes without a second query to keep in step"
    )


def test_THE_TWO_QUESTIONS_RETURN_DIFFERENT_SETS_when_a_referent_exists(driver):
    """The arm the live graph cannot supply, because its referent set is empty.

    A declared referent must be IN the offerable set and OUT of the answerable one. This is
    the property a single shared predicate would violate, and the reason the parameter exists
    rather than both callers sharing one call.
    """
    offerable = _ask(True)
    answerable = _ask(False)

    assert_fixture_discriminates("offer vs answer", offerable, answerable, describe=sorted)
    assert REFERENT_CLASS in offerable, (
        f"the declared referent is not offerable ({sorted(offerable)}); a class that grounds "
        f"on purpose must stay in the candidate pool or naming it stops working"
    )
    assert REFERENT_CLASS not in answerable, (
        f"the declared referent counts as answerable ({sorted(answerable)}) — the post-"
        f"preemption check would accept a subject nothing can answer about"
    )
    assert VERB_CLASS in offerable and VERB_CLASS in answerable, (
        f"a verb-carrying class fell out of one of the two sets (offerable={sorted(offerable)}, "
        f"answerable={sorted(answerable)}); the flag must move referents and nothing else"
    )


def test_the_cache_does_not_conflate_the_two_questions(driver):
    """One key for two questions would make whichever ran first the answer to both.

    The TTL is 120s by default, so a shared key would not be a rare race — it would be the
    normal case for two minutes after any request.
    """
    _ask(True)
    _ask(False)

    assert len(m._SERVED_CACHE) == 2, (
        f"two questions over the same domains produced {len(m._SERVED_CACHE)} cache entries "
        f"({sorted(m._SERVED_CACHE)}); the key must carry the flag or the first caller's "
        f"answer is served to the second"
    )
    assert len(driver.captured) == 2, (
        f"the store was queried {len(driver.captured)} times for two distinct questions — a "
        f"cache hit across the flag is the conflation this arm exists to catch"
    )


def test_the_cypher_keeps_the_construct_the_double_ASSUMES():
    """THE DOUBLE'S BLIND SPOT, COVERED FROM THE ONLY OTHER SIDE AVAILABLE OFFLINE.

    Every arm above reaches "referents are excluded" through a fixture that was told to
    exclude them when the parameter is None. If the Cypher were rewritten so a null root
    matched everything — `coalesce($referent_root, m.uri)`, an OPTIONAL MATCH, a
    `$referent_root IS NULL OR ...` disjunction — every arm above would stay green and the
    answerable set would silently swallow every referent. This is a text assertion because the
    property belongs to the store, and the honest offline form of it is to pin the construct.
    """
    cypher = m._SERVED_CLASSES_CYPHER

    assert "m.uri = $referent_root" in cypher, (
        "the referent UNION leg no longer selects on `m.uri = $referent_root`. The null-root "
        "switch-off depends on that comparison yielding null rather than true; if the leg has "
        "been rewritten, re-derive whether a null root still contributes nothing AGAINST THE "
        "STORE, because the fixture in this file assumes it does and cannot tell you"
    )
    assert "coalesce($referent_root" not in cypher, (
        "a coalesce over $referent_root gives the null root a substitute value, which turns "
        "the switched-off leg back on"
    )
