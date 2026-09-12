"""ADR-0051 seal 13 — the census's DERIVED population must cover every engine the chart declares.

WHY IT EXISTS, measured 2026-09-11. `gateway._fleet_version_targets()` holds no fleet list: it
DERIVES one by scanning `ENGINE_*_PUBLIC_URL`, and its docstring says exactly why — "a
hardcoded list is the shape this repo keeps paying for: a new engine's URL appears in the
ConfigMap and the census silently does not include it."

IT WAS INCOMPLETE ANYWAY. No variable existed for engine-lg, so `version_census.py` printed a
clean seventeen-row table at exit 0 with one service verified by its SPEC rather than by being
asked — and nothing in the output was wrong. The engine was serving the whole time; `/version`
returned 200 with the correct sha when asked directly.

**A DERIVED POPULATION IS ONLY AS COMPLETE AS THE THING IT DERIVES FROM.** An env var nobody
set is invisible to a scan of env vars. Deriving moved the hole from the list to the SOURCE of
the list; it did not remove it. So the derivation needs its own floor, checked against an
INDEPENDENT enumeration — here the chart's own `$engines` list, which is what actually decides
whether a workload exists.

THE EIGHTH REGISTRY SITE, and this seal is in front of the safety engine so the NINTH cannot
repeat it: adding a row to `$engines` without a URL variable turns this red, naming the engine.

WHAT THIS SEAL CANNOT SEE, AND IT IS BY CONSTRUCTION. Its independent enumeration is the chart's
`$engines` list **on this branch**. An engine that exists only on an unmerged lane branch is
therefore invisible to it: not a hole to be plugged, because the merge is precisely the act that
lands the engine, and a seal cannot enumerate a population that has not arrived. What matters is
that nobody reads this green as covering a lane branch — it asserts that every engine THE CHART
DECLARES is censused, never that every engine SOMEONE IS BUILDING is. The check that closes the
gap is the merge itself turning this red, which is the intended order: the engine and its
registry sites land together, or the seal names what is missing.

**This seal is the eighth site's own instrument, so it inherits that site's lesson one level up.**
`_COMPONENT_TO_URL_VAR` below is itself a registry site — the tenth — and a component absent from
it fails by SKIP unless `_NOT_CENSUSED` names it, which is why the map demands one or the other
rather than tolerating silence.

Run: uv run --frozen pytest tests/test_the_census_population_covers_every_engine.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ENGINES = _REPO / "helm" / "invincible-agent" / "templates" / "engines.yaml"
_CONFIGMAP = _REPO / "helm" / "invincible-agent" / "templates" / "configmap.yaml"

#: One chart row per engine: `(dict "key" "engineO" "component" "engine-o" ...)`.
_ENGINE_ROW = re.compile(r'\(dict\s+"key"\s+"(\w+)"\s+"component"\s+"([a-z0-9-]+)"')

#: The variables the census actually scans.
_URL_VAR = re.compile(r"^\s*(ENGINE_[A-Z0-9]+)_PUBLIC_URL\s*:", re.M)

#: component -> the URL variable that makes it visible to the census.
#:
#: HAND-KEPT ON PURPOSE, AND THE POPULATION IS NOT. The var name is not derivable from the
#: component — `data-analyst` is `ENGINE_DA`, `engine-fin` is `ENGINE_FIN`, `engine-p` is
#: `ENGINE_P` — so a mechanical mapping would be a guess dressed as a derivation. What IS
#: derived is the set of engines that must appear here: it comes from the chart's `$engines`
#: list, so a new engine cannot be silently absent from this map.
_COMPONENT_TO_URL_VAR = {
    "engine-a": "ENGINE_A",
    "engine-e": "ENGINE_E",
    "engine-w": "ENGINE_W",
    "engine-p": "ENGINE_P",
    "engine-fin": "ENGINE_FIN",
    "engine-cost": "ENGINE_COST",
    # engine-safety (ADR-0051). Without this the census prints a COMPLETE-LOOKING table with this
    # engine missing from it — which is how engine-lg went unaccounted for, and is the reason this
    # map demands either a URL var or an explicit waiver rather than tolerating silence.
    "engine-safety": "ENGINE_SAFETY",
    "engine-lg": "ENGINE_LG",
    "data-analyst": "ENGINE_DA",
}

#: component -> the LEGACY variable the aggregator reads instead of the convention.
#:
#: WRITING THIS SEAL FOUND THEM. My first draft assumed every engine followed
#: `ENGINE_*_PUBLIC_URL` and asserted `engine-o -> ENGINE_O_PUBLIC_URL`; the seal went red
#: because no such variable exists. Three engines predate the convention and `_add` names them
#: explicitly, so they ARE censused — by a different route. The seal was right and my model
#: was wrong, which is the direction you want on the first run.
#:
#: These are not waivers. An engine here is fully visible to the census; it simply arrives by
#: a name the scan cannot infer, which is why a scan-only coverage claim would be false.
_COMPONENT_TO_LEGACY_VAR = {
    "engine-o": "ONTOLOGY_SERVICE_URL",
    "engine-f": "PRESENTATION_AGENT_SVC_URL",
    "engine-d": "DATAHUB_WRAPPER_URL",
}

#: Engines the census deliberately cannot ask, each with the reason. An entry here is a
#: DECISION on the record, not an omission — the distinction the mirror-script row spent five
#: occurrences failing to make.
_NOT_CENSUSED = {
    "engine-b": (
        "RETIRED 2026-09-06 by ADR-0046 §8.4. Registers nothing by design; the chart block "
        "survives only until the key stops existing."
    ),
    "engine-c": (
        "swarms-scraper. Not built from this repo's build matrix, so there is no first-party "
        "sha for a census to compare against."
    ),
    "central-gateway": (
        "Not an agent_fleet engine — a gateway with no verbs of its own. Same waiver text as "
        "_NOT_A_REGISTERING_AGENT carries for it."
    ),
}


def _declared_engines() -> dict:
    """`component -> values key`, from the chart's OWN list. The independent enumeration."""
    text = _ENGINES.read_text(encoding="utf-8")
    found = {c: k for k, c in _ENGINE_ROW.findall(text)}
    assert len(found) >= 12, (
        f"the $engines scrape found only {len(found)}: {sorted(found)} — the chart's engine "
        f"list is the independent enumeration this seal rests on, and reading too little of it "
        f"makes every assertion below weaker than it appears"
    )
    return found


def _census_scannable() -> set:
    """The `ENGINE_*` prefixes the census can actually see, read from the ConfigMap."""
    found = set(_URL_VAR.findall(_CONFIGMAP.read_text(encoding="utf-8")))
    assert len(found) >= 8, (
        f"only {len(found)} ENGINE_*_PUBLIC_URL variables found: {sorted(found)} — the scrape "
        f"is reading too little of the ConfigMap to support a coverage claim"
    )
    return found


def test_every_declared_engine_is_censused_or_explicitly_waived():
    """THE SEAL. A new engine is either visible to the census or waived BY NAME with a reason.

    Silence is the failure this closes: engine-lg was neither, and the census reported a
    complete-looking fleet with it missing.
    """
    declared = _declared_engines()
    unaccounted = sorted(
        c for c in declared
        if c not in _COMPONENT_TO_URL_VAR
        and c not in _COMPONENT_TO_LEGACY_VAR
        and c not in _NOT_CENSUSED
    )
    assert not unaccounted, (
        f"engine(s) {unaccounted} are declared in the chart's $engines list and appear in "
        f"NEITHER _COMPONENT_TO_URL_VAR nor _NOT_CENSUSED. Until one of them names it, the "
        f"census will print a complete-looking table with that engine missing — which is "
        f"exactly how engine-lg went unaccounted for. Add the ENGINE_<X>_PUBLIC_URL to "
        f"configmap.yaml and map it here, or waive it with the reason."
    )


def test_every_mapped_engine_actually_has_its_variable():
    """The map is a claim about the ConfigMap, and a claim is not a fact.

    Mapping `engine-lg -> ENGINE_LG` while no such variable exists would restore the exact
    silence this seal closes, with a table entry that looks like coverage.
    """
    scannable = _census_scannable()
    missing = sorted(
        f"{c} -> {v}_PUBLIC_URL" for c, v in _COMPONENT_TO_URL_VAR.items()
        if v not in scannable
    )
    assert not missing, (
        f"mapped to a ConfigMap variable that does not exist: {missing}. The census derives "
        f"its population by scanning these names, so a mapping without a variable is invisible."
    )


def test_every_LEGACY_mapped_engine_has_its_variable_too():
    """The legacy three get the same check as the convention eight, and they need it MORE.

    Each is read with `os.getenv(name, "<default>")`, so a missing ConfigMap entry does not
    fail — it falls back to a hardcoded in-cluster URL that happens to work today. That is the
    quietest possible way for this map to become fiction: the census keeps reporting a sha, from
    a default nobody declared, until the service moves and the default stops resolving.
    """
    text = _CONFIGMAP.read_text(encoding="utf-8")
    missing = sorted(
        f"{c} -> {v}" for c, v in _COMPONENT_TO_LEGACY_VAR.items()
        if not re.search(rf"^\s*{re.escape(v)}\s*:", text, re.M)
    )
    assert not missing, (
        f"legacy census variable(s) absent from the ConfigMap: {missing}. The aggregator will "
        f"fall back to a hardcoded default and keep reporting, so this fails silently until the "
        f"service moves."
    )


def test_the_waiver_list_names_only_declared_engines():
    """A waiver for an engine that no longer exists is debt that reads as coverage.

    The same drift `test_phantom_allowlist_entries_are_still_cited` guards in the other
    direction: an allowlist nobody prunes eventually describes a repo that is gone.
    """
    declared = set(_declared_engines())
    stale = sorted(set(_NOT_CENSUSED) - declared)
    assert not stale, (
        f"_NOT_CENSUSED waives engine(s) the chart no longer declares: {stale}. Delete them — "
        f"a waiver for something that does not exist hides nothing and confuses the next reader."
    )


def test_every_waiver_states_a_REASON():
    """An unexplained waiver is an omission with better manners.

    The mirror-script row failed five times partly because 'it is in the list' and 'somebody
    decided it belongs in the list' were indistinguishable.
    """
    thin = sorted(c for c, why in _NOT_CENSUSED.items() if len(why.strip()) < 40)
    assert not thin, f"waiver(s) with no real reason: {thin}"


def test_the_scrapes_can_actually_SEE_a_new_engine():
    """THE CONTROL, and without it this whole file is a comparison of two empty sets.

    Both scrapes are regexes over chart files. If either silently matched nothing, every
    assertion above would pass — the unaccounted set would be empty because the declared set
    was. So: a fabricated engine row must be seen by the declared-scrape and must NOT be
    excused by either list.
    """
    fabricated = '(dict "key" "engineZed" "component" "engine-zed" "values" .Values.engineZed)'
    seen = dict((c, k) for k, c in _ENGINE_ROW.findall(fabricated))
    assert seen == {"engine-zed": "engineZed"}, (
        f"the $engines row pattern no longer matches a well-formed row: {seen} — it cannot "
        f"detect the new engine it exists to catch"
    )
    assert not (
        "engine-zed" in _COMPONENT_TO_URL_VAR
        or "engine-zed" in _COMPONENT_TO_LEGACY_VAR
        or "engine-zed" in _NOT_CENSUSED
    ), (
        "the fabricated engine is somehow already accounted for, so the seal cannot "
        "distinguish an unaccounted engine from an accounted one"
    )

    fabricated_var = "  ENGINE_ZED_PUBLIC_URL: \"http://x:1\"\n"
    assert _URL_VAR.findall(fabricated_var) == ["ENGINE_ZED"], (
        "the URL-variable pattern no longer matches a well-formed declaration"
    )
