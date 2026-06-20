"""Tests for the identity module (IdentityLoader)."""

import os
import tempfile
from pathlib import Path

import pytest

from local_cli.identity import IdentityContent, IdentityLoader


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
def temp_state_dir() -> str:
    """Create a temporary state directory for testing global USER.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = os.path.join(tmpdir, "state")
        os.makedirs(state_dir, exist_ok=True)
        yield state_dir


# ---------------------------------------------------------------------------
# IdentityContent tests
# ---------------------------------------------------------------------------


class TestIdentityContent:
    def test_empty_content(self) -> None:
        content = IdentityContent()
        assert not content.has_any()
        assert content.loaded_files() == []

    def test_single_field(self) -> None:
        content = IdentityContent(soul="# Soul content")
        assert content.has_any()
        assert content.loaded_files() == ["SOUL.md"]
        assert content.soul == "# Soul content"

    def test_all_fields(self) -> None:
        content = IdentityContent(
            soul="# Soul",
            user_global="# Global User",
            user_local="# Local User",
            user_merged="# Merged User",
            memory="# Memory",
            general="# General",
            agents="# Agents",
        )
        assert content.has_any()
        loaded = content.loaded_files()
        assert "SOUL.md" in loaded
        assert "USER.md (global)" in loaded
        assert "USER.md (local)" in loaded
        assert "MEMORY.md" in loaded
        assert "GENERAL.md" in loaded
        assert "AGENTS.md" in loaded


# ---------------------------------------------------------------------------
# IdentityLoader tests
# ---------------------------------------------------------------------------


class TestIdentityLoader:
    def test_init_defaults(self) -> None:
        loader = IdentityLoader()
        assert loader.agents_dir == ".agents"

    def test_init_custom(self) -> None:
        loader = IdentityLoader(agents_dir="/tmp/test-agents", state_dir="/tmp/test-state")
        assert loader.agents_dir == "/tmp/test-agents"

    def test_load_all_empty(self, temp_agents_dir: str) -> None:
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        content = loader.load_all()
        assert not content.has_any()
        assert content.soul is None
        assert content.general is None
        assert content.user_merged is None
        assert content.memory is None
        assert content.agents is None

    def test_load_soul(self, temp_agents_dir: str) -> None:
        soul_content = "# SOUL\n\nBe helpful."
        Path(temp_agents_dir, "SOUL.md").write_text(soul_content, encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        assert loader.load_soul() == soul_content

    def test_load_soul_missing(self, temp_agents_dir: str) -> None:
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        assert loader.load_soul() is None

    def test_load_general(self, temp_agents_dir: str) -> None:
        general_content = "# GENERAL\n\nUse type hints."
        Path(temp_agents_dir, "GENERAL.md").write_text(general_content, encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        assert loader.load_general() == general_content

    def test_load_memory(self, temp_agents_dir: str) -> None:
        memory_content = "# MEMORY\n\nConvention: use black."
        Path(temp_agents_dir, "MEMORY.md").write_text(memory_content, encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        assert loader.load_memory() == memory_content

    def test_load_agents(self, temp_agents_dir: str) -> None:
        """AGENTS.md is loaded from the project root (CWD), not the agents dir."""
        agents_content = "# AGENTS\n\nProject: my-app"
        agents_path = Path(temp_agents_dir).parent / "AGENTS.md"
        agents_path.write_text(agents_content, encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        # Change CWD to the temp dir so AGENTS.md is found.
        original_cwd = os.getcwd()
        try:
            os.chdir(str(agents_path.parent))
            assert loader.load_agents() == agents_content
        finally:
            os.chdir(original_cwd)

    def test_load_agents_missing(self, temp_agents_dir: str) -> None:
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        assert loader.load_agents() is None

    # ------------------------------------------------------------------
    # USER.md hierarchical loading
    # ------------------------------------------------------------------

    def test_load_user_both_global_and_local(self, temp_agents_dir: str, temp_state_dir: str) -> None:
        global_content = "# Global User\n\nName: Alice"
        local_content = "# Local User\n\nRole: Developer"
        Path(temp_state_dir, "USER.md").write_text(global_content, encoding="utf-8")
        Path(temp_agents_dir, "USER.md").write_text(local_content, encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir=temp_state_dir)
        user_global, user_local, user_merged = loader.load_user()
        assert user_global == global_content
        assert user_local == local_content
        assert user_merged is not None
        assert "Global Profile" in user_merged
        assert global_content in user_merged
        assert "Project Override" in user_merged
        assert local_content in user_merged

    def test_load_user_global_only(self, temp_agents_dir: str, temp_state_dir: str) -> None:
        global_content = "# Global User\n\nName: Alice"
        Path(temp_state_dir, "USER.md").write_text(global_content, encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir=temp_state_dir)
        user_global, user_local, user_merged = loader.load_user()
        assert user_global == global_content
        assert user_local is None
        assert user_merged == global_content

    def test_load_user_local_only(self, temp_agents_dir: str, temp_state_dir: str) -> None:
        local_content = "# Local User\n\nRole: Developer"
        Path(temp_agents_dir, "USER.md").write_text(local_content, encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir=temp_state_dir)
        user_global, user_local, user_merged = loader.load_user()
        assert user_global is None
        assert user_local == local_content
        assert user_merged == local_content

    def test_load_user_neither(self, temp_agents_dir: str, temp_state_dir: str) -> None:
        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir=temp_state_dir)
        user_global, user_local, user_merged = loader.load_user()
        assert user_global is None
        assert user_local is None
        assert user_merged is None

    def test_load_user_no_state_dir(self, temp_agents_dir: str) -> None:
        """When state_dir is None, global USER.md is not loaded."""
        local_content = "# Local User\n\nRole: Developer"
        Path(temp_agents_dir, "USER.md").write_text(local_content, encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir=None)
        user_global, user_local, user_merged = loader.load_user()
        assert user_global is None
        assert user_local == local_content
        assert user_merged == local_content

    # ------------------------------------------------------------------
    # load_all integration
    # ------------------------------------------------------------------

    def test_load_all_all_files(self, temp_agents_dir: str, temp_state_dir: str) -> None:
        soul = "# SOUL\n\nBe precise."
        general = "# GENERAL\n\nUse type hints."
        memory = "# MEMORY\n\nConvention: black."
        user_local = "# Local User\n\nRole: Dev"

        for fname, content in [("SOUL.md", soul), ("GENERAL.md", general),
                                ("MEMORY.md", memory), ("USER.md", user_local)]:
            Path(temp_agents_dir, fname).write_text(content, encoding="utf-8")

        # Write global USER.md.
        user_global = "# Global User\n\nName: Alice"
        Path(temp_state_dir, "USER.md").write_text(user_global, encoding="utf-8")

        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir=temp_state_dir)
        content = loader.load_all()

        assert content.soul == soul
        assert content.general == general
        assert content.memory == memory
        assert content.user_global == user_global
        assert content.user_local == user_local
        assert content.user_merged is not None
        assert content.agents is None
        assert content.has_any()

    def test_load_all_empty_dir(self, temp_agents_dir: str) -> None:
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        content = loader.load_all()
        assert not content.has_any()

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------

    def test_get_status_all_missing(self, temp_agents_dir: str) -> None:
        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir="/tmp/nonexistent")
        status = loader.get_status()
        assert not any(status.values())

    def test_get_status_some_present(self, temp_agents_dir: str, temp_state_dir: str) -> None:
        Path(temp_agents_dir, "SOUL.md").write_text("soul", encoding="utf-8")
        Path(temp_agents_dir, "MEMORY.md").write_text("memory", encoding="utf-8")
        Path(temp_state_dir, "USER.md").write_text("user", encoding="utf-8")
        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir=temp_state_dir)
        status = loader.get_status()
        assert status["SOUL.md"] is True
        assert status["GENERAL.md"] is False
        assert status["MEMORY.md"] is True
        assert status["USER.md (global)"] is True
        assert status["USER.md (local)"] is False
        assert status["AGENTS.md"] is False

    # ------------------------------------------------------------------
    # ensure_agents_dir / auto_init
    # ------------------------------------------------------------------

    def test_ensure_agents_dir_creates_all_templates(self, temp_agents_dir: str) -> None:
        # Use a fresh empty directory as the agents dir.
        fresh_dir = Path(temp_agents_dir).parent / "fresh-agents"
        fresh_dir.mkdir(parents=True, exist_ok=True)
        fresh_agents = str(fresh_dir)

        loader = IdentityLoader(agents_dir=fresh_agents)
        created = loader.ensure_agents_dir()

        assert "SOUL.md" in created
        assert "GENERAL.md" in created
        assert "MEMORY.md" in created
        assert "USER.md" in created

        # Verify files were actually created with content.
        assert (fresh_dir / "SOUL.md").exists()
        assert (fresh_dir / "GENERAL.md").exists()
        assert (fresh_dir / "MEMORY.md").exists()
        assert (fresh_dir / "USER.md").exists()

        content = (fresh_dir / "SOUL.md").read_text(encoding="utf-8")
        assert "SOUL" in content

    def test_ensure_agents_dir_skips_existing(self, temp_agents_dir: str) -> None:
        # Pre-create SOUL.md with custom content.
        Path(temp_agents_dir, "SOUL.md").write_text("custom soul", encoding="utf-8")

        loader = IdentityLoader(agents_dir=temp_agents_dir)
        created = loader.ensure_agents_dir()

        # SOUL.md should not be re-created (not in 'created' list).
        assert "SOUL.md" not in created
        # Other template files should be created.
        assert "GENERAL.md" in created

        # SOUL.md content should be untouched.
        content = Path(temp_agents_dir, "SOUL.md").read_text(encoding="utf-8")
        assert content == "custom soul"

    def test_load_all_with_auto_init(self, temp_agents_dir: str) -> None:
        """load_all with auto_init=True creates templates for missing files."""
        fresh_dir = Path(temp_agents_dir).parent / "auto-init-agents"
        fresh_dir.mkdir(parents=True, exist_ok=True)
        fresh_agents = str(fresh_dir)

        loader = IdentityLoader(agents_dir=fresh_agents, auto_init=True)
        content = loader.load_all()

        # After auto_init, files should exist and be loaded.
        assert content.soul is not None
        assert "SOUL" in content.soul
        assert content.general is not None
        assert content.memory is not None

    def test_auto_init_with_state_dir(self, temp_agents_dir: str, temp_state_dir: str) -> None:
        """auto_init also creates global USER.md in state_dir."""
        fresh_dir = Path(temp_agents_dir).parent / "auto-init-state"
        fresh_dir.mkdir(parents=True, exist_ok=True)
        fresh_state = Path(temp_state_dir).parent / "fresh-state"
        fresh_state.mkdir(parents=True, exist_ok=True)

        loader = IdentityLoader(
            agents_dir=str(fresh_dir),
            state_dir=str(fresh_state),
            auto_init=True,
        )
        created = loader.ensure_agents_dir()

        # Check that global USER.md was created.
        global_user = fresh_state / "USER.md"
        assert global_user.exists()
        assert "USER" in global_user.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_load_file_permission_error(self, temp_agents_dir: str) -> None:
        """Gracefully handle unreadable files."""
        soul_path = Path(temp_agents_dir, "SOUL.md")
        soul_path.write_text("soul", encoding="utf-8")
        # Make it unreadable.
        soul_path.chmod(0o000)
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        try:
            assert loader.load_soul() is None
        finally:
            soul_path.chmod(0o644)  # Restore so cleanup works

    def test_load_file_not_a_file(self, temp_agents_dir: str) -> None:
        """Gracefully handle a directory where a file is expected."""
        Path(temp_agents_dir, "SOUL.md").mkdir(parents=True, exist_ok=True)
        loader = IdentityLoader(agents_dir=temp_agents_dir)
        assert loader.load_soul() is None

    def test_init_nonexistent_dir(self) -> None:
        """Non-existent agents directory is handled gracefully."""
        loader = IdentityLoader(agents_dir="/tmp/nonexistent-xyz-123")
        content = loader.load_all()
        assert not content.has_any()
        assert content.soul is None

    def test_get_status_nonexistent_state(self, temp_agents_dir: str) -> None:
        """get_status doesn't crash when state_dir is None."""
        loader = IdentityLoader(agents_dir=temp_agents_dir, state_dir=None)
        status = loader.get_status()
        # USER.md (global) should be False when no state_dir.
        assert status["USER.md (global)"] is False
