"""Context-library subcommands: add, validate, reindex (stub), search (stub)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml
from rich.console import Console

from .config import find_harness_root

console = Console()

REQUIRED_FRONTMATTER = {"title", "tags", "summary", "updated"}


def _today() -> str:
    return dt.date.today().isoformat()


def cmd_add(path: str, title: str, tags: list[str], source: str) -> None:
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"{target} already exists; refusing to overwrite.")
    target.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "title": title,
        "tags": tags,
        "summary": "TODO — one-paragraph TL;DR",
        "updated": _today(),
        "source": source,
    }
    body = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False).strip()
        + "\n---\n\n"
        + f"# {title}\n\n"
        + "TODO — write the document body.\n"
    )
    target.write_text(body)
    console.print(f"[green]created[/green] {target}")


def _parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    block = text[4:end]
    try:
        data = yaml.safe_load(block) or {}
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def cmd_validate() -> list[str]:
    root = find_harness_root()
    ctx_root = root / "context"
    errors: list[str] = []
    if not ctx_root.exists():
        return ["context/ does not exist"]
    for md in ctx_root.rglob("*.md"):
        rel = md.relative_to(root)
        # README.md files are descriptive layout docs, exempt from frontmatter rule.
        if md.name == "README.md":
            continue
        text = md.read_text()
        fm = _parse_frontmatter(text)
        if fm is None:
            errors.append(f"{rel}: missing or unparseable frontmatter")
            continue
        missing = REQUIRED_FRONTMATTER - set(fm.keys())
        if missing:
            errors.append(f"{rel}: missing keys {sorted(missing)}")
    return errors


def cmd_reindex() -> None:
    console.print(
        "[yellow]ctx reindex[/yellow] is a stub (M2). "
        "Will rebuild context/index.json once the FTS5 backend lands."
    )


def cmd_search(query: str) -> None:
    console.print(
        f"[yellow]ctx search {query!r}[/yellow] is a stub (M2). "
        "Will query the FTS5 index once it exists."
    )
