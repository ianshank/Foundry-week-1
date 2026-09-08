"""AQA (Acceptance Quality Assurance) test layer.

These tests validate the cross-platform stub infrastructure itself — the
``make_stub`` fixture and the ``spec_repo`` fixture — to ensure the testing
harness is reliable before trusting results from other layers.

AQA invariant: if a test in this layer fails, the failure is in the *test
infrastructure*, not in the production code. That is the opposite of a unit
test, and it means a failure here should block all other test layers.

Tests are marked ``@pytest.mark.aqa`` (registered in ``pytest.ini``).
Run with ``make aqa`` or ``pytest -m aqa``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.aqa

# ---------------------------------------------------------------------------
# AQA-01: make_stub — cross-platform executable correctness
# ---------------------------------------------------------------------------


class TestMakeStubInfrastructure:
    """Validates that the make_stub fixture produces a working executable.

    These tests are deterministic: they verify the infrastructure contract,
    not the production code. A failure here means the fixture itself is broken.
    """

    def test_stub_exits_zero_for_zero_body(self, make_stub) -> None:  # type: ignore[no-untyped-def]
        """A stub that calls sys.exit(0) must exit with returncode 0."""
        stub = make_stub("import sys\nsys.exit(0)\n")
        result = subprocess.run([str(stub)], capture_output=True, timeout=10)
        assert result.returncode == 0, (
            f"make_stub produced a stub that exited {result.returncode} instead of 0. "
            f"stderr: {result.stderr!r}"
        )

    def test_stub_exits_one_for_one_body(self, make_stub) -> None:  # type: ignore[no-untyped-def]
        """A stub that calls sys.exit(1) must exit with returncode 1."""
        stub = make_stub("import sys\nsys.exit(1)\n")
        result = subprocess.run([str(stub)], capture_output=True, timeout=10)
        assert result.returncode == 1

    def test_stub_exits_two_for_two_body(self, make_stub) -> None:  # type: ignore[no-untyped-def]
        """A stub that calls sys.exit(2) must exit with returncode 2 (BLOCKED path)."""
        stub = make_stub("import sys\nsys.exit(2)\n")
        result = subprocess.run([str(stub)], capture_output=True, timeout=10)
        assert result.returncode == 2

    def test_stub_ascii_stdout_survives_pipe(self, make_stub) -> None:  # type: ignore[no-untyped-def]
        """ASCII bytes written to sys.stdout.buffer must survive the pipe intact."""
        payload = b'{"findings": []}'
        body = f"import sys\nsys.stdout.buffer.write({payload!r})\nsys.exit(0)\n"
        stub = make_stub(body)
        result = subprocess.run([str(stub)], capture_output=True, timeout=10)
        assert result.returncode == 0
        assert result.stdout == payload, (
            f"Expected {payload!r}, got {result.stdout!r}. "
            "ASCII bytes were corrupted in the pipe."
        )

    def test_stub_utf8_payload_survives_pipe(self, make_stub) -> None:  # type: ignore[no-untyped-def]
        """CJK characters written as UTF-8 bytes must survive the pipe on all platforms.

        This is the AQA guard for D-02: on Windows with cp1252, sys.stdout.write(str)
        raised UnicodeEncodeError. sys.stdout.buffer.write(bytes) must not.
        """
        payload_obj = {"verdict": "FINDINGS", "m": "\u6f22\u5b57" * 5}
        payload_bytes = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
        body = f"import sys\nsys.stdout.buffer.write({payload_bytes!r})\nsys.exit(1)\n"
        stub = make_stub(body)
        result = subprocess.run([str(stub)], capture_output=True, timeout=10)
        assert result.returncode == 1
        decoded = json.loads(result.stdout.decode("utf-8"))
        assert decoded == payload_obj, (
            f"UTF-8 payload was corrupted. got: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "payload",
        [
            b'{"findings": []}',
            b'{"findings": null, "verdict": "BLOCKED"}',
            b"null",
            b"[]",
        ],
    )
    def test_stub_various_json_payloads_survive(
        self,
        make_stub,  # type: ignore[no-untyped-def]
        payload: bytes,
    ) -> None:
        """Various JSON shapes must survive the pipe without corruption."""
        body = f"import sys\nsys.stdout.buffer.write({payload!r})\nsys.exit(0)\n"
        stub = make_stub(body)
        result = subprocess.run([str(stub)], capture_output=True, timeout=10)
        assert result.returncode == 0
        assert result.stdout == payload


# ---------------------------------------------------------------------------
# AQA-02: spec_repo — directory structure correctness
# ---------------------------------------------------------------------------


class TestSpecRepoInfrastructure:
    """Validates the spec_repo fixture creates the expected directory tree."""

    def test_spec_repo_creates_openspec_changes(self, spec_repo: Path) -> None:
        """spec_repo must contain openspec/changes/ for lint_openspec to accept it."""
        assert (spec_repo / "openspec" / "changes").is_dir(), (
            f"spec_repo at {spec_repo} is missing openspec/changes/. "
            "lint_openspec requires this directory tree."
        )

    def test_spec_repo_is_a_directory(self, spec_repo: Path) -> None:
        assert spec_repo.is_dir()

    def test_spec_repo_is_under_tmp_path(self, spec_repo: Path, tmp_path: Path) -> None:
        """spec_repo must be inside tmp_path to guarantee isolation."""
        assert spec_repo.is_relative_to(tmp_path), (
            f"spec_repo ({spec_repo}) is not under tmp_path ({tmp_path}). "
            "Tests would share state between runs."
        )


# ---------------------------------------------------------------------------
# AQA-03: Platform assertions
# ---------------------------------------------------------------------------


class TestPlatformAssertions:
    """Validates that platform detection behaves as expected for CI consumers."""

    def test_sys_platform_is_known_value(self) -> None:
        """sys.platform must be one of the known values CI uses to branch on."""
        known_platforms = {"linux", "win32", "darwin", "cygwin"}
        # sys.platform on Linux is 'linux', not 'linux2' in Python 3.3+
        assert any(sys.platform.startswith(p) for p in known_platforms), (
            f"sys.platform is {sys.platform!r}, which is not a recognised value. "
            "Platform-conditional code (make_stub, skipif decorators) may misbehave."
        )

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows-specific: .bat launcher must not be created on POSIX",
    )
    def test_make_stub_creates_bat_on_windows(self, make_stub) -> None:  # type: ignore[no-untyped-def]
        """On Windows, make_stub must produce a .bat file, not a shebang script."""
        stub = make_stub("import sys\nsys.exit(0)\n")
        assert stub.suffix == ".bat", (
            f"Expected a .bat file on Windows, got {stub} ({stub.suffix}). "
            "The WinError 193 fix is broken."
        )

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="POSIX-specific: shebang launcher must not be .bat on Linux/macOS",
    )
    def test_make_stub_creates_shebang_on_posix(self, make_stub) -> None:  # type: ignore[no-untyped-def]
        """On POSIX, make_stub must produce a shebang script with no extension."""
        stub = make_stub("import sys\nsys.exit(0)\n")
        assert stub.suffix == "", (
            f"Expected no extension for a shebang script on POSIX, got {stub} ({stub.suffix})."
        )
        first_line = stub.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("#!"), (
            f"Shebang script must start with #!, got: {first_line!r}"
        )
