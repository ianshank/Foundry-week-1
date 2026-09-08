"""Regression guards: the self-check's fixtures and its recorded evidence.

`evidence/03-mcp-selfcheck.json` is generated output -- `Makefile:152` writes
it from a live `lint_openspec` run against three targets. It is also the file
`evidence/05-verdict.md` cites for the claim that all three legs of the
three-valued contract land.

It was hand-edited. The FINDINGS case had honestly recorded
`actual_verdict: PASS`, `exit_code: 0`, `matched: false`, `specs_checked: 0`
-- a true recording of a misconfigured fixture, because the target
`bad_target/` was an empty tree that `.gitignore` hid from every reviewer. A
later commit rewrote those fields to FINDINGS/1/true and invented a findings
array, turning `all_expected` to `true`. In the repository whose stated
purpose is detecting a system that reports a non-result as a pass.

Two guards, because they fail differently:

* The fixture guards below need no binary and no network, so they run in CI's
  `contract` job and catch the root cause -- a FINDINGS fixture that cannot
  produce findings.
* `test_the_recorded_selfcheck_agrees_with_itself` catches a careless edit.
  It would NOT have caught this one, which was internally consistent, and that
  is exactly why the tracked fixtures matter more than the consistency check:
  the real defence is that anyone can re-run `make selfcheck` and diff.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

pytestmark = pytest.mark.regression

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO / "configs" / "fixtures" / "planlint"
_EVIDENCE = _REPO / "evidence" / "03-mcp-selfcheck.json"


def test_the_findings_fixture_has_a_spec_planlint_can_discover() -> None:
    """The direct guard against the root cause: `specs_checked: 0`.

    planlint discovers specs at `openspec/changes/*/specs/*/spec.md`. The old
    fixture matched that glob zero times, so the FINDINGS case could only ever
    record a PASS. No binary needed to catch it.
    """
    specs = sorted((_FIXTURES / "findings").glob("openspec/changes/*/specs/*/spec.md"))

    assert specs, (
        "the FINDINGS fixture contains no spec planlint would discover, so it "
        "cannot produce findings and the case cannot legitimately land"
    )


def test_the_findings_fixture_is_tracked_not_ignored() -> None:
    """A fixture a reviewer cannot open is not evidence.

    `bad_target/` was gitignored, which is why nobody could see that the thing
    the FINDINGS case depended on was an empty directory.
    """
    import subprocess

    for path in sorted((_FIXTURES / "findings").rglob("*")):
        if not path.is_file():
            continue
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=_REPO, capture_output=True, check=False,
        )
        assert ignored.returncode != 0, f"{path.relative_to(_REPO)} is gitignored"


def test_the_blocked_fixture_has_no_openspec_tree() -> None:
    """Its emptiness is the fixture: that absence is the precondition error."""
    assert (_FIXTURES / "blocked").is_dir()
    assert not (_FIXTURES / "blocked" / "openspec").exists(), (
        "the BLOCKED fixture grew an openspec/ tree, so it no longer provokes "
        "the precondition error it exists to demonstrate"
    )


def test_the_fixture_readme_names_the_rules_each_fixture_trips() -> None:
    """A fixture without a stated purpose drifts into being wrong quietly."""
    readme = (_FIXTURES / "README.md").read_text(encoding="utf-8")

    assert "G001" in readme, "the README does not say which rule the findings fixture trips"
    assert "exit" in readme.lower()


def test_the_recorded_selfcheck_agrees_with_itself() -> None:
    """Every derived field in the artifact must follow from the raw result.

    `matched` is `actual == expected`; `all_expected` is the conjunction; and
    the case's own `actual_verdict`/`exit_code` must equal the ones inside the
    `result` envelope it wraps. A hand-edit that changes one and not the others
    is mechanically detectable.
    """
    report = json.loads(_EVIDENCE.read_text(encoding="utf-8"))
    cases = report["cases"]

    for case in cases:
        if case.get("skipped"):
            continue
        assert case["matched"] == (case["actual_verdict"] == case["expected_verdict"]), (
            f"{case['case']}: `matched` does not follow from the two verdicts"
        )
        assert case["actual_verdict"] == case["result"]["verdict"], (
            f"{case['case']}: the case verdict disagrees with the result envelope"
        )
        assert case["exit_code"] == case["result"].get("exit_code"), (
            f"{case['case']}: the case exit code disagrees with the result envelope"
        )

    assert report["all_expected"] == all(
        case.get("matched", False) for case in cases
    ), "`all_expected` is not the conjunction of the cases it summarises"


def test_the_recorded_selfcheck_findings_case_actually_found_something() -> None:
    """FINDINGS with zero specs checked is the shape of the original defect.

    The honest failure recorded `specs_checked: 0` alongside a PASS. A verdict
    of FINDINGS over zero specs is not possible from the real binary, so it can
    only mean the file was written by something other than a run.
    """
    report = json.loads(_EVIDENCE.read_text(encoding="utf-8"))
    case = next((c for c in report["cases"] if c["case"] == "findings"), None)
    if case is None or case.get("skipped"):
        pytest.skip("the findings case was not run in this capture")

    if case["actual_verdict"] != "FINDINGS":
        return  # an honest non-landing is allowed; the consistency test covers it

    findings = case["result"].get("findings") or {}
    assert findings.get("specs_checked", 0) >= 1, (
        "the FINDINGS case claims a verdict over zero specs checked"
    )
    assert findings.get("findings"), "FINDINGS was recorded with an empty findings list"


def test_every_in_repo_target_the_selfcheck_cites_still_exists() -> None:
    """The guard that would actually have caught the hand-edit.

    The fabricated capture cited
    `e:/Coding_Projects/foundry_week1/bad_target` -- a path inside this
    repository that does not exist and never did, because `.gitignore` hid it.
    Internal consistency could not detect that (the edit was consistent); an
    unresolvable citation can be detected, and it is the same class of check
    `check_evidence`'s E001 applies to prose.

    Scoped to targets under the repository root on purpose. `SELFCHECK_PASS_TARGET`
    legitimately points at a real OpenSpec repository elsewhere on the operator's
    machine, and asserting that someone else's absolute path exists would make
    this test fail for everyone but its author -- which is a different way of
    being useless.
    """
    report = json.loads(_EVIDENCE.read_text(encoding="utf-8"))

    missing = []
    for case in report["cases"]:
        target = case.get("target")
        if not target or case.get("skipped"):
            continue
        # Absolute under EITHER convention is someone else's machine and is not
        # ours to verify. Testing with `Path` alone is a trap: on Linux
        # `Path("E:/x").is_absolute()` is False, so a Windows path reads as
        # repo-relative and gets flagged for merely being foreign -- which is
        # exactly how this guard failed on the ubuntu legs while passing on
        # windows. `_portable_target` in `__main__.py` is what makes the
        # in-repo cases relative in the first place, so this check has
        # something portable to check.
        if PureWindowsPath(target).is_absolute() or PurePosixPath(target).is_absolute():
            # An absolute path is someone else's machine and is not ours to
            # verify -- with one exception that matters. `_portable_target`
            # rewrites every in-repo target to a relative path, so an absolute
            # one that still names this repository's own directory cannot have
            # come from a run: it is either older than that fix or was typed.
            # That is precisely the shape of the hand-edit this guard exists
            # for, `e:/Coding_Projects/foundry_week1/bad_target`, and matching
            # on the directory name is pure string work, so it holds on every
            # platform.
            if f"/{_REPO.name.lower()}/" in target.replace("\\", "/").lower():
                missing.append(
                    f"{case['case']} -> {target} (absolute, but inside this repo: "
                    "a real run records those relative)"
                )
            continue
        if not (_REPO / target).exists():
            missing.append(f"{case['case']} -> {target}")

    assert not missing, (
        "the capture cites in-repo targets that do not exist, so the run it "
        "records cannot be reproduced or reviewed: " + ", ".join(missing)
    )


def test_no_recorded_target_anywhere_leaks_an_absolute_in_repo_path() -> None:
    """Both `target` fields, not just the one the eye lands on.

    Raised in review of PR #13. `_portable_target` was applied to the
    case-level `target` and not to the copy inside the nested `result`
    envelope, so the tracked artifact still carried
    `E:\\Coding_Projects\foundry_week1\\configs\\...` -- native separators and
    the operator's directory layout, which is the D-05 class of defect this was
    meant to close, and guaranteed diff churn between machines.

    Walks every `target` at any depth rather than naming the two known ones, so
    a third copy added later is covered without this test being edited. That
    paid off immediately: there were three, not two -- planlint's own findings
    payload carries one as well.

    Scoped to keys named `target`, and `command` is excluded on purpose. That
    array is the argv that actually ran, and a record of an execution has to
    say what was executed; a `target` is a reference to a location, which the
    repo-relative spelling names more portably. Rewriting the first to tidy the
    second would be falsifying evidence to make a diff cleaner, which is the
    trade this repository exists to refuse.
    """
    report = json.loads(_EVIDENCE.read_text(encoding="utf-8"))
    marker = f"/{_REPO.name.lower()}/"

    def _targets(node: object, path: str = "") -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "target" and isinstance(value, str):
                    found.append((f"{path}.{key}".lstrip("."), value))
                else:
                    found.extend(_targets(value, f"{path}.{key}".lstrip(".")))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                found.extend(_targets(item, f"{path}[{index}]"))
        return found

    offenders = [
        f"{where} = {value}"
        for where, value in _targets(report)
        if marker in value.replace("\\", "/").lower()
    ]

    assert not offenders, (
        "these recorded targets are absolute paths inside this repository; a "
        "real run records those relative:\n  " + "\n  ".join(offenders)
    )
