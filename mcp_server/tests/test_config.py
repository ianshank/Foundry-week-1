"""Configuration is loaded, not guessed.

The rule under test throughout: an *absent* setting falls back to a documented
default; a *malformed* setting raises `ConfigError`, which callers map to
BLOCKED. Silently substituting a default for `PLANLINT_TIMEOUT=abc` would hide
an operator mistake behind a result that looks fine.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from foundry_spike_mcp.config import (
    DEFAULT_FAIL_ON_VALUES,
    DEFAULT_JSON_FLAG,
    DEFAULT_MAX_ARTIFACT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ConfigError,
    load_eval_config,
    load_log_config,
    load_planlint_config,
)


def test_empty_environment_yields_documented_defaults():
    config = load_planlint_config({})
    assert config.binary == "planlint"
    assert config.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert config.json_flag == DEFAULT_JSON_FLAG
    assert config.fail_on_values == DEFAULT_FAIL_ON_VALUES
    assert config.allowed_roots == ()  # no wildcard fallback


def test_allowed_roots_falls_back_to_target_not_to_everything(tmp_path):
    config = load_planlint_config({"PLANLINT_TARGET": str(tmp_path)})
    assert config.allowed_roots == (tmp_path.resolve(),)


def test_explicit_allow_list_overrides_target_so_it_can_narrow(tmp_path):
    """Ordered fallback, not a merge. Merging would mean the allow list could
    only ever widen, which defeats the point of having one."""
    inner = tmp_path / "inner"
    inner.mkdir()
    config = load_planlint_config(
        {"PLANLINT_TARGET": str(tmp_path), "PLANLINT_ALLOWED_ROOTS": str(inner)}
    )
    assert config.allowed_roots == (inner.resolve(),)


def test_multiple_roots_split_on_the_path_separator(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    config = load_planlint_config({"PLANLINT_ALLOWED_ROOTS": f"{a}{os.pathsep}{b}"})
    assert config.allowed_roots == (a.resolve(), b.resolve())


def test_relative_allowed_root_is_a_config_error():
    """A relative root is not an allow list; it is a wish about the cwd."""
    with pytest.raises(ConfigError):
        load_planlint_config({"PLANLINT_ALLOWED_ROOTS": "./specs"})


@pytest.mark.parametrize("value", ["abc", "0", "-5", "1.5"])
def test_malformed_timeout_raises_rather_than_silently_defaulting(value):
    with pytest.raises(ConfigError):
        load_planlint_config({"PLANLINT_TIMEOUT": value})


def test_absent_timeout_uses_the_default():
    assert load_planlint_config({}).timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_json_flag_can_be_explicitly_disabled_but_absence_means_default():
    assert load_planlint_config({"PLANLINT_JSON_FLAG": ""}).json_flag is None
    assert load_planlint_config({"PLANLINT_JSON_FLAG": "  "}).json_flag is None
    assert load_planlint_config({}).json_flag == DEFAULT_JSON_FLAG
    assert load_planlint_config({"PLANLINT_JSON_FLAG": "--format=json"}).json_flag == "--format=json"


def test_fail_on_vocabulary_is_deployment_configurable():
    """planlint's severity words are a property of the installed build, so the
    vocabulary is configuration. Which *verbs* may run is not -- that is policy
    and lives in guards.py."""
    config = load_planlint_config({"PLANLINT_FAIL_ON_VALUES": "error, blocker"})
    assert config.fail_on_values == ("ERROR", "BLOCKER")


def test_eval_config_keeps_its_own_allow_list(tmp_path):
    """Separate from planlint's: the eval sink and the spec repo are different
    trust surfaces and must not be widened together by accident."""
    sink = tmp_path / "runs"
    sink.mkdir()
    config = load_eval_config({"EVAL_SINK_DIR": str(sink)})
    assert config.sink_dir == sink
    assert config.allowed_roots == (sink.resolve(),)
    assert config.max_artifact_bytes == DEFAULT_MAX_ARTIFACT_BYTES


def test_eval_config_without_a_sink_has_no_roots():
    config = load_eval_config({})
    assert config.sink_dir is None
    assert config.allowed_roots == ()


def test_log_config_defaults_to_quiet_text():
    config = load_log_config({})
    assert config.level == "WARNING"
    assert config.fmt == "text"


def test_config_objects_are_frozen():
    """A single tool call stays internally consistent even if the process
    environment changes underneath it."""
    config = load_planlint_config({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.timeout_seconds = 1  # type: ignore[misc]


def test_loader_reads_the_mapping_it_is_given_not_os_environ(monkeypatch):
    monkeypatch.setenv("PLANLINT_BIN", "from-os-environ")
    assert load_planlint_config({"PLANLINT_BIN": "injected"}).binary == "injected"
