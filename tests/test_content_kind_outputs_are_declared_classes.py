"""Every class a content-kind row says it OUTPUTS is a class the ontology declares.

A row's `outputs` is what the seam stamps on what a drop produces. A name that no ontology
declares is a phantom: the row composes, the drop is accepted, and the stamp points at nothing.
doc-tools named two such phantoms on 2026-10-07 (`mesh:DoorsExportArtifact`,
`mesh:EngineeringDocumentArtifact`).

The population is derived from both sides: every row under `policy/overlays/*/content_kinds/`
and `policy/content_kinds/`, and every prefix and class declared in `setup/ontologies/*.ttl`.
An output whose prefix no ontology declares is red. It does not pass through, because an unknown
prefix is exactly how a misspelt namespace would otherwise read as fine.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

_REPO = Path(__file__).resolve().parents[1]
_ONTOLOGIES = sorted((_REPO / "setup" / "ontologies").glob("*.ttl"))
_ROWS = sorted(
    [*(_REPO / "policy" / "content_kinds").glob("*.yaml"),
     *(_REPO / "policy" / "overlays").glob("*/content_kinds/*.yaml")]
)
_PREFIX = re.compile(r"^@prefix\s+(\w*):\s*<([^>]+)>\s*\.", re.M)


def _ontology() -> tuple[Graph, dict[str, set[str]]]:
    g = Graph()
    prefixes: dict[str, set[str]] = {}
    for f in _ONTOLOGIES:
        text = f.read_text(encoding="utf-8")
        for p, ns in _PREFIX.findall(text):
            prefixes.setdefault(p, set()).add(ns)
        g.parse(data=text, format="turtle")
    return g, prefixes


def _outputs() -> list[tuple[str, str]]:
    found = []
    for f in _ROWS:
        row = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for out in row.get("outputs") or ():
            found.append((f"{f.parent.parent.name}/{f.name}", out))
    return found


def _undeclared(outputs, g, prefixes) -> list[str]:
    bad = []
    for where, out in outputs:
        prefix, _, local = out.partition(":")
        nss = prefixes.get(prefix, set())
        if len(nss) != 1:
            bad.append(f"{where}: {out} -- prefix {prefix!r} binds {sorted(nss) or 'nothing'}")
        elif (URIRef(next(iter(nss)) + local), RDF.type, OWL.Class) not in g:
            bad.append(f"{where}: {out} -- not declared `a owl:Class` in setup/ontologies")
    return bad


def test_the_population_is_not_empty():
    # The s1000d row's output is a control: it is declared in mil_extension.ttl.
    assert len(_ONTOLOGIES) >= 10, _ONTOLOGIES
    assert ("openddil-lab/s1000d-data-module.yaml", "mil:DataModule") in _outputs()


def test_the_check_tells_a_declared_class_from_a_phantom():
    g, prefixes = _ontology()
    probe = [("probe", "mil:DataModule"), ("probe", "mesh:NoSuchArtifact"), ("probe", "nsx:Thing")]
    bad = _undeclared(probe, g, prefixes)
    assert len(bad) == 2 and "mesh:NoSuchArtifact" in bad[0] and "'nsx'" in bad[1], bad


def test_every_content_kind_output_is_a_declared_class():
    g, prefixes = _ontology()
    bad = _undeclared(_outputs(), g, prefixes)
    assert not bad, "content-kind outputs that no ontology declares:\n" + "\n".join(bad)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
