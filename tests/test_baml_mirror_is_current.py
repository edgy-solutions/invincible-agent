"""The generated BAML client must match its source — because THE GENERATED COPY IS WHAT RUNS.

THE DEFECT THIS MAKES UNCOMMITTABLE (2026-08-19, third instance of one family). Editing
`baml_src/contracts.baml` and not regenerating leaves `baml_client/inlinedbaml.py` carrying the
OLD text — and `inlinedbaml.py` is what the runtime loads. The edit is then **a no-op wearing a
diff**: the source review shows the intended change, the tests read the source, and the running
system keeps the previous prompt.

Caught by hand twice before it was caught by anything:

  * the citation seal (`db4eed4`) nearly shipped a dead link through `inlinedbaml.py` because
    "it's generated" felt like a reason to skip the file;
  * the three-part landing (2026-08-19) trimmed the `instance_identifier` prompt and the mirror
    still contained `gold.sales.revenue_summary` — the exact example being removed.

Same family as *commit-is-not-deploy* one layer down: an artifact whose real consumer reads a
DERIVED copy, and where changing the origin feels like changing the thing.

WHY THIS COMPARES TEXT RATHER THAN RUNNING `baml-cli`: the CLI is a toolchain dependency that
may be absent in CI, and a guard that skips when its tool is missing is a guard that reports
green over the failure — the population-drains-away shape from
[[a-green-check-proves-only-its-scope]]. The inlined map already contains each source verbatim,
so the comparison needs nothing but the two files.

SCOPE. IN: every `*.baml` under `baml_src` is present in the mirror and byte-identical.
OUT: that the rest of the generated client (types, function stubs) is current — a signature
change with no source-text change would pass here. Stated rather than implied.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
_SRC = _REPO / "baml_shared" / "baml_src"
_MIRROR = _REPO / "baml_shared" / "baml_client" / "baml_client" / "inlinedbaml.py"


def _inlined() -> dict[str, str]:
    """Decode the mirror's {filename: source} map without importing baml_py."""
    text = _MIRROR.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(r'"([A-Za-z0-9_.-]+\.baml)":\s*("(?:[^"\\]|\\.)*")', text):
        out[m.group(1)] = ast.literal_eval(m.group(2))
    return out


def test_the_mirror_covers_every_source_file():
    """A source file absent from the mirror is a file the runtime never sees."""
    inlined = _inlined()
    assert inlined, f"parsed no inlined sources from {_MIRROR} — the guard is broken, not the repo"
    missing = sorted({p.name for p in _SRC.glob("*.baml")} - set(inlined))
    assert not missing, (
        f"{missing} exist in baml_src but not in the generated client. Run "
        f"`baml-cli generate --from baml_shared/baml_src`."
    )
    # POPULATION SIZE, not just a verdict — the corollary from the scope law. A green with n
    # visible is falsifiable at a glance; a bare green is not.
    print(f"\n  mirror covers {len(inlined)} source file(s)")


@pytest.mark.parametrize("name", sorted(p.name for p in _SRC.glob("*.baml")))
def test_each_source_matches_the_generated_mirror(name):
    """THE ONE THAT BITES. Edit a .baml and forget to regenerate -> red here, not silence."""
    inlined = _inlined()
    # NEWLINES ARE NOT THE SUBJECT. The working tree is CRLF on Windows (.gitattributes) and
    # the generator writes LF into the mirror, so a byte comparison fails on every file for a
    # reason that has nothing to do with staleness — which would make this guard cry wolf on a
    # clean tree and get deleted. Compare CONTENT.
    on_disk = (_SRC / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    mirrored = (inlined.get(name) or "").replace("\r\n", "\n")
    assert mirrored == on_disk, (
        f"{name} differs from the copy inside inlinedbaml.py — THE GENERATED COPY IS WHAT RUNS, "
        f"so this edit currently has NO EFFECT on the system. Run "
        f"`baml-cli generate --from baml_shared/baml_src` and commit the result."
    )
