"""Tests for the skill proposals module (SkillProposalManager)."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from local_cli.skill_proposals import (
    SkillFileError,
    SkillProposalError,
    SkillProposalManager,
    SkillProposalNotFoundError,
    SkillProposalInvalidStatusError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_agents_dir() -> str:
    """Create a temporary agents directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, ".agents")
        os.makedirs(agents_dir, exist_ok=True)
        yield agents_dir


@pytest.fixture
def mgr(temp_agents_dir: str) -> SkillProposalManager:
    """Create a SkillProposalManager with a temporary agents directory."""
    return SkillProposalManager(agents_dir=temp_agents_dir)


# ---------------------------------------------------------------------------
# Propose tests
# ---------------------------------------------------------------------------


class TestPropose:
    def test_propose_creates_pending(self, mgr: SkillProposalManager) -> None:
        proposal = mgr.propose("Write unit tests for all modules")
        assert proposal["content"] == "Write unit tests for all modules"
        assert proposal["status"] == "pending"
        assert proposal["id"].startswith("skp-")
        assert proposal["proposed_by"] == "user"
        assert "timestamp" in proposal
        assert proposal["name"] == "skill-skp-001"

    def test_propose_creates_proposals_file(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Some skill content")
        proposals_path = Path(mgr._proposals_path)
        assert proposals_path.exists()
        data = json.loads(proposals_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["content"] == "Some skill content"

    def test_propose_strips_content(self, mgr: SkillProposalManager) -> None:
        proposal = mgr.propose("  \n  Spaced content  \n  ")
        assert proposal["content"] == "Spaced content"

    def test_propose_empty_content(self, mgr: SkillProposalManager) -> None:
        with pytest.raises(SkillProposalError, match="must not be empty"):
            mgr.propose("")
        with pytest.raises(SkillProposalError, match="must not be empty"):
            mgr.propose("   \n  \n  ")

    def test_propose_increments_ids(self, mgr: SkillProposalManager) -> None:
        p1 = mgr.propose("First")
        p2 = mgr.propose("Second")
        assert p1["id"] == "skp-001"
        assert p2["id"] == "skp-002"

    def test_propose_with_name_and_triggers(self, mgr: SkillProposalManager) -> None:
        proposal = mgr.propose(
            content="Django setup steps",
            name="setup-django",
            triggers=["django", "setup", "startproject"],
            description="Set up a new Django project",
        )
        assert proposal["name"] == "setup-django"
        assert proposal["triggers"] == ["django", "setup", "startproject"]
        assert proposal["description"] == "Set up a new Django project"


# ---------------------------------------------------------------------------
# Approve tests
# ---------------------------------------------------------------------------


class TestApprove:
    def test_approve_pending_proposal(self, mgr: SkillProposalManager) -> None:
        proposal = mgr.propose(
            content="Steps to set up a Django app",
            name="setup-django",
            triggers=["django"],
        )
        approved = mgr.approve(proposal["id"])
        assert approved["status"] == "approved"

        # Check that the skill file was created.
        skill_dir = Path(mgr._skills_dir, "setup-django")
        skill_file = skill_dir / "SKILL.md"
        assert skill_file.exists()
        content = skill_file.read_text(encoding="utf-8")
        assert "Steps to set up a Django app" in content
        assert "name: setup-django" in content
        assert "triggers: [django]" in content

    def test_approve_creates_skill_file_with_frontmatter(self, mgr: SkillProposalManager) -> None:
        mgr.propose(
            content="Build steps",
            name="build-app",
            triggers=["build", "compile"],
            description="Build the application",
        )
        mgr.approve("skp-001")
        skill_file = Path(mgr._skills_dir, "build-app", "SKILL.md")
        content = skill_file.read_text(encoding="utf-8")
        assert content.startswith("---")
        assert "name: build-app" in content
        assert "triggers: [build, compile]" in content
        assert "description: Build the application" in content
        assert "Build steps" in content

    def test_approve_nonexistent(self, mgr: SkillProposalManager) -> None:
        with pytest.raises(SkillProposalNotFoundError):
            mgr.approve("skp-999")

    def test_approve_already_approved(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Some skill")
        mgr.approve("skp-001")
        with pytest.raises(SkillProposalInvalidStatusError, match="pending"):
            mgr.approve("skp-001")

    def test_approve_rejected_proposal(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Some skill")
        mgr.reject("skp-001")
        with pytest.raises(SkillProposalInvalidStatusError, match="pending"):
            mgr.approve("skp-001")


# ---------------------------------------------------------------------------
# Reject tests
# ---------------------------------------------------------------------------


class TestReject:
    def test_reject_pending(self, mgr: SkillProposalManager) -> None:
        proposal = mgr.propose("Some skill")
        rejected = mgr.reject(proposal["id"])
        assert rejected["status"] == "rejected"

    def test_reject_does_not_create_file(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Some skill")
        mgr.reject("skp-001")
        # No skill file should exist.
        skill_dir = Path(mgr._skills_dir, "skill-skp-001")
        assert not skill_dir.exists()

    def test_reject_nonexistent(self, mgr: SkillProposalManager) -> None:
        with pytest.raises(SkillProposalNotFoundError):
            mgr.reject("skp-999")

    def test_reject_already_rejected(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Some skill")
        mgr.reject("skp-001")
        with pytest.raises(SkillProposalInvalidStatusError, match="pending"):
            mgr.reject("skp-001")


# ---------------------------------------------------------------------------
# List tests
# ---------------------------------------------------------------------------


class TestList:
    def test_list_empty(self, mgr: SkillProposalManager) -> None:
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_list_pending_only(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Pending one")
        mgr.propose("Pending two")
        assert len(mgr.list_pending()) == 2

    def test_list_excludes_approved(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Will be approved")
        mgr.propose("Will stay pending")
        mgr.approve("skp-001")
        pending = mgr.list_pending()
        assert len(pending) == 1
        assert pending[0]["id"] == "skp-002"

    def test_list_excludes_rejected(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Will be rejected")
        mgr.propose("Will stay pending")
        mgr.reject("skp-001")
        pending = mgr.list_pending()
        assert len(pending) == 1
        assert pending[0]["id"] == "skp-002"

    def test_list_all(self, mgr: SkillProposalManager) -> None:
        mgr.propose("First")
        mgr.propose("Second")
        mgr.approve("skp-001")
        mgr.propose("Third")
        all_proposals = mgr.list_all()
        assert len(all_proposals) == 3


# ---------------------------------------------------------------------------
# Get / Review tests
# ---------------------------------------------------------------------------


class TestGetProposal:
    def test_get_existing(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Some skill", name="my-skill")
        proposal = mgr.get_proposal("skp-001")
        assert proposal["id"] == "skp-001"
        assert proposal["name"] == "my-skill"

    def test_get_nonexistent(self, mgr: SkillProposalManager) -> None:
        with pytest.raises(SkillProposalNotFoundError):
            mgr.get_proposal("skp-999")


# ---------------------------------------------------------------------------
# Clear tests
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_all(self, mgr: SkillProposalManager) -> None:
        mgr.propose("First")
        mgr.propose("Second")
        mgr.propose("Third")
        count = mgr.clear_all()
        assert count == 3
        assert mgr.list_all() == []

    def test_clear_all_empty(self, mgr: SkillProposalManager) -> None:
        count = mgr.clear_all()
        assert count == 0

    def test_clear_pending(self, mgr: SkillProposalManager) -> None:
        mgr.propose("First")
        mgr.propose("Second")
        mgr.approve("skp-001")
        count = mgr.clear_pending()
        assert count == 1
        all_proposals = mgr.list_all()
        assert len(all_proposals) == 1
        assert all_proposals[0]["status"] == "approved"

    def test_clear_pending_empty(self, mgr: SkillProposalManager) -> None:
        count = mgr.clear_pending()
        assert count == 0


# ---------------------------------------------------------------------------
# Delete existing skill tests
# ---------------------------------------------------------------------------


class TestDeleteSkill:
    def test_delete_existing_skill(self, mgr: SkillProposalManager) -> None:
        # Create a skill via approve.
        mgr.propose("Content", name="test-skill")
        mgr.approve("skp-001")
        assert Path(mgr._skills_dir, "test-skill").is_dir()

        # Now delete it.
        result = mgr.delete_skill("test-skill")
        assert "deleted" in result
        assert not Path(mgr._skills_dir, "test-skill").exists()

    def test_delete_nonexistent(self, mgr: SkillProposalManager) -> None:
        with pytest.raises(SkillFileError, match="not found"):
            mgr.delete_skill("nonexistent-skill")

    def test_list_existing_skills(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Content A", name="skill-a")
        mgr.propose("Content B", name="skill-b")
        mgr.approve("skp-001")
        mgr.approve("skp-002")
        skills = mgr.list_existing_skills()
        assert "skill-a" in skills
        assert "skill-b" in skills
        assert len(skills) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_corrupt_proposals_file(self, temp_agents_dir: str) -> None:
        """Gracefully handle corrupt JSON."""
        proposals_path = Path(temp_agents_dir, "skill-proposals.json")
        proposals_path.write_text("not valid json", encoding="utf-8")
        mgr = SkillProposalManager(agents_dir=temp_agents_dir)
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_empty_proposals_file(self, temp_agents_dir: str) -> None:
        """Gracefully handle empty JSON array."""
        proposals_path = Path(temp_agents_dir, "skill-proposals.json")
        proposals_path.write_text("[]\n", encoding="utf-8")
        mgr = SkillProposalManager(agents_dir=temp_agents_dir)
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_non_dict_proposals_file(self, temp_agents_dir: str) -> None:
        """Gracefully handle JSON that is not a list."""
        proposals_path = Path(temp_agents_dir, "skill-proposals.json")
        proposals_path.write_text('{"object": "not a list"}', encoding="utf-8")
        mgr = SkillProposalManager(agents_dir=temp_agents_dir)
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_multiple_approve_creates_separate_dirs(self, mgr: SkillProposalManager) -> None:
        mgr.propose("Content A", name="skill-a")
        mgr.propose("Content B", name="skill-b")
        mgr.approve("skp-001")
        mgr.approve("skp-002")
        assert Path(mgr._skills_dir, "skill-a", "SKILL.md").exists()
        assert Path(mgr._skills_dir, "skill-b", "SKILL.md").exists()

    def test_list_existing_skills_empty(self, mgr: SkillProposalManager) -> None:
        assert mgr.list_existing_skills() == []


# ---------------------------------------------------------------------------
# Callback tests
# ---------------------------------------------------------------------------


class TestCallback:
    def test_post_approve_callback_called(self, mgr: SkillProposalManager) -> None:
        callback_called = [False]

        def _callback() -> None:
            callback_called[0] = True

        mgr.set_post_approve_callback(_callback)
        mgr.propose("Content", name="test")
        mgr.approve("skp-001")
        assert callback_called[0] is True

    def test_post_approve_callback_not_called_on_reject(self, mgr: SkillProposalManager) -> None:
        callback_called = [False]

        def _callback() -> None:
            callback_called[0] = True

        mgr.set_post_approve_callback(_callback)
        mgr.propose("Content", name="test")
        mgr.reject("skp-001")
        assert callback_called[0] is False
