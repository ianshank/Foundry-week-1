"""Regression test suite - guarding against previously fixed defects.

Every test here is a regression guard for a specific finding that was once broken
and fixed. If one of these fails, it means a fix was reverted.

Cross-referenced to:
- NEXT_STEPS.md D-01/D-02 (Windows platform-parity: shebang + encoding)
- Finding F4 (RecursionError escaped score_run)
- Finding F5 (unstable envelope shape)
- Finding F9 (unreachable verbs)
- Finding F14 (coverage gate)

Fixtures `make_stub` and `spec_repo` are provided by `tests/conftest.py`
and represent the canonical cross-platform executable factory for this repo.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

from foundry_spike_mcp.config import EvalConfig, PlanlintConfig
from foundry_spike_mcp.guards import ALLOWED_VERBS, REFUSED_VERBS
from foundry_spike_mcp.planlint import lint_openspec, run_verb
from foundry_spike_mcp.scoring import score_run
from foundry_spike_mcp.verdicts import (
    BLOCKED,
    BLOCKED_ARTIFACT_UNREADABLE,
    BLOCKED_GUARD_REJECTED,
    BLOCKED_UNEXPECTED_EXIT,
    FINDINGS,
    PASS,
)

# sys.path is managed by pytest.ini pythonpath + tests/conftest.py.
# No manual sys.path manipulation needed here.

pytestmark = pytest.mark.regression


# ---------------------------------------------------------------------------
# D-01/D-02 Windows platform parity
# ---------------------------------------------------------------------------

class TestWindowsPlatformParity:
    """Regression guards for D-01 (shebang WinError 193) and D-02 (cp1252 encoding)."""

    def test_ascii_payload_stub_executes(self, make_stub, spec_repo: Path) -> None:
        """D-01: .bat launcher works on Windows; shebang works on POSIX."""
        stub = make_stub('import sys\nsys.stdout.buffer.write(b\'{"findings": []}\')\nsys.exit(0)\n')
        cfg = PlanlintConfig(binary=str(stub), target=str(spec_repo), allowed_roots=(spec_repo,))
        assert lint_openspec(config=cfg)["verdict"] == PASS

    def test_cjk_payload_survives_round_trip(self, make_stub, spec_repo: Path) -> None:
        """D-02: CJK characters in planlint stdout must survive without UnicodeEncodeError."""
        payload = json.dumps({"m": "\u6f22" * 10}, ensure_ascii=False)
        stub = make_stub(
            f'import sys\nsys.stdout.buffer.write({payload.encode("utf-8")!r})\nsys.exit(1)\n'
        )
        cfg = PlanlintConfig(binary=str(stub), target=str(spec_repo), allowed_roots=(spec_repo,))
        result = lint_openspec(config=cfg)
        assert result["verdict"] == FINDINGS
        assert result["findings"] == {"m": "\u6f22" * 10}

    def test_invalid_bytes_produce_parse_error_not_exception(
        self, make_stub, spec_repo: Path
    ) -> None:
        """D-02b: Raw bytes invalid in any encoding must produce a parse error, not an exception."""
        stub = make_stub('import sys\nsys.stdout.buffer.write(b"\\xff\\xfe\\xff")\nsys.exit(1)\n')
        cfg = PlanlintConfig(binary=str(stub), target=str(spec_repo), allowed_roots=(spec_repo,))
        result = lint_openspec(config=cfg)
        assert result["verdict"] == FINDINGS
        assert result["findings"] is None
        assert result["findings_parse_error"] is not None

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "POSIX signals (SIGKILL) are not applicable on Windows. "
            "The negative-returncode contract is covered by in-process "
            "exit-code parametrize tests in test_planlint_contract.py."
        ),
    )
    def test_signal_killed_process_maps_to_blocked_unexpected_exit(
        self, make_stub, spec_repo: Path
    ) -> None:
        """D-02c: A process killed by SIGKILL produces a negative returncode -> BLOCKED."""
        stub = make_stub(
            "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n",
            name="kill-stub",
        )
        cfg = PlanlintConfig(binary=str(stub), target=str(spec_repo), allowed_roots=(spec_repo,))
        result = lint_openspec(config=cfg)
        assert result["verdict"] == BLOCKED
        assert result["blocked_reason"] == BLOCKED_UNEXPECTED_EXIT
        assert result["exit_code"] is not None and result["exit_code"] < 0




# ---------------------------------------------------------------------------
# D-02, everywhere -- not just where the canonical factory is used.
# ---------------------------------------------------------------------------

#: Both suite roots. `mcp_server/tests/` must import with neither `scripts/`
#: nor this directory on the path -- that is what `cd mcp_server && pytest` and
#: the Docker `contract` stage do -- so a single shared stub factory is
#: impossible and two canonical ones is the correct number. There is therefore
#: no runtime seam where this could be checked once. Reading the source is the
#: only mechanism that survives the import boundary.
_SUITE_ROOTS = (
    Path(__file__).resolve().parents[2] / "tests",
    Path(__file__).resolve().parents[2] / "mcp_server" / "tests",
)


def _enclosing_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _own_nodes(function: ast.AST) -> list[ast.AST]:
    """Every node lexically inside `function`, excluding nested `def` bodies.

    Stopping at nested function boundaries matters: the factories in this
    repository are inner `_create` / `_make` / `_factory` closures inside
    fixture functions, so a plain `ast.walk` attributes the same violation to
    both the closure and its enclosing fixture, reporting one defect twice.
    """
    own: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        own.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return own


#: Ways a stub body can put text on stdout through the console code page.
#: `print` is on this list because it is what `tests/journey/` actually used
#: before this branch -- an earlier version of the rule matched only
#: `sys.stdout.write(` and would have missed the real site, which was caught by
#: the other half of the rule by luck rather than by design.
_TEXT_STDOUT_WRITES = ("sys.stdout.write(", "sys.stdout.writelines(", "print(")

#: The only exculpation: bytes straight at the buffer, which no code page sees.
_BYTES_STDOUT_WRITE = "sys.stdout.buffer"

#: `@set PYTHONUTF8=1`, not merely the word. A bare substring test was
#: satisfied by `@rem PYTHONUTF8 not set`.
_UTF8_ENABLED = re.compile(r"PYTHONUTF8\s*=\s*1")

#: Methods that write a file. `write_text` alone missed `write_bytes` and the
#: `open(...)` form.
_WRITE_METHODS = frozenset({"write_text", "write_bytes"})


def _bat_valued_names(function: ast.AST) -> set[str]:
    """Local names that end up holding a `.bat` path.

    `bat = script_dir / f"{name}.bat"` then `bat.write_text(...)` is the shape
    every factory here uses, so the write site alone does not say what is being
    written.

    Three shapes beyond the obvious one, each of which was an evasion:

    * `bat: Path = d / (name + ".bat")` -- an `ast.AnnAssign`. This is the same
      node type the policy guard one directory over has a docstring about
      ("Handling `ast.AnnAssign` is not tidiness"); it was fixed there and
      reintroduced here in the same branch.
    * `(bat := ...)` -- an `ast.NamedExpr`.
    * `ext = ".bat"` then `bat = d / (name + ext)` -- the extension arrives
      through a variable, so the assignment that builds the path contains no
      `.bat` at all. Resolved by seeding from string constants first and
      running to a fixed point.
    """
    literal_bat: set[str] = set()
    bindings: list[tuple[str, str]] = []

    for node in _own_nodes(function):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif (
            isinstance(node, (ast.AnnAssign, ast.NamedExpr))
            and isinstance(node.target, ast.Name)
            and node.value
        ):
            targets, value = [node.target.id], node.value
        else:
            continue
        rendered = ast.unparse(value)
        for target in targets:
            if ".bat" in rendered:
                literal_bat.add(target)
            bindings.append((target, rendered))

    # Fixed point: a name built from a name that holds ".bat" also holds one.
    changed = True
    while changed:
        changed = False
        for target, rendered in bindings:
            if target in literal_bat:
                continue
            if any(re.search(r"\b" + re.escape(known) + r"\b", rendered) for known in literal_bat):
                literal_bat.add(target)
                changed = True
    return literal_bat


def _launcher_writes(function: ast.AST, bat_names: set[str]) -> list[ast.expr]:
    """Every expression written *as* a Windows launcher inside `function`.

    Covers `<bat>.write_text(x)`, `<bat>.write_bytes(x)` and
    `open(<bat>, "w").write(x)`. The first version handled only `write_text`,
    so two of the three ways to create the same file were invisible.
    """
    written: list[ast.expr] = []

    def _is_bat(expression: ast.expr) -> bool:
        rendered = ast.unparse(expression)
        return ".bat" in rendered or rendered in bat_names

    for node in _own_nodes(function):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args):
            continue
        # `<bat>.write_text(...)` / `<bat>.write_bytes(...)`
        if node.func.attr in _WRITE_METHODS and _is_bat(node.func.value):
            written.append(node.args[0])
            continue
        # `open(<bat>, "w").write(...)`
        if node.func.attr == "write" and isinstance(node.func.value, ast.Call):
            inner = node.func.value
            if (
                isinstance(inner.func, ast.Name)
                and inner.func.id == "open"
                and inner.args
                and _is_bat(inner.args[0])
            ):
                written.append(node.args[0])
    return written


def _launcher_violations(source: str) -> list[str]:
    """Both halves of D-02, checked wherever a test writes a Windows launcher.

    D-02 had two halves and only one of them was ever guarded:

    * D-02a -- the stub body wrote its payload through the console code page.
      On a cp1252 console a CJK payload raises `UnicodeEncodeError`.
    * D-02b -- the `.bat` launcher did not set `PYTHONUTF8=1`, which is what
      forces UTF-8 stdio on Windows regardless of the code page.

    Both are checked unconditionally, and the reason is measured rather than
    assumed: they are individually *sufficient* and jointly *necessary*.
    `PYTHONUTF8=1` rescues a text write, and a `sys.stdout.buffer` write does
    not care about the code page -- so a site with either one is safe, and only
    a site missing both actually fails. Enforcing both anyway means no reviewer
    has to work out which case a new stub falls into, and per-site reasoning is
    precisely what let this survive in four places.

    Worth stating because it is not obvious: the failure does not look like an
    encoding bug. The child dies with `UnicodeEncodeError` and exits **1**,
    which `verdict_for_exit_code` maps to FINDINGS. A test that passes non-ASCII
    and expects PASS fails as a wrong-verdict mystery instead.

    Scoped to functions that *write* a launcher, not to functions that merely
    mention one. The first draft used the looser form and reported thirteen
    hits, nine of them docstrings and `assert stub.suffix == ".bat"` lines. A
    guard that cries wolf gets an allowlist, and an allowlist is where this kind
    of rule goes to die.

    Known residual: a launcher written with a suffix this rule does not know
    (`.cmd`), or through a helper in another module. `_SUITE_ROOTS` covers both
    test trees, so a helper would still be read -- just attributed to its own
    function.
    """
    violations: list[str] = []
    for function in _enclosing_functions(ast.parse(source)):
        bat_names = _bat_valued_names(function)
        launcher_payloads = _launcher_writes(function, bat_names)
        if not launcher_payloads:
            continue

        for payload in launcher_payloads:
            if not _UTF8_ENABLED.search(ast.unparse(payload)):
                violations.append(
                    f"{function.name}: writes a .bat launcher without PYTHONUTF8=1 (D-02b)"
                )

        # This function builds a fake binary for Windows, so its payload has to
        # survive the trip. Checked over the whole function because the body and
        # the launcher are written a few lines apart.
        body = chr(10).join(ast.unparse(node) for node in _own_nodes(function))
        if _BYTES_STDOUT_WRITE in body:
            continue
        violations.extend(
            f"{function.name}: the stub body reaches stdout via {spelling.rstrip('(')} "
            "rather than bytes through sys.stdout.buffer (D-02a)"
            for spelling in _TEXT_STDOUT_WRITES
            if spelling in body
        )
    return violations


#: Synthetic factories, one per half plus a conforming one. Assembled from
#: fragments rather than written as one literal, because a source-reading rule
#: whose fixtures are themselves source is easy to get subtly wrong.
_NL = chr(10)
_HEADER = "def factory(payload):" + _NL + '    bat = d / (name + ".bat")' + _NL
_BODY_BYTES = '    py.write_text("import sys; sys.stdout.buffer.write(payload)")' + _NL
_BODY_TEXT = '    py.write_text("import sys; sys.stdout.write(payload)")' + _NL
_BAT_UTF8 = '    bat.write_text("@set PYTHONUTF8=1" + launcher)' + _NL
_BAT_PLAIN = '    bat.write_text(launcher)' + _NL

_CONFORMING_LAUNCHER = _HEADER + _BODY_BYTES + _BAT_UTF8
_D02A_ONLY = _HEADER + _BODY_TEXT + _BAT_UTF8
_D02B_ONLY = _HEADER + _BODY_BYTES + _BAT_PLAIN
#: A function that talks about `.bat` without writing one. The looser first
#: draft of the rule flagged nine of these.
_MERELY_MENTIONS = (
    "def test_shape(stub):" + _NL
    + '    """The stub is a .bat on Windows and a shebang script on POSIX."""' + _NL
    + '    assert stub.suffix == ".bat"' + _NL
)


#: Evasions found by an adversarial pass *after* the rule shipped. Every one
#: was green. The `print()` case is the one that matters: it is what
#: `tests/journey/test_engineer_workflow.py` actually contained before this
#: branch, so the first version of this rule would have missed the real site
#: and the other half caught it by luck rather than by design.
_EVASIONS = {
    "print() body": _HEADER + '    py.write_text("import json; print(json.dumps(p))")' + _NL + _BAT_UTF8,
    "writelines body": (
        _HEADER + '    py.write_text("import sys; sys.stdout.writelines(p)")' + _NL + _BAT_UTF8
    ),
    "open(bat, 'w')": _HEADER + _BODY_BYTES + '    open(bat, "w").write(launcher)' + _NL,
    "write_bytes": _HEADER + _BODY_BYTES + "    bat.write_bytes(launcher.encode())" + _NL,
    "annotated bat assignment": (
        "def factory(payload):" + _NL + '    bat: Path = d / (name + ".bat")' + _NL
        + _BODY_BYTES + "    bat.write_text(launcher)" + _NL
    ),
    "extension via a variable": (
        "def factory(payload):" + _NL + '    ext = ".bat"' + _NL + "    bat = d / (name + ext)" + _NL
        + _BODY_BYTES + "    bat.write_text(launcher)" + _NL
    ),
    "PYTHONUTF8 only in a comment": (
        _HEADER + _BODY_BYTES + '    bat.write_text("@rem PYTHONUTF8 not set" + launcher)' + _NL
    ),
}


@pytest.mark.parametrize("label", sorted(_EVASIONS))
def test_the_launcher_rule_rejects_the_evasions_it_once_allowed(label: str) -> None:
    """Seven spellings that produced zero violations when this rule shipped.

    They are the reason it now resolves `.bat` through annotated assignments,
    walruses and variable-held extensions; treats `write_bytes` and
    `open(..., "w").write` as launcher writes; requires `PYTHONUTF8=1` rather
    than the bare word; and matches `print(` and `writelines(` alongside
    `sys.stdout.write(`.
    """
    assert _launcher_violations(_EVASIONS[label]), (
        f"{label!r} still evades the rule this test exists to keep honest"
    )


def test_the_launcher_rule_rejects_each_half_of_D_02_separately() -> None:
    """Falsifiers for both halves, a conforming factory, and a near-miss.

    Written before the real violations were fixed, so the rule was shown to
    fire on the actual repository first. Kept afterwards because a rule that
    has only ever run against conforming source has never been shown to reject
    anything -- which is how the original D-02 guards came to have a blind spot
    exactly where the defect was.
    """
    assert _launcher_violations(_D02A_ONLY), "the text-write half went undetected"
    assert _launcher_violations(_D02B_ONLY), "the missing-PYTHONUTF8 half went undetected"
    assert not _launcher_violations(_CONFORMING_LAUNCHER), (
        "the rule flags a factory that does both halves correctly"
    )
    assert not _launcher_violations(_MERELY_MENTIONS), (
        "the rule flags a test that only talks about .bat files; a guard that "
        "cries wolf gets an allowlist, and an allowlist is where it dies"
    )


def test_no_test_writes_a_windows_launcher_that_cannot_carry_utf8() -> None:
    """Every `.bat` any test writes, across both suite roots."""
    offenders: list[str] = []
    for root in _SUITE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            offenders.extend(
                f"{path.relative_to(root.parent)}::{violation}"
                for violation in _launcher_violations(path.read_text(encoding="utf-8"))
            )

    assert not offenders, (
        "these tests build a fake binary that cannot carry a non-ASCII payload "
        "on Windows, which is D-02 surviving in the corners its regression "
        "guards do not reach:" + _NL + "  " + (_NL + "  ").join(offenders)
    )


# ---------------------------------------------------------------------------
# Finding F5 - Stable envelope shape
# ---------------------------------------------------------------------------

class TestStableEnvelopeShape:
    """The lint_openspec envelope must have the same keys on every code path.

    An earlier revision returned different key sets depending on whether the run
    reached planlint or was refused before it started. A model branching on a key
    that may not be present gets None silently, which is worse than a KeyError.
    """

    EXPECTED_KEYS = {
        "verdict", "exit_code", "blocked_reason", "blocked_detail",
        "verb", "target", "command", "duration_ms", "findings",
        "findings_parse_error", "findings_truncated", "stdout_excerpt",
        "stderr", "contract",
    }

    def test_all_keys_present_on_pass(self, make_stub, spec_repo: Path) -> None:
        stub = make_stub('import sys\nsys.stdout.buffer.write(b\'{"findings": []}\')\nsys.exit(0)\n')
        cfg = PlanlintConfig(binary=str(stub), target=str(spec_repo), allowed_roots=(spec_repo,))
        assert self.EXPECTED_KEYS.issubset(lint_openspec(config=cfg).keys())

    def test_all_keys_present_on_blocked(self) -> None:
        # No PLANLINT_TARGET set; isolated_environment autouse clears it.
        assert self.EXPECTED_KEYS.issubset(lint_openspec().keys())

    def test_all_keys_present_on_findings(self, make_stub, spec_repo: Path) -> None:
        stub = make_stub(
            'import sys\n'
            'sys.stdout.buffer.write(b\'{"findings": [{"rule": "R1", "message": "x"}]}\')\n'
            'sys.exit(1)\n'
        )
        cfg = PlanlintConfig(binary=str(stub), target=str(spec_repo), allowed_roots=(spec_repo,))
        assert self.EXPECTED_KEYS.issubset(lint_openspec(config=cfg).keys())


# ---------------------------------------------------------------------------
# Finding F4 - RecursionError never escapes score_run
# ---------------------------------------------------------------------------

class TestRecursionErrorContainment:
    """A deeply nested artifact must not raise RecursionError out of score_run.

    json.loads on a 20k-deep structure raises RecursionError. The module already
    handles JSONDecodeError; RecursionError is a separate branch under
    BaseException that the original except clause missed.
    """

    def test_deeply_nested_artifact_is_blocked_not_raised(self, tmp_path: Path) -> None:
        f = tmp_path / "deep.json"
        f.write_text("[" * 20_000 + "]" * 20_000, encoding="utf-8")
        cfg = EvalConfig(sink_dir=tmp_path, allowed_roots=(tmp_path,))
        result = score_run("deep", artifact_path=str(f), config=cfg)
        assert result["verdict"] == BLOCKED
        assert result["blocked_reason"] == BLOCKED_ARTIFACT_UNREADABLE


# ---------------------------------------------------------------------------
# Finding F9 - All allowed verbs actually reach the subprocess
# ---------------------------------------------------------------------------

#: A stub that records the argv it was handed, so "reached the subprocess" can
#: be asserted as a fact rather than inferred from the absence of one blocked
#: reason.
_RECORDS_ARGV = (
    "import sys\n"
    "from pathlib import Path\n"
    "Path({marker!r}).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
    "sys.exit(0)\n"
)


@pytest.mark.parametrize("verb", sorted(ALLOWED_VERBS))
def test_all_allowed_verbs_reach_subprocess(
    make_stub, spec_repo: Path, tmp_path: Path, verb: str
) -> None:
    """Every verb in guards.ALLOWED_VERBS must reach the subprocess, not be blocked.

    An earlier revision advertised six verbs and could only ever run `validate`.
    The other five were dead config -- they appeared in the allow list but
    `run_verb` had no dispatch path to them.

    This asserted `blocked_reason != BLOCKED_TOOL_NOT_FOUND`, which is a proxy
    for reaching the subprocess and a poor one: a verb blocked by the guard
    reports `guard_rejected`, which is also not `tool_not_found`, so it passed.
    Measured against the stub below, the old assertion was green for `init` and
    `write` -- both `BLOCKED / guard_rejected`, neither of which executes
    anything at all. A test named "reaches subprocess" could have stayed green
    with every verb blocked.

    The stub now records its own argv, so the fact is checked directly, and
    `test_a_refused_verb_does_not_reach_the_subprocess` proves the marker can
    register absence -- which is what the old form could never do.

    The verbs come from `guards.ALLOWED_VERBS` so the parametrisation cannot
    drift from the allow list.
    """
    marker = tmp_path / f"argv-{verb}.txt"
    stub = make_stub(_RECORDS_ARGV.format(marker=str(marker)))
    cfg = PlanlintConfig(binary=str(stub), target=str(spec_repo), allowed_roots=(spec_repo,))

    result = run_verb(verb, config=cfg)

    assert marker.is_file(), (
        f"Verb {verb!r} is in ALLOWED_VERBS but never reached the subprocess "
        f"(verdict {result['verdict']}, reason {result.get('blocked_reason')!r}). "
        "The allow list and the dispatch path are out of sync."
    )
    assert verb in marker.read_text(encoding="utf-8").split(), (
        f"the subprocess ran but was not handed {verb!r}; argv was "
        f"{marker.read_text(encoding='utf-8')!r}"
    )
    assert result["verdict"] == PASS, "the stub exits 0, so anything but PASS is the wrapper"
    assert result["exit_code"] == 0


@pytest.mark.parametrize("verb", sorted(REFUSED_VERBS))
def test_a_refused_verb_does_not_reach_the_subprocess(
    make_stub, spec_repo: Path, tmp_path: Path, verb: str
) -> None:
    """The falsifier for the test above, and half the point of the allow list.

    The positive test is only meaningful if the marker can register *absence*.
    These verbs are the ones that would write to the target repository, so
    "blocked" here has to mean "nothing executed", not "executed and reported
    a refusal afterwards".
    """
    marker = tmp_path / f"argv-{verb}.txt"
    stub = make_stub(_RECORDS_ARGV.format(marker=str(marker)))
    cfg = PlanlintConfig(binary=str(stub), target=str(spec_repo), allowed_roots=(spec_repo,))

    result = run_verb(verb, config=cfg)

    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED
    assert not marker.exists(), (
        f"{verb!r} is a refused verb and the subprocess ran anyway. A refusal "
        "reported after the fact is not a refusal."
    )


# ---------------------------------------------------------------------------
# Finding F14 - Coverage gate configured
# ---------------------------------------------------------------------------

_DECLARED_FLOOR = re.compile(r"(?m)^fail_under\s*=\s*(\d+)\s*$")
_CI_FLOOR_OVERRIDE = re.compile(r"--fail-under[= ](\d+)")


def _declared_floor(repo_root: Path) -> int:
    """Read the floor's *value* out of pyproject.toml, with the stdlib only.

    Two predecessors are folded into this one function.

    `test_coverage_gate_is_configured_in_pyproject` asserted `"fail_under" in
    content`, which `fail_under = 0` satisfies -- a substring check stops
    exactly one spelling of nothing.

    `test_the_declared_coverage_floor_is_at_least_ninety` read the value
    correctly but opened with `pytest.importorskip("tomli")` on 3.10, which
    makes a guard on the coverage floor depend on a *transitive* dependency of
    pytest. It happens to be present today (pytest requires `tomli>=1` below
    3.11), so it does not skip -- but a guard that would silently become a skip
    if pytest dropped that pin is not the shape you want on the floor that
    guards every other number in this repository. An anchored regex reads the
    same value, needs no parser, and cannot skip anywhere.
    """
    matches = _DECLARED_FLOOR.findall((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert len(matches) == 1, (
        f"expected exactly one `fail_under` declaration in pyproject.toml, found {matches}"
    )
    return int(matches[0])


def _ci_floor_overrides(ci_text: str, declared: int) -> list[int]:
    """Every `--fail-under` in the workflow that would undercut the declared floor.

    Pure over text, not over a path, so the mutants in
    `test_the_floor_check_rejects_every_spelling_the_substring_check_allowed`
    can prove this function rejects something. The version it replaces asserted
    `"--fail-under=80" not in ci_content`: one spelling, of one number, guarding
    the floor that guards everything else. `--fail-under=85`, `--fail-under 80`
    and `--fail-under=0` all passed it.
    """
    return [int(value) for value in _CI_FLOOR_OVERRIDE.findall(ci_text) if int(value) < declared]


@pytest.mark.parametrize(
    "spelling",
    ["--fail-under=80", "--fail-under=85", "--fail-under 80", "--fail-under=0"],
)
def test_the_floor_check_rejects_every_spelling_the_substring_check_allowed(spelling: str) -> None:
    """Four spellings; the old substring assertion caught one.

    Shipped permanently rather than run once, because a static guard that has
    only ever been run against conforming text has never been shown to reject
    anything. That was the state of the substring check this replaces: it had
    never been run against a workflow that *did* undercut the floor, so nobody
    noticed it recognised one spelling out of four.
    """
    assert _ci_floor_overrides(f"        run: coverage report {spelling}\n", 90), (
        f"{spelling!r} would undercut a floor of 90 and this check let it through"
    )


def test_the_floor_check_accepts_a_workflow_that_does_not_override() -> None:
    """The other half: it must be able to return empty, or it is not a check.

    `--fail-under=95` is *above* the floor and must not be reported -- a guard
    that flags every occurrence of the flag would be an accurate string matcher
    and a useless floor guard.
    """
    assert not _ci_floor_overrides("run: coverage report\n", 90)
    assert not _ci_floor_overrides("run: coverage report --fail-under=95\n", 90)


def test_the_declared_coverage_floor_is_at_least_ninety() -> None:
    """Parse the floor, do not grep for the word."""
    assert _declared_floor(Path(__file__).resolve().parents[2]) >= 90, (
        "the coverage floor was lowered"
    )


def test_ci_does_not_undercut_the_declared_coverage_floor() -> None:
    """ci.yml must not replace pyproject.toml's floor with a lower one.

    The quality job runs `coverage report` with no `--fail-under`, so
    pyproject.toml governs. A hard-coded CLI floor would silently replace it,
    and the two floors would diverge with both looking configured.
    """
    repo_root = Path(__file__).resolve().parents[2]
    declared = _declared_floor(repo_root)
    ci_text = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    undercuts = _ci_floor_overrides(ci_text, declared)
    assert not undercuts, (
        f"ci.yml passes --fail-under={undercuts}, undercutting pyproject.toml's "
        f"fail_under={declared}. Remove the flag and let pyproject.toml govern."
    )


# ---------------------------------------------------------------------------
# Layer targets must run the layer they name.
# ---------------------------------------------------------------------------

_MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"

#: The layer target that silently ran the wrong thing, and what it must reach.
#:
#: `make test-e2e` ran `tests/e2e/` only -- four tests, two of them `--help`
#: invocations -- while `mcp_server/tests/test_server_e2e_stdio.py`, which
#: spawns the server and drives a real JSON-RPC handshake over stdio, did not
#: count as an end-to-end test. That file cannot move: the contract suite must
#: also run standalone under `cd mcp_server && pytest`. So the target has to
#: name it, and nothing checked that it still does.
_TARGET_MUST_REACH = {
    "test-e2e": ("tests/e2e/", "mcp_server/tests/test_server_e2e_stdio.py"),
}


def _makefile_recipe(target: str) -> str:
    """The *commands* for one target, with comment lines stripped.

    Stripping comments is load-bearing, and it took reverting the recipe to its
    pre-fix form and watching this guard stay green to notice. The comment block
    above the command explains *why* the target names that file, so it mentions
    the path too -- and a check that reads the whole body is then satisfied by
    the explanation of the thing rather than by the thing.
    """
    lines = _MAKEFILE.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(f"{target}:"):
            continue
        body: list[str] = []
        for following in lines[index + 1 :]:
            if following and not following.startswith(("\t", " ", "#")):
                break
            if following.strip().startswith("#"):
                continue
            body.append(following)
        return chr(10).join(body)
    raise AssertionError(f"no `{target}` target found in the Makefile")


@pytest.mark.parametrize("target", sorted(_TARGET_MUST_REACH))
def test_a_layer_target_still_runs_the_layer_it_names(target: str) -> None:
    """A target whose name promises more than its recipe delivers.

    This is a source-reading guard for the same reason `_launcher_violations`
    is: there is no runtime seam. `make` is not installed on every machine that
    edits this repository, and a target that quietly stops running a file
    produces a *green* suite with less in it -- which is how the layer named
    "e2e" came to be the weakest layer while the strongest end-to-end test in
    the repository sat outside it.
    """
    recipe = _makefile_recipe(target)
    missing = [needed for needed in _TARGET_MUST_REACH[target] if needed not in recipe]

    assert not missing, (
        f"`make {target}` no longer names {missing}. The target's name promises "
        "a layer its recipe does not run, and a suite that silently shrinks "
        f"still goes green.{chr(10)}recipe:{chr(10)}{recipe}"
    )


def test_the_recipe_reader_can_tell_targets_apart() -> None:
    """The falsifier: a reader that returned the whole Makefile would pass above."""
    assert "tests/e2e/" in _makefile_recipe("test-e2e")
    assert "tests/e2e/" not in _makefile_recipe("test-unit"), (
        "the recipe reader is returning more than one target's body, so the "
        "check above would pass for any target that exists"
    )
