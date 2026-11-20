"""Shared pytest fixtures for Night Shift tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with an initial commit.

    Returns the Path to the repo root.  The repo has:
    - git user configured (required for commits to work without global config)
    - an initial commit on ``main`` so HEAD is valid
    - a remote called ``origin`` pointing at a bare clone in the same tmp dir
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed:\n{result.stderr}"
            )
        return result.stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@nightshift.local")
    git("config", "user.name", "Night Shift Test")

    # Initial commit so HEAD resolves
    readme = repo / "README.md"
    readme.write_text("# Test repo\n")
    git("add", "README.md")
    git("commit", "-m", "Initial commit")

    # Bare remote for push tests
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "clone", "--bare", str(repo), str(bare)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    git("remote", "add", "origin", str(bare))

    return repo


@pytest.fixture()
def nightshift_toml(tmp_path: Path) -> Path:
    """Write a minimal valid nightshift.toml and return its path."""
    config_file = tmp_path / "nightshift.toml"
    config_file.write_text(
        """\
[nightshift]
label = "night-shift"
max_issues = 5
max_minutes = 15
max_files = 20
max_lines = 500
test_command = "pytest"
branch_prefix = "night-shift/"
dry_run = false

[diary]
ghost_names = ["Casper", "Spook", "Wraith", "Phantom", "Specter"]
output_dir = ".nightshift/diary"
"""
    )
    return config_file
