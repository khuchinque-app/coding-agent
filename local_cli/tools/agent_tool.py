"""Agent tool for spawning independent sub-agents.

Allows the LLM to dynamically spawn sub-agents that execute tasks
autonomously with their own isolated context, tools, and provider
instance.  Analogous to Claude Code's ``Agent`` tool.

Unlike other tools (which use no-arg constructors), ``AgentTool``
requires runtime dependencies injected at construction time: the
:class:`~local_cli.sub_agent.SubAgentRunner`, a template
:class:`~local_cli.providers.base.LLMProvider`, the model name, and
the sub-agent tool list.
"""

import sys

from local_cli.providers.base import LLMProvider
from local_cli.session_memory import SessionMemory
from local_cli.spinner import ProgressBar
from local_cli.sub_agent import SubAgent, SubAgentResult, SubAgentRunner
from local_cli.tools.base import Tool

# ANSI helpers (keep in sync with local_cli.stat / local_cli.spinner)
_RESET = "\033[0m"
_BOLD = "\033[1m"
_AMBER = "\033[38;5;214m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_GRAY = "\033[90m"
_ORANGE = "\033[38;5;208m"


class AgentTool(Tool):
    """LLM-callable tool that spawns independent sub-agents.

    Each invocation creates a new :class:`~local_cli.sub_agent.SubAgent`
    with a **fresh** :class:`~local_cli.providers.base.LLMProvider`
    instance (for thread safety) and submits it to the
    :class:`~local_cli.sub_agent.SubAgentRunner`.

    Supports two execution modes:

    - **Foreground** (default): Blocks until the sub-agent completes and
      returns the formatted result.
    - **Background**: Returns immediately with the agent ID.  The result
      can be retrieved later via the runner.

    Args:
        runner: The :class:`SubAgentRunner` that manages concurrent
            sub-agent execution.
        provider: A template :class:`LLMProvider` instance used to
            determine the provider type and configuration.  This
            instance is **not** shared with sub-agents -- a fresh
            instance is created for each sub-agent.
        model: Model name to use for sub-agents (e.g. ``'qwen3:8b'``).
        sub_agent_tools: List of :class:`Tool` instances available to
            sub-agents.  Should **not** include ``AgentTool`` (prevents
            recursive spawning) or ``AskUserTool`` (prevents stdin
            blocking in silent threads).
    """

    def __init__(
        self,
        runner: SubAgentRunner,
        provider: LLMProvider,
        model: str,
        sub_agent_tools: list[Tool],
    ) -> None:
        self._runner = runner
        self._provider = provider
        self._model = model
        self._sub_agent_tools = sub_agent_tools
        self._session_memory: SessionMemory | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def session_memory(self) -> SessionMemory | None:
        """The session memory instance shared with sub-agents."""
        return self._session_memory

    @session_memory.setter
    def session_memory(self, value: SessionMemory | None) -> None:
        self._session_memory = value

    # ------------------------------------------------------------------
    # Tool interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "agent"

    @property
    def description(self) -> str:
        return (
            "Spawn an independent sub-agent to handle a task autonomously. "
            "The sub-agent runs with its own isolated context and has "
            "access to tools (bash, read, write, edit, glob, grep, "
            "web_fetch). Use this to delegate tasks that can be worked "
            "on independently. Provide a clear, detailed prompt so the "
            "sub-agent can work autonomously."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": (
                        "Short description of the task (3-5 words)."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Detailed task for the sub-agent to perform."
                    ),
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": (
                        "If true, run in background and return "
                        "immediately with an agent ID."
                    ),
                },
            },
            "required": ["description", "prompt"],
        }

    def execute(self, **kwargs: object) -> str:
        """Spawn a sub-agent to execute the given task.

        Creates a new :class:`SubAgent` with a fresh provider instance
        and submits it to the runner.  In foreground mode, blocks until
        the sub-agent completes and returns the formatted result.  In
        background mode, returns the agent ID immediately.

        During foreground execution, real-time visual feedback is printed
        to stderr: a delegation box (showing task description, model,
        and a prompt preview), a pulsing progress bar while the sub-agent
        works, and a completion box (showing status, duration, tool call
        count, and a result preview).

        Args:
            **kwargs: Must include ``description`` (str) and ``prompt``
                (str).  May include ``run_in_background`` (bool,
                default ``False``).

        Returns:
            The formatted sub-agent result string (foreground) or the
            agent ID string (background).
        """
        description = kwargs.get("description", "")
        if not isinstance(description, str) or not description.strip():
            return "Error: 'description' parameter is required and must be a non-empty string."

        prompt = kwargs.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            return "Error: 'prompt' parameter is required and must be a non-empty string."

        run_in_background = kwargs.get("run_in_background", False)
        if not isinstance(run_in_background, bool):
            run_in_background = False

        # Create a fresh provider instance for thread safety.
        try:
            fresh_provider = self._create_fresh_provider()
        except Exception as exc:
            return f"Error: failed to create provider for sub-agent: {exc}"

        sub_agent = SubAgent(
            provider=fresh_provider,
            model=self._model,
            tools=self._sub_agent_tools,
            prompt=prompt.strip(),
            description=description.strip(),
            session_memory=self._session_memory,
        )

        if run_in_background:
            agent_id = self._runner.submit_background(sub_agent)
            return (
                f"Sub-agent '{description.strip()}' started in background. "
                f"Agent ID: {agent_id}"
            )

        # ── Foreground execution with real-time visual feedback ──────

        # 1. Build a short prompt preview for the delegation box.
        prompt_preview = prompt.strip().replace("\n", " ").strip()
        if len(prompt_preview) > 70:
            prompt_preview = prompt_preview[:67] + "..."

        # 2. Print the delegation box (explains WHY the sub-agent is spawned).
        desc_stripped = description.strip()
        _print_delegation_box(desc_stripped, self._model, prompt_preview)

        # 3. Start a progress bar that shows elapsed time.
        bar = ProgressBar(f"Sub-agent: {desc_stripped}")
        bar.start()

        # 4. Run the sub-agent (blocks until completion).
        try:
            result = self._runner.submit(sub_agent)
        finally:
            bar.stop()

        # 5. Print the completion box with status summary.
        _print_completion_box(result)

        # The completion box on stderr gives the user real-time feedback.
        # The formatted result returned below is consumed by the LLM via stdout.

        return result.format_result()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_fresh_provider(self) -> LLMProvider:
        """Create a new provider instance for a sub-agent.

        Uses the template provider's :pyattr:`name` to determine which
        concrete provider to create, then calls
        :func:`~local_cli.providers.get_provider` with the appropriate
        configuration extracted from the template.

        Returns:
            A new :class:`LLMProvider` instance.

        Raises:
            ValueError: If the provider type is unknown.
        """
        from local_cli.providers import get_provider

        provider_name = self._provider.name

        if provider_name == "ollama":
            # Extract the base URL from the template provider's client.
            base_url = "http://localhost:11434"
            if hasattr(self._provider, "client") and hasattr(
                self._provider.client, "base_url"
            ):
                base_url = self._provider.client.base_url
            return get_provider("ollama", base_url=base_url)

        if provider_name == "claude":
            return get_provider("claude")

        if provider_name == "llama-server":
            base_url = getattr(self._provider, "_base_url", "http://localhost:8090")
            return get_provider("llama-server", base_url=base_url)

        # Fallback: attempt to create by name with no extra kwargs.
        return get_provider(provider_name)


# ---------------------------------------------------------------------------
# Visual feedback helpers
# ---------------------------------------------------------------------------


def _print_delegation_box(description: str, model: str, prompt_preview: str) -> None:
    """Print a delegation box explaining why the sub-agent is being spawned.

    Shows the task description, the model used, and a prompt preview so the
    user sees real-time context about what the sub-agent is doing and why.

    Args:
        description: Short task description (3-5 words).
        model: The model name running the sub-agent.
        prompt_preview: Truncated prompt text preview (max ~70 chars).
    """
    line_width = 60
    dash_line = f"{_GREEN}{'─' * line_width}{_RESET}"

    out = sys.stderr
    out.write("\n")
    out.write(f"  {_BOLD}{_GREEN}⊘ Spawning sub-agent{_RESET}\n")
    out.write(f"  {dash_line}\n")
    out.write(f"  {_BOLD}Why:{_RESET}      {description}\n")
    out.write(f"  {_BOLD}Model:{_RESET}    {model}\n")
    out.write(f"  {_BOLD}Prompt:{_RESET}   {prompt_preview}\n")
    out.write(f"  {dash_line}\n")
    out.flush()


def _print_completion_box(result: SubAgentResult) -> None:
    """Print a completion box after the sub-agent finishes.

    Shows status, duration, tool call count, and a result preview so the user
    sees what the sub-agent accomplished in real time.

    Args:
        result: The sub-agent's execution result.
    """
    line_width = 60
    status_color = _GREEN if result.status == "success" else _RED
    status_icon = "✓" if result.status == "success" else "✗"
    dash_line = f"{status_color}{'─' * line_width}{_RESET}"

    out = sys.stderr
    out.write(f"  {_BOLD}{status_color}{status_icon} Sub-agent complete{_RESET}\n")
    out.write(f"  {dash_line}\n")
    out.write(f"  {_BOLD}Status:{_RESET}   {status_color}{result.status}{_RESET}\n")
    out.write(f"  {_BOLD}Duration:{_RESET} {result.duration_seconds:.1f}s\n")
    out.write(f"  {_BOLD}Tools:{_RESET}    {result.tool_calls_count} calls\n")

    # Show a short result preview from the content.
    content = result.content.strip()
    if content:
        preview = content.replace("\n", " ").strip()
        if len(preview) > 80:
            preview = preview[:77] + "..."
        out.write(f"  {_BOLD}Result:{_RESET}   {preview}\n")

    if result.error_message:
        err_preview = result.error_message.replace("\n", " ").strip()
        if len(err_preview) > 80:
            err_preview = err_preview[:77] + "..."
        out.write(f"  {_BOLD}Error:{_RESET}    {_RED}{err_preview}{_RESET}\n")

    out.write(f"  {dash_line}\n")
    out.flush()
