"""Regression guards: a developer's shell must not be able to decide a verdict.

Both suites clear the tool variables before every test so a real
`PLANLINT_TARGET` cannot leak in and make a guard pass for the wrong reason.
That was true of the root suite and only partly true of the package suite,
which cleared a hand-written seven names against a `config.py` declaring
fifteen -- and the eight it missed were not decorative:

    EVAL_MAX_ARTIFACT_BYTES=1     -> 18 failures in test_scoring.py
    FOUNDRY_SPIKE_STDOUT_LIMIT=1  -> test_exit_two_is_blocked_not_pass fails

The probe plane was worse, because there the leak produced a *false pass*
rather than a failure. `PROBE_TIMEOUT=abc` makes `probe.cli.main` report
through `parser.error`, which exits 2 -- and `test_probe_exit_contract.py`
reads exit 2 as "no model answered". All three D-03 guards went green having
never reached `run_probe_cells`, in the file whose subject is a system that
reports a non-result as a pass.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_SRC = _REPO_ROOT / "mcp_server" / "src" / "foundry_spike_mcp"

def _poison() -> dict[str, str]:
    """Values known to change a result if they leak, keyed on the real names.

    Keyed on the `ENV_*` constants rather than string literals, and the reason
    is the same one this file's other test enforces on `src/`: a literal here
    that drifts from the name the code reads poisons a variable nothing looks
    at, the child suite passes, and **this test goes green having injected
    nothing**. Every other guard in this file fails safe; that one would fail
    silent, which is the worse direction.

    Each value was measured failing before the isolation fixtures were
    widened; the comments record which way.
    """
    from foundry_spike_mcp.config import ENV_EVAL_MAX_ARTIFACT_BYTES, ENV_STDOUT_LIMIT
    from probe.config import ENV_PROBE_TIMEOUT

    return {
        ENV_EVAL_MAX_ARTIFACT_BYTES: "1",   # 18 failures in test_scoring.py
        ENV_STDOUT_LIMIT: "1",              # test_exit_two_is_blocked_not_pass
        ENV_PROBE_TIMEOUT: "abc",           # three D-03 guards falsely green
    }

#: The files the poison above actually reaches. Scoped rather than the whole
#: suite so this stays a guard and not a second full run.
_TARGETS = (
    "mcp_server/tests/test_planlint_contract.py",
    "mcp_server/tests/test_scoring.py",
    "tests/test_cli_entrypoints.py",
    "tests/regression/test_probe_exit_contract.py",
)


def test_a_poisoned_shell_cannot_change_a_contract_result() -> None:
    """The isolation fixtures exist so a shell cannot decide a verdict.

    Run in a subprocess because the thing under test *is* a pytest fixture:
    you cannot assert on the isolation from inside the session it is already
    protecting -- by the time this test body runs, the fixture has already
    cleaned the environment it would be asserting about.
    """
    poison = _poison()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *_TARGETS],
            cwd=_REPO_ROOT,
            env={**os.environ, **poison},
            capture_output=True,
            text=True,
            # Bounded because one of the targets deliberately spawns processes
            # that never exit. Without a ceiling, a deadlocked child holds the
            # parent until GitHub's six-hour job limit instead of failing in
            # five minutes -- and every other subprocess boundary in this repo
            # treats a missing timeout as a defect.
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the poisoned child suite hung; it should finish well inside 300s")

    assert result.returncode == 0, (
        "A poisoned shell changed the result of the contract suite.\n"
        f"Injected: {poison}\n\n" + result.stdout[-4000:]
    )


def test_the_isolation_list_is_derived_from_config_not_typed_out() -> None:
    """Read `config.py` with the AST, not by importing it.

    Comparing the fixture's reflection against the same reflection would be a
    tautology that passes no matter what either side says. Parsing the source
    is a second, independent route to the same fact, so this fails if the
    fixture is ever replaced by a literal tuple -- which is exactly how
    `mcp_server/tests/conftest.py` came to be missing eight of the fifteen
    names it claimed to cover.
    """
    tree = ast.parse((_PACKAGE_SRC / "config.py").read_text(encoding="utf-8"))
    declared = {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("ENV_")
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }

    # Loaded by path, not by name. Both suites have a module called
    # `conftest`, the root one is already in `sys.modules` by the time this
    # runs, and a plain import would silently assert against the wrong file --
    # passing while the package suite's list stayed broken.
    package_conftest = _REPO_ROOT / "mcp_server" / "tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location("_package_conftest", package_conftest)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert set(module.configured_env_names()) == declared, (
        "The package suite's isolation list has drifted from config.py's ENV_* names."
    )


def test_no_module_reads_an_environment_variable_by_string_literal() -> None:
    """A bare `os.environ.get("PROBE_TOP_P", ...)` is two defects at once.

    It is a typo away from a silently-ignored setting, which is the worst
    failure mode a configuration can have; and it is invisible to the
    isolation fixtures, which derive what they clear from the `ENV_*`
    constants. Every name that was read as a literal -- the three
    `SELFCHECK_*` and the five `PROBE_*` -- was therefore also a name no test
    ever cleared.
    """
    offenders: list[str] = []
    for root in (_PACKAGE_SRC, _REPO_ROOT / "scripts"):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                reads_env = (
                    isinstance(func, ast.Attribute)
                    and func.attr in {"get", "getenv"}
                    and (
                        (isinstance(func.value, ast.Attribute) and func.value.attr == "environ")
                        or (isinstance(func.value, ast.Name) and func.value.id in {"environ", "os"})
                    )
                )
                if reads_env and isinstance(node.args[0], ast.Constant):
                    rel = path.relative_to(_REPO_ROOT).as_posix()
                    offenders.append(f"{rel}:{node.lineno} {node.args[0].value!r}")

    assert not offenders, (
        "These read an environment variable by string literal instead of an "
        "ENV_* constant, so the isolation fixtures cannot see them:\n  "
        + "\n  ".join(offenders)
    )
