"""agent.py — spawn and supervise a kiro-cli chat session.

Builds the prompt string from an Issue object and invokes the agent command
(default: ``kiro-cli chat --no-interactive --trust-tools=fs_read,fs_write``).
The process runs with a hard timeout (``max_minutes`` from config).  All
output is captured and stored in ``AgentResult``.

Design decisions:
- The prompt is passed as the final positional argument to kiro-cli, not on
  stdin.  Verified working form:
      kiro-cli chat --no-interactive --trust-tools=fs_read,fs_write "<prompt>"
- The agent command is configurable via ``config.agent_command`` (a list of
  strings).  ``run()`` appends the prompt as the last element.
- The agent is granted ``fs_read`` and ``fs_write`` only — never shell access.
  Night Shift runs the tests itself via ``config.test_command``.
- The subprocess ``cwd`` is set to *repo_root* explicitly so the agent always
  sees the right working directory, regardless of the process cwd at the time
  ``run()`` is called.
- Output is truncated to 10 000 characters in ``AgentResult.output`` so that
  large agent logs don't bloat the JSON run log.
- ``run()`` never raises on agent failure or timeout — both conditions are
  surfaced as ``AgentResult(success=False)``.  The caller (runner.py) decides
  how to handle them.
- ``subprocess.TimeoutExpired`` is caught here and re-raised only after the
  process is killed and drained, so resources are always cleaned up.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from nightshift.github import Issue

logger = logging.getLogger(__name__)

# Maximum characters captured from kiro-cli output stored in the run log.
_MAX_OUTPUT_CHARS = 10_000

# Default agent command.  Overridable via config.agent_command.
DEFAULT_AGENT_COMMAND: list[str] = [
    "kiro-cli",
    "chat",
    "--no-interactive",
    "--trust-tools=fs_read,fs_write",
]

# Prompt template (matches the design doc exactly).
_PROMPT_TEMPLATE = """\
You are working on a GitHub issue in the repository at the current directory.

Issue #{number}: {title}

{body}

Labels: {labels}

Please implement a fix or feature that satisfies this issue. Keep changes \
minimal and focused. Do not modify unrelated files.\
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    """Outcome of running the kiro-cli agent on a single issue."""

    success: bool
    output: str              # combined stdout + stderr, truncated to 10k chars
    duration_seconds: float
    timed_out: bool = False  # True when the agent was killed for exceeding timeout


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(issue: Issue) -> str:
    """Build the kiro-cli chat prompt for *issue*.

    Parameters
    ----------
    issue:
        The GitHub issue the agent should work on.

    Returns
    -------
    str
        A plain-text prompt string ready to pass to kiro-cli as a positional
        argument.
    """
    labels_str = ", ".join(issue.labels) if issue.labels else "(none)"
    return _PROMPT_TEMPLATE.format(
        number=issue.number,
        title=issue.title,
        body=issue.body or "(no body)",
        labels=labels_str,
    )


# ---------------------------------------------------------------------------
# Agent invocation
# ---------------------------------------------------------------------------


def run(
    issue: Issue,
    max_minutes: int,
    *,
    agent_command: list[str] | None = None,
    repo_root: Path | None = None,
) -> AgentResult:
    """Invoke the kiro-cli agent for *issue*.

    The prompt is appended as the final positional argument to *agent_command*
    so kiro-cli receives it directly rather than via stdin.

    Parameters
    ----------
    issue:
        The issue to work on.
    max_minutes:
        Hard time limit in minutes.  The agent process is killed after this
        many minutes regardless of its state.
    agent_command:
        Command list to invoke (without the prompt).  Defaults to
        ``DEFAULT_AGENT_COMMAND``.  Typically sourced from
        ``config.agent_command``.
    repo_root:
        Working directory for the subprocess.  Defaults to ``Path.cwd()``.
        Pass the repo root explicitly to avoid depending on the process cwd.

    Returns
    -------
    AgentResult
        Always returns (never raises).  Check ``AgentResult.success`` and
        ``AgentResult.timed_out`` to determine what happened.
    """
    if agent_command is None:
        agent_command = DEFAULT_AGENT_COMMAND
    if repo_root is None:
        repo_root = Path.cwd()

    prompt = build_prompt(issue)
    timeout_seconds = max_minutes * 60
    # Append prompt as final positional argument — kiro-cli chat [OPTIONS] [INPUT]
    cmd = list(agent_command) + [prompt]

    logger.info(
        "Spawning agent for issue #%d (timeout=%ds, cwd=%s): %s",
        issue.number,
        timeout_seconds,
        repo_root,
        " ".join(cmd[:4]),  # log command prefix only, not the full prompt
    )

    start = time.monotonic()
    timed_out = False
    success = False

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=repo_root,
        )
        duration = time.monotonic() - start
        raw_output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
        output = raw_output[:_MAX_OUTPUT_CHARS]
        success = proc.returncode == 0

        if not success:
            logger.warning(
                "Agent exited with code %d for issue #%d",
                proc.returncode,
                issue.number,
            )

    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        timed_out = True
        success = False
        # Drain whatever partial output the process left before it was killed
        raw_output = ""
        if exc.stdout:
            raw_output += exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", errors="replace")
        if exc.stderr:
            raw_output += "\n" + (exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace"))
        output = raw_output[:_MAX_OUTPUT_CHARS]
        logger.warning(
            "Agent timed out after %ds for issue #%d",
            timeout_seconds,
            issue.number,
        )

    return AgentResult(
        success=success,
        output=output,
        duration_seconds=round(duration, 2),
        timed_out=timed_out,
    )
