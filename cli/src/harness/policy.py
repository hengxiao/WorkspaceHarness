"""Policy enforcement: load agent/policies.yaml, check commands and staged paths."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from .config import find_harness_root, load_policies


def _command_matches(pattern: str, command: str) -> bool:
    return fnmatch.fnmatchcase(command, pattern.rstrip())


def _path_matches(pattern: str, path: str) -> bool:
    """Match a path against a glob pattern, with best-effort ** support.

    fnmatch handles *, ?, [], but not **. We try several shapes:
      - "**/X" also matches "X" at the root (policy-relevant for files like .env)
      - "X/**" also matches "X" itself (dir deny rule also catches the dir itself)
      - "**" is collapsed to "*" for shallow matching
    """
    candidates = {
        pattern,
        pattern.replace("/**/", "/*/"),
        pattern.replace("/**", "/*"),
        pattern.replace("**/", "*/"),
        pattern.replace("**", "*"),
    }
    # "**/X" also needs to match "X" at the root (no leading path).
    if pattern.startswith("**/"):
        candidates.add(pattern[3:])
    # "X/**" also matches X itself.
    if pattern.endswith("/**"):
        candidates.add(pattern[:-3])
    return any(fnmatch.fnmatchcase(path, p) for p in candidates)


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
