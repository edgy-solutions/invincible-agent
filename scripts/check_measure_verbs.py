"""Name every measure verb row a release would refuse at boot, before the roll.

A deployment runs this against its policy repo's `measure_verbs/` before rolling a release; a row
the release would refuse at boot is named here instead.

    python scripts/check_measure_verbs.py DIR [DIR ...]

Run it from a checkout of the release the deployment will roll to (the same tree a roll uses).
The DIRs are overlay dirs, as `MEASURE_VERB_OVERLAY_DIRS` would list them; the platform's own
`policy/measure_verbs` seed is composed in, as at boot.

Every file is built alone with the engine's OWN `measure_verbs._build` (so its `_check_*`
functions, the module-version check included), with the same `builtins` the engine passes, and
EVERY refusal is printed as `REFUSED <path>: <message>`, not only the first. When every file builds
alone, `load_measure_verbs(overlay_dirs=...)` runs once so the refusals only a composition shows (a
duplicate id, a tombstone for a key the seed does not ship) are reported too. No rule is restated
here.

Exit 0: nothing refused (`OK: <n> measure verb rows load from <k> dirs`, n counting the rows the
dirs declare, tombstones not counted). Exit 1: something refused. Exit 2: usage error (stderr).

Needs no cluster, no network and no secret. Env vars honoured, as at boot: `DATASET_CONTRACT_DIR`
(the dataset contracts a row names; default the release's `contracts/`), `FIN_CALENDAR_OVERLAY_DIRS`
(the fiscal calendars a contract names), `MEASURE_VERB_POLICY_DIR` (the seed; default the release's).
`MEASURE_VERB_OVERLAY_DIRS` is NOT read: the dirs are the arguments.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv: list[str]) -> int:
    dirs = [Path(a) for a in argv]
    if not dirs:
        print("usage: check_measure_verbs.py DIR [DIR ...]", file=sys.stderr)
        return 2
    missing = [d for d in dirs if not d.is_dir()]
    if missing:
        for d in missing:
            print(f"usage: {d} is not a directory", file=sys.stderr)
        return 2

    import yaml

    from agent_fleet.finance_agent import measure_verbs as mv

    builtins = (mv._measures.OUTPUT_URI, [v["verb"].split(":", 1)[-1] for v in mv._engine_main().VERBS])
    refused, rows = 0, 0
    for d in dirs:
        for f in sorted(d.glob("*.yaml")):
            try:
                raw = yaml.safe_load(f.read_text(encoding="utf-8"))
                if raw is None:
                    raise ValueError("an empty ratified row is not a row")
                if not raw.get("measure_id"):
                    raise ValueError("no measure_id")
                if raw.get("deleted"):
                    continue  # a tombstone is checked against the seed by the composition below
                mv._build(raw, builtins)
                rows += 1
            except Exception as exc:  # noqa: BLE001 -- every refusal is reported, not only the first
                refused += 1
                print(f"REFUSED {f}: {exc}")
    if not refused:
        try:
            mv.load_measure_verbs(overlay_dirs=dirs, builtins=builtins)
            mv.load_measure_sources(overlay_dirs=dirs, builtins=builtins)
        except mv.MeasureVerbError as exc:
            refused += 1
            print(f"REFUSED (composition): {exc}")
    if refused:
        return 1
    print(f"OK: {rows} measure verb rows load from {len(dirs)} dirs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
