"""Click root and command groups for the `harness` CLI."""

from __future__ import annotations

import sys

import click
from rich.console import Console

from . import __version__
from .bootstrap import run_bootstrap
from .config import find_harness_root
from .ctx import (
    cmd_add, cmd_callers, cmd_file, cmd_hierarchy, cmd_imports,
    cmd_query, cmd_reindex, cmd_search, cmd_stats, cmd_symbol, cmd_validate,
)
from .detect import detect_project, render_yaml_snippet
from .exec_ import run_exec
from .ingest import run_ingest
from .policy import check_command, check_staged
from .report import run_report
from .status import print_status

console = Console()
err_console = Console(stderr=True, style="bold red")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="harness")
def main() -> None:
    """Workspace Harness CLI."""


# --------------------------------------------------------------------------- #
# bootstrap
# --------------------------------------------------------------------------- #
@main.command()
@click.option("--force", is_flag=True, help="Overwrite hand-edited HARNESS:KEEP blocks.")
def bootstrap(force: bool) -> None:
    """Regenerate env/Dockerfile and env/docker-compose.yml from harness.yml."""
    try:
        written = run_bootstrap(force=force)
    except FileNotFoundError as exc:
        err_console.print(str(exc))
        sys.exit(2)
    for path in written:
        console.print(f"  [green]wrote[/green] {path}")
    console.print(f"[bold]bootstrap[/bold] complete — {len(written)} file(s) regenerated.")


# --------------------------------------------------------------------------- #
# context library
# --------------------------------------------------------------------------- #
@main.group()
def ctx() -> None:
    """Context library operations."""


@ctx.command("add")
@click.argument("path", type=click.Path(dir_okay=False))
@click.option("--title", required=True, help="Document title.")
@click.option("--tags", default="", help="Comma-separated tags.")
@click.option("--source", default="internal", type=click.Choice(["internal", "upstream", "generated"]))
def ctx_add(path: str, title: str, tags: str, source: str) -> None:
    """Scaffold a new context document with frontmatter."""
    cmd_add(path=path, title=title, tags=[t.strip() for t in tags.split(",") if t.strip()], source=source)


@ctx.command("validate")
def ctx_validate() -> None:
    """Validate every context/ doc has the required frontmatter."""
    errors = cmd_validate()
    if errors:
        for e in errors:
            err_console.print(e)
        sys.exit(1)
    console.print("[green]ok[/green] — all context/ docs have valid frontmatter.")


@ctx.command("reindex")
@click.option("--full", is_flag=True, help="Full rebuild (ignore incremental state).")
@click.option("--project", default=None, help="Only reindex this project.")
def ctx_reindex(full: bool, project: str | None) -> None:
    """Build or update the code structure index (SQLite FTS5)."""
    cmd_reindex(full=full, project_name=project)


@ctx.command("ingest")
def ctx_ingest() -> None:
    """Ingest upstream snapshots declared in context.ingest: from harness.yml."""
    result = run_ingest()
    root = find_harness_root()
    for dest in result.written:
        console.print(f"  [green]wrote[/green] {dest.relative_to(root)}")
    for pattern, reason in result.skipped:
        console.print(f"  [yellow]skip[/yellow] {pattern} ({reason})")
    console.print(f"[bold]ingest[/bold] — {result.count} file(s) written")


@ctx.command("search")
@click.argument("query")
@click.option("--project", default=None, help="Limit to this project.")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def ctx_search(query: str, project: str | None, as_json: bool) -> None:
    """Search the code index for symbols matching QUERY."""
    cmd_search(query, project=project, as_json=as_json)


@ctx.command("symbol")
@click.argument("name")
@click.option("--kind", default=None, help="Filter by kind (function, class, method, ...).")
@click.option("--project", default=None, help="Limit to this project.")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def ctx_symbol(name: str, kind: str | None, project: str | None, as_json: bool) -> None:
    """Look up a symbol by exact name."""
    cmd_symbol(name, kind=kind, project=project, as_json=as_json)


@ctx.command("file")
@click.argument("path")
@click.option("--project", default=None)
@click.option("--json", "as_json", is_flag=True)
def ctx_file(path: str, project: str | None, as_json: bool) -> None:
    """Show top-level symbols defined in a file."""
    cmd_file(path, project=project, as_json=as_json)


@ctx.command("callers")
@click.argument("name")
@click.option("--project", default=None)
@click.option("--json", "as_json", is_flag=True)
def ctx_callers(name: str, project: str | None, as_json: bool) -> None:
    """Show call sites for a function/method."""
    cmd_callers(name, project=project, as_json=as_json)


@ctx.command("imports")
@click.argument("module")
@click.option("--reverse", is_flag=True, help="Show files that import this module.")
@click.option("--project", default=None)
@click.option("--json", "as_json", is_flag=True)
def ctx_imports(module: str, reverse: bool, project: str | None, as_json: bool) -> None:
    """Show import graph for a file or module."""
    cmd_imports(module, reverse=reverse, project=project, as_json=as_json)


@ctx.command("hierarchy")
@click.argument("class_name")
@click.option("--project", default=None)
@click.option("--json", "as_json", is_flag=True)
def ctx_hierarchy(class_name: str, project: str | None, as_json: bool) -> None:
    """Show inheritance hierarchy for a class."""
    cmd_hierarchy(class_name, project=project, as_json=as_json)


@ctx.command("query")
@click.argument("sql")
@click.option("--json", "as_json", is_flag=True)
def ctx_query(sql: str, as_json: bool) -> None:
    """Execute a raw SQL query against the code index."""
    cmd_query(sql, as_json=as_json)


@ctx.command("stats")
def ctx_stats() -> None:
    """Show code index statistics."""
    cmd_stats()


# --------------------------------------------------------------------------- #
# policy
# --------------------------------------------------------------------------- #
@main.group()
def policy() -> None:
    """Agent policy enforcement."""


@policy.command("check")
@click.argument("command", required=False)
@click.option("--staged", is_flag=True, help="Check the set of staged files instead of a command.")
def policy_check(command: str | None, staged: bool) -> None:
    """Check a command (or staged paths) against agent/policies.yaml."""
    if staged:
        violations = check_staged()
    elif command:
        violations = check_command(command)
    else:
        err_console.print("Pass a COMMAND, or use --staged.")
        sys.exit(2)
    if violations:
        for v in violations:
            err_console.print(f"DENY: {v}")
        sys.exit(1)
    console.print("[green]allow[/green]")


# --------------------------------------------------------------------------- #
# exec
# --------------------------------------------------------------------------- #
@main.command()
@click.argument("target", type=click.Choice(["deps", "build", "test", "lint", "run"]))
@click.option("--project", default=None, help="Project name (required if multiple).")
def exec(target: str, project: str | None) -> None:
    """Run a project command (deps/build/test/lint/run) from harness.yml."""
    sys.exit(run_exec(target=target, project_name=project))


# --------------------------------------------------------------------------- #
# report / status
# --------------------------------------------------------------------------- #
@main.command()
def report() -> None:
    """Aggregate .harness/reports/runs/ into report.md and status.json."""
    sys.exit(run_report())


@main.command()
def status() -> None:
    """Print harness state."""
    print_status()


# --------------------------------------------------------------------------- #
# init helpers
# --------------------------------------------------------------------------- #
@main.group()
def init() -> None:
    """Initialization helpers."""


@init.command("detect")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--name", default=None, help="Project name (defaults to directory basename).")
@click.option("--project-path", default=None,
              help="Value to emit for `path:` in the snippet (defaults to `projects/<name>`).")
def init_detect(path: str, name: str | None, project_path: str | None) -> None:
    """Detect a project's toolchain and emit a harness.yml projects[] snippet.

    PATH is an already-cloned directory (typically projects/<name> inside a
    harness). The snippet is printed to stdout so the user or an agent can
    review and paste it into harness.yml.
    """
    from pathlib import Path as _Path
    result = detect_project(_Path(path), name=name)
    snippet = render_yaml_snippet(result, project_path=project_path)
    click.echo(snippet, nl=False)


if __name__ == "__main__":
    main()
