"""Execute `context.ingest:` blocks from harness.yml.

Each block declares a glob over a submodule's files and a destination
under the harness's `context/upstream/<project>/` tree. This module walks
those blocks and writes derived snapshots with standardized frontmatter,
so agent queries against the context library find the right docs.

Derived snapshots are overwritten on every run (no preserved hand-edits);
that's the design — `context/upstream/` is read-only from the user's
perspective. Edit the source in the submodule, re-run `harness ctx
ingest`, commit the regenerated snapshot.
"""

from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .config import HarnessConfig, Project

# ---------------------------------------------------------------------------
# What counts as a text file (ingested WITH frontmatter) vs a binary
# (ingested as a raw copy). Context files are overwhelmingly Markdown and
# other docs; the binary path is a fallback for things like diagrams that
# legitimately belong next to their docs.
# ---------------------------------------------------------------------------

_TEXT_SUFFIXES: set[str] = {
    "", ".md", ".mdx", ".rst", ".txt", ".yml", ".yaml",
    ".json", ".toml", ".ini", ".cfg", ".adoc", ".tex",
}


@dataclass
class IngestResult:
    written: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (pattern, reason)

    @property
    def count(self) -> int:
        return len(self.written)


def _today() -> str:
    return dt.date.today().isoformat()


def _resolve_placeholders(template: str, project: Project) -> str:
    return (
        template
        .replace("{project.path}", project.path)
        .replace("{project.name}", project.name)
    )


def _pattern_base(pattern: str) -> str:
    """Return the fixed prefix of a glob pattern (up to the first wildcard)."""
    parts = pattern.split("/")
    base_parts: list[str] = []
    for p in parts:
        if any(ch in p for ch in "*?[{"):
            break
        base_parts.append(p)
    return "/".join(base_parts) or "."


def _strip_frontmatter(text: str) -> tuple[Optional[dict], str]:
    """If the text starts with a `---`-delimited YAML frontmatter block,
    return (parsed_frontmatter, body_without_frontmatter). Otherwise
    return (None, text_unchanged)."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    try:
        fm = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None, text
    if not isinstance(fm, dict):
        return None, text
    body = text[end + 4:].lstrip("\n")
    return fm, body


def _build_frontmatter(
    project: Project,
    source_rel: str,
    source_name: str,
    tags: list[str],
) -> dict:
    return {
        "title": f"{project.name} — {source_name}",
        "tags": tags,
        "summary": f"Upstream snapshot of {source_rel} from {project.name}.",
        "updated": _today(),
        "source": "derived",
        "project": project.name,
        "source_path": source_rel,
    }


def _render(frontmatter: dict, body: str) -> str:
    return (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
        + "\n---\n\n"
        + body
    )


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_SUFFIXES


def _ingest_one_block(
    *,
    cfg: HarnessConfig,
    project: Project,
    block: dict,
    result: IngestResult,
) -> None:
    source_template: Optional[str] = block.get("source")
    into_template: Optional[str] = block.get("into")
    tags: list[str] = list(block.get("tags", []) or [])

    if not source_template or not into_template:
        result.skipped.append(
            (str(block), "block missing 'source' or 'into'")
        )
        return

    source_pattern = _resolve_placeholders(source_template, project)
    into_target = _resolve_placeholders(into_template, project)

    matches = sorted(cfg.root.glob(source_pattern))
    if not matches:
        result.skipped.append((source_pattern, "no files matched glob"))
        return

    is_dir_target = into_target.endswith("/")
    base = cfg.root / _pattern_base(source_pattern) if is_dir_target else None

    for src in matches:
        if not src.is_file():
            continue

        if is_dir_target:
            assert base is not None
            try:
                rel = src.relative_to(base)
            except ValueError:
                rel = Path(src.name)
            dest = cfg.root / into_target.rstrip("/") / rel
        else:
            dest = cfg.root / into_target

        dest.parent.mkdir(parents=True, exist_ok=True)

        project_root = cfg.root / project.path
        try:
            source_rel = str(src.relative_to(project_root))
        except ValueError:
            source_rel = src.name

        if _is_text_file(src):
            content = src.read_text(errors="replace")
            _, body = _strip_frontmatter(content)
            fm = _build_frontmatter(project, source_rel, src.name, tags)
            dest.write_text(_render(fm, body))
        else:
            shutil.copy2(src, dest)

        result.written.append(dest)


def run_ingest(root: Optional[Path] = None) -> IngestResult:
    """Execute every `context.ingest:` block for every project."""
    cfg = HarnessConfig.load(root)
    result = IngestResult()

    if not cfg.context_ingest:
        return result

    for project in cfg.projects:
        for block in cfg.context_ingest:
            _ingest_one_block(
                cfg=cfg,
                project=project,
                block=block,
                result=result,
            )

    return result
