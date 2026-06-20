"""Argument parsing and interactive REPL for local-cli.

Provides :func:`build_parser` for CLI argument parsing using ``argparse``,
and :func:`run_repl` for the interactive read-eval-print loop.
"""

import argparse
import json
import os
import readline  # noqa: F401 — imported for side-effect (line editing/history)
import sys
from datetime import datetime, timezone
from pathlib import Path

from local_cli import __version__
from local_cli.agent import (
    _COMPACT_MESSAGE_THRESHOLD,
    _COMPACT_TOKEN_THRESHOLD,
    _estimate_tokens,
    _is_complex_request,
    _needs_compaction,
    agent_loop,
    build_plan_context,
    ideation_loop,
)
from local_cli.clipboard import (
    ClipboardError,
    ClipboardUnavailableError,
    copy_to_clipboard,
)
from local_cli.config import Config
from local_cli.git_ops import GitError, GitNotInstalledError, GitOps
from local_cli.ideation import IdeationEngine
from local_cli.knowledge import KnowledgeError, KnowledgeNotFoundError, KnowledgeStore
from local_cli.model_presets import SUPPORTS_THINKING, get_model_family, get_model_preset
from local_cli.ollama_client import OllamaClient, OllamaConnectionError
from local_cli.plan_manager import PlanError, PlanManager, PlanNotFoundError
from local_cli.prompts import build_system_prompt
from local_cli.session import SessionManager
from local_cli.session_memory import SessionMemory
from local_cli.identity import IdentityLoader
from local_cli.memory_proposals import (
    MemoryError,
    MemoryProposalManager,
    MemoryProposalNotFoundError,
)
from local_cli.skills import SkillsLoader
from local_cli.skill_proposals import (
    SkillFileError,
    SkillProposalError,
    SkillProposalManager,
    SkillProposalNotFoundError,
    SkillProposalInvalidStatusError,
)
from local_cli.self_heal import SelfHealEngine, get_project_structure
from local_cli.self_improvement import (
    ImprovementError,
    ImprovementProposalManager,
    ImprovementProposalNotFoundError,
    ImprovementProposalInvalidStatusError,
    InvalidTargetError,
    NudgeEngine,
)
from local_cli.stat import (
    _AMBER,
    _BOLD,
    _CYAN,
    _GRAY,
    _GREEN,
    _ORANGE,
    _RED,
    _RESET,
    _YELLOW,
    get_controller,
    get_status,
)
from local_cli.tools.base import Tool

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

_SLASH_COMMANDS: dict[str, str] = {
    "/identity": "Show loaded identity files (SOUL.md, USER.md, etc.) status.",
    "/memory": "Manage memory proposals — propose, approve, reject, list, show, edit.",
    "/queue <cmd>": "Queue command to run after current agent finishes.",
    "/bg <cmd>": "Run command in background mode.",
    "/stop": "Stop the running agent.",
    "/interview": "Start interview mode — AI asks questions about your project.",
    "/help": "Show this help message.",
    "/exit": "Exit the REPL.",
    "/quit": "Exit the REPL (alias for /exit).",
    "/clear": "Clear conversation history.",
    "/model <name>": "Switch to a different model.",
    "/status": "Show current model, message count, connection status.",
    "/save": "Save the current session.",
    "/models": "Open interactive model selector.",
    "/checkpoint": "Create a git checkpoint (tagged commit).",
    "/rollback [tag]": "Roll back to a checkpoint (latest if no tag given).",
    "/install <model>": "Pull/install a model from Ollama registry.",
    "/uninstall <model>": "Delete a model from Ollama.",
    "/info <model>": "Show model details and capabilities.",
    "/running": "List models currently loaded in VRAM.",
    "/provider [name]": "Switch or show the active LLM provider.",
    "/brain [model]": "Set or show the orchestrator brain model.",
    "/registry": "Show current model-to-task routing registry.",
    "/update": "Check for updates and pull the latest version.",
    "/undo": "Undo the most recent file modifications (git checkout).",
    "/diff": "Show uncommitted changes in the working tree.",
    "/context": "Show context window usage (messages, tokens, compaction).",
    "/copy": "Copy last assistant response to clipboard.",
    "/usage": "Show per-message token usage and session totals.",
    "/agents": "List background sub-agent status.",
    "/plan": "Show, create, or update plans.",
    "/ideate": "Enter ideation (brainstorming) mode.",
    "/knowledge": "Save, load, or list knowledge items.",
    "/skills": "Manage skills — list, show, propose, approve, reject, review, delete.",
    "/session": "Show session memory contents (tool history, temp dir). Use /session clear to reset.",
    "/nudge": "Show startup-style nudges (pending proposals, missing files, etc.).",
    "/improve": "Manage improvement proposals for identity files — propose, list, approve, reject.",
    "/heal": "Self-heal: scan codebase for bugs, detect issues, and attempt auto-fixes with git rollback safety.",
    "/structure [depth]": "Show the current project directory tree (optional depth, default 3).",
    "/log": "Show recent session logs (for debugging). Use /log <N> to show last N log entries.",
    "/plan big": "Show a big-picture overview of all plans with progress bars and status.",
}


class _ReplContext:
    """Mutable state shared between the REPL loop and slash command handler.

    Attributes:
        config: Application configuration.
        client: The Ollama client instance.
        tools: Available tool instances.
        messages: Conversation message history (mutated in place).
        session_manager: Session persistence manager.
        system_prompt: The system prompt string used to reset on /clear.
        rag_engine: Optional RAG engine for context augmentation.
        rag_topk: Number of RAG results per query.
        git_ops: GitOps instance for checkpoint/rollback commands.
        orchestrator: Optional orchestrator for provider/brain management.
        model_manager: Optional model manager for install/delete operations.
        token_tracker: Optional token usage tracker for /usage command.
        tool_cache: Optional tool result cache for read/glob/grep caching.
        sub_agent_runner: Optional SubAgentRunner for background agent
            status queries.
        plan_manager: Optional plan manager for plan CRUD operations.
        knowledge_store: Optional knowledge store for persistent knowledge.
        skills_loader: Optional skills loader for auto-discovered skills.
        identity_loader: Optional identity loader for SOUL.md/USER.md etc.
        memory_proposal_manager: Optional memory proposal manager.
        ideation_engine: Optional ideation engine for brainstorming mode.
        active_plan_id: ID of the currently active plan (or None).
        current_mode: Current REPL mode ('agent' or 'ideate').
        ideation_messages: Separate message history for ideation mode.
    """

    __slots__ = (
        "config",
        "client",
        "tools",
        "messages",
        "session_manager",
        "system_prompt",
        "identity_loader",
        "memory_proposal_manager",
        "rag_engine",
        "rag_topk",
        "git_ops",
        "orchestrator",
        "model_manager",
        "token_tracker",
        "tool_cache",
        "sub_agent_runner",
        "plan_manager",
        "knowledge_store",
        "skill_proposal_manager",
        "skills_loader",
        "improvement_proposal_manager",
        "nudge_engine",
        "ideation_engine",
        "active_plan_id",
        "current_mode",
        "ideation_messages",
        "session_memory",
    )

    def __init__(
        self,
        config: Config,
        client: OllamaClient,
        tools: list[Tool],
        messages: list[dict],
        session_manager: SessionManager,
        system_prompt: str,
        identity_loader: IdentityLoader | None = None,
        memory_proposal_manager: MemoryProposalManager | None = None,
        skill_proposal_manager: SkillProposalManager | None = None,
        rag_engine: object | None = None,
        rag_topk: int = 5,
        orchestrator: object | None = None,
        model_manager: object | None = None,
        token_tracker: object | None = None,
        tool_cache: object | None = None,
        sub_agent_runner: object | None = None,
        plan_manager: PlanManager | None = None,
        knowledge_store: KnowledgeStore | None = None,
        skills_loader: SkillsLoader | None = None,
        improvement_proposal_manager: ImprovementProposalManager | None = None,
        nudge_engine: NudgeEngine | None = None,
        ideation_engine: IdeationEngine | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.tools = tools
        self.messages = messages
        self.session_manager = session_manager
        self.system_prompt = system_prompt
        self.identity_loader = identity_loader
        self.memory_proposal_manager = memory_proposal_manager
        self.skill_proposal_manager = skill_proposal_manager
        self.improvement_proposal_manager = improvement_proposal_manager
        self.nudge_engine = nudge_engine
        self.rag_engine = rag_engine
        self.rag_topk = rag_topk
        self.git_ops = GitOps()
        self.orchestrator = orchestrator
        self.model_manager = model_manager
        self.token_tracker = token_tracker
        self.tool_cache = tool_cache
        self.sub_agent_runner = sub_agent_runner
        self.plan_manager = plan_manager
        self.knowledge_store = knowledge_store
        self.skills_loader = skills_loader
        self.ideation_engine = ideation_engine
        self.active_plan_id: str | None = None
        self.current_mode: str = "agent"
        self.ideation_messages: list[dict] = []
        self.session_memory: SessionMemory | None = None


def _handle_slash_command(command: str, ctx: _ReplContext) -> bool:
    """Handle a slash command.

    Args:
        command: The raw user input starting with ``/``.
        ctx: The REPL context containing shared state.

    Returns:
        True if the REPL should continue, False if it should exit.
    """
    stripped = command.strip()
    parts = stripped.split(maxsplit=1)
    cmd = parts[0].lower()

    # -- /exit, /quit -------------------------------------------------------
    if cmd in ("/exit", "/quit"):
        print(f"{_RED}Goodbye!{_RESET}")
        return False

    # -- /help --------------------------------------------------------------
    if cmd == "/help":
        print(f"\n{_RED}{_BOLD}Available commands:{_RESET}")
        for name, description in _SLASH_COMMANDS.items():
            cmd_color = _AMBER if name.startswith("/heal") or name.startswith("/structure") else _ORANGE
            print(f"  {cmd_color}{name:<20}{_RESET} {description}")
        print()
        return True

    # -- /clear -------------------------------------------------------------
    if cmd == "/clear":
        ctx.messages.clear()
        ctx.messages.append({"role": "system", "content": ctx.system_prompt})
        print(f"{_GREEN}✓{_RESET} Conversation history cleared.")
        return True

    # -- /model <name> ------------------------------------------------------
    if cmd == "/model":
        if len(parts) < 2 or not parts[1].strip():
            print(f"{_ORANGE}Usage:{_RESET} /model <name>")
            return True

        new_model = parts[1].strip()

        # Validate the model exists on the Ollama server.
        try:
            models = ctx.client.list_models()
            model_names = [m.get("name", "") for m in models]
            model_found = any(
                new_model == name or new_model == name.split(":")[0]
                for name in model_names
            )
            if not model_found:
                print(f"{_RED}✖{_RESET} Model '{_AMBER}{new_model}{_RESET}' not found on Ollama server.")
                if model_names:
                    print(f"  Available: {_GRAY}{', '.join(model_names)}{_RESET}")
                return True
        except OllamaConnectionError:
            print(f"{_YELLOW}⚠{_RESET} Warning: could not connect to Ollama to validate model.")
            print(f"  Switching to '{new_model}' anyway.")

        ctx.config.model = new_model
        print(f"{_GREEN}✓{_RESET} Switched to model: {_AMBER}{new_model}{_RESET}")
        return True

    # -- /status ------------------------------------------------------------
    if cmd == "/status":
        # Count user messages (exclude system and tool messages).
        user_msg_count = sum(
            1 for m in ctx.messages if m.get("role") == "user"
        )
        print(f"\n{_AMBER}⚡ {_BOLD}Model:{_RESET}     {ctx.config.model}")
        print(f"{_YELLOW}💬 {_BOLD}Messages:{_RESET}   {user_msg_count}")
        mode_color = _CYAN if ctx.current_mode == "agent" else _ORANGE
        print(f"{mode_color}◈ {_BOLD}Mode:{_RESET}       {ctx.current_mode}")

        # Show active plan if any.
        if ctx.active_plan_id is not None:
            print(f"{_ORANGE}⊘ {_BOLD}Active plan:{_RESET} {ctx.active_plan_id}")

        # Check Ollama connection status.
        try:
            version_info = ctx.client.get_version()
            version = version_info.get("version", "unknown")
            print(f"{_GREEN}● {_BOLD}Ollama:{_RESET}     connected (v{version})")
        except OllamaConnectionError:
            print(f"{_RED}● {_BOLD}Ollama:{_RESET}     {_RED}DISCONNECTED{_RESET}")

        print()
        return True

    # -- /models ------------------------------------------------------------
    if cmd == "/models":
        try:
            from local_cli.model_selector import select_model_interactive

            result = select_model_interactive(ctx.client, ctx.config.model)
            if result is not None:
                ctx.config.model = result
                print(f"{_GREEN}✓{_RESET} Switched to model: {_AMBER}{result}{_RESET}")
        except Exception as exc:
            print(f"{_RED}✖{_RESET} Model selection failed: {exc}")
        return True

    # -- /save --------------------------------------------------------------
    if cmd == "/save":
        try:
            session_id = ctx.session_manager.save_session(ctx.messages)
            print(f"{_GREEN}✓{_RESET} Session saved: {_AMBER}{session_id}{_RESET}")
        except OSError as exc:
            print(f"{_RED}✖{_RESET} Failed to save session: {exc}")
        return True

    # -- /checkpoint --------------------------------------------------------
    if cmd == "/checkpoint":
        # Optional message from the rest of the input.
        checkpoint_msg = parts[1].strip() if len(parts) > 1 else ""
        try:
            if not ctx.git_ops.is_git_repo():
                print(f"{_YELLOW}⚠{_RESET} Not a git repository. Cannot create checkpoint.")
                return True
            tag = ctx.git_ops.create_checkpoint(checkpoint_msg)
            print(f"{_GREEN}✓{_RESET} Checkpoint created: {_AMBER}{tag}{_RESET}")
        except GitNotInstalledError:
            print(f"{_RED}✖{_RESET} git is not installed. Cannot create checkpoint.")
        except GitError as exc:
            print(f"{_RED}✖{_RESET} Checkpoint failed: {exc}")
        return True

    # -- /rollback [tag] ----------------------------------------------------
    if cmd == "/rollback":
        try:
            if not ctx.git_ops.is_git_repo():
                print(f"{_YELLOW}⚠{_RESET} Not a git repository. Cannot rollback.")
                return True

            # Determine which tag to roll back to.
            if len(parts) > 1 and parts[1].strip():
                target_tag = parts[1].strip()
            else:
                # Use the most recent checkpoint.
                checkpoints = ctx.git_ops.list_checkpoints()
                if not checkpoints:
                    print(f"{_YELLOW}⚠{_RESET} No checkpoints found. Use /checkpoint first.")
                    return True
                target_tag = checkpoints[0]

            ctx.git_ops.rollback_to_checkpoint(target_tag)
            print(f"{_GREEN}✓{_RESET} Rolled back to checkpoint: {_AMBER}{target_tag}{_RESET}")
        except GitNotInstalledError:
            print(f"{_RED}✖{_RESET} git is not installed. Cannot rollback.")
        except GitError as exc:
            print(f"{_RED}✖{_RESET} Rollback failed: {exc}")
        return True

    # -- /undo --------------------------------------------------------------
    if cmd == "/undo":
        try:
            if not ctx.git_ops.is_git_repo():
                print(f"{_YELLOW}⚠{_RESET} Not a git repository. Cannot undo.")
                return True
            result = ctx.git_ops.undo_last_change()
            print(result)
        except GitNotInstalledError:
            print(f"{_RED}✖{_RESET} git is not installed. Cannot undo.")
        except GitError as exc:
            print(f"{_RED}✖{_RESET} Undo failed: {exc}")
        return True

    # -- /diff --------------------------------------------------------------
    if cmd == "/diff":
        try:
            if not ctx.git_ops.is_git_repo():
                print(f"{_YELLOW}⚠{_RESET} Not a git repository. Cannot show diff.")
                return True
            result = ctx.git_ops.diff_working_tree()
            print(result)
        except GitNotInstalledError:
            print(f"{_RED}✖{_RESET} git is not installed. Cannot show diff.")
        except GitError as exc:
            print(f"{_RED}✖{_RESET} Diff failed: {exc}")
        return True

    # -- /install <model> ---------------------------------------------------
    if cmd == "/install":
        if len(parts) < 2 or not parts[1].strip():
            print(f"{_ORANGE}Usage:{_RESET} /install <model>")
            return True

        if ctx.model_manager is None:
            print(f"{_YELLOW}⚠{_RESET} Model management not available.")
            return True

        model_name = parts[1].strip()

        def _print_progress(
            status: str, completed: int | None, total: int | None
        ) -> None:
            if completed is not None and total is not None and total > 0:
                pct = completed * 100 // total
                print(f"\r  {status}: {pct}%", end="", flush=True)
            else:
                print(f"\r  {status}", end="", flush=True)

        try:
            print(f"{_AMBER}⟳{_RESET} Installing {_BOLD}{model_name}{_RESET}...")
            ctx.model_manager.install_model(
                model_name, progress_callback=_print_progress
            )
            print(f"{_GREEN}✓{_RESET} Model '{_AMBER}{model_name}{_RESET}' installed successfully.")
        except ValueError as exc:
            print(f"{_RED}✖{_RESET} Invalid model name: {exc}")
        except Exception as exc:
            print(f"{_RED}✖{_RESET} Installation failed: {exc}")
        return True

    # -- /uninstall <model> -------------------------------------------------
    if cmd == "/uninstall":
        if len(parts) < 2 or not parts[1].strip():
            print(f"{_ORANGE}Usage:{_RESET} /uninstall <model>")
            return True

        if ctx.model_manager is None:
            print(f"{_YELLOW}⚠{_RESET} Model management not available.")
            return True

        model_name = parts[1].strip()
        try:
            ctx.model_manager.delete_model(model_name)
            print(f"{_GREEN}✓{_RESET} Model '{_AMBER}{model_name}{_RESET}' deleted.")
        except ValueError as exc:
            print(f"{_RED}✖{_RESET} Invalid model name: {exc}")
        except Exception as exc:
            print(f"{_RED}✖{_RESET} Deletion failed: {exc}")
        return True

    # -- /info <model> ------------------------------------------------------
    if cmd == "/info":
        if len(parts) < 2 or not parts[1].strip():
            print(f"{_ORANGE}Usage:{_RESET} /info <model>")
            return True

        if ctx.model_manager is None:
            print(f"{_YELLOW}⚠{_RESET} Model management not available.")
            return True

        model_name = parts[1].strip()
        try:
            info = ctx.model_manager.get_model_info(model_name)
            print(f"\n{_AMBER}{_BOLD}Model:{_RESET} {model_name}")
            details = info.get("details", {})
            if isinstance(details, dict):
                for key, value in details.items():
                    print(f"  {_GRAY}{key}:{_RESET} {value}")
            capabilities = info.get("capabilities")
            if capabilities:
                print(f"  {_GRAY}capabilities:{_RESET} {_GREEN}{', '.join(capabilities)}{_RESET}")
            license_text = info.get("license")
            if license_text:
                first_line = license_text.strip().split("\n")[0]
                print(f"  {_GRAY}license:{_RESET} {first_line}")
            print()
        except ValueError as exc:
            print(f"{_RED}✖{_RESET} Invalid model name: {exc}")
        except Exception as exc:
            print(f"{_RED}✖{_RESET} Failed to get model info: {exc}")
        return True

    # -- /running -----------------------------------------------------------
    if cmd == "/running":
        if ctx.model_manager is None:
            print(f"{_YELLOW}⚠{_RESET} Model management not available.")
            return True

        try:
            running = ctx.model_manager.list_running()
            if not running:
                print(f"{_GRAY}No models currently loaded in VRAM.{_RESET}")
            else:
                print(f"\n{_AMBER}{_BOLD}Models in VRAM ({len(running)}):{_RESET}")
                for model_info in running:
                    name = model_info.get("name", "unknown")
                    size = model_info.get("size", 0)
                    size_gb = size / (1024 ** 3) if size else 0
                    print(f"  {_GREEN}{name}{_RESET} ({_GRAY}{size_gb:.1f} GB{_RESET})")
                print()
        except Exception as exc:
            print(f"{_RED}✖{_RESET} Failed to list running models: {exc}")
        return True

    # -- /provider [name] ---------------------------------------------------
    if cmd == "/provider":
        if ctx.orchestrator is None:
            print(f"{_YELLOW}⚠{_RESET} Provider management not available.")
            return True

        if len(parts) < 2 or not parts[1].strip():
            current = ctx.orchestrator.get_active_provider_name()
            prov_color = _GREEN if current == "ollama" else _YELLOW
            print(f"{prov_color}◆{_RESET} Active provider: {_BOLD}{current}{_RESET}")
            return True

        new_provider = parts[1].strip().lower()
        try:
            ctx.orchestrator.switch_provider(new_provider)
            prov_color = _GREEN if new_provider == "ollama" else _YELLOW
            print(f"{prov_color}◆{_RESET} Switched to provider: {_BOLD}{new_provider}{_RESET}")
        except ValueError as exc:
            print(f"{_RED}✖{_RESET} Failed to switch provider: {exc}")
        return True

    # -- /brain [model] -----------------------------------------------------
    if cmd == "/brain":
        if ctx.orchestrator is None:
            print(f"{_YELLOW}⚠{_RESET} Orchestrator not available.")
            return True

        if len(parts) < 2 or not parts[1].strip():
            brain = ctx.orchestrator.get_brain_model()
            print(f"{_AMBER}🧠{_RESET} Brain model: {_BOLD}{brain}{_RESET}")
            return True

        new_brain = parts[1].strip()
        try:
            ctx.orchestrator.set_brain_model(new_brain)
            print(f"{_GREEN}✓{_RESET} Brain model set to: {_AMBER}{new_brain}{_RESET}")
        except ValueError as exc:
            print(f"{_RED}✖{_RESET} Invalid brain model: {exc}")
        return True

    # -- /registry ----------------------------------------------------------
    if cmd == "/registry":
        if ctx.orchestrator is None:
            print(f"{_YELLOW}⚠{_RESET} Orchestrator not available.")
            return True

        registry = ctx.orchestrator.registry
        if registry is None:
            print(f"{_YELLOW}⚠{_RESET} No model registry configured.")
            return True

        routes = registry.list_routes()
        if not routes:
            print(f"{_GRAY}Model registry is empty (using defaults).{_RESET}")
            default_provider, default_model = registry.get_default()
            print(f"  {_GRAY}Default:{_RESET} {default_provider}/{_AMBER}{default_model}{_RESET}")
        else:
            print(f"\n{_AMBER}{_BOLD}Model Registry:{_RESET}")
            default_provider, default_model = registry.get_default()
            print(f"  {_GRAY}Default:{_RESET} {default_provider}/{_AMBER}{default_model}{_RESET}")
            for task_type, entries in routes.items():
                print(f"  {_YELLOW}{task_type}:{_RESET}")
                for entry in entries:
                    provider = entry.get("provider", "?")
                    model = entry.get("model", "?")
                    priority = entry.get("priority", "?")
                    print(f"    [{_GRAY}{priority}{_RESET}] {provider}/{_AMBER}{model}{_RESET}")
            print()
        return True

    # -- /update ------------------------------------------------------------
    if cmd == "/update":
        from local_cli.updater import check_for_updates, perform_update

        print(f"{_AMBER}⟳{_RESET} Checking for updates...")
        has_updates, check_msg = check_for_updates()
        if not has_updates:
            print(f"{_GREEN}✓{_RESET} {check_msg}")
            return True

        print(f"{_YELLOW}ℹ{_RESET} {check_msg}")
        print(f"{_AMBER}⟳{_RESET} Updating...")
        success, update_msg = perform_update()
        if success:
            print(f"{_GREEN}✓{_RESET} {update_msg}")
        else:
            print(f"{_RED}✖{_RESET} {update_msg}")
        return True

    # -- /context -----------------------------------------------------------
    if cmd == "/context":
        msg_count = len(ctx.messages)
        est_tokens = _estimate_tokens(ctx.messages)
        token_limit = _COMPACT_TOKEN_THRESHOLD
        compaction_triggered = _needs_compaction(ctx.messages)
        compaction_status = "triggered" if compaction_triggered else "not triggered"
        status_color = _RED if compaction_triggered else _GREEN
        print(
            f"{_GRAY}Messages:{_RESET} {_BOLD}{msg_count}{_RESET} | "
            f"{_GRAY}Tokens:{_RESET} ~{_BOLD}{est_tokens}{_RESET} / {token_limit} | "
            f"{_GRAY}Compaction:{_RESET} {status_color}{compaction_status}{_RESET}"
        )
        return True

    # -- /copy --------------------------------------------------------------
    if cmd == "/copy":
        last_assistant = None
        for msg in reversed(ctx.messages):
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if content:
                    last_assistant = content
                    break

        if last_assistant is None:
            print(f"{_YELLOW}⚠{_RESET} Nothing to copy.")
            return True

        try:
            copy_to_clipboard(last_assistant)
            print(f"{_GREEN}✓{_RESET} Copied to clipboard.")
        except ClipboardUnavailableError:
            print(f"{_YELLOW}⚠{_RESET} Clipboard not available.")
        except ClipboardError as exc:
            print(f"{_RED}✖{_RESET} Copy failed: {exc}")
        return True

    # -- /usage -------------------------------------------------------------
    if cmd == "/usage":
        if ctx.token_tracker is None:
            print(f"{_YELLOW}⚠{_RESET} Token tracking not available.")
            return True

        print(ctx.token_tracker.format_table())
        return True

    # -- /agents ------------------------------------------------------------
    if cmd == "/agents":
        if ctx.sub_agent_runner is None:
            print(f"{_YELLOW}⚠{_RESET} Sub-agent support not available.")
            return True

        agents = ctx.sub_agent_runner.list_background_agents()
        if not agents:
            print(f"{_GRAY}No background agents.{_RESET}")
        else:
            print(f"\n{_AMBER}{_BOLD}Background agents ({len(agents)}):{_RESET}")
            for info in agents:
                agent_id = info.get("agent_id", "?")
                status = info.get("status", "?")
                status_color = _GREEN if status == "running" else _YELLOW if status == "pending" else _GRAY
                print(f"  {_CYAN}{agent_id}{_RESET}  {status_color}{status}{_RESET}")
            print()
        return True

    # -- /plan [subcommand] -------------------------------------------------
    if cmd == "/plan":
        return _handle_plan_command(parts, ctx)

    # -- /ideate [subcommand] -----------------------------------------------
    if cmd == "/ideate":
        return _handle_ideate_command(parts, ctx)

    # -- /knowledge [subcommand] --------------------------------------------
    if cmd == "/knowledge":
        return _handle_knowledge_command(parts, ctx)

    # -- /memory [subcommand] -------------------------------------------------
    if cmd == "/memory":
        return _handle_memory_command(parts, ctx)

    # -- /identity ------------------------------------------------------------
    if cmd == "/identity":
        return _handle_identity_command(ctx)

    # -- /nudge ---------------------------------------------------------------
    if cmd == "/nudge":
        return _handle_nudge_command(ctx)

    # -- /improve [subcommand] ------------------------------------------------
    if cmd == "/improve":
        return _handle_improve_command(parts, ctx)

    # -- /queue <command> ------------------------------------------------------
    if cmd == "/queue":
        return _handle_queue_command(parts)

    # -- /bg <command> ---------------------------------------------------------
    if cmd == "/bg":
        return _handle_bg_command(parts)

    # -- /stop -----------------------------------------------------------------
    if cmd == "/stop":
        return _handle_stop_command()

    # -- /interview ------------------------------------------------------------
    if cmd == "/interview":
        return _handle_interview_command(parts)

    # -- /skills [subcommand] -----------------------------------------------
    if cmd == "/skills":
        return _handle_skills_command(parts, ctx)

    # -- /session [subcommand] -------------------------------------------------
    if cmd == "/session":
        return _handle_session_command(parts, ctx)

    # -- /heal ----------------------------------------------------------------
    if cmd == "/heal":
        return _handle_heal_command(ctx)

    # -- /structure [depth] ---------------------------------------------------
    if cmd == "/structure":
        return _handle_structure_command(parts, ctx)

    # -- /log -----------------------------------------------------------------
    if cmd == "/log":
        return _handle_log_command(parts, ctx)

    # -- Unknown command ----------------------------------------------------
    print(f"{_RED}✖ Unknown command:{_RESET} {stripped}")
    print(f"{_GRAY}Type /help for a list of commands.{_RESET}")
    return True


# ---------------------------------------------------------------------------
# Plan command handler
# ---------------------------------------------------------------------------


def _handle_plan_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /plan slash command and its subcommands.

    Subcommands:
        - ``/plan`` or ``/plan list`` — list all plans.
        - ``/plan create <title>`` — create a new plan.
        - ``/plan show <id>`` — show a plan's details.
        - ``/plan activate <id>`` — set a plan as the active plan.
        - ``/plan update <id> <step> done|undone`` — mark a step.
        - ``/plan review <id>`` — request an LLM review of a plan.
        - ``/plan abandon <id>`` — abandon a plan.

    Args:
        parts: The split command parts (``["/plan", ...]``).
        ctx: The REPL context containing shared state.

    Returns:
        True to continue the REPL.
    """
    if ctx.plan_manager is None:
        print("Plan management not available.")
        return True

    # No subcommand or "list" → list plans.
    if len(parts) < 2 or not parts[1].strip():
        return _plan_list(ctx)

    sub_parts = parts[1].strip().split(maxsplit=1)
    subcmd = sub_parts[0].lower()
    sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if subcmd == "list":
        return _plan_list(ctx)

    if subcmd == "create":
        if not sub_arg:
            print("Usage: /plan create <title>")
            return True
        try:
            plan = ctx.plan_manager.create_plan(
                title=sub_arg,
                model=ctx.config.model,
            )
            print(f"Plan {plan.plan_id} created: {plan.title}")
        except PlanError as exc:
            print(f"Failed to create plan: {exc}")
        return True

    if subcmd == "show":
        if not sub_arg:
            print("Usage: /plan show <id>")
            return True
        try:
            plan = ctx.plan_manager.show_plan(sub_arg)
            _print_plan(plan)
        except PlanNotFoundError:
            print(f"Plan '{sub_arg}' not found.")
        except PlanError as exc:
            print(f"Failed to show plan: {exc}")
        return True

    if subcmd == "activate":
        if not sub_arg:
            print("Usage: /plan activate <id>")
            return True
        try:
            plan = ctx.plan_manager.activate_plan(sub_arg)
            ctx.active_plan_id = plan.plan_id
            print(f"Plan {plan.plan_id} activated: {plan.title}")
        except PlanNotFoundError:
            print(f"Plan '{sub_arg}' not found.")
        except PlanError as exc:
            print(f"Failed to activate plan: {exc}")
        return True

    if subcmd == "update":
        # Expected format: /plan update <id> <step> done|undone
        update_parts = sub_arg.split(maxsplit=2)
        if len(update_parts) < 3:
            print("Usage: /plan update <id> <step> done|undone")
            return True
        plan_id = update_parts[0]
        try:
            step_num = int(update_parts[1])
        except ValueError:
            print("Step number must be an integer.")
            return True
        done_str = update_parts[2].lower()
        if done_str not in ("done", "undone"):
            print("Status must be 'done' or 'undone'.")
            return True
        done = done_str == "done"
        try:
            plan = ctx.plan_manager.update_step(plan_id, step_num, done)
            mark = "done" if done else "undone"
            print(f"Step {step_num} marked as {mark}.")
            if plan.status == "complete":
                print(f"Plan {plan.plan_id} is now complete!")
        except PlanNotFoundError:
            print(f"Plan '{plan_id}' not found.")
        except PlanError as exc:
            print(f"Failed to update step: {exc}")
        return True

    if subcmd == "review":
        if not sub_arg:
            print("Usage: /plan review <id>")
            return True
        try:
            content = ctx.plan_manager.get_plan_content(sub_arg)
        except PlanNotFoundError:
            print(f"Plan '{sub_arg}' not found.")
            return True
        except PlanError as exc:
            print(f"Failed to read plan: {exc}")
            return True

        # Send plan content to LLM for review via ideation-style loop.
        review_prompt = (
            "Please review and critique the following plan. "
            "Identify risks, suggest improvements, and assess feasibility.\n\n"
            f"{content}"
        )
        review_messages: list[dict] = [
            {"role": "system", "content": ctx.system_prompt},
            {"role": "user", "content": review_prompt},
        ]
        try:
            ideation_loop(
                client=ctx.client,
                model=ctx.config.model,
                messages=review_messages,
                think=True,
            )
        except KeyboardInterrupt:
            print("\nReview interrupted.")
        return True

    if subcmd == "abandon":
        if not sub_arg:
            print("Usage: /plan abandon <id>")
            return True
        try:
            plan = ctx.plan_manager.abandon_plan(sub_arg)
            print(f"Plan {plan.plan_id} abandoned.")
            if ctx.active_plan_id == plan.plan_id:
                ctx.active_plan_id = None
        except PlanNotFoundError:
            print(f"Plan '{sub_arg}' not found.")
        except PlanError as exc:
            print(f"Failed to abandon plan: {exc}")
        return True

    if subcmd == "big":
        return _plan_big(ctx)

    print(f"Unknown plan subcommand: {subcmd}")
    print("Usage: /plan [list|create|show|activate|update|review|abandon|big]")
    return True


def _plan_big(ctx: _ReplContext) -> bool:
    """Show big-picture overview of all plans with progress bars.

    Args:
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    try:
        plans = ctx.plan_manager.list_plans()
    except PlanError as exc:
        print(f"Failed to list plans: {exc}")
        return True

    if not plans:
        print(f"{_YELLOW}No plans found. Create one with /plan create <title>{_RESET}")
        return True

    print(f"\n{_RED}{_BOLD}╔══════════════════════════════════════════════════════╗{_RESET}")
    print(f"{_RED}{_BOLD}║              PLANS BIG PICTURE                     ║{_RESET}")
    print(f"{_RED}{_BOLD}╚══════════════════════════════════════════════════════╝{_RESET}")

    total_steps = 0
    total_done = 0
    active_count = 0
    complete_count = 0

    for plan in plans:
        done = sum(1 for d, _ in plan.steps if d)
        total = len(plan.steps)
        total_steps += total
        total_done += done
        if plan.status == "active":
            active_count += 1
        elif plan.status == "complete":
            complete_count += 1

        # Build progress bar.
        bar_width = 30
        if total > 0:
            pct = done / total
            filled = int(bar_width * pct)
            bar = "█" * filled + "░" * (bar_width - filled)
        else:
            bar = "░" * bar_width

        active_marker = f"{_GREEN}▶{_RESET}" if plan.plan_id == ctx.active_plan_id else " "

        # Color the plan ID based on status.
        if plan.status == "complete":
            id_color = _GREEN
        elif plan.status == "active":
            id_color = _AMBER
        elif plan.status == "abandoned":
            id_color = _GRAY
        else:
            id_color = _YELLOW

        progress = f"{done}/{total}" if total > 0 else "-"
        print(
            f"\n {active_marker} {id_color}{plan.plan_id}{_RESET}  "
            f"{plan.title:<30} "
            f"{_BOLD}{bar}{_RESET}  "
            f"{progress:<5} "
            f"{_GRAY}({plan.status}){_RESET}"
        )

        # Show created date.
        if plan.created:
            print(f"     {_GRAY}created: {plan.created[:10]}{_RESET}")

        # Show a snippet of steps inline.
        for i, (done_flag, text) in enumerate(plan.steps[:3], 1):
            checkbox = f"{_GREEN}✓{_RESET}" if done_flag else f"{_GRAY}○{_RESET}"
            max_text = 60
            display = text[:max_text] + "..." if len(text) > max_text else text
            print(f"     {checkbox} {display}")
        if len(plan.steps) > 3:
            print(f"     {_GRAY}... and {len(plan.steps) - 3} more step(s){_RESET}")

    # ── Summary footer ───────────────────────────────────────────────
    print(f"\n{_RED}─{_RESET}{_BOLD}{'─' * 55}{_RESET}")
    total_pct = (total_done / total_steps * 100) if total_steps > 0 else 0
    bar_width = 30
    filled = int(bar_width * total_pct / 100) if total_steps > 0 else 0
    summary_bar = "█" * filled + "░" * (bar_width - filled)
    print(
        f" {_BOLD}Total:{_RESET} {len(plans)} plan(s), "
        f"{active_count} active, {complete_count} complete | "
        f"{total_done}/{total_steps} steps  "
        f"{summary_bar}  {total_pct:.0f}%"
    )
    print(f"{_GRAY}▶ = active plan (context auto-injected){_RESET}")
    print()
    return True


def _plan_list(ctx: _ReplContext) -> bool:
    """List all plans with their status.

    Args:
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    try:
        plans = ctx.plan_manager.list_plans()
    except PlanError as exc:
        print(f"Failed to list plans: {exc}")
        return True

    if not plans:
        print("No plans found.")
        return True

    print("\nPlans:")
    for plan in plans:
        active_marker = " *" if plan.plan_id == ctx.active_plan_id else ""
        done_count = sum(1 for done, _ in plan.steps if done)
        total = len(plan.steps)
        progress = f"[{done_count}/{total}]" if total > 0 else ""
        print(
            f"  {plan.plan_id}  {plan.status:<10}  "
            f"{plan.title}  {progress}{active_marker}"
        )
    print()
    return True


def _print_plan(plan: "object") -> None:
    """Pretty-print a plan to stdout.

    Args:
        plan: A :class:`Plan` instance.
    """
    print(f"\n# Plan {plan.plan_id}: {plan.title}")
    print(f"  Status:  {plan.status}")
    print(f"  Created: {plan.created}")
    if plan.model:
        print(f"  Model:   {plan.model}")
    if plan.description:
        print(f"\n  {plan.description}")
    if plan.steps:
        print("\n  Steps:")
        for i, (done, text) in enumerate(plan.steps, 1):
            checkbox = "[x]" if done else "[ ]"
            print(f"    {i}. {checkbox} {text}")
    if plan.notes:
        print(f"\n  Notes: {plan.notes}")
    print()


# ---------------------------------------------------------------------------
# Ideate command handler
# ---------------------------------------------------------------------------


def _handle_ideate_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /ideate slash command and its subcommands.

    Subcommands:
        - ``/ideate`` — enter ideation (brainstorming) mode.
        - ``/ideate exit`` — return to normal agent mode.
        - ``/ideate clear`` — clear ideation history.
        - ``/ideate once <prompt>`` — single-shot ideation via /api/generate.

    Args:
        parts: The split command parts (``["/ideate", ...]``).
        ctx: The REPL context containing shared state.

    Returns:
        True to continue the REPL.
    """
    if ctx.ideation_engine is None:
        print("Ideation engine not available.")
        return True

    # No subcommand → enter ideation mode.
    if len(parts) < 2 or not parts[1].strip():
        ctx.current_mode = "ideate"
        if not ctx.ideation_engine.has_session:
            ctx.ideation_engine.start_session()
        print("Entered ideation mode. Type /ideate exit to return.")
        return True

    sub_parts = parts[1].strip().split(maxsplit=1)
    subcmd = sub_parts[0].lower()
    sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if subcmd == "exit":
        ctx.current_mode = "agent"
        print("Returned to agent mode.")
        return True

    if subcmd == "clear":
        ctx.ideation_engine.clear_history()
        print("Ideation history cleared.")
        return True

    if subcmd == "once":
        if not sub_arg:
            print("Usage: /ideate once <prompt>")
            return True
        try:
            ctx.ideation_engine.single_shot(
                prompt=sub_arg,
                model=ctx.config.model,
            )
        except Exception as exc:
            print(f"Ideation failed: {exc}")
        return True

    print(f"Unknown ideate subcommand: {subcmd}")
    print("Usage: /ideate [exit|clear|once <prompt>]")
    return True


# ---------------------------------------------------------------------------
# Knowledge command handler
# ---------------------------------------------------------------------------


def _handle_knowledge_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /knowledge slash command and its subcommands.

    Subcommands:
        - ``/knowledge`` or ``/knowledge list`` — list all knowledge items.
        - ``/knowledge save <name>`` — save a knowledge item.
        - ``/knowledge load <name>`` — load a knowledge item into context.
        - ``/knowledge delete <name>`` — delete a knowledge item.

    Args:
        parts: The split command parts (``["/knowledge", ...]``).
        ctx: The REPL context containing shared state.

    Returns:
        True to continue the REPL.
    """
    if ctx.knowledge_store is None:
        print("Knowledge store not available.")
        return True

    # No subcommand or "list" → list items.
    if len(parts) < 2 or not parts[1].strip():
        return _knowledge_list(ctx)

    sub_parts = parts[1].strip().split(maxsplit=1)
    subcmd = sub_parts[0].lower()
    sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if subcmd == "list":
        return _knowledge_list(ctx)

    if subcmd == "save":
        if not sub_arg:
            print("Usage: /knowledge save <name>")
            return True
        # Save with description from last assistant message if available.
        description = ""
        content = ""
        for msg in reversed(ctx.messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                description = content[:100] if content else ""
                break
        try:
            ctx.knowledge_store.save_item(
                name=sub_arg,
                description=description,
                content=content,
            )
            print(f"Knowledge item '{sub_arg}' saved.")
        except KnowledgeError as exc:
            print(f"Failed to save knowledge: {exc}")
        return True

    if subcmd == "load":
        if not sub_arg:
            print("Usage: /knowledge load <name>")
            return True
        try:
            item = ctx.knowledge_store.load_item(sub_arg)
            # Inject knowledge content into the conversation as a system message.
            artifacts = item.get("artifacts_content", {})
            content_parts = []
            for artifact_name, artifact_content in artifacts.items():
                content_parts.append(
                    f"--- {artifact_name} ---\n{artifact_content}"
                )
            if content_parts:
                knowledge_content = "\n\n".join(content_parts)
                ctx.messages.append({
                    "role": "system",
                    "content": (
                        f"Knowledge item '{sub_arg}' loaded:\n\n"
                        f"{knowledge_content}"
                    ),
                })
            print(f"Knowledge item '{sub_arg}' loaded into context.")
        except KnowledgeNotFoundError:
            print(f"Knowledge item '{sub_arg}' not found.")
        except KnowledgeError as exc:
            print(f"Failed to load knowledge: {exc}")
        return True

    if subcmd == "delete":
        if not sub_arg:
            print("Usage: /knowledge delete <name>")
            return True
        try:
            ctx.knowledge_store.delete_item(sub_arg)
            print(f"Knowledge item '{sub_arg}' deleted.")
        except KnowledgeNotFoundError:
            print(f"Knowledge item '{sub_arg}' not found.")
        except KnowledgeError as exc:
            print(f"Failed to delete knowledge: {exc}")
        return True

    print(f"Unknown knowledge subcommand: {subcmd}")
    print("Usage: /knowledge [list|save|load|delete] <name>")
    return True


def _knowledge_list(ctx: _ReplContext) -> bool:
    """List all knowledge items.

    Args:
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    try:
        items = ctx.knowledge_store.list_items()
    except KnowledgeError as exc:
        print(f"Failed to list knowledge: {exc}")
        return True

    if not items:
        print("No knowledge items found.")
        return True

    print("\nKnowledge items:")
    for item in items:
        name = item.get("name", "?")
        desc = item.get("description", "")
        tags = item.get("tags", [])
        tag_str = f"  [{', '.join(tags)}]" if tags else ""
        print(f"  {name}: {desc[:60]}{tag_str}")
    print()
    return True


# ---------------------------------------------------------------------------
# Memory command handler
# ---------------------------------------------------------------------------


def _handle_memory_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /memory slash command and its subcommands.

    Subcommands:
        - ``/memory`` or ``/memory list`` — list pending proposals.
        - ``/memory propose <content>`` — create a new pending proposal.
        - ``/memory approve [id]`` — approve a pending proposal.
        - ``/memory reject [id]`` — reject a pending proposal.
        - ``/memory show`` — display current MEMORY.md content.
        - ``/memory edit`` — open MEMORY.md in ``$EDITOR``.
        - ``/memory clear`` — clear all proposals.

    Args:
        parts: The split command parts (``["/memory", ...]``).
        ctx: The REPL context containing shared state.

    Returns:
        True to continue the REPL.
    """
    if ctx.memory_proposal_manager is None:
        print("Memory proposal system not available.")
        return True

    mgr = ctx.memory_proposal_manager

    # No subcommand or "list" → list pending proposals.
    if len(parts) < 2 or not parts[1].strip():
        return _memory_list(ctx, mgr)

    sub_parts = parts[1].strip().split(maxsplit=1)
    subcmd = sub_parts[0].lower()
    sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if subcmd == "list":
        return _memory_list(ctx, mgr)

    if subcmd == "propose":
        if not sub_arg:
            print("Usage: /memory propose <content>")
            return True
        try:
            proposal = mgr.propose(sub_arg)
            print(
                f"Memory proposal {proposal['id']} created. "
                f"Run `/memory approve {proposal['id']}` to add it to MEMORY.md."
            )
        except MemoryError as exc:
            print(f"Failed to create proposal: {exc}")
        return True

    if subcmd == "approve":
        if not sub_arg:
            pending = mgr.list_pending()
            if not pending:
                print("No pending proposals to approve.")
                return True
            if len(pending) > 1:
                print("Multiple pending proposals. Specify an ID: /memory approve <id>")
                return _memory_list(ctx, mgr)
            sub_arg = pending[0]["id"]
        try:
            proposal = mgr.approve(sub_arg)
            print(
                f"Proposal {proposal['id']} approved and appended to MEMORY.md."
            )
            # Show size warning if MEMORY.md is getting large.
            if mgr.is_memory_too_large():
                print(
                    "  Note: MEMORY.md is over 256 KB. "
                    "Consider summarizing or archiving old entries."
                )
        except MemoryProposalNotFoundError:
            print(f"Proposal '{sub_arg}' not found.")
        except MemoryError as exc:
            print(f"Failed to approve proposal: {exc}")
        return True

    if subcmd == "reject":
        if not sub_arg:
            pending = mgr.list_pending()
            if not pending:
                print("No pending proposals to reject.")
                return True
            if len(pending) > 1:
                print("Multiple pending proposals. Specify an ID: /memory reject <id>")
                return _memory_list(ctx, mgr)
            sub_arg = pending[0]["id"]
        try:
            proposal = mgr.reject(sub_arg)
            print(f"Proposal '{proposal['id']}' rejected.")
        except MemoryProposalNotFoundError:
            print(f"Proposal '{sub_arg}' not found.")
        except MemoryError as exc:
            print(f"Failed to reject proposal: {exc}")
        return True

    if subcmd == "show":
        content = mgr.show_memory()
        if not content:
            print("MEMORY.md does not exist yet. Create a proposal with /memory propose first.")
            return True
        size = mgr.get_memory_size()
        print(f"\n--- MEMORY.md ({size} bytes) ---")
        print(content)
        if not content.endswith("\n"):
            print()
        if mgr.is_memory_too_large():
            print("  (MEMORY.md is over 256 KB — consider summarizing)")
        return True

    if subcmd == "edit":
        try:
            result = mgr.edit_memory()
            print(result)
        except MemoryError as exc:
            print(f"Failed to edit MEMORY.md: {exc}")
        return True

    if subcmd == "clear":
        count = mgr.clear_all()
        if count > 0:
            print(f"Cleared {count} proposal(s).")
        else:
            print("No proposals to clear.")
        return True

    print(f"Unknown memory subcommand: {subcmd}")
    print("Usage: /memory [list|propose|approve|reject|show|edit|clear]")
    return True


def _memory_list(ctx: _ReplContext, mgr: MemoryProposalManager) -> bool:
    """List pending memory proposals.

    Args:
        ctx: The REPL context.
        mgr: The MemoryProposalManager instance.

    Returns:
        True to continue the REPL.
    """
    pending = mgr.list_pending()
    if not pending:
        print("No pending memory proposals.")
        return True

    print(f"\nPending memory proposals ({len(pending)}):")
    for p in pending:
        pid = p.get("id", "?")
        content = p.get("content", "")
        timestamp = p.get("timestamp", "")
        preview = content[:80].replace("\n", " ")
        if len(content) > 80:
            preview += "..."
        print(f"  {pid}  [{timestamp}]  {preview}")
    print()
    return True


# ---------------------------------------------------------------------------
# Identity command handler
# ---------------------------------------------------------------------------


def _handle_identity_command(ctx: _ReplContext) -> bool:
    """Handle /identity command — show loaded identity file status.

    Args:
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    if ctx.identity_loader is None:
        print("Identity system not available.")
        return True

    status = ctx.identity_loader.get_status()
    if not any(status.values()):
        print("\nIdentity files: none found.")
        print("Create .agents/SOUL.md, .agents/USER.md, etc. to get started,")
        print("or run `local-cli --init-agents` to generate default templates.\n")
        return True

    print("\nIdentity files:")
    for name, exists in status.items():
        marker = "✓" if exists else " "
        print(f"  [{marker}] {name}")
    print()
    return True


# ---------------------------------------------------------------------------
# Skills command handler
# ---------------------------------------------------------------------------


def _handle_skills_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /skills slash command and its subcommands.

    Subcommands:
        - ``/skills`` or ``/skills list`` — list all discovered skills.
        - ``/skills show <name>`` — show a skill's content.
        - ``/skills propose <content>`` — create a new pending skill proposal.
        - ``/skills approve [id]`` — approve and create skill from proposal.
        - ``/skills reject [id]`` — reject a pending skill proposal.
        - ``/skills review [id]`` — show full details of a proposal.
        - ``/skills list-proposals`` — list all pending proposals.
        - ``/skills delete <name>`` — delete an existing skill.

    Args:
        parts: The split command parts (``["/skills", ...]``).
        ctx: The REPL context containing shared state.

    Returns:
        True to continue the REPL.
    """
    if ctx.skills_loader is None:
        print("Skills system not available.")
        return True

    # No subcommand or "list" → list skills.
    if len(parts) < 2 or not parts[1].strip():
        return _skills_list(ctx)

    sub_parts = parts[1].strip().split(maxsplit=1)
    subcmd = sub_parts[0].lower()
    sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if subcmd == "list":
        return _skills_list(ctx)

    if subcmd == "show":
        if not sub_arg:
            print("Usage: /skills show <name>")
            return True
        try:
            content = ctx.skills_loader.get_skill_content(sub_arg)
            print(f"\n{content}\n")
        except Exception:
            print(f"Skill '{sub_arg}' not found.")
        return True

    if subcmd == "propose":
        if not sub_arg:
            print("Usage: /skills propose <content>")
            return True
        if ctx.skill_proposal_manager is None:
            print("Skill proposal system not available.")
            return True
        try:
            proposal = ctx.skill_proposal_manager.propose(content=sub_arg)
            print(
                f"Skill proposal {proposal['id']} created. "
                f"Run `/skills approve {proposal['id']}` to create the skill file."
            )
        except SkillProposalError as exc:
            print(f"Failed to create proposal: {exc}")
        return True

    if subcmd == "approve":
        if ctx.skill_proposal_manager is None:
            print("Skill proposal system not available.")
            return True
        if not sub_arg:
            pending = ctx.skill_proposal_manager.list_pending()
            if not pending:
                print("No pending skill proposals to approve.")
                return True
            if len(pending) > 1:
                print("Multiple pending proposals. Specify an ID: /skills approve <id>")
                return _skill_proposals_list(ctx)
            sub_arg = pending[0]["id"]
        try:
            proposal = ctx.skill_proposal_manager.approve(sub_arg)
            print(
                f"Proposal {proposal['id']} ('{proposal['name']}') approved. "
                f"Skill file created at .agents/skills/{proposal['name']}/SKILL.md."
            )
            # Skills loader is refreshed via the post-approve callback.
        except SkillProposalNotFoundError:
            print(f"Proposal '{sub_arg}' not found.")
        except SkillProposalInvalidStatusError as exc:
            print(str(exc))
        except SkillProposalError as exc:
            print(f"Failed to approve proposal: {exc}")
        return True

    if subcmd == "reject":
        if ctx.skill_proposal_manager is None:
            print("Skill proposal system not available.")
            return True
        if not sub_arg:
            pending = ctx.skill_proposal_manager.list_pending()
            if not pending:
                print("No pending skill proposals to reject.")
                return True
            if len(pending) > 1:
                print("Multiple pending proposals. Specify an ID: /skills reject <id>")
                return _skill_proposals_list(ctx)
            sub_arg = pending[0]["id"]
        try:
            proposal = ctx.skill_proposal_manager.reject(sub_arg)
            print(f"Proposal '{proposal['id']}' ('{proposal['name']}') rejected.")
        except SkillProposalNotFoundError:
            print(f"Proposal '{sub_arg}' not found.")
        except SkillProposalInvalidStatusError as exc:
            print(str(exc))
        return True

    if subcmd == "review":
        if ctx.skill_proposal_manager is None:
            print("Skill proposal system not available.")
            return True
        if not sub_arg:
            print("Usage: /skills review <id>")
            return True
        try:
            proposal = ctx.skill_proposal_manager.get_proposal(sub_arg)
            _print_skill_proposal(proposal)
        except SkillProposalNotFoundError:
            print(f"Proposal '{sub_arg}' not found.")
        return True

    if subcmd in ("list-proposals", "list_proposals"):
        if ctx.skill_proposal_manager is None:
            print("Skill proposal system not available.")
            return True
        return _skill_proposals_list(ctx)

    if subcmd == "delete":
        if ctx.skill_proposal_manager is None:
            print("Skill proposal system not available.")
            return True
        if not sub_arg:
            print("Usage: /skills delete <name>")
            return True
        try:
            result = ctx.skill_proposal_manager.delete_skill(sub_arg)
            print(result)
            # Refresh skills loader.
            ctx.skills_loader.discover_skills()
        except SkillFileError as exc:
            print(str(exc))
        return True

    print(f"Unknown skills subcommand: {subcmd}")
    print("Usage: /skills [list|show|propose|approve|reject|review|list-proposals|delete]")
    return True


def _skills_list(ctx: _ReplContext) -> bool:
    """List all discovered skills.

    Args:
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    skills = ctx.skills_loader.list_skills()
    if not skills:
        print("No skills discovered.")
        # Also show any pending proposals if available.
        if ctx.skill_proposal_manager is not None:
            pending = ctx.skill_proposal_manager.list_pending()
            if pending:
                print(f"  ({len(pending)} pending proposal(s) — use /skills list-proposals to view)")
        return True

    print("\nSkills:")
    for skill in skills:
        triggers = ", ".join(skill.triggers) if skill.triggers else ""
        print(f"  {skill.name}: {skill.description}")
        if triggers:
            print(f"    triggers: {triggers}")
    print()

    # Show pending proposal count if any.
    if ctx.skill_proposal_manager is not None:
        pending = ctx.skill_proposal_manager.list_pending()
        if pending:
            print(f"  ({len(pending)} pending proposal(s) — use /skills list-proposals to view)")

    return True


def _skill_proposals_list(ctx: _ReplContext) -> bool:
    """List pending skill proposals.

    Args:
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    mgr = ctx.skill_proposal_manager
    if mgr is None:
        print("Skill proposal system not available.")
        return True

    pending = mgr.list_pending()
    if not pending:
        print("No pending skill proposals.")
        return True

    print(f"\nPending skill proposals ({len(pending)}):")
    for p in pending:
        pid = p.get("id", "?")
        name = p.get("name", "?")
        desc = p.get("description", "")
        timestamp = p.get("timestamp", "")
        preview = desc[:60] if desc else f"({name})"
        if len(preview) > 60:
            preview += "..."
        print(f"  {pid}  [{timestamp}]  {preview}")
    print()
    return True


def _print_skill_proposal(proposal: dict) -> None:
    """Pretty-print a single skill proposal.

    Args:
        proposal: The proposal dict to display.
    """


# ---------------------------------------------------------------------------
# Session command handler
# ---------------------------------------------------------------------------


def _handle_session_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /session command — show or clear session memory contents.

    Usage:
        ``/session`` — show session memory info and tool history.
        ``/session clear`` — clear all stored session memory data.

    Args:
        parts: The split command parts (``["/session", ...]``).
        ctx: The REPL context containing shared state.

    Returns:
        True to continue the REPL.
    """
    mem = ctx.session_memory
    if mem is None:
        print(f"{_YELLOW}⚠{_RESET} Session memory not available.")
        return True

    # Check for subcommand
    if len(parts) > 1 and parts[1].strip():
        subcmd = parts[1].strip().lower()
        if subcmd == "clear":
            mem.clear()
            print(f"{_GREEN}✓{_RESET} Session memory cleared.")
            return True
        print(f"{_ORANGE}Usage:{_RESET} /session [clear]")
        return True

    # ── Display session memory info ────────────────────────────────────
    print(f"\n{_RED}{_BOLD}╔═══════════════════════════════════════╗{_RESET}")
    print(f"{_RED}{_BOLD}║       SESSION MEMORY                 ║{_RESET}")
    print(f"{_RED}{_BOLD}╚═══════════════════════════════════════╝{_RESET}")

    # Temp dir path.
    print(f"  {_AMBER}📁{_RESET} {_BOLD}Temp dir:{_RESET}  {mem.tmp_dir}")

    # Check if closed (should not happen during normal use).
    if mem._closed:
        print(f"  {_RED}✖{_RESET} Session memory is closed (will not persist).")
        return True

    # Show all stored keys.
    all_keys = mem.keys()
    if not all_keys:
        print(f"  {_GRAY}No data stored in session memory.{_RESET}")
        return True

    print(f"  {_GRAY}Keys:{_RESET}       {', '.join(all_keys)}")

    # ── Tool history details ───────────────────────────────────────────
    tool_history = mem.load("tool_history", [])
    if not tool_history:
        print(f"\n  {_YELLOW}⊘{_RESET} {_BOLD}Tool history:{_RESET} empty")
    else:
        print(f"\n  {_GREEN}⊘{_RESET} {_BOLD}Tool history:{_RESET} {len(tool_history)} entries")
        # Show the first few and last few entries.
        max_head = 8
        max_tail = 4
        total = len(tool_history)

        if total <= max_head + max_tail:
            # Show all entries.
            for idx, entry in enumerate(tool_history):
                tool_name = entry.get("tool_name", "?")
                preview = entry.get("result_preview", "")
                display = preview[:80]
                if len(preview) > 80:
                    display += "..."
                print(f"  {_GRAY}  {idx+1}.{_RESET} [{tool_name}] {display}")
        else:
            # Show first max_head, separator, last max_tail.
            for idx in range(max_head):
                entry = tool_history[idx]
                tool_name = entry.get("tool_name", "?")
                preview = entry.get("result_preview", "")
                display = preview[:80]
                if len(preview) > 80:
                    display += "..."
                print(f"  {_GRAY}  {idx+1}.{_RESET} [{tool_name}] {display}")

            hidden = total - max_head - max_tail
            print(f"  {_GRAY}     ... ({hidden} more entries){_RESET}")

            for idx in range(total - max_tail, total):
                entry = tool_history[idx]
                tool_name = entry.get("tool_name", "?")
                preview = entry.get("result_preview", "")
                display = preview[:80]
                if len(preview) > 80:
                    display += "..."
                print(f"  {_GRAY}  {idx+1}.{_RESET} [{tool_name}] {display}")

    # ── Footer with clear hint ─────────────────────────────────────────
    print(f"\n  {_GRAY}Use /session clear to reset stored memory.{_RESET}")
    print()
    return True


# ---------------------------------------------------------------------------
# Nudge command handler
# ---------------------------------------------------------------------------


def _handle_nudge_command(ctx: _ReplContext) -> bool:
    """Handle /nudge command — show current nudges.

    Args:
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    if ctx.nudge_engine is None:
        print("Nudge system not available.")
        return True

    nudges = ctx.nudge_engine.get_nudges()
    if not nudges:
        print("No pending nudges — everything looks good!")
        return True

    print("\n--- Nudges ---")
    for nudge in nudges:
        print(f"  - {nudge}")
    print()
    return True


# ---------------------------------------------------------------------------
# Improve command handler
# ---------------------------------------------------------------------------


def _handle_improve_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /improve slash command and its subcommands.

    Subcommands:
        - ``/improve`` or ``/improve list`` — list pending proposals.
        - ``/improve propose <target> <content>`` — create a new proposal.
        - ``/improve approve [id]`` — approve and apply a proposal.
        - ``/improve reject [id]`` — reject a proposal.
        - ``/improve review [id]`` — show full details of a proposal.

    Args:
        parts: The split command parts (``["/improve", ...]``).
        ctx: The REPL context containing shared state.

    Returns:
        True to continue the REPL.
    """
    if ctx.improvement_proposal_manager is None:
        print("Improvement proposal system not available.")
        return True

    mgr = ctx.improvement_proposal_manager

    if len(parts) < 2 or not parts[1].strip():
        return _improve_list(ctx, mgr)

    sub_parts = parts[1].strip().split(maxsplit=1)
    subcmd = sub_parts[0].lower()
    sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""

    if subcmd == "list":
        return _improve_list(ctx, mgr)

    if subcmd == "propose":
        if not sub_arg:
            print("Usage: /improve propose <target> <content>")
            print(f"  Targets: SOUL.md, GENERAL.md, USER.md, MEMORY.md")
            return True
        # Parse target and content from sub_arg.
        propose_parts = sub_arg.split(maxsplit=1)
        if len(propose_parts) < 2:
            print("Usage: /improve propose <target> <content>")
            return True
        raw_target = propose_parts[0].strip()
        # Normalize: uppercase name + lowercase .md extension.
        if "." in raw_target:
            name_part = raw_target.rsplit(".", 1)[0].upper()
        else:
            name_part = raw_target.upper()
        target = name_part + ".md"
        content = propose_parts[1]
        try:
            proposal = mgr.propose(content=content, target=target)
            print(
                f"Improvement proposal {proposal['id']} created for {proposal['target']}. "
                f"Run `/improve approve {proposal['id']}` to apply it."
            )
        except InvalidTargetError as exc:
            print(str(exc))
        except ImprovementError as exc:
            print(f"Failed to create proposal: {exc}")
        return True

    if subcmd == "approve":
        if not sub_arg:
            pending = mgr.list_pending()
            if not pending:
                print("No pending improvement proposals to approve.")
                return True
            if len(pending) > 1:
                print("Multiple pending proposals. Specify an ID: /improve approve <id>")
                return _improve_list(ctx, mgr)
            sub_arg = pending[0]["id"]
        try:
            proposal = mgr.approve(sub_arg)
            print(
                f"Proposal {proposal['id']} approved and applied to {proposal['target']}."
            )
        except ImprovementProposalNotFoundError:
            print(f"Proposal '{sub_arg}' not found.")
        except ImprovementProposalInvalidStatusError as exc:
            print(str(exc))
        except ImprovementError as exc:
            print(f"Failed to approve: {exc}")
        return True

    if subcmd == "reject":
        if not sub_arg:
            pending = mgr.list_pending()
            if not pending:
                print("No pending improvement proposals to reject.")
                return True
            if len(pending) > 1:
                print("Multiple pending proposals. Specify an ID: /improve reject <id>")
                return _improve_list(ctx, mgr)
            sub_arg = pending[0]["id"]
        try:
            proposal = mgr.reject(sub_arg)
            print(f"Proposal {proposal['id']} rejected.")
        except ImprovementProposalNotFoundError:
            print(f"Proposal '{sub_arg}' not found.")
        except ImprovementProposalInvalidStatusError as exc:
            print(str(exc))
        return True

    if subcmd == "review":
        if not sub_arg:
            print("Usage: /improve review <id>")
            return True
        try:
            proposal = mgr.get_proposal(sub_arg)
            _print_improve_proposal(proposal)
        except ImprovementProposalNotFoundError:
            print(f"Proposal '{sub_arg}' not found.")
        return True

    print(f"Unknown improve subcommand: {subcmd}")
    print("Usage: /improve [list|propose|approve|reject|review]")
    return True


def _improve_list(ctx: _ReplContext, mgr: ImprovementProposalManager) -> bool:
    """List pending improvement proposals.

    Args:
        ctx: The REPL context.
        mgr: The ImprovementProposalManager instance.

    Returns:
        True to continue the REPL.
    """
    pending = mgr.list_pending()
    if not pending:
        print("No pending improvement proposals.")
        return True

    print(f"\nPending improvement proposals ({len(pending)}):")
    for p in pending:
        pid = p.get("id", "?")
        target = p.get("target", "?")
        desc = p.get("description", "")
        timestamp = p.get("timestamp", "")
        preview = desc[:60]
        if len(desc) > 60:
            preview += "..."
        print(f"  {pid}  [{target}]  [{timestamp}]  {preview}")
    print()
    return True


def _print_improve_proposal(proposal: dict) -> None:
    """Pretty-print a single improvement proposal.

    Args:
        proposal: The proposal dict to display.
    """
    print(f"\n--- Improvement Proposal: {proposal.get('id', '?')} ---")
    print(f"Target:      {proposal.get('target', '?')}")
    print(f"Status:      {proposal.get('status', '?')}")
    print(f"Proposed by: {proposal.get('proposed_by', '?')}")
    print(f"Timestamp:   {proposal.get('timestamp', '?')}")
    desc = proposal.get('description', '')
    if desc:
        print(f"Description: {desc}")
    print(f"\nContent:\n{proposal.get('content', '')}")
    print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

    print(f"\n--- Skill Proposal: {proposal.get('id', '?')} ---")
    print(f"Name:        {proposal.get('name', '?')}")
    print(f"Status:      {proposal.get('status', '?')}")
    print(f"Proposed by: {proposal.get('proposed_by', '?')}")
    print(f"Timestamp:   {proposal.get('timestamp', '?')}")
    desc = proposal.get('description', '')
    if desc:
        print(f"Description: {desc}")
    triggers = proposal.get('triggers', [])
    if triggers:
        print(f"Triggers:    {', '.join(triggers)}")
    print(f"\nContent:\n{proposal.get('content', '')}")
    print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        An :class:`argparse.ArgumentParser` configured with all
        supported flags.
    """
    parser = argparse.ArgumentParser(
        prog="local-cli",
        description="Local-first AI coding agent powered by Ollama.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Ollama model to use (default: qwen3.5:9b).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=None,
        help="Enable debug output.",
    )
    parser.add_argument(
        "--rag",
        action="store_true",
        default=None,
        help="Enable RAG (retrieval-augmented generation) engine.",
    )
    parser.add_argument(
        "--rag-path",
        type=str,
        default=None,
        help="Directory to index for RAG (default: current directory).",
    )
    parser.add_argument(
        "--rag-topk",
        type=int,
        default=None,
        help="Number of RAG results per query (default: 5).",
    )
    parser.add_argument(
        "--rag-model",
        type=str,
        default=None,
        help="Embedding model for RAG (default: all-minilm).",
    )
    parser.add_argument(
        "--select-model",
        action="store_true",
        default=None,
        help="Interactively select a model from available Ollama models at startup.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Set the LLM provider (ollama or claude).",
    )
    parser.add_argument(
        "--brain-model",
        type=str,
        default=None,
        help="Set the orchestrator brain model.",
    )
    parser.add_argument(
        "--registry-file",
        type=str,
        default=None,
        help="Path to model registry JSON file.",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=None,
        help="Context window size in tokens (default: model-specific).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature (default: model-specific).",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=None,
        help="Top-p (nucleus) sampling threshold (default: model-specific).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Top-k sampling limit (default: model-specific).",
    )
    parser.add_argument(
        "--think-mode",
        action="store_true",
        default=None,
        help="Enable extended thinking mode for supported models.",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        default=False,
        help="Run in JSON-line server mode (for desktop GUI).",
    )
    parser.add_argument(
        "--web-monitor",
        action="store_true",
        default=False,
        help="Run web-based agent monitor (browser dashboard with SSE streaming).",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=7070,
        help="Port for --web-monitor (default: 7070).",
    )
    parser.add_argument(
        "--bench",
        action="store_true",
        default=False,
        help="Run quick benchmark (speed, knowledge, tool-calling).",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        default=False,
        help="Check for updates and pull the latest version.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        default=False,
        help="Start in plan mode with plan commands available.",
    )
    parser.add_argument(
        "--ideate",
        action="store_true",
        default=False,
        help="Start directly in ideation (brainstorming) mode.",
    )
    parser.add_argument(
        "--init-agents",
        action="store_true",
        default=False,
        help="Create the .agents/ directory with default template files (SOUL.md, USER.md, etc.) and exit.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        dest="auto_approve",
        action="store_true",
        default=None,
        help="Auto-approve risky commands (skip confirmation prompts).",
    )
    return parser


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------


_AGENT_NAME = "Buffy"


def _show_agent_status_box(ctx: _ReplContext) -> None:
    """Display agent status info (model, ollama, provider, identity) in a colored box.

    Shows the same identity/status information as the welcome banner,
    formatted with a boxed layout and ANSI colors.

    Args:
        ctx: The REPL context.
    """
    tool_names = ", ".join(t.name for t in ctx.tools)

    # ── Box header ────────────────────────────────────────────────────
    print(f"  {_RED}{_BOLD}╔══════════════════════════════════════════════╗{_RESET}")
    print(f"  {_RED}{_BOLD}║              AGENT STATUS                    ║{_RESET}")
    print(f"  {_RED}{_BOLD}╚══════════════════════════════════════════════╝{_RESET}")

    # ── Model ─────────────────────────────────────────────────────────
    print(f"  {_AMBER}⚡{_RESET} {_BOLD}Model:{_RESET}     {ctx.config.model}")

    # ── Ollama status ─────────────────────────────────────────────────
    try:
        version_info = ctx.client.get_version()
        version = version_info.get("version", "unknown")
        print(f"  {_GREEN}●{_RESET} {_BOLD}Ollama:{_RESET}     connected (v{version})")
    except OllamaConnectionError:
        print(f"  {_RED}●{_RESET} {_BOLD}Ollama:{_RESET}     {_RED}DISCONNECTED{_RESET}")

    # ── Provider ──────────────────────────────────────────────────────
    if ctx.orchestrator is not None:
        prov = ctx.orchestrator.get_active_provider_name()
        prov_color = _GREEN if prov == "ollama" else _YELLOW
        print(f"  {prov_color}◆{_RESET} {_BOLD}Provider:{_RESET}   {prov}")

    # ── Tools ─────────────────────────────────────────────────────────
    print(f"  {_ORANGE}⊘{_RESET} {_BOLD}Tools:{_RESET}      {tool_names}")

    # ── Identity ──────────────────────────────────────────────────────
    if ctx.identity_loader is not None:
        identity_status = ctx.identity_loader.get_status()
        loaded = [name for name, exists in identity_status.items() if exists]
        if loaded:
            print(f"  {_YELLOW}◆{_RESET} {_BOLD}Identity:{_RESET}   {', '.join(loaded)}")

    # ── Mode ──────────────────────────────────────────────────────────
    mode_color = _CYAN if ctx.current_mode == "agent" else _ORANGE
    print(f"  {mode_color}⎔{_RESET} {_BOLD}Mode:{_RESET}      {ctx.current_mode}")

    # ── Active plan ───────────────────────────────────────────────────
    if ctx.active_plan_id is not None:
        print(f"  {_ORANGE}⊘{_RESET} {_BOLD}Plan:{_RESET}      {ctx.active_plan_id}")

    # ── RAG ───────────────────────────────────────────────────────────
    if ctx.rag_engine is not None:
        print(f"  {_GREEN}◆{_RESET} {_BOLD}RAG:{_RESET}       enabled")

    # ── Bottom separator ─────────────────────────────────────────────
    print(f"  {_GRAY}{'═' * 42}{_RESET}")


def _show_agent_ready(ctx: _ReplContext) -> None:
    """Display the agent name with a ready/status indicator.

    Prints the agent name in bold with a green connection dot and
    a small contextual status line above the ``You>`` prompt.

    Args:
        ctx: The REPL context.
    """
    # Get message count
    msg_count = sum(1 for m in ctx.messages if m.get("role") == "user")
    mode_label = "IDEATE" if ctx.current_mode == "ideate" else "AGENT"
    mode_color = _CYAN if ctx.current_mode == "agent" else _ORANGE

    print(
        f"  {_AMBER}{_BOLD}{_AGENT_NAME}{_RESET}  "
        f"{_GREEN}●{_RESET} {_GRAY}Ready{_RESET}  "
        f"{mode_color}◈{_RESET} {mode_label}  "
        f"{_GRAY}💬 {msg_count}{_RESET}"
    )


def run_repl(
    config: Config,
    client: OllamaClient,
    tools: list[Tool],
    identity_loader: IdentityLoader | None = None,
    memory_proposal_manager: MemoryProposalManager | None = None,
    skill_proposal_manager: SkillProposalManager | None = None,
    improvement_proposal_manager: ImprovementProposalManager | None = None,
    nudge_engine: NudgeEngine | None = None,
    rag_engine: object | None = None,
    rag_topk: int = 5,
    orchestrator: object | None = None,
    model_manager: object | None = None,
    sub_agent_runner: object | None = None,
    plan_manager: PlanManager | None = None,
    knowledge_store: KnowledgeStore | None = None,
    skills_loader: SkillsLoader | None = None,
    ideation_engine: IdeationEngine | None = None,
    initial_mode: str = "agent",
) -> None:
    """Run the interactive REPL loop.

    Reads user input line-by-line, detects slash commands, and forwards
    natural-language prompts to :func:`agent_loop` for LLM processing.
    Supports multiple modes: ``agent`` (default tool-using mode) and
    ``ideate`` (tool-free brainstorming mode).

    Uses ``readline`` for line editing and input history (automatically
    available via the import at module level).

    Args:
        config: Application configuration.
        client: An :class:`OllamaClient` instance.
        tools: A list of :class:`Tool` instances available to the agent.
        identity_loader: Optional :class:`IdentityLoader` for identity
            file loading and injection (SOUL.md, USER.md, etc.).
        memory_proposal_manager: Optional :class:`MemoryProposalManager`
            for memory proposal management.
        rag_engine: Optional :class:`RAGEngine` for context augmentation.
        rag_topk: Number of RAG results per query.
        orchestrator: Optional :class:`Orchestrator` for provider/brain
            management and task routing.
        model_manager: Optional :class:`ModelManager` for model
            install/delete operations.
        sub_agent_runner: Optional :class:`SubAgentRunner` for background
            agent status queries via the ``/agents`` command.
        plan_manager: Optional :class:`PlanManager` for plan CRUD.
        knowledge_store: Optional :class:`KnowledgeStore` for persistent
            knowledge items.
        skills_loader: Optional :class:`SkillsLoader` for skill
            auto-discovery and contextual injection.
        ideation_engine: Optional :class:`IdeationEngine` for tool-free
            brainstorming mode.
        initial_mode: Starting REPL mode (``"agent"`` or ``"ideate"``).
    """
    # Print welcome banner with colors.
    tool_names = ", ".join(t.name for t in tools)

    # ── Banner header ────────────────────────────────────────────────
    print(f"{_RED}{_BOLD}╔══════════════════════════════════════════════╗{_RESET}")
    print(f"{_RED}{_BOLD}║        local-cli v{__version__:<20}║{_RESET}")
    print(f"{_RED}{_BOLD}╚══════════════════════════════════════════════╝{_RESET}")

    # ── Model ────────────────────────────────────────────────────────
    print(f"{_AMBER}⚡{_RESET} {_BOLD}Model:{_RESET}   {config.model}")

    # ── Ollama status ────────────────────────────────────────────────
    try:
        version_info = client.get_version()
        version = version_info.get("version", "unknown")
        print(f"{_GREEN}●{_RESET} {_BOLD}Ollama:{_RESET}   connected (v{version})")
    except OllamaConnectionError:
        print(f"{_RED}●{_RESET} {_BOLD}Ollama:{_RESET}   {_RED}DISCONNECTED{_RESET} — is ollama running?")

    # ── Provider ─────────────────────────────────────────────────────
    if orchestrator is not None:
        prov = orchestrator.get_active_provider_name()
        prov_color = _GREEN if prov == "ollama" else _YELLOW
        print(f"{prov_color}◆{_RESET} {_BOLD}Provider:{_RESET} {prov}")

    # ── Tools ────────────────────────────────────────────────────────
    print(f"{_ORANGE}⊘{_RESET} {_BOLD}Tools:{_RESET}    {tool_names}")

    # ── Identity ─────────────────────────────────────────────────────
    if identity_loader is not None:
        identity_status = identity_loader.get_status()
        loaded = [name for name, exists in identity_status.items() if exists]
        if loaded:
            print(f"{_YELLOW}◆{_RESET} {_BOLD}Identity:{_RESET} {', '.join(loaded)}")
        else:
            print(f"{_GRAY}◇{_RESET} Identity: none (run /identity for details){_RESET}")

    # ── RAG ──────────────────────────────────────────────────────────
    if rag_engine is not None:
        print(f"{_GREEN}◆{_RESET} {_BOLD}RAG:{_RESET}     enabled")

    # ── Mode ─────────────────────────────────────────────────────────
    print(f"{_ORANGE}⎔{_RESET} {_BOLD}Mode:{_RESET}    {initial_mode}")

    # ── Footer ──────────────────────────────────────────────────────
    print(f"{_GRAY}Type /help for commands, /exit to quit.{_RESET}\n")

    # Show startup nudges if available.
    if nudge_engine is not None:
        nudges = nudge_engine.get_nudges()
        if nudges:
            print(f"  {_YELLOW}── Nudges ──{_RESET}")
            for nudge in nudges:
                print(f"    {_ORANGE}◆{_RESET} {nudge}")
            print()

    # Load identity content and build system prompt with identity injection.
    identity_content = None
    if identity_loader is not None:
        identity_content = identity_loader.load_all()

    # Build a dict for build_system_prompt's identity parameter.
    identity_dict = None
    if identity_content is not None and identity_content.has_any():
        identity_dict = {
            "soul": identity_content.soul,
            "user_merged": identity_content.user_merged,
            "general": identity_content.general,
            "agents": identity_content.agents,
            "memory": identity_content.memory,
        }

    # Build system prompt with tool descriptions + identity injection.
    system_prompt = build_system_prompt(tools, identity=identity_dict)

    # Conversation history (persists across the session).
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]

    # Session manager for /save command.
    session_manager = SessionManager(config.state_dir)

    # Build the REPL context for slash commands.
    ctx = _ReplContext(
        config=config,
        client=client,
        tools=tools,
        messages=messages,
        session_manager=session_manager,
        identity_loader=identity_loader,
        memory_proposal_manager=memory_proposal_manager,
        skill_proposal_manager=skill_proposal_manager,
        improvement_proposal_manager=improvement_proposal_manager,
        nudge_engine=nudge_engine,
        system_prompt=system_prompt,
        rag_engine=rag_engine,
        rag_topk=rag_topk,
        orchestrator=orchestrator,
        model_manager=model_manager,
        sub_agent_runner=sub_agent_runner,
        plan_manager=plan_manager,
        knowledge_store=knowledge_store,
        skills_loader=skills_loader,
        ideation_engine=ideation_engine,
    )

    # Create session-scoped temporary memory (auto-deletes on exit via atexit).
    ctx.session_memory = SessionMemory()

    # Propagate session_memory to AgentTool so sub-agents also persist
    # tool-call progress to the same session store.
    for tool in tools:
        if hasattr(tool, "session_memory"):
            tool.session_memory = ctx.session_memory

    # Set initial mode.
    ctx.current_mode = initial_mode
    if initial_mode == "ideate" and ideation_engine is not None:
        if not ideation_engine.has_session:
            ideation_engine.start_session()
        print("Starting in ideation mode. Type /ideate exit to return.\n")

    while True:
        # ── Agent ready indicator ───────────────────────────────────────────
        # Show the agent name and status before the prompt.
        _show_agent_ready(ctx)

        # Read user input with mode-aware prompt.
        prompt_label = f"{_ORANGE}Ideate{_RESET}> " if ctx.current_mode == "ideate" else f"{_RED}You{_RESET}> "
        try:
            user_input = input(prompt_label)
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        # Skip empty input.
        stripped = user_input.strip()
        if not stripped:
            continue

        # Handle slash commands (available in all modes).
        if stripped.startswith("/"):
            should_continue = _handle_slash_command(stripped, ctx)
            if not should_continue:
                break
            continue

        # -- Ideation mode --------------------------------------------------
        if ctx.current_mode == "ideate":
            if ctx.ideation_engine is not None:
                try:
                    ctx.ideation_engine.chat_turn(
                        user_input=stripped,
                        model=ctx.config.model,
                    )
                except KeyboardInterrupt:
                    print("\nInterrupted.")
                except Exception as exc:
                    sys.stderr.write(f"Ideation error: {exc}\n")
            else:
                print("Ideation engine not available. Use /ideate exit.")
            continue

        # -- Agent mode -----------------------------------------------------

        # Inject skills context if skills match the user input.
        if ctx.skills_loader is not None:
            matching_skills = ctx.skills_loader.get_matching_skills(stripped)
            for skill in matching_skills:
                messages.append({
                    "role": "system",
                    "content": (
                        f"--- SKILL: {skill.name} ---\n"
                        f"{skill.content}\n"
                        f"--- END SKILL ---"
                    ),
                })

        # Fast-mode heuristic: suggest plan for complex requests.
        if (
            ctx.plan_manager is not None
            and ctx.active_plan_id is None
            and _is_complex_request(stripped)
        ):
            print(
                "This looks complex. Consider creating a plan first "
                "with /plan create <title>."
            )

        # Augment prompt with RAG context if available.
        prompt_content = stripped
        if ctx.rag_engine is not None:
            try:
                prompt_content = ctx.rag_engine.augment_prompt(
                    stripped, top_k=ctx.rag_topk,
                )
            except Exception:
                # RAG failure is non-fatal; fall back to the raw prompt.
                pass

        # Inject active plan context if a plan is active.
        if ctx.active_plan_id is not None and ctx.plan_manager is not None:
            try:
                plan_content = ctx.plan_manager.get_plan_content(
                    ctx.active_plan_id,
                )
                plan_msg = build_plan_context(plan_content)
                messages.append(plan_msg)
            except PlanError:
                # Plan read failure is non-fatal; skip injection.
                pass

        # Build user message and add to history.
        messages.append({"role": "user", "content": prompt_content})

        # ── Visual turn separator: agent name + line ───────────────────────
        print(f"{_AMBER}{_BOLD}{_AGENT_NAME}{_RESET} {_GREEN}▶{_RESET} {_GRAY}Processing...{_RESET}")
        print(f"{_RED}{_BOLD}{'─' * 54}{_RESET}")

        # Build merged inference options: defaults < presets < user config.
        default_options: dict = {"num_ctx": 8192}
        preset_options = get_model_preset(config.model)
        user_options: dict = {"num_ctx": config.num_ctx}
        if config.temperature is not None:
            user_options["temperature"] = config.temperature
        if config.top_p is not None:
            user_options["top_p"] = config.top_p
        if config.top_k is not None:
            user_options["top_k"] = config.top_k
        inference_options = {**default_options, **preset_options, **user_options}

        # Determine think mode for models that support it.
        family = get_model_family(config.model)
        think: bool | None = None
        if family in SUPPORTS_THINKING:
            think = True if config.think_mode else False

        # Run the agent loop (streams response to stdout).
        try:
            agent_loop(
                client=client,
                model=config.model,
                tools=tools,
                messages=messages,
                debug=config.debug,
                options=inference_options,
                think=think,
                session_memory=ctx.session_memory,
            )
        except KeyboardInterrupt:
            print("\nInterrupted.")
        except Exception as exc:
            sys.stderr.write(f"Error: {exc}\n")

        # ── Turn footer: status box + nudges + separator ──────────────────
        # Show the agent status box after each turn.
        _show_agent_status_box(ctx)

        # Show nudges after status box.
        if ctx.nudge_engine is not None:
            nudges = ctx.nudge_engine.get_nudges()
            if nudges:
                print(f"  {_YELLOW}── Nudges ──{_RESET}")
                for nudge in nudges:
                    print(f"    {_ORANGE}◆{_RESET} {nudge}")
                print()

        # ── Turn separator line ──────────────────────────────────────────────
        print(f"{_RED}{_BOLD}{'─' * 54}{_RESET}")

        # ── Auto-session logging ────────────────────────────────────────────
        # Save every turn to a log file for debugging.
        log_path = _write_turn_log(messages)
        if log_path and config.debug:
            sys.stderr.write(f"[debug] Turn logged: {log_path}\n")


# ---------------------------------------------------------------------------
# Session logging (auto-save every turn)
# ---------------------------------------------------------------------------


_LOG_DIR = ".agents/logs"


def _write_turn_log(
    messages: list[dict],
    log_dir: str = _LOG_DIR,
) -> str | None:
    """Append the latest turn of conversation to a session log file.

    The log is written to ``.agents/logs/<session_timestamp>.jsonl``.
    Each line is a JSON object with timestamp, role, and a truncated
    content preview.

    Args:
        messages: The full conversation message list.
        log_dir: Directory for log files (default ``.agents/logs``).

    Returns:
        The log file path, or ``None`` on failure.
    """
    try:
        log_path = Path(log_dir).expanduser()
        log_path.mkdir(parents=True, exist_ok=True)

        # Use a single session log file per run.
        session_ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_file = log_path / f"session-{session_ts}.jsonl"

        # Get the last few messages that were just added.
        # Only log user and assistant messages (not system).
        new_msgs = [
            m for m in messages
            if m.get("role") in ("user", "assistant")
        ]
        if not new_msgs:
            return None

        with open(str(log_file), "a", encoding="utf-8") as fh:
            for msg in new_msgs[-2:]:  # Log at most the last user+assistant turn
                entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "role": msg.get("role"),
                    "content_preview": msg.get("content", "")[:200],
                    "tool_calls": [
                        tc.get("function", {}).get("name", "")
                        for tc in msg.get("tool_calls", [])
                    ] if msg.get("tool_calls") else None,
                }
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return str(log_file)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Log command handler
# ---------------------------------------------------------------------------


def _handle_log_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /log command — show recent session logs.

    Usage:
        ``/log`` — list available log files and show the latest 5 entries.
        ``/log <N>`` — show the last N entries from the latest log file.
        ``/log list`` — list all available log files.
        ``/log show <filename>`` — show entries from a specific log file.

    Args:
        parts: The split command parts (``["/log", ...]``).
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    log_dir = ctx.config.agents_dir + "/logs" if hasattr(ctx.config, "agents_dir") else _LOG_DIR
    log_path = Path(log_dir).expanduser()

    if not log_path.is_dir():
        print(f"{_YELLOW}No log files found.{_RESET}")
        print(f"{_GRAY}Session logs are created automatically each time you send a prompt.{_RESET}")
        return True

    # Collect log files sorted by newest first.
    try:
        log_files = sorted(
            [f for f in log_path.iterdir() if f.suffix == ".jsonl"],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        print(f"{_RED}Failed to read log directory.{_RESET}")
        return True

    if not log_files:
        print(f"{_YELLOW}No log files found.{_RESET}")
        return True

    subcmd = parts[1].strip().lower() if len(parts) > 1 and parts[1].strip() else ""

    # /log list — list all available log files
    if subcmd == "list":
        print(f"\n{_AMBER}{_BOLD}Available log files:{_RESET}")
        for f in log_files:
            size = f.stat().st_size
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"  {_GREEN}{f.name}{_RESET}  {_GRAY}({size:,} bytes, {mtime}){_RESET}")
        print(f"\n{_GRAY}Total: {len(log_files)} log file(s){_RESET}")
        return True

    # /log show <filename> — show entries from a specific file
    if subcmd == "show":
        sub_parts = parts[1].strip().split(maxsplit=1)
        filename = sub_parts[1].strip() if len(sub_parts) > 1 else ""
        if not filename:
            print(f"{_ORANGE}Usage:{_RESET} /log show <filename>")
            return True
        target = log_path / filename
        if not target.exists():
            print(f"{_RED}Log file '{filename}' not found.{_RESET}")
            return True
        log_files = [target]

    # Determine how many entries to show.
    try:
        n = int(subcmd) if subcmd.isdigit() else 5
    except (ValueError, AttributeError):
        n = 5

    # Read from the latest log file.
    latest = log_files[0]
    try:
        lines = latest.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        print(f"{_RED}Failed to read log file.{_RESET}")
        return True

    if not lines:
        print(f"{_YELLOW}Log file is empty.{_RESET}")
        return True

    n = min(n, len(lines))
    recent = lines[-n:]

    print(f"\n{_RED}{_BOLD}╔═══════════════════════════════════════╗{_RESET}")
    print(f"{_RED}{_BOLD}║       SESSION LOG                   ║{_RESET}")
    print(f"{_RED}{_BOLD}╚═══════════════════════════════════════╝{_RESET}")
    print(f"{_GRAY}File: {latest.name} ({len(lines)} entries, showing last {n}){_RESET}")
    print()

    for line in recent:
        try:
            entry = json.loads(line)
            ts = entry.get("ts", "?")[11:19]  # HH:MM:SS
            role = entry.get("role", "?")
            preview = entry.get("content_preview", "")
            tool_calls = entry.get("tool_calls")

            role_color = _GREEN if role == "assistant" else _AMBER
            role_icon = "◀" if role == "user" else "▶"

            print(f"  {_GRAY}[{ts}]{_RESET} {role_color}{role_icon} {role:<10}{_RESET} {preview[:80]}")
            if tool_calls:
                print(f"  {_GRAY}     tools: {', '.join(tool_calls)}{_RESET}")
        except (json.JSONDecodeError, ValueError):
            continue

    print()
    return True


# ---------------------------------------------------------------------------
# Heal command handler
# ---------------------------------------------------------------------------


def _handle_heal_command(ctx: _ReplContext) -> bool:
    """Handle /heal command — scan and self-heal the codebase.

    Runs a syntax and import health scan on all Python files, reports
    issues found, and attempts auto-fixes with git checkpoint safety.

    Args:
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    print(f"\n{_RED}{_BOLD}╔═══════════════════════════════════════╗{_RESET}")
    print(f"{_RED}{_BOLD}║       SELF-HEAL ENGINE              ║{_RESET}")
    print(f"{_RED}{_BOLD}╚═══════════════════════════════════════╝{_RESET}\n")

    engine = SelfHealEngine()

    # Phase 1: Scan
    print(f"{_AMBER}Scanning codebase for issues...{_RESET}")
    issues = engine.scan()

    if not issues:
        print(f"{_GREEN}✓ No issues found. Your codebase looks healthy!{_RESET}\n")
        return True

    print(f"\n{_RED}{_BOLD}Found {len(issues)} issue(s):{_RESET}")
    for i, issue in enumerate(issues, 1):
        severity_color = _RED if issue.severity == "error" else _YELLOW
        print(f"  {severity_color}{i}. [{issue.severity}]{_RESET} {issue.file_path}:{issue.line}")
        print(f"     {issue.description}")
        if issue.fix_suggestion:
            print(f"     {_GRAY}→ {issue.fix_suggestion}{_RESET}")

    # Phase 2: Attempt auto-fix
    fixable = [i for i in issues if i.severity == "error" and i.fix_suggestion]
    if fixable:
        print(f"\n{_ORANGE}Attempting auto-fix for {len(fixable)} issue(s)...{_RESET}")
        result = engine.heal(fixable, auto_fix=False)

        if result.checkpoint_tag:
            print(f"  {_GREEN}✓{_RESET} Pre-heal checkpoint: {result.checkpoint_tag}")

        if result.issues_fixed > 0:
            print(f"  {_GREEN}✓{_RESET} Fixed {result.issues_fixed} issue(s)")
        if result.issues_failed > 0:
            print(f"  {_RED}✖{_RESET} Failed to fix {result.issues_failed} issue(s)")

        # Phase 3: Validate
        print(f"\n{_AMBER}Running validation...{_RESET}")
        validation_errors = engine.validate()
        if not validation_errors:
            print(f"  {_GREEN}✓ Validation passed{_RESET}")
        else:
            print(f"  {_RED}✖ {len(validation_errors)} validation error(s):{_RESET}")
            for err in validation_errors:
                print(f"     - {err}")
    else:
        print(f"\n{_GRAY}No auto-fixable issues found. Review warnings manually.{_RESET}")

    print()
    return True


# ---------------------------------------------------------------------------
# Structure command handler
# ---------------------------------------------------------------------------


def _handle_structure_command(parts: list[str], ctx: _ReplContext) -> bool:
    """Handle /structure command — show project directory tree.

    Displays a colorised tree view of the current project structure.
    Optional depth parameter controls how many levels to show.

    Args:
        parts: The split command parts (``["/structure", ...]``).
        ctx: The REPL context.

    Returns:
        True to continue the REPL.
    """
    depth = 3
    if len(parts) > 1 and parts[1].strip():
        try:
            depth = int(parts[1].strip())
            depth = max(1, min(depth, 6))
        except ValueError:
            print(f"{_ORANGE}Usage:{_RESET} /structure [depth]")
            print(f"  {_GRAY}depth: directory depth level (1-6, default 3){_RESET}")
            return True

    print(f"\n{_RED}{_BOLD}╔═══════════════════════════════════════╗{_RESET}")
    print(f"{_RED}{_BOLD}║       PROJECT STRUCTURE              ║{_RESET}")
    print(f"{_RED}{_BOLD}╚═══════════════════════════════════════╝{_RESET}\n")

    tree = get_project_structure(max_depth=depth)
    print(tree)
    print()
    return True


# ----------------------------------------------------------------------
# Queue, Background, Stop, Interview command handlers
# ----------------------------------------------------------------------


def _handle_queue_command(parts: list[str]) -> bool:
    """Handle /queue command - queue command to run after current finishes."""
    from local_cli.stat import _CYAN, _RESET, get_controller
    
    ctrl = get_controller()
    
    if len(parts) < 2 or not parts[1].strip():
        print(f"Usage: /queue <command>")
        print(f"  Queue size: {ctrl.queue_size}")
        return True
    
    command = parts[1].strip()
    ctrl.queue_command(command)
    return True


def _handle_bg_command(parts: list[str]) -> bool:
    """Handle /bg command - run command in background mode."""
    from local_cli.stat import _CYAN, _GREEN, _RESET, get_controller
    
    ctrl = get_controller()
    
    if len(parts) < 2 or not parts[1].strip():
        print(f"Usage: /bg <command>")
        return True
    
    command = parts[1].strip()
    ctrl.start_background(command)
    return True


def _handle_stop_command() -> bool:
    """Handle /stop command - stop the running agent."""
    from local_cli.stat import _CYAN, _RED, _RESET, get_controller
    
    ctrl = get_controller()
    ctrl.request_stop()
    
    # Also set agent status
    status = get_status()
    if status.is_running:
        status.stop()
        print(f"{_RED}Agent stopped{_RESET}")
    else:
        print(f"No agent running")
    
    return True


def _handle_interview_command(parts: list[str]) -> bool:
    """Handle /interview command - start interview mode."""
    from local_cli.stat import _CYAN, _ORANGE, _RESET, get_controller
    
    ctrl = get_controller()
    project_path = None
    
    # Optional project path
    if len(parts) > 1 and parts[1].strip():
        project_path = parts[1].strip()
    
    intro = ctrl.start_interview(project_path)
    print(intro)
    return True
