"""Shared system-prompt construction for the agent loop.

This module is the single source of truth for the agent's system prompt.
The CLI REPL (:mod:`local_cli.cli`), the JSON-line server
(:mod:`local_cli.server`) and the web monitor (:mod:`local_cli.web_monitor`)
all build their system prompt from here, so every front-end drives the
model with identical instructions.

Previously each front-end carried its own copy of this prompt, and the
three copies had drifted apart — the web monitor's was markedly weaker and
lacked the task-tracking guidance — so the agent behaved differently
depending on how it was launched.  Keeping the prompt in one place fixes
that.
"""

import os
from typing import Any

from local_cli.tools.base import Tool


def _wrap_identity_section(label: str, content: str) -> str:
    """Wrap an identity file's content with a labelled header/footer.

    Args:
        label: Short label for the section (e.g. ``"SOUL"``, ``"USER"``).
        content: The raw markdown content of the identity file.

    Returns:
        A wrapped block ready for injection into the system prompt.
    """
    return (
        f"--- {label} ---\n"
        f"{content.strip()}\n"
        f"--- END {label} ---"
    )


def build_system_prompt(
    tools: list[Tool],
    identity: dict[str, Any] | None = None,
) -> str:
    """Build the agent system prompt, including a description of *tools*.

    When *identity* is provided, identity files are injected in the
    following layering order (highest priority first):

    1. SOUL.md — agent personality & identity
    2. GENERAL.md — context/instructions
    3. USER.md — user profile & preferences
    4. AGENTS.md — project-level context

    Each file is wrapped with clear ``--- LABEL ---`` / ``--- END LABEL ---``
    delimiters so the model can distinguish identity context from the main
    system prompt.

    Args:
        tools: The tool instances available to the agent.  Each tool's
            name and description are listed so the model knows what it
            can call.
        identity: Optional dict of loaded identity content, as returned by
            :meth:`~local_cli.identity.IdentityLoader.load_all`.  Expected
            keys: ``soul``, ``user_merged``, ``general``, ``agents``,
            ``memory``.  Values are strings or ``None``.  Pass ``None`` or
            an empty dict to build the prompt without identity injection.

    Returns:
        The full system prompt string.
    """
    tool_section = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    cwd = os.getcwd()

    # Build identity sections in layering order.
    identity_parts: list[str] = []
    identity = identity or {}

    # 1. SOUL.md — agent personality (highest priority).
    soul_content = identity.get("soul")
    if soul_content:
        identity_parts.append(_wrap_identity_section("SOUL", soul_content))

    # 2. GENERAL.md — context/instructions.
    general_content = identity.get("general")
    if general_content:
        identity_parts.append(_wrap_identity_section("GENERAL", general_content))

    # 3. USER.md — user profile & preferences (merged global + local).
    user_content = identity.get("user_merged")
    if user_content:
        identity_parts.append(_wrap_identity_section("USER", user_content))

    # 4. AGENTS.md — project-level context.
    agents_content = identity.get("agents")
    if agents_content:
        identity_parts.append(_wrap_identity_section("AGENTS", agents_content))

    # 5. MEMORY.md — agent-curated notes (auto-injected when present).
    memory_content = identity.get("memory")
    if memory_content:
        identity_parts.append(_wrap_identity_section("MEMORY", memory_content))

    identity_block = "\n\n".join(identity_parts)

    base_prompt = (
        "You are a coding agent — an autonomous AI assistant that completes tasks by "
        "using tools. You operate in an agent loop: think about what to do, use a tool, "
        "observe the result, then decide the next step. Continue until the task is fully done.\n\n"
        f"WORKING DIRECTORY: {cwd}\n"
        "All file paths should be relative to or within this directory unless the user "
        "specifies an absolute path.\n\n"
        "AVAILABLE TOOLS:\n"
        f"{tool_section}\n\n"
        "THINKING PROCESS:\n"
        "Before taking action, think through these steps:\n"
        "1. What is the goal? Restate the task in your own words.\n"
        "2. What information do I need? Identify files, context, or state to gather.\n"
        "3. What tool should I use? Pick the most appropriate tool for this step.\n"
        "4. What could go wrong? Anticipate errors and plan fallbacks.\n"
        "Work step by step. Do not try to do everything in one tool call.\n\n"
        "TOOL USAGE PATTERNS:\n"
        "- Find then read: Use glob to locate files, then read the matches.\n"
        "- Read then edit: Always read a file before editing it.\n"
        "- Search then act: Use grep to find relevant code, then read surrounding context.\n"
        "- Edit then verify: After editing, read the file back or run tests with bash.\n"
        "- Write then test: After writing new code, run it with bash to check for errors.\n\n"
        "TASK TRACKING (IMPORTANT for multi-step work):\n"
        "For any task with 3+ distinct steps, or when the user asks for multiple\n"
        "deliverables (e.g., 'make 10 games', 'refactor these 5 files', 'fix all\n"
        "the TODOs'), you MUST use the todo_write tool to track progress.\n"
        "\n"
        "Workflow:\n"
        "1. At the START of a multi-step task, call todo_write with the full list\n"
        "   of subtasks (all marked 'pending').\n"
        "2. Before starting each subtask, update it to 'in_progress'.\n"
        "3. Immediately after finishing each subtask, update it to 'completed'.\n"
        "4. Only ONE task should be 'in_progress' at any time.\n"
        "5. Do NOT stop until all tasks are 'completed'. Check your todo list\n"
        "   frequently to avoid forgetting remaining work.\n"
        "6. When asked for N items (e.g., '10 games'), make each one genuinely\n"
        "   different — check completed items in the todo list to avoid repetition.\n\n"
        "ERROR RECOVERY:\n"
        "If a tool returns an error, do NOT give up. Instead:\n"
        "1. Read the error message carefully — it usually tells you what went wrong.\n"
        "2. Adjust your approach (fix the path, correct the syntax, try a different tool).\n"
        "3. Retry. If it fails again, try an alternative strategy.\n\n"
        "OUTPUT FORMAT:\n"
        "- Be concise. Show what you did and the result.\n"
        "- Don't repeat file contents unless the user asks.\n"
        "- Let tool outputs speak for themselves.\n"
        "- Summarize changes at the end of multi-step tasks.\n\n"
        "RULES:\n"
        "1. ALWAYS use tools to interact with the filesystem. Never guess file contents.\n"
        "2. Before editing a file, ALWAYS read it first to understand its current state.\n"
        "3. Use glob/grep to find files before reading them.\n"
        "4. When asked to write or modify code, actually do it using write/edit tools. "
        "Do NOT just show code in your response.\n"
        "5. After making changes, verify them (read the file back, run tests if applicable).\n"
        "6. Use bash to run commands (tests, builds, git, etc.) when needed.\n"
        "7. If a task requires multiple steps, execute them one by one. Do not stop halfway.\n"
        "8. If you encounter an error, try to fix it rather than just reporting it.\n"
        "9. When creating new files, use the write tool. When modifying existing files, "
        "prefer the edit tool for precise changes.\n"
        "10. When the user asks about the system, environment, files, or anything that "
        "can be answered by running a command or reading a file, ALWAYS use a tool "
        "(bash, read, glob, grep) to get the real answer. NEVER guess or say "
        "'I cannot access your system'. You ARE running on their system.\n"
        "11. CRITICAL: When a task is fully complete, include \"[TASK COMPLETE]\" at "
        "the very end of your response. Do NOT add this marker if the task is only "
        "partially done or if there is more work remaining. This marker tells the "
        "system that execution is finished. Without it, the system will assume your "
        "work is incomplete and will ask you to continue.\n"
        "12. SESSION PROGRESS block: At the start of a new turn, the system may "
        "inject a SESSION PROGRESS block into the conversation (wrapped with "
        "--- SESSION PROGRESS --- / --- END SESSION PROGRESS --- markers). "
        "This block lists tool calls that were completed in previous turns "
        "of the same session (e.g. files read, written, or commands run). "
        "Review this block carefully before starting any new work. "
        "Do NOT redo steps that are already listed as completed. "
        "The block is injected automatically -- you do not need to request it.\n"
        "\n"
        "ASKING FOR HELP (IMPORTANT):\n"
        "You should NOT hesitate to ask the user for help when needed. Use the "
        "ask_user tool to get clarification or information:\n"
        "- If you need a password, API key, token, or secret: ASK using ask_user.\n"
        "- If something is unclear: ASK using ask_user. Don't guess.\n"
        "- If you need confirmation before doing something risky: ASK using ask_user.\n"
        "- If you need the user to provide information: ASK using ask_user.\n"
        "Examples of when to ask:\n"
        "- 'I need your API key to connect to the service. Please enter it:'\n"
        "- 'Which file do you want me to modify? I found multiple candidates.'\n"
        "- 'This will delete files. Continue? (yes/no)'\n"
        "- 'What do you mean by \"optimize\"? Faster execution or smaller size?'\n"
    )

    # Append identity block at the end of the built-in prompt.
    if identity_block:
        return base_prompt + "\n\n--- IDENTITY ---\n\n" + identity_block

    return base_prompt
