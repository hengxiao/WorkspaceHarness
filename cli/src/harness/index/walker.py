"""File discovery, hashing, and incremental diff for the code index."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

LANG_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyx": "python",
    ".pxd": "python",
    ".pyi": "python",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".ex": "elixir",
    ".exs": "elixir",
    ".php": "php",
    ".el": "elisp",
    ".sh": "bash",
    ".bash": "bash",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".sql": "sql",
    ".md": "markdown",
    ".r": "r",
    ".R": "r",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".swift": "swift",
    ".m": "objc",
    ".mm": "objc",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".scala": "scala",
    ".zig": "zig",
    ".nim": "nim",
    ".v": "v",
    ".dart": "dart",
    ".jl": "julia",
}

SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".tox", ".venv", "venv",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
    ".eggs", "*.egg-info", ".hg", ".svn", "vendor",
})

DEFAULT_MAX_FILE_SIZE = 1_048_576  # 1 MB


@dataclass
class FileEntry:
    path: str           # relative to project root
    abs_path: Path
    language: str | None
    size: int
    content_hash: str


def classify_language(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return LANG_EXTENSIONS.get(suffix)


def content_hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _git_ls_files(project_dir: Path) -> list[str] | None:
    """Use git to list tracked files (respects .gitignore)."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=project_dir, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.splitlines() if f]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _should_skip_dir(name: str) -> bool:
    if name in SKIP_DIRS:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def walk_project(
    project_dir: Path,
    *,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    exclude_patterns: list[str] | None = None,
) -> list[FileEntry]:
    """Discover indexable files in a project directory."""
    project_dir = project_dir.resolve()
    exclude = set(exclude_patterns or [])

    git_files = _git_ls_files(project_dir)
    if git_files is not None:
        return _entries_from_list(project_dir, git_files, max_file_size, exclude)
    return _entries_from_walk(project_dir, max_file_size, exclude)


def _matches_exclude(rel_path: str, exclude: set[str]) -> bool:
    from fnmatch import fnmatch
    for pat in exclude:
        if fnmatch(rel_path, pat):
            return True
    return False


def _entries_from_list(
    root: Path, paths: list[str], max_size: int, exclude: set[str],
) -> list[FileEntry]:
    entries = []
    for rel in paths:
        if _matches_exclude(rel, exclude):
            continue
        parts = Path(rel).parts
        if any(_should_skip_dir(p) for p in parts[:-1]):
            continue
        abs_path = root / rel
        if not abs_path.is_file():
            continue
        lang = classify_language(rel)
        if lang is None:
            continue
        try:
            size = abs_path.stat().st_size
        except OSError:
            continue
        if size > max_size or size == 0:
            continue
        entries.append(FileEntry(
            path=rel, abs_path=abs_path, language=lang,
            size=size, content_hash=content_hash(abs_path),
        ))
    return entries


def _entries_from_walk(
    root: Path, max_size: int, exclude: set[str],
) -> list[FileEntry]:
    entries = []
    for child in sorted(root.rglob("*")):
        if not child.is_file():
            continue
        rel = str(child.relative_to(root))
        parts = Path(rel).parts
        if any(_should_skip_dir(p) for p in parts[:-1]):
            continue
        if _matches_exclude(rel, exclude):
            continue
        lang = classify_language(rel)
        if lang is None:
            continue
        try:
            size = child.stat().st_size
        except OSError:
            continue
        if size > max_size or size == 0:
            continue
        entries.append(FileEntry(
            path=rel, abs_path=child, language=lang,
            size=size, content_hash=content_hash(child),
        ))
    return entries


def diff_against_db(
    conn, project: str, entries: list[FileEntry],
) -> tuple[list[FileEntry], list[FileEntry], list[int]]:
    """Compare discovered files against the DB.

    Returns (new_files, changed_files, deleted_file_ids).
    """
    db_files: dict[str, tuple[int, str]] = {}
    for row in conn.execute(
        "SELECT id, path, content_hash FROM files WHERE project = ?", (project,)
    ):
        db_files[row["path"]] = (row["id"], row["content_hash"])

    entry_paths = {e.path for e in entries}
    new = []
    changed = []
    for entry in entries:
        if entry.path not in db_files:
            new.append(entry)
        else:
            db_id, db_hash = db_files[entry.path]
            if db_hash != entry.content_hash:
                changed.append(entry)

    deleted_ids = [
        fid for path, (fid, _) in db_files.items() if path not in entry_paths
    ]
    return new, changed, deleted_ids
