"""Tests for local_cli.tools._fileio (atomic write helper)."""

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from local_cli.tools._fileio import atomic_write_text


class TestAtomicWriteText(unittest.TestCase):
    """Tests for atomic_write_text()."""

    def test_writes_content(self) -> None:
        """Content is written and read back verbatim."""
        fd, p = tempfile.mkstemp()
        os.close(fd)
        try:
            atomic_write_text(Path(p), "hello\nworld\n")
            self.assertEqual(Path(p).read_text(encoding="utf-8"), "hello\nworld\n")
        finally:
            os.unlink(p)

    def test_overwrite_preserves_existing_mode(self) -> None:
        """Overwriting an existing file keeps its permission bits."""
        fd, p = tempfile.mkstemp()
        os.close(fd)
        try:
            os.chmod(p, 0o755)
            atomic_write_text(Path(p), "replaced")
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o755)
            self.assertEqual(Path(p).read_text(encoding="utf-8"), "replaced")
        finally:
            os.unlink(p)

    def test_new_file_respects_umask(self) -> None:
        """A newly created file gets 0666 & ~umask, not mkstemp's 0600."""
        d = tempfile.mkdtemp()
        try:
            p = Path(d) / "new.txt"
            atomic_write_text(p, "data")
            mode = stat.S_IMODE(os.stat(p).st_mode)
            current_umask = os.umask(0)
            os.umask(current_umask)
            self.assertEqual(mode, 0o666 & ~current_umask)
        finally:
            shutil.rmtree(d)

    def test_overwrite_leaves_no_temp_files(self) -> None:
        """After overwriting, only the target file remains in the dir."""
        d = tempfile.mkdtemp()
        try:
            p = Path(d) / "f.txt"
            atomic_write_text(p, "a")
            atomic_write_text(p, "b")
            self.assertEqual(p.read_text(encoding="utf-8"), "b")
            self.assertEqual(list(Path(d).iterdir()), [p])
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
