"""B3 standing guard — same-canonicalizer-both-sides drift detector.

Per the architect's B3 framing (2026-06-13): the B2 ingest writer and
the B3 phone-book reader must use the IDENTICAL canonicalizer code
path. Two parallel implementations would reproduce the
`n_candidates=0`-when-it-should-match failure that 49a3fdb (B2's DMC
fix) just closed at the write layer.

There are two copies of `dmc_canonicalizer.py` for legitimate
deployment reasons:

  - `doc-tools/doc_tools/parsers/dmc_canonicalizer.py` — read by the
    B2 ingest pipeline. doc-tools is a Dagster code location loaded
    by the dagster-control-plane image.

  - `agent_fleet/utils/dmc_canonicalizer.py` — read by the B3 DMC
    phone book service. agent_fleet is the runtime engine fleet;
    using a sibling utility avoids cross-repo Python deps in the
    runtime image.

This test asserts the two files are BYTE-IDENTICAL via SHA256. Any
divergence (even a whitespace change) fails this test loudly, with
the offending sha hashes named so the operator can diff the two
files explicitly.

To intentionally update the canonicalizer: edit ONE copy, then `cp`
the file to the other. The test re-passes when SHA256 matches.
NEVER let drift go uncaught — it is exactly the kind of
canonical-form bug the same-canonicalizer rule was named to prevent.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent

AGENT_FLEET_COPY = REPO_ROOT / "agent_fleet" / "utils" / "dmc_canonicalizer.py"
DOC_TOOLS_COPY = Path(
    os.getenv(
        "DOC_TOOLS_REPO",
        REPO_ROOT.parent / "doc-tools",
    )
) / "doc_tools" / "parsers" / "dmc_canonicalizer.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dmc_canonicalizer_copies_are_byte_identical():
    """Same-canonicalizer-both-sides: the agent_fleet and doc-tools
    copies must have identical SHA256.

    If the two diverge, B2's write path and B3's read path will agree
    on most inputs by coincidence and disagree on edge cases — exactly
    the failure shape the rule was named to prevent. The cheap fix is
    `cp` one copy over the other; the test re-passes when SHA256
    matches.
    """
    assert AGENT_FLEET_COPY.exists(), (
        f"agent_fleet copy missing at {AGENT_FLEET_COPY}"
    )
    if not DOC_TOOLS_COPY.exists():
        pytest.skip(
            f"doc-tools copy not found at {DOC_TOOLS_COPY}. Set "
            f"DOC_TOOLS_REPO=/path/to/doc-tools to point at it. The "
            f"drift detector is skipped in environments without "
            f"doc-tools checked out alongside; CI must keep both."
        )

    fleet_sha = _sha256(AGENT_FLEET_COPY)
    doc_sha = _sha256(DOC_TOOLS_COPY)

    assert fleet_sha == doc_sha, (
        f"DMC canonicalizer drift detected:\n"
        f"  agent_fleet/utils/dmc_canonicalizer.py SHA256:\n"
        f"    {fleet_sha}\n"
        f"  doc-tools/doc_tools/parsers/dmc_canonicalizer.py SHA256:\n"
        f"    {doc_sha}\n"
        f"\n"
        f"Same-canonicalizer-both-sides rule violated. Resolve by\n"
        f"copying one canonical copy to the other:\n"
        f"  cp {DOC_TOOLS_COPY} {AGENT_FLEET_COPY}\n"
        f"or\n"
        f"  cp {AGENT_FLEET_COPY} {DOC_TOOLS_COPY}\n"
        f"\n"
        f"NEVER let this drift land. The B2 write path and B3 read\n"
        f"path use the canonicalizer to agree on the identity of every\n"
        f"DMC; any divergence reproduces the 49a3fdb failure shape\n"
        f"(n_candidates=0 when it should match)."
    )
