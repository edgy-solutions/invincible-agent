"""The ratified EAC method rows, composed from `policy/measures/`. ADR-0053 §2.

A method is a ROW: name, module reference, version, and the clause its formula is transcribed
from. **A module on disk with no row is invisible** — inherited verbatim from
`policy/graphs/fin_program_brief.yaml`, and it is what makes §3's refusals structural rather
than disciplinary.

── WHAT THIS IS WIRED TO TODAY, STATED SO IT IS NOT MISREAD ─────────────────────────────────
The rows are **enforced at seal time** — `tests/finance/test_the_method_registry_rows.py` runs
each row's transcription against the module and asserts the row set, the `EACMethod` vocabulary
and the module's own tables all agree.

**The engine does not yet BOOT off these rows**, and that is deliberate sequencing rather than
an unfinished edit. `policy/measures/` reaches a container through a per-file `COPY` in the
`Dockerfile.agent` heredoc inside `.github/workflows/build-containers.yml` — the line this
commit adds — and that file's own comment says the per-file COPY *"is itself the fragile part:
the next shared-policy file will need"* it. Making `measures.py` import this module at import
time, before that COPY has ridden into a built image, gives a finance engine that passes every
test here and **fails only in the deployment** — the one failure class this lane has already
paid for twice.

> **The data and its COPY ship in one release; the runtime starts depending on them in the
> next.** Reversing that order is how a green suite ships an unstartable pod.

The switch is one edit — `EAC_FORMULA` and `EAC_METHODS` derived here instead of from the
`Literal` — and it is filed as
`docs/plans/the-method-rows-are-not-yet-the-runtime-source.md`.

── THE COMPOSER IS THE SDK'S, NOT A FOURTH ONE ──────────────────────────────────────────────
`iagent_mesh.declarations.compose_rows` — ADR-0039's amendment refuses a fourth composer BY
NAME, and this family gets the duplicate-key error, the tombstone rule and the overlay algebra
by passing a key field and a builder rather than by copying forty lines.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from iagent_mesh.declarations import DeclarationError, compose_rows

#: WHERE THE COMPOSED ROWS ARE READ FROM, spelled exactly like `GRAPH_POLICY_DIR`. The seed
#: ships in this repo; a work-side overlay adds, replaces or deletes (ADR-0036); composition
#: happens at the repo and the composed directory is what this reads.
MEASURE_POLICY_DIR = Path(os.getenv(
    "MEASURE_POLICY_DIR",
    str(Path(__file__).resolve().parents[2] / "policy" / "measures"),
))
MEASURE_OVERLAY_DIRS = [
    Path(p) for p in os.getenv("MEASURE_OVERLAY_DIRS", "").split(os.pathsep) if p
]

#: The fields a row must carry. Absent one, the row is REFUSED rather than defaulted: a method
#: row missing its version is a figure that travels under §5 with its provenance slot filled in
#: by whatever the loader guessed.
_REQUIRED = ("method_id", "name", "module", "function", "version", "requires_index")


class MethodRowError(DeclarationError):
    """A ratified method row is invalid. Names the FILE, which is what makes it fixable at
    merge time without a bisect."""


@dataclass(frozen=True)
class MethodRow:
    method_id: str
    name: str
    description: str
    module: str
    function: str
    version: str
    requires_index: bool
    slot: Optional[str]
    slot_of: Optional[str]
    authority: str
    clause: str
    citation: str
    transcription: str

    def resolve(self) -> Any:
        """The callable this row points at.

        §3 REFUSES *"a method row pointing at anything without a manifest"* — a row that
        resolves to an unmanifested target is worse than an absent row, because it reads as
        governed. So the module must declare `VERSION`, and the row's version must match it.
        """
        try:
            mod = importlib.import_module(self.module)
        except ImportError as exc:
            raise MethodRowError(
                f"{self.method_id}: cannot import {self.module!r}: {exc}"
            ) from exc
        declared = getattr(mod, "VERSION", None)
        if declared is None:
            raise MethodRowError(
                f"{self.method_id}: {self.module} declares no VERSION, so it has no manifest. "
                f"A row pointing at an unmanifested module reads as governed and is not."
            )
        if declared != self.version:
            raise MethodRowError(
                f"{self.method_id}: row says version {self.version!r}, module declares "
                f"{declared!r}. §5 puts this string on every artifact beside the figure, so a "
                f"row and a module disagreeing means a recipient cannot reproduce the number."
            )
        fn = getattr(mod, self.function, None)
        if fn is None:
            raise MethodRowError(f"{self.method_id}: {self.module} has no {self.function!r}")
        return fn


def _build(raw: dict) -> MethodRow:
    missing = [k for k in _REQUIRED if raw.get(k) is None]
    if missing:
        raise MethodRowError(f"method row is missing {missing}")
    derived = raw.get("derived_from") or {}
    for k in ("authority", "clause", "transcription"):
        if not derived.get(k):
            raise MethodRowError(
                f"{raw['method_id']}: derived_from.{k} is required — §2a seals a row by "
                f"RUNNING the transcription its provenance cites, and a row without one is a "
                f"row whose formula cannot be checked against a stated standard."
            )
    return MethodRow(
        method_id=raw["method_id"],
        name=raw["name"],
        description=(raw.get("description") or "").strip(),
        module=raw["module"],
        function=raw["function"],
        version=str(raw["version"]),
        requires_index=bool(raw["requires_index"]),
        slot=raw.get("slot"),
        slot_of=raw.get("slot_of"),
        authority=derived["authority"],
        clause=derived["clause"],
        citation=derived.get("citation", "unstated"),
        transcription=derived["transcription"],
    )


def load_method_rows(
    policy_dir: Path | str | None = None,
    overlay_dirs: list[Path] | None = None,
) -> list[MethodRow]:
    """Every ratified method row, composed and validated, sorted by `method_id`.

    FAIL LOUD ON NONE, for the reason `load_graphs` states: a loader returning an empty list
    leaves its caller with zero methods and a green light — the failure mode with no symptom.
    **An empty `policy/measures/` is a missing COPY, not a registry with nothing in it.**
    """
    d = Path(policy_dir) if policy_dir is not None else MEASURE_POLICY_DIR
    ov = overlay_dirs if overlay_dirs is not None else MEASURE_OVERLAY_DIRS
    rows = compose_rows(
        d, ov, key_field="method_id", builder=_build, label="method row", error=MethodRowError,
    )
    if not rows:
        raise MethodRowError(
            f"no ratified method rows under {d} (overlays: "
            f"{[str(p) for p in ov] or 'none'}). If the directory is missing from the image, "
            f"that is the defect — the COPY that ships it lives in the Dockerfile.agent "
            f"HEREDOC inside .github/workflows/build-containers.yml, and NOT in any Dockerfile "
            f"in this repo."
        )
    return rows


def by_id(rows: list[MethodRow] | None = None) -> dict[str, MethodRow]:
    """Rows keyed by `method_id`, for a caller that needs one method rather than the set."""
    return {r.method_id: r for r in (rows if rows is not None else load_method_rows())}
