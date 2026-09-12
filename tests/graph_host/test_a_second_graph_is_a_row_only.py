"""The host is a PLATFORM, not one graph with scaffolding — asserted structurally.

ADR-0046 slice 1's claim is that a team plugs a graph into engine-lg. The evidence is a second
graph admitted WITHOUT TOUCHING THE HOST, and "I didn't need to change main.py" is a claim
rather than a fact. So this file asserts the property that makes it true and keeps it true:

**THE HOST NAMES NO GRAPH.** If `main.py` mentioned any ratified `graph_id`, verb, module or
subject, the host would be graph-specific and the next graph would be a code change. The
assertion is derived from the rows — add a third graph and it covers that one too, with nothing
added here.

WHAT A SECOND GRAPH ACTUALLY COST, recorded because it is the honest version of the claim and
smaller than "just a row" but bigger than nothing:

    policy/graphs/<id>.yaml                      the row            REQUIRED
    agent_fleet/graph_host/graphs/<id>.py        the graph          REQUIRED
    setup/ontologies/<domain>_extension.ttl      its output class   IF the shape is new

That third line is the part a one-line summary loses. Contract D refuses atomically if either
end is absent, so a graph whose output shape genuinely differs needs an ontology declaration
AND A PRIME before its row can register. `cost_lot_costing_review` needed one: the cost domain
declares per-measure classes (LotCostBreakdown, PriceComposition, RateComparison) and none of
them is a composed review. **Reusing the first graph's `mesh:StatefulSupportResponse` would
have avoided the prime and been the Engine B defect** — a stateless graph (`checkpointer:
false`) describing itself with a class named for durable per-thread memory.

AND ONE CLAUSE THE ROW DECLARES THAT NOTHING ENFORCES, named here rather than left to be
discovered: `refusal` is honoured by each graph MODULE, not by the host. A row could declare
`fail` and its module return partial results, and nothing would go red. The two graphs here
differ on it deliberately (`named-hole` vs `fail`) so the declaration is at least exercised in
both directions, but exercised is not enforced. Filed as its own item.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HOST = _ROOT / "agent_fleet" / "graph_host" / "main.py"
_POLICY = _ROOT / "policy" / "graphs"


def _rows():
    from iagent_mesh.graph_manifest import load_manifests

    rows = load_manifests(_POLICY)
    assert rows, f"no ratified rows under {_POLICY} — every assertion below is vacuous"
    return rows


def test_there_are_at_least_two_graphs():
    """POSITIVE CONTROL, and it is the whole point of the phase.

    With one graph, "the host names no graph" is satisfied by a host that happens not to
    mention its only graph, and the platform claim is untested. Two graphs that differ is the
    minimum evidence. If this ever drops back to one, the claim below stops meaning anything
    and should stop passing quietly.
    """
    rows = _rows()
    assert len(rows) >= 2, (
        f"only {len(rows)} ratified graph(s). The platform claim needs a second one to be "
        f"evidence rather than an aspiration — with one graph the host trivially names none."
    )


def test_the_two_graphs_differ_in_what_the_ROW_controls():
    """A second graph matching the first would prove the host can load two files.

    What has to differ is the stuff a row DECLARES, because those are the clauses that make a
    row a contract rather than a filename.
    """
    rows = {m.graph_id: m for m in _rows()}
    a, b = rows["fin_program_brief"], rows["cost_lot_costing_review"]
    assert a.input_uri != b.input_uri, "same subject — the host is not shown to be domain-agnostic"
    assert a.output_uri != b.output_uri, "same output class — one of them is borrowing a noun"
    assert set(a.domains) != set(b.domains), "same domain"
    assert a.refusal != b.refusal, (
        "both graphs declare the same refusal disposition, so the per-row declaration is "
        "never exercised in both directions"
    )
    assert a.checkpointer != b.checkpointer, (
        "both graphs make the same checkpointer choice — the host honouring it PER ROW is "
        "untested, and a module that compiled itself could ignore it either way"
    )
    assert len([s for s in a.slots if s.required]) != len([s for s in b.slots if s.required]), (
        "same number of mandatory slots — the ask path is never made to name WHICH one"
    )


@pytest.mark.parametrize("attr", ["graph_id", "verb", "module", "input_uri", "output_uri", "name"])
def test_the_host_names_no_graph(attr: str):
    """THE PLATFORM CLAIM. Derived from the rows, so a third graph is covered automatically.

    A host mentioning any of these would make the next graph a code change — and it is exactly
    the shape that creeps in as a special case for one graph's quirk.
    """
    host_src = _HOST.read_text(encoding="utf-8")
    offenders = []
    for m in _rows():
        value = getattr(m, attr)
        needle = str(value).split("#")[-1].split(":")[-1]
        # `graphs` alone is the package name, not a graph's identity; match the specific part.
        if len(needle) > 6 and re.search(re.escape(needle), host_src):
            offenders.append(f"{m.graph_id}.{attr} = {needle!r}")
    assert not offenders, (
        "agent_fleet/graph_host/main.py names a specific graph, which makes the host "
        "graph-specific and the next graph a code change rather than a row:\n  "
        + "\n  ".join(offenders)
    )


def test_every_graph_module_is_reachable_only_through_a_row():
    """A module on disk with no row must be unreachable — ADR-0046 §2, from the file side.

    The mesh-side half lives in test_ratified_rows_are_served_by_the_mesh.py; this is the
    cheaper local half, and it catches a module added without its row before a deploy does.
    """
    declared = {m.module.split(".")[-1] for m in _rows()}
    on_disk = {
        p.stem for p in (_ROOT / "agent_fleet" / "graph_host" / "graphs").glob("*.py")
        if p.stem != "__init__"
    }
    orphans = sorted(on_disk - declared)
    assert not orphans, (
        "these graph modules exist with NO ratified row. They are unreachable and "
        "unregistered, which is correct — but an orphan module is a graph somebody meant to "
        "admit and did not, and it will sit there looking admitted:\n  " + "\n  ".join(orphans)
    )
