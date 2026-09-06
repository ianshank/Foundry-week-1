"""Every tunable in one place, read from the environment, with typed defaults.

The distinction this module draws, and the reason it is not simply
"no hard-coded values":

**Configuration** is a deployment detail -- where planlint lives, how long to
wait, which severity vocabulary this build understands. It belongs in the
environment, because it differs between the author's laptop, CI, and whatever
box runs session 3. All of it is here.

**Policy** is the refusal surface -- which verbs may run, which flags are
never passed, what a credential looks like. It stays hard-coded in
`guards.py`, on purpose. An allow list that can be widened by setting an
environment variable is not an allow list; it is a suggestion with extra
steps, and the first thing a frustrated operator does at 11pm is widen it.
Making that require a code change, a review and a test is the point.

Config objects are frozen and built by an explicit loader rather than read
lazily from `os.environ` at each use site. That keeps a single call to
`lint_openspec` internally consistent even if the environment changes
underneath it, and it makes every tunable visible in one `repr` when a trace
needs to explain why a run behaved the way it did.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- env names
# Named constants rather than inline strings: a typo in a string literal is a
# silently-ignored setting, which is the worst failure mode a config can have.
ENV_PLANLINT_BIN = "PLANLINT_BIN"
ENV_PLANLINT_TARGET = "PLANLINT_TARGET"
ENV_PLANLINT_ALLOWED_ROOTS = "PLANLINT_ALLOWED_ROOTS"
ENV_PLANLINT_TIMEOUT = "PLANLINT_TIMEOUT"
ENV_PLANLINT_JSON_FLAG = "PLANLINT_JSON_FLAG"
ENV_PLANLINT_FAIL_ON_VALUES = "PLANLINT_FAIL_ON_VALUES"
ENV_EVAL_SINK_DIR = "EVAL_SINK_DIR"
ENV_EVAL_ALLOWED_ROOTS = "EVAL_ALLOWED_ROOTS"
ENV_EVAL_MAX_ARTIFACT_BYTES = "EVAL_MAX_ARTIFACT_BYTES"
ENV_STDERR_LIMIT = "FOUNDRY_SPIKE_STDERR_LIMIT"
ENV_STDOUT_LIMIT = "FOUNDRY_SPIKE_STDOUT_LIMIT"
ENV_FINDINGS_MAX_BYTES = "FOUNDRY_SPIKE_FINDINGS_MAX_BYTES"
ENV_FINDINGS_MAX_DEPTH = "FOUNDRY_SPIKE_FINDINGS_MAX_DEPTH"
ENV_LOG_LEVEL = "FOUNDRY_SPIKE_LOG_LEVEL"
ENV_LOG_FORMAT = "FOUNDRY_SPIKE_LOG_FORMAT"

# -------------------------------------------------------------- defaults
DEFAULT_PLANLINT_BIN = "planlint"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_JSON_FLAG = "--json"
DEFAULT_FAIL_ON_VALUES = ("ERROR", "WARN", "WARNING", "INFO")
DEFAULT_STDERR_LIMIT = 2000
DEFAULT_STDOUT_LIMIT = 20000
DEFAULT_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
#: Ceiling on the planlint stdout this wrapper will parse into `findings`.
#: Sized for a payload a model can actually read: past this the evidence is
#: replaced by a bounded excerpt and the verdict, which comes from the exit
#: code, is unaffected. Deliberately far below `DEFAULT_MAX_ARTIFACT_BYTES`,
#: because that bounds a file a human chose and this bounds a subprocess's
#: output stream.
DEFAULT_FINDINGS_MAX_BYTES = 256 * 1024
#: Depth ceiling for the redaction walk over a parsed payload.
DEFAULT_FINDINGS_MAX_DEPTH = 64
DEFAULT_LOG_LEVEL = "WARNING"
DEFAULT_LOG_FORMAT = "text"


class ConfigError(ValueError):
    """A setting was present but unusable.

    Distinct from "absent". An unset variable falls back to a documented
    default; a variable set to `abc` where an integer belongs is an operator
    mistake, and silently substituting the default would hide it. Callers map
    this to BLOCKED, which is honest: a run configured wrongly could not form
    an opinion.
    """


def _env(source: Mapping[str, str], name: str, default: str = "") -> str:
    return str(source.get(name, default)).strip()


def _positive_int(source: Mapping[str, str], name: str, default: int) -> int:
    raw = _env(source, name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name}={raw!r} is not an integer") from error
    if value <= 0:
        raise ConfigError(f"{name}={value} must be positive")
    return value


def _abs_paths(source: Mapping[str, str], *names: str) -> tuple[Path, ...]:
    """First non-empty variable in `names`, split on the path separator.

    Ordered fallback rather than a merge: `PLANLINT_ALLOWED_ROOTS` overriding
    `PLANLINT_TARGET` means narrowing the allow list is possible. Merging them
    would make the allow list only ever widen, which defeats it.
    """
    for name in names:
        raw = _env(source, name)
        if not raw:
            continue
        roots: list[Path] = []
        for entry in raw.split(os.pathsep):
            entry = entry.strip()
            if not entry:
                continue
            path = Path(entry).expanduser()
            if not path.is_absolute():
                raise ConfigError(f"{name} entry {entry!r} is not an absolute path")
            try:
                roots.append(path.resolve(strict=False))
            except (ValueError, OSError) as error:
                # `resolve` raises on a path the OS cannot represent. Callers
                # catch `ConfigError`; a bare `ValueError` from here escaped
                # them all, because `ConfigError` subclasses `ValueError` and
                # not the other way round. A malformed setting is BLOCKED, and
                # the run says which variable was wrong.
                raise ConfigError(f"{name} entry is unusable: {type(error).__name__}") from error
        if roots:
            return tuple(roots)
    return ()


@dataclass(frozen=True)
class PlanlintConfig:
    """Everything `lint_openspec` needs that is not a caller argument."""

    binary: str = DEFAULT_PLANLINT_BIN
    target: str | None = None
    allowed_roots: tuple[Path, ...] = ()
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    #: None means "this build has no machine-readable flag" -- verdicts stay
    #: correct, findings degrade to raw text. Confirmed by `make baseline`.
    json_flag: str | None = DEFAULT_JSON_FLAG
    fail_on_values: tuple[str, ...] = DEFAULT_FAIL_ON_VALUES
    stderr_limit: int = DEFAULT_STDERR_LIMIT
    stdout_limit: int = DEFAULT_STDOUT_LIMIT
    findings_max_bytes: int = DEFAULT_FINDINGS_MAX_BYTES
    findings_max_depth: int = DEFAULT_FINDINGS_MAX_DEPTH


@dataclass(frozen=True)
class EvalConfig:
    """Everything `score_run` needs that is not a caller argument."""

    sink_dir: Path | None = None
    allowed_roots: tuple[Path, ...] = ()
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    stderr_limit: int = DEFAULT_STDERR_LIMIT


@dataclass(frozen=True)
class LogConfig:
    level: str = DEFAULT_LOG_LEVEL
    fmt: str = DEFAULT_LOG_FORMAT
    extra: dict[str, str] = field(default_factory=dict)


def load_planlint_config(source: Mapping[str, str] | None = None) -> PlanlintConfig:
    """Build a `PlanlintConfig` from the environment (or any mapping).

    Takes a mapping rather than reading `os.environ` directly so tests can
    drive it without mutating global state, and so a future caller could load
    settings from somewhere else without touching this module.
    """
    source = os.environ if source is None else source
    target = _env(source, ENV_PLANLINT_TARGET) or None

    # The allow list falls back to the target alone, never to everything.
    roots = _abs_paths(source, ENV_PLANLINT_ALLOWED_ROOTS, ENV_PLANLINT_TARGET)

    raw_flag = source.get(ENV_PLANLINT_JSON_FLAG)
    if raw_flag is None:
        json_flag: str | None = DEFAULT_JSON_FLAG
    else:
        stripped = raw_flag.strip()
        json_flag = stripped or None  # explicit empty string disables it

    raw_values = _env(source, ENV_PLANLINT_FAIL_ON_VALUES)
    fail_on_values = (
        tuple(v.strip().upper() for v in raw_values.split(",") if v.strip())
        if raw_values
        else DEFAULT_FAIL_ON_VALUES
    )

    return PlanlintConfig(
        binary=_env(source, ENV_PLANLINT_BIN) or DEFAULT_PLANLINT_BIN,
        target=target,
        allowed_roots=roots,
        timeout_seconds=_positive_int(source, ENV_PLANLINT_TIMEOUT, DEFAULT_TIMEOUT_SECONDS),
        json_flag=json_flag,
        fail_on_values=fail_on_values,
        stderr_limit=_positive_int(source, ENV_STDERR_LIMIT, DEFAULT_STDERR_LIMIT),
        stdout_limit=_positive_int(source, ENV_STDOUT_LIMIT, DEFAULT_STDOUT_LIMIT),
        findings_max_bytes=_positive_int(
            source, ENV_FINDINGS_MAX_BYTES, DEFAULT_FINDINGS_MAX_BYTES
        ),
        findings_max_depth=_positive_int(
            source, ENV_FINDINGS_MAX_DEPTH, DEFAULT_FINDINGS_MAX_DEPTH
        ),
    )


def load_eval_config(source: Mapping[str, str] | None = None) -> EvalConfig:
    source = os.environ if source is None else source
    sink_raw = _env(source, ENV_EVAL_SINK_DIR)
    return EvalConfig(
        sink_dir=Path(sink_raw).expanduser() if sink_raw else None,
        allowed_roots=_abs_paths(source, ENV_EVAL_ALLOWED_ROOTS, ENV_EVAL_SINK_DIR),
        max_artifact_bytes=_positive_int(
            source, ENV_EVAL_MAX_ARTIFACT_BYTES, DEFAULT_MAX_ARTIFACT_BYTES
        ),
        stderr_limit=_positive_int(source, ENV_STDERR_LIMIT, DEFAULT_STDERR_LIMIT),
    )


def load_log_config(source: Mapping[str, str] | None = None) -> LogConfig:
    source = os.environ if source is None else source
    return LogConfig(
        level=(_env(source, ENV_LOG_LEVEL) or DEFAULT_LOG_LEVEL).upper(),
        fmt=(_env(source, ENV_LOG_FORMAT) or DEFAULT_LOG_FORMAT).lower(),
    )
