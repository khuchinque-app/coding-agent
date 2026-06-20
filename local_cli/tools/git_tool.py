"""Git tool for local-cli.

Provides safe git operations — clone, add, push, commit, status, log,
diff, pull, fetch — with built-in security guards against destructive
operations (force push, hard reset, etc.) that require explicit
confirmation.
"""

import os
import subprocess
from pathlib import Path
from typing import Callable

from local_cli.security import get_sanitized_env
from local_cli.tools.base import Tool

# Maximum output size in bytes (100 KB).
_MAX_OUTPUT_BYTES = 100 * 1024

# Default command timeout in seconds.
_DEFAULT_TIMEOUT = 120

# Git operations that are considered destructive and require confirmation.
_DESTRUCTIVE_OPS: frozenset[str] = frozenset({
    "push --force", "push -f", "push --force-with-lease",
    "reset --hard", "clean -f", "clean -fd", "branch -D",
    "rebase", "cherry-pick",
})


class GitTool(Tool):
    """Execute git operations with safety guards."""

    def __init__(
        self,
        confirm: Callable[[str], bool] | None = None,
    ) -> None:
        """Create the git tool.

        Args:
            confirm: Optional callback invoked before running a destructive
                git operation (force push, hard reset, etc.). Receives the
                full git command string and returns ``True`` to proceed.
        """
        self._confirm = confirm

    @property
    def cacheable(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return (
            "Run a git operation: clone, add, commit, push, pull, fetch, "
            "status, log, diff, branch, checkout, stash, tag, remote, "
            "or any other git command. Destructive operations like "
            "force push or hard reset require user confirmation. "
            "Use this instead of 'bash' for all git commands."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": (
                        "Git operation to perform. Examples: "
                        "'clone https://github.com/user/repo.git', "
                        "'add .', 'add file.py', 'commit -m \"msg\"', "
                        "'push origin main', 'pull origin main', "
                        "'status', 'log --oneline -5', 'diff', "
                        "'fetch origin', 'checkout -b feature', "
                        "'stash', 'branch', 'tag v1.0', "
                        "'remote -v', 'rev-parse HEAD'"
                    ),
                },
                "repo_path": {
                    "type": "string",
                    "description": (
                        "Optional path to the git repository. "
                        "Defaults to the current working directory. "
                        "Required for clone (specify where to clone into)."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Maximum execution time in seconds. "
                        f"Defaults to {_DEFAULT_TIMEOUT}."
                    ),
                },
            },
            "required": ["operation"],
        }

    def _is_destructive(self, operation: str) -> bool:
        """Check if a git operation is destructive (requires confirmation)."""
        op_lower = operation.lower()
        for destructive in _DESTRUCTIVE_OPS:
            if destructive in op_lower:
                return True
        return False

    def execute(self, **kwargs: object) -> str:
        """Execute a git operation and return the output.

        Args:
            **kwargs: Must include ``operation`` (str).  May include
                ``repo_path`` (str) and ``timeout`` (int).

        Returns:
            The combined stdout and stderr of the command, or an error
            message if the command was blocked or failed.
        """
        operation = kwargs.get("operation")
        if not isinstance(operation, str) or not operation.strip():
            return "Error: 'operation' parameter is required and must be a non-empty string."

        timeout = kwargs.get("timeout", _DEFAULT_TIMEOUT)
        if not isinstance(timeout, (int, float)):
            timeout = _DEFAULT_TIMEOUT
        timeout = int(timeout)

        repo_path = kwargs.get("repo_path")
        if repo_path is not None and not isinstance(repo_path, str):
            repo_path = None

        # Build the full git command.
        command = f"git {operation.strip()}"

        # Check for destructive operations and require confirmation.
        if self._is_destructive(operation):
            if self._confirm is None:
                return (
                    f"Error: '{command}' is a destructive git operation and "
                    "cannot be run without explicit user confirmation. "
                    "Use the bash tool if you are certain."
                )
            if not self._confirm(command):
                return f"Operation declined by user (not run): {command}"

        # Determine working directory.
        cwd: str | None = None
        if repo_path:
            cwd = repo_path

        try:
            result = subprocess.run(
                [command],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=get_sanitized_env(),
                cwd=cwd,
                shell=True,
            )
        except subprocess.TimeoutExpired:
            return f"Error: git operation timed out after {timeout} seconds."
        except PermissionError as exc:
            return f"Error: permission denied: {exc}"
        except OSError as exc:
            return f"Error: failed to execute git operation: {exc}"

        # Combine stdout and stderr.
        output = result.stdout
        if result.stderr:
            output = output + result.stderr if output else result.stderr

        # Truncate if output exceeds the maximum size.
        if len(output.encode("utf-8", errors="replace")) > _MAX_OUTPUT_BYTES:
            truncated = output.encode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES]
            output = truncated.decode("utf-8", errors="replace")
            output += "\n... [output truncated at 100KB]"

        return output
