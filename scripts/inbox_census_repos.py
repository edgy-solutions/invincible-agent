"""Inbox census across several repos.

    uv run python scripts/inbox_census_repos.py <repo-main-tree> [<repo-main-tree> ...]
        [--hours 48] [--now YYYY-MM-DD]

Reads only; writes nothing into any repo. The repo NAME is the basename of each path given.
Logic lives in src/iagent_pure/inbox_repos.py (see its docstring for the age rationale).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from iagent_pure import inbox_repos as ir  # noqa: E402


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def worktrees(repo: Path):
    rc, out = _git(repo, "worktree", "list", "--porcelain")
    paths = [Path(ln[len("worktree "):].strip()) for ln in out.splitlines() if ln.startswith("worktree ")]
    return paths if rc == 0 and paths else [repo]


def tracked_names(wt: Path) -> set:
    rc, out = _git(wt, "ls-files", "sessions")
    return {Path(ln).name for ln in out.splitlines()} if rc == 0 else set()


def has_branch(repo: Path, suffix: str) -> bool:
    for ref in (f"refs/heads/{suffix}", f"refs/remotes/origin/{suffix}"):
        if _git(repo, "rev-parse", "--verify", "--quiet", ref)[0] == 0:
            return True
    return False


def collect(repos):
    """-> (recs, per-repo summary lines, divergent {name: [paths]})."""
    seen: dict = {}      # filename -> [(repo, path, tracked, mtime, is_main)]
    summary = []
    for repo in repos:
        name = repo.name
        n_wt, missing, present, tracked_here = 0, [], set(), set()
        for wi, wt in enumerate(worktrees(repo)):
            if not wt.is_dir():
                missing.append(wt.as_posix())
                continue
            n_wt += 1
            sd = wt / "sessions"
            if not sd.is_dir():
                continue
            tr = tracked_names(wt)
            for f in sorted(sd.glob("*.md")):
                t = f.name in tr
                seen.setdefault(f.name, []).append((name, f, t, f.stat().st_mtime, wi == 0))
                present.add(f.name)
                if t:
                    tracked_here.add(f.name)
        if not present:
            summary.append(f"{name}: no sessions/ in any worktree")
        else:
            summary.append(f"REPOS: {name} {len(present)} packet(s) in {n_wt} worktree(s) "
                           f"[{len(tracked_here)} tracked, {len(present - tracked_here)} placed-not-committed]")
        for m in missing:
            summary.append(f"  MISSING worktree: {m}")
    recs, divergent = [], {}
    for fname in sorted(seen):
        locs = seen[fname]
        home = locs[0][0]
        copies = [(m, t, mt, ir.parse_rec(p, home), p.as_posix()) for r, p, t, mt, m in locs]
        rec = ir.merge_copies(copies)
        rec.locations = [(r, p.as_posix(), t) for r, p, t, _, _ in locs]
        if len({p.read_bytes() for _, p, _, _, _ in locs}) > 1:
            rec.divergent = True
            divergent[fname] = [p.as_posix() for _, p, _, _, _ in locs]
        recs.append(rec)
    return recs, summary, divergent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--now", default=None)
    a = ap.parse_args(argv)
    now = (datetime.strptime(a.now, "%Y-%m-%d").replace(tzinfo=timezone.utc) if a.now
           else datetime.now(timezone.utc))
    repos = [Path(r) for r in a.repos]
    by_name = {r.name: r for r in repos}
    recs, summary, divergent = collect(repos)
    res = ir.analyze(recs, now, a.hours)

    missing: set = set()
    addrs = {p.to_addr()[0] for p in recs} | {p.from_addr()[0] for p in recs}
    for ad in addrs:
        parts = (ad or "").split("/", 2)
        if len(parts) == 3 and parts[1] == "lane" and parts[0] in by_name:
            if not has_branch(by_name[parts[0]], f"lane/{parts[2]}"):
                missing.add(ad)

    out = list(summary)
    out.append(f"POPULATION: {len(recs)} distinct packets, {len(divergent)} divergent copies")
    out.extend(ir.render_result(res, now, a.hours, frozenset(missing)))
    unchecked = set()
    for ad in addrs:
        if not ad or ad in missing:
            continue
        if ad.startswith("seat/"):
            unchecked.add("seat")
        elif "/lane/" not in ad or ad.split("/", 1)[0] not in by_name:
            unchecked.add("outside party or repo not in args")
    out.append("UNCHECKED kinds (not errors): " + (", ".join(sorted(unchecked)) or "none"))
    out.append("DIVERGENT COPIES:" + ("" if divergent else " none"))
    for fn in sorted(divergent):
        out.append(f"  {fn} -> " + "; ".join(divergent[fn]))
    dis = [r for r in recs if r.divergent and ir.disagreeing(r)]
    out.append(f"DIVERGENT AND DISAGREEING: {len(dis)}")
    for r in dis:
        out.append(f"  {r.name}")
        groups: dict = {}
        for path, t, f in r.views:
            groups.setdefault((t, f), []).append(path)
        for (t, f), paths in groups.items():     # first group holds the canonical copy
            out.append(f"    to={t} from={f}: {len(paths)} copy(ies), e.g. {paths[0]}")
    text = "\n".join(out).encode("ascii", "replace").decode("ascii") + "\n"
    sys.stdout.buffer.write(text.encode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
