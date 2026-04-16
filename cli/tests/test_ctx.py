"""Tests for harness.ctx — frontmatter parsing, validation, add."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.ctx import _parse_frontmatter, cmd_add, cmd_validate


class TestParseFrontmatter:
    def test_parses_well_formed_frontmatter(self):
        text = (
            "---\n"
            "title: Test\n"
            "tags: [a, b]\n"
            "summary: A summary.\n"
            "updated: 2026-04-15\n"
            "---\n\n"
            "body\n"
        )
        fm = _parse_frontmatter(text)
        assert fm is not None
        assert fm["title"] == "Test"
        assert fm["tags"] == ["a", "b"]

    def test_returns_none_without_frontmatter(self):
        assert _parse_frontmatter("# heading\n\nbody\n") is None

    def test_returns_none_on_unterminated_block(self):
        assert _parse_frontmatter("---\ntitle: x\n\nbody\n") is None


class TestCmdValidate:
    def _write_doc(self, path: Path, frontmatter: dict):
        import yaml as _yaml
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "---\n" + _yaml.safe_dump(frontmatter).strip() + "\n---\n\n# Body\n"
        path.write_text(body)

    def test_valid_doc_passes(self, harness_root: Path, monkeypatch):
        monkeypatch.chdir(harness_root)
        (harness_root / "context").mkdir()
        self._write_doc(harness_root / "context" / "good.md", {
            "title": "x", "tags": ["a"], "summary": "y", "updated": "2026-04-15",
        })
        assert cmd_validate() == []

    def test_missing_frontmatter_flagged(self, harness_root: Path, monkeypatch):
        monkeypatch.chdir(harness_root)
        (harness_root / "context").mkdir()
        (harness_root / "context" / "bad.md").write_text("# no frontmatter\n")
        errors = cmd_validate()
        assert len(errors) == 1
        assert "bad.md" in errors[0]

    def test_missing_keys_flagged(self, harness_root: Path, monkeypatch):
        monkeypatch.chdir(harness_root)
        (harness_root / "context").mkdir()
        self._write_doc(harness_root / "context" / "partial.md", {
            "title": "x",  # missing tags, summary, updated
        })
        errors = cmd_validate()
        assert len(errors) == 1
        assert "missing keys" in errors[0]

    def test_readme_is_exempt(self, harness_root: Path, monkeypatch):
        """README.md files describe layout; they don't need the full frontmatter."""
        monkeypatch.chdir(harness_root)
        (harness_root / "context").mkdir()
        (harness_root / "context" / "README.md").write_text("# layout notes\n")
        assert cmd_validate() == []


class TestCmdAdd:
    def test_creates_file_with_frontmatter(self, harness_root: Path, monkeypatch):
        monkeypatch.chdir(harness_root)
        target = harness_root / "context" / "internal" / "note.md"
        cmd_add(path=str(target), title="A note", tags=["internal"], source="internal")
        assert target.exists()
        text = target.read_text()
        assert text.startswith("---")
        assert "title: A note" in text
        assert "source: internal" in text

    def test_refuses_to_overwrite(self, harness_root: Path, monkeypatch):
        monkeypatch.chdir(harness_root)
        target = harness_root / "existing.md"
        target.write_text("existing\n")
        with pytest.raises(FileExistsError):
            cmd_add(path=str(target), title="x", tags=[], source="internal")
