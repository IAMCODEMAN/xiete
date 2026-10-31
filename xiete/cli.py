"""XIETE command line entry point.

``xiete``                        -> interactive REPL (banner + prompt_toolkit)
``xiete "your task"``            -> one-shot task execution
``xiete -m deepseek-chat "..."`` -> override model for this run

The module is intentionally defensive: missing API keys, missing dependencies
and network errors are reported through Rich panels instead of tracebacks.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from xiete import __version__
from xiete.agent import (
    API_KEY_VARS,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ConfigError,
    XieteConfig,
    build_agent,
    load_config,
    reset_agent_memory,
    resolve_system_prompt,
)
from xiete.tools import TOOL_SUMMARY
from xiete.ui import (
    console,
    error,
    error_panel,
    info,
    kv_table,
    print_banner,
    render_answer,
    render_code,
    section,
    success,
    warn,
    warning_panel,
)

#: Slash commands understood by the interactive REPL.
SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/help", "显示帮助信息"),
    ("/clear", "清屏并重绘 Logo"),
    ("/config", "查看当前 API 与模型配置"),
    ("/reset", "重置 Agent 记忆状态"),
    ("/exit", "退出 XIETE (同 /quit)"),
)

def _build_parser() -> argparse.ArgumentParser:
    """Create the argparse parser for the ``xiete`` command."""
    parser = argparse.ArgumentParser(
        prog="xiete",
        description="XIETE - terminal AI coding agent powered by smolagents CodeAgent.",
        epilog=(
            "Examples:\n"
            '  xiete                          # interactive REPL\n'
            '  xiete "给 utils.py 加上单元测试"   # one-shot task\n'
            '  xiete -m deepseek-chat "解释这个项目结构"\n'
            '  echo "list files" | xiete       # read a single task from stdin'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("task", nargs="*", help="Task description to execute once, then exit.")
    parser.add_argument("-m", "--model", help=f"Model id override (env XIETE_MODEL, default {DEFAULT_MODEL}).")
    parser.add_argument("-b", "--base-url", help=f"OpenAI compatible base URL (default {DEFAULT_BASE_URL}).")
    parser.add_argument("-k", "--api-key", help="API key override (prefer env vars / .env over this flag).")
    parser.add_argument("--max-steps", type=int, help="Maximum agent reasoning steps (default 40).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show smolagents internal step logs.")
    parser.add_argument("--version", action="version", version=f"xiete {__version__}")
    return parser


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def _missing_key_help(config: XieteConfig) -> None:
    """Explain how to configure an API key, then let the user continue or exit."""
    searched = ", ".join(str(p) for p in config.env_files) if config.env_files else "未发现 .env 文件"
    body = (
        f"未检测到 API Key，XIETE 无法调用模型，但 CLI 仍可正常启动。\n\n"
        f"需配置以下任一环境变量： [bold white]{' 或 '.join(API_KEY_VARS)}[/bold white]\n"
        f"已查找的 .env： [grey62]{searched}[/grey62]\n\n"
        "[bold]方式一 · 项目级 .env（推荐）[/bold]\n"
        "  [green]Copy-Item .env.example .env[/green]   然后填写（Base URL 与 Model 默认已适配 DeepSeek）:\n"
        "  [green]XIETE_API_KEY=sk-xxxx[/green]                  ← 在 platform.deepseek.com 申请\n"
        "  [green]XIETE_BASE_URL=https://api.deepseek.com[/green]\n"
        "  [green]XIETE_MODEL=deepseek-flash[/green]             ← DeepSeek-V4.1-Flash\n\n"
        "[bold]方式二 · 系统环境变量[/bold]\n"
        "  [green]PowerShell:[/green]  $env:XIETE_API_KEY=\"sk-xxxx\"\n"
        "  [green]Bash/Zsh:  [/green]  export XIETE_API_KEY=sk-xxxx\n\n"
        "[grey62]提示：本地 Ollama / vLLM 等服务可填任意占位 key，例如 XIETE_API_KEY=ollama[/grey62]"
    )
    warning_panel("缺少 API Key", body)


def _load_session_config(args: argparse.Namespace) -> tuple[XieteConfig | None, bool]:
    """Load configuration and report problems without raising.

    Returns:
        ``(config, ok)`` where ``ok`` is ``False`` if the config is unusable.
    """
    try:
        config = load_config(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            max_steps=args.max_steps,
        )
    except ConfigError as exc:
        error_panel("配置错误", f"{exc}\n\n[grey62]请检查 .env 或环境变量后重试。[/grey62]")
        return None, False

    if not config.has_api_key:
        _missing_key_help(config)
        return config, False
    return config, True


def _describe_config(config: XieteConfig) -> kv_table:  # type: ignore[valid-type]
    """Render the ``/config`` table."""
    rows = config.as_rows()
    try:
        _, prompt_source = resolve_system_prompt(config.workspace)
    except ConfigError as exc:
        prompt_source = f"error: {exc}"
    rows.extend(
        [
            ("Agent engine", "smolagents CodeAgent"),
            ("Tools", ", ".join(name for name, _ in TOOL_SUMMARY)),
            ("System prompt", prompt_source),
            ("Version", f"v{__version__}"),
        ]
    )
    return kv_table(rows)


def _banner_kwargs(config: XieteConfig | None, agent_ready: bool) -> dict[str, Any]:
    """Assemble the keyword arguments for the startup banner."""
    if config is None:
        return {
            "cwd": os.getcwd(),
            "model_name": None,
            "has_api_key": False,
        }
    return {
        "cwd": str(config.workspace),
        "model_name": config.model if agent_ready else f"{config.model} (offline)",
        "base_url": config.base_url,
        "has_api_key": config.has_api_key,
        "max_steps": config.max_steps,
        "tools": [name for name, _ in TOOL_SUMMARY],
    }


# ---------------------------------------------------------------------------
# Agent construction and task execution
# ---------------------------------------------------------------------------
def _create_agent(config: XieteConfig, verbose: bool) -> Any | None:
    """Create the CodeAgent, reporting failures as panels."""
    try:
        return build_agent(config, verbosity_level=1 if verbose else 0)
    except ConfigError as exc:
        error_panel("Agent 初始化失败", str(exc))
    except ImportError as exc:
        error_panel("缺少依赖", f"{exc}\n\n[grey62]请执行: pip install -e .[/grey62]")
    except Exception as exc:  # pragma: no cover - defensive
        error_panel("Agent 初始化异常", f"{type(exc).__name__}: {exc}")
    return None


def _friendly_error(exc: BaseException) -> str:
    """Turn a raw exception into an actionable message."""
    name = type(exc).__name__
    text = str(exc)
    lowered = text.lower()
    if "tool_choice" in lowered and ("thinking" in lowered or "required" in lowered):
        return (
            f"{name}: DeepSeek 思考模式拒绝了 tool_choice 参数。\n"
            "请确认 XIETE_MODEL 以 deepseek 开头（如 deepseek-flash），"
            "或设置 XIETE_THINKING=disabled 关闭思考模式。"
        )
    if "reasoning_content" in lowered:
        return (
            f"{name}: DeepSeek 要求回传 reasoning_content。\n"
            "请升级 XIETE 到最新版本，或设置 XIETE_THINKING=disabled 关闭思考模式。"
        )
    if "authentication" in lowered or "401" in text or "invalid api key" in lowered or "incorrect api key" in lowered:
        return (
            f"{name}: API Key 无效或已过期。\n"
            f"请检查 .env / 环境变量中的 {API_KEY_VARS[0]}，"
            "并确认 XIETE_BASE_URL 为 https://api.deepseek.com"
        )
    if "insufficient" in lowered or "balance" in lowered or "quota" in lowered:
        return f"{name}: 账户余额/额度不足。\n请到 DeepSeek 开放平台充值后重试。"
    if "model" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return (
            f"{name}: 模型不存在。\n"
            "当前可用模型名为 deepseek-flash（V4.1-Flash）或 deepseek-v4-pro，"
            "请检查 XIETE_MODEL。"
        )
    if "connection" in lowered or "connect" in lowered or "timeout" in lowered or "timed out" in lowered:
        return (
            f"{name}: 无法连接到 API 服务。\n"
            "请检查网络、代理设置与 XIETE_BASE_URL；思考模式较慢时可调大 XIETE_TIMEOUT。"
        )
    if "rate limit" in lowered or "429" in text:
        return f"{name}: 触发服务商限流，请稍后重试或降低并发。"
    return f"{name}: {text}"


def run_task(agent: Any, task: str, *, show_spinner: bool = True) -> str | None:
    """Execute one task with the agent, handling Ctrl+C gracefully.

    Args:
        agent: A smolagents ``CodeAgent``.
        task: Natural language task description.
        show_spinner: Whether to show the Rich status spinner.

    Returns:
        The final answer string, or ``None`` if the task was interrupted/failed.
    """
    console.print(section("Task"))
    console.print(f"[white]{task.strip()}[/white]")
    console.print()

    started = time.monotonic()
    status = console.status("[xiete.brand]XIETE 正在推理…[/xiete.brand]", spinner="dots")
    answer: Any = None
    try:
        if show_spinner:
            status.start()
        answer = agent.run(task)
    except KeyboardInterrupt:
        if show_spinner:
            status.stop()
        console.print()
        warn("已中断当前任务（Ctrl+C）。Agent 记忆已保留，可继续提问。")
        return None
    except EOFError:
        if show_spinner:
            status.stop()
        console.print()
        warn("输入流已关闭，任务被中断。")
        return None
    except Exception as exc:
        if show_spinner:
            status.stop()
        console.print()
        error_panel("任务执行失败", _friendly_error(exc))
        return None
    finally:
        if show_spinner:
            status.stop()

    elapsed = time.monotonic() - started
    console.print()
    text = _stringify_answer(answer)
    console.print(render_answer(text))
    console.print(f"[grey42]completed in {elapsed:.1f}s[/grey42]")
    return text


def _stringify_answer(answer: Any) -> str:
    """Convert an arbitrary agent output into Markdown text."""
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer
    return str(answer)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------
def show_help() -> None:
    """Print the interactive help table."""
    from rich.table import Table

    table = Table(title="XIETE 交互命令", title_style="xiete.brand", box=None, padding=(0, 2))
    table.add_column("命令", style="xiete.key", no_wrap=True)
    table.add_column("说明", style="white")
    for command, description in SLASH_COMMANDS:
        table.add_row(command, description)
    console.print(section("/help"))
    console.print(table)
    console.print()
    tools = Table(title="已挂载工具", title_style="xiete.brand", box=None, padding=(0, 2))
    tools.add_column("工具", style="xiete.key", no_wrap=True)
    tools.add_column("说明", style="white")
    for name, description in TOOL_SUMMARY:
        tools.add_row(name, description)
    console.print(tools)
    console.print()
    info("[grey62]直接输入自然语言即可下发任务；Ctrl+C 中断当前任务，Ctrl+D 退出。[/grey62]")
    info("[grey62]单次模式：xiete \"你的任务\"   其他选项：xiete --help[/grey62]")


def show_config(config: XieteConfig | None) -> None:
    """Print the current API/model configuration."""
    console.print(section("/config"))
    if config is None:
        warn("配置尚未加载。请检查 .env 或环境变量后重启 XIETE。")
        return
    console.print(_describe_config(config))
    if not config.has_api_key:
        warn(f"尚未配置 API Key：请在 .env 中设置 {' 或 '.join(API_KEY_VARS)}。")
    else:
        success("配置已就绪。")


def handle_slash_command(command: str, *, config: XieteConfig | None, agent: Any | None) -> str:
    """Execute a slash command.

    Args:
        command: The raw line starting with ``/``.
        config: Current configuration, may be ``None``.
        agent: Current agent instance, may be ``None``.

    Returns:
        One of ``"continue"``, ``"exit"``, ``"clear"`` (handled by the caller).
    """
    name = command.strip().split(maxsplit=1)[0].lower()
    if name in {"/exit", "/quit", "/q"}:
        return "exit"
    if name == "/help":
        show_help()
    elif name == "/clear":
        return "clear"
    elif name in {"/config", "/cfg"}:
        show_config(config)
    elif name == "/reset":
        if agent is None:
            warn("Agent 尚未初始化，无可重置的记忆。")
        elif reset_agent_memory(agent):
            success("Agent 记忆已重置，对话上下文已清空。")
        else:
            warn("未能重置 Agent 记忆（当前 smolagents 版本不支持）。")
    else:
        warn(f"未知命令：{name}")
        info("可用命令： " + "  ".join(cmd for cmd, _ in SLASH_COMMANDS))
    return "continue"


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------
class ReplSession:
    """Holds the state of one interactive session."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.config: XieteConfig | None = None
        self.agent: Any = None
        self.agent_ready = False

    # -- lifecycle ---------------------------------------------------------
    def boot(self) -> None:
        """Load configuration, build the agent, then draw the banner."""
        config, ok = _load_session_config(self.args)
        self.config = config
        if ok and config is not None:
            self.agent = _create_agent(config, self.args.verbose)
            self.agent_ready = self.agent is not None
        print_banner(**_banner_kwargs(self.config, self.agent_ready))
        if self.agent_ready and self.config is not None:
            info(
                f"Agent 已就绪 [grey62]→[/grey62] [xiete.accent]{self.config.model}[/xiete.accent] "
                f"[grey62]@ {self.config.base_url}[/grey62]"
            )
        console.print()

    def redraw(self) -> None:
        """Clear the screen and re-render the banner."""
        print_banner(**_banner_kwargs(self.config, self.agent_ready))
        console.print()

    # -- prompt ------------------------------------------------------------
    def _make_prompt(self) -> Any:
        """Build the prompt_toolkit session with persistent history.

        prompt_toolkit needs a real terminal on stdin; when stdin is a pipe we
        fall back to plain ``input()`` so scripted sessions work.

        Returns:
            A ``PromptSession``, or ``None`` to use the plain input fallback.
        """
        if _stdin_is_piped():
            return None
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.styles import Style
        except ImportError:  # pragma: no cover - fallback to plain input()
            return None

        history_path = _history_file()
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(history_path))
        except OSError:  # pragma: no cover - read-only home
            from prompt_toolkit.history import InMemoryHistory

            history = InMemoryHistory()

        style = Style.from_dict({"prompt": "ansicyan bold", "prompt.marker": "ansimagenta bold"})
        try:
            return PromptSession(
                history=history,
                style=style,
                complete_while_typing=False,
                enable_history_search=True,
                message=[("class:prompt.marker", "❯ "), ("class:prompt", "xiete "), ("", "")],
            )
        except Exception as exc:  # noqa: BLE001 - e.g. NoConsoleScreenBufferError on Windows
            warn(f"prompt_toolkit 不可用（{type(exc).__name__}），已切换为基础输入模式。")
            return None

    def read_input(self, session: Any) -> str | None:
        """Read one line of user input, tolerating Ctrl+C and Ctrl+D.

        Falls back to a plain ``input()`` prompt when prompt_toolkit cannot take
        over the terminal (no console buffer on Windows, exotic terminals, ...).

        Returns:
            The stripped input, or ``None`` if the user asked to exit.
        """
        while True:
            try:
                if session is not None:
                    try:
                        raw = session.prompt()
                    except KeyboardInterrupt:
                        raise
                    except EOFError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - e.g. NoConsoleScreenBufferError
                        warn(f"prompt_toolkit 不可用（{type(exc).__name__}），已切换为基础输入模式。")
                        session = None
                        continue
                else:
                    console.print("[xiete.prompt]❯ xiete[/xiete.prompt]", end=" ")
                    console.file.flush()
                    raw = input()
            except KeyboardInterrupt:
                console.print()
                info("[grey62]输入 /exit 或按 Ctrl+D 退出，输入 /help 查看帮助。[/grey62]")
                continue
            except EOFError:
                console.print()
                return None
            return raw.strip()

    # -- main loop ---------------------------------------------------------
    def run(self) -> int:
        """Run the REPL until the user exits."""
        session = self._make_prompt()
        while True:
            line = self.read_input(session)
            if line is None:
                console.print("[grey42]再见 👋[/grey42]")
                return 0
            if not line:
                continue
            if line.startswith("/"):
                action = handle_slash_command(line, config=self.config, agent=self.agent)
                if action == "exit":
                    console.print("[grey42]再见 👋[/grey42]")
                    return 0
                if action == "clear":
                    self.redraw()
                console.print()
                continue

            if self.agent is None:
                self._try_build_agent()
            if self.agent is None:
                continue
            run_task(self.agent, line)
            console.print()

    def _try_build_agent(self) -> None:
        """Attempt to (re)build the agent, e.g. after the user fixed the config."""
        # Reload so a freshly created .env takes effect without restarting.
        config, ok = _load_session_config(self.args)
        self.config = config
        if not ok or config is None:
            warn("Agent 仍不可用：请先配置 API Key，然后再次输入任务或重启 XIETE。")
            console.print()
            return
        self.agent = _create_agent(config, self.args.verbose)
        self.agent_ready = self.agent is not None
        if self.agent_ready and config is not None:
            success(f"Agent 已就绪：{config.model} @ {config.base_url}")
            console.print()


def _history_file() -> Path:
    """Return the history file path, honouring ``XDG_STATE_HOME`` on POSIX."""
    override = os.environ.get("XIETE_HISTORY_FILE")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home())
        return base / "xiete" / "history"
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "xiete" / "history"


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def config_workspace() -> Path:
    """Return the workspace root that tools are sandboxed to.

    Returns:
        The absolute path of the directory XIETE was launched from.
    """
    return Path.cwd().resolve()


def _stdin_is_piped() -> bool:
    """Whether stdin is a pipe (so interactive prompting is impossible)."""
    try:
        return not sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover
        return False


def _read_piped_task() -> str:
    """Read a single task from stdin."""
    try:
        return sys.stdin.read().strip()
    except (OSError, UnicodeDecodeError):  # pragma: no cover
        return ""


def run_once(task: str, args: argparse.Namespace) -> int:
    """Execute a single task, non-interactively.

    Returns:
        Process exit code (``0`` success, ``1`` failure, ``130`` interrupted).
    """
    config, ok = _load_session_config(args)
    if not ok or config is None:
        return 1
    agent = _create_agent(config, args.verbose)
    if agent is None:
        return 1
    result = run_task(agent, task)
    if result is None:
        return 130
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point registered as the ``xiete`` console script.

    Args:
        argv: Argument vector override (used by tests). Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:  # --help / --version
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)

    task_text = " ".join(args.task).strip()
    interactive = not task_text

    if interactive and _stdin_is_piped():
        # e.g. ``echo "task" | xiete`` or ``xiete < task.txt``
        piped = _read_piped_task()
        if piped:
            task_text = piped
            interactive = False
        else:
            error("未收到任务内容，且标准输入不是交互终端。")
            info("用法：xiete \"你的任务\"，或直接运行 xiete 进入交互模式。")
            return 1

    # Keep the workspace root aligned with the directory XIETE was launched from.
    os.chdir(config_workspace())

    if interactive:
        session = ReplSession(args)
        try:
            session.boot()
            return session.run()
        except KeyboardInterrupt:
            console.print()
            console.print("[grey42]已退出 XIETE。[/grey42]")
            return 0
        except Exception as exc:  # pragma: no cover - last resort
            console.print()
            error_panel("XIETE 异常退出", _friendly_error(exc))
            return 1

    console.clear()
    print_banner(**_banner_kwargs(_safe_config(args), True))
    console.print()
    code = run_once(task_text, args)
    return code


def _safe_config(args: argparse.Namespace) -> XieteConfig | None:
    """Load config for banner purposes only; never raises."""
    try:
        return load_config(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            max_steps=args.max_steps,
        )
    except Exception:  # pragma: no cover - banner must never crash
        return None


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
