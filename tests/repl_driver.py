"""Drive the XIETE REPL non-interactively, simulating a terminal session.

Usage:  python tests/repl_driver.py "task to run"

stdin is a pipe here, so ``main()`` would treat it as a one-shot task. This
driver forces interactive mode and feeds a scripted sequence of lines through
the REPL, exercising slash commands + a real agent task in one flow.
"""

from __future__ import annotations

import builtins
import io
import sys
import traceback

import xiete.cli as cli


def main() -> int:
    task = sys.argv[1] if len(sys.argv) > 1 else "create hello.txt"
    script = f"/config\n{task}\n/reset\n/help\n/clear\n/exit\n"

    # Pretend stdin is a terminal so main() enters the REPL branch, then feed
    # the scripted lines through plain input().
    cli._stdin_is_piped = lambda: False  # type: ignore[assignment]
    cursor = io.StringIO(script)
    builtins.input = lambda prompt="": cursor.readline().rstrip("\n")  # noqa: ARG005

    argv: list[str] = []
    try:
        code = cli.main(argv)
    except BaseException:  # noqa: BLE001 - always surface the traceback
        traceback.print_exc()
        return 3
    print(f"\n[repl exit code: {code}]")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
