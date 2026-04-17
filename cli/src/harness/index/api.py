"""Public API for the code structure index."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from . import db
from .extractor import ExtractionResult, extract_file
from .walker import FileEntry, diff_against_db, walk_project

# Ensure language extractors are registered on import.
from .extractors import python as _py, c as _c, javascript as _js, java as _java  # noqa: F401


def reindex(
    harness_root: Path,
    project_name: str,
    project_dir: Path,
    *,
    full: bool = False,
    exclude: list[str] | None = None,
    max_file_size: int = 1_048_576,
) -> dict:
    """Build or incrementally update the code index for a project.

    Returns a summary dict with counts of new/changed/deleted/total files.
    """
    conn = db.connect(harness_root)
    try:
        if full:
            db.clear_project(conn, project_name)

        entries = walk_project(
            project_dir, max_file_size=max_file_size, exclude_patterns=exclude,
        )
        new_files, changed_files, deleted_ids = diff_against_db(
            conn, project_name, entries,
        )

        for fid in deleted_ids:
            db.clear_file(conn, fid)

        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

        indexed = 0
        for entry in new_files + changed_files:
            _index_file(conn, project_name, entry, now)
            indexed += 1

        _resolve_type_edges(conn, project_name)

        db.set_meta(conn, "last_indexed_at", now)
        db.set_meta(conn, f"last_indexed_at:{project_name}", now)

        _try_set_git_ref(conn, project_name, project_dir)

        conn.commit()

        total = conn.execute(
            "SELECT COUNT(*) FROM files WHERE project = ?", (project_name,)
        ).fetchone()[0]
        sym_count = conn.execute(
            "SELECT COUNT(*) FROM symbols s JOIN files f ON s.file_id = f.id WHERE f.project = ?",
            (project_name,),
        ).fetchone()[0]
        ref_count = conn.execute(
            "SELECT COUNT(*) FROM refs r JOIN files f ON r.file_id = f.id WHERE f.project = ?",
            (project_name,),
        ).fetchone()[0]

        return {
            "project": project_name,
            "new": len(new_files),
            "changed": len(changed_files),
            "deleted": len(deleted_ids),
            "indexed": indexed,
            "total_files": total,
            "total_symbols": sym_count,
            "total_refs": ref_count,
        }
    finally:
        conn.close()


def _index_file(
    conn: sqlite3.Connection,
    project: str,
    entry: FileEntry,
    now: str,
) -> None:
    """Parse a file and insert its symbols, refs, and imports into the DB."""
    conn.execute(
        "DELETE FROM files WHERE project = ? AND path = ?", (project, entry.path)
    )

    conn.execute(
        "INSERT INTO files (project, path, language, size_bytes, content_hash, indexed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project, entry.path, entry.language, entry.size, entry.content_hash, now),
    )
    file_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    try:
        source = entry.abs_path.read_bytes()
    except OSError:
        return

    result = extract_file(source, entry.path, entry.language or "")
    if not result.symbols and not result.refs and not result.imports:
        return

    sym_id_map: dict[int, int] = {}
    for idx, sym in enumerate(result.symbols):
        parent_db_id = sym_id_map.get(sym.parent_idx) if sym.parent_idx is not None else None
        conn.execute(
            "INSERT INTO symbols "
            "(file_id, name, kind, line_start, line_end, col_start, col_end, "
            " parent_id, signature, docstring, visibility, is_export) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, sym.name, sym.kind, sym.line_start, sym.line_end,
             sym.col_start, sym.col_end, parent_db_id,
             sym.signature, sym.docstring, sym.visibility, sym.is_export),
        )
        sym_id_map[idx] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for base in sym.bases:
            child_db_id = sym_id_map[idx]
            conn.execute(
                "INSERT INTO type_edges (child_id, parent_name, kind) VALUES (?, ?, ?)",
                (child_db_id, base, "inherits"),
            )

    for ref in result.refs:
        scope_db_id = sym_id_map.get(ref.scope_idx) if ref.scope_idx is not None else None
        conn.execute(
            "INSERT INTO refs (file_id, name, kind, line, col, scope_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, ref.name, ref.kind, ref.line, ref.col, scope_db_id),
        )

    for imp in result.imports:
        conn.execute(
            "INSERT INTO imports (file_id, module, names, alias, line, is_reexport) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, imp.module, json.dumps(imp.names) if imp.names else None,
             imp.alias, imp.line, imp.is_reexport),
        )


def _resolve_type_edges(conn: sqlite3.Connection, project: str) -> None:
    """Try to resolve type_edges.parent_name → parent_id for known symbols."""
    conn.execute("""
        UPDATE type_edges SET parent_id = (
            SELECT s.id FROM symbols s
            JOIN files f ON s.file_id = f.id
            WHERE f.project = ? AND s.name = type_edges.parent_name AND s.kind = 'class'
            LIMIT 1
        )
        WHERE parent_id IS NULL
          AND child_id IN (
            SELECT s.id FROM symbols s
            JOIN files f ON s.file_id = f.id
            WHERE f.project = ?
          )
    """, (project, project))


def _try_set_git_ref(
    conn: sqlite3.Connection, project: str, project_dir: Path,
) -> None:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_dir, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            db.set_meta(conn, f"last_indexed_ref:{project}", ref)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def search_symbols(
    harness_root: Path,
    query: str,
    *,
    project: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> list[dict]:
    conn = db.connect(harness_root)
    try:
        sql = """
            SELECT s.name, s.kind, s.signature, s.docstring,
                   s.line_start, s.line_end, s.visibility,
                   f.path, f.project
            FROM symbols_fts fts
            JOIN symbols s ON s.id = fts.rowid
            JOIN files f ON s.file_id = f.id
            WHERE symbols_fts MATCH ?
        """
        params: list = [query]
        if project:
            sql += " AND f.project = ?"
            params.append(project)
        if kind:
            sql += " AND s.kind = ?"
            params.append(kind)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def lookup_symbol(
    harness_root: Path,
    name: str,
    *,
    project: str | None = None,
    kind: str | None = None,
) -> list[dict]:
    conn = db.connect(harness_root)
    try:
        sql = """
            SELECT s.name, s.kind, s.signature, s.docstring,
                   s.line_start, s.line_end, s.visibility, s.is_export,
                   f.path, f.project, f.language
            FROM symbols s
            JOIN files f ON s.file_id = f.id
            WHERE s.name = ?
        """
        params: list = [name]
        if project:
            sql += " AND f.project = ?"
            params.append(project)
        if kind:
            sql += " AND s.kind = ?"
            params.append(kind)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def file_symbols(
    harness_root: Path, path: str, *, project: str | None = None,
) -> list[dict]:
    conn = db.connect(harness_root)
    try:
        sql = """
            SELECT s.name, s.kind, s.signature, s.line_start, s.line_end,
                   s.visibility, s.docstring
            FROM symbols s
            JOIN files f ON s.file_id = f.id
            WHERE f.path = ?
        """
        params: list = [path]
        if project:
            sql += " AND f.project = ?"
            params.append(project)
        sql += " AND s.parent_id IS NULL ORDER BY s.line_start"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def callers_of(
    harness_root: Path, name: str, *, project: str | None = None,
) -> list[dict]:
    conn = db.connect(harness_root)
    try:
        sql = """
            SELECT f.path, r.line, r.kind,
                   scope.name AS scope_name, scope.kind AS scope_kind,
                   f.project
            FROM refs r
            JOIN files f ON r.file_id = f.id
            LEFT JOIN symbols scope ON r.scope_id = scope.id
            WHERE r.name = ?
        """
        params: list = [name]
        if project:
            sql += " AND f.project = ?"
            params.append(project)
        sql += " ORDER BY f.path, r.line"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def import_graph(
    harness_root: Path,
    module: str,
    *,
    project: str | None = None,
    reverse: bool = False,
) -> list[dict]:
    conn = db.connect(harness_root)
    try:
        if reverse:
            sql = """
                SELECT f.path, i.module, i.names, i.line, f.project
                FROM imports i
                JOIN files f ON i.file_id = f.id
                WHERE i.module LIKE ?
            """
            params: list = [f"%{module}%"]
        else:
            sql = """
                SELECT f.path, i.module, i.names, i.line, f.project
                FROM imports i
                JOIN files f ON i.file_id = f.id
                WHERE f.path LIKE ?
            """
            params = [f"%{module}%"]
        if project:
            sql += " AND f.project = ?"
            params.append(project)
        sql += " ORDER BY f.path, i.line"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def type_hierarchy(
    harness_root: Path,
    class_name: str,
    *,
    project: str | None = None,
    depth: int = 10,
) -> list[dict]:
    conn = db.connect(harness_root)
    try:
        sql = """
            WITH RECURSIVE chain(id, name, kind, path, depth) AS (
                SELECT s.id, s.name, s.kind, f.path, 0
                FROM symbols s
                JOIN files f ON s.file_id = f.id
                WHERE s.name = ? AND s.kind = 'class'
                UNION ALL
                SELECT s2.id, s2.name, s2.kind, f2.path, c.depth + 1
                FROM chain c
                JOIN type_edges te ON te.child_id = c.id
                JOIN symbols s2 ON s2.id = te.parent_id
                JOIN files f2 ON s2.file_id = f2.id
                WHERE c.depth < ?
            )
            SELECT * FROM chain ORDER BY depth
        """
        params: list = [class_name, depth]
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def raw_query(harness_root: Path, sql: str) -> list[dict]:
    conn = db.connect(harness_root)
    try:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def index_stats(harness_root: Path) -> dict:
    conn = db.connect(harness_root)
    try:
        stats = {}
        for table in ("files", "symbols", "refs", "imports", "type_edges"):
            stats[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        projects = conn.execute(
            "SELECT project, COUNT(*) as file_count FROM files GROUP BY project"
        ).fetchall()
        stats["projects"] = {r["project"]: r["file_count"] for r in projects}

        stats["last_indexed_at"] = db.get_meta(conn, "last_indexed_at")
        return stats
    finally:
        conn.close()
