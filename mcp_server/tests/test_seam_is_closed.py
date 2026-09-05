"""Stop conditions 2 and 3, enforced by the test suite rather than by memory.

Runbook stop condition 3: "Wrapping the scorer requires importing eval-harness
internals rather than reading sink output. That means the seam is wrong and
the eval plane stays closed for now."

A stop condition that only lives in a markdown file gets crossed during a
debugging session at 11pm and nobody notices. This test fails instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "foundry_spike_mcp"

#: Modules that would mean the wrapper had stopped being a subprocess/file
#: caller and started being a coupling.
FORBIDDEN_ROOTS = {"openspec_graph", "openspec", "planlint", "eval_harness", "evalharness"}

TOOL_MODULES = ["planlint.py", "scoring.py", "guards.py", "verdicts.py"]


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module", TOOL_MODULES)
def test_tools_do_not_import_the_systems_they_wrap(module):
    offending = _imported_roots(SRC / module) & FORBIDDEN_ROOTS
    assert not offending, (
        f"{module} imports {sorted(offending)}. The wrapper must stay a subprocess "
        "and file caller -- an import here is runbook stop condition 3, not a fix."
    )


@pytest.mark.parametrize("module", TOOL_MODULES)
def test_tool_logic_does_not_depend_on_the_mcp_sdk(module):
    """The contract under test must be testable without a transport."""
    assert "mcp" not in _imported_roots(SRC / module)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """ids() of the Constant nodes that are docstrings, so prose about a
    forbidden value is not mistaken for the value itself."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


@pytest.mark.parametrize("module", TOOL_MODULES)
def test_no_fourth_verdict_string_can_be_returned(module):
    """`UNKNOWN` is a state the agent instructions define no behaviour for.

    Checked against executable string literals only -- the docstrings explain
    why the runbook's UNKNOWN was dropped, and that explanation should stay.
    """
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    assert "UNKNOWN" not in literals


def test_subprocess_is_only_ever_invoked_with_a_timeout():
    """A wrapper that can hang has no BLOCKED path, it just stops answering."""
    source = (SRC / "planlint.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"run", "call", "check_output", "check_call", "Popen"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    assert calls, "expected planlint.py to shell out"
    for call in calls:
        assert any(kw.arg == "timeout" for kw in call.keywords), (
            f"subprocess call at line {call.lineno} has no timeout"
        )
