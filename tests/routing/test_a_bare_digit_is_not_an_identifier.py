"""A bare integer must not resolve to an instance, and `banana 4` is the permanent control.

THE DEFECT, measured 2026-09-11 by `invincible-agent-81` and reproduced here. The finance
instance provider's token-overlap tier read:

    tokens_h = set(hay_label.split()) | {hay_id}

which put the BARE INSTANCE ID into the haystack's token set. A needle sharing nothing with a
member but a digit therefore scored ``0.4 + 0.2 * (1/2) = 0.500`` -- **exactly** ``_RESOLVE_FLOOR``,
and the gate is ``>=``:

    'lot 4'     -> Program Support (instance_id 4)   0.500
    'site 4'    -> Program Support                   0.500
    'banana 4'  -> Program Support                   0.500   <- fabricated control
    'xyzzy 4'   -> Program Support                   0.500   <- fabricated control
    'lot four'  -> (nothing)
    '4'         -> Program Support                   1.000   <- the EXACT tier, worse

**`banana 4` resolved and `lot four` did not.** That pair is the whole finding: the scorer was
matching on the digit and ignoring the word, which is the opposite of how a name works.

WHY IT WAS NOT A FINANCE BUG. Recipe v2 lets a phone-book class override ``resolved_uri``, so a
0.500 hit on nonsense outranked a 0.92 classifier match that had correctly identified `"lot 4"`'s
`4` as a FILTER rather than the subject. **Any query in any domain containing a bare integer N was
eligible to be preempted onto WBS element N.** Its first live catch was four cost questions
abstaining instead of answering confidently from the wrong ontology -- the post-preemption check
working, on a defect nothing else would have surfaced.

THE THREE RULES, each named to the failure it answers:

1. **A bare number is not a name** unless the caller supplied ``class_uri``. Unscoped it returns
   nothing; scoped it is a legitimate match, because something other than the digit established
   the class.
2. **A contradicted digit disqualifies.** ``lot 9`` against Lot 4 shares the word ``lot`` and
   would otherwise score 0.6 -- a confident WRONG lot, worse than abstaining.
3. **Words establish, digits corroborate.** The id joins the haystack only after a word has
   matched, and a hit that lands ON the floor is not authority: a boundary-value tie is
   indistinguishable from a deliberate pass, and ``>=`` resolves it toward the weakest evidence
   in the system.

Run: uv run --frozen pytest tests/routing/test_a_bare_digit_is_not_an_identifier.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import importlib.util

import pytest


def _load_module_by_path(alias: str, path, *, reason: str):
    """Import `path` under `alias`, or skip — never binding the bare module name."""
    spec = importlib.util.spec_from_file_location(alias, str(path))
    if spec is None or spec.loader is None:
        pytest.skip(reason)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 — an absent engine dep is a skip, not a red
        pytest.skip(f"{reason} ({type(exc).__name__}: {exc})")
    return mod

_REPO = Path(__file__).resolve().parents[2]
_FIN = _REPO / "agent_fleet" / "finance_agent"
if str(_FIN) not in sys.path:
    sys.path.insert(0, str(_FIN))

# LOADED UNDER A UNIQUE NAME, NOT AS `main`. Both this seal and
# `test_an_out_of_domain_hit_is_a_candidate_not_an_authority.py` reach a module FILE called
# `main.py` in different engines. A plain `import main` binds `sys.modules["main"]` to
# whichever ran first, so in a full-suite run one of the two seals silently exercises the
# OTHER engine — 11 reds that are not about the code. Same shape as the dagster stub that
# broke the standalone CI job: a shared module name in sys.modules, resolved by import order.
main = _load_module_by_path("finance_agent_main_under_test", _FIN / "main.py",
                            reason="finance_agent not importable here")


def _resolved(query: str, class_uri: str | None = None):
    """What the provider would actually hand back -- floor applied, as `/resolve_instance` does."""
    return [c for c in main._candidates(query, class_uri) if c["score"] >= main._RESOLVE_FLOOR]


#: Fabricated needles. None of these is a word in any model this engine knows, so a resolution
#: is proof the scorer matched on the digit alone.
_FABRICATED = ["banana 4", "xyzzy 4", "banana 3", "qwerty 1"]

#: Real-looking but out-of-model: these read as identifiers to a human and must still abstain,
#: because `lot`/`site`/`phase` are not finance's nouns.
_PLAUSIBLE_BUT_NOT_OURS = ["lot 4", "site 4", "phase 3"]


@pytest.mark.parametrize("query", _FABRICATED)
def test_A_FABRICATED_NEEDLE_WITH_A_DIGIT_RESOLVES_TO_NOTHING(query):
    """THE PERMANENT CONTROL. If this ever resolves again, the fix regressed."""
    got = _resolved(query)
    assert got == [], (
        f"{query!r} resolved to {[(c['label'], c['score']) for c in got]}. Nothing in that "
        f"needle names anything this engine knows, so the scorer is matching on the bare digit "
        f"again — which makes every query in every domain containing an integer N eligible to "
        f"be preempted onto instance N."
    )


@pytest.mark.parametrize("query", _PLAUSIBLE_BUT_NOT_OURS)
def test_a_plausible_identifier_from_ANOTHER_domain_abstains(query):
    """`lot` and `phase` are real nouns — they are just not finance's."""
    assert _resolved(query) == [], f"{query!r} resolved; it belongs to another domain's vocabulary"


def test_a_BARE_DIGIT_alone_does_not_resolve_when_UNSCOPED():
    """The worst case, because it hit the EXACT tier and returned 1.0 — maximum authority
    from a token that cannot say which collection it indexes."""
    got = _resolved("4")
    assert got == [], f"bare '4' resolved to {[(c['label'], c['score']) for c in got]} at top score"


def test_a_CONTRADICTED_digit_disqualifies_rather_than_scoring_well():
    """Rule 2. Sharing the word and contradicting the number is the confident-wrong-row case."""
    for q in ("lot 9", "control account 999"):
        assert _resolved(q) == [], f"{q!r} resolved despite naming a number nothing carries"


# --------------------------------------------------------------------------------------
# POSITIVE CONTROLS — an absence assertion is vacuously satisfied by a broken producer.
# Every test above asserts that something does NOT resolve. If `_candidates` returned []
# for everything — a bad import, an empty model, a floor of 1.1 — they would all pass while
# measuring nothing. These share the seal's exact gate and report the positive case.
# --------------------------------------------------------------------------------------

def test_CONTROL_a_real_label_still_resolves_exactly():
    """THE CONTROL. Same function, same floor, opposite expectation."""
    members = [m for uri in main._RESOLVABLE for m in main._members_of(uri)]
    assert members, "CONTROL FAILED: the model is empty, so every absence above is vacuous"
    label = members[0]["label"]
    got = _resolved(label)
    assert got, (
        f"CONTROL FAILED: the exact label {label!r} does not resolve. The provider is answering "
        f"nothing for everything, so the refusals asserted above prove nothing."
    )
    assert got[0]["score"] == 1.0, f"exact label {label!r} scored {got[0]['score']}, not 1.0"


def test_CONTROL_a_digit_DOES_resolve_once_the_caller_supplies_the_class():
    """The other half of rule 1, and it keeps the rule from being 'digits never work'.

    Scoped, the caller has established the class by a means other than the digit, so indexing
    into it is legitimate. Without this control the fix would be indistinguishable from
    refusing numeric identity altogether.
    """
    uri = sorted(main._RESOLVABLE)[0]
    assert _resolved("4", uri), (
        f"CONTROL FAILED: '4' scoped to {uri} resolves to nothing. The fix has gone further "
        f"than ruled — a digit is refused as a NAME, not as an INDEX into a named class."
    )
