"""Terminal spinner and progress bar for visual feedback during long-running operations.

Provides a threaded spinner that animates in the terminal while the main thread
is blocked (e.g. waiting for LLM response or executing a tool).
Uses only stdlib -- no external dependencies.
"""

import sys
import threading
import time

# Braille-dot spinner frames (smooth 10-frame cycle).
_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Interval between frame updates (seconds).
_INTERVAL = 0.08

# ANSI color codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_AMBER = "\033[38;5;214m"
_GREEN = "\033[92m"
_GRAY = "\033[90m"
_RED = "\033[91m"
_ORANGE = "\033[38;5;208m"


class Spinner:
    """A terminal spinner that runs in a background thread.

    Usage::

        with Spinner("Thinking"):
            # ... blocking work ...
            pass

    The spinner automatically stops and clears itself when the context
    manager exits (even on exception).
    """

    def __init__(self, message: str = "Thinking") -> None:
        self._message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _animate(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            frame = _FRAMES[idx % len(_FRAMES)]
            line = f"\r  {frame} {self._message}..."
            sys.stderr.write(line)
            sys.stderr.flush()
            idx += 1
            self._stop_event.wait(_INTERVAL)
        # Clear the spinner line.
        sys.stderr.write("\r" + " " * (len(self._message) + 10) + "\r")
        sys.stderr.flush()

    def start(self) -> None:
        """Start the spinner animation."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the spinner and clear the line."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self) -> "Spinner":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


# Animated progress bar characters
_BAR_FULL = "█"
_BAR_EMPTY = "░"
_BAR_WIDTH = 20

# Pulse animation frames — a block that moves left-to-right
_PULSE_FRAMES: list[str] = []
for offset in range(_BAR_WIDTH):
    chars = [_BAR_EMPTY] * _BAR_WIDTH
    # Create a "glow" of 4 filled blocks
    for g in range(4):
        idx = (offset + g) % _BAR_WIDTH
        chars[idx] = _BAR_FULL
    _PULSE_FRAMES.append("".join(chars))


class ProgressBar:
    """An animated, indeterminate progress bar that runs in a background thread.

    Shows a pulsing bar that moves left-to-right, giving the appearance of
    progress without knowing the actual completion percentage.

    Usage::

        with ProgressBar("Buffy is thinking..."):
            # ... blocking work ...
            pass

    The progress bar automatically stops and clears itself when the context
    manager exits (even on exception).
    """

    def __init__(self, message: str = "Processing") -> None:
        self._message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _animate(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            bar = _PULSE_FRAMES[idx % len(_PULSE_FRAMES)]
            line = (
                f"\r{_AMBER}{_BOLD}▶{_RESET} "
                f"{_BOLD}{self._message}{_RESET} "
                f"{_GREEN}[{_RESET}{bar}{_GREEN}]{_RESET}"
            )
            sys.stderr.write(line)
            sys.stderr.flush()
            idx += 1
            self._stop_event.wait(_INTERVAL * 3)
        # Clear the progress bar line.
        sys.stderr.write("\r" + " " * (len(self._message) + _BAR_WIDTH + 12) + "\r")
        sys.stderr.flush()

    def start(self) -> None:
        """Start the progress bar animation."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the progress bar and clear the line."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self) -> "ProgressBar":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
