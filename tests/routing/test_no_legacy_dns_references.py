"""Legacy-DNS class-guard — catches the stale ``*-svc.default.svc.cluster.local``
pattern at CI before it can reach a fresh-cluster bootstrap.

## The class this guards against

The codebase originally referenced engine HTTP endpoints via a
``<service>-svc.default.svc.cluster.local`` DNS pattern (services living in
the ``default`` K8s namespace under names like ``weaviate-expert-svc``,
``neo4j-expert-svc``, ``data-analyst-svc``, ``restate-agent-svc``,
``datahub-wrapper-svc``, ``ontology-svc``, etc.). The current cluster naming
convention is ``<release>-<component>`` rendered by the helm chart's
``{{ .Release.Name }}-{{ .component }}`` template — so services are
``iagent-engine-e``, ``iagent-engine-w``, ``iagent-data-analyst``,
``iagent-engine-a``, ``iagent-engine-d``, ``iagent-engine-o``, etc.

The legacy DNS doesn't resolve in the current cluster. Any source file that
still defaults to it has a **fresh-bootstrap failure mode**: the cluster
comes up, an engine reads its own ``XYZ_PUBLIC_URL`` default, registers a
verb endpoint nobody can reach, and dispatch silently fails for that route.

The 2026-06-16 durability check found this pattern in 14 places across 6
files (B4 verb arc consolidation). The architect framed the discipline as
the writer-hunt one more time: *don't fix the three you found, find whether
there's a fourth, and fix the class.* That is what this guard enforces from
here forward — no new file may default to the legacy DNS pattern without
landing on the allowlist (which is intentionally hard to add to).

## Scope

The guard scans every text source file in the repository's primary work
trees (``agent_fleet/``, ``src/``, ``scripts/``, ``helm/``, ``doc-tools/``,
``tests/``, ``setup/``) for occurrences of the literal substring
``.default.svc.cluster.local``. It fails the test if any non-allowlisted
reference is found.

The allowlist is reserved for **descriptive references** (this docstring,
the help text in ``helm/.../values.yaml`` that names the pattern as an
example, the hibernated ``scripts/recreate_verb_edges.py`` recovery
script's docstring). New entries to the allowlist require deliberate
addition with a short rationale comment.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# The literal substring we forbid in live defaults.
LEGACY_DNS_PATTERN = ".default.svc.cluster.local"

# Directories scanned. Relative to repo root.
SCANNED_DIRS = (
    "agent_fleet",
    "src",
    "scripts",
    "helm",
    "doc-tools",
    "tests",
    "setup",
)

# File extensions we care about.
SCANNED_EXTS = (".py", ".yaml", ".yml", ".tpl", ".toml", ".json", ".sh", ".md")

# Allowlist: (relative_path, line_substring_match) — line text must contain
# the substring for the exemption to apply. The exemption is intentionally
# narrow so a new live reference in a previously-exempt file still trips
# the guard.
#
# Every allowlist entry must reference text that is documentary, not a
# live default. Adding to this list is a deliberate act that should be
# accompanied by a comment explaining why the reference is descriptive.
ALLOWLIST: list[tuple[str, str]] = [
    # This file's own description of the pattern.
    ("tests/routing/test_no_legacy_dns_references.py", "LEGACY_DNS_PATTERN"),
    ("tests/routing/test_no_legacy_dns_references.py", "<service>-svc."),
    ("tests/routing/test_no_legacy_dns_references.py", ".default.svc.cluster.local"),
    # Helm values comment naming the pattern as an example of K8s DNS.
    ("helm/invincible-agent/values.yaml", "Suffix for internal K8s service resolution"),
    # Hibernated recovery script's docstring describes the historical pattern.
    ("scripts/recreate_verb_edges.py", "DNS pattern to the current actual"),
    # State doc + demo script + deploy checklist reference the pattern by
    # name when describing the durability finding. Documentary, not live.
    ("tests/routing/STATE_GATEWAY_V02.md", "default.svc.cluster.local"),
    ("docs/demo-script.md", "default.svc.cluster.local"),
    ("tests/routing/SESSION_3_DEPLOY_CHECKLIST.md", "default.svc.cluster.local"),
    ("tests/routing/GUARD_SIBLING_AUDIT.md", "default.svc.cluster.local"),
    # 2026-06-17 incident commentary: helm values-sandbox.yaml comments
    # name the legacy DNS pattern when explaining what the env-var pins
    # are reproducing-around (the OLD image's source default that
    # would re-register the broken URL on pod restart). Documentary
    # references to the pattern in a comment block, not live defaults.
    ("helm/invincible-agent/values-sandbox.yaml", "data-analyst-svc.default.svc.cluster.local"),
    ("helm/invincible-agent/values-sandbox.yaml", "restate-agent-svc.default.svc.cluster.local"),
    ("helm/invincible-agent/values-sandbox.yaml", "datahub-wrapper-svc.default.svc.cluster.local"),
    # The new substrate-DNS guard's own docstring + LEGACY_DNS_FRAGMENT
    # constant name the pattern textually so the guard knows what
    # substring to look for in Neo4j edges. Self-reference, not a live
    # default.
    ("tests/routing/test_substrate_invariants.py", "default.svc.cluster.local"),
]


# Directories that are NOT this repo's source: virtualenvs, vendored deps, caches, VCS metadata.
# EXCLUDING THEM IS A CORRECTNESS FIX, not just a speed one — a legacy-DNS string inside vendored
# `site-packages` is not a "live default" of this repo, so scanning there could only ever produce a
# FALSE POSITIVE. It is also what made this test crash: `agent_fleet/restate_analyst/.venv.wsl/lib64`
# is a DANGLING WSL SYMLINK, and `Path.is_file()` on it raises OSError [WinError 1920] on Windows,
# aborting the whole scan before a single file was checked. The test failed for months with an
# environment error that looked nothing like the contract it guards.
_SKIP_DIRS = {".venv", ".venv.wsl", "venv", "node_modules", "__pycache__", ".git",
              ".pytest_cache", ".mypy_cache", ".ruff_cache", "site-packages", ".tox"}


def _scan_files(base):
    """Yield real files under `base`, pruning non-source trees and tolerating unreadable entries.

    Prunes DURING the walk (os.walk + dirnames mutation) rather than filtering after, so a broken
    symlink inside an excluded tree is never stat'ed at all — filtering afterwards would still have
    to touch it to decide, which is exactly what crashed.
    """
    import os as _os
    from pathlib import Path as _Path
    for dirpath, dirnames, filenames in _os.walk(base, onerror=lambda e: None, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".venv")]
        for name in filenames:
            fp = _Path(dirpath) / name
            try:
                if fp.is_file():
                    yield fp
            except OSError:
                continue


def _repo_root() -> Path:
    # tests/routing/test_no_legacy_dns_references.py → parents[2] is the repo root.
    return Path(__file__).resolve().parents[2]


def _is_allowlisted(rel_path: str, line_text: str) -> bool:
    for path_match, substring_match in ALLOWLIST:
        if rel_path.replace("\\", "/") == path_match and substring_match in line_text:
            return True
    return False


def test_no_live_legacy_dns_references() -> None:
    """Every source file's default endpoint must use the current K8s service name.

    If this fails, the legacy ``*-svc.default.svc.cluster.local`` DNS pattern
    has reappeared in a live default. Fix: replace with the current
    ``iagent-<component>:<port>`` form per the helm chart's service naming.
    See the docstring at the top of this file for the rationale and the
    class of bug this catches.
    """
    root = _repo_root()
    offenders: list[tuple[str, int, str]] = []
    assert SCANNED_DIRS, "nothing to scan — this guard would pass over an empty set"

    for d in SCANNED_DIRS:
        base = root / d
        if not base.exists():
            continue
        for path in _scan_files(base):
            if path.suffix not in SCANNED_EXTS:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except (UnicodeDecodeError, PermissionError, OSError):
                continue
            rel_path = str(path.relative_to(root))
            for lineno, text in enumerate(lines, start=1):
                if LEGACY_DNS_PATTERN not in text:
                    continue
                if _is_allowlisted(rel_path, text):
                    continue
                offenders.append((rel_path, lineno, text.strip()))

    assert not offenders, (
        f"Found {len(offenders)} live reference(s) to the legacy DNS pattern "
        f"'{LEGACY_DNS_PATTERN}'. The current cluster's services use the "
        f"'iagent-<component>:<port>' naming convention; legacy DNS does not "
        f"resolve in the current cluster and creates a silent fresh-bootstrap "
        f"failure (verb endpoints register against an unreachable URL). Fix "
        f"each offender to use the current service name, or — only if the "
        f"reference is genuinely descriptive (a docstring, a comment "
        f"explaining the pattern by name) — add a narrow allowlist entry "
        f"in this test file with a short rationale.\n\nOffenders:\n"
        + "\n".join(f"    - {p}:{ln}  {text}" for p, ln, text in offenders)
    )
