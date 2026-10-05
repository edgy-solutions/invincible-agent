"""A maintenance answer's weaviate source names its DMC in `label` (cortex, 2026-10-03).

Cortex draws a source's ``label`` verbatim (SourcesTrail.tsx) and will not parse a DMC out of a
uri. An S1000D chunk's ``doc_id`` is its data module's root URI, minted by doc-tools'
``s1000d_rdf.parse_data_module`` as ``mil#dmc-`` + the canonical DMC. ``source_label`` turns that
back into ``DMC-<canonical>`` through the SAME canonicalizer.

service.py imports the generated BAML client at module scope, so the function is lifted out by
AST and bound to the real ``agent_fleet.utils.dmc_canonicalizer`` -- the canonicalizer is never
stubbed. The WIRING arm is what keeps the lift honest: every ``label =`` in the module outside
the helper must be a ``source_label(...)`` call, and there must be at least the two collectors
measured on 2026-10-04 (a filter that can match nothing passes everything).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from agent_fleet.utils import dmc_canonicalizer as dmc

SERVICE = Path(__file__).resolve().parents[1] / "agent_fleet" / "weaviate_expert" / "service.py"
MIL = "http://edgy-solutions.com/ontology/mil#"  # s1000d_rdf.py:46, the producer's namespace
#: cortex's seal on the rehearsal capture: `DMC-` followed by its hyphenated segments.
DMC_SHAPE = re.compile(r"^DMC-[A-Z0-9]+(-[A-Z0-9]+)+$")

_TREE = ast.parse(SERVICE.read_text(encoding="utf-8"))
_FN = next(n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name == "source_label")


def _source_label():
    ns = {"canonicalize_dmc": dmc.canonicalize_dmc}
    exec(compile(ast.Module(body=[_FN], type_ignores=[]), str(SERVICE), "exec"), ns)
    return ns["source_label"]


def _producer_uri(**f) -> str:
    """The root URI exactly as the S1000D parser mints it: MIL[f"dmc-{assemble(...)}"]."""
    return MIL + "dmc-" + dmc.assemble_canonical_dmc(**f)


RTX = dict(mic="SANDBOXRTX", sdc="C", sysc="95", ssc="4", sssc="0", asy="00",
           dis="00", dvar="A", info="941", ivar="A", itemloc="A")


def test_an_s1000d_chunk_is_labelled_with_its_dmc():
    label = _source_label()(_producer_uri(**RTX))
    assert label == "DMC-SANDBOXRTX-C-95-40-00-00A-941A-A"
    assert DMC_SHAPE.match(label)


def test_the_label_is_canonical_whatever_case_the_fragment_carries():
    uri = MIL + "dmc-sandboxrtx-c-95-40-00-00a-941a-a"
    assert _source_label()(uri) == "DMC-SANDBOXRTX-C-95-40-00-00A-941A-A"


@pytest.mark.parametrize("doc_id", [
    "Unknown Document",                                    # the collector's own fallback
    "unknown-s1000d-dmc",                                  # the parser's no-dmCode sentinel
    MIL + "dmc-NOT-A-DMC",                                 # a dmc- fragment the canonicalizer refuses
    "http://edgy-solutions.com/ontology/dita#topic-abc",   # a non-S1000D root
    "manual.pdf",
])
def test_anything_else_keeps_its_doc_id(doc_id):
    """An honest miss: never a guessed DMC."""
    assert _source_label()(doc_id) == doc_id


def test_the_page_suffix_survives():
    assert _source_label()("manual.pdf", 7) == "manual.pdf · p.7"


def test_every_collector_labels_through_source_label():
    """The wiring: no `label =` outside the helper may build the label any other way."""
    inside = {id(n) for n in ast.walk(_FN)}
    sites, rogue = 0, []
    for node in ast.walk(_TREE):
        if id(node) in inside or not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "label" for t in node.targets):
            continue
        v = node.value
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "source_label":
            sites += 1
        else:
            rogue.append(node.lineno)
    assert not rogue, f"service.py builds a source label without source_label at lines {rogue}"
    assert sites >= 2, f"{sites} collectors call source_label; 2 were measured on 2026-10-04"


def test_both_import_branches_bind_the_shared_canonicalizer():
    """Engine images flatten agent_fleet/utils to /app/utils; both spellings must name it."""
    mods = {n.module for n in ast.walk(_TREE) if isinstance(n, ast.ImportFrom)
            and any(a.name == "canonicalize_dmc" for a in n.names)}
    assert mods == {"utils.dmc_canonicalizer", "agent_fleet.utils.dmc_canonicalizer"}, mods
