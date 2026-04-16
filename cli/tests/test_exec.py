"""Tests for harness.exec_ — distinguished exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.exec_ import (
    EX_CONFIG,
    EX_UNAVAILABLE,
    EX_USAGE,
    EXIT_NOT_CONFIGURED,
    run_exec,
)


def _write_project_dir(root: Path, name: str) -> None:
    (root / "projects" / name).mkdir(parents=True, exist_ok=True)


class TestExecExitCodes:
    def test_not_configured_returns_ex_config(self, harness_root: Path, write_harness_yml, monkeypatch):
        """Omitted command → EXIT_NOT_CONFIGURED (78), not silent-pass."""
        write_harness_yml({
            "projects": [{
                "name": "svc",
                "path": "projects/svc",
                "commands": {"test": "true"},  # no 'lint'
            }],
        })
        _write_project_dir(harness_root, "svc")
        monkeypatch.chdir(harness_root)

        assert run_exec("lint") == EXIT_NOT_CONFIGURED
        assert EXIT_NOT_CONFIGURED == EX_CONFIG == 78

    def test_missing_project_path_returns_ex_unavailable(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [{
                "name": "svc",
                "path": "projects/svc",  # directory doesn't exist
                "commands": {"test": "true"},
            }],
        })
        monkeypatch.chdir(harness_root)

        assert run_exec("test") == EX_UNAVAILABLE

    def test_ambiguous_project_returns_ex_usage(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [
                {"name": "a", "path": "projects/a", "commands": {"test": "true"}},
                {"name": "b", "path": "projects/b", "commands": {"test": "true"}},
            ],
        })
        _write_project_dir(harness_root, "a")
        _write_project_dir(harness_root, "b")
        monkeypatch.chdir(harness_root)

        assert run_exec("test") == EX_USAGE  # multiple projects, no --project

    def test_configured_command_runs(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [{"name": "svc", "path": "projects/svc", "commands": {"test": "true"}}],
        })
        _write_project_dir(harness_root, "svc")
        monkeypatch.chdir(harness_root)

        assert run_exec("test") == 0

    def test_failing_command_returns_its_exit_code(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [{"name": "svc", "path": "projects/svc", "commands": {"test": "exit 3"}}],
        })
        _write_project_dir(harness_root, "svc")
        monkeypatch.chdir(harness_root)

        assert run_exec("test") == 3
