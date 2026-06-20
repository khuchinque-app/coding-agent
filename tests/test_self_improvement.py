"""Tests for the self-improvement module (ImprovementProposalManager, NudgeEngine)."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from local_cli.self_improvement import (
    ImprovementError,
    ImprovementProposalManager,
    ImprovementProposalNotFoundError,
    ImprovementProposalInvalidStatusError,
    InvalidTargetError,
    NudgeEngine,
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
def mgr(temp_agents_dir: str) -> ImprovementProposalManager:
    return ImprovementProposalManager(agents_dir=temp_agents_dir)


# ---------------------------------------------------------------------------
# Propose tests
# ---------------------------------------------------------------------------


class TestPropose:
    def test_propose_creates_pending(self, mgr: ImprovementProposalManager) -> None:
        proposal = mgr.propose("Be more concise in responses", target="SOUL.md")
        assert proposal["content"] == "Be more concise in responses"
        assert proposal["target"] == "SOUL.md"
        assert proposal["status"] == "pending"
        assert proposal["id"].startswith("imp-")
        assert proposal["proposed_by"] == "agent"
        assert "timestamp" in proposal

    def test_propose_creates_proposals_file(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("Add Python convention", target="GENERAL.md")
        proposals_path = Path(mgr._proposals_path)
        assert proposals_path.exists()
        data = json.loads(proposals_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["content"] == "Add Python convention"

    def test_propose_empty_content(self, mgr: ImprovementProposalManager) -> None:
        with pytest.raises(ImprovementError, match="must not be empty"):
            mgr.propose("", target="SOUL.md")

    def test_propose_invalid_target(self, mgr: ImprovementProposalManager) -> None:
        with pytest.raises(InvalidTargetError, match="Invalid target"):
            mgr.propose("Content", target="README.md")

    def test_propose_increments_ids(self, mgr: ImprovementProposalManager) -> None:
        p1 = mgr.propose("First", target="SOUL.md")
        p2 = mgr.propose("Second", target="GENERAL.md")
        assert p1["id"] == "imp-001"
        assert p2["id"] == "imp-002"

    def test_propose_with_description(self, mgr: ImprovementProposalManager) -> None:
        proposal = mgr.propose(
            "Use concise style",
            target="SOUL.md",
            description="Prefer concise responses",
        )
        assert proposal["description"] == "Prefer concise responses"


# ---------------------------------------------------------------------------
# Approve tests
# ---------------------------------------------------------------------------


class TestApprove:
    def test_approve_appends_to_target(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("Be concise and direct", target="SOUL.md")
        approved = mgr.approve("imp-001")
        assert approved["status"] == "approved"

        # Check the target file was updated.
        soul_path = Path(mgr._agents_dir, "SOUL.md")
        assert soul_path.exists()
        content = soul_path.read_text(encoding="utf-8")
        assert "Be concise and direct" in content
        assert "Self-Improvement" in content

    def test_approve_creates_file_if_missing(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("Prefer type hints", target="GENERAL.md")
        mgr.approve("imp-001")
        general_path = Path(mgr._agents_dir, "GENERAL.md")
        assert general_path.exists()
        content = general_path.read_text(encoding="utf-8")
        assert "Prefer type hints" in content
        assert "# GENERAL" in content

    def test_approve_nonexistent(self, mgr: ImprovementProposalManager) -> None:
        with pytest.raises(ImprovementProposalNotFoundError):
            mgr.approve("imp-999")

    def test_approve_already_approved(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("Content", target="SOUL.md")
        mgr.approve("imp-001")
        with pytest.raises(ImprovementProposalInvalidStatusError, match="pending"):
            mgr.approve("imp-001")

    def test_approve_rejected(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("Content", target="SOUL.md")
        mgr.reject("imp-001")
        with pytest.raises(ImprovementProposalInvalidStatusError, match="pending"):
            mgr.approve("imp-001")


# ---------------------------------------------------------------------------
# Reject tests
# ---------------------------------------------------------------------------


class TestReject:
    def test_reject_pending(self, mgr: ImprovementProposalManager) -> None:
        proposal = mgr.propose("Content", target="SOUL.md")
        rejected = mgr.reject(proposal["id"])
        assert rejected["status"] == "rejected"

    def test_reject_does_not_apply(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("Content", target="SOUL.md")
        mgr.reject("imp-001")
        soul_path = Path(mgr._agents_dir, "SOUL.md")
        assert not soul_path.exists()

    def test_reject_nonexistent(self, mgr: ImprovementProposalManager) -> None:
        with pytest.raises(ImprovementProposalNotFoundError):
            mgr.reject("imp-999")


# ---------------------------------------------------------------------------
# List / Get / Clear tests
# ---------------------------------------------------------------------------


class TestList:
    def test_list_empty(self, mgr: ImprovementProposalManager) -> None:
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_list_pending_only(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("First", target="SOUL.md")
        mgr.propose("Second", target="GENERAL.md")
        assert len(mgr.list_pending()) == 2

    def test_list_excludes_approved(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("Approved one", target="SOUL.md")
        mgr.propose("Pending one", target="GENERAL.md")
        mgr.approve("imp-001")
        pending = mgr.list_pending()
        assert len(pending) == 1
        assert pending[0]["id"] == "imp-002"

    def test_list_all(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("First", target="SOUL.md")
        mgr.propose("Second", target="GENERAL.md")
        assert len(mgr.list_all()) == 2


class TestGet:
    def test_get_existing(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("Content", target="SOUL.md")
        proposal = mgr.get_proposal("imp-001")
        assert proposal["id"] == "imp-001"

    def test_get_nonexistent(self, mgr: ImprovementProposalManager) -> None:
        with pytest.raises(ImprovementProposalNotFoundError):
            mgr.get_proposal("imp-999")


class TestClear:
    def test_clear_all(self, mgr: ImprovementProposalManager) -> None:
        mgr.propose("First", target="SOUL.md")
        mgr.propose("Second", target="GENERAL.md")
        count = mgr.clear_all()
        assert count == 2
        assert mgr.list_all() == []

    def test_clear_all_empty(self, mgr: ImprovementProposalManager) -> None:
        count = mgr.clear_all()
        assert count == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_corrupt_proposals_file(self, temp_agents_dir: str) -> None:
        proposals_path = Path(temp_agents_dir, "improvement-proposals.json")
        proposals_path.write_text("not valid json", encoding="utf-8")
        mgr = ImprovementProposalManager(agents_dir=temp_agents_dir)
        assert mgr.list_pending() == []

    def test_approve_to_all_valid_targets(self, mgr: ImprovementProposalManager) -> None:
        for target in ["SOUL.md", "GENERAL.md", "USER.md", "MEMORY.md"]:
            mgr.propose(f"Improvement for {target}", target=target)
        for i in range(1, 5):
            pid = f"imp-{str(i).zfill(3)}"
            mgr.approve(pid)
        assert len(mgr.list_pending()) == 0


# ---------------------------------------------------------------------------
# NudgeEngine tests
# ---------------------------------------------------------------------------


class TestNudgeEngine:
    def test_no_nudges_when_all_ok(self, temp_agents_dir: str) -> None:
        """No nudges when MEMORY.md exists and USER.md is populated."""
        agents_dir = Path(temp_agents_dir)
        # Create MEMORY.md (non-default content)
        (agents_dir / "MEMORY.md").write_text("# MEMORY\n- Custom entries here\n", encoding="utf-8")
        # Create USER.md with non-default content
        (agents_dir / "USER.md").write_text("# USER\n- Name: Test\n", encoding="utf-8")

        engine = NudgeEngine(agents_dir=str(agents_dir))
        nudges = engine.get_nudges()
        # There should be no MEMORY.md missing nudge since it exists
        # There should be no USER.md default nudge since content doesn't contain the marker
        assert len(nudges) == 0

    def test_nudge_missing_memory(self, temp_agents_dir: str) -> None:
        """Nudge when MEMORY.md is missing."""
        engine = NudgeEngine(agents_dir=temp_agents_dir)
        nudges = engine.get_nudges()
        memory_nudges = [n for n in nudges if "MEMORY.md" in n and "not found" in n]
        assert len(memory_nudges) == 1

    def test_nudge_pending_memory_proposals(self, temp_agents_dir: str) -> None:
        """Nudge when there are pending memory proposals."""
        from local_cli.memory_proposals import MemoryProposalManager
        mmgr = MemoryProposalManager(agents_dir=temp_agents_dir)
        mmgr.propose("Test memory")
        engine = NudgeEngine(
            agents_dir=temp_agents_dir,
            memory_proposal_manager=mmgr,
        )
        nudges = engine.get_nudges()
        memory_nudges = [n for n in nudges if "memory" in n.lower() and "proposal" in n.lower()]
        assert len(memory_nudges) == 1

    def test_nudge_pending_skill_proposals(self, temp_agents_dir: str) -> None:
        """Nudge when there are pending skill proposals."""
        from local_cli.skill_proposals import SkillProposalManager
        smgr = SkillProposalManager(agents_dir=temp_agents_dir)
        smgr.propose("Test skill")
        engine = NudgeEngine(
            agents_dir=temp_agents_dir,
            skill_proposal_manager=smgr,
        )
        nudges = engine.get_nudges()
        skill_nudges = [n for n in nudges if "skill" in n.lower() and "proposal" in n.lower()]
        assert len(skill_nudges) == 1

    def test_nudge_pending_improvement_proposals(self, temp_agents_dir: str) -> None:
        """Nudge when there are pending improvement proposals."""
        imgr = ImprovementProposalManager(agents_dir=temp_agents_dir)
        imgr.propose("Be concise", target="SOUL.md")
        engine = NudgeEngine(
            agents_dir=temp_agents_dir,
            improvement_proposal_manager=imgr,
        )
        nudges = engine.get_nudges()
        improve_nudges = [n for n in nudges if "improvement" in n.lower()]
        assert len(improve_nudges) == 1

    def test_nudge_default_user(self, temp_agents_dir: str) -> None:
        """Nudge when USER.md has default content."""
        agents_dir = Path(temp_agents_dir)
        (agents_dir / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
        (agents_dir / "USER.md").write_text(
            "# USER Profile\n\n## About Me\n\n- **Name:**",
            encoding="utf-8",
        )
        engine = NudgeEngine(agents_dir=str(agents_dir))
        nudges = engine.get_nudges()
        user_nudges = [n for n in nudges if "USER.md" in n and "default" in n.lower()]
        assert len(user_nudges) == 1
