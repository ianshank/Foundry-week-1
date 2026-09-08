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
