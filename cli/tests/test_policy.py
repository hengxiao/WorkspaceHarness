"""Tests for harness.policy — command and path matching."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness.policy import _command_matches, _path_matches, check_command


@pytest.fixture
def harness_with_policy(harness_root: Path, monkeypatch) -> Path:
    """A harness_root with an agent/policies.yaml."""
    (harness_root / "agent").mkdir()
    (harness_root / "agent" / "policies.yaml").write_text(yaml.safe_dump({
        "version": 1,
        "deny": {
            "commands": ["git push*", "rm -rf*", "make deploy*"],
            "paths_writable": [".github/**", "**/.env*", "**/*.key"],
        },
        "forbidden_paths_in_submodules": ["context/", "skills/", ".harness/"],
    }))
    monkeypatch.chdir(harness_root)
    return harness_root


class TestCommandMatching:
    def test_glob_matches_wildcard(self):
        assert _command_matches("git push*", "git push origin main")
        assert _command_matches("git push*", "git push")
        # fnmatch '*' is greedy — matches any tail, including empty. That's fine
        # for policy safety: any variant of "git push..." should be caught.
        assert _command_matches("git push*", "git pushed")

    def test_exact_match(self):
        assert _command_matches("make deploy", "make deploy")
        assert not _command_matches("make deploy", "make deployment")


class TestPathMatching:
    def test_double_star_matches_deep(self):
        assert _path_matches("**/*.key", "secrets/foo.key")
        assert _path_matches("**/*.key", "deep/nested/path/auth.key")

    def test_dir_prefix_matches_children(self):
        assert _path_matches(".github/**", ".github/workflows/ci.yml")
        assert _path_matches("**/.env*", "projects/svc/.env")
        assert _path_matches("**/.env*", ".env.local")


class TestCheckCommand:
    def test_allowed_command_returns_empty(self, harness_with_policy: Path):
        assert check_command("make test") == []
        assert check_command("git status") == []

    def test_denied_command_returns_violation(self, harness_with_policy: Path):
        violations = check_command("git push origin main")
        assert violations != []
        assert "deny pattern" in violations[0]

    def test_rm_rf_denied(self, harness_with_policy: Path):
        assert check_command("rm -rf /tmp/foo") != []

    def test_make_deploy_denied(self, harness_with_policy: Path):
        assert check_command("make deploy production") != []

    def test_policy_file_missing_is_permissive(self, harness_root: Path, monkeypatch):
        """No policies.yaml means no deny rules — don't crash."""
        monkeypatch.chdir(harness_root)
        assert check_command("git push origin main") == []
