"""stdio MCP server exposing the two read-only tools.

Deliberately thin. All behaviour lives in `planlint` and `scoring`, which
import nothing from the MCP SDK -- so the contract under test is testable
without a server, and swapping transports later cannot change a verdict.

That separation earned its keep and then cost something: because the tool
tests need no SDK, the first version of this file was never imported by
anything, and it shipped importing `mcp.server.fastmcp`, which does not exist
in the SDK a fresh `pip install` resolves to. `FastMCP` was renamed
`MCPServer` in mcp 2.0. `test_server_smoke.py` now builds this server and
lists its tools, so the transport cannot rot unnoticed again.

The dependency is pinned `>=2.1,<3`: an open upper bound is what turned a
rename in someone else's major version into a broken deliverable here.

Register in Agent Builder via
    Tool -> + MCP Server -> Connect to an Existing MCP Server -> Command (stdio)
with command `uv` and args `run --directory <repo>/mcp foundry-spike-mcp`,
or press F5 from the scaffold's debug panel. Expect the Toolkit to fail the
first tool-add and open `mcp.json` for the environment variables; that is the
documented flow, not a bug.
"""

from __future__ import annotations

from typing import Any

from .planlint import lint_openspec as _lint_openspec
from .scoring import score_run as _score_run


def build_server() -> Any:
    """Construct the MCP server and register both tools.

    The SDK import is local so that `pytest` can exercise the tool contract
    with no third-party dependency installed.
    """
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("foundry-spike")

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
