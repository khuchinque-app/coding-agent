"""Shared low-level file-writing helpers for tools.

The ``edit`` and ``write`` tools both need to persist file content without
risking a half-written file if something fails mid-write.  This module is
the single place that implements that, so both tools behave identically.
"""

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (temp file + rename).

    The content is written to a sibling temp file which is then
    ``os.replace``-d into place, so a failure mid-write leaves any existing
    file intact rather than truncated.

    Permission handling:

    * When *path* already exists, its permission bits are preserved.
    * When *path* is new, the default ``0666 & ~umask`` is applied (the same
      mode a normal ``open(...,'w')`` would produce) rather than the
      restrictive ``0600`` that ``mkstemp`` creates.

    Args:
        path: Destination file path.  Its parent directory must already
            exist.
        content: Text to write (UTF-8).
    """
    try:
        orig_mode: int | None = path.stat().st_mode
    except OSError:
        orig_mode = None

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp-", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        if orig_mode is not None:
            target_mode: int | None = orig_mode
        else:
            # New file: mirror what open()'s default would give (0666 minus
            # the process umask) instead of mkstemp's locked-down 0600.
            current_umask = os.umask(0)
            os.umask(current_umask)
            target_mode = 0o666 & ~current_umask
        try:
            os.chmod(tmp_name, target_mode)
        except OSError:
            pass
        os.replace(tmp_name, str(path))
    except BaseException:
        # Clean up the temp file on any failure (including the rename).
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
