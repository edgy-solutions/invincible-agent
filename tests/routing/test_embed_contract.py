"""Standing guard: exactly ONE embedding-model name string in iagent code.

The vector-search contract lives in code (agent_fleet/utils/embed.py), NOT
in Weaviate config. Writers and readers across the fleet agree because they
all call ``embed_text()`` and ``embed_text()`` reads a single default model
name (``DEFAULT_EMBED_MODEL``).

If a second model name string appears anywhere in the agent_fleet tree —
a hot-fix line that hardcodes ``"text-embedding-3-small"``, a workaround
that uses ``"nomic-embed-8k:latest"`` to dodge the gateway, anything — the
two writers can produce numerically-incompatible vectors and reads against
them score garbage. This guard fails the build BEFORE that lands.

Pairs with the doc-tools guard
``tests/test_embed_contract.py``. The cross-repo agreement on the model
NAME (currently ``nomic-embed-text``) is enforced by code review on the
two ``DEFAULT_EMBED_MODEL`` constants; this guard enforces in-repo
single-source-of-truth.

Allow-listed mentions:
  - ``DEFAULT_EMBED_MODEL = "nomic-embed-text"`` in ``utils/embed.py``
    (the canonical declaration; one ALLOWED match here).
  - Doc-string examples / error-message hints that NAME the model in
    prose (e.g. "e.g. nomic-embed-text via Ollama-behind-LiteLLM") —
    these are documentation, not assignment / wire-format, and are
    skipped by the regex.

If the test fails, the failure message names the offending file and line.
Resolution is almost always "stop hardcoding the model name; call
``embed_text()`` instead, which reads ``LLM_EMBED_MODEL`` from env."
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_FLEET = REPO_ROOT / "agent_fleet"

# Model names that, if seen as a literal Python string assignment or
# wire-format value, would be a regression. Extend this list when a new
# embedding-model family enters the project — the guard pressures you to
# update the contract intentionally.
KNOWN_EMBEDDING_MODEL_NAMES = (
    "nomic-embed-text",
    "nomic-embed-8k:latest",  # legacy sandbox value; should not appear in code
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-ada-002",
    "BAAI/bge-large-en-v1.5",
)

# Lines that match this regex are exempt — they're declaring the contract,
# not violating it. Add new exemptions sparingly.
# The canonical contract assignment — must appear exactly once.
CONTRACT_DECLARATION = re.compile(r"DEFAULT_EMBED_MODEL\s*=\s*['\"]")

# Allowed fallback assignments: provider-specific defaults that are
# explicitly opted into by their variable name (e.g. _real_openai_default
# in mem0's SMOLAGENTS_PROVIDER=openrouter path). May appear 0..N times;
# each occurrence has to use the documented `_real_openai_default = "..."`
# shape, so a new fallback that wants a model name has to add itself
# explicitly and the reviewer sees it.
FALLBACK_DECLARATIONS = (
    re.compile(r"_real_openai_default\s*=\s*['\"]"),
)


def _is_allowed_line(line: str) -> bool:
    if CONTRACT_DECLARATION.search(line):
        return True
    return any(pat.search(line) for pat in FALLBACK_DECLARATIONS)


def _is_contract_declaration(line: str) -> bool:
    return bool(CONTRACT_DECLARATION.search(line))


def _line_is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _scan_file(text: str) -> list[tuple[int, str, str]]:
    """Yield (lineno, line, classification) for lines mentioning a model name.

    classification is one of: 'declaration', 'docstring', 'comment',
    'violation'. Uses proper multi-line docstring tracking — a line BETWEEN
    triple-quote pairs is treated as docstring even if it doesn't itself
    contain a triple quote.
    """
    out: list[tuple[int, str, str]] = []
    in_docstring = False
    docstring_delim = None  # '"""' or "'''"
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Track docstring state. A line CAN open and close on the same line
        # (e.g. `"""one liner"""`) — count occurrences of the active delimiter.
        if in_docstring:
            assert docstring_delim is not None
            # Count occurrences; if odd, we toggle out
            if line.count(docstring_delim) % 2 == 1:
                in_docstring = False
                docstring_delim = None
        else:
            for delim in ('"""', "'''"):
                if line.count(delim) % 2 == 1:
                    in_docstring = True
                    docstring_delim = delim
                    break

        # Now classify (use the IN-docstring state we just resolved, but
        # since opening lines also become "in" we treat the whole line as
        # docstring if the state is True now OR was True at line start).
        if not any(name in line for name in KNOWN_EMBEDDING_MODEL_NAMES):
            continue

        if _is_contract_declaration(line):
            out.append((lineno, line.strip(), "contract"))
            continue
        if _is_allowed_line(line):
            out.append((lineno, line.strip(), "fallback"))
            continue
        if in_docstring or _line_is_comment(line):
            out.append((lineno, line.strip(), "docstring_or_comment"))
            continue
        out.append((lineno, line.strip(), "violation"))
    return out


def test_only_canonical_embedding_model_name_in_iagent():
    """Assert no Python file in agent_fleet/ hardcodes a known embedding
    model name except in the allow-listed ``DEFAULT_EMBED_MODEL`` line and
    documentation/comment lines.

    The allow-listed declaration MUST exist exactly once (the contract).
    """
    declarations: list[tuple[str, int, str]] = []
    violations: list[tuple[str, int, str]] = []

    for py_file in AGENT_FLEET.rglob("*.py"):
        if any(part.startswith(".") for part in py_file.relative_to(AGENT_FLEET).parts):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, snippet, kind in _scan_file(text):
            if kind == "contract":
                declarations.append((str(py_file), lineno, snippet))
            elif kind == "violation":
                violations.append((str(py_file), lineno, snippet))
            # 'fallback' and 'docstring_or_comment' are exempt

    assert len(declarations) == 1, (
        f"DEFAULT_EMBED_MODEL declaration must appear exactly once across "
        f"agent_fleet/. Found {len(declarations)}:\n"
        + "\n".join(f"  {f}:{ln}  {snippet}" for f, ln, snippet in declarations)
    )

    assert not violations, (
        f"Hardcoded embedding model name(s) found outside the contract.\n"
        f"Resolve by calling agent_fleet.utils.embed.embed_document() or "
        f"embed_query() instead. They read LLM_EMBED_MODEL from env "
        f"(default 'nomic-embed-text') and apply the correct task prefix.\n"
        f"Offending lines:\n"
        + "\n".join(f"  {f}:{ln}  {snippet}" for f, ln, snippet in violations)
    )


# ---------------------------------------------------------------------------
# Task-prefix discipline guards
# ---------------------------------------------------------------------------
# nomic-embed-text uses asymmetric task prefixes:
#   - "search_document: " for corpus chunks (write side)
#   - "search_query: "    for user queries  (read side)
# Mixing them up — or using neither — silently splits the embedding space
# and tanks retrieval. Two guards keep this honest:
#
# (a) The literal prefix strings must appear ONLY in agent_fleet/utils/embed.py
#     (the contract). Anywhere else is a code path that hand-rolls prefixing,
#     which means a future model migration has to chase those strings down.
# (b) No code outside agent_fleet/utils/embed.py may import / call the
#     low-level helpers (embed_text, embed_texts, _post_embedding). All
#     non-helper code uses embed_document, embed_documents, or embed_query.
#     This forces every new vector path to declare its intent (write vs
#     read) at the call site.

EMBED_MODULE_RELATIVE = "agent_fleet/utils/embed.py"

PREFIX_STRINGS = (
    "search_document: ",
    "search_query: ",
)

# Symbols that MUST NOT appear outside the embed module. embed_text was the
# pre-prefix-split helper; embed_texts was its batch sibling. Any new code
# accidentally calling them is a contract regression that bypasses prefix
# discipline.
FORBIDDEN_LOW_LEVEL_SYMBOLS = (
    "embed_text",
    "embed_texts",
    "_post_embedding",
)


def test_prefix_strings_only_in_embed_module():
    """search_document: / search_query: literal strings may only appear in
    agent_fleet/utils/embed.py. Anywhere else is a hand-rolled prefix that
    bypasses the contract — fix by calling embed_document / embed_query."""
    violations: list[tuple[str, int, str]] = []
    embed_module_abs = AGENT_FLEET.parent / EMBED_MODULE_RELATIVE

    for py_file in AGENT_FLEET.rglob("*.py"):
        if py_file.resolve() == embed_module_abs.resolve():
            continue
        if any(part.startswith(".") for part in py_file.relative_to(AGENT_FLEET).parts):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(p in line for p in PREFIX_STRINGS):
                # Tolerate comments / docstrings referencing the prefix by
                # name; only flag string-literal occurrences. Conservative
                # heuristic: skip lines that are pure comments. Docstring
                # mentions of the prefix name in prose pass through too.
                if line.lstrip().startswith("#"):
                    continue
                violations.append((str(py_file), lineno, line.strip()))

    assert not violations, (
        "Task-prefix literal strings found outside "
        f"{EMBED_MODULE_RELATIVE}. The prefix scheme is contract; "
        "hand-rolling prefixes anywhere else means a future migration "
        "(e.g. nomic v1 -> v2 with different prefixes) has to chase strings.\n"
        "Resolve by calling embed_document() / embed_query() from "
        "agent_fleet.utils.embed.\n"
        + "\n".join(f"  {f}:{ln}  {snippet}" for f, ln, snippet in violations)
    )


def test_no_low_level_embed_symbols_outside_embed_module():
    """embed_text / embed_texts / _post_embedding only exist (and are only
    callable) inside agent_fleet/utils/embed.py. Their use elsewhere bypasses
    the task-prefix discipline."""
    violations: list[tuple[str, int, str]] = []
    embed_module_abs = AGENT_FLEET.parent / EMBED_MODULE_RELATIVE

    for py_file in AGENT_FLEET.rglob("*.py"):
        if py_file.resolve() == embed_module_abs.resolve():
            continue
        if any(part.startswith(".") for part in py_file.relative_to(AGENT_FLEET).parts):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        in_docstring = False
        docstring_delim = None
        for lineno, line in enumerate(text.splitlines(), start=1):
            if in_docstring:
                assert docstring_delim is not None
                if line.count(docstring_delim) % 2 == 1:
                    in_docstring = False
                    docstring_delim = None
                continue
            for delim in ('"""', "'''"):
                if line.count(delim) % 2 == 1:
                    in_docstring = True
                    docstring_delim = delim
                    break
            if in_docstring:
                continue
            if line.lstrip().startswith("#"):
                continue
            for sym in FORBIDDEN_LOW_LEVEL_SYMBOLS:
                # match as a word-boundary token so embed_text doesn't match
                # against embed_text_with_prefix or similar future helpers.
                import re as _re
                if _re.search(rf"\b{sym}\b", line):
                    violations.append((str(py_file), lineno, line.strip()))
                    break

    assert not violations, (
        "Low-level embed symbols (embed_text / embed_texts / _post_embedding) "
        f"used outside {EMBED_MODULE_RELATIVE}. These bypass the task-prefix "
        "discipline that pairs writers with readers.\n"
        "Resolve by calling embed_document() (write side) or embed_query() "
        "(read side) instead.\n"
        + "\n".join(f"  {f}:{ln}  {snippet}" for f, ln, snippet in violations)
    )
