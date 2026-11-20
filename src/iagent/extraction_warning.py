"""An extraction warning that reaches a person is a code and a bounded message.

Ruling (architect, 2026-11-19): "A reason that reaches a person is a code and a bounded
message." Raw prompts, raw model replies and raw exception text stay in telemetry and in the
artifact (`review.json`); they never reach a review card or a triage task.

A failed extraction pass appends a string such as ``"header extraction failed: <whole
exception text>"`` to the document's review reasons, and that text can carry the prompt and the
raw model reply. This module turns each warning into ``{"code", "message"[, "telemetry_ref"]}``
where the message is either fixed text, or a producer-authored line that already fits the
consumer's drawing rule. It never truncates: a truncated prompt is still a prompt.

The drawing rule is the consumer's (`boundedWarning.ts`): a message is drawn only if it is a
string, non-empty after trim, has no CR/LF, and is at most 160 characters.

Pure: no I/O and no fleet imports.
"""
from __future__ import annotations

import re

WARNING_MESSAGE_MAX = 160
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
FALLBACK_CODE = "extraction_warning"
WITHHELD = "An extraction warning was withheld; its detail is kept with the run."

_FAILED_RE = re.compile(r"^\s*(?P<stage>[A-Za-z][A-Za-z \-]{0,48}?) failed:", re.DOTALL)


def bounded_message(v) -> str | None:
    """`v` stripped, if the consumer would draw it; otherwise None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or "\n" in s or "\r" in s or len(s) > WARNING_MESSAGE_MAX:
        return None
    return s


def _slug(stage: str) -> str:
    return re.sub(r"[ \-]+", "_", stage.strip().lower())


def bound_warning(w) -> dict | None:
    if w is None:
        return None
    if isinstance(w, str):
        if not w.strip():
            return None
        m = _FAILED_RE.match(w)
        if m:
            stage = m.group("stage").strip()
            code = _slug(stage) + "_failed"
            if not CODE_RE.match(code):
                code = FALLBACK_CODE
            return {"code": code,
                    "message": f"{stage[:1].upper()}{stage[1:]} failed; the detail is withheld."}
        msg = bounded_message(w)
        return {"code": FALLBACK_CODE, "message": msg if msg else WITHHELD}
    if isinstance(w, dict):
        code = FALLBACK_CODE
        for k in ("code", "reason_code"):
            c = w.get(k)
            if isinstance(c, str) and CODE_RE.match(c):
                code = c
                break
        out = {"code": code,
               "message": bounded_message(w.get("message"))
               or bounded_message(w.get("reason")) or WITHHELD}
        ref = bounded_message(w.get("telemetry_ref"))
        if ref:
            out["telemetry_ref"] = ref
        return out
    return {"code": FALLBACK_CODE, "message": WITHHELD}


def bound_warnings(ws) -> list[dict]:
    if not isinstance(ws, list):
        return []
    return [b for b in (bound_warning(w) for w in ws) if b is not None]


def bounded_detail(text, *, code) -> str:
    """One bounded line for a person; the raw detail belongs in the run log."""
    msg = bounded_message(text)
    if msg:
        return msg
    return f"{code or 'refused'}: detail withheld; it is kept with the run."
