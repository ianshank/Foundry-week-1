"""Every `main()` in the repo, none of which had a test.

Coverage measurement -- run for the first time after the hardening pass --
put `__main__.py` at 0%, `scan_evidence.py` at 48% and `verifier_probe.py` at
57%. The library functions underneath them were well covered; the entry points
that operators and CI actually invoke were not. That gap is easy to miss
because the modules *look* tested.

It matters most for `foundry_spike_mcp.__main__ selfcheck`: it is the artifact
that runbook step 3's "done when" is satisfied by, and it had never been
exercised by anything but a manual run.

Exit codes are asserted, not just output. A CLI whose exit code is wrong
passes silently in a terminal and fails a pipeline.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "mcp_server" / "src"))

import promote_trace  # noqa: E402
import scan_evidence  # noqa: E402
import verifier_probe  # noqa: E402
from foundry_spike_mcp import __main__ as spike_main  # noqa: E402


@pytest.fixture
def fake_planlint(tmp_path: Path) -> Path:
    """A stand-in planlint: exit 2 with no openspec/ tree, 1 for a 'find'
    target, 0 otherwise. Mirrors the real three-way contract."""
    script = tmp_path / "bin" / "planlint"
    script.parent.mkdir(parents=True)
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "target = sys.argv[sys.argv.index('--target') + 1]\n"
        "if not os.path.isdir(os.path.join(target, 'openspec')):\n"
        "    sys.stderr.write('error: no openspec/ directory\\n')\n"
        "    sys.stdout.write('usage: planlint --target PATH validate\\n')\n"
        "    sys.exit(2)\n"
        "if 'find' in target:\n"
        "    print(json.dumps({'findings': [{'rule': 'SPEC012'}]})); sys.exit(1)\n"
        "print(json.dumps({'findings': []})); sys.exit(0)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# ------------------------------------------------- foundry_spike_mcp selfcheck


def _selfcheck_env(monkeypatch, tmp_path: Path, binary: Path) -> None:
    for name in ("pass", "find"):
        (tmp_path / name / "openspec").mkdir(parents=True)
    monkeypatch.setenv("PLANLINT_BIN", str(binary))
    monkeypatch.setenv("PLANLINT_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setenv("SELFCHECK_PASS_TARGET", str(tmp_path / "pass"))
    monkeypatch.setenv("SELFCHECK_FINDINGS_TARGET", str(tmp_path / "find"))
    monkeypatch.delenv("SELFCHECK_BLOCKED_TARGET", raising=False)


def test_selfcheck_exercises_all_three_verdicts_and_exits_zero(
    monkeypatch, tmp_path, fake_planlint, capsys
):
    """Runbook step 3's 'done when', as a test rather than a manual run."""
    _selfcheck_env(monkeypatch, tmp_path, fake_planlint)
    assert spike_main.main(["selfcheck"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["all_expected"] is True
    landed = {c["case"]: (c["actual_verdict"], c["exit_code"]) for c in report["cases"]}
    assert landed == {
        "pass": ("PASS", 0),
        "findings": ("FINDINGS", 1),
        "blocked": ("BLOCKED", 2),
    }


def test_selfcheck_exits_nonzero_when_a_verdict_does_not_land(
    monkeypatch, tmp_path, fake_planlint, capsys
):
    """The whole value of the selfcheck is the exit code. Point the PASS case
    at a tree with no openspec/ and it becomes BLOCKED -- which must fail."""
    _selfcheck_env(monkeypatch, tmp_path, fake_planlint)
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("SELFCHECK_PASS_TARGET", str(tmp_path / "empty"))
    assert spike_main.main(["selfcheck"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["all_expected"] is False


def test_selfcheck_reports_skipped_cases_rather_than_pretending_they_passed(
    monkeypatch, tmp_path, fake_planlint, capsys
):
    _selfcheck_env(monkeypatch, tmp_path, fake_planlint)
    monkeypatch.delenv("SELFCHECK_PASS_TARGET")
    assert spike_main.main(["selfcheck"]) == 1
    report = json.loads(capsys.readouterr().out)
    skipped = [c for c in report["cases"] if c.get("skipped")]
    assert [c["case"] for c in skipped] == ["pass"]
    assert report["all_expected"] is False


def test_selfcheck_writes_the_evidence_file(monkeypatch, tmp_path, fake_planlint, capsys):
    _selfcheck_env(monkeypatch, tmp_path, fake_planlint)
    out = tmp_path / "evidence" / "03-mcp-selfcheck.json"
    assert spike_main.main(["selfcheck", "--out", str(out)]) == 0
    capsys.readouterr()
    assert json.loads(out.read_text())["all_expected"] is True


def test_selfcheck_json_goes_to_stdout_and_logs_to_stderr(
    monkeypatch, tmp_path, fake_planlint, capsys
):
    """The report must stay machine-readable with logging turned up, or a
    debugging session cannot also produce evidence."""
    _selfcheck_env(monkeypatch, tmp_path, fake_planlint)
    monkeypatch.setenv("FOUNDRY_SPIKE_LOG_LEVEL", "INFO")
    from foundry_spike_mcp import logging_setup

    logging_setup.configure(force=True)
    spike_main.main(["selfcheck"])
    captured = capsys.readouterr()
    json.loads(captured.out)  # raises if a log line leaked into stdout


# ------------------------------------------------------------ scan_evidence


def test_scan_main_exits_zero_on_clean_directories(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scan_evidence, "REPO", tmp_path)
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "notes.md").write_text("SPEC012 ERROR exit=1\n", encoding="utf-8")
    assert scan_evidence.main(["evidence"]) == 0
    assert "0 hit(s)" in capsys.readouterr().out


def test_scan_main_exits_nonzero_and_names_the_file_on_a_hit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scan_evidence, "REPO", tmp_path)
    (tmp_path / "traces").mkdir()
    leaky = tmp_path / "traces" / "capture.json"
    leaky.write_text('{"e": "ghp_abcdefghijklmnopqrstuvwxyz012345"}', encoding="utf-8")
    assert scan_evidence.main(["traces"]) == 1
    out = capsys.readouterr().out
    assert "capture.json" in out
    assert "ghp_abcdefghijklmnopqrstuvwxyz012345" not in out, "the value must not be echoed"


def test_scan_main_skips_a_missing_directory_without_failing(tmp_path, monkeypatch, capsys):
    """A capture directory that does not exist yet is normal in session 1."""
    monkeypatch.setattr(scan_evidence, "REPO", tmp_path)
    assert scan_evidence.main(["nope"]) == 0
    assert "skip" in capsys.readouterr().out


# ------------------------------------------------------------ promote_trace


def test_promote_main_reports_the_destination(tmp_path, monkeypatch, capsys):
    source = tmp_path / "raw" / "run-1"
    source.mkdir(parents=True)
    (source / "summary.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(promote_trace, "REPO", tmp_path)
    monkeypatch.setattr(promote_trace, "TRACES", tmp_path / "traces")
    assert promote_trace.main([str(source)]) == 0
    assert "promoted" in capsys.readouterr().out


def test_promote_main_exits_nonzero_on_a_refusal(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(promote_trace, "REPO", tmp_path)
    monkeypatch.setattr(promote_trace, "TRACES", tmp_path / "traces")
    assert promote_trace.main([str(tmp_path / "missing")]) == 1
    assert "REFUSED" in capsys.readouterr().err


# ----------------------------------------------------------- verifier_probe


def test_probe_main_requires_models(capsys):
    with pytest.raises(SystemExit) as caught:
        verifier_probe.main(["--models", ""])
    assert caught.value.code == 2
    assert "no models given" in capsys.readouterr().err


def test_probe_main_refuses_an_unfilled_template(tmp_path, capsys):
    """`01-planner.md` ships with a `<<< PASTE >>>` placeholder. Sending it
    would spend tokens comparing four models on a literal placeholder."""
    template = tmp_path / "tpl.md"
    template.write_text("Review this:\n\n<<< PASTE proposal.md HERE >>>\n", encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        verifier_probe.main(["--models", "ollama:x", "--prompt", str(template)])
    assert caught.value.code == 2
    assert "still a template" in capsys.readouterr().err


def test_probe_main_writes_transcripts_and_a_summary_even_when_calls_fail(
    tmp_path, monkeypatch, capsys
):
    """An unreachable endpoint must still leave an auditable record; a sweep
    that spent real tokens on other slots cannot lose its index."""
    monkeypatch.setenv("OLLAMA_ENDPOINT", "http://127.0.0.1:1/v1")
    out = tmp_path / "raw"
    code = verifier_probe.main(
        [
            "--models", "ollama:unreachable",
            "--prompt", str(REPO / "configs" / "probes" / "02-verifier.md"),
            "--expect", "FINDINGS",
            "--out", str(out),
            "--timeout", "1",
        ]
    )
    capsys.readouterr()
    assert code == 0, "an ERROR row is not a laundered failure, so the exit code stays 0"
    summaries = list(out.rglob("summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text())
    assert summary["results"][0]["screen"] == verifier_probe.ERROR
    assert summary["sampling"] == {"temperature": 0.0, "top_p": 1.0, "max_tokens": 800}


def test_probe_main_exit_code_flags_a_laundered_cell(tmp_path, monkeypatch, capsys):
    """The one outcome that must be impossible to miss in a scrollback."""
    def _launders(*_args, **_kwargs):
        return {
            "status": "OK",
            "text": "Looks fine.\n\nVERDICT: PASS",
            "latency_ms": 1,
            "total_tokens": 10,
        }

    monkeypatch.setattr(verifier_probe, "call_model", _launders)
    code = verifier_probe.main(
        [
            "--models", "ollama:launderer",
            "--prompt", str(REPO / "configs" / "probes" / "02-verifier.md"),
            "--expect", "FINDINGS",
            "--out", str(tmp_path / "raw"),
        ]
    )
    capsys.readouterr()
    assert code == 1
