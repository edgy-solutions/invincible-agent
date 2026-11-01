"""THE SDK ADOPTION CENSUS IS A RATCHET: direct store clients per engine may only fall.

ca measured how many engines reach Weaviate / Neo4j with the vendor client instead of the SDK
protocols (`MeshVectors`, `MeshGraph`). This seal counts them (ast, not grep) and compares with
`direct_store_baseline.json`: a rise fails, a new engine/surface fails, and a FALL fails too until
the baseline is lowered, so a gain is locked in.
"""

from __future__ import annotations

import json
from pathlib import Path

from iagent_pure.store_client_census import census, findings

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((Path(__file__).parent / "direct_store_baseline.json").read_text("utf-8"))
KINDS = ("imports", "constructions")


def _where(engine: str, surface: str) -> str:
    return "; ".join(
        f"{rel}:{line} ({kind})"
        for e, s, kind, rel, line in findings(ROOT)
        if e == engine and s == surface
    )


def _cells(counts):
    return {(e, s, k): c[k] for e, ss in counts.items() for s, c in ss.items() for k in KINDS}


def test_no_engine_gains_a_direct_store_client():
    now, base = _cells(census(ROOT)), _cells(BASELINE["counts"])
    new, rose = [], []
    for (e, s, k), n in sorted(now.items()):
        if n == 0:
            continue
        if not any(be == e and bs == s for (be, bs, _k) in base):
            new.append(f"{e}/{s}: {n} {k}, absent from baseline -- a new direct store client: "
                       + _where(e, s))
        elif n > base.get((e, s, k), 0):
            rose.append(f"{e}/{s} {k}: {n} > baseline {base.get((e, s, k), 0)}: " + _where(e, s))
    assert not new, "\n".join(new)
    assert not rose, "\n".join(rose)


def test_a_fall_lowers_the_baseline():
    now, base = _cells(census(ROOT)), _cells(BASELINE["counts"])
    fell = [f"{e}/{s} {k}: {now.get((e, s, k), 0)} < baseline {n}"
            for (e, s, k), n in sorted(base.items()) if now.get((e, s, k), 0) < n]
    assert not fell, ("lower the baseline: run scripts/store_client_census.py --write\n"
                      + "\n".join(fell))


def test_the_detector_counts_each_pattern_and_ignores_prose(tmp_path):
    eng = tmp_path / "agent_fleet" / "eng"
    eng.mkdir(parents=True)
    (eng / "a.py").write_text("import neo4j\n", "utf-8")
    (eng / "b.py").write_text("from weaviate.classes import Filter\n", "utf-8")
    (eng / "c.py").write_text(
        "def f(g):\n    return g.GraphDatabase.driver('x')\n"
        "d = AsyncGraphDatabase.driver('y')\n", "utf-8")
    (eng / "d.py").write_text(
        '"""import neo4j; weaviate.connect_to_local()"""\n'
        "# import weaviate\n# GraphDatabase.driver()\n"
        "s = 'import neo4j  GraphDatabase.driver(x)'\n", "utf-8")
    (eng / "e.py").write_text("import weaviate\nc = weaviate.connect_to_local()\n", "utf-8")
    bff = tmp_path / "src" / "iagent"
    bff.mkdir(parents=True)
    (bff / "g.py").write_text("import neo4j\n", "utf-8")
    skipped = tmp_path / "tests"
    skipped.mkdir()
    (skipped / "t.py").write_text("import neo4j\n", "utf-8")
    assert census(tmp_path) == {
        "bff-orchestrator": {"graph": {"imports": 1, "constructions": 0}},
        "eng": {
            # c.py: g.GraphDatabase.driver is not a constructor name; AsyncGraphDatabase is.
            "graph": {"imports": 1, "constructions": 1},
            "vector": {"imports": 2, "constructions": 1},
        },
    }
