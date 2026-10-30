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
import re
import sys
import time
from collections import Counter, deque
from pathlib import Path
from typing import Optional, Tuple

import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_fleet.restate_analyst import socratic_elicitation as se  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "socratic"
NAMES = tuple(sorted(p.name for p in FIXTURES.iterdir() if (p / "transcript.yaml").is_file()))
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


# ── the scripted user who understands a question whatever its id ────────────────────────────

def _index(files: dict) -> dict:
    triggers = [d for f, d in files.items() if f.startswith("triggers/") and isinstance(d, dict)]
    decisions = {str(d.get("decision") or Path(f).stem): d for f, d in files.items()
                 if f.startswith("decisions/") and isinstance(d, dict)}
    wfs = {str(d.get("id") or Path(f).stem): d for f, d in files.items()
           if f.startswith("workflows/") and isinstance(d, dict)}
    kinds = {str(d.get("kind") or Path(f).stem): d for f, d in files.items()
             if f.startswith("task_kinds/") and isinstance(d, dict)}
    chain = {str(d["after"]): (n, d) for n, d in decisions.items() if d.get("after")}
    terminals = {t for d in decisions.values() for t in (d.get("terminals") or [])}
    trig = triggers[0] if triggers else {}
    sel_name = str(trig.get("selection")) if trig.get("selection") else None
    return {"trigger": trig, "sel": decisions.get(sel_name), "sel_name": sel_name,
            "decisions": decisions, "wfs": wfs, "kinds": kinds, "chain": chain, "terminals": terminals}


def _steps_of(wf: dict) -> list:
    return [s for s in (wf.get("steps") or []) if isinstance(s, dict)]


def _fact_target(key: str) -> Optional[Tuple[str, str]]:
    """(file, path) a TRANSLATED question key asks about, or None for a key with no such path."""
    s = key.split(".")
    if len(s) == 4 and s[0] == "actors" and s[3] == "excludes":
        return f"workflows/{s[1]}.yaml", f"steps[id={s[2]}].excludes"
    if len(s) == 4 and s[0] == "approvals" and s[3] == "deadline":
        return f"workflows/{s[1]}.yaml", f"steps[id={s[2]}].deadline_seconds"
    if len(s) == 3 and s[0] == "approvals" and s[2] == "reason_required":
        return f"task_kinds/{s[1]}.yaml", "reason_required"
    return None


def _sets_path(entry: dict, file: str, path: str) -> bool:
    """True iff one `set` fact of ``entry`` on ``file`` puts ``path`` in a scratch bundle, applied
    by the elicitation module's own setter. Present-with-null counts."""
    for fact in ((entry.get("facts") or {}).get("set") or []):
        if not isinstance(fact, dict) or fact.get("file") != file:
            continue
        scratch = {file: {}}
        se.apply_patch(se.Draft(files=scratch), {"set": [fact]}, 0)
        if se._get(scratch, file, path)[0]:
            return True
    return False


class AligningUser:
    """The scripted user for a model run. A person answers a question about "the impact review"
    whatever the model called it; this looks the question up by the EXPECTED bundle's names.

    ALIGNMENT IS STRUCTURAL ONLY, never by similarity: the draft and the expected bundle are walked
    in lock step from their selection tables, pairing rows by their `when` (verbs and input values
    are literal), so a definition is paired by the path a case reaches it by (the canonical BFS
    position). Steps pair k-th of a kind with k-th of the same kind; task kinds are the ones aligned
    human_await steps name; a chaining table follows its aligned `after`. A name no path reaches is
    NOT aligned -- the question is unanswerable, never answered as some other stage."""

    def __init__(self, transcript: dict, expected_files: dict):
        self.bank = transcript.get("answers") or {}
        self.expected = expected_files
        self.aligned_answers: list = []
        self.unaligned: list = []
        self.unbanked: list = []
        self.answered_by_path: list = []
        self.opening = transcript.get("opening")

    def entry_for_path(self, file: str, path: str) -> Optional[Tuple[str, dict]]:
        """The (source key, entry) whose facts set ``path`` of ``file``; the opening first, then the
        bank in order. The person repeats what they said FIRST; a later revision of the same fact
        arrives only through the contradiction path, which stays reachable (PCN's planted excludes
        contradiction is the opening's `[]` against the later "barred from both reviews"); a
        `contradiction:` entry is never an answer to a plain question."""
        cands = []
        if self.opening:
            cands.append(("opening", self.opening))
        cands += [(k, v) for k, v in self.bank.items() if not k.startswith("contradiction:")]
        for k, v in cands:
            if isinstance(v, dict) and _sets_path(v, file, path):
                return k, v
        return None

    def _pair_definitions(self, d: dict, e: dict) -> dict:
        """draft stage name -> expected stage name, by lock-step walk from the selection tables."""
        m: dict = {}
        bad: set = set()
        if not d["sel"] or not e["sel"]:
            return m
        queue = deque([(d["sel"].get("rows") or [], e["sel"].get("rows") or [])])
        while queue:
            drows, erows = queue.popleft()
            by_when = {_when_key(r.get("when")): r for r in erows if isinstance(r, dict)}
            for r in sorted((r for r in drows if isinstance(r, dict)), key=lambda r: _when_key(r.get("when"))):
                other = by_when.get(_when_key(r.get("when")))
                if other is None:
                    continue
                dt, et = r.get("then"), other.get("then")
                if not dt or not et or dt in d["terminals"] or et in e["terminals"]:
                    continue
                if (dt in m and m[dt] != et) or (dt not in m and et in m.values()):
                    bad.add(dt)
                    continue
                if dt not in m:
                    m[dt] = et
                    dc, ec = d["chain"].get(dt), e["chain"].get(et)
                    if dc and ec:
                        queue.append((dc[1].get("rows") or [], ec[1].get("rows") or []))
        return {k: v for k, v in m.items() if k not in bad}

    def _maps(self, draft_files: dict) -> dict:
        d, e = _index(draft_files), _index(self.expected)
        defs = self._pair_definitions(d, e)
        steps: dict = {}
        kinds: dict = {}
        tables: dict = {}
        if d["sel_name"] and e["sel_name"]:
            tables[d["sel_name"]] = e["sel_name"]
        for dw, ew in defs.items():
            if dw in d["chain"] and ew in e["chain"]:
                tables[d["chain"][dw][0]] = e["chain"][ew][0]
            if dw not in d["wfs"] or ew not in e["wfs"]:
                continue
            for kind in {s.get("kind") for s in _steps_of(d["wfs"][dw])}:
                ds = [s for s in _steps_of(d["wfs"][dw]) if s.get("kind") == kind]
                es = [s for s in _steps_of(e["wfs"][ew]) if s.get("kind") == kind]
                for a, b in zip(ds, es):
                    steps[(dw, str(a.get("id")))] = str(b.get("id"))
                    if kind == "human_await" and a.get("task_kind") and b.get("task_kind"):
                        kinds[str(a["task_kind"])] = str(b["task_kind"])
        trig = {}
        if d["trigger"] and e["trigger"]:
            trig = {str(d["trigger"].get("trigger")): str(e["trigger"].get("trigger"))}
        return {"defs": defs, "steps": steps, "kinds": kinds, "tables": tables, "trigger": trig, "d": d}

    def translate(self, key: str, draft_files: dict) -> Optional[str]:
        """The expected bundle's spelling of ``key``; None when any id segment cannot be aligned."""
        m = self._maps(draft_files)
        d = m["d"]
        if key.startswith("contradiction:") and "#" in key:
            file, path = key[len("contradiction:"):].split("#", 1)
            folder, _, fname = file.partition("/")
            stem, suffix = Path(fname).stem, Path(fname).suffix
            lookup = {"workflows": m["defs"], "decisions": m["tables"], "task_kinds": m["kinds"],
                      "triggers": m["trigger"]}.get(folder)
            tgt = lookup.get(stem) if lookup is not None else None
            if tgt is None:
                return None
            if folder == "workflows":
                out, pos = "", 0
                for mo in re.finditer(r"\[id=([^\]]*)\]", path):
                    s2 = m["steps"].get((stem, mo.group(1)))
                    if s2 is None:
                        return None
                    out += path[pos:mo.start()] + f"[id={s2}]"
                    pos = mo.end()
                path = out + path[pos:]
            return f"contradiction:{folder}/{tgt}{suffix}#{path}"
        if key.startswith("contradiction:"):
            kind, _, tail = key[len("contradiction:"):].partition(".")
            parts = tail.split(".")
            if kind == "trigger":
                return key
            target = {"routing": m["tables"], "chaining": m["tables"], "workflow": m["defs"],
                      "task_kind": m["kinds"]}.get(kind)
            t = target.get(parts[0]) if target is not None else None
            return None if t is None else ".".join([f"contradiction:{kind}", t] + parts[1:])
        segs = key.split(".")
        head = segs[0]
        if head == "trigger" or key in ("outputs.record", "outputs.end"):
            return key
        if head == "steps" and len(segs) == 2:
            w = m["defs"].get(segs[1])
            return None if w is None else f"steps.{w}"
        if head in ("steps", "actors", "approvals", "outputs") and len(segs) >= 3:
            a = segs[1]
            if a in m["defs"] or a in d["wfs"]:
                w = m["defs"].get(a)
                if w is None:
                    return None
                step_ids = {str(s.get("id")) for s in _steps_of(d["wfs"].get(a) or {})}
                if segs[2] in step_ids:
                    s2 = m["steps"].get((a, segs[2]))
                    return None if s2 is None else ".".join([head, w, s2] + segs[3:])
                return ".".join([head, w] + segs[2:])
            if a in m["kinds"] or a in d["kinds"]:
                k = m["kinds"].get(a)
                return None if k is None else ".".join([head, k] + segs[2:])
        return None

    def __call__(self, gap, draft) -> Optional[dict]:
        t = self.translate(gap.key, draft.files)
        if t is None:
            self.unaligned.append(gap.key)
            return None
        entry = self.bank.get(t)
        if entry is None:
            tgt = _fact_target(t)
            hit = self.entry_for_path(*tgt) if tgt else None
            if hit is not None:
                self.answered_by_path.append((gap.key, hit[0]))
                return hit[1]
            self.unbanked.append(gap.key)
            return None
        if t != gap.key:
            self.aligned_answers.append(gap.key)
        return entry


# ── the measurement ─────────────────────────────────────────────────────────────────────────

def measure(name: str, extractor, errors_of=lambda e: 0, aligned: bool = False) -> dict:
    d = FIXTURES / name
    transcript = yaml.safe_load((d / "transcript.yaml").read_text(encoding="utf-8"))
    expected = load_expected(d)
    t0 = time.time()
    user = AligningUser(transcript, expected) if aligned else None
    r = se.run(transcript, extractor, answer=user)
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
        "status": r["status"],
        "missing": {"count": len(r["missing"]), "first": r["missing"][:10]},
        "open": r["open"],
        "runnable_errors": {"count": len(r["runnable"]), "first": r["runnable"][:5]},
        "exact": r["files"] == expected,
        "leaf_diffs": {"count": len(ld), "first": ld[:20]},
        "semantic_diffs": {"count": len(sd), "first": sd[:20]},
        "aligned_answers": list(user.aligned_answers) if user else [],
        "unaligned": list(user.unaligned) if user else [],
        "answered_by_path": [list(p) for p in user.answered_by_path] if user else [],
        "unbanked": list(user.unbanked) if user else sorted(k for k in keys if k not in set(bank)),
        "deferred_refusals": [k for k in r["deferred_refusals"] if k in r["deferrals"]],
        "model_errors": errors_of(extractor) + len(r["model_errors"]),
        "refused_patches": r["model_errors"],
        "transport_errors": list(getattr(extractor, "transport_errors", [])),
        "asked": keys,
        "deferrals": r["deferrals"],
        "files": r["files"],
        "seconds": secs,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("oracle", "model"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--aligned", action="store_true", help="oracle arm: use the aligning user (identity)")
    ap.add_argument("--fixture", choices=NAMES, action="append")
    args = ap.parse_args()
    names = [n for n in NAMES if n in args.fixture] if args.fixture else list(NAMES)
    if args.arm == "model":
        base, model = os.environ.get("SOCRATIC_LLM_BASE_URL"), os.environ.get("SOCRATIC_LLM_MODEL")
        if not base or not model:
            print("the model arm needs SOCRATIC_LLM_BASE_URL and SOCRATIC_LLM_MODEL in the environment; "
                  "there is no default.")
            return 0
    rows = []
    for name in names:
        if args.arm == "oracle":
            rows.append(measure(name, se.OracleExtractor(), aligned=args.aligned))
        else:
            ex = se.ModelExtractor(base, model)
            rows.append(measure(name, ex, errors_of=lambda e: e.errors, aligned=True))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"arm": args.arm, "fixtures": rows}, indent=2, default=str), encoding="utf-8")
    hdr = f"{'fixture':26} {'q':>3} {'bank':>4} {'red':>3} {'unans':>5} {'unres':>5} {'contra':>6} {'defer':>5} " \
          f"{'left':>4} {'rn_err':>6} {'exact':>5} {'leaf':>4} {'sem':>4} {'mdl_err':>7} {'alg':>3} {'unal':>4} {'unbk':>4} {'path':>4} {'dref':>4} {'status':>10} {'sec':>6}"
    print(hdr)
    for r in rows:
        print(f"{r['fixture']:26} {r['questions']:>3} {r['bank']:>4} {len(r['redundant']):>3} "
              f"{r['unanswerable']:>5} {r['unresolved']:>5} "
              f"{r['contradictions_detected']}/{r['contradictions_planted']:>4} "
              f"{r['deferrals_recorded']}/{r['deferrals_planted']:>3} {len(r['gaps_left']):>4} "
              f"{r['runnable_errors']['count']:>6} {str(r['exact']):>5} {r['leaf_diffs']['count']:>4} "
              f"{r['semantic_diffs']['count']:>4} {r['model_errors']:>7} {len(r['aligned_answers']):>3} {len(r['unaligned']):>4} "
              f"{len(r['unbanked']):>4} {len(r['answered_by_path']):>4} {len(r['deferred_refusals']):>4} {r['status']:>10} {r['seconds']:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
