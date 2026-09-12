"""Strip prose from a source file so a seal can assert on CODE rather than on documentation.

WHY THIS EXISTS AS ITS OWN MODULE. `test_a_second_graph_is_a_row_only.py` asserts that the
graph host names no specific graph — the property that makes the next graph a row rather than a
code change. Its first version matched the raw source, and it went RED on the host's own
documentation: an enforcement function whose docstring cites both graphs as EXAMPLES ("a
compliant `fail` module raises — see cost_lot_costing_review").

**The check matched a STRING when the defect is a BEHAVIOUR, so it flagged the prose explaining
the fix.** A host that EXPLAINS itself with an example is good documentation; a host that
BRANCHES on a graph_id is graph-specific. Only the second makes the next graph a code change.

CODE STRING LITERALS ARE DELIBERATELY KEPT. `if graph_id == "fin_program_brief"` is exactly the
defect and lives in a string literal, so stripping all strings would blind the seal to the thing
it exists to catch. Only comments and docstrings go.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path


def code_without_prose(path: Path) -> str:
    """Return `path`'s source with comments and docstrings removed, code intact."""
    src = path.read_text(encoding="utf-8")

    # Docstrings via AST, so a multi-line one is removed whole rather than line-guessed.
    tree = ast.parse(src)
    spans: list[tuple[int, int]] = []
    holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            spans.append((first.lineno, first.end_lineno or first.lineno))

    lines = src.splitlines()
    for start, end in spans:
        for i in range(start - 1, min(end, len(lines))):
            lines[i] = ""
    stripped = "\n".join(lines)

    # Comments via tokenize. Re-tokenising the docstring-stripped source is safe because
    # removing whole logical lines leaves it parseable.
    pieces: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(stripped).readline):
        if tok.type != tokenize.COMMENT:
            pieces.append(tok.string)
    return " ".join(pieces)
