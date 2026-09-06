"""End to end over the wire: spawn the server, speak JSON-RPC, read a verdict.

Every other test in this repository calls Python functions. This one launches
`python -m foundry_spike_mcp serve` as a subprocess and talks to it the way
Agent Builder does -- newline-delimited JSON-RPC on stdin and stdout -- which
is the only way to check the three things that only exist at the transport
boundary:

* **The handshake completes.** `test_server_smoke.py` proves the server object
  constructs and its tools register. It cannot prove the process starts, reads
  a request and answers one. Those failed independently once already: the
  module shipped importing an SDK entry point that no longer existed, and
  ninety green tests said nothing about it.

* **stdout is the protocol.** The invariant is stated in four places and, until
  this file, defended by one static check that greps the source for `print()`.
  That check cannot see a dependency writing to stdout, a library calling
  `logging.basicConfig()`, or a warning from the interpreter -- and the symptom
  of any of those is not a stray line, it is the tool vanishing from Agent
  Builder with no useful error. Here the server runs at DEBUG, the noisiest
  setting an operator would ever use, and every byte of stdout is parsed.

* **The verdict survives the trip.** The whole spike asks whether the
  three-valued contract reaches a model intact. Asserting that in-process
  assumes the answer to the question being asked.

**On the transport.** Requests are written and responses read on a background
thread with a deadline, rather than through `subprocess.communicate`. That is
not fussiness: `communicate` closes stdin, the server treats end of input as
shutdown, and a tool call whose subprocess is still running is abandoned
mid-flight. Writing this test the obvious way produced a run where stderr
recorded `planlint returned FINDINGS` and stdout never carried the response.
A real client holds stdin open, so the test does too.
"""

from __future__ import annotations

import json
import os
import queue
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

# Probe the package rather than one major's submodule, for the reason set out
# in `test_server_smoke.py`: the floor of the declared range does not have the
# 2.x module path, and a suite that cannot run on its own floor is not a gate.
_SDK = "mcp"

if os.environ.get("REQUIRE_MCP"):
    import importlib

    importlib.import_module(_SDK)
else:
    pytest.importorskip(_SDK, reason="MCP SDK not installed; `make setup` installs it")

#: Generous, because a cold interpreter plus an SDK import plus a subprocess is
#: not fast on a loaded CI runner. It bounds a hang; it does not measure speed.
_DEADLINE_SECONDS = float(os.environ.get("FOUNDRY_SPIKE_E2E_TIMEOUT", "60"))

_PROTOCOL_VERSION = "2024-11-05"


class _StdioClient:
    """A minimal MCP client: enough protocol to list tools and call one.

    Deliberately hand-rolled over `subprocess` rather than driven through the
    SDK's own async client. The SDK client would frame the messages correctly
    by construction, which is precisely what must not be assumed -- if the
    framing is wrong, a test built on the same library agrees with the bug.
    Stdlib only, no event loop, no extra dependency.
    """

    def __init__(self, env: dict[str, str]) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "foundry_spike_mcp", "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        self.stdout_lines: list[str] = []

    def _pump(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def send(self, message: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()

    def request(self, request_id: int, method: str, params: Any = None) -> dict[str, Any]:
        """Send one request and return the response with the matching id.

        Notifications and unrelated traffic are recorded and skipped rather
        than treated as the answer, because a response is identified by its id
        and nothing else.
        """
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        while True:
            line = self._lines.get(timeout=_DEADLINE_SECONDS)
            if line is None:
                raise AssertionError(
                    f"server closed stdout before answering {method!r}; "
                    f"stderr:\n{self.stderr()}"
                )
            self.stdout_lines.append(line)
            payload = json.loads(line)
            if payload.get("id") == request_id:
                return payload

    def notify(self, method: str, params: Any = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)

    def handshake(self) -> dict[str, Any]:
        response = self.request(
            1,
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "contract-e2e", "version": "0"},
            },
        )
        self.notify("notifications/initialized")
        return response

    def stderr(self) -> str:
        assert self._proc.stderr is not None
        return self._proc.stderr.read()

    def close(self) -> str:
        if self._proc.stdin and not self._proc.stdin.closed:
            self._proc.stdin.close()
        try:
            self._proc.wait(timeout=_DEADLINE_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a hang
            self._proc.kill()
            self._proc.wait(timeout=_DEADLINE_SECONDS)
        captured = self.stderr()
        self._proc.stdout and self._proc.stdout.close()
        self._proc.stderr and self._proc.stderr.close()
        return captured


def _tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    """Pull the tool's dict result back out of an MCP `tools/call` response.

    The SDK may return it as `structuredContent` or serialised into a text
    content block depending on major version, and this test is deliberately
    version-tolerant about the envelope while being strict about what is
    inside it.
    """
    assert "error" not in response, f"tool call returned a protocol error: {response}"
    result = response["result"]
    assert result.get("isError") is not True, f"tool call reported isError: {result}"
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and "verdict" in structured:
        return structured
    for block in result.get("content", []):
        if block.get("type") == "text":
            decoded = json.loads(block["text"])
            if isinstance(decoded, dict) and "verdict" in decoded:
                return decoded
    raise AssertionError(f"no verdict-carrying payload in {result}")


@pytest.fixture
def stub_planlint(tmp_path: Path):
    """A planlint stand-in, so the E2E path exercises a real subprocess.

    The tool spawns a process; mocking that out would leave the interesting
    half of the wire untested.
    """

    def _make(*, exit_code: int, stdout: str) -> Path:
        script = tmp_path / "bin" / "planlint"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.exit({exit_code!r})\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return script

    return _make


@pytest.fixture
def server_env(tmp_path: Path):
    """Environment for a spawned server, with the repo's own src on the path.

    Runs at DEBUG on purpose: the quiet default would hide exactly the failure
    mode the stdout assertions exist to catch.
    """
    repo_root = Path(__file__).resolve().parents[2]

    def _env(binary: Path, target: Path, **overrides: str) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("REQUIRE_MCP", None)
        existing = env.get("PYTHONPATH", "")
        src = str(repo_root / "mcp_server" / "src")
        env["PYTHONPATH"] = f"{src}{os.pathsep}{existing}" if existing else src
        env.update(
            PLANLINT_BIN=str(binary),
            PLANLINT_TARGET=str(target),
            PLANLINT_ALLOWED_ROOTS=str(target),
            FOUNDRY_SPIKE_LOG_LEVEL="DEBUG",
        )
        env.update(overrides)
        return env

    return _env


@pytest.fixture
def spec_target(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    (target / "openspec").mkdir(parents=True)
    return target


def test_the_server_completes_a_handshake_and_lists_both_tools(
    stub_planlint, server_env, spec_target
):
    client = _StdioClient(server_env(stub_planlint(exit_code=0, stdout="{}"), spec_target))
    try:
        handshake = client.handshake()
        assert handshake["result"]["serverInfo"]["name"] == "foundry-spike"

        listed = client.request(2, "tools/list")
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert names == {"lint_openspec", "score_run"}
    finally:
        client.close()


def test_tool_descriptions_carry_the_authority_rule_to_the_model(
    stub_planlint, server_env, spec_target
):
    """A tool description is prompt surface. The rule the agent must not get
    wrong has to survive into the schema the model actually reads, not just
    into a docstring a human reads."""
    client = _StdioClient(server_env(stub_planlint(exit_code=0, stdout="{}"), spec_target))
    try:
        client.handshake()
        tools = {t["name"]: t for t in client.request(2, "tools/list")["result"]["tools"]}
        lint_description = tools["lint_openspec"]["description"]
        assert "BLOCKED" in lint_description
        assert "never be reported as a pass" in lint_description
        score_description = tools["score_run"]["description"]
        assert "null" in score_description
        assert "excluded from" in score_description
    finally:
        client.close()


@pytest.mark.parametrize(
    ("exit_code", "expected_verdict"),
    [(0, "PASS"), (1, "FINDINGS"), (2, "BLOCKED")],
)
def test_every_verdict_survives_the_round_trip(
    stub_planlint, server_env, spec_target, exit_code, expected_verdict
):
    """The spike's central question, asked over the wire instead of in process.

    Exit 2 is the one that matters: it must arrive as BLOCKED, carrying its
    reason, and never as a pass.
    """
    stdout = "{}" if exit_code != 2 else "usage: planlint validate [OPTIONS]\n"
    client = _StdioClient(server_env(stub_planlint(exit_code=exit_code, stdout=stdout), spec_target))
    try:
        client.handshake()
        response = client.request(3, "tools/call", {"name": "lint_openspec", "arguments": {}})
        payload = _tool_payload(response)
        assert payload["verdict"] == expected_verdict
        assert payload["exit_code"] == exit_code
        if expected_verdict == "BLOCKED":
            assert payload["blocked_reason"] == "precondition_error"
            assert "not a spec failure" in payload["contract"]["note"]
    finally:
        client.close()


def test_a_refusal_crosses_the_wire_as_a_verdict_not_a_protocol_error(
    stub_planlint, server_env, spec_target, tmp_path
):
    """The failure this whole package exists to prevent, tested at the boundary.

    A target outside the allow list must come back as a BLOCKED *result*. If it
    surfaced as a JSON-RPC error instead, the model would see a framework
    string with no verdict field and would be free to guess.
    """
    outside = tmp_path / "not-allowed"
    outside.mkdir()
    client = _StdioClient(server_env(stub_planlint(exit_code=0, stdout="{}"), spec_target))
    try:
        client.handshake()
        response = client.request(
            3, "tools/call", {"name": "lint_openspec", "arguments": {"target": str(outside)}}
        )
        payload = _tool_payload(response)
        assert payload["verdict"] == "BLOCKED"
        assert payload["blocked_reason"] == "guard_rejected"
    finally:
        client.close()


def test_the_bounded_payload_flag_survives_the_wire(stub_planlint, server_env, spec_target):
    """`findings_truncated` is new on the envelope. An envelope key that never
    reaches the model is not part of the contract."""
    findings = json.dumps({"findings": [{"rule": "R1", "message": "x" * 200}]})
    client = _StdioClient(
        server_env(
            stub_planlint(exit_code=1, stdout=findings),
            spec_target,
            FOUNDRY_SPIKE_FINDINGS_MAX_BYTES="10",
        )
    )
    try:
        client.handshake()
        response = client.request(3, "tools/call", {"name": "lint_openspec", "arguments": {}})
        payload = _tool_payload(response)
        # Evidence downgraded, verdict untouched.
        assert payload["verdict"] == "FINDINGS"
        assert payload["findings_truncated"] is True
        assert payload["findings"] is None
    finally:
        client.close()


def test_stdout_carries_only_protocol_even_at_debug_level(
    stub_planlint, server_env, spec_target
):
    """The invariant the static `print()` scan cannot reach.

    A dependency writing to stdout, or `logging.basicConfig` pointed at the
    default stream, would corrupt the frame and make the server disappear from
    Agent Builder with no useful error. Running at DEBUG guarantees there is
    plenty of log output competing for a stream it must not use.
    """
    client = _StdioClient(server_env(stub_planlint(exit_code=1, stdout="{}"), spec_target))
    try:
        client.handshake()
        client.request(2, "tools/list")
        client.request(3, "tools/call", {"name": "lint_openspec", "arguments": {}})
    finally:
        stderr = client.close()

    assert client.stdout_lines, "the server produced no output at all"
    for line in client.stdout_lines:
        if not line.strip():
            continue
        decoded = json.loads(line)  # raises, and should, on anything unframed
        assert decoded.get("jsonrpc") == "2.0", f"non-JSON-RPC line on stdout: {line!r}"

    # The other half of the same claim: the logs were produced, and went to the
    # stream that is allowed to have them. Without this a silent logger would
    # pass the assertion above for the wrong reason.
    assert "foundry_spike_mcp" in stderr
    assert "DEBUG" in stderr


def test_an_unknown_tool_is_refused_without_killing_the_session(
    stub_planlint, server_env, spec_target
):
    """A bad call must not take the server down: the next call still answers."""
    client = _StdioClient(server_env(stub_planlint(exit_code=0, stdout="{}"), spec_target))
    try:
        client.handshake()
        response = client.request(
            3, "tools/call", {"name": "definitely_not_a_tool", "arguments": {}}
        )
        assert "error" in response or response["result"].get("isError") is True

        recovered = client.request(4, "tools/call", {"name": "lint_openspec", "arguments": {}})
        assert _tool_payload(recovered)["verdict"] == "PASS"
    finally:
        client.close()
