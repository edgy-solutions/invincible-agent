"""Print the direct-store-client census; `--write` regenerates the ratchet baseline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from iagent_pure.store_client_census import census, findings  # noqa: E402

BASELINE = ROOT / "tests" / "sdk_adoption" / "direct_store_baseline.json"
RULE = "direct store-client count per engine and surface may only fall; lower it with --write"


def main() -> int:
    counts = census(ROOT)
    if "--write" in sys.argv:
        sha = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        doc = {"rule": RULE, "generated_from": sha, "counts": counts}
        BASELINE.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {BASELINE}")
    for e, s in counts.items():
        for surf, c in s.items():
            print(f"{e:24} {surf:7} {c['imports']}/{c['constructions']}")
    if "--files" in sys.argv:
        for f in findings(ROOT):
            print(*f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
