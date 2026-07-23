"""Guard: no typing-generic subscript in a Pydantic model field is used WITHOUT being imported, in
modules that use `from __future__ import annotations`.

Under future-annotations every annotation is a STRING forward-ref, and Pydantic v2 resolves it via the
module globals. A bare `Optional[...]` / `List[...]` whose name is NOT imported into the module is
unresolvable -> the model is "not fully defined" and 500s at request time (the exact engine-o bug; its
§657 note forbids typing imports there, so the fix is builtins / `str | None`). An IMPORTED generic
(`from typing import List`, as datahub_wrapper does) resolves fine and is NOT flagged. Static AST check
— no imports of the target modules, runs in milliseconds. Skips vendored/venv trees.
"""
from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN = {"Optional", "List", "Dict", "Union", "Tuple", "Set", "FrozenSet"}
_ROOTS = ("agent_fleet", "src")
_SKIP = (".venv", "site-packages", "node_modules", "/build/", "\\build\\")


def _is_basemodel_base(b: ast.expr) -> bool:
    return (isinstance(b, ast.Name) and b.id == "BaseModel") or (isinstance(b, ast.Attribute) and b.attr == "BaseModel")


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def _unimported_forbidden(annotation: ast.expr, imported: set[str]) -> list[str]:
    """Forbidden generics used as a BARE Name subscript (`Optional[...]`) that is NOT imported.
    Qualified `typing.Optional[...]` (an Attribute) resolves via `import typing` and is not flagged."""
    found: list[str] = []
    for node in ast.walk(annotation):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            n = node.value.id
            if n in _FORBIDDEN and n not in imported:
                found.append(n)
    return found


def test_no_unimported_typing_generics_in_future_annotations_models():
    repo = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for root in _ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            sp = str(f)
            if any(s in sp for s in _SKIP):
                continue
            try:
                txt = f.read_text(encoding="utf-8")
            except Exception:
                continue
            if "from __future__ import annotations" not in txt or "BaseModel" not in txt:
                continue
            try:
                tree = ast.parse(txt)
            except SyntaxError:
                continue
            imported = _imported_names(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(_is_basemodel_base(b) for b in node.bases):
                    for stmt in node.body:
                        if isinstance(stmt, ast.AnnAssign) and stmt.annotation is not None:
                            for name in _unimported_forbidden(stmt.annotation, imported):
                                offenders.append(
                                    f"{f.relative_to(repo)}:{stmt.lineno}  {node.name}."
                                    f"{getattr(stmt.target, 'id', '?')}: {name}[...] (not imported)"
                                )
    assert not offenders, (
        "typing-generic subscript used-but-not-imported in a Pydantic field under "
        "`from __future__ import annotations` (Pydantic v2 can't resolve it -> 500; import it, or use "
        "builtins / `X | None`):\n  " + "\n  ".join(offenders)
    )
