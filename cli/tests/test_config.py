"""Tests for harness.config — language normalization, runtime blocks, loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.config import (
    DEFAULT_RUNTIME_BLOCKS,
    HarnessConfig,
    HarnessState,
    Project,
    find_harness_root,
    normalize_language,
    normalize_languages,
)


# --------------------------------------------------------------------------- #
# Language normalization
# --------------------------------------------------------------------------- #
class TestLanguageNormalization:
    def test_known_aliases_are_canonicalized(self):
        assert normalize_language("javascript") == "node"
        assert normalize_language("js") == "node"
        assert normalize_language("typescript") == "node"
        assert normalize_language("ts") == "node"
        assert normalize_language("py") == "python"
        assert normalize_language("golang") == "go"
        assert normalize_language("rs") == "rust"

    def test_canonical_names_are_unchanged(self):
        for lang in ["node", "python", "go", "rust", "java", "ruby"]:
            assert normalize_language(lang) == lang

    def test_unknown_language_passes_through_lowercased(self):
        assert normalize_language("C") == "c"
        assert normalize_language("Elixir") == "elixir"

    def test_case_insensitive(self):
        assert normalize_language("JavaScript") == "node"
        assert normalize_language("PYTHON") == "python"

    def test_list_dedupes_preserving_order(self):
        assert normalize_languages(["javascript", "js", "python"]) == ["node", "python"]
        assert normalize_languages(["node", "ts", "js"]) == ["node"]

    def test_empty_list(self):
        assert normalize_languages([]) == []


# --------------------------------------------------------------------------- #
# Runtime blocks
# --------------------------------------------------------------------------- #
class TestRuntimeBlocks:
    def test_defaults_cover_common_languages(self):
        for lang in ["node", "python", "go", "rust", "java", "ruby"]:
            assert lang in DEFAULT_RUNTIME_BLOCKS
            assert DEFAULT_RUNTIME_BLOCKS[lang].startswith("RUN ")


# --------------------------------------------------------------------------- #
# find_harness_root
# --------------------------------------------------------------------------- #
class TestFindHarnessRoot:
    def test_finds_root_from_itself(self, harness_root: Path):
        assert find_harness_root(harness_root) == harness_root

    def test_finds_root_from_child(self, harness_root: Path):
        child = harness_root / "some" / "deep" / "path"
        child.mkdir(parents=True)
        assert find_harness_root(child) == harness_root

    def test_raises_when_not_in_a_harness(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            find_harness_root(tmp_path)


# --------------------------------------------------------------------------- #
# HarnessConfig.load
# --------------------------------------------------------------------------- #
class TestHarnessConfigLoad:
    def test_load_basic(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "harness": {"purpose": "test"},
            "env": {"base_image": "ubuntu:24.04"},
            "projects": [{
                "name": "svc",
                "path": "projects/svc",
                "writable": True,
                "runtime": {"language": ["python"]},
                "commands": {"test": "pytest"},
            }],
        })
        monkeypatch.chdir(harness_root)
        cfg = HarnessConfig.load()
        assert cfg.purpose == "test"
        assert cfg.base_image == "ubuntu:24.04"
        assert len(cfg.projects) == 1
        assert cfg.projects[0].name == "svc"
        assert cfg.projects[0].commands["test"] == "pytest"

    def test_load_normalizes_languages(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "projects": [{
                "name": "web",
                "path": "projects/web",
                "runtime": {"language": ["javascript", "js", "typescript"]},
            }],
        })
        monkeypatch.chdir(harness_root)
        cfg = HarnessConfig.load()
        # All three should collapse to a single "node"
        assert cfg.projects[0].runtime["language"] == ["node"]

    def test_load_merges_runtime_block_overrides(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "env": {
                "runtime_blocks": {
                    "node": "RUN echo custom-node",
                    "elixir": "RUN echo elixir",
                },
            },
            "projects": [{"name": "svc", "path": "projects/svc"}],
        })
        monkeypatch.chdir(harness_root)
        cfg = HarnessConfig.load()
        assert cfg.runtime_blocks["node"] == "RUN echo custom-node"
        assert cfg.runtime_blocks["elixir"] == "RUN echo elixir"
        # Defaults for other languages are preserved
        assert cfg.runtime_blocks["python"] == DEFAULT_RUNTIME_BLOCKS["python"]

    def test_load_raises_without_yaml(self, harness_root: Path, monkeypatch):
        monkeypatch.chdir(harness_root)
        with pytest.raises(FileNotFoundError):
            HarnessConfig.load()


# --------------------------------------------------------------------------- #
# HarnessConfig.project
# --------------------------------------------------------------------------- #
class TestHarnessConfigProject:
    def _cfg_with(self, names: list[str]) -> HarnessConfig:
        projects = [Project(name=n, path=f"projects/{n}") for n in names]
        return HarnessConfig(root=Path("/tmp"), projects=projects)

    def test_single_project_returns_without_name(self):
        cfg = self._cfg_with(["svc"])
        assert cfg.project().name == "svc"

    def test_single_project_by_name(self):
        cfg = self._cfg_with(["svc"])
        assert cfg.project("svc").name == "svc"

    def test_multi_project_requires_name(self):
        cfg = self._cfg_with(["a", "b"])
        with pytest.raises(ValueError, match="Multiple projects"):
            cfg.project()

    def test_multi_project_by_name(self):
        cfg = self._cfg_with(["a", "b"])
        assert cfg.project("b").name == "b"

    def test_unknown_name_raises(self):
        cfg = self._cfg_with(["a"])
        with pytest.raises(KeyError):
            cfg.project("missing")

    def test_empty_projects_raises(self):
        cfg = HarnessConfig(root=Path("/tmp"))
        with pytest.raises(ValueError, match="No projects"):
            cfg.project()


# --------------------------------------------------------------------------- #
# HarnessState
# --------------------------------------------------------------------------- #
class TestHarnessState:
    def test_state_absent_returns_uninitialized(self, harness_root: Path):
        s = HarnessState.load(harness_root)
        assert s.status == "uninitialized"
        assert s.data == {}

    def test_state_roundtrips(self, harness_root: Path):
        s = HarnessState(root=harness_root, status="initialized", data={"harness_purpose": "test"})
        s.save()
        loaded = HarnessState.load(harness_root)
        assert loaded.status == "initialized"
        assert loaded.data.get("harness_purpose") == "test"
