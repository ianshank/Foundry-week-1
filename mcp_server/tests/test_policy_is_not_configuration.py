"""The one architectural opinion in this repository, finally pinned.

`README.md` states it, `SECURITY.md` states it, `config.py`'s docstring states
it and `docs/architecture/C4.md` draws it: **policy is not configuration.**
`config.py` reads the environment; `guards.py` does not. The verb allow list,
the flag deny list and the credential patterns cannot be widened by setting a
variable, because an allow list that can be is not an allow list.

Until this file existed, nothing tested it. Four documents asserted the
property and zero tests defended it, which is the state a claim is in just
before it quietly stops being true. A review found the gap; this is the fix.

Two halves, because either one alone is a partial guarantee:

* **Behavioural** -- setting the most plausible variable names an impatient
  operator would reach for at 11pm changes nothing about what is refused.
* **Static** -- `guards.py` imports no environment access at all, so the
  behavioural half cannot be defeated by a variable nobody thought to try.
  Enumerating variable names can only ever test the ones enumerated; the
  import check is what makes the property total.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from foundry_spike_mcp import guards
from foundry_spike_mcp.config import load_planlint_config

GUARDS_SOURCE = Path(guards.__file__)

#: Modules that would let policy read its own configuration. `os` and `dotenv`
#: reach the environment; `config` is this package's own loader, and importing
#: it into `guards` is how the separation would most plausibly erode -- not
#: maliciously, but as a convenience during a late debugging session.
FORBIDDEN_IMPORTS = frozenset({"os", "dotenv", "environ"})
FORBIDDEN_PACKAGE_MODULES = frozenset({"config"})

#: What an operator trying to widen the tool would actually try. Not exhaustive
#: by construction, which is precisely why the static check below exists too.
WIDENING_ATTEMPTS = {
    "PLANLINT_ALLOWED_VERBS": "init,new,witness,make",
    "PLANLINT_ALLOW_VERBS": "init",
    "ALLOWED_VERBS": "init",
    "PLANLINT_DENIED_FLAGS": "",
    "DENIED_FLAGS": "",
    "PLANLINT_ALLOW_FORCE": "1",
    "FOUNDRY_SPIKE_ALLOW_WRITES": "true",
    "FOUNDRY_SPIKE_SECRET_PATTERNS": "",
    "SECRET_PATTERNS": "",
    "PLANLINT_DISABLE_GUARDS": "1",
}


@pytest.fixture
def widened(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set every plausible widening variable at once, then assert nothing moved.

    Together rather than one at a time on purpose: if any single one had an
    effect, a test that set them individually could still miss an interaction.
    """
    for name, value in WIDENING_ATTEMPTS.items():
        monkeypatch.setenv(name, value)


#: Spelled out rather than compared against the module's own constant, which
#: would compare the value to itself and pass however it had been widened.
EXPECTED_VERBS = frozenset({"detect", "validate", "graph", "rules", "waivers", "delta"})


def test_the_verb_allow_list_does_not_move(widened):
    assert EXPECTED_VERBS == guards.ALLOWED_VERBS


@pytest.mark.parametrize("verb", sorted(guards.REFUSED_VERBS))
def test_a_mutating_verb_is_still_refused(widened, verb):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_verb(verb)
    assert caught.value.reason == "verb_not_allowed"


@pytest.mark.parametrize("flag", sorted(guards.DENIED_FLAGS))
def test_a_mutating_flag_is_still_denied(widened, flag):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.assert_safe_argv(["planlint", "validate", flag])
    assert caught.value.reason == "denied_flag"


def test_credential_patterns_still_redact(widened):
    token = "ghp_" + "D" * 36
    assert token not in guards.redact(f"leaked {token}")


def test_the_allow_list_still_fails_closed(widened, tmp_path):
    """No roots means nothing is readable. There is no wildcard, and no
    variable that introduces one."""
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_target(str(tmp_path), ())
    assert caught.value.reason == "no_allowed_roots"


def test_configuration_still_works_while_policy_does_not_budge(widened, tmp_path):
    """The other half of the asymmetry: this is not a module that ignores the
    environment, it is a module that reads the environment for *deployment*
    settings only. A test that only proved unresponsiveness would pass just as
    well if config loading were broken."""
    loaded = load_planlint_config({"PLANLINT_TIMEOUT": "7", "PLANLINT_BIN": "/usr/bin/planlint"})
    assert loaded.timeout_seconds == 7
    assert loaded.binary == "/usr/bin/planlint"


# --------------------------------------------------------------------------
# Static half. Enumerated variable names can only test the names enumerated.
# --------------------------------------------------------------------------


def _imported_names(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
            if node.level:  # a relative import: `from . import config`
                names.update(alias.name for alias in node.names)
    return names


def test_guards_imports_nothing_that_reaches_the_environment():
    imported = _imported_names(GUARDS_SOURCE)
    assert not imported & FORBIDDEN_IMPORTS, (
        f"{GUARDS_SOURCE.name} imports {sorted(imported & FORBIDDEN_IMPORTS)}. "
        "Policy that can read configuration is configuration."
    )
    assert not imported & FORBIDDEN_PACKAGE_MODULES, (
        f"{GUARDS_SOURCE.name} imports this package's own config loader. "
        "Deployment settings belong in config.py; the refusal surface must not read them."
    )


def test_no_policy_constant_is_built_from_a_call():
    """A frozenset literal cannot be widened at import time. A frozenset built
    from a function call could be, and the call is where a `os.environ.get`
    would eventually be threaded in."""
    tree = ast.parse(GUARDS_SOURCE.read_text(encoding="utf-8"))
    policy_names = {"ALLOWED_VERBS", "REFUSED_VERBS", "DENIED_FLAGS", "VALUE_OPTIONS"}
    seen: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id not in policy_names:
                continue
            seen.add(target.id)
            assert isinstance(node.value, ast.Call), (
                f"{target.id} is expected to be a frozenset(...) of literals"
            )
            for argument in node.value.args:
                assert isinstance(argument, ast.Set | ast.List | ast.Tuple), (
                    f"{target.id} is built from {ast.dump(argument)[:60]}, not a literal. "
                    "A policy constant assembled at runtime can be assembled from the environment."
                )
    assert seen == policy_names, f"policy constants not found in {GUARDS_SOURCE.name}: {seen}"
