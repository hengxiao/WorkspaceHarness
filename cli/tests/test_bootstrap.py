"""Tests for harness.bootstrap — template rendering, KEEP-block preservation."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.bootstrap import (
    KEEP_MARKER_BEGIN,
    KEEP_MARKER_END,
    _preserve_keep_blocks,
    run_bootstrap,
)


# --------------------------------------------------------------------------- #
# KEEP-block preservation
# --------------------------------------------------------------------------- #
class TestKeepBlocks:
    def test_preserves_hand_edits_inside_marker(self):
        existing = (
            f"line a\n"
            f"{KEEP_MARKER_BEGIN} b\n"
            f"HAND-EDIT\n"
            f"{KEEP_MARKER_END} b\n"
            f"line c\n"
        )
        generated = (
            f"line a\n"
            f"{KEEP_MARKER_BEGIN} b\n"
            f"TEMPLATE-DEFAULT\n"
            f"{KEEP_MARKER_END} b\n"
            f"line c\n"
        )
        result = _preserve_keep_blocks(existing, generated)
        assert "HAND-EDIT" in result
        assert "TEMPLATE-DEFAULT" not in result

    def test_returns_generated_when_no_markers_in_existing(self):
        existing = "no markers here"
        generated = "template output"
        assert _preserve_keep_blocks(existing, generated) == generated

    def test_block_not_in_existing_takes_template_default(self):
        existing = f"{KEEP_MARKER_BEGIN} a\nedited\n{KEEP_MARKER_END} a\n"
        generated = (
            f"{KEEP_MARKER_BEGIN} a\ntmpl-a\n{KEEP_MARKER_END} a\n"
            f"{KEEP_MARKER_BEGIN} b\ntmpl-b\n{KEEP_MARKER_END} b\n"
        )
        result = _preserve_keep_blocks(existing, generated)
        assert "edited" in result
        assert "tmpl-a" not in result
        # block b only exists in the new template, should be preserved as-is
        assert "tmpl-b" in result


# --------------------------------------------------------------------------- #
# run_bootstrap — end-to-end template render against a fake harness.yml
# --------------------------------------------------------------------------- #
class TestRunBootstrap:
    def test_renders_files_for_minimal_config(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "env": {"base_image": "ubuntu:24.04"},
            "projects": [{
                "name": "svc",
                "path": "projects/svc",
                "runtime": {"language": ["python"]},
            }],
        })
        monkeypatch.chdir(harness_root)
        written = run_bootstrap()

        assert len(written) == 2
        df = (harness_root / "env" / "Dockerfile").read_text()
        compose = (harness_root / "env" / "docker-compose.yml").read_text()

        assert "FROM ubuntu:24.04" in df
        assert "python3-dev" in df, "default python runtime_block should be rendered"
        assert "stdin_open: true" in compose
        assert "tty: true" in compose
        assert "harness-home:/root" in compose, "$HOME persistence volume should be mounted"
        assert "\nvolumes:\n" in compose, "top-level volumes declaration required for named volume"

    def test_custom_runtime_block_overrides_default(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({
            "env": {"runtime_blocks": {"node": "RUN echo custom-node-install"}},
            "projects": [{"name": "svc", "path": "projects/svc", "runtime": {"language": ["node"]}}],
        })
        monkeypatch.chdir(harness_root)
        run_bootstrap()
        df = (harness_root / "env" / "Dockerfile").read_text()
        assert "custom-node-install" in df
        assert "nodesource.com" not in df, "default node block should not appear"

    def test_new_language_via_user_runtime_block(self, harness_root: Path, write_harness_yml, monkeypatch):
        """A language not in defaults works if the user supplies a runtime_block."""
        write_harness_yml({
            "env": {
                "runtime_blocks": {
                    "c": "RUN apt-get install -y autoconf automake",
                },
            },
            "projects": [{"name": "svc", "path": "projects/svc", "runtime": {"language": ["c"]}}],
        })
        monkeypatch.chdir(harness_root)
        run_bootstrap()
        df = (harness_root / "env" / "Dockerfile").read_text()
        assert "autoconf automake" in df

    def test_language_not_in_blocks_is_skipped_silently(self, harness_root: Path, write_harness_yml, monkeypatch):
        """An unknown language with no runtime_block doesn't break rendering."""
        write_harness_yml({
            "projects": [{"name": "svc", "path": "projects/svc", "runtime": {"language": ["cobol"]}}],
        })
        monkeypatch.chdir(harness_root)
        run_bootstrap()
        df = (harness_root / "env" / "Dockerfile").read_text()
        # Should render successfully without any cobol block
        assert "FROM ubuntu:24.04" in df

    def test_multiple_projects_dedupe_languages(self, harness_root: Path, write_harness_yml, monkeypatch):
        """Two projects both using 'javascript' shouldn't double-install Node."""
        write_harness_yml({
            "projects": [
                {"name": "web", "path": "projects/web", "runtime": {"language": ["javascript"]}},
                {"name": "api", "path": "projects/api", "runtime": {"language": ["js"]}},
            ],
        })
        monkeypatch.chdir(harness_root)
        run_bootstrap()
        df = (harness_root / "env" / "Dockerfile").read_text()
        # The "# node" comment should appear only once
        assert df.count("# node\n") == 1

    def test_keep_block_preserved_across_bootstrap_runs(self, harness_root: Path, write_harness_yml, monkeypatch):
        write_harness_yml({"projects": [{"name": "svc", "path": "projects/svc"}]})
        monkeypatch.chdir(harness_root)
        run_bootstrap()

        # Simulate a hand-edit inside a KEEP block.
        df_path = harness_root / "env" / "Dockerfile"
        original = df_path.read_text()
        modified = original.replace(
            "# Add custom RUN/COPY steps here. They survive `harness bootstrap`.",
            "RUN echo user-added-this",
        )
        df_path.write_text(modified)

        run_bootstrap()
        assert "RUN echo user-added-this" in df_path.read_text()
