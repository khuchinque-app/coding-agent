"""Tests for the memory proposals module (MemoryProposalManager)."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from local_cli.memory_proposals import (
    MemoryError,
    MemoryProposalManager,
    MemoryProposalNotFoundError,
    MemoryProposalInvalidStatusError,
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
def mgr(temp_agents_dir: str) -> MemoryProposalManager:
    """Create a MemoryProposalManager with a temporary agents directory."""
    return MemoryProposalManager(agents_dir=temp_agents_dir)


@pytest.fixture
def mgr_with_existing_memory(temp_agents_dir: str) -> MemoryProposalManager:
    """Create a manager with an existing MEMORY.md file."""
    memory_path = Path(temp_agents_dir, "MEMORY.md")
    memory_path.write_text(
        "# MEMORY\n\n## Project Conventions\n\n- Use type hints\n",
        encoding="utf-8",
    )
    return MemoryProposalManager(agents_dir=temp_agents_dir)


# ---------------------------------------------------------------------------
# Propose tests
# ---------------------------------------------------------------------------


class TestPropose:
    def test_propose_creates_pending(self, mgr: MemoryProposalManager) -> None:
        proposal = mgr.propose("Use type hints everywhere")
        assert proposal["content"] == "Use type hints everywhere"
        assert proposal["status"] == "pending"
        assert proposal["id"].startswith("mem-")
        assert proposal["proposed_by"] == "user"
        assert "timestamp" in proposal

    def test_propose_creates_proposals_file(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("First memory")
        proposals_path = Path(mgr._proposals_path)
        assert proposals_path.exists()
        data = json.loads(proposals_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["content"] == "First memory"

    def test_propose_strips_content(self, mgr: MemoryProposalManager) -> None:
        proposal = mgr.propose("  \n  Spaced content  \n  ")
        assert proposal["content"] == "Spaced content"

    def test_propose_empty_content(self, mgr: MemoryProposalManager) -> None:
        with pytest.raises(MemoryError, match="must not be empty"):
            mgr.propose("")
        with pytest.raises(MemoryError, match="must not be empty"):
            mgr.propose("   \n  \n  ")

    def test_propose_increments_ids(self, mgr: MemoryProposalManager) -> None:
        p1 = mgr.propose("First")
        p2 = mgr.propose("Second")
        assert p1["id"] == "mem-001"
        assert p2["id"] == "mem-002"


# ---------------------------------------------------------------------------
# Approve tests
# ---------------------------------------------------------------------------


class TestApprove:
    def test_approve_pending_proposal(self, mgr_with_existing_memory: MemoryProposalManager) -> None:
        mgr = mgr_with_existing_memory
        proposal = mgr.propose("Always run tests before committing")
        approved = mgr.approve(proposal["id"])
        assert approved["status"] == "approved"

        # Check that MEMORY.md was updated.
        memory = mgr.show_memory()
        assert "Always run tests before committing" in memory

    def test_approve_appends_to_recent_additions(self, mgr_with_existing_memory: MemoryProposalManager) -> None:
        mgr = mgr_with_existing_memory
        mgr.propose("First memory")
        mgr.approve("mem-001")
        memory = mgr.show_memory()
        assert "## Recent Additions" in memory
        assert "First memory" in memory

    def test_approve_creates_memory_if_missing(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Brand new memory")
        mgr.approve("mem-001")
        memory = mgr.show_memory()
        assert "Brand new memory" in memory
        assert "MEMORY" in memory  # Default template header

    def test_approve_nonexistent(self, mgr: MemoryProposalManager) -> None:
        with pytest.raises(MemoryProposalNotFoundError):
            mgr.approve("mem-999")

    def test_approve_already_approved(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Some memory")
        mgr.approve("mem-001")
        with pytest.raises(MemoryProposalInvalidStatusError, match="pending"):
            mgr.approve("mem-001")

    def test_approve_rejected_proposal(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Some memory")
        mgr.reject("mem-001")
        with pytest.raises(MemoryProposalInvalidStatusError, match="pending"):
            mgr.approve("mem-001")


# ---------------------------------------------------------------------------
# Reject tests
# ---------------------------------------------------------------------------


class TestReject:
    def test_reject_pending(self, mgr: MemoryProposalManager) -> None:
        proposal = mgr.propose("Some memory")
        rejected = mgr.reject(proposal["id"])
        assert rejected["status"] == "rejected"

    def test_reject_does_not_append(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Some memory")
        mgr.reject("mem-001")
        memory = mgr.show_memory()
        assert "Some memory" not in memory

    def test_reject_nonexistent(self, mgr: MemoryProposalManager) -> None:
        with pytest.raises(MemoryProposalNotFoundError):
            mgr.reject("mem-999")

    def test_reject_already_rejected(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Some memory")
        mgr.reject("mem-001")
        with pytest.raises(MemoryProposalInvalidStatusError, match="pending"):
            mgr.reject("mem-001")


# ---------------------------------------------------------------------------
# List tests
# ---------------------------------------------------------------------------


class TestList:
    def test_list_empty(self, mgr: MemoryProposalManager) -> None:
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_list_pending_only(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Pending one")
        mgr.propose("Pending two")
        assert len(mgr.list_pending()) == 2

    def test_list_excludes_approved(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Will be approved")
        mgr.propose("Will stay pending")
        mgr.approve("mem-001")
        pending = mgr.list_pending()
        assert len(pending) == 1
        assert pending[0]["id"] == "mem-002"

    def test_list_excludes_rejected(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Will be rejected")
        mgr.propose("Will stay pending")
        mgr.reject("mem-001")
        pending = mgr.list_pending()
        assert len(pending) == 1
        assert pending[0]["id"] == "mem-002"

    def test_list_all(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("First")
        mgr.propose("Second")
        mgr.approve("mem-001")
        mgr.propose("Third")
        all_proposals = mgr.list_all()
        assert len(all_proposals) == 3


# ---------------------------------------------------------------------------
# Get proposal tests
# ---------------------------------------------------------------------------


class TestGetProposal:
    def test_get_existing(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Some memory")
        proposal = mgr.get_proposal("mem-001")
        assert proposal["id"] == "mem-001"
        assert proposal["content"] == "Some memory"

    def test_get_nonexistent(self, mgr: MemoryProposalManager) -> None:
        with pytest.raises(MemoryProposalNotFoundError):
            mgr.get_proposal("mem-999")


# ---------------------------------------------------------------------------
# Clear tests
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_all(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("First")
        mgr.propose("Second")
        mgr.propose("Third")
        count = mgr.clear_all()
        assert count == 3
        assert mgr.list_all() == []
        assert mgr.list_pending() == []

    def test_clear_all_empty(self, mgr: MemoryProposalManager) -> None:
        count = mgr.clear_all()
        assert count == 0

    def test_clear_all_with_mixed_status(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("First")
        mgr.propose("Second")
        mgr.approve("mem-001")
        count = mgr.clear_all()
        assert count == 2
        assert mgr.list_all() == []

    def test_clear_pending(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("First")
        mgr.propose("Second")
        mgr.approve("mem-001")
        count = mgr.clear_pending()
        assert count == 1
        pending = mgr.list_pending()
        assert len(pending) == 0
        # Approved proposal should still exist; only pending was cleared.
        all_proposals = mgr.list_all()
        assert len(all_proposals) == 1
        assert all_proposals[0]["id"] == "mem-001"
        assert all_proposals[0]["status"] == "approved"

    def test_clear_pending_empty(self, mgr: MemoryProposalManager) -> None:
        count = mgr.clear_pending()
        assert count == 0


# ---------------------------------------------------------------------------
# Show / Edit / Size tests
# ---------------------------------------------------------------------------


class TestShowMemory:
    def test_show_memory_empty(self, mgr: MemoryProposalManager) -> None:
        content = mgr.show_memory()
        assert content == ""

    def test_show_memory_content(self, mgr_with_existing_memory: MemoryProposalManager) -> None:
        content = mgr_with_existing_memory.show_memory()
        assert "## Project Conventions" in content
        assert "Use type hints" in content


class TestMemorySize:
    def test_size_no_file(self, mgr: MemoryProposalManager) -> None:
        assert mgr.get_memory_size() == 0

    def test_size_with_content(self, mgr_with_existing_memory: MemoryProposalManager) -> None:
        size = mgr_with_existing_memory.get_memory_size()
        assert size > 0

    def test_is_not_too_large(self, mgr_with_existing_memory: MemoryProposalManager) -> None:
        assert not mgr_with_existing_memory.is_memory_too_large()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_corrupt_proposals_file(self, temp_agents_dir: str) -> None:
        """Gracefully handle corrupt JSON."""
        proposals_path = Path(temp_agents_dir, "memory-proposals.json")
        proposals_path.write_text("not valid json", encoding="utf-8")
        mgr = MemoryProposalManager(agents_dir=temp_agents_dir)
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_empty_proposals_file(self, temp_agents_dir: str) -> None:
        """Gracefully handle empty JSON array."""
        proposals_path = Path(temp_agents_dir, "memory-proposals.json")
        proposals_path.write_text("[]\n", encoding="utf-8")
        mgr = MemoryProposalManager(agents_dir=temp_agents_dir)
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_non_dict_proposals_file(self, temp_agents_dir: str) -> None:
        """Gracefully handle JSON that is not a list."""
        proposals_path = Path(temp_agents_dir, "memory-proposals.json")
        proposals_path.write_text('{"object": "not a list"}', encoding="utf-8")
        mgr = MemoryProposalManager(agents_dir=temp_agents_dir)
        assert mgr.list_pending() == []
        assert mgr.list_all() == []

    def test_multiple_approve_appends_in_order(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("First entry")
        mgr.propose("Second entry")
        mgr.approve("mem-001")
        mgr.approve("mem-002")
        memory = mgr.show_memory()
        pos1 = memory.index("First entry")
        pos2 = memory.index("Second entry")
        assert pos1 < pos2  # First entry appears before second

    def test_reject_then_propose_same_content(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Content")
        mgr.reject("mem-001")
        new_proposal = mgr.propose("Same content again")
        assert new_proposal["id"] == "mem-002"
        assert mgr.list_pending()[0]["id"] == "mem-002"


# ---------------------------------------------------------------------------
# Clear pending detailed test
# ---------------------------------------------------------------------------


class TestClearPendingDetailed:
    def test_clear_pending_keeps_approved(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Will be approved")
        mgr.propose("Will stay pending")
        mgr.approve("mem-001")
        count = mgr.clear_pending()
        assert count == 1  # Only pending proposal removed
        all_proposals = mgr.list_all()
        assert len(all_proposals) == 1
        assert all_proposals[0]["id"] == "mem-001"
        assert all_proposals[0]["status"] == "approved"

    def test_clear_pending_keeps_rejected(self, mgr: MemoryProposalManager) -> None:
        mgr.propose("Will be rejected")
        mgr.propose("Will stay pending")
        mgr.reject("mem-001")
        count = mgr.clear_pending()
        assert count == 1
        all_proposals = mgr.list_all()
        assert len(all_proposals) == 1
        assert all_proposals[0]["status"] == "rejected"
