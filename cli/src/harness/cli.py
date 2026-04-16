"""Click root and command groups for the `harness` CLI."""

from __future__ import annotations

import sys

import click
from rich.console import Console

from . import __version__
from .bootstrap import run_bootstrap
from .ctx import cmd_add, cmd_reindex, cmd_search, cmd_validate
from .detect import detect_project, render_yaml_snippet
from .exec_ import run_exec
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
def ctx_reindex() -> None:
    """Rebuild context/index.json (M2 — currently a stub)."""
    cmd_reindex()


@ctx.command("search")
@click.argument("query")
def ctx_search(query: str) -> None:
    """Search the context library (M2 — currently a stub)."""
    cmd_search(query)


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
