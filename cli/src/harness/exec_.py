"""Run per-project commands declared in harness.yml."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console

from .config import HarnessConfig

console = Console()
err_console = Console(stderr=True, style="bold red")

# Exit codes (aligned with sysexits.h where possible).
EX_OK = 0
EX_USAGE = 64           # bad invocation
EX_UNAVAILABLE = 69     # project path missing
EX_CONFIG = 78          # command not configured in harness.yml — distinct from "failed"

EXIT_NOT_CONFIGURED = EX_CONFIG

# How many log lines to embed in the run record for quick preview.
STDOUT_TAIL_LINES = 50


def classify(exit_code: int) -> str:
    """Map an exit code to a report status."""
    if exit_code == EX_OK:
        return "passed"
    if exit_code == EXIT_NOT_CONFIGURED:
        return "not_configured"
    return "failed"


def _run_record_dir(root: Path) -> Path:
    path = root / ".harness" / "reports" / "runs"
    path.mkdir(parents=True, exist_ok=True)
    if not os.access(path, os.W_OK):
        _fix_reports_ownership(path)
    return path


def _fix_reports_ownership(path: Path) -> None:
    """Attempt to fix ownership of reports dir left behind by a previous
    root-owned container run. Uses sudo if available (container has
    NOPASSWD sudo for the harness user)."""
    import shutil
    uid, gid = os.getuid(), os.getgid()
    sudo = shutil.which("sudo")
    if sudo:
        subprocess.run(
            [sudo, "chown", "-R", f"{uid}:{gid}", str(path.parent)],
            capture_output=True,
        )


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _write_run_record(
    root: Path,
    *,
    target: str,
    project: str,
    command: str | None,
    exit_code: int,
    started_at: str,
    ended_at: str,
    duration_seconds: float,
    log_path: Path | None,
) -> None:
    """Persist a per-run record that `harness report` aggregates."""
    run_dir = _run_record_dir(root)

    stdout_tail = ""
    if log_path and log_path.exists():
        lines = log_path.read_text(errors="replace").splitlines()
        stdout_tail = "\n".join(lines[-STDOUT_TAIL_LINES:])

    record = {
        "target": target,
        "project": project,
        "command": command,
        "exit_code": exit_code,
        "status": classify(exit_code),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": round(duration_seconds, 3),
        "log_path": str(log_path.relative_to(root)) if log_path else None,
        "stdout_tail": stdout_tail,
    }
    # One record per (project, target) — overwrite prior runs.
    out_path = run_dir / f"{project}__{target}.json"
    out_path.write_text(json.dumps(record, indent=2) + "\n")


def _stream_and_capture(cmd: str, cwd: Path, env: dict, log_path: Path) -> int:
    """Run cmd with live output AND capture to log_path. Return exit code."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as log_f:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log_f.write(line)
        return proc.wait()


def run_exec(target: str, project_name: str | None = None) -> int:
    cfg = HarnessConfig.load()
    try:
        project = cfg.project(project_name)
    except (KeyError, ValueError) as exc:
        err_console.print(str(exc))
        return EX_USAGE

    cmd = project.commands.get(target)
    started_at = _iso_now()
    start_ts = time.monotonic()

    if not cmd:
        console.print(
            f"[yellow]{project.name}[/yellow] — no '{target}' command configured. "
            f"[dim](exit {EXIT_NOT_CONFIGURED} = not configured)[/dim]"
        )
        _write_run_record(
            cfg.root,
            target=target, project=project.name, command=None,
            exit_code=EXIT_NOT_CONFIGURED,
            started_at=started_at, ended_at=_iso_now(),
            duration_seconds=time.monotonic() - start_ts,
            log_path=None,
        )
        return EXIT_NOT_CONFIGURED

    project_path = cfg.root / project.path
    if not project_path.exists():
        err_console.print(
            f"Project path {project_path} does not exist. "
            "Did you run `git submodule update --init`?"
        )
        _write_run_record(
            cfg.root,
            target=target, project=project.name, command=cmd,
            exit_code=EX_UNAVAILABLE,
            started_at=started_at, ended_at=_iso_now(),
            duration_seconds=time.monotonic() - start_ts,
            log_path=None,
        )
        return EX_UNAVAILABLE

    console.print(f"[bold]{project.name}[/bold] $ {cmd}  [dim](cwd={project.path})[/dim]")
    log_path = cfg.root / ".harness" / "reports" / "runs" / f"{project.name}__{target}.log"
    exit_code = _stream_and_capture(
        cmd,
        cwd=project_path,
        env={**os.environ, "HARNESS_PROJECT": project.name, "HARNESS_TARGET": target},
        log_path=log_path,
    )
    _write_run_record(
        cfg.root,
        target=target, project=project.name, command=cmd,
        exit_code=exit_code,
        started_at=started_at, ended_at=_iso_now(),
        duration_seconds=time.monotonic() - start_ts,
        log_path=log_path,
    )
    return exit_code
