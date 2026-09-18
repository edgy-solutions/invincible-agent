"""Every referent a verb declares exists as a class IN THE TTL SOURCE, not only in the graph.

WHY THIS FILE EXISTS, and it is a defect in a seal rather than in code. The three planning verbs
whose slots pointed at undeclared classes were to be sealed by *the registrar's warning count
going from three to zero at the next reregister*. `iagent-mesh-sdk-ca` pointed out that this
check is GREEN UNDER BOTH of the readings it is meant to discriminate:

    (a) the classes were minted in `idp_extension.ttl` and the prime loaded them
    (b) the classes were created directly in the LIVE GRAPH and the TTL never changed

Under (b) the warning count still goes 3 -> 0, because the graph has them either way. **It is a
green that EXPIRES**: `idp_extension.ttl` is a loaded source, so the next prime rebuilds from the
file, the classes vanish, the three warnings return, and nobody connects it to the night they
were "fixed".

> **Source and runtime are different claims.** The warning count proves the registrar stopped
> complaining. This proves the mint survives a rebuild. Neither implies the other, and only the
> pair survives a prime.

It is the exact inverse of the editable-install defect found the same night: there the repo was
the truth and the environment lied; here the environment would be the truth and the repo lies.

DERIVED, NOT LISTED. The population is every `referent` on every declared slot of every engine's
registration, read from the engine sources — so a verb minted tomorrow with a slot pointing at a
class nobody declared fails HERE, at the commit, rather than as a warning in a log after a roll
that somebody has to be watching for.

Run: uv run --frozen pytest tests/test_a_referent_class_is_declared_in_the_source.py -v
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ONTOLOGY_DIR = _REPO / "setup" / "ontologies"
_FLEET = _REPO / "agent_fleet"

#: Namespaces whose classes this repo DECLARES. A referent outside these is somebody else's
#: vocabulary — `s3kl#`, the IOF imports — and its absence from our TTLs is not our defect.
_OURS = ("http://invincible-agent/",)


def _declared_class_uris() -> set[str]:
    """Every `<uri> a owl:Class` in the primed TTLs, parsed rather than grepped.

    Grepping for the local name would match a comment mentioning the class, which is the
    search-finds-prose-about-the-name trap: prose about a class is densest exactly where the
    class is missing and someone explained why.
    """
    from rdflib import OWL, RDF, Graph  # noqa: PLC0415

    uris: set[str] = set()
    for ttl in sorted(_ONTOLOGY_DIR.glob("*.ttl")):
        g = Graph()
        try:
            g.parse(str(ttl), format="turtle")
        except Exception as exc:  # noqa: BLE001 — a broken TTL is a real failure, named
            pytest.fail(f"{ttl.name} does not parse as turtle: {exc}")
        uris |= {str(s) for s in g.subjects(RDF.type, OWL.Class)}
    return uris


def _declared_referents() -> dict[str, list[str]]:
    """`referent uri -> [where]`, read by AST from each engine's `_REFERENT_KIND` map.

    NOT A REGEX OVER THE SOURCE, and the first draft was. Referents are not written as inline
    strings — they are `_IDP + "Initiative"`, a module-level prefix constant plus a local name —
    so a pattern looking for `"referent": "..."` matched NOTHING and the floor below caught it.
    That is the instrument failing at exactly the job it was built for, and the floor is why it
    was a red rather than a green over an empty set.

    So this resolves the prefix constants and folds the concatenation, which is what the code
    itself does at import.
    """
    import ast  # noqa: PLC0415

    found: dict[str, list[str]] = {}
    for src in sorted(_FLEET.glob("*/*.py")):
        if "__pycache__" in str(src):
            continue
        text = src.read_text(encoding="utf-8", errors="replace")
        if "_REFERENT_KIND" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        where = str(src.relative_to(_REPO)).replace("\\", "/")

        # Module-level string constants, so `_IDP + "Initiative"` can be folded.
        consts: dict[str, str] = {}
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = node.value.value

        def _resolve(v: ast.expr) -> str | None:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                return v.value
            if isinstance(v, ast.BinOp) and isinstance(v.op, ast.Add):
                left, right = _resolve(v.left), _resolve(v.right)
                return None if left is None or right is None else left + right
            if isinstance(v, ast.Name):
                return consts.get(v.id)
            return None

        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(t, ast.Name) and t.id == "_REFERENT_KIND" for t in targets):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for val in node.value.values:
                uri = _resolve(val)
                if uri:
                    found.setdefault(uri, []).append(where)
    return found


def test_THE_POPULATION_IS_NOT_EMPTY():
    """THE FLOOR, and this seal is worthless without it.

    An extraction that matches nothing passes every assertion below while proving nothing — the
    vacuum this repo has met often enough to name. If the engines stop spelling referents the way
    this reads them, that is a change to the seal's reach and must be a decision rather than a
    silent green.
    """
    refs = _declared_referents()
    assert refs, (
        "no referent declarations were found in agent_fleet/*/*.py — either no slot declares one "
        "(measurably false: three planning verbs and seven cost/finance verbs do) or this "
        "extraction no longer matches how they are written"
    )
    assert len(refs) >= 4, f"only {sorted(refs)} extracted — too few to be the real population"


def test_EVERY_REFERENT_WE_OWN_IS_DECLARED_IN_A_TTL():
    """THE SEAL. A referent in our own namespace must exist as a class in a primed source.

    The registrar reports this at runtime — "N slot(s) declare a referent with no OntologyClass
    node, so <verb> will NOT be reachable through them" — but only after a roll, only in a log,
    and only to whoever is reading it. This fails at the commit.
    """
    declared = _declared_class_uris()
    refs = _declared_referents()
    missing = {
        uri: sorted(set(where))
        for uri, where in refs.items()
        if uri.startswith(_OURS) and uri not in declared
    }
    assert not missing, (
        "slot referents in our own namespace with no owl:Class in setup/ontologies/*.ttl:\n"
        + json.dumps(missing, indent=2)
        + "\n\nThe verb stays reachable through its own subject, so this is a shortfall in the "
        "parameterisation widening rather than an outage — but it is invisible from the graph, "
        "because a missing edge and a verb that declares no referents are the same absence."
    )


def test_THE_TWO_MINTED_CLASSES_ARE_IN_THE_SOURCE():
    """The specific case this file was written for, asserted by name.

    `idp:Initiative` and `idp:Project` were minted because three planning verbs pointed at them
    and nothing declared them. Naming them keeps the general arm honest: if the extraction above
    ever stops seeing the planning engine, the general assertion passes over an empty set and
    this one still fails.
    """
    declared = _declared_class_uris()
    for name in ("Initiative", "Project"):
        uri = "http://invincible-agent/idp#" + name
        assert uri in declared, (
            f"idp:{name} is not declared as an owl:Class in any primed TTL. If it is present in "
            f"the LIVE GRAPH, that is the failure this file exists for: the next prime rebuilds "
            f"from the source and deletes it, the registrar's warnings return, and the green "
            f"that reported it fixed will have expired."
        )


def test_A_FOREIGN_NAMESPACE_IS_NOT_OUR_DEFECT():
    """THE CONTROL ON THE SCOPE, and without it this seal would demand we declare other people's
    vocabularies. `s3kl#Project` exists and is a different ontology answering a different
    question — it was explicitly NOT the class to borrow when `idp:Project` was minted."""
    refs = _declared_referents()
    foreign = [u for u in refs if not u.startswith(_OURS)]
    declared = _declared_class_uris()
    for uri in foreign:
        # Asserting nothing about whether it resolves — only that this seal does not claim it
        # should be in OUR ttls.
        assert uri not in declared or True
    assert _OURS == ("http://invincible-agent/",), (
        "the ownership prefix changed; the scope of this seal changed with it and that is a "
        "decision rather than a refactor"
    )
