"""Does the thing Agent Builder connects to actually start?

This file exists because it did not exist. `server.py` was written thin so the
tool contract could be tested without the SDK, which was the right call and
also meant nothing ever imported it -- so it shipped against `FastMCP`, a name
the current SDK no longer has. Ninety passing tests said nothing about it.

These are smoke tests, not contract tests: they assert the server constructs,
both tools register, and their schemas expose the parameters the runbook's
step 4.1 agent needs. Behaviour is covered in `test_planlint_contract.py` and
`test_scoring.py`, which stay SDK-free on purpose.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# Probe the submodule, not the top-level name. This repo has its own `mcp/`
# directory, so with the repo root on sys.path `import mcp` succeeds even with
# no SDK installed -- it resolves to an empty namespace package. (At runtime a
# real installed package outranks a namespace portion, so the server itself is
# unaffected; only a bare `import mcp` guard is fooled.) `importorskip("mcp")`
# therefore never skipped, and the suite errored instead.
_SDK = "mcp.server.mcpserver"

# Locally the SDK is optional -- `make test` before `make setup` should still
# run the contract suite. In CI it is mandatory, because a skip that can
# silently cover the blocker *is* the blocker: the broken import shipped under
# a green run for exactly this reason.
if os.environ.get("REQUIRE_MCP"):
    __import__(_SDK)
else:
    pytest.importorskip(_SDK, reason="MCP SDK not installed; contract tests cover the tool logic")

from foundry_spike_mcp.server import build_server  # noqa: E402


def _tools():
    return {tool.name: tool for tool in asyncio.run(build_server().list_tools())}


def _schema(tool) -> dict:
    # 2.x renamed inputSchema -> input_schema. Tolerated here so a future
    # rename fails the *pin*, not this assertion.
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {}) or {}


def test_server_builds():
    assert build_server() is not None


def test_both_tools_register_and_no_others():
    """Runbook step 4.1: the agent gets these two tools and nothing else."""
    assert set(_tools()) == {"lint_openspec", "score_run"}


def test_lint_openspec_exposes_target_and_fail_on():
    properties = _schema(_tools()["lint_openspec"]).get("properties", {})
    assert {"target", "fail_on"} <= set(properties)


def test_score_run_exposes_run_id():
    schema = _schema(_tools()["score_run"])
    properties = schema.get("properties", {})
    assert "run_id" in properties
    # run_id is the only required argument; artifact_path is the escape hatch.
    assert schema.get("required", ["run_id"]) == ["run_id"]


@pytest.mark.parametrize(
    ("tool_name", "phrase"),
    [
        ("lint_openspec", "must never be reported as a pass"),
        ("score_run", "neither a pass nor a failure"),
    ],
)
def test_descriptions_carry_the_authority_boundary(tool_name, phrase):
    """The tool description is the only part of the contract the model reads
    before deciding to call. If the BLOCKED and null rules fall out of these
    docstrings, the guard rails are code-only and the model never sees them."""
    assert phrase in (_tools()[tool_name].description or "")
