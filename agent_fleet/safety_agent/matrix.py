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

#: (severity_code, probability_code) -> (risk_level_label, acceptance_audience)
_CELLS: Optional[Dict[Tuple[str, str], Tuple[str, str]]] = None
_SOURCE: str = ""


def candidate_matrix_paths(module_path: Path) -> list[Path]:
    """Where the ratified matrix might be. THE REPO CANDIDATE IS GUARDED ON DEPTH.

    **TAKES `module_path` RATHER THAN READING `__file__`, and that signature is why this is
    testable at all** — copied from `restate_analyst.candidate_definition_dirs`, which takes the
    same argument for the same reason. A seal can hand it `/app/matrix.py` and observe the guard.

    That mattered immediately. The first seal written for this defect copied the engine into a
    temp directory, called it "the flat layout", and **passed with the guard REMOVED** — because
    `C:/Users/.../Temp/.../app/matrix.py` has plenty of parents. `/app` has two only because it
    sits at the filesystem root. The fixture could not reproduce the property it was named after:
    the fixture-that-cannot-fail shape, found inside the seal written to catch this very bug.

    THIS CRASHED THE ENGINE AT IMPORT, AND THE ENGINE HAD NOT SHIPPED YET. It was a module-scope
    constant:

        _DEFAULT_TTL = Path(__file__).resolve().parents[2] / "setup" / ...

    In the image `/app` IS the engine directory, so this module is `/app/matrix.py`, whose parents
    are exactly `['/app', '/']`. `parents[2]` raises **IndexError at module scope**, and
    `measures.py` imports this module at load — so the process would never have served. Not a 500;
    a pod that cannot come up.

    **AND THE ESCAPE HATCH COULD NOT HAVE SAVED IT, which is why it had to be a code fix.**
    `matrix_path()` honours `SAFETY_RISK_MATRIX_TTL`, but the constant was evaluated at IMPORT —
    the override was computed *after* the thing that crashed. No deployment-time workaround
    existed.

    `restate_analyst/workflow_definition.py:250` already carried this exact lesson in a docstring:
    *"has exactly two parents, so an unguarded `parents[2]` raises IndexError."* Somebody hit it,
    understood it, and fixed it in one file — **and it did not travel.** Two more engines shipped
    the defect afterwards. The knowledge was in the tree the whole time.

    LAZY RATHER THAN A CONSTANT, so the env override is read at CALL time and a deployment naming
    the file it actually primed is obeyed.
    """
    here = module_path.resolve()
    out: list[Path] = []
    if len(here.parents) >= 3:  # repo layout only; guarded, see docstring
        out.append(here.parents[2] / "setup" / "ontologies" / "safety_risk_matrix.ttl")
    # Flattened container layout. NOTHING COPIES THE TTL HERE TODAY — the image build copies the
    # engine directory, `utils/`, and named policy files; the ontologies are PRIMED, not shipped.
    # So in the image this candidate does not exist and `SAFETY_RISK_MATRIX_TTL` (or increment 5's
    # graph read) is required. Stated rather than discovered: the engine now STARTS either way and
    # refuses loudly when asked for a level it has no table for.
    out.append(here.parent / "safety_risk_matrix.ttl")
    return out


def matrix_path() -> Path:
    """The ratified matrix, env override first, then the first candidate that EXISTS.

    Returns the last candidate when none exists, so the refusal names the flat path a deployment
    would have to supply rather than a repo path that means nothing inside the image.
    """
    override = os.getenv("SAFETY_RISK_MATRIX_TTL", "").strip()
    if override:
        return Path(override)
    candidates = candidate_matrix_paths(Path(__file__))
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


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
