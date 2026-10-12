"""AN ORIGIN WRITE SAYS HOW IT WAS RESOLVED -- tripwire for the AnswerArtifact ruling.

Ruling (architect): the AnswerArtifact "how resolved" field is added to the write path WHEN
something first writes an origin there, not before. Today nothing writes an origin onto an
AnswerArtifact, while readers (`artifact_reads.py`, gateway) already ask for one. This seal
makes the first such writer red unless it also writes `origin_resolved_by`.

The rule is defended for the CLASS, not one module: every write of `origin_owner_domain` in
the tree, in either form --
  * dict form: `write_node(..., payload={"origin_owner_domain": ..., "origin_resolved_by": ...})`
  * Cypher form: `<var>.origin_owner_domain =` under a SET clause, or `origin_owner_domain:` in a
    map under SET/MERGE/CREATE, in a string or f-string (holes read as `$_`). Reads are not sites.

The rule is one-directional: a dict with ONLY `origin_resolved_by` is fine (origin_writer.py
does exactly that for a re-resolution).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ROOTS = ("src/", "agent_fleet/", "scripts/", "setup/")
_OWNER = "origin_owner_domain"
_RESOLVED = "origin_resolved_by"

_KEYWORDS = re.compile(
    r"\b(SET|WHERE|RETURN|WITH|MATCH|OPTIONAL\s+MATCH|MERGE|CREATE|UNWIND|ORDER\s+BY|DELETE|REMOVE|CALL)\b",
    re.IGNORECASE)
_SET_FORM = r"\b\w+\.{prop}\s*=(?!=)"
_MAP_FORM = r"\b{prop}\s*:"


def _clause_before(text, pos):
    last = None
    for m in _KEYWORDS.finditer(text):
        if m.end() <= pos:
            last = m
        else:
            break
    return re.sub(r"\s+", " ", last.group(1).upper()) if last else None


def _writes(text, prop):
    """True iff `text` WRITES `prop`: `x.prop =` under a SET clause, or `prop:` in a map under
    SET (`SET n += {...}`), MERGE or CREATE. A MATCH pattern map is a read."""
    for m in re.finditer(_SET_FORM.format(prop=prop), text):
        if _clause_before(text, m.start()) == "SET":
            return True
    for m in re.finditer(_MAP_FORM.format(prop=prop), text):
        if _clause_before(text, m.start()) in ("SET", "MERGE", "CREATE"):
            return True
    return False


def _text_of(node):
    if isinstance(node, ast.Constant):
        return node.value
    return "".join(v.value if isinstance(v, ast.Constant) else "$_" for v in node.values)


def dict_sites(tree):
    """[(lineno, ok)] for every dict literal carrying the constant key `origin_owner_domain`."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            keys = {k.value for k in n.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if _OWNER in keys:
                out.append((n.lineno, _RESOLVED in keys))
    return sorted(set(out))


def cypher_sites(tree):
    """[(lineno, ok)] for every string (f-strings with `$_` for each hole) that WRITES
    `origin_owner_domain`; ok iff the same text also writes `origin_resolved_by`. Reads
    (WHERE / RETURN / MATCH maps) are not sites."""
    inner = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
    out = []
    for n in ast.walk(tree):
        if id(n) in inner:
            continue
        if isinstance(n, ast.JoinedStr) or (isinstance(n, ast.Constant) and isinstance(n.value, str)):
            text = _text_of(n)
            if _OWNER in text and _writes(text, _OWNER):
                out.append((n.lineno, _writes(text, _RESOLVED)))
    return sorted(set(out))


def _population():
    out = subprocess.run(["git", "-C", str(_REPO), "ls-files", "*.py"],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return sorted(p for p in out
                  if p.startswith(_ROOTS) and "baml_shared/" not in p and "baml_client/" not in p
                  and not p.startswith("tests/"))


def _scan():
    """({path: [(line, ok), ...]} for dict sites, same for cypher sites, [unparseable paths])."""
    dicts, cyphers, bad = {}, {}, []
    for rel in _population():
        try:
            tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        except (SyntaxError, ValueError, OSError):
            bad.append(rel)
            continue
        d, c = dict_sites(tree), cypher_sites(tree)
        if d:
            dicts[rel] = d
        if c:
            cyphers[rel] = c
    return dicts, cyphers, bad


def _src(code):
    return ast.parse(code)


def test_every_origin_write_says_how_it_was_resolved():
    dicts, cyphers, bad = _scan()
    assert not bad, f"unparseable files in the population: {bad}"
    offenders = [f"{p}:{ln}" for sites in (dicts, cyphers)
                 for p, ss in sites.items() for ln, ok in ss if not ok]
    assert not offenders, ("an origin write without `origin_resolved_by` (the AnswerArtifact "
                           "'how resolved' ruling): " + ", ".join(sorted(offenders)))


def test_the_detector_sees_the_writers_we_know():
    dicts, _, bad = _scan()
    assert not bad, f"unparseable files in the population: {bad}"
    assert "src/iagent/origin_writer.py" in dicts
    assert "src/iagent/promotion_stores.py" in dicts


def test_the_answer_artifact_writer_writes_no_origin_today():
    """STATE MARKER, not an obligation. When this goes red a first origin writer appeared in
    answer_artifact_writer.py: delete THIS arm, keep the rule arm; per the ruling the "how
    resolved" field (`origin_resolved_by`) goes in with that writer."""
    dicts, cyphers, _ = _scan()
    rel = "src/iagent/answer_artifact_writer.py"
    assert rel not in dicts and rel not in cyphers


def _cy(code):
    return cypher_sites(_src(code))


def test_detector_controls_cypher_reads_are_no_site():
    assert _cy('q = "MATCH (n) WHERE n.origin_owner_domain = $d RETURN n"') == []
    assert _cy('q = "MATCH (n {origin_owner_domain: $d}) RETURN n"') == []
    assert _cy('q = "RETURN n.origin_owner_domain AS d"') == []


def test_detector_controls_cypher_writes():
    assert _cy('q = "MERGE (n {id: $id}) SET n.origin_owner_domain = $d"') == [(1, False)]
    both = 'q = "MERGE (n {id: $id}) SET n.origin_owner_domain = $d, n.origin_resolved_by = $r"'
    assert _cy(both) == [(1, True)]
    assert _cy('q = "CREATE (n {origin_owner_domain: $d, origin_resolved_by: $r})"') == [(1, True)]
    assert _cy('q = "CREATE (n {origin_owner_domain: $d})"') == [(1, False)]
    assert _cy('q = "MERGE (a) ON CREATE SET a.origin_owner_domain = $d"') == [(1, False)]
    # A map under SET is a write (`SET n += {...}` / `SET n = {...}`), unlike a MATCH pattern map.
    assert _cy('q = "MATCH (n {id: $id}) SET n += {origin_owner_domain: $d}"') == [(1, False)]
    assert _cy('q = "MATCH (n {id: $id}) SET n += {origin_owner_domain: $d, '
               'origin_resolved_by: $r}"') == [(1, True)]


def test_detector_controls_fstring():
    w = 'q = f"MATCH (a {{id: $id}}) SET a.origin_owner_domain = {x}"'
    assert _cy(w) == [(1, False)]
    ok = 'q = f"MATCH (a {{id: $id}}) SET a.origin_owner_domain = {x}, a.origin_resolved_by = {y}"'
    assert _cy(ok) == [(1, True)]


def test_detector_controls_dict():
    assert dict_sites(_src('d = {"origin_owner_domain": 1}')) == [(1, False)]
    assert dict_sites(_src('d = {"origin_owner_domain": 1, "origin_resolved_by": 2}')) == [(1, True)]
    assert dict_sites(_src('d = {"origin_resolved_by": 2}')) == []
