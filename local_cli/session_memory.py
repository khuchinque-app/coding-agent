"""Session-scoped temporary storage that auto-creates on run and auto-deletes on session end.

Uses Python stdlib only (``tempfile`` + ``shelve``) — zero external
dependencies.  Every :class:`SessionMemory` instance creates a secure
temporary directory that is wiped when the process exits (via
:func:`atexit.register`).

Example::

    mem = SessionMemory()
    mem.save("progress", {"step": 3, "files_created": ["foo.py"]})
    data = mem.load("progress")   # {"step": 3, ...}
    mem.close()                   # optional, cleaned up automatically
"""

import atexit
import os
import shelve
import shutil
import sys
import tempfile
from typing import Any


class SessionMemory:
    """Temporary key-value storage scoped to a single process session.

    Wraps :class:`shelve.open` with a secure :func:`tempfile.mkdtemp`
    directory that is deleted when the process exits via :func:`atexit`.
    This ensures data persists across multiple :func:`agent_loop` calls
    within the same session but is cleaned up automatically when the
    REPL or server exits — even on crash.

    All public methods are safe to call even after :meth:`close` (they
    become no-ops), so callers do not need to check ``is_alive``.

    Args:
        prefix: Prefix for the temporary directory name (default
            ``"local-cli-session-"``).

    Attributes:
        tmp_dir: Path to the temporary directory (read-only, for
            debugging / inspection).
    """

    def __init__(self, prefix: str = "local-cli-session-") -> None:
        self._tmp_dir: str = tempfile.mkdtemp(prefix=prefix)
        self._db_path: str = os.path.join(self._tmp_dir, "session_memory")
        self._closed: bool = False
        atexit.register(self._cleanup)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, key: str, value: Any) -> None:
        """Persist *value* under *key* to session storage.

        Args:
            key: String key for the stored value.
            value: Any picklable Python object.
        """
        if self._closed:
            return
        try:
            with shelve.open(self._db_path, protocol=2) as db:
                db[key] = value
        except Exception as exc:
            sys.stderr.write(f"[session_memory] save({key!r}) failed: {exc}\n")

    def load(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by *key*, returning *default* when missing.

        Args:
            key: The key to look up.
            default: Value returned when *key* is not found (default
                ``None``).

        Returns:
            The stored value, or *default*.
        """
        if self._closed:
            return default
        try:
            with shelve.open(self._db_path, protocol=2, flag="r") as db:
                return db.get(key, default)
        except Exception:
            return default

    def keys(self) -> list[str]:
        """Return all keys currently stored in session memory.

        Returns:
            A list of key strings (empty list if storage is closed or
            unavailable).
        """
        if self._closed:
            return []
        try:
            with shelve.open(self._db_path, protocol=2, flag="r") as db:
                return list(db.keys())
        except Exception:
            return []

    def clear(self) -> None:
        """Remove all stored data from session storage."""
        if self._closed:
            return
        try:
            with shelve.open(self._db_path, protocol=2) as db:
                db.clear()
        except Exception as exc:
            sys.stderr.write(f"[session_memory] clear failed: {exc}\n")

    def close(self) -> None:
        """Explicitly delete the temporary directory.

        Also called automatically via :func:`atexit` when the process
        exits, so explicit :meth:`close` is optional.  Safe to call
        multiple times (subsequent calls are no-ops).
        """
        if self._closed:
            return
        self._closed = True
        try:
            atexit.unregister(self._cleanup)
        except Exception:
            pass
        self._cleanup()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tmp_dir(self) -> str:
        """Path to the temporary directory (read-only)."""
        return self._tmp_dir

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        """Remove the temp directory and all its contents."""
        try:
            if os.path.isdir(self._tmp_dir):
                shutil.rmtree(self._tmp_dir, ignore_errors=True)
        except Exception:
            pass
