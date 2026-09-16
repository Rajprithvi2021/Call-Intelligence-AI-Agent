"""PostgreSQL store (pure-Python pg8000 driver), with pgvector when available.

pg8000 is used instead of psycopg because the development machine's
application-control policy blocks psycopg's compiled DLLs. Vectors are passed
as text literals and cast with CAST(... AS vector).

If the database has no pgvector extension (e.g. Railway's default Postgres),
the store still works and search is keyword-only.
"""
import json
import logging
import ssl
from contextlib import contextmanager
from urllib.parse import parse_qs, unquote, urlparse

import pg8000.exceptions
import pg8000.native

from app.config import ROOT, settings
from app.store import rrf_merge

INIT_SQL = ROOT / "db" / "init.sql"
VECTOR_SQL = ROOT / "db" / "vector.sql"
log = logging.getLogger(__name__)


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class PostgresStore:
    kind = "postgres"

    def __init__(self, url: str):
        u = urlparse(url)
        # SSL only when the URL asks for it: Railway's private network is plain TCP,
        # while hosted URLs (Neon, Supabase, Railway's public proxy) carry ?sslmode=require.
        sslmode = parse_qs(u.query).get("sslmode", ["disable"])[0]
        self.params = dict(
            user=unquote(u.username or "postgres"), password=unquote(u.password or ""),
            host=u.hostname or "localhost", port=u.port or 5432, database=(u.path or "/postgres").lstrip("/"),
            ssl_context=ssl.create_default_context() if sslmode in ("require", "verify-ca", "verify-full") else None,
        )
        self.has_vector = False
        self.init_db()

    @contextmanager
    def conn(self):
        con = pg8000.native.Connection(**self.params)
        try:
            yield con
        finally:
            con.close()

    @staticmethod
    def rows(con, sql: str, **params) -> list[dict]:
        result = con.run(sql, **params)
        cols = [c["name"] for c in (con.columns or [])]
        return [dict(zip(cols, r)) for r in (result or [])]

    @staticmethod
    def _statements(path) -> list[str]:
        sql = path.read_text(encoding="utf-8").replace("{EMBED_DIM}", str(settings.embed_dim))
        body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
        return [s.strip() for s in body.split(";") if s.strip()]

    def init_db(self) -> None:
        with self.conn() as con:
            for stmt in self._statements(INIT_SQL):
                con.run(stmt)
            try:
                con.run("CREATE EXTENSION IF NOT EXISTS vector")
            except pg8000.exceptions.DatabaseError as exc:
                log.warning("pgvector not available (%s); search will be keyword-only", exc)
                return
            for stmt in self._statements(VECTOR_SQL):
                con.run(stmt)
            self.has_vector = True

    # ------------------------------------------------------------------ calls

    def create_call(self, title, domain, meeting_date, source, participants, input_ref):
        with self.conn() as con:
            r = con.run(
                "INSERT INTO calls (title, domain, meeting_date, source, participants, input_ref) "
                "VALUES (:t, :d, :m, :s, :p, :i) RETURNING id",
                t=title, d=domain, m=meeting_date, s=source, p=participants, i=input_ref,
            )
        return str(r[0][0])

    def get_input(self, call_id):
        if not str(call_id).isdigit():
            return None
        with self.conn() as con:
            rows = self.rows(con, "SELECT id::text AS id, domain, meeting_date, participants, source, status, "
                                  "input_ref AS input FROM calls WHERE id = :id", id=int(call_id))
        return rows[0] if rows else None

    def set_status(self, call_id, status, error=None):
        with self.conn() as con:
            con.run("UPDATE calls SET status = :s, error = :e WHERE id = :id", s=status, e=error, id=int(call_id))

    def save_result(self, call_id, result, embeddings):
        cid = int(call_id)
        notes = result.notes.model_dump(mode="json")
        with self.conn() as con:
            con.run("START TRANSACTION")
            try:
                con.run("UPDATE calls SET domain = :d WHERE id = :id", d=notes["domain"], id=cid)
                con.run(
                    "INSERT INTO call_notes (call_id, tag, sentiment, notes) VALUES (:id, :t, :s, CAST(:n AS jsonb)) "
                    "ON CONFLICT (call_id) DO UPDATE SET tag = EXCLUDED.tag, sentiment = EXCLUDED.sentiment, notes = EXCLUDED.notes",
                    id=cid, t=notes["tag"], s=notes["sentiment"]["overall"], n=json.dumps(notes),
                )
                con.run("DELETE FROM transcript_lines WHERE call_id = :id", id=cid)
                for i, l in enumerate(result.transcript):
                    row = dict(id=cid, n=l.n, sp=l.speaker, r=l.role, st=l.start, en=l.end, tx=l.text)
                    if self.has_vector:
                        emb = _vec(embeddings[i]) if embeddings and i < len(embeddings) else None
                        con.run(
                            "INSERT INTO transcript_lines (call_id, n, speaker, role, start_s, end_s, text, embedding) "
                            "VALUES (:id, :n, :sp, :r, :st, :en, :tx, CAST(:emb AS vector))", emb=emb, **row)
                    else:
                        con.run(
                            "INSERT INTO transcript_lines (call_id, n, speaker, role, start_s, end_s, text) "
                            "VALUES (:id, :n, :sp, :r, :st, :en, :tx)", **row)
                con.run("DELETE FROM review_items WHERE call_id = :id", id=cid)
                for r in notes["review_items"]:
                    con.run(
                        "INSERT INTO review_items (call_id, item_ref, reason, category, severity, source, evidence) "
                        "VALUES (:id, :ref, :reason, :cat, :sev, :src, CAST(:ev AS jsonb))",
                        id=cid, ref=r["item_ref"], reason=r["reason"], cat=r["category"],
                        sev=r["severity"], src=r["source"], ev=json.dumps(r["evidence"]),
                    )
                con.run("COMMIT")
            except Exception:
                con.run("ROLLBACK")
                raise

    _CALL_SUMMARY = """
        SELECT c.id::text AS id, c.title, c.domain, c.meeting_date::text AS meeting_date, c.participants,
               c.source, c.status, c.error, c.created_at::text AS created_at,
               n.tag, n.sentiment,
               (SELECT count(*) FROM review_items r WHERE r.call_id = c.id AND r.status = 'open') AS open_reviews
        FROM calls c LEFT JOIN call_notes n ON n.call_id = c.id
    """

    def list_calls(self):
        with self.conn() as con:
            return self.rows(con, self._CALL_SUMMARY + " ORDER BY c.created_at DESC")

    def get_call(self, call_id):
        if not str(call_id).isdigit():
            return None
        cid = int(call_id)
        with self.conn() as con:
            rows = self.rows(con, self._CALL_SUMMARY + " WHERE c.id = :id", id=cid)
            if not rows:
                return None
            call = rows[0]
            notes = self.rows(con, "SELECT notes FROM call_notes WHERE call_id = :id", id=cid)
            call["notes"] = notes[0]["notes"] if notes else None
            call["transcript"] = self.rows(
                con, "SELECT n, speaker, role, start_s AS start, end_s AS \"end\", text "
                     "FROM transcript_lines WHERE call_id = :id ORDER BY n", id=cid)
        call["reviews"] = self.list_reviews(call_id=call_id)
        return call

    # ------------------------------------------------------------------ review queue

    _REVIEW_SELECT = """
        SELECT r.id::text AS id, r.call_id::text AS call_id, r.item_ref, r.reason, r.category, r.severity,
               r.source, r.evidence, r.status, r.resolver, r.resolution_note, r.resolved_at::text AS resolved_at,
               c.title AS call_title, c.meeting_date::text AS meeting_date
        FROM review_items r JOIN calls c ON c.id = r.call_id
    """

    def list_reviews(self, status=None, call_id=None):
        where, params = [], {}
        if status:
            where.append("r.status = :status")
            params["status"] = status
        if call_id:
            where.append("r.call_id = :cid")
            params["cid"] = int(call_id)
        sql = self._REVIEW_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY CASE r.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, r.id"
        with self.conn() as con:
            return self.rows(con, sql, **params)

    def resolve_review(self, review_id, status, resolver, note):
        if not str(review_id).isdigit():
            return None
        with self.conn() as con:
            con.run(
                "UPDATE review_items SET status = :s, resolver = :who, resolution_note = :note, resolved_at = now() "
                "WHERE id = :id", s=status, who=resolver, note=note, id=int(review_id),
            )
            rows = self.rows(con, self._REVIEW_SELECT + " WHERE r.id = :id", id=int(review_id))
        return rows[0] if rows else None

    # ------------------------------------------------------------------ search

    def search(self, q, qvec, domain, flag, sentiment, limit=20):
        where, params = ["TRUE"], {}
        if domain:
            where.append("c.domain = :domain")
            params["domain"] = domain
        if sentiment:
            where.append("n.sentiment = :sentiment")
            params["sentiment"] = sentiment
        if flag:
            where.append("n.notes->'risk_flags' @> CAST(:flag AS jsonb)")
            params["flag"] = json.dumps([{"type": flag}])
        filters = " AND ".join(where)

        with self.conn() as con:
            if not q.strip():
                return self.rows(con, f"""
                    SELECT c.id::text AS call_id, c.title, n.tag, NULL::int AS line, NULL AS speaker,
                           n.notes->>'summary' AS text, 0.0 AS score
                    FROM calls c JOIN call_notes n ON n.call_id = c.id
                    WHERE {filters} ORDER BY c.created_at DESC LIMIT :lim""", lim=limit, **params)

            base = f"""FROM transcript_lines l JOIN calls c ON c.id = l.call_id
                       JOIN call_notes n ON n.call_id = c.id WHERE {filters}"""
            keyword = self.rows(con, f"""
                SELECT l.id FROM transcript_lines l, websearch_to_tsquery('english', :q) query
                WHERE l.tsv @@ query AND l.id IN (SELECT l.id {base})
                ORDER BY ts_rank(l.tsv, query) DESC LIMIT 50""", q=q, **params)
            semantic = []
            if qvec and self.has_vector:
                semantic = self.rows(con, f"""
                    SELECT l.id {base} AND l.embedding IS NOT NULL
                      AND (l.embedding <=> CAST(:qv AS vector)) <= :maxd
                    ORDER BY l.embedding <=> CAST(:qv AS vector) LIMIT :k""",
                    qv=_vec(qvec), maxd=settings.search_max_distance, k=settings.search_semantic_top_k, **params)

            scores = rrf_merge([str(r["id"]) for r in keyword], [str(r["id"]) for r in semantic])
            best = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
            if not best:
                return []
            ids = [int(k) for k, _ in best]
            found = self.rows(con, """
                SELECT l.id, c.id::text AS call_id, c.title, n.tag, l.n AS line, l.speaker, l.text
                FROM transcript_lines l JOIN calls c ON c.id = l.call_id JOIN call_notes n ON n.call_id = c.id
                WHERE l.id = ANY(CAST(:ids AS bigint[]))""", ids="{" + ",".join(map(str, ids)) + "}")
        by_id = {str(r.pop("id")): r for r in found}
        return [{**by_id[k], "score": round(s, 4)} for k, s in best if k in by_id]
