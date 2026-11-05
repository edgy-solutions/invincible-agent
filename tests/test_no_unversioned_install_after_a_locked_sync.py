"""NO UNVERSIONED INSTALL AFTER A LOCKED SYNC (board 01M6MZ6HK5PMK9VQ2PM95DC7E2, 0.4.79).

`uv sync --locked` makes the image's packages the ones `uv.lock` names. A `pip install <name>`
after it, with no version, resolves whatever the index serves at build time, so two builds of
one sha can differ, and the package's transitive pins leave the lock with it. The control-plane
image did exactly that with acryl-datahub, which the root lock already carried.

The rule, read from every `Dockerfile*` under `.github/docker/`: once a file has run a
`--locked` sync, every `pip install` names each package with a version (`==`), a URL or a path.
`-r <file>` and `-e <path>` install from a file or a tree and are not package names.

KNOWN_UNVERSIONED is the measured remainder, not an exemption list: the census must equal it
EXACTLY. A new unversioned install fails, and so does fixing one without deleting its row.
Dockerfile.agent's build tools are board 01M6N07ZJJ37W9NQ7KGRE1VRW9 (no reason was recorded for
them when the Dockerfile was extracted, eac4b5328, and pinning them changes every engine image).

Arms:
  1. The census of the real Dockerfiles equals KNOWN_UNVERSIONED.
  2. acryl-datahub is installed by no `pip install` in any Dockerfile (the lock carries it).
  3. CONTROL: the parser flags the removed Dockerfile.dagster line, and passes its pinned and
     before-the-sync forms.

Run: uv run pytest tests/test_no_unversioned_install_after_a_locked_sync.py -v
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKER_DIR = ROOT / ".github" / "docker"

KNOWN_UNVERSIONED = {
    ("Dockerfile.agent", "packaging"),
    ("Dockerfile.agent", "setuptools"),
    ("Dockerfile.agent", "wheel"),
}

# Options of `pip install` / `uv pip install` that take a value as the next word.
_VALUED = {"--python", "-p", "--index-url", "-i", "--extra-index-url", "--target", "-t",
           "--prefix", "-c", "--constraint", "--find-links", "-f", "--cache-dir"}
_FROM_FILE = {"-r", "--requirement", "-e", "--editable"}


def _instructions(text: str) -> list[str]:
    """The file's instructions with `\\` continuations joined and comments dropped."""
    out: list[str] = []
    cur = ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith("\\"):
            cur += s[:-1] + " "
            continue
        out.append(cur + s)
        cur = ""
    if cur:
        out.append(cur)
    return out


def _versioned(word: str) -> bool:
    return "==" in word or "@" in word or "://" in word or word.startswith((".", "/"))


def unversioned_after_locked_sync(text: str) -> list[str]:
    """Package names installed with no version after the file's first `--locked` sync."""
    found: list[str] = []
    locked = False
    for ins in _instructions(text):
        # Commands in the order the shell meets them; `if … then A else B fi` keeps both arms.
        for cmd in re.split(r"&&|\|\||;|\bthen\b|\belse\b|\bfi\b", ins):
            try:
                words = shlex.split(cmd, posix=True)
            except ValueError:  # a quote the split above cut in half; only bare words matter
                words = cmd.split()
            if "sync" in words and "--locked" in words:
                locked = True
                continue
            if not locked or "install" not in words or "pip" not in words[: words.index("install")]:
                continue
            args = words[words.index("install") + 1:]
            i = 0
            while i < len(args):
                w = args[i]
                if w in _FROM_FILE or w in _VALUED:
                    i += 2
                    continue
                if not w.startswith("-") and not _versioned(w):
                    found.append(w)
                i += 1
    return found


def _census() -> set[tuple[str, str]]:
    return {(p.name, pkg)
            for p in sorted(DOCKER_DIR.glob("Dockerfile*"))
            for pkg in unversioned_after_locked_sync(p.read_text(encoding="utf-8"))}


def test_the_census_is_exactly_the_known_remainder():
    assert sorted(DOCKER_DIR.glob("Dockerfile*")), "no Dockerfile found: the census read nothing"
    assert _census() == KNOWN_UNVERSIONED


def test_no_dockerfile_pip_installs_acryl_datahub():
    hits = [p.name for p in DOCKER_DIR.glob("Dockerfile*")
            if re.search(r"pip install[^\n]*acryl-datahub", p.read_text(encoding="utf-8"))]
    assert hits == []


_SYNC = 'RUN uv sync --locked --no-dev --no-install-project --compile-bytecode\n'


@pytest.mark.parametrize("text, expected", [
    # The line this PR removed from Dockerfile.dagster.
    (_SYNC + "RUN --mount=type=cache,target=/root/.cache/uv \\\n"
             "uv pip install --python /app/.venv/bin/python acryl-datahub\n", ["acryl-datahub"]),
    (_SYNC + "RUN uv pip install --python /app/.venv/bin/python acryl-datahub==1.7.0\n", []),
    ("RUN uv pip install acryl-datahub\n" + _SYNC, []),
    ('RUN if [ -f "uv.lock" ]; then uv sync --locked; else uv pip install --system -r r.txt; fi\n', []),
    (_SYNC + "RUN uv sync --locked && \\\nuv pip install packaging setuptools wheel\n",
     ["packaging", "setuptools", "wheel"]),
])
def test_control_the_parser_flags_the_removed_line_and_passes_its_fixed_forms(text, expected):
    assert unversioned_after_locked_sync(text) == expected
