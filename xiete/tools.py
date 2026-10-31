"""Local tool set for the XIETE coding agent.

Every tool is a plain function decorated with ``smolagents.tool``. smolagents
builds the tool's JSON schema from the function *type hints* and its *Google
style docstring* (an ``Args:`` block is mandatory, otherwise schema parsing
raises ``DocstringParsingException``).

Security model for v0.1.0
-------------------------
* Every path is resolved through :func:`_resolve_path`, which pins relative
  paths to the session working directory and refuses to escape it.
* ``run_shell_command`` is run without a shell (``shell=False``), with a hard
  30 second timeout and a block-list for destructive commands.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Union

from smolagents import tool

#: Default timeout (seconds) for shell commands.
SHELL_TIMEOUT_SECONDS: int = 30

#: Maximum number of characters any single tool result may return.
MAX_OUTPUT_CHARS: int = 30_000

#: Directories that are never walked when listing a directory.
_IGNORED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
        ".idea",
        ".vscode",
        "dist",
        "build",
        ".egg-info",
    }
)

#: File extensions that are treated as binary and refused by ``read_file``.
_BINARY_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".rar",
        ".7z",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".pyc",
        ".pyo",
        ".pyd",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
        ".db",
        ".sqlite",
    }
)

#: High risk command patterns, matched case-insensitively against the full
#: command line. Each entry is ``(compiled_pattern, human_reason)``.
_DANGEROUS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in (
        (r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+", "recursive/forced file deletion"),
        (r"\brm\s+-\w*[rf]\w*\s+.*(\s/|\s~|\s\*|\.\.)", "deletion of root/home/glob paths"),
        (r"\b(mkfs|mke2fs|fdisk|parted|diskpart)(\.\w+)?\b", "disk formatting/partitioning"),
        (r"\bdd\s+.*\bof=", "raw disk writing via dd"),
        (r":\(\)\s*\{\s*:\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
        (r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b", "system shutdown/reboot"),
        (r"\bgit\s+push\s+.*(--force|-f)\b", "force pushing git history"),
        (r"\bgit\s+clean\s+-[a-z]*[xfd]", "destructive git clean"),
        (r"\bgit\s+reset\s+--hard\b", "destructive git reset"),
        (r"\bchmod\s+-R\s+777\b", "world-writable recursive permission change"),
        (r"\bchown\s+-R\b", "recursive ownership change"),
        (r"\bdel\s+/[sf]\b", "Windows forced/silent deletion"),
        (r"\b(rd|rmdir)\s+/s\b", "Windows recursive directory removal"),
        (r"\bformat\s+[a-z]:", "Windows drive formatting"),
        (r"\bRemove-Item\b.*-Recurse", "PowerShell recursive deletion"),
        (r"\b(Invoke-Expression|iex)\b", "execution of dynamically fetched code"),
        (r"\bcurl\b[^|]*\|\s*(ba)?sh\b", "piping remote script into a shell"),
        (r"\bwget\b[^|]*\|\s*(ba)?sh\b", "piping remote script into a shell"),
        (r">\s*/dev/(sd|nvme|disk)", "writing directly to a block device"),
        (r"\bhistory\s+-c\b", "clearing shell history"),
    )
)

#: Session working directory. Set by :func:`configure_tools` from the CLI; the
#: default keeps the tools usable when imported standalone (e.g. in tests).
_WORKSPACE_ROOT: Path = Path.cwd().resolve()

#: Explicit user safe-list. Any command whose first token matches an entry is
#: allowed even if it would otherwise trip a heuristic block rule.
_ALLOWED_COMMANDS: frozenset[str] = frozenset()

#: Set to ``False`` by ``/config``-style toggles if the user wants read-only mode.
_WRITE_ENABLED: bool = True


# ---------------------------------------------------------------------------
# Public configuration hooks (used by the CLI / agent factory)
# ---------------------------------------------------------------------------
def configure_tools(
    workspace: Union[str, Path, None] = None,
    allow_write: bool = True,
    allow_commands: Union[list[str], tuple[str, ...], None] = None,
) -> None:
    """Configure the process-wide sandbox used by every XIETE tool.

    Args:
        workspace: Directory all relative paths are resolved against. ``None``
            keeps the current setting.
        allow_write: When ``False``, ``write_file`` refuses to modify files.
        allow_commands: Extra command names that bypass the heuristic shell
            block-list (e.g. ``["rm"]`` for a trusted scratch directory).
    """
    global _WORKSPACE_ROOT, _WRITE_ENABLED, _ALLOWED_COMMANDS
    if workspace is not None:
        _WORKSPACE_ROOT = Path(workspace).expanduser().resolve()
    _WRITE_ENABLED = bool(allow_write)
    if allow_commands is not None:
        _ALLOWED_COMMANDS = frozenset(str(name).strip().lower() for name in allow_commands if str(name).strip())


def get_workspace_root() -> Path:
    """Return the working directory that every tool resolves paths against.

    Returns:
        The absolute, resolved workspace root path.
    """
    return _WORKSPACE_ROOT


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Clamp ``text`` to ``limit`` characters with an explicit notice."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    return f"{head}\n\n... [output truncated: showing {limit} of {len(text)} characters]"


def _resolve_path(file_path: str, *, must_exist: bool = False) -> Path:
    """Resolve a user supplied path inside the workspace sandbox.

    Args:
        file_path: Absolute or workspace-relative path.
        must_exist: When ``True`` a missing target raises ``FileNotFoundError``.

    Returns:
        The resolved absolute :class:`pathlib.Path`.

    Raises:
        ValueError: If the path escapes the workspace root.
        FileNotFoundError: If ``must_exist`` is set and the path is missing.
    """
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("file path must be a non-empty string")

    candidate = Path(file_path).expanduser()
    if not candidate.is_absolute():
        candidate = _WORKSPACE_ROOT / candidate
    resolved = candidate.resolve()

    root = _WORKSPACE_ROOT
    if resolved != root and root not in resolved.parents:
        raise ValueError(
            f"Path '{file_path}' is outside the workspace root '{root}'. "
            "XIETE tools are restricted to the current working directory."
        )

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"Path not found: {file_path} (resolved to {resolved})")
    return resolved


def _relative_display(path: Path) -> str:
    """Render ``path`` relative to the workspace root when possible."""
    try:
        return path.relative_to(_WORKSPACE_ROOT).as_posix() or "."
    except ValueError:  # pragma: no cover - defensive, paths are pre-validated
        return str(path)


def _is_probably_binary(path: Path) -> bool:
    """Heuristically decide whether ``path`` holds binary content."""
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return True
    try:
        chunk = path.open("rb").read(4096)
    except OSError:
        return False
    if b"\x00" in chunk:
        return True
    return False


def _build_tree(root: Path, max_depth: int, name_filter: str | None) -> list[str]:
    """Walk ``root`` and render an indented tree."""
    lines: list[str] = []
    pattern = re.compile(name_filter, re.IGNORECASE) if name_filter else None
    counters = {"files": 0, "dirs": 0}

    def walk(directory: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(
                directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except PermissionError:
            lines.append(f"{prefix}[permission denied]")
            return

        visible = [
            entry
            for entry in entries
            if entry.name not in _IGNORED_DIR_NAMES and not entry.name.endswith(".egg-info")
        ]
        for index, entry in enumerate(visible):
            is_last = index == len(visible) - 1
            branch = "└── " if is_last else "├── "
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            suffix = "/" if is_dir else ""
            if pattern and not pattern.search(entry.name):
                # Still descend into directories so nested matches are findable.
                if is_dir:
                    walk(entry, prefix + ("    " if is_last else "│   "), depth + 1)
                continue
            lines.append(f"{prefix}{branch}{entry.name}{suffix}")
            if is_dir:
                counters["dirs"] += 1
                walk(entry, prefix + ("    " if is_last else "│   "), depth + 1)
            else:
                counters["files"] += 1

    walk(root, "", 1)
    lines.append(
        f"\n({counters['files']} files, {counters['dirs']} directories, "
        f"max depth {max_depth}, ignored: .git, .venv, __pycache__, node_modules, ...)"
    )
    return lines


def _split_command(command: str) -> list[str]:
    """Split a command line into an argv list.

    On POSIX ``shlex.split`` handles quoting as the user expects. On Windows it
    would keep the quotes in the tokens *and* treat backslashes as escapes, which
    breaks paths like ``C:\\Python\\python.exe`` -- so we use the Windows rule set
    there (double quotes group, backslashes are literal).
    """
    try:
        if os.name == "nt":
            return shlex.split(command, posix=False)
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _unquote(token: str) -> str:
    """Strip one layer of surrounding double/single quotes from ``token``."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def _check_command(command: str) -> str | None:
    """Return a rejection reason when ``command`` looks destructive."""
    lowered = command.strip().lower()
    tokens = [_unquote(token) for token in _split_command(command)]
    if tokens:
        first = Path(tokens[0]).name.lower()
        if first.endswith(".exe"):
            first = first[:-4]
        if first in _ALLOWED_COMMANDS:
            return None
    for pattern, reason in _DANGEROUS_PATTERNS:
        if pattern.search(lowered):
            return reason
    return None


def _working_directory() -> Path:
    """Return the directory shell commands should execute in."""
    root = _WORKSPACE_ROOT
    return root if root.is_dir() else Path.cwd()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool
def read_file(file_path: str, max_lines: Union[int, None] = None) -> str:
    """Read the full text content of a local file and return it.

    Use this before editing a file so you know its exact current content.
    Binary files (images, archives, compiled binaries) are rejected.

    Args:
        file_path: Path of the file to read, relative to the workspace root or absolute inside it.
        max_lines: Optional maximum number of lines to return, counted from the top of the file.

    Returns:
        The file content as UTF-8 text, prefixed with a one line header showing the path and line count.
    """
    path = _resolve_path(file_path, must_exist=True)
    if path.is_dir():
        raise IsADirectoryError(f"'{_relative_display(path)}' is a directory; use list_directory instead.")
    if _is_probably_binary(path):
        raise ValueError(f"'{_relative_display(path)}' looks like a binary file and cannot be read as text.")

    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]

    lines = text.splitlines()
    total_lines = len(lines)
    if max_lines is not None and max_lines > 0 and total_lines > max_lines:
        body = "\n".join(lines[:max_lines])
        header = (
            f"# {_relative_display(path)} (showing first {max_lines} of {total_lines} lines, "
            f"{len(raw)} bytes)\n"
        )
        return _truncate(header + body + "\n... [more lines omitted]")

    header = f"# {_relative_display(path)} ({total_lines} lines, {len(raw)} bytes)\n"
    return _truncate(header + text)


@tool
def write_file(file_path: str, content: str) -> str:
    """Create a new file or fully overwrite an existing file with the given content.

    Parent directories are created automatically. Use this for new files; for
    surgical edits prefer rewriting the whole file with up to date content.

    Args:
        file_path: Target path, relative to the workspace root or absolute inside it.
        content: Complete text content to write (UTF-8). An empty string creates or truncates the file.

    Returns:
        A short confirmation message with the resolved path, bytes written and line count.
    """
    if not _WRITE_ENABLED:
        raise PermissionError("Writing files is disabled for this session (read-only mode).")
    if not isinstance(content, str):
        raise TypeError("content must be a string")

    path = _resolve_path(file_path)
    if path.exists() and path.is_dir():
        raise IsADirectoryError(f"'{_relative_display(path)}' is a directory, cannot overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)

    existed = path.exists()
    data = content.encode("utf-8")
    path.write_bytes(data)
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    action = "Updated" if existed else "Created"
    return f"{action} '{_relative_display(path)}' ({len(data)} bytes, {line_count} lines)."


@tool
def list_directory(dir_path: str = ".", max_depth: int = 2, name_filter: Union[str, None] = None) -> str:
    """List files and folders under a directory as an indented tree.

    Heavy or irrelevant folders (.git, node_modules, __pycache__, virtualenvs)
    are skipped automatically.

    Args:
        dir_path: Directory to inspect, relative to the workspace root or absolute inside it. Defaults to the workspace root.
        max_depth: How many directory levels to recurse into, between 1 and 6.
        name_filter: Optional case-insensitive regular expression; only entries whose name matches are shown (directories are still walked to find nested matches).

    Returns:
        A tree rendering of the directory followed by a summary line.
    """
    path = _resolve_path(dir_path, must_exist=True)
    if not path.is_dir():
        raise NotADirectoryError(f"'{_relative_display(path)}' is not a directory.")

    depth = max(1, min(int(max_depth), 6))
    if name_filter:
        try:
            re.compile(name_filter)
        except re.error as exc:
            raise ValueError(f"name_filter is not a valid regular expression: {exc}") from exc

    header = f"Workspace tree for '{_relative_display(path)}':"
    tree = _build_tree(path, depth, name_filter)
    return _truncate(header + "\n" + "\n".join(tree))


@tool
def run_shell_command(command: str) -> str:
    """Run a terminal command in the workspace and return its stdout and stderr.

    Commands run without a shell, so shell syntax such as pipes, redirects,
    ``&&`` or glob expansion is not interpreted. Destructive commands (recursive
    deletion, disk formatting, force push, ...) are blocked, and every command is
    killed after 30 seconds.

    Args:
        command: The full command line to execute, for example "python --version" or "pytest -q tests/".

    Returns:
        A report containing the exit code, execution duration, stdout and stderr.
    """
    import time

    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")

    reason = _check_command(command)
    if reason is not None:
        return (
            f"BLOCKED: refusing to run '{command}'.\n"
            f"Reason: this command matches a high risk pattern ({reason}).\n"
            "Ask the user to run it manually if it is really required."
        )

    try:
        argv = [_unquote(token) for token in _split_command(command)]
    except ValueError as exc:
        raise ValueError(f"Could not parse command: {exc}") from exc
    if not argv:
        raise ValueError(f"Could not parse any executable from command: {command!r}")

    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell disabled on purpose
            argv,
            cwd=str(_working_directory()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SHELL_TIMEOUT_SECONDS,
            shell=False,
            stdin=subprocess.DEVNULL,
            env={**_child_env()},
        )
    except KeyboardInterrupt:
        raise
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        partial_out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return (
            f"TIMEOUT: '{command}' exceeded the {SHELL_TIMEOUT_SECONDS}s limit and was killed "
            f"(after {elapsed:.1f}s).\n"
            f"Partial stdout:\n{_truncate(partial_out)}"
        )
    except FileNotFoundError:
        return (
            f"COMMAND NOT FOUND: '{argv[0]}' is not available on PATH in this environment. "
            "Try a different executable or ask the user."
        )
    except PermissionError:
        return f"PERMISSION DENIED: '{argv[0]}' is not executable."
    except OSError as exc:
        return f"FAILED TO START: '{command}' raised {type(exc).__name__}: {exc}"

    elapsed = time.monotonic() - started
    stdout = (completed.stdout or "").rstrip()
    stderr = (completed.stderr or "").rstrip()
    parts = [
        f"$ {command}",
        f"exit code: {completed.returncode}",
        f"duration: {elapsed:.2f}s",
    ]
    parts.append("stdout:\n" + (stdout if stdout else "<empty>"))
    if stderr:
        parts.append("stderr:\n" + stderr)
    return _truncate("\n".join(parts))


def _child_env() -> dict[str, str]:
    """Build a child process environment with non-interactive defaults."""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    # Keep interactive pagers/colours from polluting captured output.
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("NO_COLOR", "1")
    return env


#: Tools injected into the ``CodeAgent``, in prompt order.
DEFAULT_TOOLS = [read_file, write_file, list_directory, run_shell_command]

#: Human readable summary used by ``/help`` and ``/config``.
TOOL_SUMMARY: tuple[tuple[str, str], ...] = (
    ("read_file", "读取本地文件内容"),
    ("write_file", "创建/覆盖写入文件（自动建父目录）"),
    ("list_directory", "查看目录树结构"),
    ("run_shell_command", "执行终端命令（30s 超时 + 高危拦截）"),
)


__all__ = [
    "DEFAULT_TOOLS",
    "SHELL_TIMEOUT_SECONDS",
    "TOOL_SUMMARY",
    "configure_tools",
    "get_workspace_root",
    "list_directory",
    "read_file",
    "run_shell_command",
    "write_file",
]
