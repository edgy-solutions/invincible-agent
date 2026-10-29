"""engine-r core (ADR-0062 section 2): an in-process repository-of-record library.

Bare repositories, libgit2 through pygit2. NO shell-out -- no ``subprocess``, no ``git`` binary
(a test reads this package's source with ``ast`` and refuses one). No Restate, no HTTP: this is
the storage, verbs, identity, signing, pre-receive checks and audit; the wrapper that serialises
calls per repository, and who-may-approve (ADR section 5), are other changes.

The invariants, in the order a merge enforces them:

  * a REFUSAL moves no ref and writes no note (every check runs before anything is written; the
    CAS refusal, which fires after the note, withdraws it by restoring ``refs/notes/audit``);
  * the audit note is written BEFORE the ref moves, on the merge commit;
  * the ref update re-reads the tip and refuses ``target_moved`` if it changed since the merge
    commit was built. pygit2 exposes no compare-and-swap on a reference, so this is a
    check-then-set, and it is only as atomic as the one-writer-per-repository key the ADR puts
    in front of this library;
  * a merge is never a squash and never a fast-forward.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pygit2

try:  # flat in the image (/app)
    import sshsig
except ImportError:  # packaged in the repo
    from agent_fleet.repository_agent import sshsig

AUDIT_REF = "refs/notes/audit"
PROPOSAL_PREFIX = "refs/proposals/"
META_PREFIX = "refs/proposal-meta/"

# ADR-0062 section 1's governed roots. The rail can narrow check 6; it cannot widen it.
GOVERNED_ROOTS = ("policy/", "docs/adr/", "tests/fixtures/", "sessions/")

TRAILER_KEYS = ("On-Behalf-Of", "Auth-Via", "Proposal")


# --------------------------------------------------------------------------- values


class RepoRefusal(Exception):
    """The standard refusal envelope. A refusal has moved nothing."""

    def __init__(
        self,
        status: int,
        error: str,
        *,
        policy_id: str = "code",
        missing_binding: str = "",
        message: str = "",
        check: str | None = None,
    ) -> None:
        super().__init__(message or error)
        self.status = status
        self.error = error
        self.policy_id = policy_id
        self.missing_binding = missing_binding
        self.message = message or error
        self.check = check


_BAD_ID = re.compile(r"[\x00-\x1f<>\x7f]")


@dataclass(frozen=True)
class Caller:
    authz_id: str
    auth_via: str  # "local" | "brokered:<idp>" | "service"

    def __post_init__(self) -> None:
        if not self.authz_id or _BAD_ID.search(self.authz_id) or self.authz_id != self.authz_id.strip():
            raise ValueError("authz_id must be a non-empty single line without <, > or control characters")
        v = self.auth_via
        ok = v in ("local", "service") or (
            v.startswith("brokered:") and len(v) > len("brokered:") and not _BAD_ID.search(v) and v == v.strip()
        )
        if not ok:
            raise ValueError(f"auth_via must be local | brokered:<idp> | service, got {v!r}")


@dataclass(frozen=True)
class Approval:
    authz_id: str
    sha: str  # the head sha that was approved
    task_id: str
    at: str  # ISO-8601 UTC


def parse_repository_paths(text: str, repo_id: str) -> dict[str, dict]:
    """The ``paths`` mapping of one repository out of ``policy/repository_paths.yaml`` (ADR section 5)."""
    import yaml

    doc = yaml.safe_load(text) or {}
    rows = ((doc.get("repository_paths") or {}).get(repo_id) or {}).get("paths") or {}
    return dict(rows)


@dataclass
class Policy:
    governed: dict[str, dict]
    customer_terms: list[str] | None
    signer: "sshsig.Signer"
    committer_name: str
    committer_email: str
    extra_checks: list[Callable[["Repo", dict], None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        for prefix in self.governed:
            if (
                not isinstance(prefix, str)
                or ".." in prefix.split("/")
                or not prefix.startswith(GOVERNED_ROOTS)
            ):
                raise ValueError(
                    f"governed prefix {prefix!r} is outside {GOVERNED_ROOTS}: the rail cannot widen check 6"
                )


# --------------------------------------------------------------------------- helpers


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _email_for(authz_id: str) -> str:
    return authz_id if "@" in authz_id else f"{authz_id}@users.engine-r.invalid"


def _sig(name: str, email: str) -> pygit2.Signature:
    return pygit2.Signature(name, email, int(datetime.now(timezone.utc).timestamp()), 0)


def _trailers(caller: Caller, proposal: str) -> str:
    return f"On-Behalf-Of: {caller.authz_id}\nAuth-Via: {caller.auth_via}\nProposal: {proposal}\n"


def _with_trailers(message: str, caller: Caller, proposal: str) -> str:
    return message.rstrip() + "\n\n" + _trailers(caller, proposal)


def parse_trailers(message: str) -> dict[str, str] | None:
    """Trailers from the LAST paragraph only; None if that paragraph is not all ``Key: value``."""
    paras = re.split(r"\n\s*\n", message.strip())
    if len(paras) < 2:
        return None
    out: dict[str, str] = {}
    for ln in paras[-1].splitlines():
        m = re.match(r"^([A-Za-z][A-Za-z0-9-]*):\s+(\S.*)$", ln)
        if not m:
            return None
        out[m.group(1)] = m.group(2).strip()
    return out


_PEM = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_AKIA = re.compile(r"AKIA[0-9A-Z]{16}")
_ASSIGN = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*(\S{8,})")


def _line_has_secret(line: str) -> bool:
    if _PEM.search(line) or _JWT.search(line) or _AKIA.search(line):
        return True
    for m in _ASSIGN.finditer(line):
        v = m.group(2)
        if re.fullmatch(r"<.*>", v) or re.fullmatch(r"\$\{.*\}", v) or v.lower() == "changeme":
            continue
        return True
    return False


# --------------------------------------------------------------------------- the repository


class Repo:
    def __init__(self, repo: pygit2.Repository, repo_id: str, policy: Policy | None) -> None:
        self._r = repo
        self.repo_id = repo_id
        self.policy = policy

    @classmethod
    def init_bare(cls, path, repo_id, policy: Policy | None = None) -> "Repo":
        r = pygit2.init_repository(str(path), bare=True, initial_head="master")
        return cls(r, repo_id, policy)

    @classmethod
    def open(cls, path, repo_id, policy: Policy | None = None) -> "Repo":
        return cls(pygit2.Repository(str(path)), repo_id, policy)

    # ---- plumbing

    def _policy(self) -> Policy:
        if self.policy is None:
            raise ValueError("this Repo was opened without a Policy")
        return self.policy

    def _read_tip(self, ref: str) -> str | None:
        try:
            return str(self._r.references[ref].resolve().target)
        except KeyError:
            return None

    def _commit_text_signed(
        self, author: pygit2.Signature, tree: pygit2.Oid, parents: list, message: str
    ) -> pygit2.Oid:
        p = self._policy()
        committer = _sig(p.committer_name, p.committer_email)
        text = self._r.create_commit_string(
            author, committer, message, tree, [pygit2.Oid(hex=str(x)) for x in parents]
        )
        sig = p.signer.sign(text.encode("utf-8"))
        return self._r.create_commit_with_signature(text, sig, "gpgsig")

    def _caller_sig(self, caller: Caller) -> pygit2.Signature:
        return _sig(caller.authz_id, _email_for(caller.authz_id))

    def _committer_sig(self) -> pygit2.Signature:
        p = self._policy()
        return _sig(p.committer_name, p.committer_email)

    def _set_ref(self, ref: str, sha: str, msg: str) -> None:
        self._r.create_reference(ref, pygit2.Oid(hex=sha), force=True, message=msg)

    # ---- proposal metadata: a commit chain, one meta.json per state

    def _write_meta(self, meta: dict) -> str:
        ref = META_PREFIX + meta["id"]
        blob = self._r.create_blob(json.dumps(meta, sort_keys=True, indent=2).encode("utf-8"))
        tb = self._r.TreeBuilder()
        tb.insert("meta.json", blob, pygit2.GIT_FILEMODE_BLOB)
        tree = tb.write()
        prev = self._read_tip(ref)
        c = self._commit_text_signed(
            self._committer_sig(), tree, [prev] if prev else [], f"proposal {meta['id']}: {meta['state']}\n"
        )
        self._set_ref(ref, str(c), "proposal-meta")
        return str(c)

    def proposal(self, proposal_id: str) -> dict:
        tip = self._read_tip(META_PREFIX + proposal_id)
        if tip is None:
            raise RepoRefusal(
                409, "unknown_proposal", missing_binding="a proposal with this id",
                message="unknown proposal", check="check1",
            )
        blob = self._r[self._r[tip].tree["meta.json"].id]
        return json.loads(blob.data.decode("utf-8"))

    # ---- import

    def import_from(self, source: str) -> dict:
        remote = self._r.remotes.create_anonymous(str(source))
        remote.fetch(["+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"])
        refs: dict[str, str] = {}
        for name in self._r.references:
            if name.startswith(("refs/heads/", "refs/tags/")):
                refs[name] = str(self._r.references[name].resolve().target)
        head = refs.get("refs/heads/master")
        count = 0
        if head:
            w = self._r.walk(pygit2.Oid(hex=head), pygit2.GIT_SORT_TOPOLOGICAL)
            count = sum(1 for _ in w)
        return {"refs": refs, "head": head, "commit_count": count}

    # ---- propose

    def propose(self, *, caller: Caller, target_ref: str, changes: dict, intent: str, message: str) -> dict:
        tip = self._read_tip(target_ref)
        if tip is None:
            raise ValueError(f"target_ref {target_ref} does not exist")
        base = self._r[tip]
        index = pygit2.Index()
        index.read_tree(base.tree)
        for path, data in changes.items():
            if data is None:
                index.remove(path)
            else:
                index.add(pygit2.IndexEntry(path, self._r.create_blob(data), pygit2.GIT_FILEMODE_BLOB))
        tree = index.write_tree(self._r)
        pid = uuid.uuid4().hex[:12]
        head = self._commit_text_signed(
            self._caller_sig(caller), tree, [tip], _with_trailers(message, caller, pid)
        )
        self._set_ref(PROPOSAL_PREFIX + pid, str(head), "propose")
        meta = {
            "id": pid,
            "repo": self.repo_id,
            "target_ref": target_ref,
            "base_sha": tip,
            "head_sha": str(head),
            "intent": intent,
            "proposer": caller.authz_id,
            "auth_via": caller.auth_via,
            "state": "open",
            "created_at": _now(),
        }
        self._write_meta(meta)
        return meta

    # ---- the diff of a proposal

    def _proposal_diff(self, meta: dict) -> pygit2.Diff:
        base = self._r[meta["base_sha"]].tree
        head = self._r[meta["head_sha"]].tree
        return base.diff_to_tree(head, context_lines=0)

    @staticmethod
    def _paths_of(diff: pygit2.Diff) -> list[str]:
        out: list[str] = []
        for d in diff.deltas:
            for p in (d.old_file.path, d.new_file.path):
                if p not in out:
                    out.append(p)
        return out

    @staticmethod
    def _added_lines(diff: pygit2.Diff):
        for patch in diff:
            if patch.delta.is_binary:
                continue
            for hunk in patch.hunks:
                for ln in hunk.lines:
                    if ln.origin == "+":
                        yield patch.delta.new_file.path, ln.new_lineno, ln.content

    # ---- approvals (the part of section 5 that is not who-may-approve)

    @staticmethod
    def _check_approvals(approvals: list[Approval], sha: str, proposer: str | None) -> None:
        for a in approvals:
            if a.sha != sha:
                raise RepoRefusal(
                    409, "approval_of_another_sha", missing_binding="an approval of the reviewed sha",
                    message="an approval names a different sha than the one reviewed", check="approvals",
                )
        if proposer is not None:
            for a in approvals:
                if a.authz_id == proposer:
                    raise RepoRefusal(
                        403, "proposer_cannot_approve", missing_binding="the dropper rule",
                        message="a proposer may not approve their own proposal", check="approvals",
                    )
        if not approvals:
            raise RepoRefusal(
                409, "no_approval", missing_binding="at least one approval",
                message="no approval was supplied", check="approvals",
            )

    # ---- merge

    def merge(self, *, proposal_id: str, reviewed_sha: str, approvals: list[Approval], completes: Caller) -> dict:
        p = self._policy()
        checks: dict[str, str] = {}

        # check1: a merge by sha closes its proposal
        meta = self.proposal(proposal_id)
        if meta["state"] != "open":
            raise RepoRefusal(
                409, "proposal_closed", missing_binding="an open proposal",
                message="the proposal is already closed", check="check1",
            )
        ref_now = self._read_tip(PROPOSAL_PREFIX + proposal_id)
        if reviewed_sha != meta["head_sha"] or ref_now != meta["head_sha"]:
            raise RepoRefusal(
                409, "reviewed_sha_is_not_head", missing_binding="a review of the current head",
                message="the reviewed sha is not the proposal head", check="check1",
            )
        checks["check1"] = "pass"

        self._check_approvals(approvals, reviewed_sha, meta["proposer"])
        checks["approvals"] = "pass"

        diff = self._proposal_diff(meta)
        paths = self._paths_of(diff)

        # check6: only governed paths merge
        for path in paths:
            if not any(path.startswith(prefix) for prefix in p.governed):
                raise RepoRefusal(
                    403, "path_not_governed", policy_id="repository_paths",
                    missing_binding=f"a row covering {path}",
                    message="path not governed by engine-r", check="check6",
                )
        checks["check6"] = "pass"

        # check5: every commit in base..head carries the three trailers (last paragraph only)
        w = self._r.walk(pygit2.Oid(hex=meta["head_sha"]), pygit2.GIT_SORT_TOPOLOGICAL)
        w.hide(pygit2.Oid(hex=meta["base_sha"]))
        for c in w:
            t = parse_trailers(c.message)
            if t is None or any(not t.get(k) for k in TRAILER_KEYS):
                raise RepoRefusal(
                    409, "missing_trailers", missing_binding="On-Behalf-Of, Auth-Via and Proposal trailers",
                    message=f"commit {str(c.id)[:12]} lacks the three trailers", check="check5",
                )
        checks["check5"] = "pass"

        # check3: no secrets in the added lines
        for path, lineno, content in self._added_lines(diff):
            if _line_has_secret(content):
                raise RepoRefusal(
                    403, "secret_in_diff", missing_binding="a diff free of secrets",
                    message=f"secret-shaped content in {path} at line {lineno}", check="check3",
                )
        checks["check3"] = "pass"

        # check4: no customer-identifying context; fail closed when the terms are absent
        if p.customer_terms is None:
            raise RepoRefusal(
                403, "customer_terms_absent", missing_binding="the customer-terms list",
                message="the customer-terms list is not configured", check="check4",
            )
        terms = [t.lower() for t in p.customer_terms if t]
        if terms:
            for path, lineno, content in self._added_lines(diff):
                low = content.lower()
                if any(t in low for t in terms):
                    raise RepoRefusal(
                        403, "customer_context_in_diff", missing_binding="a diff free of customer context",
                        message=f"customer-identifying context in {path} at line {lineno}", check="check4",
                    )
        checks["check4"] = "pass"

        # pluggable extra checks
        ctx = {"proposal": meta, "paths": paths}
        for fn in p.extra_checks:
            fn(self, ctx)
            checks[getattr(fn, "__name__", "extra_check")] = "pass"

        # the merge commit: parents = [tip, reviewed]; never a squash, never a fast-forward
        target_ref = meta["target_ref"]
        tip = self._read_tip(target_ref)
        if tip is None:
            raise RepoRefusal(409, "target_moved", missing_binding="the target ref", message="the target ref is gone")
        head_commit = self._r[reviewed_sha]
        if tip == meta["base_sha"]:
            tree = head_commit.tree.id
        else:
            ancestor = self._r[meta["base_sha"]].tree
            merged = self._r.merge_trees(ancestor, self._r[tip].tree, head_commit.tree)
            if merged.conflicts is not None:
                raise RepoRefusal(
                    409, "merge_conflict", missing_binding="a proposal that applies to the current tip",
                    message="the proposal conflicts with the current target", check="merge",
                )
            tree = merged.write_tree(self._r)
        msg = _with_trailers(f"Merge proposal {proposal_id}\n\n{meta['intent']}", completes, proposal_id)
        merge_oid = self._commit_text_signed(self._caller_sig(completes), tree, [tip, reviewed_sha], msg)
        merge_sha = str(merge_oid)

        # the audit note, BEFORE the ref moves
        note = {
            "repo": self.repo_id,
            "ref": target_ref,
            "old": tip,
            "new": merge_sha,
            "verb": "merge",
            "on_behalf_of": completes.authz_id,
            "auth_via": completes.auth_via,
            "proposal": proposal_id,
            "review_task_ids": [a.task_id for a in approvals],
            "approvers": [a.authz_id for a in approvals],
            "checks": checks,
            "at": _now(),
        }
        notes_before = self._read_tip(AUDIT_REF)
        self._write_note(merge_sha, note)

        # compare-and-swap on the tip (see the module docstring for how atomic this is)
        if self._read_tip(target_ref) != tip:
            self._unwrite_note(notes_before)
            raise RepoRefusal(
                409, "target_moved", missing_binding="a target unchanged since the merge was built",
                message="the target ref moved while the merge was being built", check="cas",
            )
        self._set_ref(target_ref, merge_sha, f"merge {proposal_id}")

        closed = dict(meta, state="merged", merge_sha=merge_sha, closed_at=_now())
        self._write_meta(closed)
        return {"merge_sha": merge_sha, "target_ref": target_ref, "old": tip, "new": merge_sha, "note": note}

    # ---- notes

    def _write_note(self, annotated: str, body: dict) -> None:
        self._r.create_note(
            json.dumps(body, sort_keys=True, indent=2),
            self._committer_sig(), self._committer_sig(), annotated, AUDIT_REF,
        )

    def _unwrite_note(self, notes_before: str | None) -> None:
        """Put ``refs/notes/audit`` back where it was: a refusal writes no note (ADR-0062 section 2).

        The CAS refusal is the one refusal that fires after the note is written, and an orphan's
        note left on the notes ref would be mirrored as the audit of a merge that never landed.
        """
        if notes_before is None:
            with contextlib.suppress(KeyError):
                self._r.references.delete(AUDIT_REF)
        else:
            self._set_ref(AUDIT_REF, notes_before, "refused: the note is withdrawn")

    def _read_note(self, sha: str) -> dict | None:
        try:
            return json.loads(self._r.lookup_note(sha, AUDIT_REF).message)
        except (KeyError, pygit2.GitError):
            return None

    # ---- tags

    def _tag_common(
        self, *, name: str, sha: str, caller: Caller, approvals: list[Approval], verb: str, extra: dict,
        reason: str | None = None,
    ) -> dict:
        ref = f"refs/tags/{name}"
        if not name or not pygit2.reference_is_valid_name(ref):
            raise ValueError(f"invalid tag name {name!r}")
        try:
            target = self._r.get(pygit2.Oid(hex=sha))
        except (ValueError, KeyError):
            target = None
        if target is None:
            raise RepoRefusal(409, "unknown_sha", missing_binding="an object at this sha", message="unknown sha")
        self._check_approvals(approvals, sha, None)
        old = self._read_tip(ref)
        text = (
            f"object {sha}\ntype {target.type_str}\ntag {name}\n"
            f"tagger {caller.authz_id} <{_email_for(caller.authz_id)}> "
            f"{int(datetime.now(timezone.utc).timestamp())} +0000\n\n"
            + _with_trailers(f"{verb} {name}", caller, "none")
        )
        armored = self._policy().signer.sign(text.encode("utf-8"))
        tag_oid = self._r.write(pygit2.GIT_OBJECT_TAG, (text + armored).encode("utf-8"))
        note = {
            "repo": self.repo_id,
            "ref": ref,
            "old": old,
            "new": str(tag_oid),
            "target": sha,
            "verb": verb,
            "on_behalf_of": caller.authz_id,
            "auth_via": caller.auth_via,
            "proposal": None,
            "review_task_ids": [a.task_id for a in approvals],
            "approvers": [a.authz_id for a in approvals],
            "checks": {"approvals": "pass", **extra},
            "at": _now(),
        }
        if reason is not None:
            note["reason"] = reason
        notes_before = self._read_tip(AUDIT_REF)
        self._write_note(str(tag_oid), note)
        if self._read_tip(ref) != old:
            self._unwrite_note(notes_before)
            raise RepoRefusal(409, "target_moved", message="the tag moved while it was being written", check="cas")
        self._set_ref(ref, str(tag_oid), verb)
        return {"tag": name, "sha": sha, "tag_object": str(tag_oid), "note": note}

    def tag(self, *, name: str, sha: str, caller: Caller, approvals: list[Approval], release: bool) -> dict:
        exists = self._read_tip(f"refs/tags/{name}") is not None
        if exists and release:
            raise RepoRefusal(
                409, "release_tag_immutable", missing_binding="a logged repair_tag call",
                message="a release tag never moves", check="check2",
            )
        if exists:
            raise RepoRefusal(409, "tag_exists", missing_binding="repair_tag", message="the tag already exists")
        return self._tag_common(
            name=name, sha=sha, caller=caller, approvals=approvals, verb="tag", extra={"check2": "pass"}
        )

    def repair_tag(self, *, name: str, sha: str, caller: Caller, approvals: list[Approval], reason: str) -> dict:
        if not reason or not reason.strip():
            raise ValueError("repair_tag requires a reason")
        if self._read_tip(f"refs/tags/{name}") is None:
            raise RepoRefusal(409, "unknown_tag", missing_binding="an existing tag", message="no such tag")
        return self._tag_common(
            name=name, sha=sha, caller=caller, approvals=approvals, verb="repair_tag",
            extra={}, reason=reason.strip(),
        )

    # ---- audit

    def _first_parent_merges(self, ref: str):
        sha = self._read_tip(ref)
        while sha:
            c = self._r[sha]
            if len(c.parents) >= 2:
                yield c
            sha = str(c.parents[0].id) if c.parents else None

    def audit(self, *, ref: str | None = None, path: str | None = None, proposal_id: str | None = None) -> list[dict]:
        if proposal_id is not None:
            out = []
            with contextlib.suppress(KeyError, pygit2.GitError):
                for n in self._r.notes(AUDIT_REF):
                    body = json.loads(n.message)
                    if body.get("proposal") == proposal_id:
                        out.append(body)
            return out
        refs = [ref] if ref else [r for r in self._r.references if r.startswith("refs/heads/")]
        out, seen = [], set()
        for rf in refs:
            for c in self._first_parent_merges(rf):
                sha = str(c.id)
                if sha in seen:
                    continue
                if path is not None:
                    d = c.parents[0].tree.diff_to_tree(c.tree)
                    if not any(
                        p == path or (path.endswith("/") and p.startswith(path)) for p in self._paths_of(d)
                    ):
                        continue
                note = self._read_note(sha)
                if note is not None:
                    seen.add(sha)
                    out.append(note)
        return out

    def unaudited_merges(self, ref: str) -> list[str]:
        """Merge commits on the first-parent chain with no audit note. Reports; never refuses."""
        return [str(c.id) for c in self._first_parent_merges(ref) if self._read_note(str(c.id)) is None]


# --------------------------------------------------------------------------- extra checks


def _load_validate_policy(path: Path):
    """``policy/sync/validate_policy.validate``, imported by file path. Leaves sys.path/sys.modules as found."""
    saved_path = list(sys.path)
    saved_mods = set(sys.modules)
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("_engine_r_validate_policy", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod.validate
    finally:
        sys.path[:] = saved_path
        for k in set(sys.modules) - saved_mods:
            del sys.modules[k]


def _materialize(repo: pygit2.Repository, tree: pygit2.Tree, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for e in tree:
        obj = repo[e.id]
        if obj.type == pygit2.GIT_OBJECT_TREE:
            _materialize(repo, obj, dest / e.name)
        else:
            (dest / e.name).write_bytes(obj.data)


def validate_policy_check(enums_dir: Path, validate_path: Path | None = None) -> Callable[["Repo", dict], None]:
    """An extra check: when the diff touches ``policy/``, run the fleet's own policy validator on the head tree."""
    vp = validate_path or Path(__file__).resolve().parents[2] / "policy" / "sync" / "validate_policy.py"

    def validate_policy_check(repo: "Repo", ctx: dict) -> None:
        if not any(p.startswith("policy/") for p in ctx["paths"]):
            return
        head = repo._r[ctx["proposal"]["head_sha"]].tree
        try:
            sub = repo._r[head["policy"].id]
        except KeyError:
            sub = None
        with tempfile.TemporaryDirectory() as td:
            pdir = Path(td) / "policy"
            pdir.mkdir()
            if sub is not None:
                _materialize(repo._r, sub, pdir)
            errors = _load_validate_policy(vp)(pdir, Path(enums_dir))
        if errors:
            raise RepoRefusal(
                409, "policy_invalid", missing_binding="a policy/ tree that validates",
                message="; ".join(str(e) for e in errors[:3]), check="validate_policy",
            )

    return validate_policy_check
