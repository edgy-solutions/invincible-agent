"""The risk matrix, READ FROM THE RATIFIED FILE — never held as a copy in code.

THIS MODULE IS ADR-0051 §2 MADE OPERATIONAL, and seal 4 is what proves it. Change one row in
`setup/ontologies/safety_risk_matrix.ttl` and the drafted risk level changes with no code edit;
hardcode the table here and the seal goes red. The whole argument for the matrix being data is
that the second programme is an overlay file rather than a fork of the drafting engine, and that
argument is only true while this module refuses to know the answer.

── WHAT THIS READS TODAY, AND WHAT IT WILL READ ────────────────────────────────────────────
Today: the TTL on disk, so the derivation runs offline and the seal needs no cluster.
Increment 5: the PRIMED GRAPH, because the ratified artifact at runtime is what the prime
loaded, not what happens to be in a working tree. The parse is deliberately confined to this
module so that swap is one function, and `SAFETY_RISK_MATRIX_TTL` exists so a deployment can
point at the file it actually primed rather than a path this repo guessed.

── THE REFUSAL IS THE POINT ────────────────────────────────────────────────────────────────
An unrecognized severity or probability RESOLVES TO NOTHING and the caller refuses loudly,
naming the vocabulary's source file (seal 5). It is never coerced to a neighbouring cell and
never defaulted to the bottom of the matrix — which would read as *assessed and negligible*,
the optimistic-default dishonesty this domain can least afford.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

_SAFETY = "http://internal/sustainment/safety#"

#: Repo-relative default. Overridable so a deployment names the file it primed.
_DEFAULT_TTL = (
    Path(__file__).resolve().parents[2] / "setup" / "ontologies" / "safety_risk_matrix.ttl"
)

#: (severity_code, probability_code) -> (risk_level_label, acceptance_audience)
_CELLS: Optional[Dict[Tuple[str, str], Tuple[str, str]]] = None
_SOURCE: str = ""


def matrix_path() -> Path:
    return Path(os.getenv("SAFETY_RISK_MATRIX_TTL", str(_DEFAULT_TTL)))


def _load() -> Dict[Tuple[str, str], Tuple[str, str]]:
    """Parse the ratified TTL into cells. Cached, because a verb must not re-parse per call.

    RAISES RATHER THAN RETURNING EMPTY if the file yields no cells. An empty matrix would flow
    into "this pair is not a cell" and every draft would refuse with a message blaming the
    hazard's data — an instrument failure wearing a finding's clothes, which is the shape this
    repo has paid for more than once.
    """
    global _CELLS, _SOURCE
    if _CELLS is not None:
        return _CELLS

    import rdflib

    path = matrix_path()
    g = rdflib.Graph()
    g.parse(str(path), format="turtle")
    _SOURCE = path.name

    S = rdflib.Namespace(_SAFETY)
    # level IRI -> (label, audience)
    levels: Dict[str, Tuple[str, str]] = {}
    for lvl in set(g.subjects(S.acceptanceAudience, None)):
        label = g.value(lvl, rdflib.RDFS.label)
        audience = g.value(lvl, S.acceptanceAudience)
        if label is not None and audience is not None:
            levels[str(lvl)] = (str(label), str(audience))

    cells: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for cell in set(g.subjects(S.whenSeverity, None)):
        sev = g.value(cell, S.whenSeverity)
        prob = g.value(cell, S.whenProbability)
        lvl = g.value(cell, S.yieldsRiskLevel)
        if sev is None or prob is None or lvl is None:
            continue
        resolved = levels.get(str(lvl))
        if resolved is None:
            continue
        cells[(str(sev), str(prob))] = resolved

    if not cells:
        raise AssertionError(
            f"{path} yielded ZERO matrix cells — instrument failure, not an empty matrix. "
            "Refusing to resolve any risk level rather than reporting every hazard as "
            "out-of-vocabulary."
        )
    _CELLS = cells
    return cells


def resolve_risk_level(severity: str, probability: str) -> Tuple[Optional[str], Optional[str], str]:
    """(risk_level, acceptance_audience, source) — or (None, None, source) if not a cell.

    Returning the SOURCE on both paths is deliberate: a refusal that cannot name the vocabulary
    it consulted sends the reader looking for the wrong file.
    """
    cells = _load()
    hit = cells.get((severity, probability))
    if hit is None:
        return None, None, _SOURCE
    return hit[0], hit[1], _SOURCE


def known_cells() -> Dict[Tuple[str, str], Tuple[str, str]]:
    """The whole table, for seals that assert completeness rather than a single lookup."""
    return dict(_load())


def reset_cache() -> None:
    """Drop the cache so a seal can re-read a MUTATED matrix in the same process.

    Seal 4 exists to prove the level follows the file. A module-level cache would make that
    seal pass against the first parse forever, which is a green that proves the cache works.
    """
    global _CELLS, _SOURCE
    _CELLS = None
    _SOURCE = ""
