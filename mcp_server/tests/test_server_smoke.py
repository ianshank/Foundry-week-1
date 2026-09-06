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

# Probe the package, not one major's submodule.
#
# This guard used to name `mcp.server.mcpserver`, which exists only in 2.x. The
# stated reason was that the repo's own `mcp/` directory made a bare
# `import mcp` succeed as an empty namespace package even with no SDK
# installed, so `importorskip("mcp")` never skipped. That directory was renamed
# to `mcp_server/`, and the workaround outlived the hazard: on the declared
# floor of 1.2 the submodule does not exist, so this file errored during
# collection under REQUIRE_MCP and skipped silently without it. A floor that
# cannot run its own smoke suite is not a supported version.
#
# `test_the_sdk_is_a_real_package_not_a_namespace_shim` below re-asserts the
# original hazard directly, so probing the package name stays safe.
_SDK = "mcp"

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


# --------------------------------------------------------------------------
# SDK compatibility. Both majors are supported, so both are tested: the
# installed one for real, the other through a stub. A compat path that is
# never exercised is a compat path that does not work.
# --------------------------------------------------------------------------


def test_the_sdk_is_a_real_package_not_a_namespace_shim():
    """The hazard the old submodule probe was working around, asserted directly.

    If a directory named `mcp/` ever reappears at the repo root, `import mcp`
    resolves to an empty namespace package, every skip above becomes hollow and
    this file certifies nothing. A namespace package has no `__file__`.
    """
    import mcp

    assert getattr(mcp, "__file__", None) is not None, (
        "`mcp` resolved to a namespace package, so the SDK guard is hollow. "
        "Something at the repo root is shadowing the installed SDK."
    )


def test_loader_reports_which_sdk_major_it_found():
    from foundry_spike_mcp.server import _load_server_class

    server_class, major = _load_server_class()
    assert major in (1, 2)
    assert callable(server_class)


def test_loader_falls_back_to_fastmcp_when_only_the_1x_api_exists(monkeypatch):
    """Simulates an environment the Toolkit set up on mcp 1.x."""
    import importlib
    import types

    from foundry_spike_mcp import server as server_module

    class _StubFastMCP:
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self):
            return lambda fn: fn

    stub = types.ModuleType("mcp.server.fastmcp")
    stub.FastMCP = _StubFastMCP  # type: ignore[attr-defined]

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "mcp.server.mcpserver":
            raise ImportError("No module named 'mcp.server.mcpserver'")
        if name == "mcp.server.fastmcp":
            return stub
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    server_class, major = server_module._load_server_class()
    assert server_class is _StubFastMCP
    assert major == 1


def test_missing_sdk_raises_an_actionable_message_not_a_bare_importerror(monkeypatch):
    import importlib

    from foundry_spike_mcp import server as server_module

    def fake_import(name: str, *args, **kwargs):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(RuntimeError) as caught:
        server_module._load_server_class()
    assert "pip install" in str(caught.value)



def _unwrap(result: object) -> dict:
    """Pull the tool's dict out of whatever the installed SDK major returns.

    2.x returns `(content, structured)`; 1.x returns a content list. The test
    is version-tolerant about the envelope and strict about what is inside it.
    """
    import json as _json

    if isinstance(result, tuple):
        for part in reversed(result):
            if isinstance(part, dict):
                return part.get("result", part)
    blocks = result if isinstance(result, list) else getattr(result, "content", [])
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            return _json.loads(text)
    raise AssertionError(f"no dict payload in {result!r}")

def test_the_registered_tool_actually_runs_when_the_protocol_calls_it(tmp_path, monkeypatch):
    """Registering a tool and running one are different claims.

    `list_tools` proves the wrappers were registered. Their bodies were never
    executed by any in-process test, so the one line that matters -- the wrapper
    delegating to the real implementation -- was covered only by the subprocess
    E2E, whose coverage the parent process does not see. A wrapper that
    registered and then returned the wrong thing would pass every other test in
    this file.
    """
    target = tmp_path / "repo"
    (target / "openspec").mkdir(parents=True)
    monkeypatch.setenv("PLANLINT_TARGET", str(target))
    monkeypatch.setenv("PLANLINT_ALLOWED_ROOTS", str(target))
    monkeypatch.setenv("PLANLINT_BIN", "/nonexistent/planlint-for-this-test")

    server = build_server()
    result = asyncio.run(server.call_tool("lint_openspec", {}))

    payload = _unwrap(result)
    # The binary does not exist, so the honest answer is BLOCKED -- and the
    # point is that it arrived as a verdict through the registered wrapper
    # rather than as an exception out of it.
    assert payload["verdict"] == "BLOCKED"
    assert payload["blocked_reason"] == "tool_not_found"
    assert payload["contract"]["authority"] == "exit_code"


def test_the_scorer_wrapper_also_delegates(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_SINK_DIR", str(tmp_path))
    monkeypatch.setenv("EVAL_ALLOWED_ROOTS", str(tmp_path))
    server = build_server()
    payload = _unwrap(asyncio.run(server.call_tool("score_run", {"run_id": "absent"})))
    assert payload["verdict"] == "BLOCKED"
    assert payload["blocked_reason"] == "artifact_missing"
    assert payload["pass_rate"] is None
