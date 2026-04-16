"""Project-toolchain detection for `harness init detect`.

Encodes the manifest / lock-file rules from skills/initialization.md as
executable code so agents don't have to re-apply them by hand each time.

Detection is conservative: if a signal isn't present, the relevant field
is left ``None`` rather than guessed. The CLI renders a commented
``# notes:`` section so the user/agent can see what was (and wasn't)
detected and make the final call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

@dataclass
class DetectResult:
    name: str
    languages: list[str] = field(default_factory=list)
    deps: Optional[str] = None
    build: Optional[str] = None
    test: Optional[str] = None
    lint: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    has_native_extension: bool = False


# ---------------------------------------------------------------------------
# Language detection — from manifest files only
# ---------------------------------------------------------------------------

_LANGUAGE_MANIFESTS: list[tuple[str, list[str]]] = [
    ("python",     ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile"]),
    ("javascript", ["package.json"]),
    ("rust",       ["Cargo.toml"]),
    ("go",         ["go.mod"]),
    ("ruby",       ["Gemfile"]),
    ("java",       ["pom.xml", "build.gradle", "build.gradle.kts"]),
    ("elixir",     ["mix.exs"]),
    ("php",        ["composer.json"]),
    ("c",          ["configure.ac", "CMakeLists.txt"]),
]


def _detect_languages(path: Path) -> list[str]:
    found: list[str] = []
    for lang, manifests in _LANGUAGE_MANIFESTS:
        if any((path / m).exists() for m in manifests):
            found.append(lang)
    return found


# ---------------------------------------------------------------------------
# Lock-file-aware dependency install commands
# ---------------------------------------------------------------------------

def _detect_deps_command(path: Path, languages: list[str]) -> Optional[str]:
    """Prefer the locked install command when a lock file is present."""
    if "javascript" in languages:
        if (path / "package-lock.json").exists():
            return "npm ci"
        if (path / "pnpm-lock.yaml").exists():
            return "pnpm install --frozen-lockfile"
        if (path / "yarn.lock").exists():
            return "yarn install --frozen-lockfile"
        if (path / "package.json").exists():
            return "npm install"

    if "python" in languages:
        if (path / "poetry.lock").exists():
            return "poetry install --no-interaction"
        if (path / "uv.lock").exists():
            return "uv sync --frozen"
        if (path / "pdm.lock").exists():
            return "pdm install --frozen-lockfile"
        if (path / "Pipfile.lock").exists():
            return "pipenv sync"
        if (path / "pyproject.toml").exists() or (path / "setup.py").exists():
            return "pip install --user -e ."
        if (path / "requirements.txt").exists():
            return "pip install --user -r requirements.txt"

    if "rust" in languages:
        if (path / "Cargo.lock").exists():
            return "cargo fetch --locked"
        return "cargo fetch"

    if "go" in languages:
        return "go mod download"

    if "ruby" in languages:
        if (path / "Gemfile.lock").exists():
            return "bundle config set frozen 1 && bundle install"
        return "bundle install"

    if "java" in languages:
        if (path / "pom.xml").exists():
            return "mvn -B dependency:go-offline"
        return "gradle dependencies"

    if "elixir" in languages:
        return "mix deps.get"

    if "php" in languages:
        if (path / "composer.lock").exists():
            return "composer install --no-interaction"
        return "composer install"

    if "c" in languages:
        if (path / "configure.ac").exists():
            return "./autogen.sh && ./configure"
        if (path / "CMakeLists.txt").exists():
            return "cmake -S . -B build"

    return None


# ---------------------------------------------------------------------------
# Makefile target probing — prefer project-declared workflows
# ---------------------------------------------------------------------------

_MAKEFILE_TARGET = re.compile(r"^([a-zA-Z0-9_\-./]+)\s*:", re.MULTILINE)


def _makefile_targets(path: Path) -> set[str]:
    mf = path / "Makefile"
    if not mf.exists():
        return set()
    try:
        text = mf.read_text(errors="ignore")
    except OSError:
        return set()
    # Strip .PHONY declarations and comments
    text = re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE)
    return {m.group(1) for m in _MAKEFILE_TARGET.finditer(text)}


def _detect_test_command(path: Path, languages: list[str]) -> Optional[str]:
    targets = _makefile_targets(path)
    # Projects that declare their own `make test` win (xz, pyyaml both do this).
    if "test" in targets:
        return "make test"
    if "check" in targets:
        return "make check"

    if "javascript" in languages:
        pj = path / "package.json"
        if pj.exists():
            try:
                data = json.loads(pj.read_text())
            except (OSError, json.JSONDecodeError):
                data = {}
            if "test" in (data.get("scripts") or {}):
                return "npm test"
    if "python" in languages:
        return "pytest"
    if "rust" in languages:
        return "cargo test"
    if "go" in languages:
        return "go test ./..."
    if "ruby" in languages:
        return "bundle exec rake test"
    if "java" in languages:
        if (path / "pom.xml").exists():
            return "mvn test"
        return "gradle test"
    if "elixir" in languages:
        return "mix test"
    if "php" in languages:
        return "vendor/bin/phpunit"
    return None


def _detect_build_command(path: Path, languages: list[str]) -> Optional[str]:
    targets = _makefile_targets(path)
    if "build" in targets:
        return "make build"
    if "all" in targets and not (path / "configure.ac").exists():
        # `make all` is the canonical build target for many non-autotools projects.
        return "make all"

    if "javascript" in languages:
        pj = path / "package.json"
        if pj.exists():
            try:
                data = json.loads(pj.read_text())
            except (OSError, json.JSONDecodeError):
                data = {}
            if "build" in (data.get("scripts") or {}):
                return "npm run build"
    if "rust" in languages:
        return "cargo build"
    if "go" in languages:
        return "go build ./..."
    if "c" in languages and "make" not in targets:
        return "make"
    return None


# ---------------------------------------------------------------------------
# Native-extension detection — Python + Cython/C extensions need an
# "install after build" step to refresh the editable install.
# ---------------------------------------------------------------------------

def _has_native_extension(path: Path, languages: list[str]) -> bool:
    if "python" not in languages:
        return False
    # Cython sources
    for _ in path.rglob("*.pyx"):
        return True
    for _ in path.rglob("*.pxd"):
        return True
    # setup.py Extension(...) / ext_modules=
    setup_py = path / "setup.py"
    if setup_py.exists():
        try:
            text = setup_py.read_text(errors="ignore")
        except OSError:
            text = ""
        if "ext_modules" in text or "Extension(" in text:
            return True
    return False


# ---------------------------------------------------------------------------
# Lint detection — best-effort; if none, lint stays None so harness.yml
# omits the key (per the "omit, don't stub" rule in skills/initialization.md).
# ---------------------------------------------------------------------------

_LINT_CONFIGS: list[tuple[str, str]] = [
    (".eslintrc.js",     "npm run lint"),
    (".eslintrc.json",   "npm run lint"),
    (".eslintrc.yml",    "npm run lint"),
    ("eslint.config.js", "npm run lint"),
    ("ruff.toml",        "ruff check ."),
    (".ruff.toml",       "ruff check ."),
    (".golangci.yml",    "golangci-lint run"),
    (".golangci.toml",   "golangci-lint run"),
    ("clippy.toml",      "cargo clippy -- -D warnings"),
    (".rubocop.yml",     "bundle exec rubocop"),
]


def _detect_lint_command(path: Path, languages: list[str]) -> Optional[str]:
    for filename, command in _LINT_CONFIGS:
        if (path / filename).exists():
            return command
    # pyproject.toml can embed a [tool.ruff] section
    if "python" in languages:
        pp = path / "pyproject.toml"
        if pp.exists():
            try:
                text = pp.read_text(errors="ignore")
            except OSError:
                text = ""
            if "[tool.ruff" in text:
                return "ruff check ."
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_project(path: Path, name: Optional[str] = None) -> DetectResult:
    """Detect toolchain and commands for a project directory."""
    name = name or path.resolve().name
    languages = _detect_languages(path)
    native = _has_native_extension(path, languages)

    notes: list[str] = []
    if not languages:
        notes.append(
            "No language manifest detected. The project may need manual command entry."
        )
    if len(languages) > 1:
        notes.append(
            f"Multiple languages detected: {languages}. "
            f"Primary commands target {languages[0]}; review for correctness."
        )
    if native:
        notes.append(
            "Native extension detected (.pyx / setup.py ext_modules). "
            "After `build`, you may need to refresh the editable install "
            "(e.g. `pip install -e . --force-reinstall --no-deps`) so rebuilt "
            ".so files are picked up by the installed package."
        )

    lint = _detect_lint_command(path, languages)
    if lint is None:
        notes.append(
            "No linter config detected. `lint` is omitted "
            "(report will show not_configured, which is the correct advisory)."
        )

    return DetectResult(
        name=name,
        languages=languages,
        deps=_detect_deps_command(path, languages),
        build=_detect_build_command(path, languages),
        test=_detect_test_command(path, languages),
        lint=lint,
        notes=notes,
        has_native_extension=native,
    )


# ---------------------------------------------------------------------------
# YAML snippet rendering
# ---------------------------------------------------------------------------

def render_yaml_snippet(result: DetectResult, project_path: Optional[str] = None) -> str:
    """Render a `projects[]`-entry fragment suitable for pasting into harness.yml."""
    path = project_path or f"projects/{result.name}"
    lines: list[str] = [
        f"- name: {result.name}",
        f"  path: {path}",
        f"  writable: true",
    ]
    if result.languages:
        lines.append("  runtime:")
        lines.append(f"    language: [{', '.join(result.languages)}]")

    cmds: list[tuple[str, str]] = []
    if result.deps:
        cmds.append(("deps", result.deps))
    if result.build:
        cmds.append(("build", result.build))
    if result.test:
        cmds.append(("test", result.test))
    if result.lint:
        cmds.append(("lint", result.lint))

    if cmds:
        lines.append("  commands:")
        for key, value in cmds:
            escaped = value.replace('"', '\\"')
            lines.append(f'    {key}: "{escaped}"')

    if result.notes:
        lines.append("  # notes (review and delete after updating):")
        for note in result.notes:
            lines.append(f"  #   - {note}")

    return "\n".join(lines) + "\n"
