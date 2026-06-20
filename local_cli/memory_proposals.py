"""Memory proposal system for local-cli.

Provides :class:`MemoryProposalManager` for managing pending memory proposals
and updating the MEMORY.md file.  Proposals are stored as JSON in
``.agents/memory-proposals.json`` and approved proposals are appended to
``.agents/MEMORY.md``.

Workflow:
    1. Agent discovers something worth remembering.
    2. User runs ``/memory propose <content>`` — creates a pending proposal.
    3. User runs ``/memory list`` — reviews pending proposals.
    4. User runs ``/memory approve <id>`` — proposal is appended to MEMORY.md.
    5. User runs ``/memory reject <id>`` — proposal is marked as rejected.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from local_cli.tools._fileio import atomic_write_text


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Proposal ID prefix and counter padding.
_PROPOSAL_PREFIX = "mem-"
_PROPOSAL_PAD_WIDTH = 3

# Valid proposal statuses.
_VALID_STATUSES = frozenset({"pending", "approved", "rejected"})

# Maximum MEMORY.md size in bytes before warning (256 KB).
_MAX_MEMORY_SIZE = 256 * 1024


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MemoryError(Exception):
    """Base exception for memory operations."""


class MemoryProposalNotFoundError(MemoryError):
    """Raised when a referenced proposal does not exist."""


class MemoryProposalInvalidStatusError(MemoryError):
    """Raised when a proposal cannot transition to the requested status."""


# ---------------------------------------------------------------------------
# MemoryProposalManager
# ---------------------------------------------------------------------------


class MemoryProposalManager:
    """Manages pending memory proposals and the MEMORY.md file.

    Proposals are stored as a JSON array in ``memory-proposals.json``
    within the agents directory.  Each proposal has a unique ID, content,
    proposer label, timestamp, and status (``pending``, ``approved``, or
    ``rejected``).

    When a proposal is approved, its content is appended as a new entry
    to the ``## Recent Additions`` section of MEMORY.md.

    Args:
        agents_dir: Path to the ``.agents`` directory.  Defaults to
            ``".agents"``.
    """

    _PROPOSALS_FILE = "memory-proposals.json"
    _MEMORY_FILE = "MEMORY.md"

    def __init__(self, agents_dir: str = ".agents") -> None:
        self._agents_dir = Path(agents_dir)
        self._proposals_path = self._agents_dir / self._PROPOSALS_FILE
        self._memory_path = self._agents_dir / self._MEMORY_FILE

    # ------------------------------------------------------------------
    # Public API — proposals
    # ------------------------------------------------------------------

    def propose(self, content: str) -> dict:
        """Create a new pending memory proposal.

        Args:
            content: The memory content to propose (markdown text).

        Returns:
            The created proposal dict with keys ``id``, ``content``,
            ``proposed_by``, ``timestamp``, and ``status``.

        Raises:
            MemoryError: If the content is empty or the proposal cannot
                be saved.
        """
        if not content or not content.strip():
            raise MemoryError("Memory proposal content must not be empty.")

        proposals = self._load_proposals()
        proposal_id = self._next_id(proposals)

        proposal: dict = {
            "id": proposal_id,
            "content": content.strip(),
            "proposed_by": "user",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "pending",
        }
        proposals.append(proposal)
        self._save_proposals(proposals)
        return proposal

    def approve(self, proposal_id: str) -> dict:
        """Approve a pending proposal and append it to MEMORY.md.

        Args:
            proposal_id: The proposal identifier (e.g. ``"mem-001"``).

        Returns:
            The updated proposal dict with status ``"approved"``.

        Raises:
            MemoryProposalNotFoundError: If the proposal does not exist.
            MemoryProposalInvalidStatusError: If the proposal is not
                pending.
            MemoryError: If the proposal cannot be appended to MEMORY.md.
        """
        proposals = self._load_proposals()
        proposal = self._find_proposal(proposals, proposal_id)

        if proposal["status"] != "pending":
            raise MemoryProposalInvalidStatusError(
                f"Cannot approve proposal '{proposal_id}' "
                f"with status '{proposal['status']}'. "
                f"Only pending proposals can be approved."
            )

        # Append proposal content to MEMORY.md.
        self._append_to_memory(proposal["content"])

        proposal["status"] = "approved"
        self._save_proposals(proposals)
        return proposal

    def reject(self, proposal_id: str) -> dict:
        """Reject a pending proposal without writing to MEMORY.md.

        Args:
            proposal_id: The proposal identifier (e.g. ``"mem-001"``).

        Returns:
            The updated proposal dict with status ``"rejected"``.

        Raises:
            MemoryProposalNotFoundError: If the proposal does not exist.
            MemoryProposalInvalidStatusError: If the proposal is not
                pending.
        """
        proposals = self._load_proposals()
        proposal = self._find_proposal(proposals, proposal_id)

        if proposal["status"] != "pending":
            raise MemoryProposalInvalidStatusError(
                f"Cannot reject proposal '{proposal_id}' "
                f"with status '{proposal['status']}'. "
                f"Only pending proposals can be rejected."
            )

        proposal["status"] = "rejected"
        self._save_proposals(proposals)
        return proposal

    def list_pending(self) -> list[dict]:
        """Return all pending proposals.

        Returns:
            A list of proposal dicts with status ``"pending"``, sorted
            by creation order (oldest first).
        """
        proposals = self._load_proposals()
        return [p for p in proposals if p.get("status") == "pending"]

    def list_all(self) -> list[dict]:
        """Return all proposals, sorted by creation order.

        Returns:
            A list of all proposal dicts.
        """
        return self._load_proposals()

    def get_proposal(self, proposal_id: str) -> dict:
        """Return a single proposal by ID.

        Args:
            proposal_id: The proposal identifier.

        Returns:
            The proposal dict.

        Raises:
            MemoryProposalNotFoundError: If the proposal does not exist.
        """
        proposals = self._load_proposals()
        return self._find_proposal(proposals, proposal_id)

    def clear_all(self) -> int:
        """Delete all proposals (regardless of status).

        Returns:
            The number of proposals that were deleted.
        """
        proposals = self._load_proposals()
        count = len(proposals)
        if count > 0:
            self._save_proposals([])
        return count

    def clear_pending(self) -> int:
        """Delete only pending proposals.

        Returns:
            The number of pending proposals that were deleted.
        """
        proposals = self._load_proposals()
        pending = [p for p in proposals if p.get("status") == "pending"]
        count = len(pending)
        if count > 0:
            remaining = [p for p in proposals if p.get("status") != "pending"]
            self._save_proposals(remaining)
        return count

    # ------------------------------------------------------------------
    # Public API — MEMORY.md
    # ------------------------------------------------------------------

    def show_memory(self) -> str:
        """Return the current content of MEMORY.md.

        Returns:
            The MEMORY.md content as a string.  Returns an empty string
            if the file does not exist.
        """
        if not self._memory_path.is_file():
            return ""
        try:
            return self._memory_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def edit_memory(self) -> str:
        """Open MEMORY.md in the user's ``$EDITOR`` for manual editing.

        Respects the ``EDITOR`` and ``VISUAL`` environment variables,
        falling back to ``nano``.  The file is created with the default
        template if it does not exist.

        Returns:
            A status message indicating what was done.

        Raises:
            MemoryError: If the editor cannot be launched.
        """
        # Create MEMORY.md with default template if it doesn't exist.
        if not self._memory_path.is_file():
            self._create_default_memory()

        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"

        try:
            subprocess.run(
                [editor, str(self._memory_path)],
                check=True,
            )
        except FileNotFoundError:
            raise MemoryError(
                f"Editor '{editor}' not found. "
                f"Set $EDITOR to your preferred editor or edit "
                f"{self._memory_path} manually."
            )
        except subprocess.CalledProcessError:
            raise MemoryError(f"Editor '{editor}' exited with an error.")

        return f"Opened {self._memory_path} in {editor}."

    def get_memory_size(self) -> int:
        """Return the size of MEMORY.md in bytes.

        Returns:
            File size in bytes, or 0 if the file does not exist.
        """
        if not self._memory_path.is_file():
            return 0
        try:
            return self._memory_path.stat().st_size
        except OSError:
            return 0

    def is_memory_too_large(self) -> bool:
        """Check if MEMORY.md exceeds the recommended size limit.

        Returns:
            ``True`` if MEMORY.md is larger than 256 KB.
        """
        return self.get_memory_size() > _MAX_MEMORY_SIZE

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_proposals(self) -> list[dict]:
        """Load proposals from the JSON file.

        Returns:
            A list of proposal dicts.  Returns an empty list if the
            file does not exist or cannot be parsed.
        """
        if not self._proposals_path.is_file():
            return []

        try:
            text = self._proposals_path.read_text(encoding="utf-8")
            data = json.loads(text)
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_proposals(self, proposals: list[dict]) -> None:
        """Save proposals to the JSON file atomically.

        Args:
            proposals: List of proposal dicts to persist.

        Raises:
            MemoryError: If the file cannot be written.
        """
        try:
            self._agents_dir.mkdir(parents=True, exist_ok=True)
            content = json.dumps(proposals, ensure_ascii=False, indent=2) + "\n"
            atomic_write_text(self._proposals_path, content)
        except OSError as exc:
            raise MemoryError(f"Failed to save proposals: {exc}")

    def _next_id(self, proposals: list[dict]) -> str:
        """Generate the next sequential proposal ID.

        Args:
            proposals: Current list of proposal dicts.

        Returns:
            A proposal ID string (e.g. ``"mem-001"``).
        """
        max_num = 0
        for p in proposals:
            pid = p.get("id", "")
            if pid.startswith(_PROPOSAL_PREFIX):
                try:
                    num = int(pid[len(_PROPOSAL_PREFIX):])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    continue
        next_num = max_num + 1
        return f"{_PROPOSAL_PREFIX}{str(next_num).zfill(_PROPOSAL_PAD_WIDTH)}"

    def _find_proposal(self, proposals: list[dict], proposal_id: str) -> dict:
        """Find a proposal by ID.

        Args:
            proposals: List of proposal dicts.
            proposal_id: The proposal identifier to find.

        Returns:
            The matching proposal dict.

        Raises:
            MemoryProposalNotFoundError: If no proposal with the given
                ID exists.
        """
        for p in proposals:
            if p.get("id") == proposal_id:
                return p
        raise MemoryProposalNotFoundError(
            f"Memory proposal '{proposal_id}' not found."
        )

    def _append_to_memory(self, content: str) -> None:
        """Append content as a new entry to MEMORY.md.

        If MEMORY.md does not exist, it is created with a default
        template before appending.

        Args:
            content: The markdown content to append.

        Raises:
            MemoryError: If the file cannot be written.
        """
        try:
            self._agents_dir.mkdir(parents=True, exist_ok=True)

            if not self._memory_path.is_file():
                self._create_default_memory()

            # Read existing content.
            existing = self._memory_path.read_text(encoding="utf-8")

            # Build the entry to append.
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            entry = f"\n- **{now}:** {content}"

            # Check if there's a "## Recent Additions" section.
            if "## Recent Additions" in existing:
                # Append after the Recent Additions heading.
                new_content = existing + entry
            else:
                # Append at the end with a new section heading.
                new_content = existing + f"\n\n## Recent Additions\n{entry}\n"

            # Write back atomically using the shared helper.
            atomic_write_text(self._memory_path, new_content)

        except OSError as exc:
            raise MemoryError(f"Failed to update MEMORY.md: {exc}")

    def _create_default_memory(self) -> None:
        """Create a default MEMORY.md file with template structure."""
        DEFAULT_MEMORY_TEMPLATE = (
            "# MEMORY\n"
            "\n"
            "## Project Conventions\n"
            "\n"
            "- (Agent notes conventions here as they are discovered)\n"
            "\n"
            "## Build & Configuration\n"
            "\n"
            "- (Agent notes build workarounds, config quirks)\n"
            "\n"
            "## Common Issues\n"
            "\n"
            "- (Agent documents recurring problems and solutions)\n"
            "\n"
            "## Completed Milestones\n"
            "\n"
            "- (Agent notes significant completed work)\n"
        )

        try:
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            self._memory_path.write_text(DEFAULT_MEMORY_TEMPLATE, encoding="utf-8")
        except OSError as exc:
            raise MemoryError(f"Failed to create MEMORY.md: {exc}")
