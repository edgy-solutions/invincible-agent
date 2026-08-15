"""A verb registered against N subjects must carry ONE description.

WHY THIS IS A TRAP AND NOT A STYLE RULE. BAML's TypeBuilder dedupes enum values by NAME.
When two candidate rows share a `verb_iri` and disagree on `description`, the last one
added wins and the others are silently discarded — and the LLM then REFUSES the subject
whose description got dropped, reasoning "this verb operates on X, but the subject is Y".

Engine E hit exactly this: its first `mesh:queryKnowledgeGraph` second-registration used a
ProcedureStep-specific description, and the classifier began refusing WorkInstruction
subjects — the ORIGINAL subject, broken by adding a second one. The fix, recorded at
`neo4j_expert/main.py:126-140`: the description is about WHAT THE VERB DOES, never which
subject path reached it.

Nothing enforced it until now. The failure is silent, appears at a DIFFERENT subject than
the one edited, and presents as a routing regression rather than a registration defect —
which is the most expensive shape a bug can have.
"""
from __future__ import annotations

import pathlib
import re
from collections import defaultdict

import pytest

ENGINES = [
    "agent_fleet/restate_analyst/main.py",
    "agent_fleet/neo4j_expert/main.py",
    "agent_fleet/weaviate_expert/main.py",
    "agent_fleet/data_analyst/main.py",
    "agent_fleet/datahub_wrapper/main.py",
]
ROOT = pathlib.Path(__file__).resolve().parents[2]

_NAME = re.compile(r'name="([^"]+)"')
_VERB = re.compile(r'verb="([^"]+)"')
_INPUT = re.compile(r'input_uri="([^"]+)"')
_STR = re.compile(r'"([^"]*)"')


def _registrations():
    """Line-based on purpose.

    The first version used `(?:.*\\n)*?` under re.S to grab the description block. Nested
    quantifiers backtrack exponentially and it hung for minutes on a 3000-line engine
    file — a test that cannot finish is a test that will be deleted. Scanning lines is
    linear and, here, also clearer about what a "block" is.
    """
    out = []
    for rel in ENGINES:
        p = ROOT / rel
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        starts = [i for i, ln in enumerate(lines)
                  if ln.strip().startswith("register_engine_to_mesh(")]
        for i in starts:
            # A call ends at the first line that is exactly the closing paren at call indent.
            end = next((j for j in range(i + 1, len(lines))
                        if lines[j].rstrip() in ("    )", ")")), min(i + 200, len(lines)))
            body = lines[i:end]
            name = verb = inp = None
            desc_parts, in_desc = [], False
            for ln in body:
                st = ln.strip()
                if st.startswith("description=("):
                    in_desc = True
                    continue
                if in_desc:
                    if st.startswith("),"):
                        in_desc = False
                    elif st.startswith('"'):
                        desc_parts += _STR.findall(st)
                    continue
                if not name and (mo := _NAME.search(ln)):
                    name = mo.group(1)
                if not verb and (mo := _VERB.search(ln)):
                    verb = mo.group(1)
                if not inp and (mo := _INPUT.search(ln)):
                    inp = mo.group(1)
            if not (name and verb):
                continue
            out.append({
                "file": rel, "name": name, "verb": verb, "input_uri": inp or "",
                # Join the literal pieces; whitespace between them is formatting, and
                # only the WORDS are the contract BAML dedupes on.
                "desc": re.sub(r"\s+", " ", "".join(desc_parts)).strip(),
            })
    return out


def test_a_verb_registered_twice_carries_one_description():
    """THE PIN. Group every registration by verb_iri; any verb with >1 registration must
    have exactly one distinct description across them."""
    by_verb = defaultdict(list)
    for r in _registrations():
        by_verb[r["verb"]].append(r)

    multi = {v: rs for v, rs in by_verb.items() if len(rs) > 1}
    assert multi, "no multi-subject verbs found — this pin would be measuring nothing"

    # EXEMPT: verbs that never enter the classifier's enum, where distinct descriptions
    # are informative rather than competing. `mesh:resolveInstance` is typed against
    # `mesh#InstanceIdentifier`, which no subject resolves to — the router reaches it by
    # PROVIDER FAN-OUT (`_resolve_instance` calls every registered provider and compares
    # their answers), not by an LLM picking one enum value. Engine D describing catalog
    # paths and Engine E describing DMCs is exactly right there: each says what ITS phone
    # book knows. The BAML dedup hazard simply does not apply to a verb the classifier
    # never sees, and pretending otherwise would force three providers to describe
    # themselves identically for no benefit.
    FAN_OUT_VERBS = {"mesh:resolveInstance"}

    problems = []
    for verb, rs in sorted(multi.items()):
        if verb in FAN_OUT_VERBS:
            continue
        descs = {r["desc"] for r in rs}
        if len(descs) > 1:
            problems.append(
                f"{verb} has {len(descs)} distinct descriptions across "
                f"{len(rs)} registrations: {sorted(r['name'] for r in rs)}"
            )
    assert not problems, (
        "BAML dedupes enum values by name, so divergent descriptions on one verb mean the "
        "last-added wins and the classifier REFUSES the subjects whose description was "
        "dropped — breaking a subject that previously worked:\n  " + "\n  ".join(problems)
    )


def test_the_column_registrations_exist_and_target_column():
    """The idp:Column coverage added 2026-08-15 — measured at 48% of catalog probes
    returning no_compatible_verbs because Column hangs off prov:Entity and the compat-walk
    only climbs. Pinned so a future edit cannot quietly drop the subject again."""
    regs = [r for r in _registrations()
            if r["input_uri"] == "http://invincible-agent/idp#Column"]
    verbs = {r["verb"] for r in regs}
    assert verbs == {
        "mesh:findSchema", "mesh:traceLineage",
        "mesh:assessImpact", "mesh:describeAsset",
    }, f"idp:Column coverage changed: {sorted(verbs)}"


@pytest.mark.parametrize("excluded", ["mesh:enumerateCatalog", "mesh:checkFreshness",
                                      "mesh:analyzeDataset"])
def test_meaningless_verbs_are_NOT_declared_on_column(excluded):
    """The deliberate omissions, pinned as decisions rather than oversights.

    enumerateCatalog is set-level over datasets; checkFreshness is a table property; and
    analyzeDataset routes to Engine DA whose `query_datahub_asset` takes a DATASET urn — a
    column urn would advertise a read that cannot execute, which is worse than the gap.
    """
    regs = [r for r in _registrations()
            if r["input_uri"] == "http://invincible-agent/idp#Column"]
    assert excluded not in {r["verb"] for r in regs}, (
        f"{excluded} was declared on idp:Column — see the omission rationale in "
        "restate_analyst/main.py; if this is intentional, move the reasoning there first"
    )
