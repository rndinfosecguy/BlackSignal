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
        _local.conn.execute("PRAGMA cache_size=-8192")
        _local.conn.execute("PRAGMA temp_store=FILE")
    return _local.conn


def build_filter_conditions(
    query: Optional[str] = None,
    source: Optional[list[str]] = None,
    content_type: Optional[list[str]] = None,
    has_secrets: Optional[bool] = None,
    secret_types: Optional[list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    conditions = []
    params = []
    if query:
        conditions.append("p.id IN (SELECT id FROM pastes_fts WHERE pastes_fts MATCH ?)")
        params.append(query)
    if source:
        placeholders = ",".join("?" for _ in source)
        conditions.append(f"p.source IN ({placeholders})")
        params.extend(source)
    if content_type:
        placeholders = ",".join("?" for _ in content_type)
        conditions.append(f"p.content_type IN ({placeholders})")
        params.extend(content_type)
    if has_secrets is not None:
        conditions.append("p.has_secrets = ?")
        params.append(1 if has_secrets else 0)
    if secret_types:
        st_clauses = []
        for st in secret_types:
            # Match exact token within comma-separated list — not substrings
            st_clauses.append(
                "(p.secret_types LIKE ? OR p.secret_types LIKE ?"
                " OR p.secret_types LIKE ? OR p.secret_types LIKE ?)"
            )
            params.extend([f'{st},%', f'%,{st},%', f'%,{st}', st])
        conditions.append(f"({' OR '.join(st_clauses)})")
    if date_from:
        conditions.append("p.first_seen >= ?")
        params.append(date_from)
    if date_to:
        # If no time component, extend to end of day for inclusive filtering
        if ' ' not in date_to:
            date_to = date_to + ' 23:59:59'
        conditions.append("p.first_seen <= ?")
        params.append(date_to)
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
            modified_at TEXT,
            fully_scanned INTEGER NOT NULL DEFAULT 0
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
        CREATE INDEX IF NOT EXISTS idx_pastes_has_passwords ON pastes(has_passwords);
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

    try:
        conn.execute("INSERT INTO pastes_fts(pastes_fts) VALUES('automerge=1')")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE pastes ADD COLUMN fully_scanned INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    conn.commit()


def upsert_paste(paste_id, filename, source, content, content_type, size,
                 has_passwords, has_secrets, secrets_detail, modified_at, fully_scanned=0, commit=True):
    conn = get_conn()

    secret_types = ''
    if secrets_detail:
        types = sorted(set(s['type'] for s in secrets_detail))
        secret_types = ','.join(types)

    conn.execute("""
        INSERT INTO pastes (id, filename, source, content, content_type, size,
                            has_passwords, has_secrets, secrets_detail, secret_types, snippet, modified_at, fully_scanned)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            content=excluded.content,
            content_type=excluded.content_type,
            size=excluded.size,
            has_passwords=excluded.has_passwords,
            has_secrets=excluded.has_secrets,
            secrets_detail=excluded.secrets_detail,
            secret_types=excluded.secret_types,
            snippet=excluded.snippet,
            modified_at=excluded.modified_at,
            fully_scanned=excluded.fully_scanned
    """, (paste_id, filename, source, content, content_type, size,
          has_passwords, has_secrets, json.dumps(secrets_detail) if secrets_detail else None,
          secret_types, content[:200], modified_at, fully_scanned))

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


def delete_paste(paste_id, commit=True):
    conn = get_conn()
    conn.execute("DELETE FROM pastes WHERE id = ?", (paste_id,))
    conn.execute("DELETE FROM pastes_fts WHERE id = ?", (paste_id,))
    if commit:
        conn.commit()


def search_pastes_grouped(group_by, query=None, source=None, content_type=None,
                          has_secrets=None, secret_types=None, per_group=5,
                          date_from=None, date_to=None):
    """Search pastes grouped by a column (source or content_type).
    Returns top 10 groups, each with up to `per_group` results."""
    conn = get_conn()
    conditions, params = build_filter_conditions(query, source, content_type, has_secrets, secret_types, date_from=date_from, date_to=date_to)
    where = " AND ".join(conditions) if conditions else "1=1"

    # Validate group_by column
    valid_columns = {"source": "p.source", "content_type": "p.content_type"}
    col_expr = valid_columns.get(group_by)
    if not col_expr:
        return None  # fallback to flat search

    # Get top 10 groups by count
    group_sql = f"SELECT {col_expr} AS key, COUNT(*) AS cnt FROM pastes p WHERE {where} GROUP BY key ORDER BY cnt DESC LIMIT 10"
    groups = conn.execute(group_sql, params).fetchall()

    total = sum(g["cnt"] for g in groups)
    result_groups = []

    data_sql = f"""
        SELECT p.id, p.filename, p.source, p.content_type, p.size,
               p.has_passwords, p.has_secrets, p.secret_types,
               p.first_seen, p.modified_at,
               CASE WHEN p.snippet = '' THEN substr(p.content, 1, 200) ELSE p.snippet END as snippet
        FROM pastes p
        WHERE {where} AND {col_expr} = ?
        ORDER BY p.first_seen DESC
        LIMIT ?
    """

    for g in groups:
        key = g["key"]
        rows = conn.execute(data_sql, params + [key, per_group]).fetchall()
        items = []
        for row in rows:
            d = dict(row)
            st = d.get("secret_types") or ""
            d["secret_types"] = [x for x in st.split(",") if x] if st else []
            items.append(d)
        result_groups.append({
            "key": key,
            "total": g["cnt"],
            "results": items,
        })

    return {
        "total": total,
        "group_by": group_by,
        "groups": result_groups,
    }


def search_pastes(query=None, source=None, content_type=None,
                  has_secrets=None, secret_types=None,
                  page=1, per_page=50, date_from=None, date_to=None):
    conn = get_conn()
    conditions, params = build_filter_conditions(query, source, content_type, has_secrets, secret_types, date_from=date_from, date_to=date_to)
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


def export_pastes(query=None, source=None, content_type=None,
                  has_secrets=None, secret_types=None, include_content=False,
                  date_from=None, date_to=None):
    """Generator yielding paste dicts matching the current filters.
    Used by the /api/pastes/export endpoint — no LIMIT/OFFSET.
    secrets_detail is parsed into a proper Python list for JSON serialization."""
    conn = get_conn()
    conditions, params = build_filter_conditions(query, source, content_type, has_secrets, secret_types, date_from=date_from, date_to=date_to)
    where = " AND ".join(conditions) if conditions else "1=1"

    content_col = ", p.content" if include_content else ""
    data_sql = f"""
        SELECT p.id, p.filename, p.source, p.content_type, p.size,
               p.has_passwords, p.has_secrets, p.secret_types, p.secrets_detail,
               p.first_seen
               {content_col}
        FROM pastes p
        WHERE {where}
        ORDER BY p.first_seen DESC
    """
    import json
    rows = conn.execute(data_sql, params).fetchall()
    for row in rows:
        d = dict(row)
        st = d.get("secret_types") or ""
        d["secret_types"] = [x for x in st.split(",") if x] if st else []
        # Parse secrets_detail from JSON string into proper list
        sd = d.get("secrets_detail")
        if sd and sd != "None" and sd != "null":
            try:
                d["secrets_detail"] = json.loads(sd) if isinstance(sd, str) else sd
            except (json.JSONDecodeError, TypeError):
                d["secrets_detail"] = []
        else:
            d["secrets_detail"] = []
        yield d


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


def get_sources(content_type=None):
    conn = get_conn()
    where, params = "", []
    if content_type:
        where, params = "WHERE content_type = ?", [content_type]
    rows = conn.execute(
        f"SELECT source, COUNT(*) as count FROM pastes {where} GROUP BY source ORDER BY count DESC",
        params
    ).fetchall()
    return [dict(r) for r in rows]


def get_content_types(source=None):
    conn = get_conn()
    where, params = "", []
    if source:
        where, params = "WHERE source = ?", [source]
    rows = conn.execute(
        f"SELECT content_type, COUNT(*) as count FROM pastes {where} GROUP BY content_type ORDER BY count DESC",
        params
    ).fetchall()
    return [dict(r) for r in rows]


def get_secret_types(source=None, content_type=None):
    conn = get_conn()
    conditions = ["secret_types != ''"]
    params = []
    if source:
        conditions.append("source = ?")
        params.append(source)
    if content_type:
        conditions.append("content_type = ?")
        params.append(content_type)
    where = " AND ".join(conditions)
    rows = conn.execute(f"SELECT secret_types FROM pastes WHERE {where}", params).fetchall()

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
    row = conn.execute("""
        SELECT COUNT(*) as total,
               COALESCE(SUM(CASE WHEN has_secrets=1 THEN 1 ELSE 0 END), 0) as with_secrets,
               COALESCE(SUM(CASE WHEN has_passwords=1 THEN 1 ELSE 0 END), 0) as with_passwords,
               COUNT(DISTINCT source) as sources
        FROM pastes
    """).fetchone()
    d = dict(row)
    d["total_all"] = d["total"]
    d["with_secrets_all"] = d["with_secrets"]
    d["with_passwords_all"] = d["with_passwords"]
    d["sources_all"] = d["sources"]
    return d


def get_stats_filtered(conditions, params):
    conn = get_conn()
    where = " AND ".join(conditions) if conditions else "1=1"

    row = conn.execute(f"""
        SELECT COUNT(*) as total,
               COALESCE(SUM(CASE WHEN has_secrets=1 THEN 1 ELSE 0 END), 0) as with_secrets,
               COALESCE(SUM(CASE WHEN has_passwords=1 THEN 1 ELSE 0 END), 0) as with_passwords,
               COUNT(DISTINCT source) as sources
        FROM pastes p WHERE {where}
    """, params).fetchone()

    all_row = conn.execute("""
        SELECT COUNT(*) as total,
               COALESCE(SUM(CASE WHEN has_secrets=1 THEN 1 ELSE 0 END), 0) as with_secrets,
               COALESCE(SUM(CASE WHEN has_passwords=1 THEN 1 ELSE 0 END), 0) as with_passwords,
               COUNT(DISTINCT source) as sources
        FROM pastes
    """).fetchone()

    return {
        "total": row["total"], "total_all": all_row["total"],
        "with_secrets": row["with_secrets"], "with_secrets_all": all_row["with_secrets"],
        "with_passwords": row["with_passwords"], "with_passwords_all": all_row["with_passwords"],
        "sources": row["sources"], "sources_all": all_row["sources"],
    }


def clear_all_data():
    """Delete all indexed pastes and FTS entries — used for purge reindex.
    Uses DROP TABLE instead of DELETE FROM for fast execution on large databases."""

    conn = get_conn()
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("DROP TABLE IF EXISTS pastes_fts")
    conn.execute("DROP TABLE IF EXISTS pastes")
    conn.commit()
    conn.execute("PRAGMA synchronous=NORMAL")
    # Re-create the tables and indexes
    init_db()


def get_indexed_ids():
    conn = get_conn()
    rows = conn.execute("SELECT id FROM pastes").fetchall()
    return {r["id"] for r in rows}


def get_indexed_mtimes():
    """Return {id: modified_at} for all indexed pastes.
    Used by incremental reindex to skip unchanged files."""
    conn = get_conn()
    rows = conn.execute("SELECT id, modified_at FROM pastes WHERE modified_at IS NOT NULL AND modified_at != ''").fetchall()
    return {r["id"]: r["modified_at"] for r in rows}