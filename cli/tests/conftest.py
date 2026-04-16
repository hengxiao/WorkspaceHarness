"""Shared fixtures for CLI tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def harness_root(tmp_path: Path) -> Path:
    """A minimal harness root: skills/CLAUDE.md marker + harness.yml."""
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "CLAUDE.md").write_text("placeholder\n")
    return tmp_path


@pytest.fixture
def write_harness_yml(harness_root: Path):
    """Helper that writes a harness.yml under the fixture root."""

    def _write(config: dict) -> Path:
        path = harness_root / "harness.yml"
        path.write_text(yaml.safe_dump(config))
        return path

    return _write
