"""An in-cluster URL in code must name a service the chart actually renders.

WHY THIS EXISTS. `src/iagent/gateway.py` defaulted Engine P's URL to
`http://iagent-planning-agent:8095` — a service that has never existed. The chart names engine
services by COMPONENT (`iagent-engine-p`); the IMAGE and the Keycloak client are named
`planning-agent`. Those differ for exactly one engine, which is what made the mistake easy and
invisible: three plausible names for one thing, two of them correct somewhere else.

IT WAS THE SECOND OCCURRENCE. The identical wrong name was fixed in Engine P's own
`ENGINE_P_PUBLIC_URL` two days earlier. That fix was applied where it was found, and the other
site was never enumerated — so the defect survived its own repair. That is the naming-a-class-
is-not-a-guard law again, and the answer is the same: enumerate mechanically.

Nothing failed loudly. `ENGINE_P_URL` is unset in the ConfigMap, so the wrong default WAS the
live value, and the route simply could not reach the engine.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CHART = _ROOT / "helm" / "invincible-agent"
_ENGINES_TPL = _CHART / "templates" / "engines.yaml"

# `http://iagent-<name>:<port>` as it appears in source.
_URL = re.compile(r'https?://iagent-([a-z0-9-]+):(\d+)')
_COMPONENT = re.compile(r'"component"\s+"([\w-]+)"')

# Services the chart renders OUTSIDE engines.yaml. Listed rather than parsed because each
# comes from a different template or subchart; a name here that stops existing is caught by
# test_every_known_service_is_plausible below.
_NON_ENGINE_SERVICES = {
    "weaviate", "weaviate-grpc", "neo4j", "neo4j-bolt", "postgresql", "redis", "minio",
    "keycloak", "restate", "fuseki", "electric", "cortex-bff", "cortex-ui", "mesh-registrar",
    "dagster", "dagster-user-code", "clickhouse", "projector", "domain-broker",
    "pub-tools", "pub-tools-broker", "dag-tools", "dag-tools-broker", "central-gateway",
    "data-analyst", "topaz",
}


def _chart_services() -> set[str]:
    text = _ENGINES_TPL.read_text(encoding="utf-8")
    return {m.group(1) for m in _COMPONENT.finditer(text)} | _NON_ENGINE_SERVICES


def _source_urls() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for root in ("src", "agent_fleet"):
        for path in (_ROOT / root).rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            for m in _URL.finditer(path.read_text(encoding="utf-8", errors="replace")):
                found.setdefault(m.group(1), []).append(
                    f"{path.relative_to(_ROOT).as_posix()} -> iagent-{m.group(1)}:{m.group(2)}"
                )
    return found


# Found by this seal on its FIRST RUN, all pre-existing, all the SAME MISTAKE: an agent's
# DIRECTORY name used where the chart's COMPONENT name belongs. Waived rather than fixed
# because they are other lanes' routing code and Engines B and C are disabled in sandbox, so
# these are dead-but-unused rather than actively broken. Recorded so they are not mistaken for
# correctness, and paired with an expiry guard so a waiver cannot outlive its defect.
WAIVED = {
    "langgraph-support": "engineB's dir name; the service is iagent-engine-b. Engine B disabled in sandbox.",
    "swarms-scraper": "engineC's dir name; the service is iagent-engine-c. Engine C disabled in sandbox.",
    "litellm": "no such service in any chart template; embed path's default, unreached in sandbox.",
}


def test_the_inputs_are_readable():
    """Positive control. A regex that matched nothing would pass over nothing."""
    assert len(_chart_services()) >= 15, "chart service list did not parse"
    assert len(_source_urls()) >= 5, "no in-cluster URLs found in source — the pattern moved"


def test_every_in_cluster_url_names_a_service_the_chart_renders():
    """THE SEAL. A URL naming a service that does not exist fails at REQUEST time, in a cluster,
    as a connection error far from the line that wrote it."""
    known = _chart_services()
    offenders = []
    for name, sites in sorted(_source_urls().items()):
        if name not in known and name not in WAIVED:
            offenders.extend(sites)
    assert not offenders, (
        "these URLs name services the chart does not render:\n  "
        + "\n  ".join(offenders)
        + f"\n\nServices the chart renders: {sorted(known)}"
    )


def test_no_waiver_outlives_its_defect():
    """A waiver that survives its own fix is a lie the next reader has to disprove."""
    known = _chart_services()
    live = {n for n in _source_urls() if n not in known}
    stale = sorted(set(WAIVED) - live)
    assert not stale, (
        "these waivers no longer describe a real offender - delete them:\n  "
        + "\n  ".join(f"{s} ({WAIVED[s]})" for s in stale)
    )


# ─────────────────────────────────────────────────────────────────────────────
# THE SHADOWING SEAL — a bare `env` literal silently REPLACES the templated FQDN
#
# The ConfigMap builds every engine URL through the `svcDomain` helper, whose whole purpose is
# stated in its own docstring: a BARE service name has no dots, so it does not suffix-match a
# NO_PROXY entry of ".svc.cluster.local", and under a corporate proxy the in-cluster call is
# handed to the proxy and dies.
#
# A container's `env` OVERRIDES its `envFrom`. So a literal in a values file does not REINFORCE
# the ConfigMap, it REPLACES it — and the protection is gone with no diff to show for it.
# MEASURED on the live sandbox, 2026-08-27:
#
#     ConfigMap : http://iagent-engine-w.sandbox.svc.cluster.local:8088/query_knowledge
#     pod env   : http://iagent-engine-w:8088/query_knowledge          <- the literal won
#
# Reported from the work cluster as "cannot route to engine-p". Invisible in the sandbox,
# which has no proxy — the bare name resolves there, so the sandbox CANNOT reproduce this
# class of failure while these pins exist.
#
# THIS IS THE THIRD TIME engine-p's URL has been wrong, and the first two fixes each corrected
# the instance in front of them: the wrong service name in ENGINE_P_PUBLIC_URL (2026-08-22),
# then the same wrong name in gateway.py (2026-08-24, whose comment says "the other site was
# never enumerated"). Both fixed a NAME. Neither asked whether the URL was BUILT like every
# other engine's — it was not, and ENGINE_P_URL was set by no template at all.
#
# Four names for one engine is why: values key `enginePlanning`, image `planning-agent`,
# service `engine-p`, Keycloak client `planning-agent`. Grepping any one finds a quarter of
# the wiring.
# ─────────────────────────────────────────────────────────────────────────────

_VALUES_FILES = ("values.yaml", "values-sandbox.yaml")
_URL_KEY = re.compile(r"^\s*(ENGINE_\w*_URL|ENGINE_\w*_PUBLIC_URL)\s*:\s*(.+?)\s*$", re.M)

# Bare-name pins that remain, each a STALE-IMAGE workaround with its own recorded reason, both
# SANDBOX-ONLY so neither reaches the work cluster. Exempted rather than removed: they were
# added because a deployed image baked a wrong default, and deleting them without confirming
# the image is current would trade a proxy bug for a DNS bug. An exemption is a claim, and this
# one says "known, scoped, and someone must re-check the image", not "acceptable".
_SHADOW_EXEMPT = {
    "ENGINE_A_PUBLIC_URL": "values-sandbox: old engine-a image baked restate-agent-svc.default.svc",
    "ENGINE_DA_PUBLIC_URL": "values-sandbox: pin so deploy does not depend on an image rebuild",
}


def _configmap_url_keys() -> set[str]:
    text = (_CHART / "templates" / "configmap.yaml").read_text(encoding="utf-8")
    return {m.group(1) for m in _URL_KEY.finditer(text)}


def _values_url_literals() -> dict[str, list[str]]:
    """URL keys declared as literals in a values file — these become container `env`."""
    out: dict[str, list[str]] = {}
    for name in _VALUES_FILES:
        path = _CHART / name
        if not path.is_file():
            continue
        for m in _URL_KEY.finditer(path.read_text(encoding="utf-8")):
            key, value = m.group(1), m.group(2)
            # A templated value is fine in a TEMPLATE; in a values file it is never rendered
            # (no `tpl` on engine env), so `{{` here would ship as a literal brace.
            out.setdefault(key, []).append(f"{name}: {key}: {value}")
    return out


def test_the_shadow_inputs_are_readable():
    """Positive control — both sides must parse, or the seal passes over nothing."""
    keys = _configmap_url_keys()
    assert len(keys) >= 5, f"configmap URL keys did not parse: {sorted(keys)}"
    assert "ENGINE_P_URL" in keys, "ENGINE_P_URL is not templated in the ConfigMap"


def test_every_engine_url_is_templated_through_svcDomain():
    """A URL the ConfigMap builds must go through the helper, not be a literal."""
    text = (_CHART / "templates" / "configmap.yaml").read_text(encoding="utf-8")
    offenders = []
    for m in _URL_KEY.finditer(text):
        key, value = m.group(1), m.group(2)
        if "svcDomain" not in value:
            offenders.append(f"{key}: {value}")
    assert not offenders, (
        "ConfigMap URL(s) not built through invincible-agent.svcDomain:\n  "
        + "\n  ".join(offenders)
        + "\n\nA bare service name has no dots and does not suffix-match a NO_PROXY entry of "
        "'.svc.cluster.local'; under a corporate proxy the call is proxied and dies."
    )


def test_no_values_literal_SHADOWS_a_templated_configmap_url():
    """THE SEAL. `env` beats `envFrom`, so a literal here silently disables the FQDN."""
    templated = _configmap_url_keys()
    offenders = []
    for key, sites in sorted(_values_url_literals().items()):
        if key in templated and key not in _SHADOW_EXEMPT:
            offenders.extend(sites)
    assert not offenders, (
        "values-file literal(s) SHADOW a templated ConfigMap URL:\n  "
        + "\n  ".join(offenders)
        + "\n\nA container's `env` overrides `envFrom`, so these REPLACE the FQDN with a bare "
        "service name rather than reinforcing it. Delete the literal; the ConfigMap is the "
        "single source. Override global.clusterDomain to change the suffix."
    )


def test_no_shadow_exemption_outlives_its_defect():
    """An exemption that no longer describes a real pin is a hole nobody remembers opening."""
    live = set(_values_url_literals())
    stale = sorted(set(_SHADOW_EXEMPT) - live)
    assert not stale, (
        "these shadow exemptions no longer describe a real literal - delete them:\n  "
        + "\n  ".join(f"{s} ({_SHADOW_EXEMPT[s]})" for s in stale)
    )
