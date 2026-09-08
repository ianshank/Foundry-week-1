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


def test_no_subprocess_wait_is_unbounded():
    """A wrapper that can hang has no BLOCKED path, it just stops answering.

    The invariant is unchanged; the shape it has to recognise is not. This
    check used to require `timeout=` on the call that *starts* the process,
    including `subprocess.Popen` -- which does not take one, because with
    `Popen` the bound belongs on the wait. So the old form would have rejected
    every correct use of `Popen` while passing a `communicate()` with no
    timeout at all, which is the actual hang.

    It now checks the two shapes separately, and is strictly stricter than
    before: the blocking one-shot helpers still need `timeout=`, and every
    `communicate()` and `wait()` in the module is checked too.
    """
    source = (SRC / "planlint.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    def _attribute_calls(names: set[str], receiver: str | None = None) -> list[ast.Call]:
        found = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in names:
                continue
            if receiver is not None:
                value = node.func.value
                if not (isinstance(value, ast.Name) and value.id == receiver):
                    continue
            found.append(node)
        return found

    def _has_timeout(call: ast.Call) -> bool:
        return any(keyword.arg == "timeout" for keyword in call.keywords)

    # 1. The blocking one-shot helpers take the bound at the call site.
    one_shot = _attribute_calls({"run", "call", "check_output", "check_call"}, "subprocess")
    for call in one_shot:
        assert _has_timeout(call), f"subprocess call at line {call.lineno} has no timeout"

    # 2. `Popen` defers the wait, so the bound has to be on the wait instead.
    spawned = _attribute_calls({"Popen"}, "subprocess")
    waits = _attribute_calls({"communicate", "wait"})
    assert one_shot or spawned, "expected planlint.py to shell out"

    if spawned:
        assert waits, "planlint.py spawns a process and never bounds the wait on it"
        bounded = [call for call in waits if _has_timeout(call)]
        assert bounded, "no communicate()/wait() carries a timeout; the wrapper can hang"

    # 3. An unbounded wait is allowed only where the process is already dead --
    #    the post-kill drain. Anything else is a hang waiting to happen.
    #    Scoped to the *body* of `_drain`, not to everything after its `def`.
    #    The first version of this rule compared line numbers against the
    #    definition line, so every later call in the file counted as "inside"
    #    it -- and a mutation removing the real timeout passed. A check that
    #    cannot fail is worse than no check, because it is trusted.
    drain_body = next(
        (
            range(node.lineno, (node.end_lineno or node.lineno) + 1)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_drain"
        ),
        None,
    )
    for call in waits:
        if _has_timeout(call):
            continue
        attr = call.func.attr  # type: ignore[union-attr]
        assert drain_body is not None and call.lineno in drain_body, (
            f"unbounded {attr}() at line {call.lineno}: only the post-kill drain "
            "may wait without a bound, because there the process is already dead"
        )
