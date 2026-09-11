"""Does what a TTL DECLARES actually RESOLVE in the deployed graph?

**NO SEAL IN EITHER REPO ASKED THIS.** Every archetype check reads a seeded `.ttl` file or a
Python registry, so all of them are green the moment a class is committed — and a class reaches
the graph only through a prime, off a pushed master sha, from TTLs baked into the image.

The gap cost real time three times in eight days. `mesh:StepLadder`, `mesh:NamedHole` and
`mesh:CompetingMeasures` were each declared, each showed green across every registry seal, and
each was **absent from the graph**, so a binding naming one would register, report ACCEPTED, and
never match. Both lanes found it the same way each time: by running a SPARQL ASK by hand and
remembering to.

> **A seal over the declaration cannot see the deployment.** Declared and resolves are different
> claims and they need different instruments.

WHY THIS IS A TEST AND NOT A SCRIPT. A script is run by someone who already suspects. This runs
with the suite, and when the cluster is unreachable it **VOIDS BY NAME** rather than passing —
because a check that silently succeeds when it cannot look is the uniform-positive tell this
repo has now been bitten by four times.

WHAT A RED MEANS, AND THE SEAL SEPARATES THE CASES RATHER THAN LISTING THEM. It first said it
could not tell them apart and named two — and MISSED THE ONE THAT WAS ACTUALLY TRUE, that the
class was declared on an unmerged lane branch. A prime reads TTLs baked into the image and CI
builds pushed MASTER shas, so no prime can deliver a class that is not on master: the next step
is a MERGE. "Outstanding on a prime" would have sent a reader to ask the prime owner for
something no prime could do.

So the failure text checks `origin/master` and says which of three it is:

  * not on origin/master   -> merge, then CI -> roll -> prime. Ask whoever gates merges.
  * on master, still absent -> the prime has not run since, OR the IRI is misspelled and never
                               existed. Check the spelling BEFORE scheduling a prime.
  * git could not answer    -> said so; read as the merged case.

STILL UNDISTINGUISHED, and named so nobody assumes otherwise: a prime that has not run from an
IRI that is misspelled. Both are "on master and absent", and only reading the TTL separates them.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGIES = ROOT / "setup" / "ontologies"

#: Where the deployed graph is reachable. A port-forward is the usual way; the test does not
#: create one — starting infrastructure from a test is how a suite acquires a dependency nobody
#: declared.
ENDPOINT = os.environ.get("JENA_QUERY_URL", "http://localhost:13030/ds")
AUTH = os.environ.get("JENA_AUTH", "admin:Admin123!")

#: Namespaces this repo owns. A class outside them is someone else's to prime.
OURS = re.compile(r"<(http://invincible-agent/[^>]+)>")

_ARCHETYPE = "http://invincible-agent/mesh#Archetype"


def _ask(query: str):
    """None when the graph cannot be reached — NEVER False. The distinction is the whole point:
    `False` is an answer about the graph, `None` is an answer about the instrument."""
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "12", "-u", AUTH,
             "-H", "Accept: application/sparql-results+json",
             "--data-urlencode", "query=" + query, ENDPOINT],
            capture_output=True, text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)["boolean"]
    except (ValueError, KeyError):
        return None


def declared_archetypes() -> dict[str, str]:
    """`mesh:Foo` -> full IRI, for every class declared `subClassOf mesh:Archetype` in a seeded
    TTL. DERIVED from the files rather than listed, so a new archetype is covered on the commit
    that declares it."""
    found: dict[str, str] = {}
    for ttl in sorted(ONTOLOGIES.glob("*.ttl")):
        text = ttl.read_text(encoding="utf-8")
        for m in re.finditer(
            r"^(\w+:\w+)\s+a\s+owl:Class\s*;(.*?)\.\s*$", text, re.S | re.M
        ):
            curie, body = m.group(1), m.group(2)
            if "mesh:Archetype" in body and "subClassOf" in body:
                prefix, local = curie.split(":", 1)
                ns = re.search(rf"@prefix\s+{prefix}:\s*<([^>]+)>", text)
                if ns:
                    found[curie] = ns.group(1) + local
    return found


@pytest.fixture(scope="module")
def graph_reachable():
    alive = _ask("ASK {}")
    if alive is None:
        pytest.skip(
            "VOID: the deployed graph is not reachable at "
            f"{ENDPOINT} — this check proves NOTHING here. It is not a pass. Port-forward "
            "Fuseki (kubectl port-forward -n sandbox svc/iagent-fuseki 13030:3030) to run it."
        )
    return True


def test_the_probe_can_say_NO(graph_reachable):
    """POSITIVE CONTROL, and it has already earned its place once. A first version of this probe
    replaced the subprocess environment instead of extending it; kubectl never ran, every ASK
    read as not-found, and a uniform NOT FOUND across real classes read as a finding rather than
    as instrument failure. A fabricated IRI must come back absent."""
    assert _ask(f"ASK {{ <{_ARCHETYPE}Phantom> a <http://www.w3.org/2002/07/owl#Class> }}") is False
    assert _ask(f"ASK {{ <{_ARCHETYPE}> a <http://www.w3.org/2002/07/owl#Class> }}") is True


def test_the_scan_ACTUALLY_FINDS_archetypes():
    """A regex that matched nothing would make the check below green forever."""
    found = declared_archetypes()
    assert len(found) >= 3, f"only {len(found)} archetypes parsed out of the TTLs: {sorted(found)}"


def on_origin_master(curie: str) -> bool | None:
    """Is this class declared on `origin/master`? None when git cannot answer.

    THIS IS WHAT TURNS AN AMBIGUOUS RED INTO A PRECISE ONE. A prime reads the TTLs baked into
    the image and CI builds pushed MASTER shas, so a class living only on a lane branch cannot
    be primed at all — the next step is a MERGE, not a prime. The first version of this seal
    listed two readings and missed the one that was actually true, which would have sent a
    reader to ask the prime owner for something no prime could deliver.
    """
    local = curie.split(":", 1)[1]
    try:
        r = subprocess.run(
            ["git", "show", f"origin/master:setup/ontologies/mesh_system.ttl"],
            capture_output=True, text=True, cwd=ROOT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return bool(re.search(rf"\b\w+:{re.escape(local)}\s+a\s+owl:Class", r.stdout))


def test_EVERY_DECLARED_ARCHETYPE_RESOLVES_IN_THE_GRAPH(graph_reachable):
    """The check neither repo had.

    A red here is NOT a code defect — the declaration has not reached the deployment. There are
    three reasons and the seal SEPARATES them rather than listing them, because "outstanding on
    a prime" is one step short of true when the class is on an unmerged branch, and a reader a
    week later would go asking the prime owner for something no prime can deliver.
    """
    absent = []
    for curie, iri in sorted(declared_archetypes().items()):
        if _ask(f"ASK {{ <{iri}> a <http://www.w3.org/2002/07/owl#Class> }}") is not True:
            absent.append(curie)
    if not absent:
        return

    unmerged, merged, unknown = [], [], []
    for curie in absent:
        where = on_origin_master(curie)
        (unmerged if where is False else merged if where is True else unknown).append(curie)

    lines = [f"declared in a seeded TTL and ABSENT from the deployed graph: {absent}.",
             "A binding naming one of these registers, reports ACCEPTED, and never matches — "
             "the card falls through to KNOWLEDGE_DOCUMENT with 'No content available'.", ""]
    if unmerged:
        lines += [f"  NOT ON origin/master: {unmerged}",
                  "    A prime reads the TTLs baked into the image and CI builds pushed MASTER "
                  "shas, so no prime can deliver these. The next step is a MERGE, then "
                  "CI -> roll -> prime. Do not ask the prime owner; ask whoever gates merges."]
    if merged:
        lines += [f"  ON origin/master and still absent: {merged}",
                  "    Either the prime has not run since that merge, or the IRI is misspelled "
                  "in the TTL and never existed. Check the spelling BEFORE scheduling a prime."]
    if unknown:
        lines += [f"  could not check origin/master for: {unknown}",
                  "    git could not answer — fetch, or read this as the merged case."]
    assert False, "\n".join(lines)
