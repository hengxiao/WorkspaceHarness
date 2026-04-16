"""Tests for harness.ingest — executes context.ingest: blocks from harness.yml."""

from __future__ import annotations

from pathlib import Path

import yaml as _yaml

from harness.ingest import (
    _pattern_base,
    _strip_frontmatter,
    run_ingest,
)


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

class TestPatternBase:
    def test_no_wildcards(self):
        assert _pattern_base("projects/svc/README.md") == "projects/svc/README.md"

    def test_stops_at_first_wildcard(self):
        assert _pattern_base("projects/svc/docs/**/*.md") == "projects/svc/docs"

    def test_star_in_middle_component(self):
        assert _pattern_base("projects/svc/*/*.md") == "projects/svc"

    def test_char_class_is_a_wildcard(self):
        assert _pattern_base("projects/svc/f[a-z]oo") == "projects/svc"

    def test_only_wildcards(self):
        assert _pattern_base("**/*.md") == "."


class TestStripFrontmatter:
    def test_no_frontmatter(self):
        fm, body = _strip_frontmatter("# heading\n\ncontent\n")
        assert fm is None
        assert body == "# heading\n\ncontent\n"

    def test_with_frontmatter(self):
        fm, body = _strip_frontmatter(
            "---\ntitle: x\ntags: [a]\n---\n\nbody content\n"
        )
        assert fm == {"title": "x", "tags": ["a"]}
        assert body == "body content\n"

    def test_unterminated_frontmatter_returns_unchanged(self):
        text = "---\ntitle: x\nno end marker\n"
        fm, body = _strip_frontmatter(text)
        assert fm is None
        assert body == text


# ---------------------------------------------------------------------------
# End-to-end: fixture harness with a synthetic submodule
# ---------------------------------------------------------------------------

def _make_harness(tmp_path: Path, ingest_blocks: list[dict]) -> Path:
    """Create a minimal harness with one project 'svc' and a few source files."""
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "CLAUDE.md").write_text("placeholder\n")

    project_dir = tmp_path / "projects" / "svc"
    (project_dir / "docs").mkdir(parents=True)
    (project_dir / "README.md").write_text("# svc README\n\nTop-level doc.\n")
    (project_dir / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0\n\nInitial.\n")
    (project_dir / "docs" / "guide.md").write_text("# Guide\n\nContent.\n")
    (project_dir / "docs" / "nested").mkdir(parents=True, exist_ok=True)
    (project_dir / "docs" / "nested" / "api.md").write_text("# API\n\nDetails.\n")

    (tmp_path / "harness.yml").write_text(_yaml.safe_dump({
        "harness": {"purpose": "t"},
        "projects": [{
            "name": "svc",
            "path": "projects/svc",
        }],
        "context": {"ingest": ingest_blocks},
    }))
    return tmp_path


class TestRunIngest:
    def test_single_file_ingest(self, tmp_path: Path, monkeypatch):
        root = _make_harness(tmp_path, [{
            "source": "{project.path}/README.md",
            "into": "context/upstream/{project.name}/README.md",
            "tags": ["docs", "upstream"],
        }])
        monkeypatch.chdir(root)

        result = run_ingest()

        dest = root / "context" / "upstream" / "svc" / "README.md"
        assert dest in result.written
        assert dest.exists()
        text = dest.read_text()
        assert text.startswith("---\n")
        assert "# svc README" in text
        # Frontmatter contains the key metadata
        fm, body = _strip_frontmatter(text)
        assert fm["project"] == "svc"
        assert fm["source"] == "derived"
        assert fm["source_path"] == "README.md"
        assert "upstream" in fm["tags"]

    def test_glob_ingest_preserves_structure(self, tmp_path: Path, monkeypatch):
        root = _make_harness(tmp_path, [{
            "source": "{project.path}/docs/**/*.md",
            "into": "context/upstream/{project.name}/docs/",
            "tags": ["docs"],
        }])
        monkeypatch.chdir(root)

        result = run_ingest()

        # docs/guide.md and docs/nested/api.md both ingested, structure preserved
        assert (root / "context/upstream/svc/docs/guide.md") in result.written
        assert (root / "context/upstream/svc/docs/nested/api.md") in result.written

    def test_ingest_is_idempotent(self, tmp_path: Path, monkeypatch):
        root = _make_harness(tmp_path, [{
            "source": "{project.path}/README.md",
            "into": "context/upstream/{project.name}/README.md",
            "tags": ["docs"],
        }])
        monkeypatch.chdir(root)

        run_ingest()
        dest = root / "context/upstream/svc/README.md"
        first = dest.read_text()

        # Second run — same output.
        run_ingest()
        second = dest.read_text()
        assert first == second, "ingest must be idempotent"

    def test_reingest_replaces_existing_frontmatter(self, tmp_path: Path, monkeypatch):
        """If someone hand-edited the snapshot's frontmatter, re-ingest
        restores the derived one (that's the contract: upstream/ is derived)."""
        root = _make_harness(tmp_path, [{
            "source": "{project.path}/README.md",
            "into": "context/upstream/{project.name}/README.md",
            "tags": ["docs"],
        }])
        monkeypatch.chdir(root)
        run_ingest()

        dest = root / "context/upstream/svc/README.md"
        dest.write_text(
            "---\n"
            "title: HAND_EDITED\n"
            "tags: [hand]\n"
            "---\n\n"
            "# svc README\n\nTop-level doc.\n"
        )

        run_ingest()
        fm, body = _strip_frontmatter(dest.read_text())
        assert fm["title"] != "HAND_EDITED", "re-ingest must overwrite hand-edits"
        assert fm["source"] == "derived"
        # Body is preserved
        assert "# svc README" in body

    def test_no_matches_is_recorded_as_skip(self, tmp_path: Path, monkeypatch):
        root = _make_harness(tmp_path, [{
            "source": "{project.path}/NONEXISTENT.md",
            "into": "context/upstream/{project.name}/NONEXISTENT.md",
            "tags": [],
        }])
        monkeypatch.chdir(root)

        result = run_ingest()
        assert result.written == []
        assert len(result.skipped) == 1
        assert "no files matched" in result.skipped[0][1]

    def test_missing_source_or_into_is_skipped(self, tmp_path: Path, monkeypatch):
        root = _make_harness(tmp_path, [
            {"source": "{project.path}/README.md"},          # no into
            {"into": "context/upstream/svc/x.md"},            # no source
        ])
        monkeypatch.chdir(root)

        result = run_ingest()
        assert result.written == []
        assert len(result.skipped) == 2

    def test_harness_without_ingest_blocks_is_a_noop(self, tmp_path: Path, monkeypatch):
        (tmp_path / "skills").mkdir()
        (tmp_path / "skills" / "CLAUDE.md").write_text("x")
        (tmp_path / "harness.yml").write_text(_yaml.safe_dump({
            "projects": [{"name": "svc", "path": "projects/svc"}],
        }))
        monkeypatch.chdir(tmp_path)

        result = run_ingest()
        assert result.count == 0
        assert result.skipped == []

    def test_ingest_output_passes_ctx_validate(self, tmp_path: Path, monkeypatch):
        """Ingested snapshots must have valid frontmatter (so ctx validate passes)."""
        from harness.ctx import cmd_validate

        root = _make_harness(tmp_path, [{
            "source": "{project.path}/**/*.md",
            "into": "context/upstream/{project.name}/",
            "tags": ["docs", "upstream"],
        }])
        monkeypatch.chdir(root)
        run_ingest()

        errors = cmd_validate()
        assert errors == [], f"ingested files failed ctx validate: {errors}"
