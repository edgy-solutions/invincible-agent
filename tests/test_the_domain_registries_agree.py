"""The domains the prime SEEDS and the domains policy can GRANT are one population, or a class is unreachable.

MEASURED ON THE LIVE SANDBOX 2026-09-18, after "how do I add an engine?" grounded to `idp#Column`
at 0.30 with `excluded: []` — a subject pool holding exactly one weak option, which won by
default.

`mesh:DocPage` was not ranked low. IT WAS NEVER A CANDIDATE, for any persona. `/resolve`
domain-scopes the OntologyClass pool to the caller's cells, `DocPage` is seeded under DOCS and
MESH, and NEITHER APPEARED IN `policy/domains.yaml` — so no group could grant them, no cell could
hold them, and every class seeded under them was invisible to everyone.

    prime seeds:    DATA_ENGINEERING  DOCS  MAINTENANCE  MANUFACTURING  MESH
                    PORTFOLIO_PLANNING  PRODUCTION_COST  PROGRAM_FINANCE  SUSTAINMENT
    policy grants:  DATA_ENGINEERING        MAINTENANCE                  AVIATION
                    PORTFOLIO_PLANNING  PRODUCTION_COST  PROGRAM_FINANCE  SUSTAINMENT
                    DEFENSE  ENTERPRISE

BOTH DIRECTIONS ARE SILENT, AND BOTH ARE REAL:

  * SEEDED BUT UNGRANTABLE — the class lands in Neo4j, the verb registers and reports accepted,
    the prime succeeds, and the only symptom is a question that grounds to something irrelevant.
    This is "registration is not entitlement" one level out: the CELL cannot exist, so there is
    no grant anyone could make.
  * GRANTABLE BUT UNSEEDED — a group can hold a cell whose domain grounds nothing. The grant
    confers nothing and reads, in `groups.yaml`, exactly like one that does.

THE MIRROR CLASS. Two declarations of one population, each complete and correct on its own side,
with nothing asserting the relation. Every per-file check passes; the divergence lives BETWEEN
them and is invisible to both. Same shape as the two prefix tables and the archetype-binding
mirror — and the same remedy: derive both, and partition.

WHY IT IS A PARTITION AND NOT AN EQUALITY. A one-sided domain can be legitimate, so each is
either in both registries or in `_ONE_SIDED` WITH A REASON. Failing while undecided is the point;
an equality assertion would have to be loosened the first time a real exception appeared, and a
loosened assertion is the one nobody re-reads.

Run: uv run --frozen pytest tests/test_the_domain_registries_agree.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._ratchet import stale_entries, ABSENT_FROM_LIVE, PRESENT_IN_LIVE

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[1]
_MANIFEST_SRC = _REPO / "setup" / "prime_databases.py"
_DOMAINS_YAML = _REPO / "policy" / "domains.yaml"
_GROUPS_YAML = _REPO / "policy" / "groups.yaml"

#: A domain deliberately present on ONE side only. AN EXEMPTION IS A CLAIM — each says which side
#: it is missing from and why that is correct, so "undecided" can never masquerade as "considered".
_ONE_SIDED: dict[str, str] = {
    "AVIATION": (
        "GRANTABLE, NOT SEEDED. Held by aviation-stewards/aviation-engineers and carries no "
        "ontology of its own: the maintenance and sustainment planes hold the classes an "
        "aviation steward grounds against. The cell scopes WHO, not WHICH classes exist. Kept "
        "rather than removed because live users hold it; revisit if it ever grants a verb "
        "nothing can answer."
    ),
    "DEFENSE": (
        "GRANTABLE, NOT SEEDED. Same posture as AVIATION — a persona plane over the shared "
        "sustainment classes rather than a class population of its own."
    ),
    "ENTERPRISE": (
        "GRANTABLE, NOT SEEDED. Same posture as AVIATION; held by enterprise-architects."
    ),
}


def _seeded_domains() -> set:
    """Every `"domain"` in `CANONICAL_TTL_MANIFEST`, read by AST.

    BY AST rather than by import: importing `prime_databases` pulls boto3, neo4j and the rest of
    the prime's dependencies into the unit suite, and a check that can only run where the prime
    can run is a check that stops running.
    """
    tree = ast.parse(_MANIFEST_SRC.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if "CANONICAL_TTL_MANIFEST" not in targets or not isinstance(node.value, ast.List):
            continue
        found = set()
        for entry in node.value.elts:
            if not isinstance(entry, ast.Dict):
                continue
            for k, v in zip(entry.keys, entry.values):
                if (isinstance(k, ast.Constant) and k.value == "domain"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                    found.add(v.value)
        return found
    return set()


def _policy_domains() -> set:
    doc = yaml.safe_load(_DOMAINS_YAML.read_text(encoding="utf-8")) or {}
    return set(doc.get("domains") or []) | set(doc.get("platform_domains") or [])


def _granted_domains() -> set:
    doc = yaml.safe_load(_GROUPS_YAML.read_text(encoding="utf-8")) or {}
    out = set()
    for spec in (doc.get("groups") or {}).values():
        for grant in (spec or {}).get("grants") or []:
            if isinstance(grant, dict) and grant.get("domain"):
                out.add(grant["domain"])
    return out


def test_both_derivations_find_something():
    """THE FLOOR. Either side reading empty would make every assertion below vacuous and green
    forever — which is precisely how a derived population turns back into a remembered one."""
    seeded, policy = _seeded_domains(), _policy_domains()
    assert len(seeded) >= 6, f"only {len(seeded)} seeded domains parsed: {sorted(seeded)}"
    assert len(policy) >= 6, f"only {len(policy)} policy domains parsed: {sorted(policy)}"
    for expect in ("MAINTENANCE", "PRODUCTION_COST"):
        assert expect in seeded, f"{expect} missing from the manifest derivation"
        assert expect in policy, f"{expect} missing from the policy derivation"


def test_EVERY_SEEDED_DOMAIN_CAN_BE_GRANTED():
    """THE DIRECTION THAT COST THE DOCS WALK.

    A class seeded under a domain no group can grant is unreachable by every persona — not
    ranked low, never in the pool. The prime succeeds, the verb registers and reports accepted,
    and the symptom is a question grounding somewhere irrelevant.
    """
    missing = sorted(d for d in _seeded_domains() - _policy_domains() if d not in _ONE_SIDED)
    assert not missing, (
        f"domains the prime SEEDS that policy cannot grant: {missing}. Every OntologyClass "
        f"under them is invisible to every caller, because /resolve scopes the class pool to "
        f"the cells the caller holds and no cell can carry these. Add to policy/domains.yaml "
        f"(as a domain or a platform domain), or record in _ONE_SIDED with the reason."
    )


def test_EVERY_POLICY_DOMAIN_IS_SEEDED_OR_EXCUSED():
    """The other direction, and the one people forget. A grant that confers nothing reads in
    `groups.yaml` exactly like one that works."""
    empty = sorted(d for d in _policy_domains() - _seeded_domains() if d not in _ONE_SIDED)
    assert not empty, (
        f"domains policy can grant with no ontology behind them: {empty}. A cell whose domain "
        f"grounds nothing is a grant that confers nothing. Seed it, remove it, or record it in "
        f"_ONE_SIDED with the reason."
    )


# LIFTED OUT AND EXERCISED AGAINST A FIXTURE, because a ratchet that walks its own list has no
# reach on the day that list is empty -- and empty is the state the work is aimed at. Shown on
# 2026-09-18 by lane/91: with their `_KNOWN` emptied (by me), replacing their entire ratchet
# computation with `stale = []` left the suite GREEN. The guard gutted, nothing said.
#
# So the RULE is a function, and the test calls it with data it controls, BOTH DIRECTIONS: an
# entry that stopped being excused must be flagged, and one still excused must not. A ratchet
# that flagged everything would satisfy the live assertion too, for the wrong reason.
def _stale_one_sided(one_sided, on_both_sides) -> list:
    """Exempt names that are no longer one-sided. THE RULE, callable with any data."""
    return sorted(set(one_sided) & set(on_both_sides))



def test_AN_EXEMPTION_IS_A_CLAIM_AND_RETIRES_ITSELF():
    """An entry that is no longer one-sided is a claim nobody re-read — and it would hide a real
    gap if that name were ever reused."""
    for name, reason in _ONE_SIDED.items():
        assert reason and len(reason) > 40, f"{name} is exempt without a reason"
    both = _seeded_domains() & _policy_domains()
    stale = stale_entries(_ONE_SIDED, both, stale_when=PRESENT_IN_LIVE)
    assert not stale, (
        f"{stale} are now on BOTH sides, so the exemption describes nothing. Delete the entry."
    )
    # THE SECOND RATCHET IN THIS ARM, and I converted only the first. One register, two staleness
    # computations — the same miss 81 reported in their own file, where one register was recorded
    # and three were there. A register is not the unit; a COMPUTATION is.
    unknown = stale_entries(
        _ONE_SIDED, _seeded_domains() | _policy_domains(), stale_when=ABSENT_FROM_LIVE
    )
    assert not unknown, f"exemption(s) for domains in neither registry: {unknown}"


def test_A_PLATFORM_DOMAIN_IS_DECLARED_ONCE_not_repeated_per_group():
    """Platform domains are held by EVERY group by declaration.

    Written as one list the sync expands, never as a row per group: a universal grant copied into
    every group is a population maintained by remembering to, and the group that gets missed is
    the one whose users report that the corpus does not answer them.
    """
    doc = yaml.safe_load(_DOMAINS_YAML.read_text(encoding="utf-8")) or {}
    platform = set(doc.get("platform_domains") or [])
    if not platform:
        pytest.skip("no platform domains declared")
    per_group = _granted_domains() & platform
    assert not per_group, (
        f"platform domain(s) {sorted(per_group)} are ALSO written as explicit group grants. "
        f"They are granted to every group by declaration; a per-group row is a second "
        f"declaration of the same fact, and the two go stale apart."
    )


def test_THE_VALIDATOR_AND_THE_SYNC_SEE_THE_SAME_VOCABULARY():
    """THE THIRD MIRROR, and it appeared in the change that added this file.

    `topaz_sync.load_policy` expands `platform_domains`; `validate_policy` builds its OWN bundle
    for the overlay-enum path and read `domains` alone. The validator reported 10 domains while
    the sync applied 12 — so the bundle that was VALIDATED was not the bundle that SHIPS, which
    is the mirror class in its most expensive form: it passes, and the thing it passed is not
    the thing deployed.

    Both now call `expand_platform_domains`. This asserts the outcome rather than the call, so
    a future second reader that forgets it fails here instead of silently validating a phantom.
    """
    import sys
    sync_dir = str(_REPO / "policy" / "sync")
    if sync_dir not in sys.path:
        sys.path.insert(0, sync_dir)
    from topaz_sync import load_policy

    bundle = load_policy(_REPO / "policy")
    declared = _policy_domains()
    assert set(bundle.domains) == declared, (
        f"the sync's vocabulary {sorted(set(bundle.domains))} differs from what "
        f"policy/domains.yaml declares {sorted(declared)} — two readers of one file"
    )
    granted = {(g.persona, g.domain) for spec in bundle.groups.values() for g in spec.grants}
    doc = yaml.safe_load(_DOMAINS_YAML.read_text(encoding="utf-8")) or {}
    for pd in (doc.get("platform_domains") or []):
        holders = {p for p, d in granted if d == pd}
        personas = {p for p, _ in granted}
        assert holders == personas, (
            f"platform domain {pd!r} is held by {len(holders)} of {len(personas)} granted "
            f"personas — 'held by every group by declaration' is not what the expansion produced"
        )
