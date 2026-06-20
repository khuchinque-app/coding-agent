"""Identity files for local-cli.

Provides :class:`IdentityLoader` for discovering, loading, and managing identity
files that shape the agent's personality, context, and user awareness — inspired
by Nous Research's Hermes Agent.

Identity files are stored in a configurable ``.agents`` directory at the project
root and follow an uppercase naming convention:

    .agents/
    ├── SOUL.md         # Agent personality, tone, guardrails
    ├── USER.md         # User profile & preferences (per-project override)
    ├── MEMORY.md       # Agent-curated notes (project conventions, workarounds)
    ├── GENERAL.md      # Context/instructions (shared project rules)
    └── skills/         # Skills directory (already exists)

USER.md has a hierarchical loading model: a global file at
``~/.config/local-cli/USER.md`` is loaded first, then a per-project override at
``.agents/USER.md`` is merged on top (per-project values win on conflict).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default filenames within the agents directory.
_SOUL_FILE = "SOUL.md"
_USER_FILE = "USER.md"
_MEMORY_FILE = "MEMORY.md"
_GENERAL_FILE = "GENERAL.md"

# Project root filename.
_AGENTS_FILE = "AGENTS.md"

# Global USER.md path (relative to state_dir).
_GLOBAL_USER_RELATIVE = "USER.md"

# Set of all known identity filenames (used for discovery / status).
_IDENTITY_FILES = frozenset({_SOUL_FILE, _USER_FILE, _MEMORY_FILE, _GENERAL_FILE})


# ---------------------------------------------------------------------------
# Identity data container
# ---------------------------------------------------------------------------


class IdentityContent:
    """Container for all loaded identity file contents.

    Each attribute is the raw text content of the corresponding file, or
    ``None`` if the file does not exist.

    Attributes:
        soul: Content of SOUL.md (agent personality), or ``None``.
        user_global: Content of global USER.md (``~/.config/local-cli/USER.md``),
            or ``None``.
        user_local: Content of per-project USER.md (``.agents/USER.md``),
            or ``None``.
        user_merged: Merged content of user_global + user_local.  ``None`` if
            neither file exists.
        memory: Content of MEMORY.md (agent-curated notes), or ``None``.
        general: Content of GENERAL.md (context/instructions), or ``None``.
        agents: Content of AGENTS.md at the project root, or ``None``.
    """

    __slots__ = (
        "soul",
        "user_global",
        "user_local",
        "user_merged",
        "memory",
        "general",
        "agents",
    )

    def __init__(
        self,
        soul: str | None = None,
        user_global: str | None = None,
        user_local: str | None = None,
        user_merged: str | None = None,
        memory: str | None = None,
        general: str | None = None,
        agents: str | None = None,
    ) -> None:
        self.soul = soul
        self.user_global = user_global
        self.user_local = user_local
        self.user_merged = user_merged
        self.memory = memory
        self.general = general
        self.agents = agents

    def has_any(self) -> bool:
        """Return ``True`` if at least one identity file was loaded."""
        return any(
            v is not None
            for v in (self.soul, self.user_merged, self.memory, self.general, self.agents)
        )

    def loaded_files(self) -> list[str]:
        """Return a list of filenames that were successfully loaded."""
        files: list[str] = []
        if self.soul is not None:
            files.append("SOUL.md")
        if self.user_global is not None:
            files.append("USER.md (global)")
        if self.user_local is not None:
            files.append("USER.md (local)")
        if self.memory is not None:
            files.append("MEMORY.md")
        if self.general is not None:
            files.append("GENERAL.md")
        if self.agents is not None:
            files.append("AGENTS.md")
        return files


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class IdentityError(Exception):
    """Base exception for identity operations."""


# ---------------------------------------------------------------------------
# Default templates (shipped inline to keep zero dependencies)
# ---------------------------------------------------------------------------

_DEFAULT_SOUL = """\
# SOUL

You are a helpful, precise coding agent. You value clarity and correctness over speed.

## Core Directives

- Think step by step before taking action
- Use tools (read, write, bash, glob, grep, etc.) to verify your assumptions
- Never guess file contents — always read them first
- Be concise in your responses; let tool output speak for itself
- When you make a mistake, acknowledge it and correct it

## Communication Style

- Professional and direct
- Explain what you did and why, not just what
- Ask clarifying questions when requirements are ambiguous
"""

_DEFAULT_USER = """\
# USER Profile

## About Me

- **Name:**
- **Role:** (e.g., Full-stack developer, ML engineer, Hobbyist)
- **Preferred languages:** Python, TypeScript, Go, etc.
- **Preferred frameworks:** (e.g., React, FastAPI, Flask, Next.js)

## Preferences

- **Communication style:** Concise / Detailed / Balanced
- **Testing preference:** I prefer tests to be written alongside code
- **Error handling:** Prefer explicit error handling over silent failures
- **Code style:** (e.g., type hints required, Google-style docstrings)

## Environment

- **Preferred shell:** bash / zsh
- **OS:** Linux / macOS / Windows
- **Editor:** VSCode / Vim / JetBrains

## Notes

(Any other information you want the agent to know about you)
"""

_DEFAULT_GENERAL = """\
# GENERAL Instructions

## Workflow

- Always run typechecks or linters after making code changes
- Prefer existing utility functions over reimplementing
- When installing packages, prefer the project's existing package manager

## Safety

- Never commit directly to main/master without a PR
- Always test changes before declaring a task complete
- When in doubt about a destructive operation, ask the user first
"""

_DEFAULT_MEMORY = """\
# MEMORY

## Project Conventions

- (Agent notes conventions here as they are discovered)

## Build & Configuration

- (Agent notes build workarounds, config quirks)

## Common Issues

- (Agent documents recurring problems and solutions)

## Completed Milestones

- (Agent notes significant completed work)
"""


# ---------------------------------------------------------------------------
# IdentityLoader
# ---------------------------------------------------------------------------


class IdentityLoader:
    """Discovers, loads, and manages identity files for the agent.

    Identity files are stored in a configurable ``agents_dir`` (default
    ``.agents``) at the project root, with the exception of the global
    USER.md which lives in ``state_dir`` (e.g.
    ``~/.local/state/local-cli/USER.md``).

    The loader is **not** restricted to the project root for the agents
    directory per se, but it resolves paths relative to the current working
    directory at construction time.  If the directory does not exist, loading
    methods gracefully return ``None`` rather than raising.

    Args:
        agents_dir: Directory for identity files (``.agents/`` relative to
            the current working directory).  Defaults to ``".agents"``.
        state_dir: Base directory for application state (e.g.
            ``~/.local/state/local-cli``).  Used to locate the global USER.md.
            If ``None``, global USER.md is not loaded.
        auto_init: If ``True`` and the agents directory does not exist,
            create it with default template files on first call to
            :meth:`load_all`.  Defaults to ``False``.
    """

    def __init__(
        self,
        agents_dir: str = ".agents",
        state_dir: str | None = None,
        auto_init: bool = False,
    ) -> None:
        self._agents_dir = Path(agents_dir)
        self._state_dir: Path | None = Path(state_dir).expanduser() if state_dir else None
        self._auto_init = auto_init
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Public API: load individual files
    # ------------------------------------------------------------------

    def _maybe_init(self) -> None:
        """Run auto-init once if ``auto_init`` was set at construction time.

        Called by every public loader method so that auto-init works
        regardless of which method is called first.
        """
        if self._auto_init and not self._initialized:
            self._ensure_agents_dir()
            self._initialized = True

    @staticmethod
    def _merge_user_content(
        user_global: str | None,
        user_local: str | None,
    ) -> str | None:
        """Merge global and local USER.md content into a single string.

        When both exist, they are combined with labelled sections showing
        the origin of each.  When only one exists, it is returned as-is.

        Args:
            user_global: Content of the global USER.md file, or ``None``.
            user_local: Content of the per-project USER.md file, or ``None``.

        Returns:
            The merged content string, or ``None`` if neither file exists.
        """
        if user_global is not None and user_local is not None:
            return (
                f"--- Global Profile ---\n{user_global}\n\n"
                f"--- Project Override ---\n{user_local}"
            )
        if user_global is not None:
            return user_global
        if user_local is not None:
            return user_local
        return None

    def load_all(self, *, init_if_missing: bool | None = None) -> IdentityContent:
        """Load all identity files and return their contents.

        This is the primary entry point.  If ``auto_init`` was set at
        construction time (or ``init_if_missing`` is ``True``), the agents
        directory is created with default templates on the first call.

        Args:
            init_if_missing: Override the constructor's ``auto_init`` setting
                for this call.

        Returns:
            An :class:`IdentityContent` instance with all loaded contents.
        """
        should_init = init_if_missing if init_if_missing is not None else self._auto_init

        if should_init and not self._initialized:
            self._ensure_agents_dir()
            self._initialized = True

        soul = self._load_file(_SOUL_FILE)
        user_global = self._load_global_user()
        user_local = self._load_file(_USER_FILE)
        memory = self._load_file(_MEMORY_FILE)
        general = self._load_file(_GENERAL_FILE)
        agents = self._load_agents_file()

        return IdentityContent(
            soul=soul,
            user_global=user_global,
            user_local=user_local,
            user_merged=self._merge_user_content(user_global, user_local),
            memory=memory,
            general=general,
            agents=agents,
        )

    def load_soul(self) -> str | None:
        """Load and return the content of SOUL.md, or ``None``."""
        self._maybe_init()
        return self._load_file(_SOUL_FILE)

    def load_user(self) -> tuple[str | None, str | None, str | None]:
        """Load USER.md content.

        Returns:
            A tuple of ``(global_content, local_content, merged_content)``.
            Each element is ``None`` if the corresponding file does not exist.
        """
        self._maybe_init()
        user_global = self._load_global_user()
        user_local = self._load_file(_USER_FILE)
        return (
            user_global,
            user_local,
            self._merge_user_content(user_global, user_local),
        )

    def load_general(self) -> str | None:
        """Load and return the content of GENERAL.md, or ``None``."""
        self._maybe_init()
        return self._load_file(_GENERAL_FILE)

    def load_memory(self) -> str | None:
        """Load and return the content of MEMORY.md, or ``None``."""
        self._maybe_init()
        return self._load_file(_MEMORY_FILE)

    def load_agents(self) -> str | None:
        """Load and return the content of AGENTS.md at the project root, or ``None``."""
        self._maybe_init()
        return self._load_agents_file()

    # ------------------------------------------------------------------
    # Public API: status / discovery
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, bool]:
        """Return a dictionary mapping filename to whether it exists.

        Includes both global and local USER.md (as ``USER.md (global)`` and
        ``USER.md (local)`` keys).

        Returns:
            A dict like ``{"SOUL.md": True, "USER.md": False, ...}``.
        """
        status: dict[str, bool] = {}
        for fname in _IDENTITY_FILES:
            if fname == _USER_FILE:
                continue  # Handle separately below.
            status[fname] = (self._agents_dir / fname).is_file()

        status["USER.md (global)"] = (
            self._global_user_path().is_file() if self._state_dir else False
        )
        status["USER.md (local)"] = (self._agents_dir / _USER_FILE).is_file()
        status["AGENTS.md"] = Path(_AGENTS_FILE).is_file()

        return status

    @property
    def agents_dir(self) -> str:
        """Return the agents directory path as a string."""
        return str(self._agents_dir)

    # ------------------------------------------------------------------
    # Initialization: create agents directory with default templates
    # ------------------------------------------------------------------

    def ensure_agents_dir(self) -> list[str]:
        """Create the agents directory with default template files.

        Only creates files that do not already exist.  The global USER.md
        is created in ``state_dir``, not in the agents directory.

        Returns:
            A list of filenames that were created.
        """
        self._initialized = True
        return self._ensure_agents_dir()

    def _ensure_agents_dir(self) -> list[str]:
        """Internal implementation of agents directory initialization."""
        created: list[str] = []

        # Create the agents directory.
        try:
            self._agents_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return created

        # Create default templates for missing files.
        templates: list[tuple[str, str]] = [
            (_SOUL_FILE, _DEFAULT_SOUL),
            (_GENERAL_FILE, _DEFAULT_GENERAL),
            (_MEMORY_FILE, _DEFAULT_MEMORY),
            (_USER_FILE, _DEFAULT_USER),
        ]

        for fname, content in templates:
            path = self._agents_dir / fname
            if not path.exists():
                try:
                    path.write_text(content, encoding="utf-8")
                    created.append(fname)
                except OSError:
                    pass

        # Create global USER.md if state_dir is available.
        if self._state_dir is not None:
            global_path = self._global_user_path()
            if not global_path.exists():
                try:
                    global_path.parent.mkdir(parents=True, exist_ok=True)
                    global_path.write_text(_DEFAULT_USER, encoding="utf-8")
                    created.append(f"~/{global_path.relative_to(Path.home())}")
                except (OSError, ValueError):
                    pass

        return created

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_file(self, filename: str) -> str | None:
        """Load the content of an identity file from the agents directory.

        Args:
            filename: The file to load (e.g. ``"SOUL.md"``).

        Returns:
            The file content as a string, or ``None`` if the file cannot
            be read (not found, permission error, etc.).
        """
        path = self._agents_dir / filename
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _load_global_user(self) -> str | None:
        """Load the global USER.md from ``state_dir``.

        Returns:
            The file content, or ``None`` if unavailable.
        """
        if self._state_dir is None:
            return None
        path = self._global_user_path()
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _global_user_path(self) -> Path:
        """Return the path to the global USER.md file."""
        assert self._state_dir is not None
        return self._state_dir / _GLOBAL_USER_RELATIVE

    def _load_agents_file(self) -> str | None:
        """Load AGENTS.md from the project root (current working directory).

        Returns:
            The file content, or ``None`` if not found.
        """
        path = Path(_AGENTS_FILE)
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None
