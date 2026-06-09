"""Edit tool for replacing text in files.

Performs exact string matching and replacement within files.  Reads the
file, locates an exact match of the ``old_text`` parameter, replaces it
with ``new_text``, and writes the result back.  Returns a diff-like
output showing the changes made.
"""

import os
import tempfile
from pathlib import Path

from local_cli.tools.base import Tool


def _make_diff_output(
    file_path: str,
    old_text: str,
    new_text: str,
    occurrences: int,
) -> str:
    """Build a diff-like summary of the replacement.

    Args:
        file_path: Path to the edited file.
        old_text: The original text that was replaced.
        new_text: The replacement text.
        occurrences: Number of replacements made.

    Returns:
        A human-readable diff-like string.
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    parts: list[str] = [f"--- {file_path}"]
    parts.append(f"+++ {file_path}")
    parts.append(f"@@ replaced {occurrences} occurrence(s) @@")
    for line in old_lines:
        parts.append(f"-{line}")
    for line in new_lines:
        parts.append(f"+{line}")

    return "\n".join(parts)


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (temp file + rename).

    The new content is written to a sibling temp file which is then
    ``os.replace``-d into place, so a failure mid-write leaves the original
    file intact rather than half-written.  The original file's permission
    bits are preserved across the replacement.

    Args:
        path: Destination file path.
        content: Text to write.
    """
    try:
        orig_mode: int | None = path.stat().st_mode
    except OSError:
        orig_mode = None

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".edit-", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        if orig_mode is not None:
            try:
                os.chmod(tmp_name, orig_mode)
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


class EditTool(Tool):
    """Replace exact text matches in a file."""

    @property
    def name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return (
            "Replace an exact text match in a file. Reads the file, "
            "finds the exact occurrence of old_text, replaces it with "
            "new_text, and writes the result back. Returns a diff-like "
            "output showing the changes. Use replace_all to control "
            "whether all occurrences or just the first are replaced."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path to the file to edit.",
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find in the file.",
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace old_text with.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": (
                        "If true, replace all occurrences. "
                        "If false (default), replace only the first occurrence."
                    ),
                },
            },
            "required": ["file_path", "old_text", "new_text"],
        }

    def execute(self, **kwargs: object) -> str:
        """Replace exact text in a file and return a diff-like summary.

        Args:
            **kwargs: Must include ``file_path`` (str), ``old_text``
                (str), and ``new_text`` (str).  May include
                ``replace_all`` (bool, default False).

        Returns:
            A diff-like string showing the changes, or an error message
            if the operation failed.
        """
        file_path = kwargs.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            return "Error: 'file_path' parameter is required and must be a non-empty string."

        old_text = kwargs.get("old_text")
        if not isinstance(old_text, str):
            return "Error: 'old_text' parameter is required and must be a string."
        if not old_text:
            return "Error: 'old_text' must not be empty."

        new_text = kwargs.get("new_text")
        if not isinstance(new_text, str):
            return "Error: 'new_text' parameter is required and must be a string."

        replace_all = kwargs.get("replace_all", False)
        if not isinstance(replace_all, bool):
            replace_all = False

        path = Path(file_path)

        if not path.exists():
            return f"Error: file not found: {file_path}"

        if not path.is_file():
            return f"Error: not a regular file: {file_path}"

        # Read the current content.
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="latin-1")
            except OSError as exc:
                return f"Error: could not read file: {exc}"
        except PermissionError:
            return f"Error: permission denied: {file_path}"
        except OSError as exc:
            return f"Error: could not read file: {exc}"

        # Check that old_text exists in the file.
        count = content.count(old_text)
        if count == 0:
            # Fallback: the model usually emits LF line endings, but the
            # file on disk may use CRLF (or bare CR).  Normalize both sides
            # to LF and retry; on a match, operate on the normalized content
            # so the rewritten file is internally consistent.
            norm_content = content.replace("\r\n", "\n").replace("\r", "\n")
            norm_old = old_text.replace("\r\n", "\n").replace("\r", "\n")
            if norm_old and norm_content.count(norm_old) > 0:
                content = norm_content
                old_text = norm_old
                count = content.count(old_text)
            else:
                return f"Error: old_text not found in {file_path}"

        # Perform the replacement.
        if replace_all:
            new_content = content.replace(old_text, new_text)
            occurrences = count
        else:
            new_content = content.replace(old_text, new_text, 1)
            occurrences = 1

        # Write the modified content back atomically so a failure mid-write
        # cannot leave the file truncated or corrupted.
        try:
            _atomic_write(path, new_content)
        except PermissionError:
            return f"Error: permission denied: {file_path}"
        except OSError as exc:
            return f"Error: could not write file: {exc}"

        return _make_diff_output(file_path, old_text, new_text, occurrences)
