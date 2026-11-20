"""config.py — load and validate nightshift.toml.

Design decisions:
- Uses ``tomllib`` (Python 3.11 stdlib), no extra dependency.
- ``NightShiftConfig`` is a frozen dataclass so it's read-only after load.
- ``DiaryConfig`` is nested inside ``NightShiftConfig``.
- All fields have documented defaults; only ``test_command`` is required
  (no sensible universal default exists for it).
- Secrets are never read from the config file — the design doc says tokens
  come from environment variables only, handled by the ``gh`` CLI.
- ``load()`` searches cwd first, then ``~/.config/nightshift/config.toml``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

_DEFAULT_GHOST_NAMES = ["Casper", "Spook", "Wraith", "Phantom", "Specter"]


@dataclass(frozen=True)
class DiaryConfig:
    ghost_names: list[str] = field(default_factory=lambda: list(_DEFAULT_GHOST_NAMES))
    output_dir: str = ".nightshift/diary"


@dataclass(frozen=True)
class NightShiftConfig:
    # Required — no default (must be present in the config file)
    test_command: str

    # Optional with defaults
    label: str = "night-shift"
    max_issues: int = 5
    max_minutes: int = 15
    max_files: int = 20
    max_lines: int = 500
    branch_prefix: str = "night-shift/"
    dry_run: bool = False

    # Nested sub-config
    diary: DiaryConfig = field(default_factory=DiaryConfig)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {"test_command"}

_INT_FIELDS = {"max_issues", "max_minutes", "max_files", "max_lines"}
_BOOL_FIELDS = {"dry_run"}
_STR_FIELDS = {"label", "test_command", "branch_prefix"}
_SECRET_KEYS = {
    "token",
    "github_token",
    "gh_token",
    "api_key",
    "secret",
    "password",
}


class ConfigError(ValueError):
    """Raised when the config file is missing or invalid."""


def _check_no_secrets(raw: dict) -> None:
    """Raise ConfigError if any secret-like key appears in the raw dict."""
    nightshift_section = raw.get("nightshift", {})
    for key in nightshift_section:
        if key.lower() in _SECRET_KEYS:
            raise ConfigError(
                f"Config field '{key}' looks like a secret. "
                "Night Shift never reads tokens from nightshift.toml. "
                "Use environment variables (e.g. GH_TOKEN) instead."
            )


def _parse_nightshift_section(section: dict) -> dict:
    """Validate types in the [nightshift] section and return a clean dict."""
    errors: list[str] = []

    for f in _REQUIRED_FIELDS:
        if f not in section:
            errors.append(f"Missing required field: nightshift.{f}")

    for f in _INT_FIELDS:
        if f in section and not isinstance(section[f], int):
            errors.append(f"nightshift.{f} must be an integer, got {type(section[f]).__name__}")

    for f in _BOOL_FIELDS:
        if f in section and not isinstance(section[f], bool):
            errors.append(f"nightshift.{f} must be a boolean, got {type(section[f]).__name__}")

    for f in _STR_FIELDS:
        if f in section and not isinstance(section[f], str):
            errors.append(f"nightshift.{f} must be a string, got {type(section[f]).__name__}")

    if errors:
        raise ConfigError("Configuration errors:\n" + "\n".join(f"  • {e}" for e in errors))

    return section


def _parse_diary_section(section: dict) -> DiaryConfig:
    """Validate and construct a DiaryConfig from the [diary] section."""
    ghost_names = section.get("ghost_names", _DEFAULT_GHOST_NAMES)
    if not isinstance(ghost_names, list) or not all(isinstance(n, str) for n in ghost_names):
        raise ConfigError("diary.ghost_names must be a list of strings")
    if not ghost_names:
        raise ConfigError("diary.ghost_names must not be empty")

    output_dir = section.get("output_dir", ".nightshift/diary")
    if not isinstance(output_dir, str):
        raise ConfigError("diary.output_dir must be a string")

    return DiaryConfig(ghost_names=ghost_names, output_dir=output_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load(path: Path | None = None) -> NightShiftConfig:
    """Load and validate a nightshift.toml file.

    Search order when *path* is ``None``:
    1. ``{cwd}/nightshift.toml``
    2. ``~/.config/nightshift/config.toml``

    Raises
    ------
    ConfigError
        If no config file is found, a required field is missing, or a type
        is wrong.
    """
    if path is None:
        candidates = [
            Path.cwd() / "nightshift.toml",
            Path.home() / ".config" / "nightshift" / "config.toml",
        ]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break
        else:
            raise ConfigError(
                "No nightshift.toml found in the current directory or "
                "~/.config/nightshift/config.toml.  "
                "Copy nightshift.toml.example to nightshift.toml and edit it."
            )

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc

    _check_no_secrets(raw)

    nightshift_section = raw.get("nightshift", {})
    _parse_nightshift_section(nightshift_section)  # validates and raises early

    diary_section = raw.get("diary", {})
    diary = _parse_diary_section(diary_section)

    return NightShiftConfig(
        test_command=nightshift_section["test_command"],
        label=nightshift_section.get("label", "night-shift"),
        max_issues=nightshift_section.get("max_issues", 5),
        max_minutes=nightshift_section.get("max_minutes", 15),
        max_files=nightshift_section.get("max_files", 20),
        max_lines=nightshift_section.get("max_lines", 500),
        branch_prefix=nightshift_section.get("branch_prefix", "night-shift/"),
        dry_run=nightshift_section.get("dry_run", False),
        diary=diary,
    )
