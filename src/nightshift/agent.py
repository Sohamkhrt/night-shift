"""agent.py — spawn and supervise a kiro-cli chat session.

Builds the prompt string from an Issue object and invokes
``kiro-cli chat --no-interactive``.  The process runs with a hard timeout
(``max_minutes`` from config).  All output is captured and stored in
``AgentResult``.

Design decisions:
- The prompt is plain text (not Jinja2) to keep the dependency footprint small
  and the template easy to read in the source.
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

from nightshift.github import Issue

logger = logging.getLogger(__name__)

# Maximum characters captured from kiro-cli output stored in the run log.
_MAX_OUTPUT_CHARS = 10_000

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
        A plain-text prompt string ready to pass to kiro-cli via stdin or a
        ``--message`` argument.
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


def run(issue: Issue, max_minutes: int) -> AgentResult:
    """Invoke ``kiro-cli chat --no-interactive`` for *issue*.

    The process receives the prompt on stdin and is killed if it exceeds
    *max_minutes*.

    Parameters
    ----------
    issue:
        The issue to work on.
    max_minutes:
        Hard time limit in minutes.  The agent process is killed after this
        many minutes regardless of its state.

    Returns
    -------
    AgentResult
        Always returns (never raises).  Check ``AgentResult.success`` and
        ``AgentResult.timed_out`` to determine what happened.
    """
    prompt = build_prompt(issue)
    timeout_seconds = max_minutes * 60
    cmd = ["kiro-cli", "chat", "--no-interactive"]

    logger.info(
        "Spawning agent for issue #%d (timeout=%ds): %s",
        issue.number,
        timeout_seconds,
        " ".join(cmd),
    )

    start = time.monotonic()
    timed_out = False
    success = False

    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
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
