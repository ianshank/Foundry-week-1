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


def _relative_closure(entry: Path) -> tuple[Path, ...]:
    """`entry`, plus every sibling module it reaches by relative import.

    Equal to `(guards.py,)` today, and the point is that it is *derived*.

    The static checks below have to know which file holds the policy. Naming
    that file is fine while there is one; the day policy is split across two,
    an enumerated list inspects half of it and reports success -- and the
    enumerated list is exactly the thing nobody remembers to update. That is
    not hypothetical: `guards.py` is a standing decomposition candidate, and a
    naive split would move `_SECRET_PATTERNS` into a module this file no longer
    reads, halving the guarantee while the suite stayed green.

    So this is the prerequisite for splitting safely, not a prediction that it
    will happen. Deriving the set costs twenty lines and makes the guarantee
    follow the code wherever it goes.
    """
    seen: set[Path] = set()
    queue = [entry]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        tree = ast.parse(current.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            candidates = [node.module] if node.module else [a.name for a in node.names]
            for candidate in candidates:
                if not candidate:
                    continue
                head = candidate.split(".")[0]
                sibling = current.parent / (head + ".py")
                if sibling.is_file():
                    queue.append(sibling)
    return tuple(sorted(seen))


#: Every file the policy guarantee has to hold over.
POLICY_SOURCES = _relative_closure(GUARDS_SOURCE)

#: The four refusal lists, the credential rule table, and the table's public
#: alias.
#:
#: `_SECRET_PATTERNS` is on this list because both this file's docstring and
#: `guards.py`'s claim the credential patterns cannot be widened by setting a
#: variable -- and until now the static half did not look at them, for two
#: independent reasons either of which alone would have sunk it. It was not in
#: the name set, *and* it is written `_SECRET_PATTERNS: tuple[...] = (...)`,
#: an `ast.AnnAssign`, invisible to a walk that only handled `ast.Assign`.
#:
#: What defended that sentence in the meantime was one behavioural test
#: covering the `ghp_` rule -- 1 of 22 -- and the accident that the patterns
#: happen to live in the file the check happens to read.
LITERAL_FROZENSETS = frozenset({"ALLOWED_VERBS", "REFUSED_VERBS", "DENIED_FLAGS", "VALUE_OPTIONS"})
LITERAL_RULE_TABLE = "_SECRET_PATTERNS"
PUBLIC_ALIAS = "SECRET_PATTERNS"
POLICY_NAMES = LITERAL_FROZENSETS | {LITERAL_RULE_TABLE, PUBLIC_ALIAS}


def _module_assignments(tree: ast.Module) -> list[tuple[str, ast.expr]]:
    """Every module-level `name = value`, annotated or not.

    Handling `ast.AnnAssign` is not tidiness. `_SECRET_PATTERNS` carries a type
    annotation and was therefore invisible to the previous walk, which means
    adding its name to the checked set would still have checked nothing.
    """
    found: list[tuple[str, ast.expr]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            found.extend(
                (target.id, node.value) for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            found.append((node.target.id, node.value))
    return found


def _is_written_out_pattern(node: ast.expr) -> bool:
    """True for a string literal, or `re.compile(<string literal>)`.

    Anything else -- a name, a variable, an f-string, a call with a computed
    argument -- is a pattern assembled at runtime, and a pattern assembled at
    runtime can be assembled from the environment.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if not isinstance(node, ast.Call) or node.keywords:
        return False
    function = node.func
    is_compile = (isinstance(function, ast.Attribute) and function.attr == "compile") or (
        isinstance(function, ast.Name) and function.id == "compile"
    )
    if not is_compile or len(node.args) != 1:
        return False
    argument = node.args[0]
    return isinstance(argument, ast.Constant) and isinstance(argument.value, str)


def _policy_violations(source: str) -> list[str]:
    """One entry per policy constant that is assembled rather than written out.

    Takes source *text*, not a path, so the mutants in
    `test_the_shape_rule_rejects_a_widenable_policy_constant` can prove this
    function rejects something. A static guard that has only ever been run
    against conforming source has never been shown to reject anything -- which
    is the state its predecessor was in with respect to the credential table.
    """
    violations: list[str] = []
    for name, value in _module_assignments(ast.parse(source)):
        if name in LITERAL_FROZENSETS:
            if not isinstance(value, ast.Call):
                violations.append(name + " is not a frozenset(...) of literals")
                continue
            violations.extend(
                name + " is built from " + ast.dump(argument)[:60] + ", not a literal"
                for argument in value.args
                if not isinstance(argument, ast.Set | ast.List | ast.Tuple)
            )
        elif name == LITERAL_RULE_TABLE:
            if not isinstance(value, ast.Tuple):
                violations.append(name + " is not a tuple literal")
                continue
            for index, element in enumerate(value.elts):
                where = name + "[" + str(index) + "]"
                if not (
                    isinstance(element, ast.Call)
                    and isinstance(element.func, ast.Name)
                    and element.func.id == "SecretRule"
                ):
                    violations.append(where + " is not a SecretRule(...) call")
                    continue
                violations.extend(
                    where + " takes a pattern that is not written out here"
                    for argument in element.args
                    if not _is_written_out_pattern(argument)
                )
        elif name == PUBLIC_ALIAS and not (
            isinstance(value, ast.Name) and value.id == LITERAL_RULE_TABLE
        ):
            # The alias must be a bare rebinding. `SECRET_PATTERNS =
            # list(_SECRET_PATTERNS)` and `= _OTHER` are both places the public
            # list could diverge from the checked one, and `scan_evidence.py`
            # imports the public name, not the private one.
            violations.append(name + " is not a bare rebinding of " + LITERAL_RULE_TABLE)
    return violations


def _policy_names_defined(source: str) -> set[str]:
    return {name for name, _ in _module_assignments(ast.parse(source))} & POLICY_NAMES


#: Each of these passes the shape rule this file shipped before. The first two
#: are the real defect: the annotated form defeats an `ast.Assign`-only walk,
#: and a call-built table defeats a name set that never listed it.
_MUTANTS = {
    "annotated verb list": "ALLOWED_VERBS: frozenset[str] = frozenset(_from_env())",
    "call-built rule table": "_SECRET_PATTERNS: tuple[SecretRule, ...] = tuple(_load_rules())",
    "env-widened pattern": (
        "_SECRET_PATTERNS: tuple[SecretRule, ...] = (\n"
        "    SecretRule(re.compile(os.environ['P']), 'x', 'y'),\n"
        ")"
    ),
    "pattern from a name": (
        "_SECRET_PATTERNS: tuple[SecretRule, ...] = (\n"
        "    SecretRule(_GITHUB_TOKEN_RE, '[REDACTED]', 'github-token'),\n"
        ")"
    ),
    "alias through a call": "SECRET_PATTERNS = list(_SECRET_PATTERNS)",
    "alias to something else": "SECRET_PATTERNS = _OTHER_PATTERNS",
    "verb list from a call": "ALLOWED_VERBS = frozenset(_read('VERBS'))",
}

_CONFORMING = (
    "ALLOWED_VERBS = frozenset({'validate', 'diff'})\n"
    "_SECRET_PATTERNS: tuple[SecretRule, ...] = (\n"
    "    SecretRule(re.compile('gh[pousr]_'), '[REDACTED]', 'github-token'),\n"
    ")\n"
    "SECRET_PATTERNS = _SECRET_PATTERNS\n"
)


@pytest.mark.parametrize("label", sorted(_MUTANTS))
def test_the_shape_rule_rejects_a_widenable_policy_constant(label: str) -> None:
    """Seven mutants, every one of which the previous shape rule accepted."""
    assert _policy_violations(_MUTANTS[label]), (
        f"{label!r} passed the shape rule. This file's docstring says the "
        "credential patterns cannot be widened by setting a variable; until "
        "this parametrisation existed, one behavioural test covering 1 of 22 "
        "rules was the entire defence of that sentence."
    )


def test_the_shape_rule_accepts_policy_that_is_written_out() -> None:
    """The other half: it must be able to return empty, or it is not a check."""
    assert not _policy_violations(_CONFORMING)


@pytest.mark.parametrize("source", POLICY_SOURCES, ids=lambda path: path.name)
def test_no_policy_source_reaches_the_environment(source: Path) -> None:
    imported = _imported_names(source)
    assert not imported & FORBIDDEN_IMPORTS, (
        f"{source.name} imports {sorted(imported & FORBIDDEN_IMPORTS)}. "
        "Policy that can read configuration is configuration."
    )
    assert not imported & FORBIDDEN_PACKAGE_MODULES, (
        f"{source.name} imports this package's own config loader. "
        "Deployment settings belong in config.py; the refusal surface must not read them."
    )


@pytest.mark.parametrize("source", POLICY_SOURCES, ids=lambda path: path.name)
def test_no_policy_constant_is_built_from_a_call(source: Path) -> None:
    """A literal cannot be widened at import time. A call could be, and the
    call is where an `os.environ.get` would eventually be threaded in."""
    violations = _policy_violations(source.read_text(encoding="utf-8"))
    assert not violations, (
        f"{source.name}: "
        + "; ".join(violations)
        + ". A policy constant assembled at runtime can be assembled from the environment."
    )


def test_every_policy_constant_is_somewhere_in_the_closure() -> None:
    """Completeness, over the closure rather than over one named file.

    Keyed off the full set on purpose: adding a name to `POLICY_NAMES` without
    teaching `_module_assignments` to walk its node type fails here loudly,
    instead of silently checking nothing. That is precisely how
    `_SECRET_PATTERNS` would have escaped a half-done fix.
    """
    defined: set[str] = set()
    for source in POLICY_SOURCES:
        defined |= _policy_names_defined(source.read_text(encoding="utf-8"))

    assert defined == POLICY_NAMES, (
        f"policy constants missing from the closure {[p.name for p in POLICY_SOURCES]}: "
        f"{sorted(POLICY_NAMES - defined)}"
    )


def test_the_closure_pins_todays_single_file_policy() -> None:
    """Looks like a tautology and is not.

    It is the counterpart of `test_seam_is_closed.py`'s `assert one_shot or
    spawned`: a check that the derived audit is still pointed at a real module.
    Without it, a `_relative_closure` bug returning `()` turns every
    parametrisation above into zero test cases -- which pytest reports as
    green, and which is the exact failure this whole file exists to refuse.
    """
    assert POLICY_SOURCES == (GUARDS_SOURCE,), (
        "policy has been split across more than one file. That is allowed -- "
        "the closure follows it. Update this pin deliberately, and confirm the "
        "parametrised checks above now run once per file."
    )


def test_the_closure_follows_a_relative_import(tmp_path: Path) -> None:
    """Proof the closure walks, run against a package it constructs itself."""
    (tmp_path / "a.py").write_text("from .b import X\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from . import c\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("VALUE = 2\n", encoding="utf-8")

    closure = _relative_closure(tmp_path / "a.py")

    assert {path.name for path in closure} == {"a.py", "b.py", "c.py"}, (
        "the closure must follow relative imports transitively, and must not "
        "sweep in siblings nothing imports"
    )
