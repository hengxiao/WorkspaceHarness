"""SQLite schema, connection management, and migrations for the code index."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY,
    project      TEXT NOT NULL,
    path         TEXT NOT NULL,
    language     TEXT,
    size_bytes   INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at   TEXT NOT NULL,
    UNIQUE(project, path)
);

CREATE TABLE IF NOT EXISTS symbols (
    id          INTEGER PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    line_start  INTEGER NOT NULL,
    line_end    INTEGER NOT NULL,
    col_start   INTEGER NOT NULL DEFAULT 0,
    col_end     INTEGER NOT NULL DEFAULT 0,
    parent_id   INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    signature   TEXT,
    docstring   TEXT,
    visibility  TEXT,
    is_export   BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS refs (
    id       INTEGER PRIMARY KEY,
    file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    kind     TEXT,
    line     INTEGER NOT NULL,
    col      INTEGER NOT NULL DEFAULT 0,
    scope_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    module      TEXT NOT NULL,
    names       TEXT,
    alias       TEXT,
    line        INTEGER NOT NULL,
    is_reexport BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS type_edges (
    id          INTEGER PRIMARY KEY,
    child_id    INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    parent_name TEXT NOT NULL,
    parent_id   INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbols_file   ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name   ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_kind   ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_id);
CREATE INDEX IF NOT EXISTS idx_refs_file      ON refs(file_id);
CREATE INDEX IF NOT EXISTS idx_refs_name      ON refs(name);
CREATE INDEX IF NOT EXISTS idx_imports_file   ON imports(file_id);
CREATE INDEX IF NOT EXISTS idx_imports_module ON imports(module);
CREATE INDEX IF NOT EXISTS idx_files_project  ON files(project);
CREATE INDEX IF NOT EXISTS idx_files_lang     ON files(project, language);
CREATE INDEX IF NOT EXISTS idx_type_child     ON type_edges(child_id);
CREATE INDEX IF NOT EXISTS idx_type_parent    ON type_edges(parent_id);
"""

_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name, docstring, signature,
    content=symbols, content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, docstring, signature)
    VALUES (new.id, new.name, new.docstring, new.signature);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, docstring, signature)
    VALUES ('delete', old.id, old.name, old.docstring, old.signature);
END;

CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, docstring, signature)
    VALUES ('delete', old.id, old.name, old.docstring, old.signature);
    INSERT INTO symbols_fts(rowid, name, docstring, signature)
    VALUES (new.id, new.name, new.docstring, new.signature);
END;
"""


def db_path(harness_root: Path) -> Path:
    return harness_root / ".harness" / "code.db"


def connect(harness_root: Path) -> sqlite3.Connection:
    path = db_path(harness_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.executescript(_FTS_SQL)
    _ensure_meta(conn)
    return conn


def _ensure_meta(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()


def clear_file(conn: sqlite3.Connection, file_id: int) -> None:
    """Delete all data for a file (CASCADE removes symbols, refs, imports)."""
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))


def clear_project(conn: sqlite3.Connection, project: str) -> None:
    conn.execute("DELETE FROM files WHERE project = ?", (project,))
    conn.commit()
