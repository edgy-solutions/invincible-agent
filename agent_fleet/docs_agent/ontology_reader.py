"""The reader binding — one named operation over one HTTP call. NOT a driver.

**THIS IS WHAT KEEPS engine-docs THE FIRST ENGINE BORN WITHOUT A DRIVER.** It holds an `httpx`
call to a named operation on engine-o, which is the substrate's one legitimate reader. There is no
query in it, no query language, and no connection to a store — the subject goes out, rows come
back, and what runs against Jena runs inside the service that owns that read.

**THE OPERATION IS ENGINE-O'S; THE PROTOCOL IS THIS ENGINE'S.** `reads.DocPageReader` was written
as the first consumer's contract before any implementation existed, and this class is the thin
thing that satisfies it. If the two ever disagree, the seam is here — one file, one method — which
is the whole reason the Protocol was written down separately.

── WHAT ARRIVES AND WHAT THIS CONVERTS ────────────────────────────────────────────────────────
The wire carries `explains` as a JSON array; `PageRow.explains` is a tuple, because a row that a
caller can mutate is a row two callers can disagree about. That conversion is this file's only
transformation, and it is a shape change rather than a content one — nothing here reinterprets a
value, which is the same discipline `body_store` follows for bytes.

── EMPTY IS AN ANSWER, AND THAT IS LOAD-BEARING ───────────────────────────────────────────────
`count: 0` with `200` is the corpus saying nothing explains this subject yet. It returns `[]`, the
verb abstains naming the subject, and nothing raises. An engine that treated it as an error would
turn the honest and common state of a young corpus into a failure.
"""
from __future__ import annotations

import os
from typing import Any, Optional

try:  # flat in the image (/app), packaged in the repo — runbook §5, FLAT FIRST.
    from reads import PageRow
except ImportError:  # pragma: no cover — exercised by the flat-layout check
    from agent_fleet.docs_agent.reads import PageRow


class ReaderUnavailable(Exception):
    """The operation could not be reached, or answered in a shape this engine cannot read.

    DISTINCT FROM AN EMPTY ANSWER, which is not an error at all. Collapsing the two would make
    "nothing explains this" and "the corpus could not be consulted" render identically — and the
    second is the one where a reader should be told to come back, not told there is no page.
    """


class OntologyDocPageReader:
    """`reads.DocPageReader` over `POST /page_for_subject`."""

    def __init__(self, *, base_url: Optional[str] = None, client: Any = None,
                 timeout_s: float = 10.0):
        self.base_url = (base_url or os.environ.get("ONTOLOGY_SERVICE_URL", "")).rstrip("/")
        self._client = client
        self.timeout_s = timeout_s

    def _post(self, path: str, body: dict) -> dict:
        if self._client is not None:
            return self._client.post(path, body)
        if not self.base_url:
            raise ReaderUnavailable(
                "ONTOLOGY_SERVICE_URL is unset, so there is no operation to call. The engine will "
                "refuse rather than answer from nothing.")
        import httpx

        try:
            r = httpx.post(f"{self.base_url}{path}", json=body, timeout=self.timeout_s)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 — httpx raises a family; the cause is the point
            raise ReaderUnavailable(
                f"POST {self.base_url}{path} failed: {exc}. The corpus could not be consulted, "
                f"which is a different answer from 'nothing explains this'.") from exc

    def page_for_subject(self, subject_iri: str) -> list[PageRow]:
        """Pages whose `mesh:explains` includes the subject, in the order the operation returned.

        **THE ORDER IS NOT RE-SORTED HERE, ON PURPOSE.** Ordering is the operation's job and its
        precedence is ruled; a client that re-sorted would silently override a rule it cannot see
        the inputs to. Today the operation reports every page tied, which is exactly why the
        engine renders them all.

        **`audience` IS SENT AS `null` AND THAT IS NOT A PLACEHOLDER.** No persona reaches this
        engine on the direct-dispatch route, so there is nothing honest to put there; sending a
        guess would make the operation order by an audience nobody asserted. The field is in the
        body because the operation accepts it and because the day a persona arrives, the change is
        this one line rather than a new call shape.
        """
        payload = self._post("/page_for_subject", {"subject": subject_iri, "audience": None})
        if not isinstance(payload, dict) or "pages" not in payload:
            raise ReaderUnavailable(
                f"the operation answered without a `pages` key: {str(payload)[:200]}. That is an "
                f"instrument failure and must not be read as an empty corpus.")

        rows: list[PageRow] = []
        for p in payload["pages"]:
            missing = [f for f in ("iri", "title", "doc_kind", "audience_hint", "source",
                                   "body_sha") if f not in p]
            if missing:
                raise ReaderUnavailable(
                    f"a page row is missing {missing}. The engine asserts a sha before it renders, "
                    f"so a row without one cannot be served and must not be silently dropped.")
            rows.append(PageRow(
                iri=p["iri"], title=p["title"], doc_kind=p["doc_kind"],
                audience_hint=p["audience_hint"], source=p["source"], body_sha=p["body_sha"],
                explains=tuple(p.get("explains") or ()),
            ))
        return rows
