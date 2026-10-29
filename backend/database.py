import sqlite3
import os
import json
import threading
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "/app/data/pastes.db")

_local = threading.local()


def get_conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, timeout=15)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA busy_timeout=10000")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA cache_size=-64000")
        _local.conn.execute("PRAGMA temp_store=MEMORY")
    return _local.conn


def build_filter_conditions(
    query: Optional[str] = None,
    source: Optional[str] = None,
    content_type: Optional[str] = None,
    has_secrets: Optional[bool] = None,
    secret_types: Optional[list[str]] = None,
):
    conditions = []
    params = []
    if query:
        conditions.append("p.id IN (SELECT id FROM pastes_fts WHERE pastes_fts MATCH ?)")
        params.append(query)
    if source:
        conditions.append("p.source = ?")
        params.append(source)
    if content_type:
        conditions.append("p.content_type = ?")
        params.append(content_type)
    if has_secrets is not None:
        conditions.append("p.has_secrets = ?")
        params.append(1 if has_secrets else 0)
    if secret_types:
        clauses = ["p.secret_types LIKE ?" for _ in secret_types]
        conditions.append(f"({' OR '.join(clauses)})")
        params.extend([f'%{st}%' for st in secret_types])
    return conditions, params


def init_db():
    conn = get_conn()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""

        CREATE TABLE IF NOT EXISTS pastes (
            id          TEXT PRIMARY KEY,
            filename    TEXT NOT NULL,
            source      TEXT NOT NULL,
            content     TEXT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'unknown',
            size        INTEGER NOT NULL DEFAULT 0,
            has_passwords INTEGER NOT NULL DEFAULT 0,
            has_secrets   INTEGER NOT NULL DEFAULT 0,
            secrets_detail TEXT,
            secret_types  TEXT NOT NULL DEFAULT '',
            snippet      TEXT NOT NULL DEFAULT '',
            first_seen  TEXT DEFAULT (datetime('now')),
            modified_at TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS pastes_fts USING fts5(
            id UNINDEXED,
            filename,
            source UNINDEXED,
            content_type UNINDEXED,
            content,
            tokenize='porter unicode61'
        );

        CREATE INDEX IF NOT EXISTS idx_pastes_source ON pastes(source);
        CREATE INDEX IF NOT EXISTS idx_pastes_content_type ON pastes(content_type);
        CREATE INDEX IF NOT EXISTS idx_pastes_has_secrets ON pastes(has_secrets);
        CREATE INDEX IF NOT EXISTS idx_pastes_secret_types ON pastes(secret_types);
        CREATE INDEX IF NOT EXISTS idx_pastes_first_seen ON pastes(first_seen DESC);
        CREATE INDEX IF NOT EXISTS idx_pastes_has_first ON pastes(has_secrets, first_seen DESC);
    """)

    try:
        conn.execute("ALTER TABLE pastes ADD COLUMN secret_types TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE pastes ADD COLUMN snippet TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    conn.commit()


def upsert_paste(paste_id, filename, source, content, content_type, size,
                 has_passwords, has_secrets, secrets_detail, modified_at, commit=True):
    conn = get_conn()

    secret_types = ''
    if secrets_detail:
        types = sorted(set(s['type'] for s in secrets_detail))
        secret_types = ','.join(types)

    conn.execute("""
        INSERT INTO pastes (id, filename, source, content, content_type, size,
                            has_passwords, has_secrets, secrets_detail, secret_types, snippet, modified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            content=excluded.content,
            content_type=excluded.content_type,
            size=excluded.size,
            has_passwords=excluded.has_passwords,
            has_secrets=excluded.has_secrets,
            secrets_detail=excluded.secrets_detail,
            secret_types=excluded.secret_types,
            snippet=excluded.snippet,
            modified_at=excluded.modified_at
    """, (paste_id, filename, source, content, content_type, size,
          has_passwords, has_secrets, json.dumps(secrets_detail) if secrets_detail else None,
          secret_types, content[:200], modified_at))

    fts_content = content[:50000]
    existing = conn.execute("SELECT id FROM pastes_fts WHERE id = ?", (paste_id,)).fetchone()
    if existing:
        conn.execute("UPDATE pastes_fts SET filename=?, source=?, content_type=?, content=? WHERE id=?",
                     (filename, source, content_type, fts_content, paste_id))
    else:
        conn.execute("INSERT INTO pastes_fts (id, filename, source, content_type, content) VALUES (?, ?, ?, ?, ?)",
                     (paste_id, filename, source, content_type, fts_content))
    if commit:
        conn.commit()


def backfill_snippets():
    conn = get_conn()
    total = 0
    while True:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM pastes WHERE snippet = '' OR snippet IS NULL LIMIT 500"
        ).fetchall()]
        if not ids:
            break
        conn.executemany(
            "UPDATE pastes SET snippet = substr(content, 1, 200) WHERE id = ?",
            [(i,) for i in ids]
        )
        conn.commit()
        total += len(ids)
    return total


def delete_paste(paste_id, commit=True):
    conn = get_conn()
    conn.execute("DELETE FROM pastes WHERE id = ?", (paste_id,))
    conn.execute("DELETE FROM pastes_fts WHERE id = ?", (paste_id,))
    if commit:
        conn.commit()


def search_pastes(query=None, source=None, content_type=None,
                  has_secrets=None, secret_types=None,
                  page=1, per_page=50):
    conn = get_conn()
    conditions, params = build_filter_conditions(query, source, content_type, has_secrets, secret_types)
    where = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) FROM pastes p WHERE {where}"
    total = conn.execute(count_sql, params).fetchone()[0]

    data_sql = f"""
        SELECT p.id, p.filename, p.source, p.content_type, p.size,
               p.has_passwords, p.has_secrets, p.secret_types,
               p.first_seen, p.modified_at,
               CASE WHEN p.snippet = '' THEN substr(p.content, 1, 200) ELSE p.snippet END as snippet
        FROM pastes p
        WHERE {where}
        ORDER BY p.first_seen DESC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(data_sql, params + [per_page, offset]).fetchall()

    results = []
    for row in rows:
        d = dict(row)
        st = d.get("secret_types") or ""
        d["secret_types"] = [x for x in st.split(",") if x] if st else []
        results.append(d)

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "results": results,
    }


def get_paste_by_id(paste_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM pastes WHERE id = ?", (paste_id,)).fetchone()
    if row:
        d = dict(row)
        d["secrets_detail"] = json.loads(d["secrets_detail"]) if d["secrets_detail"] else None
        st = d.get("secret_types") or ""
        d["secret_types"] = [x for x in st.split(",") if x] if st else []
        return d
    return None


def get_sources():
    conn = get_conn()
    rows = conn.execute(
        "SELECT source, COUNT(*) as count FROM pastes GROUP BY source ORDER BY count DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_content_types():
    conn = get_conn()
    rows = conn.execute(
        "SELECT content_type, COUNT(*) as count FROM pastes GROUP BY content_type ORDER BY count DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_secret_types():
    conn = get_conn()
    rows = conn.execute(
        "SELECT secret_types FROM pastes WHERE secret_types != ''"
    ).fetchall()

    counts = {}
    for row in rows:
        for st in row["secret_types"].split(","):
            st = st.strip()
            if st:
                counts[st] = counts.get(st, 0) + 1

    result = [{"type": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return result


def get_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM pastes").fetchone()[0]
    with_secrets = conn.execute("SELECT COUNT(*) FROM pastes WHERE has_secrets = 1").fetchone()[0]
    with_passwords = conn.execute("SELECT COUNT(*) FROM pastes WHERE has_passwords = 1").fetchone()[0]
    sources = conn.execute("SELECT COUNT(DISTINCT source) FROM pastes").fetchone()[0]
    return {
        "total": total,
        "with_secrets": with_secrets,
        "with_passwords": with_passwords,
        "sources": sources,
        "total_all": total,
        "with_secrets_all": with_secrets,
        "with_passwords_all": with_passwords,
        "sources_all": sources,
    }


def get_stats_filtered(conditions, params):
    conn = get_conn()
    where = " AND ".join(conditions) if conditions else "1=1"

    total_all = conn.execute("SELECT COUNT(*) FROM pastes").fetchone()[0]
    total = conn.execute(f"SELECT COUNT(*) FROM pastes p WHERE {where}", params).fetchone()[0]

    secrets_all = conn.execute("SELECT COUNT(*) FROM pastes WHERE has_secrets = 1").fetchone()[0]
    secrets = conn.execute(f"SELECT COUNT(*) FROM pastes p WHERE {where} AND p.has_secrets = 1", params).fetchone()[0]

    passwords_all = conn.execute("SELECT COUNT(*) FROM pastes WHERE has_passwords = 1").fetchone()[0]
    passwords = conn.execute(f"SELECT COUNT(*) FROM pastes p WHERE {where} AND p.has_passwords = 1", params).fetchone()[0]

    sources_all = conn.execute("SELECT COUNT(DISTINCT source) FROM pastes").fetchone()[0]
    sources = conn.execute(f"SELECT COUNT(DISTINCT source) FROM pastes p WHERE {where}", params).fetchone()[0]

    return {
        "total": total, "total_all": total_all,
        "with_secrets": secrets, "with_secrets_all": secrets_all,
        "with_passwords": passwords, "with_passwords_all": passwords_all,
        "sources": sources, "sources_all": sources_all,
    }


def get_indexed_ids():
    conn = get_conn()
    rows = conn.execute("SELECT id FROM pastes").fetchall()
    return {r["id"] for r in rows}