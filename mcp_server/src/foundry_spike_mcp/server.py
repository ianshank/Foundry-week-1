"""stdio MCP server exposing the two read-only tools.

Deliberately thin. All behaviour lives in `planlint` and `scoring`, which
import nothing from the MCP SDK -- so the contract under test is testable
without a server, and swapping transports later cannot change a verdict.

That separation earned its keep and then cost something: because the tool
tests need no SDK, the first version of this file was never imported by
anything, and it shipped importing `mcp.server.fastmcp`, which does not exist
in the SDK a fresh `pip install` resolves to. `test_server_smoke.py` now builds
this server and lists its tools, and CI runs it as its own job with the SDK
installed, so the transport cannot rot unnoticed again.

**SDK compatibility.** `FastMCP` (mcp 1.x) was renamed `MCPServer` (mcp 2.x);
the `.tool()` decorator and `.run()` entry point are otherwise unchanged.
`_load_server_class` accepts either, newest first. This matters beyond
tidiness: Agent Builder's own Python scaffold and whatever is already in a
developer's environment may be on either major, and a spike that refuses to
start on the version already installed is a spike nobody runs.

Register in Agent Builder via
    Tool -> + MCP Server -> Connect to an Existing MCP Server -> Command (stdio)
with the command and args from `mcp_server/mcp.json.example`, or press F5 from
the scaffold's debug panel. Expect the Toolkit to fail the first tool-add and
open `mcp.json` for the environment variables; that is the documented flow, not
a bug.

To be exact about what refuses, because an earlier wording here said the server
does and that is wrong: the **process starts** without an allow list and its
tools register. Every *tool call* then returns BLOCKED with `no_allowed_roots`
until one is set. That is the intended shape -- the guard fails closed, and it
does so as a verdict rather than as a crash, which is the whole contract.
"""

from __future__ import annotations

from typing import Any

from .logging_setup import get_logger
from .planlint import lint_openspec as _lint_openspec
from .scoring import score_run as _score_run

SERVER_NAME = "foundry-spike"

#: Candidate SDK entry points, newest major first. A fresh install resolves to
#: 2.x, so that is tried first; 1.x stays supported because it may already be
#: in the environment the Toolkit set up.
_SDK_CANDIDATES = (
    ("mcp.server.mcpserver", "MCPServer", 2),
    ("mcp.server.fastmcp", "FastMCP", 1),
)

_log = get_logger("server")


def _load_server_class() -> tuple[Any, int]:
    """Return ``(server_class, sdk_major)`` for whichever SDK is installed.

    Raises `RuntimeError` with an actionable message rather than letting an
    `ImportError` surface: "No module named 'mcp.server.fastmcp'" sent one
    reviewer looking for a typo in this file when the real answer was a major
    version bump.
    """
    import importlib

    attempts: list[str] = []
    for module_name, class_name, major in _SDK_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ImportError as error:
            attempts.append(f"{module_name}: {error}")
            continue
        server_class = getattr(module, class_name, None)
        if server_class is None:
            attempts.append(f"{module_name}: no attribute {class_name}")
            continue
        _log.debug("using MCP SDK major %s via %s.%s", major, module_name, class_name)
        return server_class, major

    raise RuntimeError(
        "No supported MCP SDK found. Install one with `pip install -e ./mcp_server` "
        "(pinned >=1.2,<3). Tried: " + "; ".join(attempts)
    )


def build_server() -> Any:
    """Construct the MCP server and register both tools.

    The SDK import is deferred into this function so that `pytest` can
    exercise the tool contract with no third-party dependency installed.
    """
    server_class, _major = _load_server_class()
    server = server_class(SERVER_NAME)

    @server.tool()
    def lint_openspec(target: str | None = None, fail_on: str = "ERROR") -> dict[str, Any]:
        """Validate OpenSpec specs with planlint (read-only).

        Returns a three-way verdict derived from planlint's exit code:
        PASS (exit 0, no findings at or above the threshold), FINDINGS (exit 1,
        the run completed and found problems), or BLOCKED (exit 2 or an
        infrastructure failure -- the run could not form an opinion).

        BLOCKED is not a spec failure and must never be reported as a pass.
        The exit code is authoritative; the findings payload is evidence.
        """
        return _lint_openspec(target=target, fail_on=fail_on)

    @server.tool()
    def score_run(run_id: str, artifact_path: str | None = None) -> dict[str, Any]:
        """Read one eval-harness run artifact and report per-scorer verdicts.

        Each scorer's `passed` is true, false, or null. null means the scorer
        produced no verdict (e.g. a trajectory scorer with no trajectory); it
        is excluded from `pass_rate` and is neither a pass nor a failure.
        `pass_rate` is null when nothing was scored.
        """
        return _score_run(run_id=run_id, artifact_path=artifact_path)

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
