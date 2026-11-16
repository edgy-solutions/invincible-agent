"""Is every backend presentation row on every registered frontend menu, as SERVED?

WHY THIS EXISTS. At the 2026-11-16 rehearsal, where-used drew no card: cortex said "no render
registered for mesh#WhereUsedSet". The repo had a render test for it, and that test was green,
because it read only the backend half: `capabilities.PRESENTATION_CAPABILITIES`. A card needs both
halves. The selector picks from the caller frontend's REGISTERED menu: the `rendersAs` rows that
`graph_menu_source.fetch_registered_entries()` reads from the graph. The frontend had never
registered a WhereUsedSet row, so the selector found nothing, and cortex fell back to its own map.

This probe reads the served menus through the selector's own reader and its own IRI folding. For
each frontend's newest menu, it lists the backend rows that are not on it. It also checks a
CONTROL: a row the frontend is known to carry. If the control is absent, the read itself is
suspect. The control's default is mesh:NoticePartSet, which sits beside WhereUsedSet in both
tables.

RUN inside the presentation engine's pod (engine-f), where the graph credentials and the modules
are importable at top level:

    kubectl exec -i deploy/<presentation engine> -- python - [--control IRI] [--frontend ID] \
        < scripts/probes/served_render_menus.py

The probe prints one block per frontend and exits with:
  0  every backend row is on every menu checked;
  1  a gap: some backend row is missing from some menu;
  3  the graph could not be reached;
  4  the read is suspect: the control is absent, a menu is empty, or no menu was registered.
The decision is `menu_gaps()`. tests/test_served_render_menus_probe.py seals it offline.
"""
from __future__ import annotations

import sys
from typing import Callable, Dict, Iterable, List, Mapping

DEFAULT_CONTROL = "mesh:NoticePartSet"


def menu_gaps(entries: Mapping[str, Mapping], backend: Iterable[Mapping], canonical: Callable[[str], str],
              control: str = DEFAULT_CONTROL) -> Dict[str, Dict]:
    """For each frontend: its row count, whether the control is present, and the backend rows missing."""
    want = sorted({str(b.get("subject_uri") or "") for b in backend if b.get("subject_uri")})
    out: Dict[str, Dict] = {}
    for fid, ent in sorted(entries.items()):
        caps = list(ent.get("capabilities") or [])
        have = {canonical(str(c.get("subject_uri") or "")) for c in caps}
        out[fid] = {
            "version": ent.get("frontend_version"),
            "rows": len(caps),
            "control_present": canonical(control) in have,
            "missing": [w for w in want if canonical(w) not in have],
        }
    return out


def verdict(gaps: Mapping[str, Mapping]) -> int:
    if not gaps:
        return 4
    if any(g["rows"] == 0 or not g["control_present"] for g in gaps.values()):
        return 4
    return 1 if any(g["missing"] for g in gaps.values()) else 0


def _args(argv: List[str]) -> Dict[str, object]:
    got: Dict[str, object] = {"control": DEFAULT_CONTROL, "frontends": []}
    it = iter(argv)
    for a in it:
        if a == "--control":
            got["control"] = next(it)
        elif a == "--frontend":
            got["frontends"].append(next(it))  # type: ignore[union-attr]
        else:
            raise SystemExit(f"unknown argument {a!r}")
    return got


def main(argv: List[str]) -> int:
    import capability_registry as reg  # noqa: E402  (top-level inside the engine's image)
    import graph_menu_source as menus
    from capabilities import PRESENTATION_CAPABILITIES as BACKEND

    a = _args(argv)
    entries = menus.fetch_registered_entries()
    if entries is None:
        print("UNREACHABLE: the graph read returned None")
        return 3
    if a["frontends"]:
        entries = {k: v for k, v in entries.items() if k in a["frontends"]}
    gaps = menu_gaps(entries, BACKEND, reg._canonical, str(a["control"]))
    print(f"backend rows: {len(list(BACKEND))}; control: {a['control']}; frontends: {len(gaps)}")
    for fid, g in gaps.items():
        print(f"FRONTEND {fid} version={g['version']} rows={g['rows']} "
              f"control={'PRESENT' if g['control_present'] else 'ABSENT'}")
        print(f"  backend rows not on this menu: {len(g['missing'])}: {g['missing']}")
    rc = verdict(gaps)
    print({0: "OK: every backend row is on every menu", 1: "GAP: a backend row has no frontend row",
           4: "SUSPECT: the control is absent, a menu is empty, or none was registered"}[rc])
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
