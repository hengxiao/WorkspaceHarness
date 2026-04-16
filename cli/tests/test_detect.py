"""Tests for harness.detect — language, lock-file, command, and
native-extension detection, plus YAML snippet rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.detect import DetectResult, detect_project, render_yaml_snippet


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

class TestLanguageDetection:
    def test_python_from_pyproject(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "[project]\nname = 'x'\n")
        assert detect_project(tmp_path).languages == ["python"]

    def test_python_from_setup_py(self, tmp_path: Path):
        _touch(tmp_path / "setup.py", "from setuptools import setup\nsetup(name='x')\n")
        assert detect_project(tmp_path).languages == ["python"]

    def test_python_from_requirements(self, tmp_path: Path):
        _touch(tmp_path / "requirements.txt", "requests\n")
        assert detect_project(tmp_path).languages == ["python"]

    def test_javascript_from_package_json(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{"name":"x"}')
        assert detect_project(tmp_path).languages == ["javascript"]

    def test_rust_from_cargo_toml(self, tmp_path: Path):
        _touch(tmp_path / "Cargo.toml", '[package]\nname = "x"\n')
        assert detect_project(tmp_path).languages == ["rust"]

    def test_go_from_go_mod(self, tmp_path: Path):
        _touch(tmp_path / "go.mod", "module x\n")
        assert detect_project(tmp_path).languages == ["go"]

    def test_ruby_from_gemfile(self, tmp_path: Path):
        _touch(tmp_path / "Gemfile", "source 'https://rubygems.org'\n")
        assert detect_project(tmp_path).languages == ["ruby"]

    def test_java_from_pom(self, tmp_path: Path):
        _touch(tmp_path / "pom.xml", "<project></project>")
        assert detect_project(tmp_path).languages == ["java"]

    def test_java_from_gradle(self, tmp_path: Path):
        _touch(tmp_path / "build.gradle", "apply plugin: 'java'")
        assert detect_project(tmp_path).languages == ["java"]

    def test_elixir_from_mix_exs(self, tmp_path: Path):
        _touch(tmp_path / "mix.exs", "defmodule X.MixProject do\nend")
        assert detect_project(tmp_path).languages == ["elixir"]

    def test_php_from_composer_json(self, tmp_path: Path):
        _touch(tmp_path / "composer.json", "{}")
        assert detect_project(tmp_path).languages == ["php"]

    def test_c_from_configure_ac(self, tmp_path: Path):
        _touch(tmp_path / "configure.ac", "AC_INIT(x, 0)\n")
        assert detect_project(tmp_path).languages == ["c"]

    def test_c_from_cmake(self, tmp_path: Path):
        _touch(tmp_path / "CMakeLists.txt", "project(x)\n")
        assert detect_project(tmp_path).languages == ["c"]

    def test_multiple_languages_are_all_detected(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{}')
        _touch(tmp_path / "go.mod", "module x")
        langs = detect_project(tmp_path).languages
        assert "javascript" in langs
        assert "go" in langs

    def test_empty_directory_yields_no_languages(self, tmp_path: Path):
        result = detect_project(tmp_path)
        assert result.languages == []
        assert any("No language manifest" in note for note in result.notes)


# ---------------------------------------------------------------------------
# Lock-file-aware deps commands
# ---------------------------------------------------------------------------

class TestLockFileAwareness:
    def test_node_with_package_lock_uses_npm_ci(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{}')
        _touch(tmp_path / "package-lock.json", '{}')
        assert detect_project(tmp_path).deps == "npm ci"

    def test_node_with_pnpm_lock(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{}')
        _touch(tmp_path / "pnpm-lock.yaml", "")
        assert detect_project(tmp_path).deps == "pnpm install --frozen-lockfile"

    def test_node_with_yarn_lock(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{}')
        _touch(tmp_path / "yarn.lock", "")
        assert detect_project(tmp_path).deps == "yarn install --frozen-lockfile"

    def test_node_without_lock_falls_back_to_install(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{}')
        assert detect_project(tmp_path).deps == "npm install"

    def test_python_with_poetry_lock(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        _touch(tmp_path / "poetry.lock", "")
        assert detect_project(tmp_path).deps == "poetry install --no-interaction"

    def test_python_with_uv_lock(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        _touch(tmp_path / "uv.lock", "")
        assert detect_project(tmp_path).deps == "uv sync --frozen"

    def test_python_without_lock(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        assert detect_project(tmp_path).deps == "pip install --user -e ."

    def test_rust_with_lock_uses_locked(self, tmp_path: Path):
        _touch(tmp_path / "Cargo.toml", "")
        _touch(tmp_path / "Cargo.lock", "")
        assert detect_project(tmp_path).deps == "cargo fetch --locked"

    def test_rust_without_lock(self, tmp_path: Path):
        _touch(tmp_path / "Cargo.toml", "")
        assert detect_project(tmp_path).deps == "cargo fetch"

    def test_ruby_with_gemfile_lock(self, tmp_path: Path):
        _touch(tmp_path / "Gemfile", "")
        _touch(tmp_path / "Gemfile.lock", "")
        assert "frozen" in detect_project(tmp_path).deps

    def test_c_autotools(self, tmp_path: Path):
        _touch(tmp_path / "configure.ac", "AC_INIT(x, 0)")
        assert detect_project(tmp_path).deps == "./autogen.sh && ./configure"

    def test_c_cmake(self, tmp_path: Path):
        _touch(tmp_path / "CMakeLists.txt", "project(x)")
        assert detect_project(tmp_path).deps == "cmake -S . -B build"


# ---------------------------------------------------------------------------
# Test / build command detection — prefer Makefile, fall back to language
# ---------------------------------------------------------------------------

class TestCommandDetection:
    def test_makefile_test_target_wins_over_language_default(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{"scripts":{"test":"jest"}}')
        _touch(tmp_path / "Makefile", "test:\n\tmake check\n")
        assert detect_project(tmp_path).test == "make test"

    def test_makefile_check_target_used_when_no_test(self, tmp_path: Path):
        _touch(tmp_path / "configure.ac", "")
        _touch(tmp_path / "Makefile", "check:\n\t./run-tests.sh\n")
        assert detect_project(tmp_path).test == "make check"

    def test_python_default_test_is_pytest(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        assert detect_project(tmp_path).test == "pytest"

    def test_node_with_test_script(self, tmp_path: Path):
        _touch(tmp_path / "package.json", json.dumps({"scripts": {"test": "jest"}}))
        assert detect_project(tmp_path).test == "npm test"

    def test_node_without_test_script_has_no_test(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{}')
        assert detect_project(tmp_path).test is None

    def test_rust_test_is_cargo_test(self, tmp_path: Path):
        _touch(tmp_path / "Cargo.toml", "")
        assert detect_project(tmp_path).test == "cargo test"

    def test_go_test(self, tmp_path: Path):
        _touch(tmp_path / "go.mod", "module x")
        assert detect_project(tmp_path).test == "go test ./..."

    def test_build_command_from_makefile(self, tmp_path: Path):
        _touch(tmp_path / "Cargo.toml", "")
        _touch(tmp_path / "Makefile", "build:\n\tcargo build --release\n")
        assert detect_project(tmp_path).build == "make build"

    def test_build_command_from_npm_script(self, tmp_path: Path):
        _touch(tmp_path / "package.json", json.dumps({"scripts": {"build": "webpack"}}))
        assert detect_project(tmp_path).build == "npm run build"


# ---------------------------------------------------------------------------
# Native extension detection (issue we hit with pyyaml)
# ---------------------------------------------------------------------------

class TestNativeExtension:
    def test_cython_pyx_file_detected(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        _touch(tmp_path / "mypkg" / "_fast.pyx", "def foo(): pass")
        result = detect_project(tmp_path)
        assert result.has_native_extension
        assert any("Native extension" in note for note in result.notes)

    def test_setup_py_ext_modules_detected(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        _touch(
            tmp_path / "setup.py",
            "from setuptools import setup, Extension\n"
            "setup(ext_modules=[Extension('x', ['x.c'])])\n",
        )
        result = detect_project(tmp_path)
        assert result.has_native_extension

    def test_pure_python_not_flagged(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        _touch(tmp_path / "mypkg" / "__init__.py", "")
        result = detect_project(tmp_path)
        assert not result.has_native_extension


# ---------------------------------------------------------------------------
# Lint detection — presence, absence, and the "omit, don't stub" note
# ---------------------------------------------------------------------------

class TestLintDetection:
    def test_ruff_config_detected(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        _touch(tmp_path / "ruff.toml", "line-length = 100")
        assert detect_project(tmp_path).lint == "ruff check ."

    def test_pyproject_ruff_section_detected(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
        assert detect_project(tmp_path).lint == "ruff check ."

    def test_eslint_config_detected(self, tmp_path: Path):
        _touch(tmp_path / "package.json", '{}')
        _touch(tmp_path / ".eslintrc.json", "{}")
        assert detect_project(tmp_path).lint == "npm run lint"

    def test_no_linter_config_leaves_lint_none(self, tmp_path: Path):
        _touch(tmp_path / "pyproject.toml", "")
        result = detect_project(tmp_path)
        assert result.lint is None
        assert any("not_configured" in note for note in result.notes)


# ---------------------------------------------------------------------------
# YAML snippet rendering
# ---------------------------------------------------------------------------

class TestRenderYamlSnippet:
    def test_full_snippet_has_all_blocks(self, tmp_path: Path):
        result = DetectResult(
            name="svc",
            languages=["python"],
            deps="pip install --user -e .",
            build="make build",
            test="pytest",
            lint=None,
            notes=["no linter"],
        )
        out = render_yaml_snippet(result)
        assert "- name: svc" in out
        assert "path: projects/svc" in out
        assert "writable: true" in out
        assert "language: [python]" in out
        assert "deps:" in out and "pip install" in out
        assert "lint:" not in out, "None-valued lint must be omitted, not stubbed"
        assert "# notes" in out

    def test_no_languages_still_renders(self, tmp_path: Path):
        result = DetectResult(name="svc")
        out = render_yaml_snippet(result)
        assert "- name: svc" in out
        assert "language:" not in out
        assert "commands:" not in out

    def test_project_path_override(self, tmp_path: Path):
        result = DetectResult(name="svc", languages=["python"])
        out = render_yaml_snippet(result, project_path="vendor/svc")
        assert "path: vendor/svc" in out


# ---------------------------------------------------------------------------
# End-to-end fixture: reproduce what we'd detect for pyyaml
# ---------------------------------------------------------------------------

class TestRealisticFixtures:
    def _make_pyyaml_like(self, tmp_path: Path) -> Path:
        _touch(
            tmp_path / "pyproject.toml",
            '[build-system]\nrequires = ["setuptools", "Cython"]\n',
        )
        _touch(
            tmp_path / "setup.py",
            "from setuptools import setup, Extension\n"
            "setup(ext_modules=[Extension('_yaml', ['yaml/_yaml.pyx'])])\n",
        )
        _touch(tmp_path / "yaml" / "_yaml.pyx", "def foo(): pass")
        _touch(
            tmp_path / "Makefile",
            "test:\n\tPYYAML_FORCE_LIBYAML=0 python3 -I -m pytest\n"
            "build:\n\tpython3 setup.py build\n",
        )
        return tmp_path

    def test_pyyaml_like_project(self, tmp_path: Path):
        self._make_pyyaml_like(tmp_path)
        result = detect_project(tmp_path, name="pyyaml")
        assert result.languages == ["python"]
        # Lock-free pyproject → default pip install
        assert result.deps == "pip install --user -e ."
        # Makefile targets win over language default
        assert result.build == "make build"
        assert result.test == "make test"
        assert result.has_native_extension
        # Lint unconfigured upstream
        assert result.lint is None

    def _make_xz_like(self, tmp_path: Path) -> Path:
        _touch(tmp_path / "configure.ac", "AC_INIT(xz, 5.8.0)")
        _touch(
            tmp_path / "Makefile",
            "check:\n\t./run-tests.sh\n"
            "all:\n\tgcc ...\n",
        )
        return tmp_path

    def test_xz_like_autotools_project(self, tmp_path: Path):
        self._make_xz_like(tmp_path)
        result = detect_project(tmp_path, name="xz")
        assert result.languages == ["c"]
        assert result.deps == "./autogen.sh && ./configure"
        assert result.test == "make check"
        assert result.lint is None
