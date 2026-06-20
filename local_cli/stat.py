"""Status display with colorful shell output.

Provides a rich terminal UI for showing agent status with red/orange
color themes and running indicator. Also provides utilities for the
agent to ask clarifying questions when needed.

Shell Control Commands:
    /queue <command> - Queue command to run after current agent finishes
    /bg <command>   - Run command in background
    /stop           - Stop the running agent
    /interview      - Start interview mode (AI asks questions about your project)
"""

from __future__ import annotations

import os
import queue
import readline
import subprocess
import sys
import threading
import time
from typing import Optional

# ANSI color codes
_RESET = "\033[0m"
_BOLD = "\033[1m"

# Red theme colors
_RED = "\033[91m"
_RED_BG = "\033[41m"
_RED_DIM = "\033[91;2m"

# Orange theme colors  
_ORANGE = "\033[38;5;208m"
_ORANGE_BG = "\033[48;5;208m"
_ORANGE_DIM = "\033[38;5;208;2m"

# Additional warm tones
_AMBER = "\033[38;5;214m"
_CORAL = "\033[38;5;203m"

# Status colors
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_GRAY = "\033[90m"
_MAGENTA = "\033[95m"


# ----------------------------------------------------------------------
# Agent Status
# ----------------------------------------------------------------------


class AgentStatus:
    """Track agent running status with visual indicator."""

    _instance: "Optional[AgentStatus]" = None
    _lock = threading.Lock()

    def __new__(cls) -> "AgentStatus":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._running = False
                    cls._instance._start_time: Optional[float] = None
                    cls._instance._task_name: Optional[str] = None
        return cls._instance

    @property
    def is_running(self) -> bool:
        """Check if agent is currently running."""
        return self._running

    @property
    def start_time(self) -> Optional[float]:
        """Get the start time of current run."""
        return self._start_time

    @property
    def task_name(self) -> Optional[str]:
        """Get the current task name."""
        return self._task_name

    def start(self, task_name: Optional[str] = None) -> None:
        """Mark agent as started."""
        self._running = True
        self._start_time = time.time()
        self._task_name = task_name or "Working"

    def stop(self) -> None:
        """Mark agent as stopped."""
        self._running = False
        self._start_time = None
        self._task_name = None

    def running_elapsed(self) -> Optional[float]:
        """Get elapsed time in seconds since agent started."""
        if self._start_time is None:
            return None
        return time.time() - self._start_time


def get_status() -> AgentStatus:
    """Get the global AgentStatus singleton."""
    return AgentStatus()


def _format_time(seconds: float) -> str:
    """Format elapsed time as human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


# ----------------------------------------------------------------------
# Agent Controller (Queue, Background, Stop)
# ----------------------------------------------------------------------


class AgentController:
    """Controls agent execution: queue commands, background mode, stop."""
    
    _instance: "Optional[AgentController]" = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "AgentController":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._command_queue: queue.Queue = queue.Queue()
                    cls._instance._is_background = False
                    cls._instance._should_stop = False
                    cls._instance._current_command: Optional[str] = None
                    cls._instance._background_thread: Optional[threading.Thread] = None
                    cls._instance._interview_mode = False
                    cls._instance._interview_questions: list[str] = []
                    cls._instance._interview_answers: dict[str, str] = {}
        return cls._instance
    
    @property
    def is_running(self) -> bool:
        """Check if agent is currently processing."""
        return get_status().is_running
    
    @property
    def is_background(self) -> bool:
        """Check if running in background mode."""
        return self._is_background
    
    @property
    def should_stop(self) -> bool:
        """Check if stop was requested."""
        return self._should_stop
    
    @property
    def queue_size(self) -> int:
        """Get number of queued commands."""
        return self._command_queue.qsize()
    
    @property
    def is_interview_mode(self) -> bool:
        """Check if in interview mode."""
        return self._interview_mode
    
    def queue_command(self, command: str) -> None:
        """Add a command to the queue to run after current one finishes."""
        self._command_queue.put(command)
        print(f"{_CYAN}⏳ Queued:{_RESET} {command}")
        if self._is_background:
            print(f"{_GRAY}  (Queue size: {self.queue_size}){_RESET}")
    
    def get_queued_command(self, timeout: float = 0.1) -> Optional[str]:
        """Get next command from queue (non-blocking)."""
        try:
            return self._command_queue.get_nowait()
        except queue.Empty:
            return None
    
    def clear_queue(self) -> int:
        """Clear all queued commands. Returns count of cleared commands."""
        cleared = 0
        while True:
            try:
                self._command_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        return cleared
    
    def set_background(self, is_bg: bool) -> None:
        """Set background mode."""
        self._is_background = is_bg
    
    def request_stop(self) -> None:
        """Request the agent to stop."""
        self._should_stop = True
        print(f"{_RED}⏹ Stop requested{_RESET}")
    
    def clear_stop(self) -> None:
        """Clear stop request."""
        self._should_stop = False
    
    def start_background(self, command: str) -> None:
        """Run a command in background."""
        self._is_background = True
        self._should_stop = False
        
        def run_background():
            # Will be executed by the REPL after this returns
            pass
        
        self._background_thread = threading.Thread(target=run_background, daemon=True)
        self._background_thread.start()
        
        print(f"{_GREEN}▶ Started in background:{_RESET} {command}")
        print(f"{_GRAY}  Use /stop to halt, /queue to add commands{_RESET}")
    
    def stop(self) -> None:
        """Stop background mode."""
        self._is_background = False
        self._should_stop = True
    
    # ------------------------------------------------------------------
    # Interview Mode
    # ------------------------------------------------------------------
    
    def start_interview(self, project_path: Optional[str] = None) -> str:
        """Start interview mode and return the intro prompt.
        
        Args:
            project_path: Path to project to analyze (defaults to cwd)
            
        Returns:
            The initial prompt to send to the agent
        """
        self._interview_mode = True
        self._interview_questions = []
        self._interview_answers = {}
        
        path = project_path or os.getcwd()
        
        # Generate intro prompt
        intro = f"""{_ORANGE}{_BOLD}╔════════════════════════════════════════╗
║      INTERVIEW MODE STARTED         ║
╚════════════════════════════════════╝{_RESET}

{_CYAN}I'm going to ask you questions about your project to understand it better.
Please answer each question thoroughly so I can learn about:{_RESET}

  • Project structure and purpose
  • Key files and their roles
  • Dependencies and configuration
  • Testing approach
  • Any conventions or patterns

{_YELLOW}Let's start! First, tell me in 2-3 sentences:{_RESET}

{_AMBER}What does this project do? What is its main purpose?{_RESET}

"""
        
        print(intro)
        return intro
    
    def get_interview_question(self, question_num: int) -> Optional[str]:
        """Get the next interview question."""
        questions = [
            "What is the main entry point of this project?",
            "What are the key dependencies and how are they managed?",
            "What is the project structure (main directories and their purpose)?",
            "How is testing done in this project?",
            "Are there any configuration files I should know about?",
            "What are the naming conventions used?",
            "Are there any specific patterns or patterns to follow?",
            "What is the build/deployment process?",
            "Any other important things I should know about this project?",
        ]
        
        if question_num <= len(questions):
            return questions[question_num - 1]
        return None
    
    def record_answer(self, question: str, answer: str) -> None:
        """Record an interview answer."""
        self._interview_answers[question] = answer
    
    def end_interview(self) -> str:
        """End interview mode and return the summary."""
        self._interview_mode = False
        
        summary = f"""{_GREEN}{_BOLD}╔════════════════════════════════════════╗
║      INTERVIEW COMPLETE            ║
╚════════════════════════════════════╝{_RESET}

{_CYAN}Thanks! Here's what I learned about your project:{_RESET}

"""
        for i, (q, a) in enumerate(self._interview_answers.items(), 1):
            summary += f"{_ORANGE}{i}. {q}{_RESET}\n"
            summary += f"   {a}\n\n"
        
        # Also save to MEMORY.md
        self._save_to_memory()
        
        return summary
    
    def _save_to_memory(self) -> None:
        """Save interview findings to MEMORY.md."""
        try:
            agents_dir = os.path.join(os.getcwd(), ".agents")
            memory_path = os.path.join(agents_dir, "MEMORY.md")
            
            if not os.path.exists(agents_dir):
                os.makedirs(agents_dir)
            
            # Append to MEMORY.md
            timestamp = time.strftime("%Y-%m-%d")
            entry = f"\n### Interview {timestamp}\n"
            
            for q, a in self._interview_answers.items():
                entry += f"- **{q}**: {a}\n"
            
            with open(memory_path, "a") as f:
                f.write(entry)
            
            print(f"{_GREEN}✓ Saved to MEMORY.md{_RESET}")
        except Exception as e:
            print(f"{_ORANGE}Could not save to MEMORY.md: {e}{_RESET}")
    
    def is_interview_active(self) -> bool:
        """Check if interview mode is active."""
        return self._interview_mode


def get_controller() -> AgentController:
    """Get the global AgentController singleton."""
    return AgentController()


# ----------------------------------------------------------------------
# Shell output functions
# ----------------------------------------------------------------------


def print_header(text: str) -> None:
    """Print a bold red header line."""
    print(f"{_RED}{_BOLD}{text}{_RESET}")


def print_subheader(text: str) -> None:
    """Print an orange subheader line."""
    print(f"{_ORANGE}{_BOLD}{text}{_RESET}")


def print_running_marker(show_task: bool = True, task: Optional[str] = None) -> None:
    """Print the running indicator with pulsing animation.

    Args:
        show_task: Whether to show task name from status tracker
        task: Optional task name to display (overrides status tracker)
    """
    status = get_status()
    display_task = task or (status.task_name if show_task else None)
    
    if status.is_running:
        # Pulsing effect - alternates between two frames
        frame = "▶" if int(time.time() * 2) % 2 == 0 else "▸"
        
        if display_task:
            elapsed = status.running_elapsed()
            time_str = _format_time(elapsed) if elapsed else ""
            print(
                f"\r{_ORANGE}{frame} {_BOLD}{display_task}{_RESET} "
                f"{_ORANGE_DIM}{time_str}{_RESET}   ",
                end="",
                flush=True
            )
        else:
            print(
                f"\r{_ORANGE}{frame} {_BOLD}Agent running{_RESET}   ",
                end="",
                flush=True
            )
    else:
        print(f"\r{_GRAY}○ Idle{_RESET}                    ", end="", flush=True)


def print_stopped_marker() -> None:
    """Print the stopped indicator."""
    print(f"\r{_RED}■ Idle{_RESET}                    ", end="", flush=True)


def print_status_bar(
    model: Optional[str] = None,
    messages: int = 0,
    mode: str = "agent",
    running: bool = False,
    task: Optional[str] = None,
) -> None:
    """Print a colorful status bar.

    Args:
        model: Current model name
        messages: Number of messages exchanged
        mode: Current mode (agent/ideate)
        running: Whether agent is currently running
        task: Current task name if running
    """
    # Build the status line pieces
    parts = []

    # Running indicator
    if running:
        frame = "▶"
        elapsed = get_status().running_elapsed()
        time_str = f"({_format_time(elapsed)})" if elapsed else ""
        task_str = f"{task}" if task else ""
        time_display = f" {_ORANGE_DIM}{time_str}{_RESET}" if time_str else ""
        parts.append(
            f"{_ORANGE}{frame}{_RESET} {_BOLD}{task_str}{_RESET}{time_display}"
        )
    else:
        parts.append(f"{_GRAY}○ Idle{_RESET}")

    # Model
    if model:
        parts.append(f"{_RED}⚡{_RESET} {model}")

    # Messages
    parts.append(f"{_AMBER}💬{_RESET} {messages}")

    # Mode
    mode_color = _CYAN if mode == "agent" else _ORANGE
    parts.append(f"{mode_color}◈{_RESET} {mode}")

    # Print the bar
    print(f"\n{' │ '.join(parts)}\n")


def print_error(text: str) -> None:
    """Print an error message in red."""
    print(f"{_RED}✖ Error:{_RESET} {text}", file=sys.stderr)


def print_warning(text: str) -> None:
    """Print a warning message in orange/amber."""
    print(f"{_ORANGE}⚠ Warning:{_RESET} {text}")


def print_success(text: str) -> None:
    """Print a success message in green."""
    print(f"{_GREEN}✓ Success:{_RESET} {text}")


def print_info(text: str) -> None:
    """Print an info message in cyan."""
    print(f"{_CYAN}ℹ Info:{_RESET} {text}")


def print_thinking(text: str) -> None:
    """Print thinking/reasoning in dim orange."""
    for line in text.splitlines():
        print(f"{_ORANGE_DIM}> {line}{_RESET}")


def print_tool_execution(tool_name: str, args: Optional[dict] = None) -> None:
    """Print tool execution in progress."""
    args_str = ""
    if args:
        args_str = f" {args}"
    print(f"{_ORANGE}⟳ {_BOLD}Executing: {_RESET}{tool_name}{args_str}")


def print_tool_result(tool_name: str, truncated: bool = False) -> None:
    """Print tool result completion."""
    suffix = " (truncated)" if truncated else ""
    print(f"{_GREEN}✓ {tool_name}{suffix}{_RESET}")


# ----------------------------------------------------------------------
# Agent clarification helpers
# ----------------------------------------------------------------------


def ask_for_password(field: str = "password") -> str:
    """Prompt user for a password interactively.

    Args:
        field: Name of the password field being requested

    Returns:
        The password entered by user (what they type)
    """
    import getpass
    print(f"{_ORANGE}🔐 Enter {field}:{_RESET}", end=" ")
    return getpass.getpass("")


def ask_yes_no(question: str, default: Optional[bool] = None) -> bool:
    """Ask a yes/no question.

    Args:
        question: The question to ask
        default: Default value if user just presses Enter (True/False/None)

    Returns:
        True for yes, False for no
    """
    # Build prompt
    default_str = ""
    if default is True:
        default_str = " [Y/n]"
    elif default is False:
        default_str = " [y/N]"
    else:
        default_str = " [y/n]"

    while True:
        print(f"{_ORANGE}?{_RESET} {question}{default_str}: ", end="")
        response = input().strip().lower()

        if not response:
            if default is not None:
                return default
            print(f"{_ORANGE}Please answer y or n{_RESET}")
            continue

        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        else:
            print(f"{_ORANGE}Please answer y or n{_RESET}")


def ask_for_explanation(prompt: str) -> str:
    """Ask user to clarify or explain something.

    Args:
        prompt: What the agent wants explained

    Returns:
        User's explanation text
    """
    print(f"\n{_ORANGE}{_BOLD}? Clarification needed:{_RESET}")
    print(f"{_ORANGE}{prompt}{_RESET}")
    print(f"{_CYAN}Your response: {_RESET}", end="")
    return input().strip()


def ask_to_continue(
    reason: str,
    default_yes: bool = False,
) -> bool:
    """Ask user if they want to continue with an action.

    Args:
        reason: Why confirmation is needed
        default_yes: If True, Enter without input means yes

    Returns:
        True to proceed, False to abort
    """
    default_str = " [y/n]" if not default_yes else " [Y/n]"
    while True:
        print(f"\n{_ORANGE}?{_RESET} {reason}{default_str}: ", end="")
        response = input().strip().lower()

        if not response:
            return default_yes

        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        else:
            print(f"{_ORANGE}Please answer y or n{_RESET}")


def request_input(
    field_name: str,
    description: str,
    required: bool = True,
) -> Optional[str]:
    """Request a specific input from the user.

    Args:
        field_name: Name of the field (e.g., "password", "API key")
        description: What the field is for
        required: If True, empty input will prompt again

    Returns:
        User input or None if cancelled
    """
    print(f"\n{_ORANGE}{_BOLD}Input needed:{_RESET} {field_name}")
    print(f"  {description}")

    while True:
        print(f"{_CYAN}> {_RESET}", end="")
        value = input().strip()

        if value:
            return value
        elif required:
            print(f"{_ORANGE}This field is required. Please enter a value.{_RESET}")
        else:
            return None


# ----------------------------------------------------------------------
# Convenience decorator for marking agent running status
# ----------------------------------------------------------------------


def agent_running(task_name: Optional[str] = None):
    """Decorator/context manager to track agent running status.

    Can be used as a decorator or context manager.

    Usage as decorator:
        @agent_running("Processing files")
        def do_work():
            ...

    Usage as context manager:
        with agent_running("Writing file"):
            write_file(...)
    """
    class _AgentRunning:
        def __init__(self, name: Optional[str]):
            self._name = name
            self._status = get_status()

        def __enter__(self):
            self._status.start(self._name)
            return self

        def __exit__(self, *args):
            self._status.stop()

        def __call__(self, func):
            def wrapper(*args, **kwargs):
                self._status.start(self._name)
                try:
                    return func(*args, **kwargs)
                finally:
                    self._status.stop()
            return wrapper

    return _AgentRunning(task_name)


# ----------------------------------------------------------------------
# Demo / test
# ----------------------------------------------------------------------


if __name__ == "__main__":
    print_header("╔══════════════════════════════════╗")
    print_header("║     Local CLI Status Demo       ║")
    print_header("╚══════════════════════════════════╝")

    print("\n")
    print_subheader("── Status Bar Samples ──")
    print_status_bar(model="qwen2.5:14b", messages=12, mode="agent", running=False)

    print_status_bar(
        model="qwen2.5:14b", 
        messages=15, 
        mode="agent", 
        running=True, 
        task="Refactoring auth.py"
    )

    print("\n")
    print_subheader("── Messages ──")
    print_success("Operation completed successfully!")
    print_warning("This is a warning message")
    print_error("An error occurred: connection refused")
    print_info("Here's some information")

    print("\n")
    print_subheader("── Running Indicator Demo ──")
    import sys
    
    status = get_status()
    status.start("Demo task")
    print("\nAgent started, showing running indicator:")
    for i in range(10):
        print_running_marker()
        time.sleep(0.2)
    
    status.stop()
    print("\n")
    print_success("Agent stopped!")
    
    print("\n")
    print_header("Demo complete!")