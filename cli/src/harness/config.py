"""Loaders for harness.yml and .harness/state.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def find_harness_root(start: Path | None = None) -> Path:
    """Walk upward from `start` (or cwd) looking for a harness root."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "skills" / "CLAUDE.md").exists() or (candidate / "harness.yml").exists():
            return candidate
    raise FileNotFoundError(
        "Could not locate a workspace-harness root from "
        f"{current}. Expected to find harness.yml or skills/CLAUDE.md."
    )


@dataclass
class Project:
    name: str
    path: str
    submodule: dict[str, Any] = field(default_factory=dict)
    writable: bool = False
    runtime: dict[str, Any] = field(default_factory=dict)
    commands: dict[str, str] = field(default_factory=dict)


@dataclass
class HarnessConfig:
    root: Path
    purpose: str = ""
    initialized_at: str | None = None
    projects: list[Project] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    context_ingest: list[dict[str, Any]] = field(default_factory=list)
    agent: dict[str, Any] = field(default_factory=dict)
    base_image: str = "ubuntu:24.04"

    @classmethod
    def load(cls, root: Path | None = None) -> "HarnessConfig":
        root = root or find_harness_root()
        yml_path = root / "harness.yml"
        if not yml_path.exists():
            raise FileNotFoundError(
                f"harness.yml not found at {yml_path}. "
                "Run the 'initialization' skill (skills/initialization.md)."
            )
        data = yaml.safe_load(yml_path.read_text()) or {}
        harness_block = data.get("harness", {}) or {}
        env_block = data.get("env", {}) or {}
        projects = [
            Project(
                name=p["name"],
                path=p["path"],
                submodule=p.get("submodule", {}),
                writable=p.get("writable", False),
                runtime=p.get("runtime", {}),
                commands=p.get("commands", {}),
            )
            for p in (data.get("projects") or [])
        ]
        return cls(
            root=root,
            purpose=harness_block.get("purpose", ""),
            initialized_at=harness_block.get("initialized_at"),
            projects=projects,
            services=data.get("services") or [],
            context_ingest=(data.get("context") or {}).get("ingest", []) or [],
            agent=data.get("agent") or {},
            base_image=env_block.get("base_image", "ubuntu:24.04"),
        )

    def project(self, name: str | None = None) -> Project:
        if not self.projects:
            raise ValueError("No projects declared in harness.yml.")
        if name is None:
            if len(self.projects) > 1:
                raise ValueError(
                    "Multiple projects declared; pass --project to disambiguate."
                )
            return self.projects[0]
        for p in self.projects:
            if p.name == name:
                return p
        raise KeyError(f"No project named {name!r} in harness.yml.")


@dataclass
class HarnessState:
    root: Path
    status: str = "uninitialized"
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path | None = None) -> "HarnessState":
        root = root or find_harness_root()
        path = root / ".harness" / "state.json"
        if not path.exists():
            return cls(root=root, status="uninitialized", data={})
        data = json.loads(path.read_text() or "{}")
        return cls(root=root, status=data.get("status", "uninitialized"), data=data)

    def save(self) -> None:
        path = self.root / ".harness" / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.data["status"] = self.status
        path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")


def load_policies(root: Path | None = None) -> dict[str, Any]:
    root = root or find_harness_root()
    path = root / "agent" / "policies.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)
