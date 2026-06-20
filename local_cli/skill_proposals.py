"""Skill proposal system for local-cli.

Provides :class:`SkillProposalManager` for managing pending skill proposals
and creating skill files from approved drafts.  Proposals are stored as JSON
in ``.agents/skill-proposals.json`` and approved proposals are written as
``SKILL.md`` files to ``.agents/skills/<name>/SKILL.md``.

Workflow:
    1. User or agent proposes a skill via ``/skills propose <content>``.
    2. User runs ``/skills list-proposals`` — reviews pending proposals.
    3. User runs ``/skills approve <id>`` — creates the skill file.
    4. User runs ``/skills reject <id>`` — marks the proposal as rejected.
    5. User runs ``/skills delete <name>`` — removes an existing skill.
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
_PROPOSAL_PREFIX = "skp-"
_PROPOSAL_PAD_WIDTH = 3

# Valid proposal statuses.
_VALID_STATUSES = frozenset({"pending", "approved", "rejected"})

# Expected skill filename within each skill subdirectory.
_SKILL_FILE = "SKILL.md"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SkillProposalError(Exception):
    """Base exception for skill proposal operations."""


class SkillProposalNotFoundError(SkillProposalError):
    """Raised when a referenced proposal does not exist."""


class SkillProposalInvalidStatusError(SkillProposalError):
    """Raised when a proposal cannot transition to the requested status."""


class SkillFileError(SkillProposalError):
    """Raised when a skill file operation fails."""


# ---------------------------------------------------------------------------
# SkillProposalManager
# ---------------------------------------------------------------------------


class SkillProposalManager:
    """Manages pending skill proposals and creates skills from approved ones.

    Proposals are stored as a JSON array in ``skill-proposals.json``
    within the agents directory.  Each proposal has a unique ID, name,
    trigger keywords, description, content (full SKILL.md body), proposer
    label, timestamp, and status (``pending``, ``approved``, or
    ``rejected``).

    When a proposal is approved, a ``SKILL.md`` file is created at
    ``.agents/skills/<name>/SKILL.md`` with the proper YAML-like frontmatter,
    and the skill loader is notified to refresh.

    Args:
        agents_dir: Path to the ``.agents`` directory.  Defaults to
            ``".agents"``.
        skills_dir: Path to the skills subdirectory within agents_dir.
            Defaults to ``"skills"`` (i.e. ``.agents/skills/``).
    """

    _PROPOSALS_FILE = "skill-proposals.json"

    def __init__(
        self,
        agents_dir: str = ".agents",
        skills_subdir: str = "skills",
    ) -> None:
        self._agents_dir = Path(agents_dir)
        self._skills_dir = self._agents_dir / skills_subdir
        self._proposals_path = self._agents_dir / self._PROPOSALS_FILE
        self._post_approve_callback = None

    # ------------------------------------------------------------------
    # Public API — proposals
    # ------------------------------------------------------------------

    def propose(
        self,
        content: str,
        name: str | None = None,
        triggers: list[str] | None = None,
        description: str | None = None,
    ) -> dict:
        """Create a new pending skill proposal.

        Args:
            content: The skill body content (markdown, goes below frontmatter).
            name: Suggested skill name.  Auto-generated from ID if not
                provided.
            triggers: List of trigger keywords for matching.
            description: Brief description of what the skill does.

        Returns:
            The created proposal dict with keys ``id``, ``name``,
            ``triggers``, ``description``, ``content``, ``proposed_by``,
            ``timestamp``, and ``status``.

        Raises:
            SkillProposalError: If the content is empty.
        """
        if not content or not content.strip():
            raise SkillProposalError("Skill proposal content must not be empty.")

        proposals = self._load_proposals()
        proposal_id = self._next_id(proposals)
        gen_name = name or f"skill-{proposal_id}"

        proposal: dict = {
            "id": proposal_id,
            "name": gen_name.strip(),
            "triggers": triggers or [],
            "description": (description or "").strip(),
            "content": content.strip(),
            "proposed_by": "user",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "pending",
        }
        proposals.append(proposal)
        self._save_proposals(proposals)
        return proposal

    def approve(self, proposal_id: str) -> dict:
        """Approve a pending proposal and create the skill file.

        Args:
            proposal_id: The proposal identifier (e.g. ``"skp-001"``).

        Returns:
            The updated proposal dict with status ``"approved"``.

        Raises:
            SkillProposalNotFoundError: If the proposal does not exist.
            SkillProposalInvalidStatusError: If the proposal is not pending.
            SkillFileError: If the skill file cannot be written.
        """
        proposals = self._load_proposals()
        proposal = self._find_proposal(proposals, proposal_id)

        if proposal["status"] != "pending":
            raise SkillProposalInvalidStatusError(
                f"Cannot approve proposal '{proposal_id}' "
                f"with status '{proposal['status']}'. "
                f"Only pending proposals can be approved."
            )

        # Create the skill file from the proposal.
        self._create_skill_file(proposal)

        proposal["status"] = "approved"
        self._save_proposals(proposals)

        # Notify callback (e.g. to refresh SkillsLoader).
        if self._post_approve_callback is not None:
            self._post_approve_callback()

        return proposal

    def reject(self, proposal_id: str) -> dict:
        """Reject a pending proposal without creating a skill file.

        Args:
            proposal_id: The proposal identifier (e.g. ``"skp-001"``).

        Returns:
            The updated proposal dict with status ``"rejected"``.

        Raises:
            SkillProposalNotFoundError: If the proposal does not exist.
            SkillProposalInvalidStatusError: If the proposal is not pending.
        """
        proposals = self._load_proposals()
        proposal = self._find_proposal(proposals, proposal_id)

        if proposal["status"] != "pending":
            raise SkillProposalInvalidStatusError(
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
            SkillProposalNotFoundError: If the proposal does not exist.
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
    # Public API — existing skill management
    # ------------------------------------------------------------------

    def delete_skill(self, name: str) -> str:
        """Delete an existing skill directory and all its contents.

        Args:
            name: The skill name (subdirectory name under skills_dir).

        Returns:
            A status message.

        Raises:
            SkillFileError: If the skill does not exist or cannot be deleted.
        """
        skill_path = self._skills_dir / name
        if not skill_path.is_dir():
            raise SkillFileError(f"Skill '{name}' not found at {skill_path}.")

        try:
            import shutil
            shutil.rmtree(skill_path)
        except OSError as exc:
            raise SkillFileError(f"Failed to delete skill '{name}': {exc}")

        return f"Skill '{name}' deleted."

    def list_existing_skills(self) -> list[str]:
        """Return a list of existing skill names (subdirectories containing SKILL.md).

        Returns:
            A sorted list of skill names.
        """
        if not self._skills_dir.is_dir():
            return []
        skills: list[str] = []
        try:
            for entry in sorted(self._skills_dir.iterdir()):
                if entry.is_dir() and (entry / _SKILL_FILE).is_file():
                    skills.append(entry.name)
        except OSError:
            pass
        return skills

    # ------------------------------------------------------------------
    # Callback for post-approve notification
    # ------------------------------------------------------------------

    def set_post_approve_callback(self, callback) -> None:
        """Set a callback to be called after a skill is approved.

        The callback receives no arguments.  This is used to refresh the
        SkillsLoader after a new skill is created.

        Args:
            callback: A zero-argument callable.
        """
        self._post_approve_callback = callback

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
            SkillProposalError: If the file cannot be written.
        """
        try:
            self._agents_dir.mkdir(parents=True, exist_ok=True)
            content = json.dumps(proposals, ensure_ascii=False, indent=2) + "\n"
            atomic_write_text(self._proposals_path, content)
        except OSError as exc:
            raise SkillProposalError(f"Failed to save proposals: {exc}")

    def _next_id(self, proposals: list[dict]) -> str:
        """Generate the next sequential proposal ID.

        Args:
            proposals: Current list of proposal dicts.

        Returns:
            A proposal ID string (e.g. ``"skp-001"``).
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
            SkillProposalNotFoundError: If no proposal with the given ID exists.
        """
        for p in proposals:
            if p.get("id") == proposal_id:
                return p
        raise SkillProposalNotFoundError(
            f"Skill proposal '{proposal_id}' not found."
        )

    def _create_skill_file(self, proposal: dict) -> None:
        """Create a SKILL.md file from an approved proposal.

        The file is written to ``.agents/skills/<name>/SKILL.md`` with
        proper YAML-like frontmatter.

        Args:
            proposal: The approved proposal dict.

        Raises:
            SkillFileError: If the file cannot be written.
        """
        skill_name = proposal.get("name", "").strip()
        if not skill_name:
            skill_name = f"skill-{proposal['id']}"

        triggers_raw = proposal.get("triggers", [])
        description = proposal.get("description", "")
        body = proposal.get("content", "")

        # Build frontmatter — use bracket format matching existing SkillsLoader parser.
        triggers_str = f"[{', '.join(triggers_raw)}]" if triggers_raw else "[]"
        frontmatter_lines = ["---"]
        frontmatter_lines.append(f"name: {skill_name}")
        frontmatter_lines.append(f"triggers: {triggers_str}")
        if description:
            frontmatter_lines.append(f"description: {description}")
        frontmatter_lines.append("---")
        frontmatter = "\n".join(frontmatter_lines)

        # Combine frontmatter + body.
        skill_content = f"{frontmatter}\n\n{body}\n"

        # Write the file.
        skill_dir = self._skills_dir / skill_name
        skill_file = skill_dir / _SKILL_FILE
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(skill_content, encoding="utf-8")
        except OSError as exc:
            raise SkillFileError(
                f"Failed to create skill file '{skill_file}': {exc}"
            )
