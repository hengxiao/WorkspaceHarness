"""Tests for the CLI dev bind-mount mode (HARNESS_DEV=1).

The compose override file + editable install in the Dockerfile combine
so that edits to cli/ on the host show up immediately inside the dev
container — no image rebuild per CLI change.

Unit-level assertions here; a full docker-based smoke test is in
test_container_user.py alongside the non-root-user integration tests
(both need HARNESS_RUN_DOCKER_TESTS=1).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import yaml

HARNESS_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Unit — the artifacts exist and declare what we need
# ---------------------------------------------------------------------------

class TestDevArtifacts:
    def test_dev_compose_file_exists(self):
        dev_file = HARNESS_ROOT / "env" / "docker-compose.dev.yml"
        assert dev_file.exists(), "env/docker-compose.dev.yml must exist"

    def test_dev_compose_mounts_cli_over_opt_harness_cli(self):
        dev_file = HARNESS_ROOT / "env" / "docker-compose.dev.yml"
        data = yaml.safe_load(dev_file.read_text())
        dev_volumes = data["services"]["dev"]["volumes"]
        assert any(
            v == "../cli:/opt/harness-cli" or v.startswith("../cli:/opt/harness-cli:")
            for v in dev_volumes
        ), f"dev override must bind cli/ over /opt/harness-cli, got {dev_volumes}"

    def test_dockerfile_uses_editable_install(self):
        """Editable install is required for the bind-mount approach to work —
        otherwise installed metadata points at copied files, not the mount."""
        df = (HARNESS_ROOT / "env" / "Dockerfile").read_text()
        assert "pip install" in df and "-e /opt/harness-cli" in df, (
            "Dockerfile must install the CLI editable (-e) so bind-mount works"
        )

    def test_dockerfile_template_uses_editable_install(self):
        tmpl = (HARNESS_ROOT / "cli" / "src" / "harness" / "templates" / "Dockerfile.j2").read_text()
        assert "-e /opt/harness-cli" in tmpl

    def test_makefile_activates_override_when_harness_dev_set(self):
        """Grep the Makefile for the conditional — it should add the override
        file only when HARNESS_DEV=1, and leave it out otherwise."""
        mf = (HARNESS_ROOT / "env" / "Makefile").read_text()
        assert "HARNESS_DEV" in mf
        assert "docker-compose.dev.yml" in mf

    def test_makefile_help_documents_dev_mode(self):
        mf = (HARNESS_ROOT / "env" / "Makefile").read_text()
        assert "HARNESS_DEV=1" in mf

    def test_run_target_does_not_use_dash_T(self):
        """The `run` target must NOT use -T because interactive programs
        (emacs, REPLs, shells) need a TTY. Other targets (deps, build,
        test, lint) correctly use -T for non-interactive execution."""
        mf = (HARNESS_ROOT / "env" / "Makefile").read_text()
        import re
        # Find the run: target block (from 'run:' to the next blank line or target)
        run_match = re.search(r"^run:.*\n(?:\t.*\n)*", mf, re.MULTILINE)
        assert run_match, "run target not found in Makefile"
        run_block = run_match.group(0)
        assert "-T" not in run_block, (
            f"run target must not use -T (interactive programs need a TTY), "
            f"got: {run_block.strip()}"
        )
        # Verify non-interactive targets DO still use -T
        for target in ("deps", "build", "test", "lint"):
            target_match = re.search(
                rf"^{target}:.*\n(?:\t.*\n)*", mf, re.MULTILINE
            )
            assert target_match, f"{target} target not found"
            assert "-T" in target_match.group(0), (
                f"{target} target should use -T for non-interactive exec"
            )


# ---------------------------------------------------------------------------
# Integration — actually edit the CLI and see it reflected in the container.
# Slow; gated on HARNESS_RUN_DOCKER_TESTS=1.
# ---------------------------------------------------------------------------

_can_run_docker = (
    os.environ.get("HARNESS_RUN_DOCKER_TESTS") == "1"
    and subprocess.run(["which", "docker"], capture_output=True).returncode == 0
)

needs_docker = pytest.mark.skipif(
    not _can_run_docker,
    reason="docker integration tests disabled (set HARNESS_RUN_DOCKER_TESTS=1)",
)


@needs_docker
class TestLiveEditIntegration:
    """Full-flow smoke: set HARNESS_DEV=1, start the container with a temporary
    edit to cli/, observe the edit in the container without rebuilding the image.
    """

    def test_live_cli_edit_takes_effect(self):
        cli_init = HARNESS_ROOT / "cli" / "src" / "harness" / "__init__.py"
        original = cli_init.read_text()
        marker_version = f"0.0.0+livetest-{int(time.time())}"

        try:
            # Bump the version string — this is what `harness --version` will show.
            cli_init.write_text(
                original.replace('__version__ = "0.1.0"',
                                 f'__version__ = "{marker_version}"')
            )

            env = {**os.environ, "HARNESS_DEV": "1"}
            # Bring up the dev-mode container.
            subprocess.run(
                ["make", "-f", "env/Makefile", "up"],
                cwd=HARNESS_ROOT, env=env, check=True, capture_output=True,
            )
            try:
                # Execute harness --version inside the container.
                result = subprocess.run(
                    ["make", "-f", "env/Makefile", "shell"],
                    input=f"harness --version\n",
                    cwd=HARNESS_ROOT, env=env, capture_output=True, text=True,
                    timeout=30,
                )
                assert marker_version in result.stdout, (
                    f"live CLI edit didn't reach the container. stdout: {result.stdout}"
                )
            finally:
                subprocess.run(
                    ["make", "-f", "env/Makefile", "down"],
                    cwd=HARNESS_ROOT, env=env, capture_output=True,
                )
        finally:
            cli_init.write_text(original)
