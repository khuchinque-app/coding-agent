"""Self-improvement system for local-cli.

Provides startup nudges and identity improvement proposals — the agent's
ability to learn from user feedback and propose updates to its own
identity files (SOUL.md, GENERAL.md, USER.md).

Startup Nudges (spec §7.3)
---------------------------
On startup the agent checks and suggests:
- Is MEMORY.md missing? → Suggest creating it
- Is USER.md empty/default? → Suggest filling it in
- Are there pending memory proposals? → Remind user to review
- Are there pending skill proposals? → Remind user to review

Improvement Proposals (spec §7.1)
---------------------------------
When the agent discovers user feedback that could improve its identity
files, it creates a pending proposal.  The user reviews and
approves/rejects via slash commands.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from local_cli.tools._fileio import atomic_write_text


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Proposal ID prefix and counter padding.
_PROPOSAL_PREFIX = "imp-"
_PROPOSAL_PAD_WIDTH = 3

# Valid proposal statuses.
_VALID_STATUSES = frozenset({"pending", "approved", "rejected"})

# Valid target identity files for improvement proposals.
_VALID_TARGETS = frozenset({"SOUL.md", "GENERAL.md", "USER.md", "MEMORY.md"})

# Default USER.md content (used to detect whether user has filled it in).
_DEFAULT_USER_MARKER = "- **Name:**"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ImprovementError(Exception):
    """Base exception for improvement operations."""


class ImprovementProposalNotFoundError(ImprovementError):
    """Raised when a referenced proposal does not exist."""


class ImprovementProposalInvalidStatusError(ImprovementError):
    """Raised when a proposal cannot transition to the requested status."""


class InvalidTargetError(ImprovementError):
    """Raised when an invalid target file is specified."""


# ---------------------------------------------------------------------------
# ImprovementProposalManager
# ---------------------------------------------------------------------------


class ImprovementProposalManager:
    """Manages pending improvement proposals for identity files.

    Proposals are stored as a JSON array in ``improvement-proposals.json``
    within the agents directory.  Each proposal has a unique ID, target
    file (e.g. ``"SOUL.md"``), content (the new/modified text to add),
    a description, proposer label, timestamp, and status.

    When a proposal is approved, the content is appended to the target
    file within the agents directory.

    Args:
        agents_dir: Path to the ``.agents`` directory.  Defaults to
            ``".agents"``.
    """

    _PROPOSALS_FILE = "improvement-proposals.json"

    def __init__(self, agents_dir: str = ".agents") -> None:
        self._agents_dir = Path(agents_dir)
        self._proposals_path = self._agents_dir / self._PROPOSALS_FILE

    # ------------------------------------------------------------------
    # Public API — proposals
    # ------------------------------------------------------------------

    def propose(
        self,
        content: str,
        target: str = "SOUL.md",
        description: str | None = None,
    ) -> dict:
        """Create a new pending improvement proposal.

        Args:
            content: The content to add or change in the target file.
            target: The identity file to improve (``"SOUL.md"``,
                ``"GENERAL.md"``, ``"USER.md"``, or ``"MEMORY.md"``).
            description: Human-readable summary of what this improvement
                does.

        Returns:
            The created proposal dict with keys ``id``, ``target``,
            ``content``, ``description``, ``proposed_by``, ``timestamp``,
            and ``status``.

        Raises:
            ImprovementError: If content is empty.
            InvalidTargetError: If target is not a valid identity file.
        """
        if not content or not content.strip():
            raise ImprovementError("Improvement proposal content must not be empty.")

        if target not in _VALID_TARGETS:
            raise InvalidTargetError(
                f"Invalid target '{target}'. Valid targets: {', '.join(sorted(_VALID_TARGETS))}"
            )

        proposals = self._load_proposals()
        proposal_id = self._next_id(proposals)

        proposal: dict = {
            "id": proposal_id,
            "target": target,
            "content": content.strip(),
            "description": (description or f"Proposed update to {target}").strip(),
            "proposed_by": "agent",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "pending",
        }
        proposals.append(proposal)
        self._save_proposals(proposals)
        return proposal

    def approve(self, proposal_id: str) -> dict:
        """Approve a pending proposal and apply it to the target file.

        The content is appended to the target file with a section header
        and timestamp.

        Args:
            proposal_id: The proposal identifier (e.g. ``"imp-001"``).

        Returns:
            The updated proposal dict with status ``"approved"``.

        Raises:
            ImprovementProposalNotFoundError: If the proposal does not exist.
            ImprovementProposalInvalidStatusError: If the proposal is not
                pending.
            ImprovementError: If the target file cannot be updated.
        """
        proposals = self._load_proposals()
        proposal = self._find_proposal(proposals, proposal_id)

        if proposal["status"] != "pending":
            raise ImprovementProposalInvalidStatusError(
                f"Cannot approve proposal '{proposal_id}' "
                f"with status '{proposal['status']}'. "
                f"Only pending proposals can be approved."
            )

        # Apply the improvement to the target file.
        self._apply_to_file(proposal)

        proposal["status"] = "approved"
        self._save_proposals(proposals)
        return proposal

    def reject(self, proposal_id: str) -> dict:
        """Reject a pending proposal without applying it.

        Args:
            proposal_id: The proposal identifier (e.g. ``"imp-001"``).

        Returns:
            The updated proposal dict with status ``"rejected"``.

        Raises:
            ImprovementProposalNotFoundError: If the proposal does not exist.
            ImprovementProposalInvalidStatusError: If the proposal is not
                pending.
        """
        proposals = self._load_proposals()
        proposal = self._find_proposal(proposals, proposal_id)

        if proposal["status"] != "pending":
            raise ImprovementProposalInvalidStatusError(
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
            ImprovementProposalNotFoundError: If the proposal does not exist.
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_to_file(self, proposal: dict) -> None:
        """Apply a proposal's content to its target identity file.

        Appends the content with a labelled section and timestamp.

        Args:
            proposal: The proposal dict (must have ``target`` and
                ``content`` keys).

        Raises:
            ImprovementError: If the file cannot be written.
        """
        target = proposal.get("target", "SOUL.md")
        content = proposal.get("content", "")
        description = proposal.get("description", "Improvement")

        target_path = self._agents_dir / target
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        entry = (
            f"\n\n## Self-Improvement: {description}\n"
            f"*Added on {now}*\n\n"
            f"{content}\n"
        )

        try:
            self._agents_dir.mkdir(parents=True, exist_ok=True)

            if target_path.is_file():
                existing = target_path.read_text(encoding="utf-8")
                new_content = existing + entry
            else:
                new_content = f"# {target.replace('.md', '')}\n{entry}"

            atomic_write_text(target_path, new_content)
        except OSError as exc:
            raise ImprovementError(
                f"Failed to apply improvement to {target}: {exc}"
            )

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
            ImprovementError: If the file cannot be written.
        """
        try:
            self._agents_dir.mkdir(parents=True, exist_ok=True)
            content = json.dumps(proposals, ensure_ascii=False, indent=2) + "\n"
            atomic_write_text(self._proposals_path, content)
        except OSError as exc:
            raise ImprovementError(f"Failed to save proposals: {exc}")

    def _next_id(self, proposals: list[dict]) -> str:
        """Generate the next sequential proposal ID.

        Args:
            proposals: Current list of proposal dicts.

        Returns:
            A proposal ID string (e.g. ``"imp-001"``).
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
            ImprovementProposalNotFoundError: If no proposal with the given
                ID exists.
        """
        for p in proposals:
            if p.get("id") == proposal_id:
                return p
        raise ImprovementProposalNotFoundError(
            f"Improvement proposal '{proposal_id}' not found."
        )


# ---------------------------------------------------------------------------
# NudgeEngine — Startup nudges
# ---------------------------------------------------------------------------


class NudgeEngine:
    """Generates startup nudges based on the current state of identity files.

    Checks for:
    - Missing MEMORY.md → suggest creating it
    - USER.md with default content → suggest filling it in
    - Pending memory proposals → remind user to review
    - Pending skill proposals → remind user to review
    - Pending improvement proposals → remind user to review
    """

    def __init__(
        self,
        memory_proposal_manager: object | None = None,
        skill_proposal_manager: object | None = None,
        improvement_proposal_manager: ImprovementProposalManager | None = None,
        agents_dir: str = ".agents",
    ) -> None:
        self._memory_proposal_manager = memory_proposal_manager
        self._skill_proposal_manager = skill_proposal_manager
        self._improvement_proposal_manager = improvement_proposal_manager
        self._agents_dir = Path(agents_dir)

    def get_nudges(self) -> list[str]:
        """Return a list of nudge messages (strings), empty if none.

        Returns:
            A list of human-readable nudge strings suitable for printing,
            each formatted as a single-line, actionable suggestion.
        """
        nudges: list[str] = []

        # 1. Check for missing MEMORY.md.
        memory_path = self._agents_dir / "MEMORY.md"
        if not memory_path.is_file():
            nudges.append(
                "MEMORY.md not found — create one with /memory propose "
                "to enable persistent agent memory across sessions."
            )

        # 2. Check for default USER.md (still has placeholder name field).
        user_path = self._agents_dir / "USER.md"
        if user_path.is_file():
            try:
                user_content = user_path.read_text(encoding="utf-8")
                if _DEFAULT_USER_MARKER in user_content:
                    nudges.append(
                        "USER.md still contains default template content. "
                        "Personalize it so the agent can better understand "
                        "your preferences."
                    )
            except OSError:
                pass

        # 3. Check for pending memory proposals.
        if self._memory_proposal_manager is not None:
            try:
                pending_memory = self._memory_proposal_manager.list_pending()
                if pending_memory:
                    count = len(pending_memory)
                    label = "proposal" if count == 1 else "proposals"
                    nudges.append(
                        f"You have {count} pending memory {label} — "
                        f"run /memory list to review and approve."
                    )
            except Exception:
                pass

        # 4. Check for pending skill proposals.
        if self._skill_proposal_manager is not None:
            try:
                pending_skills = self._skill_proposal_manager.list_pending()
                if pending_skills:
                    count = len(pending_skills)
                    label = "proposal" if count == 1 else "proposals"
                    nudges.append(
                        f"You have {count} pending skill {label} — "
                        f"run /skills list-proposals to review and approve."
                    )
            except Exception:
                pass

        # 5. Check for pending improvement proposals.
        if self._improvement_proposal_manager is not None:
            try:
                pending_improvements = self._improvement_proposal_manager.list_pending()
                if pending_improvements:
                    count = len(pending_improvements)
                    label = "proposal" if count == 1 else "proposals"
                    nudges.append(
                        f"You have {count} pending improvement {label} — "
                        f"run /improve list to review and approve."
                    )
            except Exception:
                pass

        return nudges
