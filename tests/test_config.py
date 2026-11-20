"""Tests for nightshift.config."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nightshift.config import (
    ConfigError,
    DiaryConfig,
    NightShiftConfig,
    load,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_toml(path: Path, content: str) -> Path:
    """Write *content* to *path* and return *path*."""
    path.write_text(content, encoding="utf-8")
    return path


def minimal_toml(tmp_path: Path, **overrides: str) -> Path:
    """Write the smallest valid nightshift.toml to *tmp_path* and return it."""
    lines = [
        "[nightshift]",
        'test_command = "pytest"',
    ]
    for k, v in overrides.items():
        lines.append(f"{k} = {v!r}")
    return write_toml(tmp_path / "nightshift.toml", "\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Valid config loading
# ---------------------------------------------------------------------------


class TestLoadValid:
    def test_minimal_config_loads(self, tmp_path: Path) -> None:
        cfg = load(minimal_toml(tmp_path))
        assert cfg.test_command == "pytest"

    def test_defaults_applied(self, tmp_path: Path) -> None:
        cfg = load(minimal_toml(tmp_path))
        assert cfg.label == "night-shift"
        assert cfg.max_issues == 5
        assert cfg.max_minutes == 15
        assert cfg.max_files == 20
        assert cfg.max_lines == 500
        assert cfg.branch_prefix == "night-shift/"
        assert cfg.dry_run is False

    def test_full_config_overrides_defaults(self, tmp_path: Path) -> None:
        content = """\
[nightshift]
label = "my-label"
max_issues = 3
max_minutes = 10
max_files = 5
max_lines = 100
test_command = "make test"
branch_prefix = "bot/"
dry_run = true

[diary]
ghost_names = ["Boo", "Moo"]
output_dir = ".ns/diary"
"""
        cfg = load(write_toml(tmp_path / "nightshift.toml", content))
        assert cfg.label == "my-label"
        assert cfg.max_issues == 3
        assert cfg.max_minutes == 10
        assert cfg.max_files == 5
        assert cfg.max_lines == 100
        assert cfg.test_command == "make test"
        assert cfg.branch_prefix == "bot/"
        assert cfg.dry_run is True
        assert cfg.diary.ghost_names == ["Boo", "Moo"]
        assert cfg.diary.output_dir == ".ns/diary"

    def test_returns_nightshift_config(self, tmp_path: Path) -> None:
        cfg = load(minimal_toml(tmp_path))
        assert isinstance(cfg, NightShiftConfig)

    def test_diary_defaults(self, tmp_path: Path) -> None:
        cfg = load(minimal_toml(tmp_path))
        assert isinstance(cfg.diary, DiaryConfig)
        assert len(cfg.diary.ghost_names) > 0

    def test_explicit_path(self, tmp_path: Path) -> None:
        p = tmp_path / "custom.toml"
        write_toml(p, '[nightshift]\ntest_command = "cargo test"\n')
        cfg = load(p)
        assert cfg.test_command == "cargo test"


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


class TestMissingRequired:
    def test_missing_test_command_raises(self, tmp_path: Path) -> None:
        p = write_toml(tmp_path / "nightshift.toml", "[nightshift]\n")
        with pytest.raises(ConfigError, match="test_command"):
            load(p)

    def test_error_message_mentions_field_name(self, tmp_path: Path) -> None:
        p = write_toml(tmp_path / "nightshift.toml", "[nightshift]\n")
        with pytest.raises(ConfigError) as exc_info:
            load(p)
        assert "test_command" in str(exc_info.value)

    def test_no_config_file_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nightshift.toml"
        with pytest.raises(ConfigError):
            load(missing)


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------


class TestTypeValidation:
    def test_max_issues_must_be_int(self, tmp_path: Path) -> None:
        p = write_toml(
            tmp_path / "nightshift.toml",
            '[nightshift]\ntest_command = "pytest"\nmax_issues = "five"\n',
        )
        with pytest.raises(ConfigError, match="max_issues"):
            load(p)

    def test_dry_run_must_be_bool(self, tmp_path: Path) -> None:
        p = write_toml(
            tmp_path / "nightshift.toml",
            '[nightshift]\ntest_command = "pytest"\ndry_run = "yes"\n',
        )
        with pytest.raises(ConfigError, match="dry_run"):
            load(p)

    def test_invalid_toml_raises(self, tmp_path: Path) -> None:
        p = write_toml(tmp_path / "nightshift.toml", "[[[[invalid toml")
        with pytest.raises(ConfigError):
            load(p)


# ---------------------------------------------------------------------------
# Secrets must not appear in config
# ---------------------------------------------------------------------------


class TestNoSecrets:
    def test_token_field_rejected(self, tmp_path: Path) -> None:
        p = write_toml(
            tmp_path / "nightshift.toml",
            '[nightshift]\ntest_command = "pytest"\ntoken = "abc123"\n',
        )
        with pytest.raises(ConfigError, match="[Ss]ecret|[Tt]oken"):
            load(p)

    def test_github_token_rejected(self, tmp_path: Path) -> None:
        p = write_toml(
            tmp_path / "nightshift.toml",
            '[nightshift]\ntest_command = "pytest"\ngithub_token = "abc123"\n',
        )
        with pytest.raises(ConfigError):
            load(p)


# ---------------------------------------------------------------------------
# Diary config validation
# ---------------------------------------------------------------------------


class TestDiaryConfig:
    def test_empty_ghost_names_rejected(self, tmp_path: Path) -> None:
        p = write_toml(
            tmp_path / "nightshift.toml",
            '[nightshift]\ntest_command = "pytest"\n[diary]\nghost_names = []\n',
        )
        with pytest.raises(ConfigError):
            load(p)

    def test_ghost_names_must_be_strings(self, tmp_path: Path) -> None:
        p = write_toml(
            tmp_path / "nightshift.toml",
            '[nightshift]\ntest_command = "pytest"\n[diary]\nghost_names = [1, 2]\n',
        )
        with pytest.raises(ConfigError):
            load(p)


# ---------------------------------------------------------------------------
# Property-based: round-trip serialisation
# ---------------------------------------------------------------------------

# Strategy for valid NightShiftConfig values
_valid_str = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_ "),
    min_size=1,
    max_size=50,
)
_valid_prefix = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="-/"),
    min_size=1,
    max_size=20,
)
_ghost_names_strategy = st.lists(
    st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu")), min_size=1, max_size=15),
    min_size=1,
    max_size=10,
)


def config_to_toml(cfg: NightShiftConfig) -> str:
    """Serialise a NightShiftConfig back to TOML for round-trip testing."""
    # Escape TOML strings manually (simple: only need to escape backslash and quote)
    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    ghost_list = "[" + ", ".join(q(n) for n in cfg.diary.ghost_names) + "]"
    return (
        f"[nightshift]\n"
        f"label = {q(cfg.label)}\n"
        f"max_issues = {cfg.max_issues}\n"
        f"max_minutes = {cfg.max_minutes}\n"
        f"max_files = {cfg.max_files}\n"
        f"max_lines = {cfg.max_lines}\n"
        f"test_command = {q(cfg.test_command)}\n"
        f"branch_prefix = {q(cfg.branch_prefix)}\n"
        f"dry_run = {'true' if cfg.dry_run else 'false'}\n"
        f"\n"
        f"[diary]\n"
        f"ghost_names = {ghost_list}\n"
        f"output_dir = {q(cfg.diary.output_dir)}\n"
    )


@settings(max_examples=50)
@given(
    label=_valid_str,
    max_issues=st.integers(min_value=1, max_value=100),
    max_minutes=st.integers(min_value=1, max_value=120),
    max_files=st.integers(min_value=1, max_value=1000),
    max_lines=st.integers(min_value=1, max_value=10000),
    test_command=_valid_str,
    branch_prefix=_valid_prefix,
    dry_run=st.booleans(),
    ghost_names=_ghost_names_strategy,
    output_dir=_valid_str,
)
def test_round_trip(
    tmp_path: Path,
    label: str,
    max_issues: int,
    max_minutes: int,
    max_files: int,
    max_lines: int,
    test_command: str,
    branch_prefix: str,
    dry_run: bool,
    ghost_names: list[str],
    output_dir: str,
) -> None:
    """Any valid NightShiftConfig, when serialised to TOML and re-parsed, is equal."""
    diary = DiaryConfig(ghost_names=ghost_names, output_dir=output_dir)
    original = NightShiftConfig(
        label=label,
        max_issues=max_issues,
        max_minutes=max_minutes,
        max_files=max_files,
        max_lines=max_lines,
        test_command=test_command,
        branch_prefix=branch_prefix,
        dry_run=dry_run,
        diary=diary,
    )
    toml_text = config_to_toml(original)

    # Ensure TOML is parseable before writing to disk
    try:
        tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError:
        # If our serializer produced bad TOML for exotic inputs, skip gracefully
        return

    p = tmp_path / "nightshift.toml"
    p.write_text(toml_text, encoding="utf-8")
    loaded = load(p)

    assert loaded.label == original.label
    assert loaded.max_issues == original.max_issues
    assert loaded.max_minutes == original.max_minutes
    assert loaded.max_files == original.max_files
    assert loaded.max_lines == original.max_lines
    assert loaded.test_command == original.test_command
    assert loaded.branch_prefix == original.branch_prefix
    assert loaded.dry_run == original.dry_run
    assert loaded.diary.ghost_names == original.diary.ghost_names
    assert loaded.diary.output_dir == original.diary.output_dir
