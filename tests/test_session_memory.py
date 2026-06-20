"""Tests for local_cli.session_memory module."""

import os
import tempfile
import unittest

from local_cli.session_memory import SessionMemory


class TestSessionMemorySaveLoad(unittest.TestCase):
    """Basic save/load operations."""

    def setUp(self) -> None:
        self.mem = SessionMemory(prefix="test-session-")

    def tearDown(self) -> None:
        self.mem.close()

    def test_save_and_load(self) -> None:
        """Simple save/load round-trip."""
        self.mem.save("name", "hello")
        self.assertEqual(self.mem.load("name"), "hello")

    def test_load_default_when_missing(self) -> None:
        """Loading a missing key returns the default."""
        result = self.mem.load("nonexistent", default=42)
        self.assertEqual(result, 42)

    def test_load_none_default(self) -> None:
        """Loading a missing key returns None by default."""
        self.assertIsNone(self.mem.load("nonexistent"))

    def test_overwrite_key(self) -> None:
        """Overwriting a key replaces the old value."""
        self.mem.save("key", "first")
        self.mem.save("key", "second")
        self.assertEqual(self.mem.load("key"), "second")

    def test_multiple_keys(self) -> None:
        """Multiple keys can be stored independently."""
        self.mem.save("a", 1)
        self.mem.save("b", {"nested": True})
        self.mem.save("c", [1, 2, 3])
        self.assertEqual(self.mem.load("a"), 1)
        self.assertEqual(self.mem.load("b"), {"nested": True})
        self.assertEqual(self.mem.load("c"), [1, 2, 3])

    def test_keys_method(self) -> None:
        """keys() returns all stored keys."""
        self.mem.save("x", 1)
        self.mem.save("y", 2)
        keys = self.mem.keys()
        self.assertIn("x", keys)
        self.assertIn("y", keys)

    def test_clear(self) -> None:
        """clear() removes all stored data."""
        self.mem.save("a", 1)
        self.mem.save("b", 2)
        self.mem.clear()
        self.assertIsNone(self.mem.load("a"))
        self.assertIsNone(self.mem.load("b"))
        self.assertEqual(self.mem.keys(), [])

    def test_empty_keys(self) -> None:
        """keys() returns empty list when no data stored."""
        self.assertEqual(self.mem.keys(), [])


class TestSessionMemoryLifecycle(unittest.TestCase):
    """Session lifecycle: temp dir creation and cleanup."""

    def test_tmp_dir_exists_while_open(self) -> None:
        """The temp directory exists while the session is alive."""
        mem = SessionMemory(prefix="test-lifecycle-")
        self.assertTrue(os.path.isdir(mem.tmp_dir))
        mem.close()
        self.assertFalse(os.path.isdir(mem.tmp_dir))

    def test_close_twice_is_safe(self) -> None:
        """Calling close() multiple times does not error."""
        mem = SessionMemory()
        mem.close()
        mem.close()  # Should be a no-op

    def test_operations_after_close_are_noops(self) -> None:
        """Save/load/keys/clear after close return safe defaults."""
        mem = SessionMemory()
        mem.save("a", 1)
        mem.close()

        # After close, operations should be no-ops.
        mem.save("b", 2)  # Should not crash
        self.assertIsNone(mem.load("a"))  # Cannot read after close
        self.assertEqual(mem.keys(), [])
        mem.clear()  # Should not crash

    def test_tmp_dir_property(self) -> None:
        """tmp_dir returns the temp directory path."""
        mem = SessionMemory(prefix="test-property-")
        self.assertTrue(mem.tmp_dir.startswith(tempfile.gettempdir()))
        self.assertIn("test-property-", mem.tmp_dir)
        mem.close()


class TestSessionMemoryToolHistory(unittest.TestCase):
    """Integration: storing tool-call history entries."""

    def setUp(self) -> None:
        self.mem = SessionMemory(prefix="test-tools-")

    def tearDown(self) -> None:
        self.mem.close()

    def test_save_and_load_tool_history(self) -> None:
        """Tool history can be saved and loaded as a list of dicts."""
        history = [
            {"tool_name": "read", "result_preview": "file contents..."},
            {"tool_name": "write", "result_preview": "wrote 10 bytes"},
        ]
        self.mem.save("tool_history", history)
        loaded = self.mem.load("tool_history", [])
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["tool_name"], "read")
        self.assertEqual(loaded[1]["tool_name"], "write")

    def test_tool_history_append(self) -> None:
        """History can be extended by loading, appending, and saving."""
        self.mem.save("tool_history", [
            {"tool_name": "read", "result_preview": "first"},
        ])
        prior = self.mem.load("tool_history", [])
        prior.append({"tool_name": "write", "result_preview": "second"})
        self.mem.save("tool_history", prior)
        loaded = self.mem.load("tool_history", [])
        self.assertEqual(len(loaded), 2)

    def test_last_tool_count_tracking(self) -> None:
        """_last_tool_count is preserved across save/load cycles."""
        self.mem.save("_last_tool_count", 5)
        self.assertEqual(self.mem.load("_last_tool_count", 0), 5)
        self.mem.save("_last_tool_count", 10)
        self.assertEqual(self.mem.load("_last_tool_count", 0), 10)


if __name__ == "__main__":
    unittest.main()
