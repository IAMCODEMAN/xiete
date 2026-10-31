"""Rendering layer for XIETE: ASCII logo, banner panel and Rich style helpers.

Everything that touches *how the CLI looks* lives here. To rebrand the tool you
only need to replace :data:`XIETE_LOGO` (and optionally :data:`XIETE_TAGLINE`)
-- no other module knows about the artwork.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Iterable, Sequence

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from xiete import __version__

# ---------------------------------------------------------------------------
# ============================ LOGO (REPLACE ME) ============================
# ---------------------------------------------------------------------------
# 下面是 HOLYXIETE 的 ASCII Art 字符画，风格为 ANSI Shadow（硬朗、现代的块状字体）。
#
# 想换成你自己的设计时：
#   1. 直接把下面的字符串字面量整体替换成你的字符画；
#   2. 保持每行长度尽量一致（渲染时会按字符列自动做金色渐变）；
#   3. 不要使用 Tab，避免宽度不一致；建议 7 行以内，宽度 <= 80 列；
#   4. 特殊字符（如 `[`、`]`）会被当作普通文本渲染，无需转义。
#
# 生成器推荐：https://patorjk.com/software/taag/ （字体选 "ANSI Shadow"）
# ---------------------------------------------------------------------------
XIETE_LOGO: str = r"""
██╗  ██╗ ██████╗ ██╗     ██╗   ██╗██╗  ██╗██╗███████╗████████╗███████╗
██║  ██║██╔═══██╗██║     ╚██╗ ██╔╝╚██╗██╔╝██║██╔════╝╚══██╔══╝██╔════╝
███████║██║   ██║██║      ╚████╔╝  ╚███╔╝ ██║█████╗     ██║   █████╗
██╔══██║██║   ██║██║       ╚██╔╝   ██╔██╗ ██║██╔══╝     ██║   ██╔══╝
██║  ██║╚██████╔╝███████╗   ██║   ██╔╝ ██╗██║███████╗   ██║   ███████╗
╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚══════╝   ╚═╝   ╚══════╝
"""
# ---------------------------------------------------------------------------
# ========================== END OF LOGO SECTION ============================
# ---------------------------------------------------------------------------

#: One line slogan printed under the logo.
XIETE_TAGLINE: str = "HOLYXIETE · Terminal AI Coding Agent · powered by smolagents"

#: Gradient endpoints used for the logo (start -> end). Golden-toned palette.
LOGO_GRADIENT: tuple[str, str] = ("#ffe066", "#c8912a")

#: Shortcut hints shown inside the banner panel.
SHORTCUT_HINTS: tuple[tuple[str, str], ...] = (
    ("Enter", "发送指令"),
    ("↑ / ↓", "历史记录"),
    ("Ctrl+C", "中断当前任务"),
    ("Ctrl+D", "退出"),
)


class XieteTheme(Theme):
    """Rich theme shared by the whole CLI."""

    def __init__(self) -> None:
        super().__init__(
            {
                "xiete.logo": "bold",
                "xiete.brand": "bold cyan",
                "xiete.accent": "bold magenta",
                "xiete.dim": "dim",
                "xiete.key": "bold cyan",
                "xiete.value": "white",
                "xiete.ok": "bold green",
                "xiete.warn": "bold yellow",
                "xiete.error": "bold red",
                "xiete.info": "cyan",
                "xiete.prompt": "bold cyan",
                "xiete.rule": "grey42",
            }
        )


def make_console(
    *,
    force_terminal: bool | None = None,
    width: int | None = None,
    file: Any = None,
) -> Console:
    """Create the shared Rich console.

    Args:
        force_terminal: Force ANSI output on/off. ``None`` auto-detects.
        width: Fixed console width in columns. ``None`` detects the terminal.
        file: Output stream. ``None`` uses stdout (or the Rich default).

    Returns:
        A configured :class:`rich.console.Console` instance.
    """
    return Console(
        theme=XieteTheme(),
        highlight=False,
        soft_wrap=False,
        force_terminal=force_terminal,
        width=width,
        emoji=True,
        file=file,
    )


#: Global console used by the CLI (also imported by the REPL loop).
console: Console = make_console()


# ---------------------------------------------------------------------------
# Logo helpers
# ---------------------------------------------------------------------------
def _blend(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        round(start[0] + (end[0] - start[0]) * t),
        round(start[1] + (end[1] - start[1]) * t),
        round(start[2] + (end[2] - start[2]) * t),
    )


def _parse_color(name: str) -> tuple[int, int, int]:
    """Resolve a small set of named colours to RGB tuples.

    ``#rrggbb`` (or ``#rgb``) hex strings are also accepted.
    """
    if isinstance(name, str) and name.startswith("#") and len(name) in (4, 7):
        try:
            h = name[1:]
            if len(h) == 3:
                h = "".join(ch * 2 for ch in h)
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            return (255, 255, 255)
    table = {
        "cyan": (0, 255, 255),
        "magenta": (255, 0, 255),
        "blue": (60, 130, 246),
        "purple": (170, 0, 255),
        "green": (0, 255, 128),
        "yellow": (255, 220, 0),
        "gold": (255, 215, 0),
        "gwhite": (200, 220, 255),
    }
    return table.get(name, (255, 255, 255))


def render_logo(logo: str = XIETE_LOGO, start: str = LOGO_GRADIENT[0], end: str = LOGO_GRADIENT[1]) -> Text:
    """Render the ASCII logo with a horizontal colour gradient.

    Args:
        logo: Multi-line ASCII art.
        start: Gradient start colour (Rich colour name or ``#rrggbb``).
        end: Gradient end colour.

    Returns:
        A :class:`rich.text.Text` renderable with per-character colouring.
    """
    lines = [line for line in logo.strip("\n").splitlines() if line.strip()]
    if not lines:
        return Text("XIETE", style="bold cyan")

    try:
        start_rgb = _parse_color(start)
        end_rgb = _parse_color(end)
    except Exception:  # pragma: no cover - defensive fallback
        start_rgb, end_rgb = (0, 255, 255), (255, 0, 255)

    # Align art to the left edge: compute the common leading-space padding.
    non_empty = [line for line in lines if line.strip()]
    pad = min((len(line) - len(line.lstrip(" ")) for line in non_empty), default=0)
    pad = min(pad, min((len(line) - len(line.lstrip(" ")) for line in non_empty if line.strip()), default=0))
    lines = [line[pad:] if len(line) > pad else "" for line in lines]
    max_len = max((len(line) for line in lines), default=1) or 1

    text = Text()
    for row, line in enumerate(lines):
        if row:
            text.append("\n")
        for col, char in enumerate(line):
            # Diagonal gradient: combine horizontal and vertical position.
            t = min(1.0, (col + row * 0.35) / max(1.0, max_len - 1))
            r, g, b = _blend(start_rgb, end_rgb, t)
            text.append(char, style=f"bold #{r:02x}{g:02x}{b:02x}")
    return text


def _shorten(text: str, limit: int = 58) -> str:
    """Collapse a path to ``limit`` characters, keeping the tail."""
    text = str(text)
    if len(text) <= limit:
        return text
    return "…" + text[-(limit - 1) :]


def render_banner(
    width: int | None = None,
    *,
    cwd: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    has_api_key: bool = True,
    max_steps: int | None = None,
    tools: Sequence[str] | None = None,
) -> Panel:
    """Build the startup banner panel.

    Args:
        width: Console width used for layout decisions. ``None`` uses the console's.
        cwd: Working directory to display. Defaults to ``os.getcwd()``.
        model_name: Mounted model id, e.g. ``gpt-4o``.
        base_url: Mounted API base URL.
        has_api_key: Whether an API key is configured.
        max_steps: Agent step budget.
        tools: Names of the mounted tools.

    Returns:
        A :class:`rich.panel.Panel` ready to print.
    """
    cwd = cwd or os.getcwd()
    content_width = width or console.width or 80

    logo_text = render_logo()
    tagline = Text(XIETE_TAGLINE, style="italic #ffd75e")

    meta = Table.grid(padding=(0, 2))
    meta.add_column(justify="right", style="xiete.dim", no_wrap=True)
    meta.add_column(style="xiete.value", no_wrap=True)
    meta.add_row("version", Text(f"v{__version__}", style="bold magenta"))
    meta.add_row("cwd", Text(_shorten(cwd, max(20, content_width - 24)), style="white"))
    meta.add_row(
        "model",
        Text(model_name or "not mounted", style="bold cyan" if model_name else "xiete.warn"),
    )
    if base_url:
        meta.add_row("endpoint", Text(_shorten(base_url, max(20, content_width - 24)), style="grey62"))
    meta.add_row(
        "api key",
        Text("configured ✓" if has_api_key else "missing ✗", style="xiete.ok" if has_api_key else "xiete.error"),
    )
    if max_steps is not None:
        meta.add_row("max steps", Text(str(max_steps), style="white"))
    if tools:
        meta.add_row("tools", Text(", ".join(tools), style="grey62"))

    hints = Text()
    for index, (key, label) in enumerate(SHORTCUT_HINTS):
        if index:
            hints.append("   ")
        hints.append(key, style="xiete.key")
        hints.append(f" {label}", style="grey62")

    body = Group(
        Align.center(logo_text),
        Align.center(tagline),
        Text(""),
        meta,
        Text(""),
        hints,
    )

    return Panel(
        body,
        box=box.ROUNDED,
        border_style="#c8912a",
        title="[bold #ffd700]❯ HOLYXIETE[/bold #ffd700] [grey42]— AI Coding Agent[/grey42]",
        title_align="left",
        subtitle="[grey42]one-shot: xiete \"<task>\"[/grey42]",
        subtitle_align="right",
        padding=(1, 3),
    )


def render_welcome() -> Panel:
    """Return the short hint panel printed under the banner."""
    body = Group(
        Text.from_markup(
            "[xiete.accent]输入你的编程任务[/xiete.accent] [grey62]（自然语言即可，例如 \"给 utils.py 加上单元测试\"）[/grey62]"
        ),
        Text.from_markup(
            "[xiete.accent]斜杠命令[/xiete.accent] [grey62]/help /clear /config /reset /exit[/grey62]"
        ),
    )
    return Panel(body, box=box.SIMPLE, border_style="grey35", padding=(0, 1))


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------
def print_banner(**kwargs) -> None:
    """Clear the screen and print the full startup banner plus hints.

    Args:
        **kwargs: Forwarded to :func:`render_banner`.
    """
    console.clear()
    console.print(render_banner(**kwargs))
    console.print(render_welcome())


def section(title: str) -> Rule:
    """Create a subtle horizontal rule with a title.

    Args:
        title: Rule caption.

    Returns:
        A :class:`rich.rule.Rule` renderable.
    """
    return Rule(Text(title, style="xiete.brand"), style="xiete.rule", align="left")


def info(message: str) -> None:
    """Print an informational line with a bullet marker."""
    console.print(f"[xiete.info]•[/xiete.info] {message}")


def success(message: str) -> None:
    """Print a success line with a check marker."""
    console.print(f"[xiete.ok]✓[/xiete.ok] {message}")


def warn(message: str) -> None:
    """Print a warning line."""
    console.print(f"[xiete.warn]![/xiete.warn] {message}")


def error(message: str) -> None:
    """Print an error line."""
    console.print(f"[xiete.error]✗[/xiete.error] {message}")


def warning_panel(title: str, body: RenderableType | str, *, hint: str | None = None) -> None:
    """Print a friendly yellow warning panel instead of crashing.

    Args:
        title: Panel title.
        body: Panel body, plain text or any Rich renderable.
        hint: Optional extra line printed below the panel.
    """
    renderable: RenderableType = Text.from_markup(body) if isinstance(body, str) else body
    console.print(
        Panel(
            renderable,
            title=f"[xiete.warn]{title}[/xiete.warn]",
            title_align="left",
            border_style="yellow",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    if hint:
        console.print(f"[grey62]{hint}[/grey62]")


def error_panel(title: str, body: RenderableType | str) -> None:
    """Print a red error panel.

    Args:
        title: Panel title.
        body: Panel body, plain text or any Rich renderable.
    """
    renderable: RenderableType = Text.from_markup(body) if isinstance(body, str) else body
    console.print(
        Panel(
            renderable,
            title=f"[xiete.error]{title}[/xiete.error]",
            title_align="left",
            border_style="red",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def render_answer(text: str) -> RenderableType:
    """Render the agent's final answer as Markdown (with code highlighting).

    Args:
        text: Raw Markdown produced by the agent.

    Returns:
        A Rich renderable.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return Text("(agent returned an empty answer)", style="xiete.dim")
    return Group(
        section("Answer"),
        Markdown(cleaned, code_theme="monokai", inline_code_lexer="python"),
    )


def render_code(code: str, lexer: str = "python") -> RenderableType:
    """Render a code block with syntax highlighting.

    Args:
        code: Source code to highlight.
        lexer: Pygments lexer name.

    Returns:
        A :class:`rich.syntax.Syntax` renderable.
    """
    return Syntax(code, lexer, theme="monokai", line_numbers=False, word_wrap=True, padding=(0, 1))


def kv_table(rows: Iterable[tuple[str, str]]) -> Table:
    """Build a two-column key/value table used by ``/config``.

    Args:
        rows: ``(key, value)`` pairs.

    Returns:
        A :class:`rich.table.Table` renderable.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", style="xiete.dim", no_wrap=True)
    table.add_column(style="xiete.value")
    for key, value in rows:
        table.add_row(Text(key), Text(value))
    return table


def detect_color_support() -> bool:
    """Best-effort check whether the current output supports ANSI colours."""
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    return bool(sys.stdout.isatty())


__all__ = [
    "LOGO_GRADIENT",
    "SHORTCUT_HINTS",
    "XIETE_LOGO",
    "XIETE_TAGLINE",
    "console",
    "detect_color_support",
    "error",
    "error_panel",
    "info",
    "kv_table",
    "make_console",
    "print_banner",
    "render_answer",
    "render_banner",
    "render_code",
    "render_logo",
    "render_welcome",
    "section",
    "success",
    "warn",
    "warning_panel",
]
