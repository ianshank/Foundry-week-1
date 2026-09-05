"""Read-only MCP tools over `planlint` and the eval-harness sink, for the
Foundry Toolkit week-1 spike.

Two tools, both read-only, both subprocess-or-file callers. No imports of
`openspec_graph` or eval-harness internals -- see `scoring` for why that
constraint is load-bearing rather than stylistic.
"""

from .planlint import lint_openspec
from .scoring import score_run
from .verdicts import BLOCKED, FINDINGS, PASS

__all__ = ["lint_openspec", "score_run", "PASS", "FINDINGS", "BLOCKED"]
__version__ = "0.1.0"
