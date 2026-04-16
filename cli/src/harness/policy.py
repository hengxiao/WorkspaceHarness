"""Policy enforcement: load agent/policies.yaml, check commands and staged paths."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from .config import find_harness_root, load_policies


def _command_matches(pattern: str, command: str) -> bool:
    return fnmatch.fnmatchcase(command, pattern.rstrip())


def _path_matches(pattern: str, path: str) -> bool:
    # fnmatch handles *, ?, [], but not **; expand "**" to "*" for shallow matching.
    p = pattern.replace("/**/", "/*/").replace("/**", "/*").replace("**/", "*/")
    return fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(path, pattern.replace("**", "*"))


def check_command(command: str) -> list[str]:
    """Return a list of policy violations (empty = allowed)."""
    pol = load_policies()
    deny_cmds = (pol.get("deny") or {}).get("commands") or []
    for pattern in deny_cmds:
        if _command_matches(pattern, command):
            return [f"command {command!r} matches deny pattern {pattern!r}"]
    return []


def check_staged() -> list[str]:
    """Check staged files against deny + forbidden_paths_in_submodules."""
    pol = load_policies()
    root = find_harness_root()
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"],
            cwd=root,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        return [f"git diff --cached failed: {exc}"]
    staged = [line.strip() for line in out.splitlines() if line.strip()]
    if not staged:
        return []

    violations: list[str] = []
    deny_paths = (pol.get("deny") or {}).get("paths_writable") or []
    forbidden_in_sub = pol.get("forbidden_paths_in_submodules") or []

    for path in staged:
        for pattern in deny_paths:
            if _path_matches(pattern, path):
                violations.append(f"{path} matches deny pattern {pattern!r}")
                break
        if path.startswith("projects/"):
            tail = "/".join(path.split("/")[2:])  # strip projects/<name>/
            for forbidden in forbidden_in_sub:
                if tail.startswith(forbidden.rstrip("/")):
                    violations.append(
                        f"{path} writes harness directory {forbidden!r} into a submodule"
                    )
                    break
    return violations
