"""Context-library subcommands: add, validate, reindex, search, symbol, etc."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from .config import HarnessConfig, find_harness_root

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


def cmd_reindex(full: bool = False, project_name: str | None = None) -> dict:
    """Build or update the code structure index."""
    from .index.api import reindex

    root = find_harness_root()
    try:
        cfg = HarnessConfig.load(root)
    except FileNotFoundError:
        console.print("[red]harness.yml not found — cannot determine projects.[/red]")
        return {}

    exclude = (cfg.context_ingest[0].get("exclude", [])
               if cfg.context_ingest else [])

    results = {}
    for proj in cfg.projects:
        if project_name and proj.name != project_name:
            continue
        project_dir = root / proj.path
        if not project_dir.is_dir():
            console.print(f"[yellow]skip {proj.name}:[/yellow] {proj.path} not found")
            continue
        console.print(f"[bold]indexing {proj.name}[/bold] …", end=" ")
        summary = reindex(
            root, proj.name, project_dir, full=full, exclude=exclude,
        )
        results[proj.name] = summary
        console.print(
            f"[green]{summary['total_files']} files, "
            f"{summary['total_symbols']} symbols, "
            f"{summary['total_refs']} refs[/green] "
            f"(+{summary['new']} new, ~{summary['changed']} changed, "
            f"-{summary['deleted']} deleted)"
        )
    return results


def cmd_search(query: str, project: str | None = None, as_json: bool = False) -> None:
    """Search the code index for symbols matching a query."""
    from .index.api import search_symbols

    root = find_harness_root()
    rows = search_symbols(root, query, project=project)
    if as_json:
        console.print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print(f"[yellow]no results for {query!r}[/yellow]")
        return
    table = Table(title=f"search: {query}")
    table.add_column("name")
    table.add_column("kind")
    table.add_column("file")
    table.add_column("line")
    table.add_column("signature")
    for r in rows:
        table.add_row(r["name"], r["kind"], r["path"],
                      str(r["line_start"]), r.get("signature", ""))
    console.print(table)


def cmd_symbol(
    name: str, kind: str | None = None,
    project: str | None = None, as_json: bool = False,
) -> None:
    """Look up a symbol by exact name."""
    from .index.api import lookup_symbol

    root = find_harness_root()
    rows = lookup_symbol(root, name, project=project, kind=kind)
    if as_json:
        console.print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print(f"[yellow]no symbol named {name!r}[/yellow]")
        return
    for r in rows:
        console.print(
            f"[bold]{r['name']}[/bold] [{r['kind']}] "
            f"in [cyan]{r['path']}:{r['line_start']}[/cyan]"
        )
        if r.get("signature"):
            console.print(f"  {r['signature']}")
        if r.get("docstring"):
            console.print(f"  [dim]{r['docstring'][:120]}[/dim]")


def cmd_file(path: str, project: str | None = None, as_json: bool = False) -> None:
    """Show top-level symbols defined in a file."""
    from .index.api import file_symbols

    root = find_harness_root()
    rows = file_symbols(root, path, project=project)
    if as_json:
        console.print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print(f"[yellow]no symbols found in {path}[/yellow]")
        return
    for r in rows:
        vis = f"[dim]{r['visibility']}[/dim] " if r.get("visibility") else ""
        console.print(f"  {vis}[bold]{r['name']}[/bold] [{r['kind']}] L{r['line_start']}")


def cmd_callers(name: str, project: str | None = None, as_json: bool = False) -> None:
    """Show call sites for a function/method."""
    from .index.api import callers_of

    root = find_harness_root()
    rows = callers_of(root, name, project=project)
    if as_json:
        console.print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print(f"[yellow]no callers of {name!r} found[/yellow]")
        return
    for r in rows:
        scope = f" (in {r['scope_name']})" if r.get("scope_name") else ""
        console.print(f"  [cyan]{r['path']}:{r['line']}[/cyan]{scope}")


def cmd_imports(
    module: str, reverse: bool = False,
    project: str | None = None, as_json: bool = False,
) -> None:
    """Show import graph for a file or module."""
    from .index.api import import_graph

    root = find_harness_root()
    rows = import_graph(root, module, project=project, reverse=reverse)
    if as_json:
        console.print(json.dumps(rows, indent=2))
        return
    if not rows:
        label = "importers of" if reverse else "imports from"
        console.print(f"[yellow]no {label} {module!r} found[/yellow]")
        return
    for r in rows:
        names = json.loads(r["names"]) if r.get("names") else None
        names_str = f" ({', '.join(names)})" if names else ""
        console.print(f"  [cyan]{r['path']}:{r['line']}[/cyan] → {r['module']}{names_str}")


def cmd_hierarchy(
    class_name: str, project: str | None = None, as_json: bool = False,
) -> None:
    """Show inheritance hierarchy for a class."""
    from .index.api import type_hierarchy

    root = find_harness_root()
    rows = type_hierarchy(root, class_name, project=project)
    if as_json:
        console.print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print(f"[yellow]no class {class_name!r} found[/yellow]")
        return
    for r in rows:
        indent = "  " * r["depth"]
        console.print(f"{indent}[bold]{r['name']}[/bold] in {r['path']}")


def cmd_query(sql: str, as_json: bool = False) -> None:
    """Execute a raw SQL query against the code index."""
    from .index.api import raw_query

    root = find_harness_root()
    try:
        rows = raw_query(root, sql)
    except Exception as e:
        console.print(f"[red]query error:[/red] {e}")
        return
    if as_json:
        console.print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print("[dim]no results[/dim]")
        return
    for r in rows:
        console.print(dict(r))


def cmd_stats() -> None:
    """Show index statistics."""
    from .index.api import index_stats

    root = find_harness_root()
    try:
        stats = index_stats(root)
    except Exception:
        console.print("[yellow]no code index found — run harness ctx reindex[/yellow]")
        return
    console.print("[bold]Code index stats[/bold]")
    console.print(f"  files:      {stats.get('files', 0)}")
    console.print(f"  symbols:    {stats.get('symbols', 0)}")
    console.print(f"  refs:       {stats.get('refs', 0)}")
    console.print(f"  imports:    {stats.get('imports', 0)}")
    console.print(f"  type_edges: {stats.get('type_edges', 0)}")
    if stats.get("projects"):
        console.print("  projects:")
        for name, count in stats["projects"].items():
            console.print(f"    {name}: {count} files")
    if stats.get("last_indexed_at"):
        console.print(f"  last indexed: {stats['last_indexed_at']}")
