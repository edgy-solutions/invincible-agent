"""FRESH-DEPLOY ENV AUDIT — find hand-seeded state the chart does not reproduce.

Three bootstrap-debt instances surfaced by tripping over them in one evening (Restate
registrations for DA/W, DA's CORTEX_CLIENT_* creds, DA's Keycloak client). This finds the
REST of the class by looking instead of waiting: for every running pod, every env var NAME
is checked against the chart-rendered manifests (deployment env, ConfigMap keys, Secret
keys). A name present in the cluster and absent from the chart is state no fresh deploy
reproduces.

NAMES ONLY — values are never read, printed, or compared.

Usage: env_audit.py <rendered-chart.yaml> <pod-env-dump.json>
"""
import json, re, sys, collections

rendered = open(sys.argv[1], encoding="utf-8", errors="replace").read()
pods = json.load(open(sys.argv[2], encoding="utf-8"))

# ── PER-INPUT SENTINELS — the repair for this audit's own false positive ──────────────
# The first run rendered with values-sandbox.yaml ONLY and reported the Langfuse trio as
# hand-seeded. They were not: they live in values-sandbox.secret.yaml. The positive control
# passed and proved nothing, because every control token I picked came from the SAME input
# file as the finding — a control drawn from one source cannot detect a MISSING source.
#
# GENERAL FORM: a positive control must exercise every INPUT the conclusion depends on, not
# just every STAGE. So: one sentinel per values file, each a key whose ONLY home is that
# file. If any is missing from the render, the render is missing an input and this REFUSES
# rather than reporting — an absent input must not be able to manufacture findings.
SENTINELS = {
    "values.yaml": "OPENAI_API_KEY",              # base chart secrets block
    "values-sandbox.yaml": "WEAVIATE_HTTP_HOST",  # sandbox overlay
    "values-sandbox.secret.yaml": "LANGFUSE_HOST",  # secret overlay — the one that was missed
}
missing = [f"{f} (sentinel {s!r})" for f, s in SENTINELS.items() if s not in rendered]
if missing:
    print("REFUSING TO REPORT — the render is missing input(s):")
    for m in missing:
        print("   ", m)
    print("\nRe-render with every values file, e.g.:")
    print("  helm template <rel> <chart> -f values-sandbox.yaml -f values-sandbox.secret.yaml")
    sys.exit(2)

# Every identifier-ish token the chart mentions anywhere: env names, configmap/secret keys.
# Deliberately GENEROUS (substring over the whole render) — this audit must not cry wolf,
# so anything the chart mentions at all counts as reproduced.
chart_tokens = set(re.findall(r"[A-Z][A-Z0-9_]{2,}", rendered))

# Env injected by Kubernetes itself or the language runtime — not chart responsibility.
IGNORE_EXACT = {
    "PATH", "HOME", "HOSTNAME", "TERM", "PWD", "SHLVL", "LANG", "LC_ALL", "TZ",
    "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH", "VIRTUAL_ENV",
    "KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT", "KUBERNETES_PORT",
    "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "UV_", "NVIDIA_", "CUDA_",
}
IGNORE_PREFIX = ("KUBERNETES_", "NVIDIA_", "CUDA_", "UV_")
# k8s auto-injects <SVC>_PORT / <SVC>_SERVICE_* for every service in the namespace.
SVC_LINK = re.compile(r"^[A-Z0-9_]+_(PORT|SERVICE_HOST|SERVICE_PORT[A-Z0-9_]*|PORT_\d+[A-Z0-9_]*)$")


def ignorable(name: str) -> bool:
    if name in IGNORE_EXACT or name.startswith(IGNORE_PREFIX):
        return True
    return bool(SVC_LINK.match(name))


findings = collections.defaultdict(list)
for pod, names in sorted(pods.items()):
    for n in sorted(names):
        if ignorable(n):
            continue
        if n not in chart_tokens:
            findings[pod].append(n)

print("=" * 78)
print("HAND-SEEDED ENV — present in the running pod, absent from the rendered chart")
print("=" * 78)
if not findings:
    print("none — every pod env name is reproduced by the chart")
for pod, names in sorted(findings.items()):
    print(f"\n{pod}  ({len(names)})")
    for n in names:
        print(f"    {n}")
print(f"\nTOTAL: {sum(len(v) for v in findings.values())} names across {len(findings)} pods")
