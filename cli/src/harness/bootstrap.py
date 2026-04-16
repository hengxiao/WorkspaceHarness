"""Render env/Dockerfile and env/docker-compose.yml from harness.yml."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import HarnessConfig

KEEP_MARKER_BEGIN = "# HARNESS:KEEP:BEGIN"
KEEP_MARKER_END = "# HARNESS:KEEP:END"

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def _preserve_keep_blocks(existing: str, generated: str) -> str:
    """Carry hand-edited KEEP blocks from `existing` into `generated`.

    Anything between matching KEEP:BEGIN/KEEP:END markers in `existing`
    overrides the same-named block in `generated`. Block names match by line.
    """
    if KEEP_MARKER_BEGIN not in existing:
        return generated
    out_lines = generated.splitlines(keepends=True)
    existing_blocks = _extract_keep_blocks(existing)
    if not existing_blocks:
        return generated
    rendered: list[str] = []
    skipping = False
    current_name: str | None = None
    for line in out_lines:
        if KEEP_MARKER_BEGIN in line and not skipping:
            current_name = line.split(KEEP_MARKER_BEGIN, 1)[1].strip()
            rendered.append(line)
            if current_name in existing_blocks:
                rendered.extend(existing_blocks[current_name])
                skipping = True
            continue
        if KEEP_MARKER_END in line and skipping:
            rendered.append(line)
            skipping = False
            current_name = None
            continue
        if not skipping:
            rendered.append(line)
    return "".join(rendered)


def _extract_keep_blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current_name: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if KEEP_MARKER_BEGIN in line:
            current_name = line.split(KEEP_MARKER_BEGIN, 1)[1].strip()
            current_lines = []
        elif KEEP_MARKER_END in line and current_name is not None:
            blocks[current_name] = current_lines
            current_name = None
        elif current_name is not None:
            current_lines.append(line)
    return blocks


def _render(template_name: str, context: dict) -> str:
    return _template_env().get_template(template_name).render(**context)


def run_bootstrap(force: bool = False) -> list[Path]:
    """Render env/Dockerfile and env/docker-compose.yml. Returns paths written."""
    cfg = HarnessConfig.load()
    env_dir = cfg.root / "env"
    env_dir.mkdir(parents=True, exist_ok=True)

    context = {
        "base_image": cfg.base_image,
        "projects": [_project_template_view(p) for p in cfg.projects],
        "services": cfg.services,
    }

    written: list[Path] = []
    for template_name, out_name in [
        ("Dockerfile.j2", "Dockerfile"),
        ("docker-compose.yml.j2", "docker-compose.yml"),
    ]:
        generated = _render(template_name, context)
        target = env_dir / out_name
        if target.exists() and not force:
            generated = _preserve_keep_blocks(target.read_text(), generated)
        target.write_text(generated)
        written.append(target)
    return written


def _project_template_view(project) -> dict:
    """Shape a Project for use in Jinja templates."""
    return {
        "name": project.name,
        "path": project.path,
        "runtime": project.runtime or {},
        "languages": (project.runtime.get("language") or []) if project.runtime else [],
    }
