"""Archive tool for local-cli.

Provides zip and unzip operations using Python's ``zipfile`` module
so they work without external zip/unzip binaries.
"""

import os
import shutil
from pathlib import Path
from typing import Callable

from local_cli.tools.base import Tool

# Maximum output size in bytes (100 KB).
_MAX_OUTPUT_BYTES = 100 * 1024


class ArchiveTool(Tool):
    """Create and extract zip archives without external dependencies."""

    def __init__(
        self,
        confirm: Callable[[str], bool] | None = None,
    ) -> None:
        """Create the archive tool.

        Args:
            confirm: Optional callback for confirmation prompts.
        """
        self._confirm = confirm

    @property
    def cacheable(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "archive"

    @property
    def description(self) -> str:
        return (
            "Create or extract zip archives. Use 'zip <archive> <source>...' "
            "to compress files/directories into a zip file. Use "
            "'unzip <archive> [dest]' to extract a zip file to a directory. "
            "Handles large files efficiently."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "Either 'zip' to create an archive or 'unzip' to extract one."
                    ),
                    "enum": ["zip", "unzip"],
                },
                "archive": {
                    "type": "string",
                    "description": (
                        "Path to the zip archive file (e.g. 'archive.zip')."
                    ),
                },
                "sources": {
                    "type": "string",
                    "description": (
                        "For 'zip': space-separated list of files/directories "
                        "to add to the archive (e.g. 'src/ README.md'). "
                        "Not used for 'unzip'."
                    ),
                },
                "destination": {
                    "type": "string",
                    "description": (
                        "For 'unzip': directory to extract into. "
                        "Defaults to the current directory. "
                        "Not used for 'zip'."
                    ),
                },
            },
            "required": ["action", "archive"],
        }

    def _do_zip(self, archive_path: str, sources: list[str]) -> str:
        """Create a zip archive from source files/directories."""
        import zipfile

        archive = Path(archive_path)
        if archive.exists():
            return f"Error: {archive_path} already exists. Remove it first or use a different name."

        # Resolve all source paths.
        resolved_sources: list[Path] = []
        for src in sources:
            src_path = Path(src).expanduser().resolve()
            if not src_path.exists():
                return f"Error: source '{src}' does not exist."
            resolved_sources.append(src_path)

        try:
            # Ensure parent directory exists.
            archive.parent.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(
                str(archive), "w", zipfile.ZIP_DEFLATED, allowZip64=True
            ) as zf:
                added = 0
                for src_path in resolved_sources:
                    if src_path.is_dir():
                        for file_path in src_path.rglob("*"):
                            if file_path.is_file():
                                arcname = str(file_path.relative_to(
                                    src_path.parent
                                ))
                                zf.write(str(file_path), arcname)
                                added += 1
                    else:
                        zf.write(str(src_path), src_path.name)
                        added += 1

            # Get final size.
            size = archive.stat().st_size
            size_str = self._format_size(size)
            return (
                f"Created {archive_path} ({size_str}) with {added} file(s)."
            )

        except zipfile.BadZipFile as exc:
            return f"Error: zip creation failed: {exc}"
        except OSError as exc:
            return f"Error: failed to create archive: {exc}"

    def _do_unzip(self, archive_path: str, destination: str) -> str:
        """Extract a zip archive to a destination directory."""
        import zipfile

        archive = Path(archive_path).expanduser().resolve()
        if not archive.exists():
            return f"Error: archive '{archive_path}' not found."

        dest = Path(destination).expanduser().resolve()

        try:
            # Ask for confirmation if destination is not empty.
            if dest.exists() and any(dest.iterdir()):
                if self._confirm is not None:
                    msg = (
                        f"Destination '{destination}' is not empty. "
                        "Extract anyway? (files may be overwritten)"
                    )
                    if not self._confirm(msg):
                        return "Operation declined by user."

            dest.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(str(archive), "r") as zf:
                # Check for path traversal attempts.
                for info in zf.infolist():
                    name = Path(info.filename).as_posix()
                    if ".." in name or name.startswith("/"):
                        return (
                            f"Error: archive contains unsafe path: {info.filename}"
                        )

                zf.extractall(str(dest))

            # Count extracted files and total size.
            extracted = 0
            total_size = 0
            for extracted_path in dest.rglob("*"):
                if extracted_path.is_file():
                    extracted += 1
                    total_size += extracted_path.stat().st_size

            size_str = self._format_size(total_size)
            return (
                f"Extracted {extracted} file(s) from {archive_path} "
                f"to {destination}/ ({size_str})."
            )

        except zipfile.BadZipFile:
            return f"Error: '{archive_path}' is not a valid zip file."
        except OSError as exc:
            return f"Error: failed to extract archive: {exc}"

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format a byte count into a human-readable string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def execute(self, **kwargs: object) -> str:
        """Execute an archive operation.

        Args:
            **kwargs: Must include ``action`` (str: 'zip' or 'unzip') and
                ``archive`` (str).  For 'zip', ``sources`` (str) is also
                required.  For 'unzip', ``destination`` (str) is optional.

        Returns:
            A string describing the result.
        """
        action = kwargs.get("action")
        if not isinstance(action, str) or action not in ("zip", "unzip"):
            return "Error: 'action' must be 'zip' or 'unzip'."

        archive = kwargs.get("archive")
        if not isinstance(archive, str) or not archive.strip():
            return "Error: 'archive' parameter is required."

        if action == "zip":
            sources_raw = kwargs.get("sources")
            if not isinstance(sources_raw, str) or not sources_raw.strip():
                return "Error: 'sources' parameter is required for 'zip' action."
            sources = [s.strip() for s in sources_raw.split() if s.strip()]
            return self._do_zip(archive, sources)
        else:
            destination = kwargs.get("destination")
            if not isinstance(destination, str) or not destination.strip():
                destination = "."
            return self._do_unzip(archive, destination)
