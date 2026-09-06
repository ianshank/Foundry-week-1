"""Deterministic validation of the repo's skills, agents, hooks and settings.

Skills and agents are prompt-shaped, so the temptation is to call them
unverifiable and move on. Most of what makes them work is not: a skill with a
malformed frontmatter block never loads, a `name` that disagrees with its
directory is invoked by a name nobody types, a hook pointing at a missing file
fails silently on every edit, and a `description` with no trigger language
never fires when it should. All of that is checkable without a model in the
loop, and this file checks it.

What is *not* asserted here is behaviour -- whether the guidance is any good.
That is measured by whether the contract tests keep passing, which is the only
honest instrument available.

Frontmatter is parsed with a small local reader rather than PyYAML. The blocks
are flat `key: value` and the suite's whole premise is that it runs with
nothing installed; pulling in a parser to read six keys would trade that away.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLAUDE = REPO / ".claude"
SKILLS = sorted((CLAUDE / "skills").glob("*/SKILL.md"))
AGENTS = sorted((CLAUDE / "agents").glob("*.md"))
SETTINGS = CLAUDE / "settings.json"

#: Anthropic's guidance caps skill descriptions; a description longer than this
#: is a sign the skill is doing too many things to be triggered reliably.
MAX_DESCRIPTION = 1024
MIN_DESCRIPTION = 40

#: Words that make a description a *trigger* rather than a title. Without one,
#: the model has nothing to match a user's request against.
TRIGGER_WORDS = ("use when", "use for", "use before", "use this", "triggers on")


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    """Return ``(frontmatter, body)`` for a `---`-delimited markdown file.

    Raises `AssertionError` with a specific message rather than returning an
    empty dict: a missing or malformed block is the failure, and a silent empty
    result would let a broken asset pass as merely featureless.
    """
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter block"
    _, _, rest = text.partition("---\n")
    block, delimiter, body = rest.partition("\n---\n")
    assert delimiter, f"{path} frontmatter block is not closed"

    data: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        if not line.strip():
            continue
        if line[0] not in " \t" and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            data[key] = value.strip()
        elif key:  # a wrapped continuation line
            data[key] = f"{data[key]} {line.strip()}".strip()
    return data, body


# --------------------------------------------------------------------------- skills


def test_the_repo_ships_at_least_one_skill():
    assert SKILLS, "no .claude/skills/*/SKILL.md found"


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter_is_wellformed(path):
    data, body = parse_frontmatter(path)
    assert "name" in data, f"{path} frontmatter has no `name`"
    assert "description" in data, f"{path} frontmatter has no `description`"
    assert body.strip(), f"{path} has frontmatter but no body"


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_name_matches_its_directory(path):
    """A skill invoked as `/<name>` must be findable at the name it declares."""
    data, _ = parse_frontmatter(path)
    assert data["name"] == path.parent.name


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_name_is_a_valid_slug(path):
    data, _ = parse_frontmatter(path)
    name = data["name"]
    assert name == name.lower(), f"{name} should be lowercase"
    assert all(c.isalnum() or c == "-" for c in name), f"{name} should be kebab-case"


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_description_can_actually_trigger(path):
    """A description that only names the skill gives the model nothing to match
    a user's request against, so the skill never fires."""
    description = parse_frontmatter(path)[0]["description"]
    assert MIN_DESCRIPTION <= len(description) <= MAX_DESCRIPTION, len(description)
    assert any(word in description.lower() for word in TRIGGER_WORDS), (
        f"{path.parent.name}: description states what it is but not when to use it"
    )


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_descriptions_are_distinct(path):
    """Two skills that describe the same trigger surface make the choice
    between them arbitrary."""
    mine = parse_frontmatter(path)[0]["description"]
    for other in SKILLS:
        if other == path:
            continue
        assert mine != parse_frontmatter(other)[0]["description"]


def _reference_resolves(ref: str) -> bool:
    """True when a path referenced in prose is one a reader can actually follow.

    A reference is satisfied by the file itself, or by a `*.template.md`
    sibling. The template case is not a loophole: `evidence/05-verdict.md` is an
    *output* the week produces from `05-verdict.template.md`, and a skill that
    tells the operator where the verdict goes is correct to name the
    destination rather than the blank.
    """
    target = REPO / ref
    if target.exists():
        return True
    template = target.with_name(f"{target.stem}.template{target.suffix}")
    return template.exists()


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_paths_referenced_by_a_skill_exist(path):
    """A skill that points at a moved file sends the model somewhere empty.

    This caught the `mcp/` -> `mcp_server/` rename before a reader did.
    """
    import re

    body = parse_frontmatter(path)[1]
    referenced = set(re.findall(r"`((?:[\w.-]+/)+[\w.-]+)`", body))
    missing = sorted(ref for ref in referenced if not _reference_resolves(ref))
    assert not missing, f"{path.parent.name} references paths that do not exist: {missing}"


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_paths_referenced_by_an_agent_exist(path):
    import re

    body = parse_frontmatter(path)[1]
    referenced = set(re.findall(r"`((?:[\w.-]+/)+[\w.-]+)`", body))
    missing = sorted(ref for ref in referenced if not _reference_resolves(ref))
    assert not missing, f"{path.stem} references paths that do not exist: {missing}"


# --------------------------------------------------------------------------- agents


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agent_frontmatter_is_wellformed(path):
    data, body = parse_frontmatter(path)
    assert data.get("name") == path.stem, f"{path} name must match its filename"
    assert data.get("description"), f"{path} has no description"
    assert body.strip(), f"{path} has no instructions"


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agent_description_can_actually_trigger(path):
    description = parse_frontmatter(path)[0]["description"]
    assert MIN_DESCRIPTION <= len(description) <= MAX_DESCRIPTION
    assert any(word in description.lower() for word in TRIGGER_WORDS)


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agent_tools_are_named_not_wildcarded(path):
    """An agent granted `*` has whatever the parent has, which is not a
    reviewable grant. Naming the tools makes the blast radius readable."""
    data, _ = parse_frontmatter(path)
    tools = data.get("tools")
    if tools is None:
        return
    assert "*" not in tools, f"{path.stem} requests wildcard tools"
    named = [t.strip() for t in tools.split(",") if t.strip()]
    assert named, f"{path.stem} has an empty tools list"


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_a_read_only_reviewer_cannot_write(path):
    """The contract reviewer reports; it does not fix. A reviewer that can edit
    the code it is judging can make its own findings disappear."""
    data, _ = parse_frontmatter(path)
    if "review" not in data["name"]:
        return
    tools = data.get("tools", "")
    for forbidden in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        assert forbidden not in tools, f"{path.stem} should not be able to {forbidden}"


# ------------------------------------------------------------------------- settings


def test_settings_is_valid_json():
    assert SETTINGS.is_file(), "no .claude/settings.json"
    json.loads(SETTINGS.read_text(encoding="utf-8"))


def test_every_hook_command_points_at_a_file_that_exists_and_runs():
    """A hook referencing a missing script fails on every single edit, and the
    failure is easy to mistake for the harness misbehaving."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for group in settings.get("hooks", {}).values()
        for matcher in group
        for hook in matcher.get("hooks", [])
        if hook.get("type") == "command"
    ]
    assert commands, "settings.json declares no command hooks"
    for command in commands:
        script = next(
            (token for token in command.split() if token.endswith((".sh", ".py"))),
            None,
        )
        assert script, f"cannot identify a script in hook command: {command}"
        resolved = REPO / script
        assert resolved.is_file(), f"hook script missing: {script}"
        assert os.access(resolved, os.X_OK), f"hook script not executable: {script}"


@pytest.mark.skipif(sys.platform == "win32", reason="CRLF line endings on Windows break bash syntax check")
def test_hook_scripts_are_syntactically_valid():
    import subprocess

    for script in sorted((CLAUDE / "hooks").glob("*.sh")) + sorted((REPO / ".githooks").glob("*")):
        if not script.is_file():
            continue
        proc = subprocess.run(
            ["bash", "-n", script.name], cwd=script.parent, capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, f"{script.name}: {proc.stderr}"


@pytest.mark.skipif(sys.platform == "win32", reason="Executable permissions not checked natively on Windows")
def test_git_hooks_are_executable():
    for script in sorted((REPO / ".githooks").glob("*")):
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR, f"{script.name} is not executable; `make hooks` would install a no-op"


def test_permissions_deny_reading_the_files_that_hold_credentials():
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    deny = " ".join(settings.get("permissions", {}).get("deny", []))
    for secret_path in (".env", "mcp.json", "traces/raw"):
        assert secret_path in deny, f"{secret_path} is not denied in settings.json"


def test_permissions_deny_the_planlint_write_verbs():
    """Defence in depth. `guards.py` refuses these inside the tool; this stops
    a shell call from going around it."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    deny = " ".join(settings.get("permissions", {}).get("deny", []))
    for verb in ("init", "new", "witness"):
        assert f"planlint {verb}" in deny


def test_no_skill_or_agent_contains_a_credential():
    from scan_evidence import scan_file

    for path in [*SKILLS, *AGENTS, SETTINGS]:
        assert scan_file(path) == [], f"{path} tripped the secret scan"
