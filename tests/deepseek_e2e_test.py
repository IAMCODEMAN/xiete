"""End-to-end test that emulates DeepSeek's strict thinking-mode API rules.

The mock server reproduces the documented DeepSeek behaviours:

* ``tool_choice="required"`` (or a named tool) in thinking mode -> HTTP 400
* when ``tools`` is present, assistant messages missing ``reasoning_content``
  after the first turn -> HTTP 400
* unknown model ids -> HTTP 404 (validates ``deepseek-flash``)

If XIETE's adapter works, a full multi-step CodeAgent run succeeds; if the
adapter regressed, the mock returns 400 and the run fails.

Run with:  python tests/deepseek_e2e_test.py
"""

from __future__ import annotations

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

REQUESTS: list[dict[str, Any]] = []
VALID_MODELS = {"deepseek-flash", "deepseek-v4-pro"}

STEP_ONE = """I'll create the file and verify it.

```python
msg = write_file(file_path="note.txt", content="deepseek ok\\n")
print(msg)
print(list_directory(dir_path="."))
```"""

STEP_TWO = """Verification finished.

```python
final_answer("Created note.txt and verified the tree.")
```"""


class Handler(BaseHTTPRequestHandler):
    """Mock DeepSeek /chat/completions endpoint."""

    def log_message(self, *args: Any) -> None:  # silence
        pass

    def _error(self, code: int, message: str) -> None:
        body = json.dumps({"error": {"message": message, "type": "invalid_request_error"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        REQUESTS.append(payload)

        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._error(404, f"unknown path {self.path}")

        model = payload.get("model")
        if model not in VALID_MODELS:
            return self._error(404, f"Model '{model}' does not exist. Valid: {sorted(VALID_MODELS)}")

        thinking_field = payload.get("thinking")
        thinking_on = True
        if isinstance(thinking_field, dict):
            thinking_on = thinking_field.get("type", "enabled") == "enabled"
        elif payload.get("reasoning_effort") == "none":
            thinking_on = False

        has_tools = bool(payload.get("tools"))

        # RULE 1: required/named tool_choice is rejected in thinking mode.
        tool_choice = payload.get("tool_choice")
        if thinking_on and tool_choice not in (None, "auto", "none"):
            return self._error(
                400,
                "tool_choice: 'required' and named tool choices are not supported in thinking mode.",
            )

        messages = payload.get("messages", [])
        # RULE 2: with tools present, assistant turns after the first must carry
        # reasoning_content back to the API.
        if thinking_on and has_tools:
            assistant_turns = [m for m in messages if m.get("role") == "assistant"]
            for index, turn in enumerate(assistant_turns):
                if index == 0:
                    continue  # the very first assistant turn has no prior reasoning
                if not turn.get("reasoning_content"):
                    return self._error(
                        400,
                        f"reasoning_content is required on assistant turn #{index + 1} when tools are present.",
                    )

        turns_done = len([m for m in messages if m.get("role") == "assistant"])
        content = STEP_ONE if turns_done == 0 else STEP_TWO
        body = {
            "id": "chatcmpl-deepseek-mock",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "system_fingerprint": "mock",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                        # Thinking-mode models always return this field.
                        "reasoning_content": f"reasoning for turn {turns_done + 1}",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "prompt_tokens_details": {"prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 100},
                "completion_tokens_details": {"reasoning_tokens": 20},
            },
        }
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    workspace = Path(tempfile.mkdtemp(prefix="xiete_ds_e2e_"))

    env = {
        **os.environ,
        "XIETE_API_KEY": "sk-deepseek-mock",
        "XIETE_BASE_URL": base_url,
        "XIETE_MODEL": "deepseek-flash",
        "XIETE_THINKING": "enabled",
        "NO_COLOR": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "COLUMNS": "100",
    }
    # Do not let a stray .env from the repo root leak in.
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        env.pop(key, None)

    failures: list[str] = []
    print(f"mock DeepSeek server on {base_url}")

    proc = subprocess.run(
        [sys.executable, "-m", "xiete.cli", "create note.txt"],
        cwd=str(workspace),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        shell=False,
    )
    print("---- stdout (tail) ----")
    print(proc.stdout[-2200:])
    if proc.returncode != 0:
        failures.append(f"exit code {proc.returncode}\nstderr={proc.stderr[-2500:]}")
    if not (workspace / "note.txt").is_file():
        failures.append("agent did not create note.txt")
    if len(REQUESTS) < 2:
        failures.append(f"expected >=2 API calls, got {len(REQUESTS)}")

    # Assert the adapter actually sent DeepSeek-valid payloads.
    for index, req in enumerate(REQUESTS):
        if req.get("model") != "deepseek-flash":
            failures.append(f"request {index}: model {req.get('model')!r}")
        if req.get("tools") and req.get("tool_choice") not in (None, "auto"):
            failures.append(f"request {index}: tool_choice={req.get('tool_choice')!r} would 400")
        if "temperature" in req:
            failures.append(f"request {index}: temperature should be dropped in thinking mode")
        thinking = req.get("thinking")
        if thinking != {"type": "enabled"}:
            failures.append(f"request {index}: thinking={thinking!r}")
    if len(REQUESTS) >= 3:
        second = REQUESTS[2] if len(REQUESTS) > 2 else REQUESTS[-1]
        assistants = [m for m in second.get("messages", []) if m.get("role") == "assistant"]
        if len(assistants) >= 2 and not assistants[1].get("reasoning_content"):
            failures.append("reasoning_content was not replayed on later assistant turns")
        else:
            print("[ok] reasoning_content replayed on later assistant turns")

    print(f"\n{len(REQUESTS)} API request(s) validated")
    server.shutdown()

    print("=" * 60)
    if failures:
        for item in failures:
            print(f"  FAIL  {item}")
        return 1
    print("  DEEPSEEK E2E CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
