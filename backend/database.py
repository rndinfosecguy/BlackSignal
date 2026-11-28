import sqlite3
import os
import json
import threading
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "/app/data/pastes.db")

_local = threading.local()


class QueryError(Exception):
    """Raised when a user-supplied FTS5 query is malformed."""


def _is_fts_error(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "fts5" in msg or "unterminated string" in msg or ("syntax" in msg and "match" in msg)


def _execute(conn: sqlite3.Connection, sql: str, params):
    """Execute a statement, mapping malformed-FTS errors to QueryError."""
    try:
        return conn.execute(sql, params)
    except sqlite3.OperationalError as e:
        if _is_fts_error(e):
            raise QueryError("Invalid search query") from e
        raise


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
    triage_status: Optional[list[str]] = None,
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
    if triage_status:
        placeholders = ",".join("?" for _ in triage_status)
        conditions.append(f"p.triage_status IN ({placeholders})")
        params.extend(triage_status)
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


def _split_types(secret_types: Optional[str]) -> set[str]:
    """Parse the comma-separated secret_types column into a set."""
    return {t.strip() for t in (secret_types or "").split(",") if t.strip()}


def _adjust_type_counts(conn, types, delta: int) -> None:
    """Increment/decrement the precomputed per-type paste counts."""
    for t in types:
        conn.execute(
            "INSERT INTO secret_type_counts (type, count) VALUES (?, ?) "
            "ON CONFLICT(type) DO UPDATE SET count = count + ?",
            (t, delta, delta),
        )
        conn.execute(
            "DELETE FROM secret_type_counts WHERE type = ? AND count <= 0", (t,)
        )


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
            fully_scanned INTEGER NOT NULL DEFAULT 0,
            triage_status TEXT NOT NULL DEFAULT 'new',
            triage_note TEXT NOT NULL DEFAULT '',
            triage_reviewer TEXT NOT NULL DEFAULT '',
            triage_updated_at TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS pastes_fts USING fts5(
            id UNINDEXED,
            filename,
            source UNINDEXED,
            content_type UNINDEXED,
            content,
            tokenize='porter unicode61'
        );

        CREATE TABLE IF NOT EXISTS secret_type_counts (
            type  TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_pastes_source ON pastes(source, triage_status, has_secrets, has_passwords, content_type);
        CREATE INDEX IF NOT EXISTS idx_pastes_content_type ON pastes(content_type, triage_status, has_secrets, has_passwords, source);
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

    # Triage columns (added after existing tables so ALTERs work on old DBs).
    for ddl in (
        "ALTER TABLE pastes ADD COLUMN triage_status TEXT NOT NULL DEFAULT 'new'",
        "ALTER TABLE pastes ADD COLUMN triage_note TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE pastes ADD COLUMN triage_reviewer TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE pastes ADD COLUMN triage_updated_at TEXT",
    ):
        try:
            conn.execute(ddl)
            conn.commit()
        except sqlite3.OperationalError:
            pass

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pastes_triage ON pastes(triage_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pastes_triage_first ON pastes(triage_status, first_seen DESC)")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Covering indexes for the stats aggregates. Without them every /api/stats
    # call scans the whole pastes table (row content included), which takes
    # seconds on a multi-hundred-MB database. These indexes are tiny because
    # they only contain counters/labels, never content.
    #
    # Older databases also have single-column source/content_type indexes.
    # Widen those in place so filtered stats stay covered too. Each index is
    # rebuilt only when its definition is out of date.
    for name, wanted in (
        ("idx_pastes_stats",
         ["triage_status", "has_secrets", "has_passwords", "source",
          "content_type", "first_seen"]),
        ("idx_pastes_source",
         ["source", "triage_status", "has_secrets", "has_passwords", "content_type"]),
        ("idx_pastes_content_type",
         ["content_type", "triage_status", "has_secrets", "has_passwords", "source"]),
    ):
        try:
            current = [r[2] for r in conn.execute(f"PRAGMA index_info({name})").fetchall()]
            if current and current != wanted:
                conn.execute(f"DROP INDEX {name}")
                current = []
            if not current:
                conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON pastes({', '.join(wanted)})")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Backfill the precomputed secret-type counts once (new table or databases
    # indexed before it existed). Kept incremental afterwards by upsert/delete.
    try:
        empty = conn.execute("SELECT COUNT(*) FROM secret_type_counts").fetchone()[0] == 0
        if empty:
            counts = {}
            for row in conn.execute("SELECT secret_types FROM pastes WHERE secret_types != ''"):
                for t in _split_types(row["secret_types"]):
                    counts[t] = counts.get(t, 0) + 1
            if counts:
                conn.executemany(
                    "INSERT INTO secret_type_counts (type, count) VALUES (?, ?)",
                    counts.items(),
                )
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

    # The precomputed per-type counts need the previous row to apply a delta.
    old_row = conn.execute(
        "SELECT secret_types FROM pastes WHERE id = ?", (paste_id,)
    ).fetchone()
    old_types = _split_types(old_row["secret_types"]) if old_row else set()
    new_types = _split_types(secret_types)

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

    if old_types != new_types:
        _adjust_type_counts(conn, old_types - new_types, -1)
        _adjust_type_counts(conn, new_types - old_types, +1)

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
    row = conn.execute(
        "SELECT secret_types FROM pastes WHERE id = ?", (paste_id,)
    ).fetchone()
    conn.execute("DELETE FROM pastes WHERE id = ?", (paste_id,))
    conn.execute("DELETE FROM pastes_fts WHERE id = ?", (paste_id,))
    if row:
        _adjust_type_counts(conn, _split_types(row["secret_types"]), -1)
    if commit:
        conn.commit()


def search_pastes_grouped(group_by, query=None, source=None, content_type=None,
                          has_secrets=None, secret_types=None, per_group=5,
                          date_from=None, date_to=None, triage_status=None):
    """Search pastes grouped by a column (source or content_type).
    Returns top 10 groups, each with up to `per_group` results."""
    conn = get_conn()
    conditions, params = build_filter_conditions(
        query, source, content_type, has_secrets, secret_types,
        date_from=date_from, date_to=date_to, triage_status=triage_status,
    )
    where = " AND ".join(conditions) if conditions else "1=1"

    # Validate group_by column
    valid_columns = {"source": "p.source", "content_type": "p.content_type"}
    col_expr = valid_columns.get(group_by)
    if not col_expr:
        return None  # fallback to flat search

    # Get top 10 groups by count
    group_sql = f"SELECT {col_expr} AS key, COUNT(*) AS cnt FROM pastes p WHERE {where} GROUP BY key ORDER BY cnt DESC LIMIT 10"
    groups = _execute(conn, group_sql, params).fetchall()

    total = sum(g["cnt"] for g in groups)
    result_groups = []

    data_sql = f"""
        SELECT p.id, p.filename, p.source, p.content_type, p.size,
               p.has_passwords, p.has_secrets, p.secret_types,
               p.first_seen, p.modified_at,
               p.triage_status, p.triage_note, p.triage_reviewer, p.triage_updated_at,
               CASE WHEN p.snippet = '' THEN substr(p.content, 1, 200) ELSE p.snippet END as snippet
        FROM pastes p
        WHERE {where} AND {col_expr} = ?
        ORDER BY p.first_seen DESC
        LIMIT ?
    """

    for g in groups:
        key = g["key"]
        rows = _execute(conn, data_sql, params + [key, per_group]).fetchall()
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
                  page=1, per_page=50, date_from=None, date_to=None,
                  triage_status=None):
    conn = get_conn()
    conditions, params = build_filter_conditions(
        query, source, content_type, has_secrets, secret_types,
        date_from=date_from, date_to=date_to, triage_status=triage_status,
    )
    where = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) FROM pastes p WHERE {where}"
    total = _execute(conn, count_sql, params).fetchone()[0]

    data_sql = f"""
        SELECT p.id, p.filename, p.source, p.content_type, p.size,
               p.has_passwords, p.has_secrets, p.secret_types,
               p.first_seen, p.modified_at,
               p.triage_status, p.triage_note, p.triage_reviewer, p.triage_updated_at,
               CASE WHEN p.snippet = '' THEN substr(p.content, 1, 200) ELSE p.snippet END as snippet
        FROM pastes p
        WHERE {where}
        ORDER BY p.first_seen DESC
        LIMIT ? OFFSET ?
    """
    rows = _execute(conn, data_sql, params + [per_page, offset]).fetchall()

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


def count_pastes(query=None, source=None, content_type=None,
                 has_secrets=None, secret_types=None,
                 date_from=None, date_to=None, triage_status=None) -> int:
    """Cheap COUNT of pastes matching the filters — no row content is loaded.

    Use this to enforce limits before materializing results."""
    conn = get_conn()
    conditions, params = build_filter_conditions(
        query, source, content_type, has_secrets, secret_types,
        date_from=date_from, date_to=date_to, triage_status=triage_status,
    )
    where = " AND ".join(conditions) if conditions else "1=1"
    return _execute(conn, f"SELECT COUNT(*) FROM pastes p WHERE {where}", params).fetchone()[0]


def validate_fts(query: str) -> None:
    """Raise QueryError if the FTS5 expression is malformed (cheap probe)."""
    conn = get_conn()
    _execute(conn, "SELECT 1 FROM pastes_fts WHERE pastes_fts MATCH ? LIMIT 1", (query,))


def export_pastes(query=None, source=None, content_type=None,
                  has_secrets=None, secret_types=None, include_content=False,
                  date_from=None, date_to=None, limit=None, triage_status=None):
    """Generator yielding paste dicts matching the current filters.
    Used by the /api/pastes/export endpoint and the LLM report builder.
    Pass ``limit`` to cap the number of rows loaded (recommended for callers
    that must not materialize an entire large collection).
    secrets_detail is parsed into a proper Python list for JSON serialization."""
    conn = get_conn()
    conditions, params = build_filter_conditions(
        query, source, content_type, has_secrets, secret_types,
        date_from=date_from, date_to=date_to, triage_status=triage_status,
    )
    where = " AND ".join(conditions) if conditions else "1=1"

    content_col = ", p.content" if include_content else ""
    limit_sql = ""
    if limit is not None:
        # Cast to int defensively — never interpolate caller strings into SQL.
        limit_sql = f" LIMIT {int(limit)}"
    data_sql = f"""
        SELECT p.id, p.filename, p.source, p.content_type, p.size,
               p.has_passwords, p.has_secrets, p.secret_types, p.secrets_detail,
               p.first_seen, p.modified_at,
               p.triage_status, p.triage_note, p.triage_reviewer, p.triage_updated_at
               {content_col}
        FROM pastes p
        WHERE {where}
        ORDER BY p.first_seen DESC{limit_sql}
    """
    import json
    cursor = _execute(conn, data_sql, params)
    for row in cursor:
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


def update_triage(paste_id: str, status: Optional[str] = None,
                  note: Optional[str] = None, reviewer: str = "") -> Optional[dict]:
    """Update triage state for one paste. Returns the new state or None."""
    if status is not None and status not in TRIAGE_STATUSES:
        raise ValueError("Invalid triage status")

    sets = []
    params = []
    if status is not None:
        sets.append("triage_status = ?")
        params.append(status)
    if note is not None:
        sets.append("triage_note = ?")
        params.append(note)
    if not sets:
        return None

    sets.append("triage_reviewer = ?")
    params.append(reviewer or "")
    sets.append("triage_updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    params.append(paste_id)

    conn = get_conn()
    cursor = conn.execute(f"UPDATE pastes SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    if cursor.rowcount == 0:
        return None

    row = conn.execute(
        "SELECT triage_status, triage_note, triage_reviewer, triage_updated_at"
        " FROM pastes WHERE id = ?",
        (paste_id,),
    ).fetchone()
    return dict(row)


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
    if not source and not content_type:
        # Unfiltered counts are maintained incrementally by upsert/delete.
        rows = conn.execute(
            "SELECT type, count FROM secret_type_counts WHERE count > 0 ORDER BY count DESC"
        ).fetchall()
        if rows:
            return [{"type": r["type"], "count": r["count"]} for r in rows]
        # Empty table with no types indexed: fall through to the scan so a
        # database indexed by an older version still answers correctly.

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
        for st in _split_types(row["secret_types"]):
            counts[st] = counts.get(st, 0) + 1

    result = [{"type": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return result


TRIAGE_STATUSES = ("new", "reviewed", "false_positive", "escalated")


def get_stats():
    conn = get_conn()
    row = conn.execute("""
        SELECT COUNT(*) as total,
               COALESCE(SUM(CASE WHEN has_secrets=1 THEN 1 ELSE 0 END), 0) as with_secrets,
               COALESCE(SUM(CASE WHEN has_passwords=1 THEN 1 ELSE 0 END), 0) as with_passwords,
               COUNT(DISTINCT source) as sources,
               COALESCE(SUM(CASE WHEN triage_status='new' THEN 1 ELSE 0 END), 0) as unreviewed,
               COALESCE(SUM(CASE WHEN triage_status='reviewed' THEN 1 ELSE 0 END), 0) as reviewed,
               COALESCE(SUM(CASE WHEN triage_status='false_positive' THEN 1 ELSE 0 END), 0) as false_positive,
               COALESCE(SUM(CASE WHEN triage_status='escalated' THEN 1 ELSE 0 END), 0) as escalated
        FROM pastes
    """).fetchone()
    d = dict(row)
    d["total_all"] = d["total"]
    d["with_secrets_all"] = d["with_secrets"]
    d["with_passwords_all"] = d["with_passwords"]
    d["sources_all"] = d["sources"]
    for key in ("unreviewed", "reviewed", "false_positive", "escalated"):
        d[f"{key}_all"] = d[key]
    return d


def get_stats_filtered(conditions, params):
    conn = get_conn()
    where = " AND ".join(conditions) if conditions else "1=1"

    select_stats = """
        SELECT COUNT(*) as total,
               COALESCE(SUM(CASE WHEN has_secrets=1 THEN 1 ELSE 0 END), 0) as with_secrets,
               COALESCE(SUM(CASE WHEN has_passwords=1 THEN 1 ELSE 0 END), 0) as with_passwords,
               COUNT(DISTINCT source) as sources,
               COALESCE(SUM(CASE WHEN triage_status='new' THEN 1 ELSE 0 END), 0) as unreviewed,
               COALESCE(SUM(CASE WHEN triage_status='reviewed' THEN 1 ELSE 0 END), 0) as reviewed,
               COALESCE(SUM(CASE WHEN triage_status='false_positive' THEN 1 ELSE 0 END), 0) as false_positive,
               COALESCE(SUM(CASE WHEN triage_status='escalated' THEN 1 ELSE 0 END), 0) as escalated
        FROM pastes
    """

    row = _execute(conn, f"{select_stats} p WHERE {where}", params).fetchone()
    all_row = conn.execute(select_stats).fetchone()

    result = {
        "total": row["total"], "total_all": all_row["total"],
        "with_secrets": row["with_secrets"], "with_secrets_all": all_row["with_secrets"],
        "with_passwords": row["with_passwords"], "with_passwords_all": all_row["with_passwords"],
        "sources": row["sources"], "sources_all": all_row["sources"],
    }
    for key in ("unreviewed", "reviewed", "false_positive", "escalated"):
        result[key] = row[key]
        result[f"{key}_all"] = all_row[key]
    return result


def clear_all_data():
    """Delete all indexed pastes and FTS entries — used for purge reindex.
    Uses DROP TABLE instead of DELETE FROM for fast execution on large databases."""

    conn = get_conn()
    conn.execute("PRAGMA synchronous=OFF")
    # Debian/Ubuntu build SQLite with secure_delete=ON, so DROP TABLE zeroes
    # every freed page. On a 600 MB database that is the dominant purge cost
    # (tens of seconds on EBS/overlay2). The purge immediately reindexes, and
    # the raw source files remain on disk anyway, so skip the zeroing here and
    # restore the pragma afterwards.
    try:
        conn.execute("PRAGMA secure_delete=OFF")
    except sqlite3.OperationalError:
        pass
    conn.execute("DROP TABLE IF EXISTS pastes_fts")
    conn.execute("DROP TABLE IF EXISTS pastes")
    conn.execute("DROP TABLE IF EXISTS secret_type_counts")
    conn.commit()
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        conn.execute("PRAGMA secure_delete=ON")
    except sqlite3.OperationalError:
        pass
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