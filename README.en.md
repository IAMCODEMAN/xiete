# HOLYXIETE

[中文](README.md) · **English**

> **HOLYXIETE** — an AI coding agent that lives in your terminal.
> Powered by Hugging Face [`smolagents`](https://github.com/huggingface/smolagents) `CodeAgent`: the model writes Python code → it runs in a local sandbox → it calls file and shell tools to get the job done.

```
██╗  ██╗ ██████╗ ██╗     ██╗   ██╗██╗  ██╗██╗███████╗████████╗███████╗
██║  ██║██╔═══██╗██║     ╚██╗ ██╔╝╚██╗██╔╝██║██╔════╝╚══██╔══╝██╔════╝
███████║██║   ██║██║      ╚████╔╝  ╚███╔╝ ██║█████╗     ██║   █████╗
██╔══██║██║   ██║██║       ╚██╔╝   ██╔██╗ ██║██╔══╝     ██║   ██╔══╝
██║  ██║╚██████╔╝███████╗   ██║   ██╔╝ ██╗██║███████╗   ██║   ███████╗
╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚══════╝   ╚═╝   ╚══════╝
```

Current version: **v0.1.0**

---

## Features

| Capability | Details |
| --- | --- |
| 🐋 DeepSeek-first | Works out of the box with **DeepSeek-V4.1-Flash-1017** (`deepseek-flash`), including thinking-mode compatibility handled for you |
| 🧠 Code-style agent | Built on `smolagents.CodeAgent`: the model emits executable Python instead of JSON tool calls |
| 🖥️ Terminal UI | `rich` + `prompt_toolkit`: gradient ASCII logo panel, spinner, Markdown and syntax highlighting |
| ⌨️ Global command | After `pip install -e .`, run `xiete` from any directory |
| 🗂️ History | Browse previous inputs with the arrow keys; persisted to a local file |
| 🔌 Any provider | Any OpenAI-compatible endpoint: DeepSeek / OpenAI / Moonshot / Qwen / Ollama / vLLM / one-api |
| ⚙️ Flexible config | Environment variables or a project `.env`, with automatic upward discovery |
| 🛡️ Guardrails | Tools are confined to the working directory; shell commands time out at 30s and destructive patterns are blocked |

---

## Quick start

### 1. Install

```bash
# From the project directory that contains pyproject.toml
cd xiete-cli
pip install -e .
```

> A virtual environment is recommended so you don't pollute the global Python install:
>
> ```bash
> python -m venv .venv
> source .venv/bin/activate        # Windows: .venv\Scripts\activate
> pip install -e .
> ```

The `xiete` command is registered in your Python Scripts directory and can be called from **any** directory:

```bash
xiete --version
```

If the command is not found, make sure that Scripts directory is on your `PATH` (on Windows it is usually `%APPDATA%\Python\Python3xx\Scripts`).

### 2. Configure a DeepSeek API key

HOLYXIETE targets **DeepSeek-V4.1-Flash-1017** by default, so you only need to supply your own key.

Create one at [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys), then copy the template:

```bash
cp .env.example .env          # macOS / Linux
copy .env.example .env        # Windows CMD
Copy-Item .env.example .env   # PowerShell
```

Edit `.env` — only the first line needs your input, the other defaults are already correct:

```dotenv
XIETE_API_KEY=sk-your-deepseek-key-here     # ← put your own key here
XIETE_BASE_URL=https://api.deepseek.com     # ← already correct
XIETE_MODEL=deepseek-flash                  # ← already correct
```

Or use real environment variables instead (they take priority over `.env`, and avoid keeping a plaintext key on disk):

```powershell
# Windows PowerShell (current session)
$env:XIETE_API_KEY="sk-your-deepseek-key-here"
$env:XIETE_BASE_URL="https://api.deepseek.com"
$env:XIETE_MODEL="deepseek-flash"

# Persist for the current user
[Environment]::SetEnvironmentVariable("XIETE_API_KEY","sk-your-deepseek-key-here","User")
```

```bash
# macOS / Linux
export XIETE_API_KEY="sk-your-deepseek-key-here"
```

Run `/config` inside the REPL at any time to confirm the configuration took effect.

### 3. Run

```bash
xiete                                    # interactive mode
xiete "add a unit test for utils.py and run it"   # one-shot mode
```

---

## DeepSeek specifics

### Recommended configuration

| Setting | Value | Notes |
| --- | --- | --- |
| `XIETE_API_KEY` | `sk-...` (your own) | Create it on the DeepSeek platform |
| `XIETE_BASE_URL` | `https://api.deepseek.com` | Official OpenAI-compatible endpoint. **No** `/v1` suffix needed (it also works if you add one) |
| `XIETE_MODEL` | `deepseek-flash` | DeepSeek-V4.1-Flash-1017, 1M context, recommended |

### Model name mapping

| Model | `XIETE_MODEL` value | Notes |
| --- | --- | --- |
| DeepSeek-V4.1-Flash-1017 | `deepseek-flash` | **Recommended default**: fast, cheap, strong at coding |
| DeepSeek-V4-Pro-0813 | `deepseek-v4-pro` | More capable, higher price |
| Legacy aliases | `deepseek-v4-flash` / `deepseek-v4.1-flash` / `deepseek-v4.1-flash-1017` | Still accepted; the server routes them to V4.1-Flash and HOLYXIETE normalises them to `deepseek-flash` |

> ⚠️ The older `deepseek-chat` / `deepseek-reasoner` names are no longer current. Use the values above.

### Three DeepSeek thinking-mode pitfalls already handled

DeepSeek V4 enables thinking mode by default, and three of its rules make a plain OpenAI-compatible client fail with **HTTP 400**. HOLYXIETE's `DeepSeekModel` adapts automatically — no manual configuration:

| # | DeepSeek rule | What happens without handling | What HOLYXIETE does |
| --- | --- | --- | --- |
| 1 | In thinking mode `tool_choice` may only be `auto` / `none`; `required` returns 400 | `smolagents` sends `required` by default, so **every call fails** | Rewrites it to `tool_choice="auto"` |
| 2 | When `tools` are present, assistant messages in subsequent turns must echo `reasoning_content` | Fails from step 2 onward, so any multi-step agent breaks | Captures it each turn and replays it in order |
| 3 | `temperature` has no effect in thinking mode | No error, but the value is silently ignored and behaviour is unpredictable | Stripped in thinking mode, sent only when thinking is disabled |

Thinking mode itself is pinned explicitly via `extra_body={"thinking": {"type": "enabled"}}` rather than relying on the server default.

### Toggling thinking mode

```dotenv
# Default: higher accuracy, good for complex coding tasks
XIETE_THINKING=enabled

# Disabled: faster and cheaper, good for simple Q&A
XIETE_THINKING=disabled

# Reasoning effort (default high): low / high / max
XIETE_REASONING_EFFORT=high
```

> Setting `XIETE_REASONING_EFFORT=none` is equivalent to disabling thinking mode.

---

## Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `XIETE_API_KEY` | ✅ | — | API key; falls back to `DEEPSEEK_API_KEY`, then `OPENAI_API_KEY` |
| `XIETE_BASE_URL` | | `https://api.deepseek.com` | OpenAI-compatible base URL |
| `XIETE_MODEL` | | `deepseek-flash` | Model name |
| `XIETE_THINKING` | | `enabled` | DeepSeek thinking mode (`enabled` / `disabled`) |
| `XIETE_REASONING_EFFORT` | | server default `high` | Reasoning effort: `low` / `high` / `max` / `none` |
| `XIETE_MAX_STEPS` | | `40` | Maximum reasoning steps per task |
| `XIETE_TIMEOUT` | | `300` | Per-request timeout in seconds (thinking mode is slow) |
| `XIETE_TEMPERATURE` | | provider default | Sampling temperature, **only effective when thinking mode is off** |
| `XIETE_HISTORY_FILE` | | system state dir | Custom path for the input history file |
| `XIETE_SYSTEM_PROMPT` | | unset | Path to an extra system-prompt file appended after the built-in rules; see [Editing the system prompt](#editing-the-system-prompt) |

### Configuration lookup order

1. Environment variables already present in the process (highest priority)
2. `.env` in the current working directory
3. `.env` found by walking up (up to 5 levels); a directory containing `.git` / `pyproject.toml` is treated as the project root and stops the walk

### Switching to another provider

Skip this if you only use DeepSeek. To switch providers, change all three variables together — HOLYXIETE then uses the standard `OpenAIModel` and no longer applies the DeepSeek thinking-mode rewrites:

```dotenv
# OpenAI
XIETE_BASE_URL=https://api.openai.com/v1
XIETE_MODEL=gpt-4o

# Qwen (DashScope compatible mode)
XIETE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
XIETE_MODEL=qwen-max

# Zhipu GLM
XIETE_BASE_URL=https://open.bigmodel.cn/api/paas/v4
XIETE_MODEL=glm-4-plus

# Local Ollama (no real key needed, any placeholder works)
XIETE_API_KEY=ollama
XIETE_BASE_URL=http://localhost:11434/v1
XIETE_MODEL=qwen2.5-coder:14b
```

> 💡 When reaching DeepSeek through Ollama / one-api or similar proxies, the thinking-mode adapter still applies as long as `XIETE_MODEL` starts with `deepseek`.

---

## Usage

### Interactive mode (`xiete`)

On startup the screen is cleared and a logo panel appears with the version, current working directory, mounted model and key bindings, followed by the REPL:

```
❯ xiete analyse the directory structure of this project and point me to the entry point
```

- `Enter` sends the instruction
- `↑` / `↓` browse previous inputs
- `Ctrl+C` **interrupts the current task only** — it does not exit the CLI
- `Ctrl+D` exits (pressing `Ctrl+C` while idle only prints how to quit)

### Built-in slash commands

| Command | Description |
| --- | --- |
| `/help` | Show help and the mounted tool list |
| `/clear` | Clear the screen and redraw the logo panel |
| `/config` | Show the current API key (masked), base URL, model and other settings |
| `/reset` | Reset agent memory and start a fresh context |
| `/exit` / `/quit` | Exit gracefully |

### One-shot mode

```bash
xiete "add type annotations to every function in src/utils.py"
xiete "explain what ./app.py does in 3 sentences"
xiete -m deepseek-v4-pro "list every TODO in this project"
```

You can also pipe a task in from a file:

```bash
echo "count how many .py files are in this repo" | xiete
xiete < task.txt
```

### Command-line options

```bash
xiete --help
```

| Option | Description |
| --- | --- |
| `-m, --model` | Model for this run (overrides the environment) |
| `-b, --base-url` | API base URL for this run |
| `-k, --api-key` | API key for this run (**not recommended** — it ends up in your shell history) |
| `--max-steps` | Maximum reasoning steps |
| `-v, --verbose` | Print smolagents step logs for debugging |
| `--version` | Show the version |

---

## Built-in tools

Tools live in `xiete/tools.py` and use smolagents' `@tool` decorator (with full type hints and Google-style docstrings).

| Tool | Signature | Description |
| --- | --- | --- |
| `read_file` | `(file_path: str, max_lines: int \| None = None) -> str` | Read a text file; binary files are rejected automatically |
| `write_file` | `(file_path: str, content: str) -> str` | Create or overwrite a file; parent directories are created |
| `list_directory` | `(dir_path: str = ".", max_depth: int = 2, name_filter: str \| None = None) -> str` | Print a directory tree, skipping `.git` / `node_modules` and friends |
| `run_shell_command` | `(command: str) -> str` | Run a terminal command and return exit code, stdout and stderr |

### Safety boundaries

- **Path sandbox**: file tools can only reach the working directory and its subdirectories; `../` escapes are rejected.
- **Shell timeout**: commands running longer than 30 seconds are killed and partial output is returned.
- **Destructive patterns blocked**: `rm -rf`, `mkfs`, `dd of=`, `shutdown`, `git push --force`, `curl | sh` and similar are refused with an explanation.
- **No shell interpreter**: commands are executed as argument lists (`shell=False`), so pipes, redirections and globs are not interpreted — which also rules out command injection.
- **Read-only mode**: `configure_tools(allow_write=False)` disables file writes.

---

## Project layout

```text
xiete-cli/
├── pyproject.toml         # Dependencies and [project.scripts] xiete = "xiete.cli:main"
├── .env.example           # Environment variable template
├── README.md              # Chinese documentation
├── README.en.md           # This document
└── xiete/
    ├── __init__.py        # __version__ = "0.1.0"
    ├── cli.py             # Terminal entry point, REPL loop, slash commands, argument parsing
    ├── ui.py              # XIETE_LOGO artwork (HOLYXIETE), banner rendering, Rich style helpers
    ├── agent.py           # Config loading (.env / environment) + CodeAgent setup
    └── tools.py           # @tool implementations
```

### Customising the logo

`xiete/ui.py` has a dedicated **LOGO section** at the top; the artwork is a single string constant:

```python
XIETE_LOGO: str = r"""
██╗  ██╗ ██████╗ ...
"""
```

Replace it with any ASCII art you like. The current brand is **HOLYXIETE**; the renderer applies a diagonal `#ffe066 → #c8912a` (golden) per-character gradient. Change the endpoints via `LOGO_GRADIENT`, which accepts `#rrggbb` hex values as well as names like `gold` / `yellow`.

### Editing the system prompt

The built-in rules live in the `AGENT_INSTRUCTIONS` constant in `xiete/agent.py` (six rules covering tool usage and safety boundaries). **Editing the source is not recommended** — append an external file instead:

**Option 1: drop a `XIETE_PROMPT.md` into the project (easiest)**

Create it in the directory where you launch `xiete` (or in a parent project root) and restart:

```markdown
# Additional requirements

- Always answer in English.
- Explain your plan before changing any code.
- Follow the Conventional Commits spec for commit messages.
```

**Option 2: point to any path via an environment variable**

```bash
# In .env or your environment
XIETE_SYSTEM_PROMPT=.\my_prompt.md
```

**Priority**: the file named by `XIETE_SYSTEM_PROMPT` → `XIETE_PROMPT.md` in the working directory → `XIETE_PROMPT.md` in a parent directory (up to 5 levels) → built-in rules only.

**Behaviour**

- The file's contents are **appended** to the built-in rules under an "Additional user requirements (highest priority)" heading, so **the built-in safety boundaries and tool rules still apply** — you are only layering on top.
- An empty file falls back to the built-in rules.
- If the environment variable points to a missing file, HOLYXIETE errors out instead of silently ignoring it.
- Changes take effect after **restarting `xiete`**; a running session is not hot-reloaded.
- Use `/config` to see the active source, e.g. `System prompt  workspace file (XIETE_PROMPT.md)`.

> To **replace** the built-in prompt entirely instead, edit the `AGENT_INSTRUCTIONS` string in `xiete/agent.py`.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Yellow "missing API key" panel on startup | Create `.env` or export the environment variables as the panel suggests; you can retype your task afterwards without restarting |
| `authentication failed / 401` | The `XIETE_API_KEY` is invalid or expired; confirm `XIETE_BASE_URL=https://api.deepseek.com` |
| `Model does not exist` | The model name should be `deepseek-flash` or `deepseek-v4-pro`; the old `deepseek-chat` is no longer available |
| `tool_choice: required ... not supported in thinking mode` | The DeepSeek adapter is not active; make sure `XIETE_MODEL` starts with `deepseek`, or set `XIETE_THINKING=disabled` |
| `reasoning_content is required ...` | Same as above; check that you didn't mix in a non-DeepSeek base URL, or upgrade HOLYXIETE |
| Connection timeouts / very slow responses | Thinking mode is inherently slow — raise `XIETE_TIMEOUT` (default 300) or set `XIETE_THINKING=disabled` |
| `Insufficient Balance` | Top up your DeepSeek account |
| Chinese text looks garbled on Windows terminals | Use Windows Terminal, or run `chcp 65001` to switch to UTF-8 |
| No colour in CI / redirected output | Set `NO_COLOR=1` to disable colour output |

---

## Development and testing

```bash
git clone https://github.com/IAMCODEMAN/xiete.git && cd xiete-cli
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Syntax / import sanity check
python -c "import xiete, xiete.cli, xiete.ui; print(xiete.__version__)"
python -m compileall xiete
```

Offline tests (no real API key required — everything runs against a local mock server):

```bash
python tests/smoke_test.py           # tools / config / UI / agent construction
python tests/deepseek_test.py        # unit checks for the three DeepSeek thinking-mode rules
python tests/deepseek_e2e_test.py    # full agent run against simulated DeepSeek strict rules
python tests/e2e_mock_server.py      # REPL / slash commands / Ctrl+C end-to-end
```

Requirements baseline:

- Python ≥ 3.10
- `smolagents >= 1.26` (from that version `OpenAIServerModel` is named `OpenAIModel`; the code keeps a bidirectional import fallback for older versions)

## License

MIT — see [LICENSE](LICENSE).
