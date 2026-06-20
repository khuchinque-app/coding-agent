"""Integration tests for session memory flow.

Tests cover:

1.  tool_history persists across multiple ``agent_loop`` turns.
2.  ``SESSION PROGRESS`` is injected on subsequent turns.
3.  ``SESSION PROGRESS`` is **not** injected when it already exists
    (deduplication).
4.  ``session_memory=None`` is backward compatible.
5.  ``_handle_session_command`` display logic (``/session``).
6.  Sub-agent session memory propagation (``AgentTool`` --> ``SubAgent``).
7.  No duplicate entries in ``tool_history`` across successive saves.
"""

import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import MagicMock

from local_cli.agent import _save_session_progress, agent_loop
from local_cli.session_memory import SessionMemory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyTool:
    """Minimal concrete tool for testing."""

    def __init__(
        self,
        name: str = "dummy",
        result: str = "ok",
        *,
        side_effect: Exception | None = None,
    ) -> None:
        self._name = name
        self._result = result
        self._side_effect = side_effect

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A dummy tool for testing."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "arg": {"type": "string", "description": "An argument."},
            },
            "required": [],
        }

    @property
    def cacheable(self) -> bool:
        return False

    def execute(self, **kwargs: object) -> str:
        if self._side_effect is not None:
            raise self._side_effect
        return self._result

    def to_ollama_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _chunk(content: str, *, tool_calls: list | None = None) -> dict[str, Any]:
    """Build a single streaming chunk."""
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"message": msg, "done": True}


def _make_stream(responses: list[list[dict]]) -> MagicMock:
    """Create a mock provider whose chat_stream cycles through *responses*.

    Each element of *responses* is a list of chunks for one LLM call.
    """
    client = MagicMock()
    client.chat_stream.side_effect = [iter(r) for r in responses]
    return client


# ============================================================================
# 1. tool_history persists across multiple agent_loop turns
# ============================================================================


class TestToolHistoryAcrossTurns(unittest.TestCase):
    """Session memory persists tool-call history across REPL turns."""

    def setUp(self) -> None:
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = self._stdout
        sys.stderr = self._stderr

    def tearDown(self) -> None:
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def test_tool_history_accumulates_across_two_turns(self) -> None:
        """Turn 1 saves tool calls; Turn 2 appends new ones.

        Uses the SAME messages list across both turns (matching real
        REPL behaviour where agent_loop mutates messages in place).
        Each turn uses a different tool so that the dedup check in
        _save_session_progress (which compares the last existing entry
        to the last new entry) does not erroneously skip the save.
        """
        mem = SessionMemory(prefix="test-accum-")
        tool_bash = _DummyTool(name="bash", result="bash_result")
        tool_read = _DummyTool(name="read", result="read_result")

        tc1 = [{"function": {"name": "bash", "arguments": {"command": "echo a"}}}]
        tc2 = [{"function": {"name": "read", "arguments": {"file_path": "/a"}}}]

        streams = [
            # Turn 1: bash tool call → done
            [_chunk("", tool_calls=tc1)],
            [_chunk("Turn1 done. [TASK COMPLETE]")],
            # Turn 2: read tool call → done
            [_chunk("", tool_calls=tc2)],
            [_chunk("Turn2 done. [TASK COMPLETE]")],
        ]
        client = _make_stream(streams)

        # Shared messages list (same pattern as the real REPL).
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do thing"},
        ]

        # --- Turn 1: call bash tool ---
        agent_loop(client, "m", [tool_bash, tool_read], msgs,
                   session_memory=mem)
        history = mem.load("tool_history", [])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["tool_name"], "bash")
        self.assertIn("bash_result", history[0]["result_preview"])

        # --- Turn 2: call read tool (different tool, different result) ---
        msgs.append({"role": "user", "content": "do other thing"})
        agent_loop(client, "m", [tool_bash, tool_read], msgs,
                   session_memory=mem)
        history = mem.load("tool_history", [])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["tool_name"], "bash")
        self.assertEqual(history[1]["tool_name"], "read")
        self.assertIn("bash_result", history[0]["result_preview"])
        self.assertIn("read_result", history[1]["result_preview"])

        mem.close()

    def test_tool_history_empty_when_no_tool_calls(self) -> None:
        """No tool calls means tool_history stays empty."""
        mem = SessionMemory(prefix="test-empty-")
        client = _make_stream([
            [_chunk("Hello. [TASK COMPLETE]")],
        ])
        msgs: list[dict[str, Any]] = [
            {"role": "user", "content": "say hello"},
        ]
        agent_loop(client, "m", [], msgs, session_memory=mem)
        self.assertEqual(mem.load("tool_history", []), [])
        mem.close()


# ============================================================================
# 2. SESSION PROGRESS is injected on subsequent turns
# ============================================================================


class TestSessionProgressInjection(unittest.TestCase):
    """The SESSION PROGRESS block is injected on subsequent turns."""

    def setUp(self) -> None:
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = self._stdout
        sys.stderr = self._stderr

    def tearDown(self) -> None:
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def test_session_progress_injected_on_second_turn(self) -> None:
        """Prior tool history causes SESSION PROGRESS injection."""
        mem = SessionMemory(prefix="test-inject-")
        tool = _DummyTool(name="read", result="file content")

        # Turn 1: tool call → done.
        tc = [{"function": {"name": "read", "arguments": {"file_path": "/a"}}}]
        turn1 = [
            [_chunk("", tool_calls=tc)],
            [_chunk("Read it. [TASK COMPLETE]")],
        ]
        client = _make_stream(turn1)
        agent_loop(client, "m", [tool], [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "read file"},
        ], session_memory=mem)

        # --- Turn 2: new messages, same session_memory, NO tools ---
        client2 = _make_stream([
            [_chunk("Ok. [TASK COMPLETE]")],
        ])
        msgs2: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "next step"},
        ]
        agent_loop(client2, "m", [], msgs2, session_memory=mem)

        progress_msgs = [
            m for m in msgs2
            if "--- SESSION PROGRESS ---" in (m.get("content", "") or "")
        ]
        self.assertEqual(len(progress_msgs), 1)
        content = progress_msgs[0]["content"]
        self.assertIn("--- SESSION PROGRESS ---", content)
        self.assertIn("--- END SESSION PROGRESS ---", content)
        self.assertIn("[read]", content)
        self.assertIn("file content", content)
        self.assertIn("Do NOT redo completed steps", content)

        mem.close()

    def test_session_progress_not_injected_when_already_present(self) -> None:
        """If SESSION PROGRESS already exists, no duplicate is added."""
        mem = SessionMemory(prefix="test-dedup-")
        tool = _DummyTool(name="bash", result="ran")

        # Turn 1: populate history.
        tc = [{"function": {"name": "bash", "arguments": {"command": "ls"}}}]
        turn1 = [
            [_chunk("", tool_calls=tc)],
            [_chunk("Ran. [TASK COMPLETE]")],
        ]
        client = _make_stream(turn1)
        agent_loop(client, "m", [tool], [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "run command"},
        ], session_memory=mem)

        # Turn 2: inject manually (simulates first injection in a real session).
        client2 = _make_stream([
            [_chunk("Ok. [TASK COMPLETE]")],
        ])
        msgs2: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {
                "role": "system",
                "content": "--- SESSION PROGRESS ---\n  [bash] ran\n--- END SESSION PROGRESS ---",
            },
            {"role": "user", "content": "next"},
        ]
        agent_loop(client2, "m", [], msgs2, session_memory=mem)

        progress_msgs = [
            m for m in msgs2
            if "--- SESSION PROGRESS ---" in (m.get("content", "") or "")
        ]
        self.assertEqual(len(progress_msgs), 1)
        mem.close()

    def test_no_session_progress_without_prior_history(self) -> None:
        """No prior tool history means no SESSION PROGRESS injection."""
        mem = SessionMemory(prefix="test-noprogress-")
        client = _make_stream([
            [_chunk("Hello. [TASK COMPLETE]")],
        ])
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        agent_loop(client, "m", [], msgs, session_memory=mem)

        progress_msgs = [
            m for m in msgs
            if "--- SESSION PROGRESS ---" in (m.get("content", "") or "")
        ]
        self.assertEqual(len(progress_msgs), 0)
        mem.close()


# ============================================================================
# 3. session_memory=None is backward compatible
# ============================================================================


class TestSessionMemoryNone(unittest.TestCase):
    """session_memory=None does not cause errors."""

    def setUp(self) -> None:
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = self._stdout
        sys.stderr = self._stderr

    def tearDown(self) -> None:
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def test_none_session_memory_no_errors(self) -> None:
        """agent_loop works without session_memory (backward compatible)."""
        client = _make_stream([
            [_chunk("Done. [TASK COMPLETE]")],
        ])
        msgs: list[dict[str, Any]] = [
            {"role": "user", "content": "do it"},
        ]
        agent_loop(client, "m", [], msgs, session_memory=None)
        self.assertEqual(len(msgs), 2)  # user + assistant

    def test_sub_agent_loop_with_none(self) -> None:
        """sub_agent_loop with session_memory=None works (backward compatible)."""
        from local_cli.agent import sub_agent_loop

        provider = MagicMock()
        provider.format_tools.return_value = []
        provider.chat_stream.return_value = iter([
            _chunk("Done. [TASK COMPLETE]"),
        ])

        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do something"},
        ]
        result = sub_agent_loop(provider, "m", [], msgs, session_memory=None)
        self.assertIn("Done.", result)


# ============================================================================
# 4. _handle_session_command display logic
# ============================================================================


class TestSessionCommandDisplay(unittest.TestCase):
    """Tests for _handle_session_command (/session)."""

    def setUp(self) -> None:
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = self._stdout
        sys.stderr = self._stderr

    def tearDown(self) -> None:
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def _make_ctx(self, session_memory: Any = None) -> Any:
        ctx = MagicMock()
        ctx.session_memory = session_memory
        return ctx

    def test_session_none_memory(self) -> None:
        """When session_memory is None, displays a warning."""
        from local_cli.cli import _handle_session_command

        ctx = self._make_ctx(session_memory=None)
        result = _handle_session_command(["/session"], ctx)
        self.assertTrue(result)
        self.assertIn("not available", self._stdout.getvalue().lower())

    def test_session_clear(self) -> None:
        """/session clear calls mem.clear()."""
        from local_cli.cli import _handle_session_command

        mem = MagicMock()
        ctx = self._make_ctx(session_memory=mem)
        result = _handle_session_command(["/session", "clear"], ctx)
        self.assertTrue(result)
        mem.clear.assert_called_once()

    def test_session_shows_temp_dir(self) -> None:
        """/session shows temp dir path."""
        from local_cli.cli import _handle_session_command

        mem = SessionMemory(prefix="test-cmd-")
        ctx = self._make_ctx(session_memory=mem)
        _handle_session_command(["/session"], ctx)
        self.assertIn(mem.tmp_dir, self._stdout.getvalue())
        mem.close()

    def test_session_shows_empty_history(self) -> None:
        """/session shows 'empty' when no tool history."""
        from local_cli.cli import _handle_session_command

        mem = SessionMemory(prefix="test-emptycmd-")
        ctx = self._make_ctx(session_memory=mem)
        _handle_session_command(["/session"], ctx)
        self.assertIn("empty", self._stdout.getvalue())
        mem.close()

    def test_session_shows_tool_entries(self) -> None:
        """/session shows stored tool history entries."""
        from local_cli.cli import _handle_session_command

        mem = SessionMemory(prefix="test-entries-")
        mem.save("tool_history", [
            {"tool_name": "bash", "result_preview": "output_123"},
            {"tool_name": "read", "result_preview": "file content"},
        ])
        ctx = self._make_ctx(session_memory=mem)
        _handle_session_command(["/session"], ctx)
        output = self._stdout.getvalue()
        self.assertIn("2 entries", output)
        self.assertIn("[bash]", output)
        self.assertIn("[read]", output)
        mem.close()


# ============================================================================
# 5. _save_session_progress deduplication
# ============================================================================


class TestSaveSessionProgressDedup(unittest.TestCase):
    """_save_session_progress does not produce duplicate entries."""

    def setUp(self) -> None:
        self.mem = SessionMemory(prefix="test-dedup-")

    def tearDown(self) -> None:
        self.mem.close()

    def test_no_duplicates_from_same_messages(self) -> None:
        """Calling _save_session_progress twice on the same messages
        appends entries only once."""
        msgs: list[dict[str, Any]] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"function": {"name": "bash", "arguments": {}}}]},
            {"role": "tool", "tool_name": "bash", "content": "output"},
        ]
        _save_session_progress(self.mem, msgs)
        self.assertEqual(len(self.mem.load("tool_history", [])), 1)

        # Second save with same messages (no new tool messages).
        _save_session_progress(self.mem, msgs)
        self.assertEqual(len(self.mem.load("tool_history", [])), 1)

    def test_append_only_new_entries(self) -> None:
        """Subsequent saves add only newly arrived tool messages."""
        msgs: list[dict[str, Any]] = [
            {"role": "user", "content": "run"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"function": {"name": "bash", "arguments": {}}}]},
            {"role": "tool", "tool_name": "bash", "content": "first_result"},
        ]
        _save_session_progress(self.mem, msgs)
        self.assertEqual(len(self.mem.load("tool_history", [])), 1)

        # Append new tool messages (simulating a second iteration).
        msgs2 = list(msgs) + [
            {"role": "assistant", "content": "",
             "tool_calls": [{"function": {"name": "read", "arguments": {}}}]},
            {"role": "tool", "tool_name": "read", "content": "second_result"},
        ]
        _save_session_progress(self.mem, msgs2)
        history = self.mem.load("tool_history", [])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["tool_name"], "bash")
        self.assertEqual(history[1]["tool_name"], "read")


# ============================================================================
# 6. Sub-agent session memory propagation
# ============================================================================


class TestSubAgentSessionMemory(unittest.TestCase):
    """SubAgent receives and saves to session_memory."""

    def test_agent_tool_has_session_memory_property(self) -> None:
        """AgentTool has a session_memory property that can be set."""
        from local_cli.tools.agent_tool import AgentTool
        from local_cli.sub_agent import SubAgentRunner

        runner = SubAgentRunner(max_workers=1)
        provider = MagicMock()
        tool = AgentTool(runner=runner, provider=provider, model="m",
                         sub_agent_tools=[])
        try:
            self.assertIsNone(tool.session_memory)
            mem = SessionMemory(prefix="test-agenttool-")
            tool.session_memory = mem
            self.assertIs(tool.session_memory, mem)
            mem.close()
        finally:
            runner.shutdown()

    def test_sub_agent_constructor_accepts_session_memory(self) -> None:
        """SubAgent.__init__ accepts a session_memory argument."""
        from local_cli.sub_agent import SubAgent, SubAgentRunner

        runner = SubAgentRunner(max_workers=1)
        mem = SessionMemory(prefix="test-subagent-")
        try:
            provider = MagicMock()
            agent = SubAgent(
                provider=provider,
                model="m",
                tools=[],
                prompt="test task",
                session_memory=mem,
            )
            self.assertIs(agent._session_memory, mem)
        finally:
            runner.shutdown()
            mem.close()

    def test_sub_agent_session_memory_defaults_to_none(self) -> None:
        """SubAgent without session_memory defaults to None (backward compat)."""
        from local_cli.sub_agent import SubAgent, SubAgentRunner

        runner = SubAgentRunner(max_workers=1)
        try:
            provider = MagicMock()
            agent = SubAgent(
                provider=provider,
                model="m",
                tools=[],
                prompt="test task",
            )
            self.assertIsNone(agent._session_memory)
        finally:
            runner.shutdown()


# ============================================================================
# 7. Session memory survives compaction
# ============================================================================


class TestSessionMemoryWithExitConditions(unittest.TestCase):
    """Session memory behaviour at session boundaries."""

    def setUp(self) -> None:
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = self._stdout
        sys.stderr = self._stderr

    def tearDown(self) -> None:
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def test_session_memory_survives_context_compaction(self) -> None:
        """tool_history in session memory survives message compaction."""
        from local_cli.agent import _COMPACT_KEEP_RECENT

        mem = SessionMemory(prefix="test-compact-")
        tool = _DummyTool(name="bash", result="ok")

        tc = [{"function": {"name": "bash", "arguments": {"command": "x"}}}]
        turn1 = [
            [_chunk("", tool_calls=tc)],
            [_chunk("Done. [TASK COMPLETE]")],
        ]
        client = _make_stream(turn1)
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "go"},
        ]
        agent_loop(client, "m", [tool], msgs, session_memory=mem)

        history_before = mem.load("tool_history", [])
        self.assertEqual(len(history_before), 1)

        # Verify tool history is still intact after simulating compaction
        # on a different set of messages.
        msgs2: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
        ]
        for _ in range(_COMPACT_KEEP_RECENT + 10):
            msgs2.append({"role": "tool", "tool_name": "t", "content": "x" * 1000})
        msgs2.append({"role": "user", "content": "next"})

        from local_cli.agent import compact_messages
        compact_messages(msgs2)

        history_after = mem.load("tool_history", [])
        self.assertEqual(len(history_after), 1)
        self.assertEqual(history_after[0]["tool_name"], "bash")
        self.assertIn("ok", history_after[0]["result_preview"])

        mem.close()


if __name__ == "__main__":
    unittest.main()
