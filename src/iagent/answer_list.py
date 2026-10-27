"""GET /answers: the caller's own answers as SUMMARIES, never bodies (rev 187).

Cortex measured one Electric shape of `answer_artifact_projection` at 6.82 MB for ~816 rows
(`routing` 47% of the bytes, `rendered_output` 31%); a list row needs ~200 B. So this module
selects a fixed, narrow column list and nothing else. The body is fetched by id from
`GET /answers/{id}/body`.

The statement is built here, as text, so a seal can read the SQL actually sent.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import human_tasks

# The ONE definition of the search expression. It must equal, whitespace aside, the expression
# in `idx_aap_search_tsv` (sql/create_answer_artifact_projection.sql) or the planner cannot use
# the index. A seal reads the SQL file and compares.
SEARCH_EXPR = (
    "to_tsvector('simple', coalesce(question_text,'') || ' ' || coalesce(summary,''))"
)

TITLE_MAX = 140
MAX_TOKENS = 8
_TOKEN_RE = re.compile(r"\w+")

# Only the sub-paths of `routing` the S·P composer reads (`_compose_answer_summary`,
# gateway.py): about.uri, about.instance_label, about.label. Never the whole column.
_SELECT = """SELECT id,
       created_at,
       question_text,
       summary,
       kind,
       status,
       archived_at,
       routing->'about'->>'uri' AS subject_uri,
       routing->'about'->>'instance_label' AS subject_instance_label,
       routing->'about'->>'label' AS subject_label,
       count(*) OVER () AS total
  FROM answer_artifact_projection"""


def build_tsquery(q: Optional[str]) -> Optional[str]:
    """`a | b & !c :* )` -> `a:* & b:* & c:*`. Tokens are word characters only, so no tsquery operator can
    come from user input; the result still goes in as a PARAMETER."""
    tokens = _TOKEN_RE.findall(q or "")[:MAX_TOKENS]
    if not tokens:
        return None
    return " & ".join(f"{t}:*" for t in tokens)


def build_list_query(
    *, caller: str, page: int, size: int, sort: str, q: Optional[str] = None,
    type_: Optional[str] = None, status: Optional[str] = None,
    include_archived: bool = False,
) -> tuple[str, dict[str, Any]]:
    where = ["produced_for_user_id = %(caller)s"]
    params: dict[str, Any] = {"caller": caller}
    if not include_archived:
        where.append("archived_at IS NULL")
    if type_:
        where.append("kind = %(kind)s")
        params["kind"] = type_
    if status:
        where.append("status = %(status)s")
        params["status"] = status
    tsq = build_tsquery(q)
    if tsq:
        where.append(f"{SEARCH_EXPR} @@ to_tsquery('simple', %(tsq)s)")
        params["tsq"] = tsq
    direction = "ASC" if sort == "oldest" else "DESC"
    params["limit"] = size
    params["offset"] = (page - 1) * size
    sql = (
        f"{_SELECT}\n WHERE " + "\n   AND ".join(where)
        + f"\n ORDER BY created_at {direction}, id {direction}"
        + "\n LIMIT %(limit)s OFFSET %(offset)s"
    )
    return sql, params


def _title(text: Optional[str]) -> str:
    t = (text or "").strip()
    if len(t) <= TITLE_MAX:
        return t
    cut = t[: TITLE_MAX - 1]
    space = cut.rfind(" ")
    if space >= TITLE_MAX // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def _pg_connect():
    return human_tasks._pg_connect()


def _item(row: dict) -> dict:
    uri = row.get("subject_uri")
    label = (row.get("subject_instance_label") or "").strip() or (row.get("subject_label") or "").strip()
    subject = {"uri": uri, "label": label} if (uri or label) else None
    return {
        "id": row["id"],
        "ts": int(row["created_at"]),
        "title": _title(row.get("question_text")),
        "summary": row.get("summary"),
        "type": row.get("kind"),
        "status": row.get("status"),
        "subject": subject,
        "archived": row.get("archived_at") is not None,
    }


def list_answers(**kw: Any) -> dict:
    """Sync (psycopg2): the route calls it through run_in_threadpool."""
    import psycopg2.extras

    sql, params = build_list_query(**kw)
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
    total = int(rows[0]["total"]) if rows else 0
    if not rows and kw["page"] > 1:
        # Past the last page: count(*) OVER () has no row to ride on.
        total = _count(kw)
    return {"items": [_item(r) for r in rows], "page": kw["page"], "size": kw["size"], "total": total}


def _count(kw: dict) -> int:
    sql, params = build_list_query(**{**kw, "page": 1, "size": 1})
    sql = "SELECT count(*) AS n FROM (" + sql.split("\n LIMIT")[0].replace(
        "count(*) OVER () AS total", "1 AS total") + ") t"
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return int(cur.fetchone()[0])
