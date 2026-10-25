"""Measure the ADR-0061 socratic elicitation loop on the three synthetic fixtures. PROTOTYPE.

    uv run scripts/socratic_measure.py --arm oracle --out dist/socratic_oracle.json
    SOCRATIC_LLM_BASE_URL=... SOCRATIC_LLM_MODEL=... \\
        uv run scripts/socratic_measure.py --arm model --out dist/socratic_model.json

It measures; it does not gate. Exit 0 always (a missing environment for the model arm exits with a
message). The model arm never sees ``facts`` or ``expected/`` -- only each answer's ``says``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, deque
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_fleet.restate_analyst import socratic_elicitation as se  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "socratic"
NAMES = ("pcn_review", "maint_case_release", "training_course_approval")
_FOLDERS = ("triggers", "decisions", "workflows", "task_kinds")


def load_expected(fixture_dir: Path) -> dict:
    files = {}
    for folder in _FOLDERS:
        for p in sorted((fixture_dir / "expected" / folder).glob("*.yaml")):
            files[f"{folder}/{p.name}"] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return files


def _flatten(prefix: str, value, out: dict) -> None:
    if isinstance(value, dict) and value:
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out[prefix] = value


def leaf_diffs(final: dict, expected: dict) -> list:
    a: dict = {}
    b: dict = {}
    for f, d in final.items():
        _flatten(f, d, a)
    for f, d in expected.items():
        _flatten(f, d, b)
    return sorted(k for k in set(a) | set(b) if k not in a or k not in b or a[k] != b[k])


# ── canonical (semantic) form -- names and free text do not count ────────────────────────────

def _when_key(when: dict) -> tuple:
    return tuple(sorted((str(k), str(v)) for k, v in (when or {}).items()))


def canonical(files: dict) -> dict:
    triggers = [d for f, d in files.items() if f.startswith("triggers/")]
    decisions = {str(d.get("decision")): d for f, d in files.items() if f.startswith("decisions/")}
    wfs = {str(d.get("id")): d for f, d in files.items() if f.startswith("workflows/")}
    kinds = {str(d.get("kind")): d for f, d in files.items() if f.startswith("task_kinds/")}
    chain_of = {str(d["after"]): d for d in decisions.values() if d.get("after")}
    terminals = {t for d in decisions.values() for t in (d.get("terminals") or [])}
    trig = triggers[0] if triggers else {}
    sel = decisions.get(str(trig.get("selection")), {})
    names: dict = {}
    order: deque = deque()

    def target(then):
        if then is None:
            return None
        if then in terminals or then not in wfs:
            return "END"
        if then not in names:
            names[then] = f"wf{len(names)}"
            order.append(then)
        return names[then]

    sel_rows = sorted(sel.get("rows") or [], key=lambda r: _when_key(r.get("when")))
    canon_sel = {"matches": sorted(sel.get("matches") or []),
                 "rows": sorted((_when_key(r.get("when")), target(r.get("then"))) for r in sel_rows)}
    defs: dict = {}
    while order:
        wid = order.popleft()
        wf = wfs[wid]
        steps = []
        for s in wf.get("steps") or []:
            k = kinds.get(str(s.get("task_kind"))) if s.get("kind") == "human_await" else s
            k = k or {}
            steps.append((s.get("kind"), s.get("audience"),
                          tuple(sorted(k.get("accepts") or [])), tuple(sorted(k.get("reason_required") or [])),
                          s.get("deadline_seconds", "ABSENT"), bool(s.get("excludes")),
                          tuple(sorted(s.get("accepts") or [])) if s.get("kind") == "signal_await" else ()))
        ch = chain_of.get(wid)
        rows = []
        if ch:
            for r in sorted(ch.get("rows") or [], key=lambda r: _when_key(r.get("when"))):
                rows.append((_when_key(r.get("when")), target(r.get("then"))))
        defs[names[wid]] = {"steps": steps, "chain": sorted(rows, key=repr),
                            "matches": sorted((ch or {}).get("matches") or [])}
    return {"trigger": {"key": trig.get("key"), "episode": sorted(trig.get("episode") or []),
                        "requires": sorted(trig.get("requires") or [])},
            "selection": canon_sel, "defs": defs}


def _walk(prefix: str, a, b, out: list) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{prefix}.{k}")
            else:
                _walk(f"{prefix}.{k}", a[k], b[k], out)
    elif a != b:
        out.append(prefix)


def semantic_diffs(final: dict, expected: dict) -> list:
    out: list = []
    _walk("", canonical(final), canonical(expected), out)
    return out


# ── the measurement ─────────────────────────────────────────────────────────────────────────

def measure(name: str, extractor, errors_of=lambda e: 0) -> dict:
    d = FIXTURES / name
    transcript = yaml.safe_load((d / "transcript.yaml").read_text(encoding="utf-8"))
    expected = load_expected(d)
    t0 = time.time()
    r = se.run(transcript, extractor)
    secs = round(time.time() - t0, 2)
    keys = [q["key"] for q in r["questions"]]
    bank = list((transcript.get("answers") or {}).keys())
    planted = transcript.get("planted") or {}
    pc, pd = planted.get("contradictions") or [], planted.get("deferrals") or []
    ld, sd = leaf_diffs(r["files"], expected), semantic_diffs(r["files"], expected)
    return {
        "fixture": name,
        "questions": len(keys), "bank": len(bank),
        "redundant": sorted(k for k, n in Counter(keys).items() if n > 1),
        "unanswerable": r["unanswerable"], "unresolved": r["unresolved"],
        "unused_bank": sorted(set(bank) - set(keys)),
        "contradictions_planted": len(pc),
        "contradictions_detected": len(set(pc) & set(r["contradictions_asked"])),
        "deferrals_planted": len(pd),
        "deferrals_recorded": len(set(pd) & set(r["deferrals"])),
        "gaps_left": r["gaps_left"],
        "runnable_errors": {"count": len(r["runnable"]), "first": r["runnable"][:5]},
        "exact": r["files"] == expected,
        "leaf_diffs": {"count": len(ld), "first": ld[:20]},
        "semantic_diffs": {"count": len(sd), "first": sd[:20]},
        "model_errors": errors_of(extractor),
        "transport_errors": list(getattr(extractor, "transport_errors", [])),
        "asked": keys,
        "deferrals": r["deferrals"],
        "seconds": secs,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("oracle", "model"), required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.arm == "model":
        base, model = os.environ.get("SOCRATIC_LLM_BASE_URL"), os.environ.get("SOCRATIC_LLM_MODEL")
        if not base or not model:
            print("the model arm needs SOCRATIC_LLM_BASE_URL and SOCRATIC_LLM_MODEL in the environment; "
                  "there is no default.")
            return 0
    rows = []
    for name in NAMES:
        if args.arm == "oracle":
            rows.append(measure(name, se.OracleExtractor()))
        else:
            ex = se.ModelExtractor(base, model)
            rows.append(measure(name, ex, errors_of=lambda e: e.errors))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"arm": args.arm, "fixtures": rows}, indent=2, default=str), encoding="utf-8")
    hdr = f"{'fixture':26} {'q':>3} {'bank':>4} {'red':>3} {'unans':>5} {'unres':>5} {'contra':>6} {'defer':>5} " \
          f"{'left':>4} {'rn_err':>6} {'exact':>5} {'leaf':>4} {'sem':>4} {'mdl_err':>7} {'sec':>6}"
    print(hdr)
    for r in rows:
        print(f"{r['fixture']:26} {r['questions']:>3} {r['bank']:>4} {len(r['redundant']):>3} "
              f"{r['unanswerable']:>5} {r['unresolved']:>5} "
              f"{r['contradictions_detected']}/{r['contradictions_planted']:>4} "
              f"{r['deferrals_recorded']}/{r['deferrals_planted']:>3} {len(r['gaps_left']):>4} "
              f"{r['runnable_errors']['count']:>6} {str(r['exact']):>5} {r['leaf_diffs']['count']:>4} "
              f"{r['semantic_diffs']['count']:>4} {r['model_errors']:>7} {r['seconds']:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
