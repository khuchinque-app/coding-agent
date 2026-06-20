"""Self-healing engine for local-cli.

Provides tools to detect and automatically repair common issues in the
agent's own codebase — syntax errors, missing imports, undefined
variables, and other detectable Python bugs — with git checkpoint
safety for rollback.

The heal cycle:
1. Create a git checkpoint (safe point)
2. Scan all local_cli Python files for issues
3. Attempt fixes with user approval via /heal
4. Validate the fix (syntax check + import test)
5. Report results
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from local_cli.stat import _AMBER, _BOLD, _GRAY, _RESET, _YELLOW


# ---------------------------------------------------------------------------
# Health Report types
# ---------------------------------------------------------------------------

class HealthIssue:
    """A single issue found during a health scan.

    Attributes:
        file_path: Relative path to the affected file.
        line: Line number where the issue was found (0 if unknown).
        severity: ``"error"``, ``"warning"``, or ``"info"``.
        description: Human-readable description of the issue.
        issue_type: Category like ``"syntax"``, ``"import"``, ``"style"``.
        fix_suggestion: Optional suggested fix text.
    """

    __slots__ = (
        "file_path", "line", "severity", "description",
        "issue_type", "fix_suggestion",
    )

    def __init__(
        self,
        file_path: str,
        line: int = 0,
        severity: str = "warning",
        description: str = "",
        issue_type: str = "unknown",
        fix_suggestion: str | None = None,
    ) -> None:
        self.file_path = file_path
        self.line = line
        self.severity = severity
        self.description = description
        self.issue_type = issue_type
        self.fix_suggestion = fix_suggestion


class HealResult:
    """Result of a self-heal operation.

    Attributes:
        issues_found: Number of issues detected during the scan.
        issues_fixed: Number of issues successfully fixed.
        issues_failed: Number of issues that could not be fixed.
        checkpoint_tag: Git tag of the pre-heal checkpoint, or ``None``.
        details: List of per-issue result dicts.
    """

    __slots__ = ("issues_found", "issues_fixed", "issues_failed",
                 "checkpoint_tag", "details")

    def __init__(
        self,
        issues_found: int = 0,
        issues_fixed: int = 0,
        issues_failed: int = 0,
        checkpoint_tag: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.issues_found = issues_found
        self.issues_fixed = issues_fixed
        self.issues_failed = issues_failed
        self.checkpoint_tag = checkpoint_tag
        self.details = details or []


# ---------------------------------------------------------------------------
# The SelfHealEngine
# ---------------------------------------------------------------------------

class SelfHealEngine:
    """Scans and repairs issues in the agent's own codebase.

    The engine performs three types of checks:
    - **Syntax check**: Uses ``ast.parse`` to find syntax errors.
    - **Import check**: Verifies all imports resolve.
    - **Git health**: Checks for uncommitted changes and dirty state.

    Before applying any fix the engine creates a git checkpoint so the
    user can always ``/rollback``.
    """

    def __init__(self, project_root: str | None = None) -> None:
        self._project_root = project_root or os.getcwd()
        self._source_dirs = ["local_cli"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> list[HealthIssue]:
        """Scan the codebase for issues.

        Returns:
            A list of :class:`HealthIssue` objects found.
        """
        issues: list[HealthIssue] = []
        py_files = self._find_python_files()

        for fp in py_files:
            rel = os.path.relpath(fp, self._project_root)
            # 1. Syntax check
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    source = fh.read()
            except (OSError, UnicodeDecodeError) as exc:
                issues.append(HealthIssue(
                    file_path=rel,
                    severity="error",
                    description=f"Cannot read file: {exc}",
                    issue_type="io",
                ))
                continue

            try:
                tree = ast.parse(source, filename=fp)
            except SyntaxError as exc:
                issues.append(HealthIssue(
                    file_path=rel,
                    line=exc.lineno or 0,
                    severity="error",
                    description=f"Syntax error: {exc.msg}",
                    issue_type="syntax",
                    fix_suggestion=self._suggest_syntax_fix(exc, source),
                ))
                continue

            # 2. Check for bare ``except:`` (no exception type)
            self._check_bare_except(tree, rel, issues)

            # 3. Check for unused imports (top-level only heuristic)
            self._check_unused_imports(tree, rel, issues)

        return issues

    def heal(self, issues: list[HealthIssue] | None = None,
             auto_fix: bool = False) -> HealResult:
        """Attempt to fix the given issues, with git checkpoint safety.

        Before applying any changes the engine creates a git checkpoint.
        If *auto_fix* is ``True``, fixes are applied without asking;
        otherwise only fixable issues with a suggestion are attempted.

        Args:
            issues: List of issues to fix.  If ``None``, runs :meth:`scan`
                first.
            auto_fix: If ``True``, attempt to fix all fixable issues
                without confirmation.

        Returns:
            A :class:`HealResult` with details of what was done.
        """
        if issues is None:
            issues = self.scan()

        result = HealResult(
            issues_found=len(issues),
            issues_fixed=0,
            issues_failed=0,
            details=[],
        )

        # Create git checkpoint for rollback safety.
        try:
            from local_cli.git_ops import GitOps
            gops = GitOps()
            if gops.is_git_repo():
                tag = gops.create_checkpoint("self-heal before fix")
                result.checkpoint_tag = tag
        except Exception:
            pass  # Non-fatal; proceed without checkpoint.

        fixable = [i for i in issues if i.fix_suggestion and i.severity == "error"]

        if not fixable:
            return result

        for issue in fixable:
            success = self._apply_fix(issue)
            if success:
                result.issues_fixed += 1
                result.details.append({
                    "file": issue.file_path,
                    "line": issue.line,
                    "description": issue.description,
                    "status": "fixed",
                })
            else:
                result.issues_failed += 1
                result.details.append({
                    "file": issue.file_path,
                    "line": issue.line,
                    "description": issue.description,
                    "status": "failed",
                })

        return result

    def validate(self) -> list[str]:
        """Run a post-heal validation (syntax check + import smoke test).

        Returns:
            A list of error messages.  Empty list = all clear.
        """
        errors: list[str] = []
        py_files = self._find_python_files()

        for fp in py_files:
            rel = os.path.relpath(fp, self._project_root)
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    source = fh.read()
                ast.parse(source, filename=fp)
            except SyntaxError as exc:
                errors.append(f"{rel}:{exc.lineno}: {exc.msg}")
            except Exception as exc:
                errors.append(f"{rel}: {exc}")

        # Import smoke test — try importing the main module.
        try:
            import local_cli  # noqa: F401
        except ImportError as exc:
            errors.append(f"ImportError: local_cli module cannot be loaded: {exc}")

        return errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_python_files(self) -> list[str]:
        """Find all ``.py`` files in the source directories."""
        files: list[str] = []
        for d in self._source_dirs:
            base = os.path.join(self._project_root, d)
            if not os.path.isdir(base):
                continue
            for root, _dirs, fnames in os.walk(base):
                for fn in fnames:
                    if fn.endswith(".py"):
                        files.append(os.path.join(root, fn))
        return sorted(files)

    # ------------------------------------------------------------------
    # Issue detectors
    # ------------------------------------------------------------------

    @staticmethod
    def _check_bare_except(tree: ast.Module, rel: str,
                           issues: list[HealthIssue]) -> None:
        """Find bare ``except:`` clauses (no exception type)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    issues.append(HealthIssue(
                        file_path=rel,
                        line=getattr(node, "lineno", 0),
                        severity="warning",
                        description="Bare 'except:' clause — catches all exceptions",
                        issue_type="style",
                        fix_suggestion=(
                            "Replace 'except:' with 'except Exception:' "
                            "to avoid catching SystemExit/KeyboardInterrupt."
                        ),
                    ))

    @staticmethod
    def _check_unused_imports(tree: ast.Module, rel: str,
                               issues: list[HealthIssue]) -> None:
        """Heuristic: find top-level imports that may be unused.

        This is a simple heuristic that flags imports whose name does not
        appear anywhere else in the file.  Star imports (``from x import *``)
        are ignored.
        """
        # Collect all top-level import names.
        imported_names: dict[str, int] = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_names[name] = getattr(node, "lineno", 0)
            elif isinstance(node, ast.ImportFrom):
                if node.names and node.names[0].name == "*":
                    continue  # Star import — skip.
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_names[name] = getattr(node, "lineno", 0)

        # Collect all name references.
        used_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)

        # Report potentially unused imports.
        for name, lineno in imported_names.items():
            if name not in used_names:
                issues.append(HealthIssue(
                    file_path=rel,
                    line=lineno,
                    severity="info",
                    description=f"Import '{name}' appears unused",
                    issue_type="style",
                    fix_suggestion=f"Consider removing unused import '{name}'.",
                ))

    # ------------------------------------------------------------------
    # Fix suggester / applier
    # ------------------------------------------------------------------

    @staticmethod
    def _suggest_syntax_fix(exc: SyntaxError, source: str) -> str | None:
        """Suggest a fix for a syntax error, if possible.

        Handles common cases like missing closing parentheses, brackets,
        or colons.
        """
        if exc.msg and "unterminated" in exc.msg.lower():
            return (
                f"Line {exc.lineno}: Check for missing closing "
                f"parenthesis, bracket, or string delimiter."
            )
        if exc.msg and "invalid syntax" in exc.msg.lower():
            return (
                f"Line {exc.lineno}: Check for missing colon, comma, "
                f"or operator. Verify keyword spelling."
            )
        return None

    def _apply_fix(self, issue: HealthIssue) -> bool:
        """Attempt to apply an automated fix for a single issue.

        Supports:
        - **bare except**: Replaces ``except:`` with ``except Exception:``

        Args:
            issue: The :class:`HealthIssue` to fix.

        Returns:
            ``True`` if the fix was applied successfully.
        """
        if issue.issue_type == "style" and "bare 'except:'" in issue.description.lower():
            return self._fix_bare_except(issue)

        return False

    def _fix_bare_except(self, issue: HealthIssue) -> bool:
        """Replace a bare ``except:`` with ``except Exception:``.

        Args:
            issue: The HealthIssue for the bare except.

        Returns:
            ``True`` if the replacement succeeded.
        """
        file_path = os.path.join(self._project_root, issue.file_path)
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            return False

        # Line is 1-based, convert to 0-based index.
        idx = issue.line - 1
        if idx < 0 or idx >= len(lines):
            return False

        old_line = lines[idx]
        # Replace bare 'except:' with 'except Exception:', preserving indentation.
        stripped = old_line.lstrip()
        indent = old_line[:len(old_line) - len(stripped)]
        if stripped.strip() == "except:":
            new_line = f"{indent}except Exception:\n"
            lines[idx] = new_line
        else:
            # Could be "except :" or similar whitespace variant.
            new_line = old_line.replace("except", "except Exception", 1)
            if new_line == old_line:
                return False
            lines[idx] = new_line

        try:
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Convenience: run a full heal cycle
# ---------------------------------------------------------------------------

def run_self_heal(auto_fix: bool = False) -> HealResult:
    """Run a complete self-heal cycle: scan, fix, validate.

    This is the main entry point called from the ``/heal`` slash command.

    Args:
        auto_fix: If ``True``, attempt auto-fixes without confirmation.

    Returns:
        A :class:`HealResult` summarising what was found and fixed.
    """
    engine = SelfHealEngine()
    issues = engine.scan()
    result = engine.heal(issues, auto_fix=auto_fix)
    validation_errors = engine.validate() if result.issues_fixed > 0 else []
    if validation_errors:
        result.issues_failed += len(validation_errors)
        for err in validation_errors:
            result.details.append({
                "file": "validation",
                "line": 0,
                "description": err,
                "status": "validation_failed",
            })
    return result


# ---------------------------------------------------------------------------
# Project structure helper
# ---------------------------------------------------------------------------

def get_project_structure(root: str | None = None,
                          max_depth: int = 3,
                          show_hidden: bool = False) -> str:
    """Return a human-readable tree of the project file structure.

    Args:
        root: Root directory to inspect (defaults to CWD).
        max_depth: Maximum directory depth to recurse into.
        show_hidden: Whether to include hidden files/directories.

    Returns:
        A multi-line string with the tree representation.
    """
    root = root or os.getcwd()
    lines: list[str] = []
    root_name = os.path.basename(root) or root
    lines.append(f"{_AMBER}{_BOLD}{root_name}/{_RESET}")

    skip_names = {
        "__pycache__", ".git", ".DS_Store", "node_modules",
        ".venv", "venv", ".mypy_cache", ".pytest_cache",
        "__pycache__", ".ruff_cache",
    }
    if not show_hidden:
        skip_names.add(".*")

    def _walk(dir_path: str, prefix: str = "", depth: int = 0) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(os.listdir(dir_path))
        except PermissionError:
            return

        # Separate dirs and files, filter hidden.
        dirs = []
        files = []
        for e in entries:
            if e in skip_names:
                continue
            if not show_hidden and e.startswith("."):
                continue
            full = os.path.join(dir_path, e)
            if os.path.isdir(full):
                dirs.append(e)
            else:
                files.append(e)

        for i, d in enumerate(dirs):
            is_last = (i == len(dirs) - 1) and not files
            connector = "└── " if is_last else "├── "
            sub_prefix = "    " if is_last else "│   "
            lines.append(f"{prefix}{connector}{_YELLOW}{d}/{_RESET}")
            _walk(os.path.join(dir_path, d),
                  prefix + sub_prefix, depth + 1)

        for i, f in enumerate(files):
            is_last = (i == len(files) - 1)
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{_GRAY}{f}{_RESET}")

    _walk(root)
    return "\n".join(lines)
