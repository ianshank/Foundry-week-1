"""Sanity and environment verification suite.

Validates that:
- Python environment meets 2026 enterprise runtime standards (>= 3.10).
- Required core tooling packages are installed and importable.
- Fundamental repository configuration files exist and are well-formed.
- MCP server package metadata, typing markers, and entrypoints are intact.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_sanity_python_version():
    """Verify runtime Python version meets minimum enterprise requirement (3.10+)."""
    assert sys.version_info >= (3, 10), f"Python 3.10+ required, current is {sys.version}"


@pytest.mark.parametrize(
    "package_name",
    [
        "pytest",
        "ruff",
        "mypy",
        "coverage",
        "mcp",
    ],
)
def test_sanity_core_dependencies(package_name: str) -> None:
    """Verify that required development tools and SDKs are installed."""
    try:
        mod = importlib.import_module(package_name)
        assert mod is not None
    except ImportError as err:
        if package_name != "pytest" and os.environ.get("REQUIRE_DEV_DEPS") != "1":
            pytest.skip(f"Optional/dev dependency '{package_name}' not installed in minimal environment: {err}")
        pytest.fail(f"Required dependency '{package_name}' is not installed: {err}")


@pytest.mark.parametrize(
    "rel_path",
    [
        "pyproject.toml",
        "pytest.ini",
        ".gitignore",
        ".gitleaks.toml",
        "Makefile",
        "Dockerfile",
        "README.md",
        "CHANGELOG.md",
        "NEXT_STEPS.md",
    ],
)
def test_sanity_required_repository_files(rel_path: str):
    """Verify presence and non-emptiness of core repository configuration files."""
    file_path = REPO_ROOT / rel_path
    assert file_path.exists(), f"Required file '{rel_path}' is missing."
    assert file_path.stat().st_size > 0, f"File '{rel_path}' is empty."


def test_sanity_mcp_package_typed_marker():
    """Verify PEP 561 typing marker exists in mcp_server package."""
    typed_file = REPO_ROOT / "mcp_server" / "src" / "foundry_spike_mcp" / "py.typed"
    assert typed_file.exists(), "PEP 561 py.typed marker is missing from foundry_spike_mcp."


def test_sanity_entrypoint_callability():
    """Verify that the MCP entrypoint is importable and callable."""
    from foundry_spike_mcp.__main__ import main
    from foundry_spike_mcp.server import build_server

    assert callable(main)
    assert callable(build_server)


def test_sanity_probe_package_api():
    """Verify that scripts.probe modular package exports expected symbols."""
    import scripts.probe as probe

    assert hasattr(probe, "run_probe_cells")
    assert hasattr(probe, "screen")
    assert hasattr(probe, "call_model")
    assert hasattr(probe, "HELD")
    assert hasattr(probe, "LAUNDERED")
