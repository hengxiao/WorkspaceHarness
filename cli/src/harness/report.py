"""Aggregate .harness/reports/runs/*.json into report.md and status.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

from .config import find_harness_root

console = Console()

REPORT_MD = "report.md"
STATUS_JSON = "status.json"

# Targets reported on, in display order.
REPORT_TARGETS = ["deps", "build", "test", "lint"]


@dataclass
class Run:
    target: str
    project: str
    command: str | None
    exit_code: int
    status: str
    duration_seconds: float
    stdout_tail: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Run":
        return cls(
            target=d["target"],
            project=d["project"],
            command=d.get("command"),
            exit_code=d["exit_code"],
            status=d["status"],
            duration_seconds=d.get("duration_seconds", 0.0),
            stdout_tail=d.get("stdout_tail", ""),
        )


def _load_runs(root: Path) -> list[Run]:
    runs_dir = root / ".harness" / "reports" / "runs"
    if not runs_dir.exists():
        return []
    return [Run.from_dict(json.loads(p.read_text())) for p in sorted(runs_dir.glob("*.json"))]


def _status_icon(status: str) -> str:
    return {"passed": "✓", "failed": "✗", "not_configured": "–"}.get(status, "?")


def _overall_status(runs: list[Run]) -> str:
    """Overall status: failed > passed > not_configured. Empty → not_configured."""
    if any(r.status == "failed" for r in runs):
        return "failed"
    if any(r.status == "passed" for r in runs):
        return "passed"
    return "not_configured"


def _render_markdown(runs: list[Run], overall: str) -> str:
    lines: list[str] = []
    icon = _status_icon(overall)
    lines.append(f"# Harness Report — {icon} {overall}")
    lines.append("")

    if not runs:
        lines.append("_No runs captured. Run `make deps`, `make build`, or `make test` first._")
        return "\n".join(lines) + "\n"

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Project | Target | Status | Duration | Exit |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in runs:
        lines.append(
            f"| {r.project} | {r.target} | {_status_icon(r.status)} {r.status} | "
            f"{r.duration_seconds:.2f}s | {r.exit_code} |"
        )
    lines.append("")

    # Failures — show tail of each failing run
    failures = [r for r in runs if r.status == "failed"]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for r in failures:
            lines.append(f"### {r.project} / {r.target} (exit {r.exit_code})")
            lines.append("")
            if r.command:
                lines.append(f"`{r.command}`")
                lines.append("")
            if r.stdout_tail:
                lines.append("<details><summary>output (tail)</summary>")
                lines.append("")
                lines.append("```")
                lines.append(r.stdout_tail)
                lines.append("```")
                lines.append("")
                lines.append("</details>")
                lines.append("")

    # Not configured — surface as an advisory, not a silent gap.
    not_configured = [r for r in runs if r.status == "not_configured"]
    if not_configured:
        lines.append("## Not configured")
        lines.append("")
        for r in not_configured:
            lines.append(f"- `{r.project}` has no `{r.target}` command in `harness.yml`")
        lines.append("")

    return "\n".join(lines) + "\n"


def _status_summary(runs: list[Run], overall: str) -> dict[str, Any]:
    by_status: dict[str, int] = {"passed": 0, "failed": 0, "not_configured": 0}
    for r in runs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    return {
        "overall": overall,
        "counts": by_status,
        "runs": [
            {
                "project": r.project,
                "target": r.target,
                "status": r.status,
                "exit_code": r.exit_code,
                "duration_seconds": r.duration_seconds,
            }
            for r in runs
        ],
    }


def run_report() -> int:
    """Aggregate run records. Returns 0 if overall==passed/not_configured, 1 if failed."""
    root = find_harness_root()
    reports_dir = root / ".harness" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    runs = _load_runs(root)
    overall = _overall_status(runs)

    (reports_dir / REPORT_MD).write_text(_render_markdown(runs, overall))
    (reports_dir / STATUS_JSON).write_text(
        json.dumps(_status_summary(runs, overall), indent=2) + "\n"
    )

    console.print(f"[bold]report[/bold] — overall: {_status_icon(overall)} {overall}")
    console.print(f"  wrote {reports_dir / REPORT_MD}")
    console.print(f"  wrote {reports_dir / STATUS_JSON}")

    return 0 if overall != "failed" else 1
