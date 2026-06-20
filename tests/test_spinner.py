"""Tests for local_cli.spinner."""

import io
import sys
import time
import unittest

from local_cli.spinner import ProgressBar, Spinner


class TestSpinner(unittest.TestCase):
    """Tests for the Spinner class."""

    def test_context_manager_starts_and_stops(self) -> None:
        """Spinner starts and stops cleanly as a context manager."""
        with Spinner("Test"):
            # Thread should be alive inside the context.
            pass
        # After exiting, the thread should be stopped.

    def test_start_stop(self) -> None:
        """Spinner can be started and stopped explicitly."""
        s = Spinner("Working")
        s.start()
        self.assertIsNotNone(s._thread)
        self.assertTrue(s._thread.is_alive())
        s.stop()
        self.assertIsNone(s._thread)

    def test_stop_without_start(self) -> None:
        """Stopping a spinner that was never started does not raise."""
        s = Spinner("Idle")
        s.stop()  # Should not raise.

    def test_double_stop(self) -> None:
        """Stopping twice does not raise."""
        s = Spinner("Twice")
        s.start()
        s.stop()
        s.stop()  # Should not raise.

    def test_writes_to_stderr(self) -> None:
        """Spinner writes animation frames to stderr."""
        captured = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = captured
        try:
            s = Spinner("Loading")
            s.start()
            time.sleep(0.15)  # Let a few frames render.
            s.stop()
        finally:
            sys.stderr = original_stderr

        output = captured.getvalue()
        self.assertIn("Loading", output)

    def test_clears_line_on_stop(self) -> None:
        """Spinner clears its line when stopped."""
        captured = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = captured
        try:
            s = Spinner("Clear")
            s.start()
            time.sleep(0.1)
            s.stop()
        finally:
            sys.stderr = original_stderr

        output = captured.getvalue()
        # The last write should be a clearing line (spaces + \r).
        self.assertTrue(output.rstrip(" ").endswith("\r"))


class TestProgressBar(unittest.TestCase):
    """Tests for the ProgressBar class."""

    def test_context_manager_starts_and_stops(self) -> None:
        """ProgressBar starts and stops cleanly as a context manager."""
        with ProgressBar("Test"):
            # Thread should be alive inside the context.
            pass
        # After exiting, the thread should be stopped.

    def test_start_stop(self) -> None:
        """ProgressBar can be started and stopped explicitly."""
        p = ProgressBar("Working")
        p.start()
        self.assertIsNotNone(p._thread)
        self.assertTrue(p._thread.is_alive())
        p.stop()
        self.assertIsNone(p._thread)

    def test_stop_without_start(self) -> None:
        """Stopping a ProgressBar that was never started does not raise."""
        p = ProgressBar("Idle")
        p.stop()  # Should not raise.

    def test_double_stop(self) -> None:
        """Stopping a ProgressBar twice does not raise."""
        p = ProgressBar("Twice")
        p.start()
        p.stop()
        p.stop()  # Should not raise.

    def test_default_message(self) -> None:
        """ProgressBar uses 'Processing' as default message."""
        p = ProgressBar()
        self.assertEqual(p._message, "Processing")

    def test_custom_message(self) -> None:
        """ProgressBar accepts a custom message."""
        p = ProgressBar("Custom message")
        self.assertEqual(p._message, "Custom message")

    def test_writes_to_stderr(self) -> None:
        """ProgressBar writes animation frames to stderr."""
        captured = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = captured
        try:
            p = ProgressBar("Loading")
            p.start()
            time.sleep(0.3)  # Let a few frames render (slower interval: 0.24s).
            p.stop()
        finally:
            sys.stderr = original_stderr

        output = captured.getvalue()
        # Should contain the message.
        self.assertIn("Loading", output)
        # Should contain the bar characters.
        self.assertIn("█", output)
        # Should contain the ANSI escape for amber color.
        self.assertIn("\033[38;5;214m", output)

    def test_clears_line_on_stop(self) -> None:
        """ProgressBar clears its line when stopped."""
        captured = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = captured
        try:
            p = ProgressBar("Clear")
            p.start()
            time.sleep(0.3)
            p.stop()
        finally:
            sys.stderr = original_stderr

        output = captured.getvalue()
        # The last write should be a clearing line (spaces + \r).
        self.assertTrue(output.rstrip(" ").endswith("\r"))


if __name__ == "__main__":
    unittest.main()
