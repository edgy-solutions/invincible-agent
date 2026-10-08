"""The NetworkPolicy templates admit the substrate allowlist — TRANSLATED INTO COMPONENT NAMES.

⛔ THE DEFECT THIS FILE EXISTS FOR, because it is invisible and it very nearly shipped:
**a NetworkPolicy selector that matches no pod is valid YAML, deploys without error, and silently
denies.** There is no warning, no event, no rejected manifest — just a pod that cannot reach the
store, failing at runtime in its own name, with the policy looking correct in review.

And the chart makes that easy to do, because the pods have TWO names. The allowlist in
``tests/test_substrate_allowlist_exceptions_expire.py`` is keyed on AGENT names — the
``agent_fleet/`` directory and image name — while a ``podSelector`` can only match the chart's
COMPONENT label. Four of the six admitted pods differ between the two registries:

    allowlist key        chart component     what a literal transcription would have selected
    ------------------   -----------------   ------------------------------------------------
    engine-o             engine-o            (agrees)
    mesh-registrar       mesh-registrar      (agrees)
    restate-analyst      engine-a            NOTHING
    weaviate-expert      engine-w            NOTHING
    neo4j-expert         engine-e            NOTHING
    presentation-agent   engine-f            NOTHING   (the EXCEPTION — see below)

So a policy written in the allowlist's own vocabulary would have admitted two of six and quietly
denied four, and every check short of a live connection would have passed. That is the whole
reason this seal is a set EQUALITY against a derived population rather than a spot check.

── WHAT EACH ARM DEFENDS ───────────────────────────────────────────────────────────────────
The arms below are deliberately split between the TEXT of the templates and the RENDERED output,
because they answer different questions. The text arms answer "does the source enumerate every
engine?" — a question about drift, since the policy file necessarily repeats ``engines.yaml``'s
engine list and Helm gives no way to share it. The render arms answer "does the object that would
actually deploy select the right pods?" — the only question the cluster cares about.

⚠ EVERY PARSE HERE IS AN INSTRUMENT AND CAN BE VACUOUS. A regex that matches nothing makes a set
comparison pass against an empty set and a substring check pass against no candidates. So
``test_THE_INSTRUMENTS_FIND_SOMETHING`` runs first and asserts non-trivial anchor counts, and the
address check carries an inline positive control. A green from this file is worth nothing without
those two.

── A CORRECTION TO THIS SEAL'S OWN SPEC, MADE ON PURPOSE ───────────────────────────────────
The spec these templates were written from asked for the DNS egress rule FIRST. The seal asserts
that DNS is PRESENT, not that it is first, because a NetworkPolicy's egress rules are a UNION and
their order carries no meaning. Asserting position would have sealed a property the cluster does
not have, which is worse than not asserting it: it reads as a guarantee and constrains an editor
for no reason. Presence is the real requirement — a default-deny egress without a DNS rule breaks
name resolution, and then every other rule in the policy is unreachable for a reason that looks
like a DNS outage.

Run: uv run --frozen pytest tests/test_networkpolicy_admits_the_allowlist_by_component.py -v
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_TPL = _CHART / "templates"

_ENGINES_TPL = _TPL / "engines.yaml"
_NP_ENGINES = _TPL / "networkpolicy-engines.yaml"
_NP_STORES = _TPL / "networkpolicy-stores.yaml"

#: The allowlist's own module. Loaded by PATH rather than imported as a package so that this seal
#: fails loudly if the population's source file moves — the population moving is exactly the event
#: this file must not survive quietly.
_ALLOWLIST_SRC = _REPO / "tests" / "test_substrate_allowlist_exceptions_expire.py"


def _load_allowlist_module():
    spec = importlib.util.spec_from_file_location("substrate_allowlist__seal", _ALLOWLIST_SRC)
    assert spec and spec.loader, f"cannot load the allowlist module at {_ALLOWLIST_SRC}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: The ONE place the two name registries are reconciled. Derived from values.yaml's per-engine
#: `image.name` against engines.yaml's `component`, read 2026-09-28. A key added to the allowlist
#: with no entry here fails `test_THE_ALLOWLIST_TRANSLATES_TO_COMPONENTS_THAT_EXIST` rather than
#: being silently dropped.
AGENT_TO_COMPONENT: dict[str, str] = {
    "engine-o": "engine-o",                 # ontology-service
    "mesh-registrar": "mesh-registrar",     # not an engine; its own template
    "restate-analyst": "engine-a",
    "weaviate-expert": "engine-w",
    "neo4j-expert": "engine-e",
    "presentation-agent": "engine-f",       # the EXCEPTION, not an allowlist entry
}

_COMPONENT_IN_TEMPLATE = re.compile(r'"component"\s+"([a-z0-9-]+)"')
_COMPONENT_LABEL = re.compile(r"app\.kubernetes\.io/component:\s*([a-z0-9-]+)")
#: Dotted quads and anything that looks like a host:port. Deliberately broad — this is a leak
#: check, and a false positive here costs a conversation while a miss commits infra detail.
_ADDRESS_LITERAL = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _render(enabled: bool, values: Path | None = None) -> list[dict]:
    """Render the chart and return every NetworkPolicy document.

    With no `values` the chart renders with DEFAULT values. That is deliberate: the question is
    what the CHART does, and a sandbox values file would make the answer a property of one
    deployment. The directCallers arm passes the sandbox file as well, because that is where the
    population lives.
    """
    cmd = ["helm", "template", "iagent", str(_CHART)]
    if values is not None:
        cmd += ["-f", str(values)]
    if enabled:
        cmd += ["--set", "networkPolicy.enabled=true"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"helm template failed: {proc.stderr[-2000:]}"
    docs = [d for d in yaml.safe_load_all(proc.stdout) if isinstance(d, dict)]
    return [d for d in docs if d.get("kind") == "NetworkPolicy"]


def _from_components(policy: dict) -> set[str]:
    out: set[str] = set()
    for rule in policy.get("spec", {}).get("ingress") or []:
        for peer in rule.get("from") or []:
            sel = (peer.get("podSelector") or {}).get("matchLabels") or {}
            comp = sel.get("app.kubernetes.io/component")
            if comp:
                out.add(comp)
    return out


# ── the anti-vacuity floor ──────────────────────────────────────────────────────────────────

def test_THE_INSTRUMENTS_FIND_SOMETHING():
    """Every arm below compares sets built by a regex. A regex that matches nothing turns each of
    those comparisons into a tautology, so the counts are asserted before anything is concluded
    from them."""
    for p in (_ENGINES_TPL, _NP_ENGINES, _NP_STORES):
        assert p.is_file(), f"{p.name} does not exist — the seal has no subject"

    engine_components = set(_COMPONENT_IN_TEMPLATE.findall(_text(_ENGINES_TPL)))
    assert len(engine_components) >= 16, (
        f"parsed only {len(engine_components)} components from engines.yaml; the chart declares "
        f"sixteen. The parser has stopped matching the template's form, and every set comparison "
        f"in this file is now vacuous."
    )

    # POSITIVE CONTROL for the address check: prove the pattern fires on a string that must match,
    # so a clean result below means "no address present" and not "the pattern is broken".
    assert _ADDRESS_LITERAL.search("endpoint 10.0.0.1:9000"), (
        "the address-literal pattern does not match an obvious address — the leak check below "
        "would report clean for any input"
    )


def test_NO_ADDRESS_LITERAL_IN_EITHER_TEMPLATE():
    """Infra detail is never committed. External endpoints reach these policies through
    `.Values.networkPolicy.extraEgress`, which is why the templates need no address of their own."""
    for p in (_NP_ENGINES, _NP_STORES):
        hits = _ADDRESS_LITERAL.findall(_text(p))
        assert not hits, (
            f"{p.name} contains what looks like an address literal: {hits}. External endpoints "
            f"belong in values, passed through extraEgress, never in a tracked template."
        )


# ── drift: the engine list is necessarily duplicated, so it is sealed ────────────────────────

def test_EVERY_ENGINE_IN_THE_CHART_HAS_AN_EGRESS_POLICY():
    """Helm offers no way to share a list between two template files, so
    `networkpolicy-engines.yaml` repeats `engines.yaml`'s enumeration. A repeated population
    drifts, and the drift is silent in the worst direction: a NEW engine simply has no policy, so
    it is the one pod in the fleet with unrestricted egress and nothing says so.

    This arm is the reason that duplication is acceptable."""
    in_chart = set(_COMPONENT_IN_TEMPLATE.findall(_text(_ENGINES_TPL)))
    in_policy = set(_COMPONENT_IN_TEMPLATE.findall(_text(_NP_ENGINES)))

    missing = in_chart - in_policy
    assert not missing, (
        f"engines with no egress policy: {sorted(missing)}. Each is a pod whose egress is "
        f"unrestricted while the chart reads as though the perimeter is closed."
    )
    extra = in_policy - in_chart
    assert not extra, (
        f"the policy file names components the chart does not deploy: {sorted(extra)}. Each is a "
        f"selector that matches no pod — valid YAML that silently protects nothing."
    )


# ── the population, translated ───────────────────────────────────────────────────────────────

def test_THE_ALLOWLIST_TRANSLATES_TO_COMPONENTS_THAT_EXIST():
    """The translation table is the load-bearing part of these templates. An entry that maps to a
    component the chart never renders is the silent-deny defect this file opens with."""
    mod = _load_allowlist_module()
    allowlist = dict(mod.SUBSTRATE_CLIENTS)
    assert len(allowlist) >= 4, "the allowlist parsed to almost nothing; the population is unreal"

    untranslated = sorted(set(allowlist) - set(AGENT_TO_COMPONENT))
    assert not untranslated, (
        f"allowlisted pods with no component mapping: {untranslated}. A pod admitted to the "
        f"substrate with no chart component cannot be expressed as a podSelector at all, so it "
        f"would be denied by a policy that looks complete."
    )

    deployed = set(_COMPONENT_IN_TEMPLATE.findall(_text(_ENGINES_TPL))) | {"mesh-registrar"}
    for agent, comp in AGENT_TO_COMPONENT.items():
        assert comp in deployed, (
            f"{agent} maps to component {comp!r}, which the chart does not deploy. A selector on "
            f"{comp!r} matches no pod and denies silently."
        )


def test_THE_EXCEPTION_IS_ADMITTED_AND_IS_NOT_AN_ALLOWLIST_ENTRY():
    """presentation-agent reaches Weaviate over `urllib.request` — no driver package, so no
    import ban can see it. It is load-bearing until the MeshVectors migration, so the policy MUST
    admit it; admitting it is what makes the policy honest instead of aspirational.

    It must also NOT have quietly become an allowlist entry, which would make the exception
    decorative and the access simply permitted."""
    mod = _load_allowlist_module()
    assert "presentation-agent" not in mod.SUBSTRATE_CLIENTS, (
        "presentation-agent is now an allowlist entry as well as an exception — the partition "
        "rule. Both at once means nothing ends the access."
    )
    names = {e.pod for e in mod.EXCEPTIONS}
    assert "presentation-agent" in names, (
        "presentation-agent is no longer a recorded exception. If the access ended, remove it "
        "from the store policy in the same change; if it did not, the exception must say so."
    )


def test_THE_EXCEPTION_GRANT_EXPIRES_WITH_THE_EXCEPTION():
    """⛔ The grant in the chart and the exception in this suite must die together.

    An exception that cannot expire is not an exception, it is the policy written where nobody
    looks — and a NetworkPolicy rule is an even better hiding place than a Python list, because
    nobody greps a chart for a security decision. So once the recorded backstop has passed, the
    presence of `engine-f` in the store policy is itself the failure."""
    mod = _load_allowlist_module()
    exc = next(e for e in mod.EXCEPTIONS if e.pod == "presentation-agent")
    if date.today() <= exc.backstop:
        pytest.skip(
            f"the presentation-agent exception has not reached its backstop "
            f"({exc.backstop.isoformat()}); the grant in the store policy is still in force"
        )
    assert "engine-f" not in _text(_NP_STORES), (
        f"the presentation-agent exception passed its backstop {exc.backstop.isoformat()} and "
        f"engine-f is still admitted to the stores. Either the MeshVectors migration landed and "
        f"this rule should go, or the backstop needs moving ON PURPOSE with a reason."
    )


# ── the rendered objects: what the cluster would actually get ────────────────────────────────

_NEEDS_HELM = pytest.mark.skipif(
    shutil.which("helm") is None,
    reason="the `helm` binary is not on PATH — a DECLARED condition (binary absent), not a probe "
           "of any cluster. These arms render the chart locally and need no cluster at all.",
)


@_NEEDS_HELM
def test_THE_GATE_DEFAULTS_CLOSED():
    """Read the default FROM the artifact rather than restating it. These policies change traffic,
    and enabling them before the direct-substrate callers are migrated breaks them, so the chart's
    default must be off — and that is a property of the render, not of a comment."""
    assert _render(enabled=False) == [], (
        "the chart renders NetworkPolicy objects with default values. Enabling this perimeter is "
        "a behavioural change and must be an operator's explicit decision."
    )


@_NEEDS_HELM
def test_THE_GATE_ACTUALLY_OPENS():
    """The inverse control. A gate that renders nothing either way would pass the arm above while
    shipping no policy at all — the same vacuous green, one layer up."""
    assert _render(enabled=True), (
        "networkPolicy.enabled=true renders no NetworkPolicy. The templates are inert, and every "
        "arm that reads their TEXT would still pass."
    )


def _direct_callers(values: Path | None) -> dict[str, set[str]]:
    """store component -> {caller components listing it}, READ FROM THE VALUES FILE (the chart's
    values.yaml, overlaid by `values` if given). Never typed here: the population is the file's."""
    merged = (yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8")) or {})
    cfg = dict(((merged.get("networkPolicy") or {}).get("directCallers")) or {})
    if values is not None:
        over = yaml.safe_load(values.read_text(encoding="utf-8")) or {}
        cfg = dict(((over.get("networkPolicy") or {}).get("directCallers")) or cfg)
    out: dict[str, set[str]] = {}
    for caller, entries in cfg.items():
        for e in entries or []:
            out.setdefault(e["store"], set()).add(caller)
    return out


def _assert_store_policies_admit_exactly(values: Path | None) -> None:
    mod = _load_allowlist_module()
    base = {AGENT_TO_COMPONENT[a] for a in mod.SUBSTRATE_CLIENTS} | {"engine-f"}
    direct = _direct_callers(values)

    stores = [p for p in _render(enabled=True, values=values) if (p.get("spec") or {}).get("ingress")]
    assert stores, "no NetworkPolicy with an ingress rule rendered; the store half is missing"

    for pol in stores:
        name = pol.get("metadata", {}).get("name", "<unnamed>")
        store = (pol["spec"]["podSelector"]["matchLabels"])["app.kubernetes.io/component"]
        expected = base | direct.get(store, set())
        got = _from_components(pol)
        assert got == expected, (
            f"{name} admits {sorted(got)}; expected exactly {sorted(expected)}. "
            f"Missing {sorted(expected - got)} would be denied silently; extra {sorted(got - expected)} "
            f"is a wider grant than the allowlist plus the directCallers entries record."
        )


@_NEEDS_HELM
def test_THE_STORE_POLICY_ADMITS_EXACTLY_THE_ALLOWLIST_PLUS_THE_EXCEPTION():
    """Set EQUALITY, in both directions. A subset check would miss an over-wide rule, which is the
    failure that matters for a control whose whole purpose is to exclude.

    Expected per store = allowlist U {engine-f} U {components whose directCallers entry names the
    store}, the last read from the values file. At chart defaults directCallers is empty, so this
    arm is the original allowlist-plus-exception equality; the sandbox arm below is the same
    equality with the population present."""
    _assert_store_policies_admit_exactly(None)


@_NEEDS_HELM
def test_THE_STORE_POLICY_ADMITS_THE_ALLOWLIST_PLUS_THE_EXCEPTION_PLUS_THE_DIRECT_CALLERS():
    """The same exact equality under values-sandbox.yaml, where directCallers is populated. A
    population that is non-empty here is what makes the per-store union non-trivial."""
    sandbox = _CHART / "values-sandbox.yaml"
    assert any(_direct_callers(sandbox).values()), "values-sandbox.yaml carries no directCallers"
    _assert_store_policies_admit_exactly(sandbox)


@_NEEDS_HELM
def test_EVERY_EGRESS_POLICY_ALLOWS_DNS():
    """A default-deny egress with no DNS rule breaks name resolution, and then every other rule in
    the policy is unreachable — presenting as a DNS outage rather than as a policy defect.

    Presence, not position: egress rules are a union and their order means nothing."""
    egress_policies = [
        p for p in _render(enabled=True)
        if "Egress" in ((p.get("spec") or {}).get("policyTypes") or [])
    ]
    assert egress_policies, "no egress policy rendered"

    for pol in egress_policies:
        name = pol.get("metadata", {}).get("name", "<unnamed>")
        ports: set[tuple[str, int]] = set()
        for rule in (pol.get("spec") or {}).get("egress") or []:
            for peer in rule.get("to") or []:
                sel = (peer.get("podSelector") or {}).get("matchLabels") or {}
                if sel.get("k8s-app") == "kube-dns":
                    for port in rule.get("ports") or []:
                        ports.add((port.get("protocol"), port.get("port")))
        assert ("UDP", 53) in ports, f"{name} has no UDP/53 egress to kube-dns"
        assert ("TCP", 53) in ports, (
            f"{name} has no TCP/53 egress to kube-dns — resolution falls back to TCP for large "
            f"responses, so UDP alone fails intermittently and looks like a flake"
        )


# ── what the TEXT arms structurally cannot see ───────────────────────────────────────────────
#
# `test_EVERY_ENGINE_IN_THE_CHART_HAS_AN_EGRESS_POLICY` compares two FILES and passes 16-to-16.
# The render is 10 policies, because both files gate each entry on that engine's `.enabled` and
# six engines ship disabled. The text arm cannot see that, and a text arm never could: it
# compares populations, and the hazard lives in the CONDITIONS attached to them. An engine whose
# Deployment renders under one condition and whose policy renders under another deploys with
# unrestricted egress while both files still name it. So the arms below assert against the
# RENDER, where a condition has already been evaluated.

def _engine_components() -> set[str]:
    """The chart's own engine enumeration, read from engines.yaml. Deliberately the TEXT, because
    the point of the next arm is to compare that declared population against what RENDERED."""
    return set(_COMPONENT_IN_TEMPLATE.findall(_text(_ENGINES_TPL)))


def _rendered(enabled: bool) -> list[dict]:
    cmd = ["helm", "template", "iagent", str(_CHART)]
    if enabled:
        cmd += ["--set", "networkPolicy.enabled=true"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"helm template failed: {proc.stderr[-2000:]}"
    return [d for d in yaml.safe_load_all(proc.stdout) if isinstance(d, dict)]


def _workload_components(docs: list[dict]) -> set[str]:
    out: set[str] = set()
    for d in docs:
        if d.get("kind") not in ("Deployment", "StatefulSet"):
            continue
        comp = ((d.get("metadata") or {}).get("labels") or {}).get("app.kubernetes.io/component")
        if comp:
            out.add(comp)
    return out


def _egress_target_components(docs: list[dict]) -> set[str]:
    """Components named as the DESTINATION of an egress rule. The DNS rule is excluded: it selects
    on `k8s-app`, in another namespace, and is not a component of this chart."""
    out: set[str] = set()
    for pol in docs:
        if pol.get("kind") != "NetworkPolicy":
            continue
        for rule in (pol.get("spec") or {}).get("egress") or []:
            for peer in rule.get("to") or []:
                sel = (peer.get("podSelector") or {}).get("matchLabels") or {}
                comp = sel.get("app.kubernetes.io/component")
                if comp:
                    out.add(comp)
    return out


@_NEEDS_HELM
def test_EVERY_RENDERED_ENGINE_WORKLOAD_HAS_AN_EGRESS_POLICY():
    """THE ARM THE TEXT COMPARISON CANNOT MAKE — a deployed engine with no policy on it.

    Both sides come from ONE render, so this holds under any values file rather than only under
    the defaults: whatever set of engines a deployment turns on, that same set must have egress
    policies. A divergence means an engine's Deployment and its policy are gated on different
    conditions, and the pod that renders without a policy is the one pod in the fleet with
    unrestricted egress at exactly the moment the chart reads as though the perimeter is closed.

    Measured 2026-09-28 at chart defaults: 10 engines render, 10 egress policies render.
    """
    docs = _rendered(enabled=True)
    engines = _engine_components()
    deployed_engines = _workload_components(docs) & engines
    assert deployed_engines, (
        "no engine workload rendered at all, so this arm proved nothing — it would pass an empty "
        "chart. The render, not the assertion, is what failed."
    )
    policed = {
        ((p.get("spec") or {}).get("podSelector") or {}).get("matchLabels", {}).get(
            "app.kubernetes.io/component"
        )
        for p in docs
        if p.get("kind") == "NetworkPolicy"
        and "Egress" in ((p.get("spec") or {}).get("policyTypes") or [])
    }
    unpoliced = deployed_engines - policed
    assert not unpoliced, (
        f"these engines render a workload but NO egress policy: {sorted(unpoliced)}. Their "
        f"Deployment and their policy are gated on different conditions. Each is a pod with "
        f"unrestricted egress in a chart that now advertises a perimeter."
    )


@_NEEDS_HELM
def test_NO_EGRESS_RULE_NAMES_A_COMPONENT_THE_CHART_CANNOT_DEPLOY():
    """A podSelector naming a component that exists NOWHERE in the chart is the silent-deny defect
    in its purest form: valid YAML, clean deploy, and the dependency is simply never reachable.
    A typo in an egress target cannot be caught by reading the rendered policy, because the
    rendered policy looks exactly right.

    ⚠ THE TWO POLICY TEMPLATES ARE EXCLUDED FROM THE DECLARABLE SET, AND THAT EXCLUSION IS THE
    WHOLE ARM. Measured 2026-09-28: without it this guard could not fire. Every component a
    policy names is written as an `app.kubernetes.io/component:` line INSIDE the policy file, so
    a scan that includes those files finds the typo declaring itself and the arm passes for the
    same reason it should have failed. It was caught by mutation, not by review — typing
    `lite-llm` into rule 4 left this arm green while a different arm went red.
    """
    docs = _rendered(enabled=True)
    _self = {_NP_ENGINES.name, _NP_STORES.name}
    declarable = set()
    for tpl in _TPL.glob("*.yaml"):
        if tpl.name in _self:
            continue
        declarable |= set(_COMPONENT_LABEL.findall(_text(tpl)))
        declarable |= set(_COMPONENT_IN_TEMPLATE.findall(_text(tpl)))
    assert "cortex-bff" in declarable and "litellm" in declarable, (
        f"POSITIVE CONTROL on the exclusion: the declarable set must still be built from the rest "
        f"of the chart. It has {len(declarable)} components and is missing a known one, so the "
        f"exclusion has removed too much and this arm would red on correct templates."
    )
    unknown = _egress_target_components(docs) - declarable
    assert not unknown, (
        f"egress rules name components no template in this chart declares: {sorted(unknown)}. "
        f"Each selects nothing, in every deployment, forever — and looks correct."
    )


@_NEEDS_HELM
def test_THE_EGRESS_TARGETS_THAT_SELECT_NO_POD_ARE_THE_KNOWN_TWO():
    """⚠ THE ONE THAT MATTERS, AND IT IS A RATCHET RATHER THAN A PROOF.

    A rule naming a real component is NOT evidence the dependency is reachable. At chart defaults
    two of the three named targets render no workload — `meshRegistrar.enabled` and
    `litellm.enabled` are both false — so their rules select nothing while reading as coverage.

    That is tolerable for the registrar: `values-sandbox.yaml` sets `meshRegistrar.enabled: true`,
    so the rule is live where it matters. **It is NOT tolerable for the model gateway, and this is
    the finding this arm exists to carry.** Measured 2026-09-28 against `values-sandbox.yaml`:
    `litellm:` is ABSENT from that file, so it inherits `enabled: false`, and both of that file's
    mentions of the in-cluster proxy are COMMENTS. The endpoint the fleet actually uses is set by
    `LLM_BASE_URL` to an off-cluster numeric host, which no podSelector can ever match.

    So enabling this gate against sandbox as shipped denies every engine its model and embedding
    endpoint, and `extraEgress` — the only rule that could reach an off-cluster host — defaults to
    empty. The failure would present as model timeouts, not as a policy error, which is the same
    shape as the missing-DNS-rule hazard one rule up.

    This arm cannot assert reachability; nothing renderable can. It asserts that the set of
    targets selecting no pod does not GROW unnoticed. A third name appearing here means the
    perimeter has quietly acquired another dependency it cannot reach.
    """
    docs = _rendered(enabled=True)
    inert = _egress_target_components(docs) - _workload_components(docs)
    assert inert == {"mesh-registrar", "litellm"}, (
        f"the inert egress targets at chart defaults are {sorted(inert)}, not the recorded "
        f"{sorted({'mesh-registrar', 'litellm'})}.\n"
        f"GROWN: a new target selects no pod. Ask which dependency just became unreachable when "
        f"the gate is on, and whether it is off-cluster — in which case it belongs in "
        f"extraEgress, not in a podSelector.\n"
        f"SHRUNK: a component was enabled by default, or a rule was deleted. Update this record "
        f"and say which, because a smaller set here is not automatically an improvement."
    )
