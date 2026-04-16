"""Aggregate .harness/reports/ into report.md (M4 — currently a stub)."""

from __future__ import annotations

from rich.console import Console

console = Console()


def run_report() -> None:
    console.print(
        "[yellow]harness report[/yellow] is a stub (M4). "
        "Will aggregate .harness/reports/{test,lint}/ into report.md "
        "and write .harness/reports/status.json."
    )
