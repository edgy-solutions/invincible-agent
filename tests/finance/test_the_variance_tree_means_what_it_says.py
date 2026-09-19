"""The variance tree's two most documented rules are never exercised by the seed.

R-029's mutate-the-unit check on `fin_variance_analysis`, before the ADR-0053 §7 extraction:

    share_of_root inverted (root/node instead of node/root)  ->  0 red   ⚠ REAL
    the materiality floor removed entirely                   ->  0 red   (equivalent)
    the `depth` stop_reason never reported                   ->  0 red   (equivalent)
    the depth limit off by one                               ->  0 red   (equivalent)
    `favourable` inferred from the sign, not the convention  ->  1 red   ✅

**Measured, which is what separates the finding from the other three:**

    nodes                                    7
    max depth reached                        2
    stop reasons present         {decomposed: 4, leaf: 3}
    stop reasons ABSENT          explained, depth
    nodes where share != its inverse         6
    nodes with a NEGATIVE share_of_root      2

── THE ONE THAT IS REAL ─────────────────────────────────────────────────────────────────────
`share_of_root` is **node over root**. Inverted it becomes root over node — a number that still
looks like a proportion, still sits between −1 and 1 for the larger contributors, and is wrong
on every node but the root itself.

── THE THREE THAT ARE EQUIVALENT, AND WHY THAT IS THE FINDING ───────────────────────────────
**No node in this seed stops on `explained`, and none stops on `depth`.** So the materiality
floor never fires, the depth limit is never reached, and all three mutations produce an
identical tree.

Those are the two rules the docstring argues for at greatest length — *"materiality IS A
FRACTION OF THE ROOT VARIANCE, not of the parent's"*, and *"a truncated tree that looks complete
is the failure this field exists to prevent"*. **The seed contains no case that would tell
either of them from its absence.** The prose is the only thing asserting them.

**Contriving a seed to reach them would be testing the fixture.** The extraction is what makes
them testable: a module taking a tree of quantities directly can be handed a deep hierarchy and
a set of immaterial variances in a few lines each — the third time this pattern has named where
the next test comes from. *A rule becomes checkable by being lifted.* **Pinning both is owed by
the commit that lifts this verb.**

TEST-ONLY. The verb is correct; what was missing is any assertion that it is.
"""
from __future__ import annotations

import pytest

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()
PROGRAM = "NP-MERIDIAN"


def _walk(node, depth=0):
    yield node, depth
    for child in node.get("contributors", ()):
        yield from _walk(child, depth + 1)


@pytest.fixture(scope="module")
def tree():
    out = m.fin_variance_analysis(STATE, program_id=PROGRAM)
    assert len(out) == 1, "the decomposition returns ONE element holding a tree, not a row set"
    return out[0]


@pytest.fixture(scope="module")
def nodes(tree):
    return [n for n, _ in _walk(tree)]


def test_share_of_root_is_NODE_OVER_ROOT(tree, nodes):
    """Inverted it still looks like a proportion and is wrong on every node but the root.

    Recomputed against the tree's own root variance, so this cannot pass by restating the
    expression.
    """
    root = tree["variance"]
    for node in nodes:
        if node.get("share_of_root") is None:
            continue
        assert node["share_of_root"] == pytest.approx(node["variance"] / root), (
            f"{node.get('entity_id', node.get('name'))}: share_of_root is not node/root"
        )


def test_the_share_and_its_INVERSE_differ_on_most_nodes(nodes):
    """THE CONTROL. On a tree where every contributor equals the root the inversion is an
    equivalent mutant — measured: 6 of 7 nodes discriminate here."""
    differing = [n for n in nodes
                 if n.get("share_of_root") not in (None, 0)
                 and n["variance"] != 0
                 and n["share_of_root"] != pytest.approx(1 / n["share_of_root"])]
    assert len(differing) >= 5, f"only {len(differing)} nodes can tell the inversion apart"


def test_a_FAVOURABLE_contributor_inside_an_UNFAVOURABLE_root_carries_two_disagreeing_signs(nodes):
    """THE CASE THE VERDICT EXISTS FOR, and the one mutation that already reddened.

    A favourable contributor inside an unfavourable root has a POSITIVE `variance` and a
    NEGATIVE `share_of_root`. **A card colouring from either number alone would be right about
    half the tree** — which is why `favourable` is emitted by the producer rather than inferred
    by the renderer.
    """
    disagreeing = [n for n in nodes
                   if n.get("share_of_root") is not None
                   and n["variance"] > 0 and n["share_of_root"] < 0]
    assert disagreeing, (
        "no node has a positive variance inside a negative root, so this seed no longer "
        "contains the case the `favourable` verdict was introduced for"
    )
    for node in disagreeing:
        assert node["favourable"] is True, (
            f"{node.get('entity_id')}: a positive variance in a cost decomposition is "
            f"favourable by the convention, whatever its share's sign says"
        )


def test_every_node_that_stops_SAYS_WHY(nodes):
    """A stop with no reason leaves a reader inferring completeness from an absent list."""
    for node in nodes:
        if not node.get("contributors"):
            assert node.get("stop_reason"), (
                f"{node.get('entity_id')} has no contributors and no stop_reason"
            )


def test_the_stop_reasons_present_are_ONLY_the_ones_this_seed_can_produce(nodes):
    """⚠ THE FINDING, ASSERTED AS A FACT ABOUT THE FIXTURE RATHER THAN THE CODE.

    `explained` and `depth` never occur here: the materiality floor never fires and the depth
    limit is never reached. **Three mutations are equivalent because of it** — removing the
    floor, mis-reporting the depth reason, and moving the depth limit by one all produce an
    identical tree.

    This asserts the fixture's reach so the gap is visible in a test run rather than only in a
    commit message. **If a future seed grows a deeper hierarchy or an immaterial contributor,
    this fails and says the three mutations have become detectable** — which is the outcome to
    want, and the signal to go and pin them.
    """
    reasons = {n["stop_reason"] for n in nodes if n.get("stop_reason")}
    assert reasons == {"decomposed", "leaf"}, (
        f"stop reasons are now {reasons}. If `explained` or `depth` appears, the materiality "
        f"floor or the depth limit is finally being exercised — go and seal it, and delete "
        f"this assertion's premise from the module docstring."
    )


def test_materiality_outside_zero_to_one_is_REFUSED():
    """A fraction, not a percentage and not an amount. 25 would silently mean 2500%.

    ASSERTED ON THE EXCEPTION TYPE, not on `Exception`. My first version caught anything at
    all, which would have passed on a TypeError from an unrelated signature change — a seal
    that cannot tell the guard firing from the call breaking.
    """
    from agent_fleet.finance_agent.entities import NotInModel

    for bad in (-0.1, 1.5, 25):
        with pytest.raises(NotInModel):
            m.fin_variance_analysis(STATE, program_id=PROGRAM, materiality=bad)

    # THE POSITIVE CONTROL: a value inside the range must NOT raise, or the seal above is
    # satisfied by a verb that refuses everything.
    assert m.fin_variance_analysis(STATE, program_id=PROGRAM, materiality=0.05)


def test_the_decomposition_returns_ONE_element_holding_a_TREE(tree):
    """Not a flat row set. A variance stated without what produced it is a number nobody can
    act on, so the nesting is the output type rather than a rendering choice."""
    assert tree.get("contributors"), "the root has no contributors; the tree is flat"
    assert any(child.get("contributors") for child in tree["contributors"]), (
        "no second level; the seed no longer exercises nesting at all"
    )
