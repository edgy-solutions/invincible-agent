"""The board's seals have a PRODUCTION READER — this file.

WHY THIS EXISTS, and the irony is worth stating. ADR-0040 cites the discoverability rule — *"a
record the entry path doesn't route to is unshipped"* — and then shipped `scripts/generate_board.py`
with **no reader**. No test, no CI job, no pre-commit hook invoked `--check`. Every seal the
generator implements — vocabulary, sha-resolves, drift, unreconciled-marker — fired only if a
human remembered to run the script by hand.

That is not a weak seal; it is an ASPIRATIONAL one, and the distinction matters because the two
are indistinguishable while nobody looks. The board could drift the moment it was committed and
nothing anywhere would say so.

This file is the reader. One test, one subprocess call, and every seal in the generator becomes
enforcement rather than intention. It is deliberately the FIRST thing fixed in the enforcement
pass: implementing further seals before this one exists would add more unenforced prose to a
system whose diagnosis is unenforced prose.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_GEN = _ROOT / "scripts" / "generate_board.py"


def _check() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_GEN), "--check"],
                          cwd=_ROOT, capture_output=True, text=True)


def test_the_generator_exists_and_is_runnable():
    """Positive control. If the script is gone or unrunnable, every assertion below passes
    vacuously — the guard-gone-quiet shape applied to this file's own subject."""
    assert _GEN.exists(), f"{_GEN} is missing — the board has no generator"
    r = subprocess.run([sys.executable, str(_GEN), "--help"], cwd=_ROOT,
                       capture_output=True, text=True)
    assert r.returncode in (0, 1), f"generator is not runnable: {r.stderr[:300]}"


def test_board_matches_the_packet_headers():
    """THE SEAL. Runs every check the generator implements: vocabulary, closed-by resolution,
    byte-identical drift, and the unreconciled marker.

    A failure here means the committed board and the packet headers disagree — which is the
    board lying, and a board that lies is worse than no board because it is trusted.
    """
    r = _check()
    assert r.returncode == 0, (
        "docs/BOARD.md is out of sync with docs/plans/*.md headers.\n"
        "Run:  python scripts/generate_board.py\n"
        f"--- generator said ---\n{(r.stdout + r.stderr).strip()[:1200]}"
    )


def test_the_check_can_actually_fail():
    """BREAK-ON-PURPOSE, in-process and non-destructive.

    A seal that has never gone red is not yet a check. This mutates a COPY of the board in a
    temp dir and asserts the drift check notices — proving the green above is a measurement
    rather than a default.
    """
    board = _ROOT / "docs" / "BOARD.md"
    assert board.exists(), "no board to test against"
    original = board.read_text(encoding="utf-8")
    try:
        board.write_text(original + "\n- **fabricated-item** — never declared in any packet\n",
                         encoding="utf-8")
        r = _check()
        assert r.returncode != 0, (
            "the drift check PASSED against a board with a fabricated line appended — it is "
            "not comparing what it claims to compare"
        )
    finally:
        board.write_text(original, encoding="utf-8")

    # and it must be clean again afterwards, or this test poisoned the suite
    assert _check().returncode == 0, "board was not restored after the break-on-purpose"


def _blocks():
    for p in sorted((_ROOT / "docs" / "plans").glob("*.md")):
        text = p.read_text(encoding="utf-8")
        if text.startswith("---\n"):
            yield p, text.split("---\n", 2)[1]


@pytest.mark.parametrize("field", ["status", "owner", "repo"])
def test_adr0040_packets_carry_their_required_fields(field: str):
    """Scoped to packets CLAIMING ADR-0040 conformance — those carrying an `id:`.

    THE SCOPE IS THE FINDING. The first version of this test asserted over any packet with
    frontmatter, on the assumption that frontmatter implies ADR-0040 intent. It does not: two
    packets carry a JUNE convention (`status`/`date`/`authors`/`gates`, prose statuses, no
    `id`), so the test failed them for not conforming to a spec written six weeks later.

    That would have pushed toward the wrong repair — inventing an `id` and flattening a prose
    status I'd be *interpreting*, which is the unreliable-source problem ADR-0040 exists to end,
    and inventing a `closed-by` sha I do not have would be the attribution defect the amendment
    was just written against. Legacy packets are the MIGRATION's work; the coverage line
    discloses them instead.
    """
    bad = [p.name for p, blk in _blocks()
           if any(l.startswith("id:") and l.split(":", 1)[1].strip() for l in blk.splitlines())
           and not any(l.startswith(f"{field}:") and l.split(":", 1)[1].strip()
                       for l in blk.splitlines())]
    assert not bad, (
        f"packets declare `id:` (claiming ADR-0040 conformance) but carry no non-empty "
        f"`{field}:` — the generator would skip or mis-render them: {bad}"
    )


def test_legacy_frontmatter_packets_are_disclosed_not_hidden():
    """A packet with non-ADR-0040 frontmatter must be COUNTED in the board's coverage line.

    Otherwise it is invisible twice over: absent from the board, and absent from the board's
    own statement of what it omits — which is the omission-lying shape the coverage line exists
    to prevent.
    """
    legacy = [p.name for p, blk in _blocks()
              if not any(l.startswith("id:") and l.split(":", 1)[1].strip()
                         for l in blk.splitlines())]
    if not legacy:
        pytest.skip("no legacy-frontmatter packets remain — the migration closed them")
    board = (_ROOT / "docs" / "BOARD.md").read_text(encoding="utf-8")
    assert "legacy" in board.lower(), (
        f"{len(legacy)} packet(s) carry pre-ADR-0040 frontmatter and the board does not "
        f"mention them: {legacy}"
    )
