"""End-to-end test with a local mock OpenAI-compatible server (no real API key).

The mock server answers the smolagents CodeAgent's chat completion request with a
single code step that calls the local tools and then a ``final_answer`` call.
This proves: model wiring -> code generation parsing -> tool execution -> answer.

Run with:  python tests/e2e_mock_server.py
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CALLS: list[dict[str, Any]] = []

STEP_ONE = """I will create a file and then verify it with the shell tool.

```python
msg = write_file(file_path="hello.txt", content="hello from xiete\\n")
listing = list_directory(dir_path=".")
print(msg)
print(listing)
```"""

STEP_TWO = """Done.

```python
final_answer("Created hello.txt via write_file and verified it with list_directory.")
```"""


class Handler(BaseHTTPRequestHandler):
    """Minimal /v1/chat/completions responder."""

    def log_message(self, *args: Any) -> None:  # silence stderr noise
        pass

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        payload = json.loads(raw or b"{}")
        CALLS.append(payload)
        messages = payload.get("messages", [])
        # A tool observation is present once the agent has executed code.
        has_observation = any(m.get("role") == "tool" for m in messages) or any(
            "Execution logs" in str(m.get("content", "")) for m in messages
        )
        content = STEP_TWO if has_observation else STEP_ONE
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", "mock-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    import signal

    # The test runner and the CLI it spawns share this console, so a Ctrl+C
    # would also interrupt us. Ignore SIGINT here; only the child reacts.
    if os.name == "nt":
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}/v1"
    print(f"mock server on {base_url}")

    workspace = Path(tempfile.mkdtemp(prefix="xiete_e2e_"))
    env = {
        **os.environ,
        "XIETE_API_KEY": "sk-mock",
        "XIETE_BASE_URL": base_url,
        "XIETE_MODEL": "mock-model",
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "COLUMNS": "100",
        # Child processes must not inherit an unrelated .env from the repo root.
        "XIETE_HISTORY_FILE": str(Path(tempfile.mkdtemp(prefix="xiete_hist_")) / "history"),
    }

    failures: list[str] = []

    # The in-process checks below build sessions from this process's own
    # environment, so mirror the child configuration here.
    for key in ("XIETE_API_KEY", "XIETE_BASE_URL", "XIETE_MODEL"):
        os.environ[key] = env[key]

    # ---- 1. one-shot mode through the real console script ------------------
    proc = subprocess.run(
        [sys.executable, "-m", "xiete.cli", "create hello.txt"],
        cwd=str(workspace),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        shell=False,
    )
    print("---- stdout ----")
    print(proc.stdout[-2500:])
    if proc.returncode != 0:
        failures.append(f"one-shot exit code {proc.returncode}\nstderr={proc.stderr[-2000:]}")
    if not (workspace / "hello.txt").is_file():
        failures.append("hello.txt was not created by the agent")
    elif (workspace / "hello.txt").read_text(encoding="utf-8") != "hello from xiete\n":
        failures.append("hello.txt content mismatch")
    if "Created hello.txt" not in proc.stdout:
        failures.append("final answer not rendered in stdout")
    if len(CALLS) < 2:
        failures.append(f"expected >=2 model calls, got {len(CALLS)}")

    # ---- 2. interactive REPL: /config, task, /reset, /help, /exit ----------
    # stdin is a pipe, so drive ReplSession directly with a fake terminal input.
    calls_before = len(CALLS)
    repl_proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "repl_driver.py"), "create hello.txt"],
        cwd=str(workspace),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        shell=False,
    )
    print("---- repl stdout (tail) ----")
    print(repl_proc.stdout[-2000:])
    if repl_proc.returncode != 0:
        failures.append(f"repl exit code {repl_proc.returncode}\nstderr={repl_proc.stderr[-2000:]}")
    if len(CALLS) <= calls_before:
        failures.append("REPL did not call the model for the task line")
    for needle in ("/config", "Agent 记忆已重置", "再见"):
        if needle not in repl_proc.stdout:
            failures.append(f"REPL output missing {needle!r}")

    # ---- 3. Ctrl+C while a task runs -------------------------------------
    # In-process, using a real ReplSession whose agent raises KeyboardInterrupt:
    # the REPL must report the interruption and hand control back to the prompt.
    try:
        import xiete.cli as cli_mod
        from xiete import ui

        class InterruptingAgent:
            def __init__(self) -> None:
                self.calls = 0

            def run(self, task: str):  # noqa: ANN001
                self.calls += 1
                raise KeyboardInterrupt

        script_lines = iter(["do something", "/reset", "/exit"])
        buf = io.StringIO()
        quiet = ui.make_console(force_terminal=False, width=100, file=buf)
        original_console = cli_mod.console
        original_ui = ui.console
        original_input = __import__("builtins").input
        original_piped = cli_mod._stdin_is_piped
        cli_mod.console = quiet
        ui.console = quiet
        cli_mod._stdin_is_piped = lambda: False
        __import__("builtins").input = lambda prompt="": next(script_lines, "")  # noqa: ARG005
        try:
            args = cli_mod._build_parser().parse_args([])
            session = cli_mod.ReplSession(args)
            config, ok = cli_mod._load_session_config(args)
            session.config = config
            session.agent = InterruptingAgent() if ok else None
            session.agent_ready = ok
            repl_code = session.run()
        finally:
            cli_mod.console = original_console
            ui.console = original_ui
            __import__("builtins").input = original_input
            cli_mod._stdin_is_piped = original_piped

        output = buf.getvalue()
        print("---- ctrl+c repl (tail) ----")
        print(output[-900:])
        if repl_code != 0:
            failures.append(f"REPL returned {repl_code} instead of 0 after /exit")
        if "已中断当前任务" not in output:
            failures.append("REPL did not report the Ctrl+C interruption")
        if "再见" not in output:
            failures.append("REPL did not exit cleanly on /exit after an interruption")
    except Exception as exc:  # pragma: no cover
        failures.append(f"Ctrl+C REPL check raised: {type(exc).__name__}: {exc}")

    # ---- 4. in-process: run_task absorbs KeyboardInterrupt ---------------
    try:
        from xiete import ui
        from xiete.cli import run_task

        class BlockingAgent:
            def run(self, task: str):  # noqa: ANN001
                raise KeyboardInterrupt

        buf = io.StringIO()
        quiet = ui.make_console(force_terminal=False, width=100, file=buf)
        original = ui.console
        ui.console = quiet
        try:
            result = run_task(BlockingAgent(), "anything", show_spinner=True)
        finally:
            ui.console = original
        if result is not None:
            failures.append(f"run_task should return None on Ctrl+C, got {result!r}")
        if "已中断当前任务" not in buf.getvalue():
            failures.append("run_task did not report the interruption to the user")
        print("[ok] in-process Ctrl+C is absorbed by run_task")
    except Exception as exc:  # pragma: no cover
        failures.append(f"in-process Ctrl+C check raised: {type(exc).__name__}: {exc}")

    server.shutdown()
    print("\n" + "=" * 60)
    if failures:
        for item in failures:
            print(f"  FAIL  {item}")
        print(f"{len(failures)} failure(s)")
        return 1
    print("  ALL E2E CHECKS PASSED")
    return 0


class SlowHandler(Handler):
    """Handler that stalls so the client can be interrupted mid-request."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        time.sleep(120)


def signal_ctrl_c() -> int:
    """Return the platform Ctrl+C notion used for interrupt delivery."""
    import signal

    return signal.SIGINT if os.name != "nt" else signal.CTRL_C_EVENT


def send_ctrl_c(proc: "subprocess.Popen[str]") -> bool:
    """Deliver an interrupt to ``proc``.

    POSIX: a plain ``SIGINT`` reaches the child's ``KeyboardInterrupt`` handler.

    Windows has no per-process SIGINT for a child that does not share a console
    process group, so console-level delivery is reported as unavailable and the
    caller relies on the in-process assertion instead.

    Returns:
        ``True`` when the interrupt was delivered.
    """
    if os.name != "nt":
        proc.send_signal(__import__("signal").SIGINT)
        return True
    return False

if __name__ == "__main__":
    sys.exit(main())
