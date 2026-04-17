"""Tests for the code structure index: schema, walker, extractors, and API."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from harness.index import db
from harness.index.walker import (
    FileEntry, classify_language, content_hash, diff_against_db, walk_project,
)
from harness.index.extractor import ExtractionResult, extract_file
from harness.index.api import (
    callers_of, file_symbols, import_graph, index_stats,
    lookup_symbol, reindex, search_symbols, type_hierarchy,
)


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

class TestDatabase:
    def test_connect_creates_db(self, tmp_path: Path):
        conn = db.connect(tmp_path)
        assert (tmp_path / ".harness" / "code.db").exists()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "files" in tables
        assert "symbols" in tables
        assert "refs" in tables
        assert "imports" in tables
        assert "type_edges" in tables
        assert "meta" in tables
        conn.close()

    def test_schema_version_is_set(self, tmp_path: Path):
        conn = db.connect(tmp_path)
        assert db.get_meta(conn, "schema_version") == str(db.SCHEMA_VERSION)
        conn.close()

    def test_set_and_get_meta(self, tmp_path: Path):
        conn = db.connect(tmp_path)
        db.set_meta(conn, "test_key", "test_value")
        assert db.get_meta(conn, "test_key") == "test_value"
        conn.close()

    def test_clear_file_cascades(self, tmp_path: Path):
        conn = db.connect(tmp_path)
        conn.execute(
            "INSERT INTO files (project, path, language, size_bytes, content_hash, indexed_at) "
            "VALUES ('p', 'f.py', 'python', 10, 'abc', '2026-01-01')"
        )
        file_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO symbols (file_id, name, kind, line_start, line_end) "
            "VALUES (?, 'foo', 'function', 1, 5)",
            (file_id,),
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 1
        db.clear_file(conn, file_id)
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
        conn.close()


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------

class TestWalker:
    def test_classify_language(self):
        assert classify_language("foo.py") == "python"
        assert classify_language("bar.c") == "c"
        assert classify_language("baz.js") == "javascript"
        assert classify_language("README.md") == "markdown"
        assert classify_language("image.png") is None

    def test_content_hash_is_deterministic(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h1 = content_hash(f)
        h2 = content_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_walk_project_finds_source_files(self, tmp_path: Path):
        _touch(tmp_path / "main.py", "print('hello')")
        _touch(tmp_path / "lib" / "util.py", "def foo(): pass")
        _touch(tmp_path / "README.md", "# Hello")
        _touch(tmp_path / "data.bin", "\x00\x01\x02")
        entries = walk_project(tmp_path)
        paths = {e.path for e in entries}
        assert "main.py" in paths
        assert "lib/util.py" in paths
        assert "README.md" in paths

    def test_walk_project_skips_pycache(self, tmp_path: Path):
        _touch(tmp_path / "main.py", "x = 1")
        _touch(tmp_path / "__pycache__" / "main.cpython-312.pyc", "")
        entries = walk_project(tmp_path)
        paths = {e.path for e in entries}
        assert "main.py" in paths
        assert not any("__pycache__" in p for p in paths)

    def test_walk_project_respects_max_file_size(self, tmp_path: Path):
        _touch(tmp_path / "small.py", "x = 1")
        _touch(tmp_path / "big.py", "x" * 2_000_000)
        entries = walk_project(tmp_path, max_file_size=1_000_000)
        paths = {e.path for e in entries}
        assert "small.py" in paths
        assert "big.py" not in paths

    def test_diff_against_db(self, tmp_path: Path):
        conn = db.connect(tmp_path)
        conn.execute(
            "INSERT INTO files (project, path, language, size_bytes, content_hash, indexed_at) "
            "VALUES ('p', 'old.py', 'python', 10, 'oldhash', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO files (project, path, language, size_bytes, content_hash, indexed_at) "
            "VALUES ('p', 'same.py', 'python', 10, 'samehash', '2026-01-01')"
        )
        conn.commit()

        entries = [
            FileEntry("same.py", tmp_path / "same.py", "python", 10, "samehash"),
            FileEntry("new.py", tmp_path / "new.py", "python", 10, "newhash"),
        ]
        new, changed, deleted = diff_against_db(conn, "p", entries)
        assert len(new) == 1 and new[0].path == "new.py"
        assert len(changed) == 0
        assert len(deleted) == 1
        conn.close()


# ---------------------------------------------------------------------------
# Python extractor
# ---------------------------------------------------------------------------

class TestPythonExtractor:
    def test_extract_functions_and_classes(self):
        source = b"""
def top_level():
    pass

class MyClass:
    def method(self):
        pass

    def _private(self):
        pass
"""
        result = extract_file(source, "test.py", "python")
        names = [s.name for s in result.symbols]
        assert "top_level" in names
        assert "MyClass" in names
        assert "method" in names
        assert "_private" in names

        cls = next(s for s in result.symbols if s.name == "MyClass")
        assert cls.kind == "class"
        method = next(s for s in result.symbols if s.name == "method")
        assert method.kind == "method"
        priv = next(s for s in result.symbols if s.name == "_private")
        assert priv.visibility == "private"

    def test_extract_imports(self):
        source = b"""
import os
import json as j
from pathlib import Path
from typing import Optional, List
from . import sibling
"""
        result = extract_file(source, "test.py", "python")
        modules = [i.module for i in result.imports]
        assert "os" in modules
        assert "json" in modules
        assert "pathlib" in modules
        assert "typing" in modules

        path_import = next(i for i in result.imports if i.module == "pathlib")
        assert path_import.names == ["Path"]

    def test_extract_docstrings(self):
        source = b'''
def documented():
    """This is the docstring."""
    pass
'''
        result = extract_file(source, "test.py", "python")
        sym = next(s for s in result.symbols if s.name == "documented")
        assert sym.docstring == "This is the docstring."

    def test_extract_class_bases(self):
        source = b"""
class Child(Parent, Mixin):
    pass
"""
        result = extract_file(source, "test.py", "python")
        cls = next(s for s in result.symbols if s.name == "Child")
        assert "Parent" in cls.bases
        assert "Mixin" in cls.bases

    def test_extract_calls(self):
        source = b"""
def caller():
    result = some_function(x)
    other_call(y)
"""
        result = extract_file(source, "test.py", "python")
        call_names = {r.name for r in result.refs if r.kind == "call"}
        assert "some_function" in call_names
        assert "other_call" in call_names

    def test_unsupported_language_returns_empty(self):
        result = extract_file(b"hello", "test.txt", "unknown_lang")
        assert result.symbols == []


# ---------------------------------------------------------------------------
# C extractor
# ---------------------------------------------------------------------------

class TestCExtractor:
    def test_extract_functions(self):
        source = b"""
int main(int argc, char **argv) {
    return 0;
}

static void helper(void) {
    /* do stuff */
}
"""
        result = extract_file(source, "test.c", "c")
        names = [s.name for s in result.symbols]
        assert "main" in names
        assert "helper" in names
        helper = next(s for s in result.symbols if s.name == "helper")
        assert helper.visibility == "private"

    def test_extract_structs_and_macros(self):
        source = b"""
#define MAX_SIZE 1024
#define MIN(a, b) ((a) < (b) ? (a) : (b))

struct Point {
    int x;
    int y;
};

typedef unsigned long size_t;
"""
        result = extract_file(source, "test.c", "c")
        names = [s.name for s in result.symbols]
        assert "MAX_SIZE" in names
        assert "MIN" in names
        assert "Point" in names

        macro = next(s for s in result.symbols if s.name == "MIN")
        assert macro.kind == "macro"
        assert "(a, b)" in macro.signature

    def test_extract_includes(self):
        source = b"""
#include <stdio.h>
#include "config.h"
"""
        result = extract_file(source, "test.c", "c")
        modules = [i.module for i in result.imports]
        assert "stdio.h" in modules
        assert "config.h" in modules


# ---------------------------------------------------------------------------
# End-to-end: reindex + query API
# ---------------------------------------------------------------------------

class TestReindexAPI:
    def _make_project(self, tmp_path: Path) -> tuple[Path, Path]:
        harness = tmp_path / "harness"
        project = harness / "projects" / "mylib"
        _touch(harness / "skills" / "CLAUDE.md", "---\ntitle: x\n---\n")
        _touch(harness / "harness.yml", """
projects:
  - name: mylib
    path: projects/mylib
    runtime:
      language: [python]
""")
        _touch(project / "mylib" / "__init__.py", """
from .core import main_func
""")
        _touch(project / "mylib" / "core.py", """
class BaseProcessor:
    def process(self):
        pass

class FastProcessor(BaseProcessor):
    def process(self):
        self._do_fast()

    def _do_fast(self):
        pass

def main_func(data):
    proc = FastProcessor()
    proc.process()
    return helper(data)

def helper(x):
    return x
""")
        _touch(project / "tests" / "test_core.py", """
from mylib.core import main_func, helper

def test_main():
    assert main_func(1) == 1
""")
        return harness, project

    def test_reindex_populates_db(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        summary = reindex(harness, "mylib", project)
        assert summary["total_files"] > 0
        assert summary["total_symbols"] > 0

    def test_search_symbols(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        reindex(harness, "mylib", project)
        results = search_symbols(harness, "main_func")
        assert any(r["name"] == "main_func" for r in results)

    def test_lookup_symbol(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        reindex(harness, "mylib", project)
        results = lookup_symbol(harness, "FastProcessor")
        assert len(results) >= 1
        assert results[0]["kind"] == "class"
        assert "core.py" in results[0]["path"]

    def test_file_symbols(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        reindex(harness, "mylib", project)
        results = file_symbols(harness, "mylib/core.py")
        names = [r["name"] for r in results]
        assert "BaseProcessor" in names
        assert "FastProcessor" in names
        assert "main_func" in names

    def test_callers_of(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        reindex(harness, "mylib", project)
        results = callers_of(harness, "helper")
        assert len(results) >= 1
        paths = [r["path"] for r in results]
        assert any("core.py" in p for p in paths)

    def test_import_graph_reverse(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        reindex(harness, "mylib", project)
        results = import_graph(harness, "mylib.core", reverse=True)
        assert len(results) >= 1

    def test_type_hierarchy(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        reindex(harness, "mylib", project)
        results = type_hierarchy(harness, "FastProcessor")
        names = [r["name"] for r in results]
        assert "FastProcessor" in names

    def test_incremental_reindex(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        s1 = reindex(harness, "mylib", project)
        assert s1["new"] > 0

        s2 = reindex(harness, "mylib", project)
        assert s2["new"] == 0
        assert s2["changed"] == 0
        assert s2["deleted"] == 0

    def test_full_reindex_clears_and_rebuilds(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        reindex(harness, "mylib", project)
        s2 = reindex(harness, "mylib", project, full=True)
        assert s2["new"] > 0
        assert s2["total_files"] > 0

    def test_index_stats(self, tmp_path: Path):
        harness, project = self._make_project(tmp_path)
        reindex(harness, "mylib", project)
        stats = index_stats(harness)
        assert stats["files"] > 0
        assert stats["symbols"] > 0
        assert "mylib" in stats["projects"]
