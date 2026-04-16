"""Run per-project commands declared in harness.yml."""

from __future__ import annotations

import os
import subprocess
import sys

from rich.console import Console

from .config import HarnessConfig

console = Console()
err_console = Console(stderr=True, style="bold red")


def run_exec(target: str, project_name: str | None = None) -> int:
    cfg = HarnessConfig.load()
    try:
        project = cfg.project(project_name)
    except (KeyError, ValueError) as exc:
        err_console.print(str(exc))
        return 2

    cmd = project.commands.get(target)
    if not cmd:
        err_console.print(
            f"Project {project.name!r} has no '{target}' command in harness.yml. "
            "Add it under projects[].commands."
        )
        return 2

    project_path = cfg.root / project.path
    if not project_path.exists():
        err_console.print(
            f"Project path {project_path} does not exist. "
            "Did you run `git submodule update --init`?"
        )
        return 2

    console.print(f"[bold]{project.name}[/bold] $ {cmd}  [dim](cwd={project.path})[/dim]")
    return subprocess.call(
        cmd,
        shell=True,
        cwd=project_path,
        env={**os.environ, "HARNESS_PROJECT": project.name, "HARNESS_TARGET": target},
    )
