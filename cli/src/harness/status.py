"""Print harness state — purpose, projects, init status."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .config import HarnessConfig, HarnessState, find_harness_root

console = Console()


def print_status() -> None:
    root = find_harness_root()
    state = HarnessState.load(root)

    console.print(f"[bold]workspace-harness[/bold]  [dim]{root}[/dim]")
    console.print(f"  status: {state.status}")

    try:
        cfg = HarnessConfig.load(root)
    except FileNotFoundError:
        console.print("  [yellow]harness.yml not found — run the 'initialization' skill.[/yellow]")
        return

    console.print(f"  purpose: {cfg.purpose or '[dim](unset)[/dim]'}")
    console.print(f"  base_image: {cfg.base_image}")

    if not cfg.projects:
        console.print("  [yellow]no projects declared[/yellow]")
        return

    table = Table(title="projects", show_header=True, header_style="bold")
    table.add_column("name")
    table.add_column("path")
    table.add_column("writable")
    table.add_column("languages")
    for p in cfg.projects:
        langs = ", ".join(p.runtime.get("language", []) or [])
        table.add_row(p.name, p.path, "yes" if p.writable else "no", langs or "-")
    console.print(table)
