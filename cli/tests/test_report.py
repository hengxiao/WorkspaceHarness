"""End-to-end tests for the report pipeline: exec writes records, report aggregates."""

from __future__ import annotations

import json
import os
from pathlib import Path

from harness.exec_ import EXIT_NOT_CONFIGURED, _run_record_dir, run_exec
from harness.report import run_report


def _write_project_dir(root: Path, name: str) -> None:
    (root / "projects" / name).mkdir(parents=True, exist_ok=True)


def _read_status(root: Path) -> dict:
    return json.loads((root / ".harness" / "reports" / "status.json").read_text())


def _read_report(root: Path) -> str:
    return (root / ".harness" / "reports" / "report.md").read_text()


class TestExecWritesRunRecord:
    def test_successful_run_writes_passed_record(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [{"name": "svc", "path": "projects/svc", "commands": {"test": "true"}}],
        })
        _write_project_dir(harness_root, "svc")
        monkeypatch.chdir(harness_root)

        assert run_exec("test") == 0
        record_path = harness_root / ".harness" / "reports" / "runs" / "svc__test.json"
        record = json.loads(record_path.read_text())
        assert record["status"] == "passed"
        assert record["exit_code"] == 0
        assert record["project"] == "svc"
        assert record["target"] == "test"

    def test_failed_run_writes_failed_record(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [{"name": "svc", "path": "projects/svc", "commands": {"test": "exit 2"}}],
        })
        _write_project_dir(harness_root, "svc")
        monkeypatch.chdir(harness_root)

        assert run_exec("test") == 2
        record = json.loads((harness_root / ".harness" / "reports" / "runs" / "svc__test.json").read_text())
        assert record["status"] == "failed"
        assert record["exit_code"] == 2

    def test_not_configured_run_writes_not_configured_record(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [{"name": "svc", "path": "projects/svc", "commands": {"test": "true"}}],
        })
        _write_project_dir(harness_root, "svc")
        monkeypatch.chdir(harness_root)

        assert run_exec("lint") == EXIT_NOT_CONFIGURED
        record = json.loads((harness_root / ".harness" / "reports" / "runs" / "svc__lint.json").read_text())
        assert record["status"] == "not_configured"
        assert record["command"] is None

    def test_stdout_is_captured_in_log_and_tail(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [{"name": "svc", "path": "projects/svc",
                          "commands": {"test": "echo hello-from-test"}}],
        })
        _write_project_dir(harness_root, "svc")
        monkeypatch.chdir(harness_root)

        run_exec("test")
        log = (harness_root / ".harness" / "reports" / "runs" / "svc__test.log").read_text()
        assert "hello-from-test" in log
        record = json.loads((harness_root / ".harness" / "reports" / "runs" / "svc__test.json").read_text())
        assert "hello-from-test" in record["stdout_tail"]


class TestReportAggregation:
    def _run_all(self, root: Path, commands: dict, write_harness_yml, monkeypatch, targets=("test",)):
        write_harness_yml({
            "projects": [{"name": "svc", "path": "projects/svc", "commands": commands}],
        })
        _write_project_dir(root, "svc")
        monkeypatch.chdir(root)
        for t in targets:
            run_exec(t)

    def test_all_passed_yields_passed_overall(self, harness_root, write_harness_yml, monkeypatch):
        self._run_all(harness_root, {"test": "true", "build": "true"}, write_harness_yml, monkeypatch,
                      targets=("test", "build"))
        assert run_report() == 0
        status = _read_status(harness_root)
        assert status["overall"] == "passed"
        assert status["counts"]["passed"] == 2
        assert status["counts"]["failed"] == 0
        assert "Harness Report" in _read_report(harness_root)

    def test_any_failure_yields_failed_overall(self, harness_root, write_harness_yml, monkeypatch):
        self._run_all(harness_root, {"test": "exit 1", "build": "true"}, write_harness_yml, monkeypatch,
                      targets=("test", "build"))
        assert run_report() == 1
        status = _read_status(harness_root)
        assert status["overall"] == "failed"
        assert status["counts"]["failed"] == 1
        assert status["counts"]["passed"] == 1

    def test_not_configured_does_not_fail_overall(self, harness_root, write_harness_yml, monkeypatch):
        """Missing lint shouldn't flip overall to failed."""
        self._run_all(harness_root, {"test": "true"}, write_harness_yml, monkeypatch,
                      targets=("test", "lint"))
        assert run_report() == 0
        status = _read_status(harness_root)
        assert status["overall"] == "passed"
        assert status["counts"]["not_configured"] == 1
        # Report surfaces it, doesn't hide it
        assert "Not configured" in _read_report(harness_root)

    def test_empty_runs_dir_yields_not_configured_overall(self, harness_root, write_harness_yml, monkeypatch):
        write_harness_yml({"projects": [{"name": "svc", "path": "projects/svc"}]})
        monkeypatch.chdir(harness_root)
        assert run_report() == 0
        status = _read_status(harness_root)
        assert status["overall"] == "not_configured"
        assert "No runs captured" in _read_report(harness_root)

    def test_report_includes_failure_tail(self, harness_root, write_harness_yml, monkeypatch):
        self._run_all(
            harness_root,
            {"test": "echo context-line && echo failing-detail && exit 1"},
            write_harness_yml, monkeypatch, targets=("test",),
        )
        run_report()
        md = _read_report(harness_root)
        assert "## Failures" in md
        assert "failing-detail" in md


class TestReportsOwnership:
    def test_run_record_dir_creates_writable_directory(self, harness_root: Path):
        """_run_record_dir must return a writable directory even when
        created from scratch."""
        d = _run_record_dir(harness_root)
        assert d.is_dir()
        assert os.access(d, os.W_OK)

    def test_run_record_dir_handles_existing_dir(self, harness_root: Path):
        """If .harness/reports/runs/ already exists, _run_record_dir must
        still return it and it must be writable."""
        d = harness_root / ".harness" / "reports" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        result = _run_record_dir(harness_root)
        assert result == d
        assert os.access(result, os.W_OK)
