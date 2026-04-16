"""End-to-end test that the dev image runs as a non-root user matching the
host caller, with root available via --user root.

Slow test — it builds an image and spins up a container. Gated on the
HARNESS_RUN_DOCKER_TESTS env var so the default `pytest tests/` stays fast.
Run with:

    HARNESS_RUN_DOCKER_TESTS=1 pytest tests/test_container_user.py -v
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

needs_docker = pytest.mark.skipif(
    os.environ.get("HARNESS_RUN_DOCKER_TESTS") != "1"
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="docker integration tests disabled (set HARNESS_RUN_DOCKER_TESTS=1)",
)

HARNESS_ROOT = Path(__file__).resolve().parents[2]
TAG = "harness-dev-test-nonroot"


def _build(uid: int, gid: int) -> None:
    subprocess.run(
        [
            "docker", "build",
            "--build-arg", f"HOST_UID={uid}",
            "--build-arg", f"HOST_GID={gid}",
            "-f", str(HARNESS_ROOT / "env" / "Dockerfile"),
            "-t", TAG,
            str(HARNESS_ROOT),
        ],
        check=True,
        capture_output=True,
    )


def _run(*args, user: str | None = None, work_mount: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["docker", "run", "--rm"]
    if user is not None:
        cmd += ["--user", user]
    if work_mount is not None:
        cmd += ["-v", f"{work_mount}:/work"]
    cmd += [TAG, *args]
    return subprocess.run(cmd, capture_output=True, text=True)


@needs_docker
class TestContainerUser:
    # We pin to a non-root test UID/GID so the test works even when the
    # test runner itself is running as root (e.g. inside Docker-in-Docker).
    # A UID of 0 would collide with the root entry in /etc/passwd and make
    # `whoami` / $HOME resolve to root, not harness.
    TEST_UID = 1001
    TEST_GID = 1001

    @classmethod
    def setup_class(cls):
        cls.host_uid = cls.TEST_UID
        cls.host_gid = cls.TEST_GID
        _build(cls.host_uid, cls.host_gid)

    @classmethod
    def teardown_class(cls):
        subprocess.run(["docker", "rmi", TAG], capture_output=True)

    def test_default_user_is_harness(self):
        r = _run("whoami")
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "harness"

    def test_default_uid_matches_host(self):
        r = _run("id -u")
        assert r.returncode == 0, r.stderr
        assert int(r.stdout.strip()) == self.host_uid

    def test_default_gid_matches_host(self):
        r = _run("id -g")
        assert r.returncode == 0, r.stderr
        assert int(r.stdout.strip()) == self.host_gid

    def test_home_directory_is_home_harness(self):
        r = _run("echo $HOME")
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "/home/harness"

    def test_root_available_with_user_root_override(self):
        r = _run("whoami", user="root")
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "root"

    def test_sudo_works_without_password(self):
        """The harness user has passwordless sudo for tool install at runtime."""
        r = _run("sudo -n true")
        assert r.returncode == 0, r.stderr

    def test_harness_cli_is_on_path(self):
        r = _run("which harness")
        assert r.returncode == 0, r.stderr
        assert "/harness" in r.stdout  # some path ending in .../harness

    def test_bind_mounted_work_is_writable_and_host_owned(self, tmp_path):
        """Real use case: /work is bind-mounted from a host-owned dir.

        We create the dir with the same UID the container runs as, so the
        container's harness user can write into it, and the host user sees
        those writes as their own.
        """
        os.chown(tmp_path, self.host_uid, self.host_gid)
        r = _run("bash -c 'touch /work/from-container && echo ok'",
                 work_mount=str(tmp_path))
        assert r.returncode == 0, r.stderr
        assert "ok" in r.stdout
        created = tmp_path / "from-container"
        assert created.exists()
        assert created.stat().st_uid == self.host_uid
