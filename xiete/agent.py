"""Agent wiring for XIETE: configuration loading + smolagents ``CodeAgent``.

The configuration is resolved in this order (first match wins for each field):

1. Real process environment variables (``XIETE_*`` then fallbacks).
2. ``.env`` in the current working directory.
3. ``.env`` in the nearest project root found by walking up (max 5 levels).

Because ``python-dotenv`` never overrides variables that already exist,
loading the ``.env`` files last keeps real environment variables authoritative.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dotenv import dotenv_values

from xiete import __version__
from xiete.tools import DEFAULT_TOOLS, configure_tools, get_workspace_root

#: Default OpenAI compatible endpoint (DeepSeek, see README).
DEFAULT_BASE_URL = "https://api.deepseek.com"
#: Default model id. DeepSeek's V4.1-Flash-1017 series is served as ``deepseek-flash``.
DEFAULT_MODEL = "deepseek-flash"
#: Default agent step budget. Thinking mode is slower, so the budget is generous.
DEFAULT_MAX_STEPS = 40
#: Default per-request timeout (seconds). DeepSeek thinking mode can be slow.
DEFAULT_TIMEOUT = 300
#: Maximum number of parent directories searched for a ``.env`` file.
ENV_SEARCH_DEPTH = 5

#: DeepSeek model aliases accepted from users -> canonical API model id.
#: ``deepseek-v4-flash`` is a legacy alias that DeepSeek still routes to V4.1-Flash.
MODEL_ALIASES: dict[str, str] = {
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4-flash-vision-exp": "deepseek-flash",
    "deepseek-4.1-flash": "deepseek-flash",
    "deepseek-v4.1-flash": "deepseek-flash",
    "deepseek-v4.1-flash-1017": "deepseek-flash",
}

#: Valid DeepSeek reasoning efforts for ``reasoning_effort``.
REASONING_EFFORTS: tuple[str, ...] = ("none", "low", "high", "max")

#: Environment variable names (in priority order) for each setting.
API_KEY_VARS: tuple[str, ...] = ("XIETE_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
BASE_URL_VARS: tuple[str, ...] = ("XIETE_BASE_URL", "DEEPSEEK_BASE_URL", "OPENAI_BASE_URL")
MODEL_VARS: tuple[str, ...] = ("XIETE_MODEL", "DEEPSEEK_MODEL", "OPENAI_MODEL")
MAX_STEPS_VARS: tuple[str, ...] = ("XIETE_MAX_STEPS",)
TIMEOUT_VARS: tuple[str, ...] = ("XIETE_TIMEOUT",)
TEMPERATURE_VARS: tuple[str, ...] = ("XIETE_TEMPERATURE",)
THINKING_VARS: tuple[str, ...] = ("XIETE_THINKING",)
REASONING_EFFORT_VARS: tuple[str, ...] = ("XIETE_REASONING_EFFORT",)
#: Extra system-prompt file appended after :data:`AGENT_INSTRUCTIONS`.
SYSTEM_PROMPT_VARS: tuple[str, ...] = ("XIETE_SYSTEM_PROMPT",)
#: Sidecar file probed (cwd first, then project root) when no env var is set.
SYSTEM_PROMPT_FILENAMES: tuple[str, ...] = ("XIETE_PROMPT.md",)

#: Python modules the agent's generated code may import besides smolagents'
#: base set (collections, datetime, itertools, math, queue, random, re, stat,
#: statistics, time, unicodedata).
AUTHORIZED_IMPORTS: list[str] = [
    "os",
    "sys",
    "json",
    "csv",
    "pathlib",
    "typing",
    "dataclasses",
    "enum",
    "functools",
    "textwrap",
    "glob",
    "shutil",
    "subprocess",
    "difflib",
    "hashlib",
    "ast",
    "decimal",
    "fractions",
    "string",
    "itertools",
    "collections",
    "datetime",
    "time",
    "re",
    "math",
    "random",
    "statistics",
    "unicodedata",
]

#: Extra instructions injected into the CodeAgent system prompt.
AGENT_INSTRUCTIONS = """
You are XIETE, an expert software engineering agent working directly inside the
user's terminal. You operate on the local file system through the provided tools
and you write real, runnable code.

Operating rules:
1. Always inspect before you modify: use `list_directory` and `read_file` to
   understand the existing code before writing anything.
2. Prefer small, focused, verifiable changes. Use `write_file` to create or
   fully overwrite a file, and `run_shell_command` to run tests, linters or the
   program itself to prove your change works.
3. Keep file paths relative to the working directory.
4. Never invent tool names, file contents or command output. If a command fails,
   read the error, fix the cause and retry.
5. Destructive commands are blocked on purpose; do not try to work around the
   block list. Ask the user instead.
6. Finish with `final_answer(...)` containing a concise Markdown summary of what
   you changed (file paths, key decisions, how you verified it) and the next
   suggested step. Write the answer in the user's language.
""".strip()


def _default_prompt_candidates(workspace: Path | None) -> list[Path]:
    """Return candidate system-prompt files: cwd first, then the project root."""
    candidates: list[Path] = []
    if workspace is not None:
        candidates.append(Path(workspace) / SYSTEM_PROMPT_FILENAMES[0])
        for parent in list(Path(workspace).parents)[:ENV_SEARCH_DEPTH]:
            candidate = parent / SYSTEM_PROMPT_FILENAMES[0]
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def resolve_system_prompt(
    workspace: Path | None = None,
    *,
    base: str = AGENT_INSTRUCTIONS,
) -> tuple[str, str]:
    """Combine the built-in rules with a user supplied extra prompt file.

    Resolution order (first readable match wins):

    1. ``XIETE_SYSTEM_PROMPT`` env var / ``.env`` entry (a file path).
    2. ``XIETE_PROMPT.md`` in the workspace, then in its parent directories.

    The file contents are *appended* to ``base`` under an "Additional user
    requirements" heading, so the built-in operating rules stay in force.

    Args:
        workspace: Workspace root used to probe for ``XIETE_PROMPT.md``.
        base: Built-in instructions to extend.

    Returns:
        A ``(prompt, source)`` tuple. ``source`` is a human readable origin
        (``"built-in"`` when no extra file was found).

    Raises:
        ConfigError: If the configured file is missing or unreadable.
    """
    raw_path, origin = _first_value(SYSTEM_PROMPT_VARS)
    if raw_path and raw_path.strip():
        path = Path(raw_path.strip()).expanduser()
        if not path.is_absolute() and workspace is not None:
            path = Path(workspace) / path
        path = path.resolve()
        if not path.is_file():
            raise ConfigError(f"{origin} points to a missing file: {path}")
        candidates = [(path, origin)]
    else:
        candidates = [
            (candidate, "workspace file")
            for candidate in _default_prompt_candidates(workspace)
            if candidate.is_file()
        ]

    if not candidates:
        return base.strip(), "built-in"

    path, origin = candidates[0]
    try:
        extra = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read system prompt file {path}: {exc}") from exc
    if not extra:
        return base.strip(), "built-in"

    prompt = f"{base.strip()}\n\nAdditional user requirements (highest priority):\n\n{extra}\n"
    return prompt, f"{origin} ({path.name})"


class ConfigError(RuntimeError):
    """Raised when the agent cannot be constructed from the configuration."""


@dataclass
class XieteConfig:
    """Resolved runtime configuration for one XIETE session."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    max_steps: int = DEFAULT_MAX_STEPS
    timeout: int = DEFAULT_TIMEOUT
    temperature: float | None = None
    thinking: bool = True
    reasoning_effort: str | None = None
    workspace: Path = field(default_factory=get_workspace_root)
    env_files: list[Path] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def has_api_key(self) -> bool:
        """Whether a non-empty API key is available."""
        return bool(self.api_key)

    @property
    def is_deepseek(self) -> bool:
        """Whether this session talks to DeepSeek.

        Decided by the *model id* rather than the URL alone, so pointing XIETE at
        a DeepSeek-compatible proxy (localhost, one-api, a gateway) keeps the
        thinking-mode adaptations. The host check covers custom model names.
        """
        model = (self.model or "").strip().lower()
        if model.startswith("deepseek"):
            return True
        return "deepseek" in (self.base_url or "").lower()

    @property
    def effective_model(self) -> str:
        """The canonical model id sent to the API (aliases resolved)."""
        return _normalise_model_id(self.model)

    @property
    def masked_api_key(self) -> str:
        """A safe-to-display version of the API key."""
        key = self.api_key or ""
        if not key:
            return "<not set>"
        if len(key) <= 12:
            return key[:2] + "*" * max(4, len(key) - 2)
        return f"{key[:6]}…{key[-4:]}"

    def as_rows(self) -> list[tuple[str, str]]:
        """Return display rows for ``/config``."""
        model_label = self.model
        if self.effective_model != self.model:
            model_label = f"{self.model}  →  {self.effective_model}"
        if self.is_deepseek:
            if self.thinking:
                effort = self.reasoning_effort or "high (default)"
                thinking_label = f"enabled · effort={effort}"
            else:
                thinking_label = "disabled"
        else:
            thinking_label = "n/a (非 DeepSeek 端点)"
        rows = [
            ("Provider", "DeepSeek" if self.is_deepseek else "OpenAI-compatible"),
            ("API Key", self.masked_api_key),
            ("Base URL", self.base_url),
            ("Model", model_label),
            ("Thinking", thinking_label),
            ("Max steps", str(self.max_steps)),
            ("Timeout", f"{self.timeout}s"),
            (
                "Temperature",
                "ignored in thinking mode"
                if self.is_deepseek and self.thinking
                else ("provider default" if self.temperature is None else f"{self.temperature:g}"),
            ),
            ("Workspace", str(self.workspace)),
            ("Env files", ", ".join(str(p) for p in self.env_files) if self.env_files else "<none>"),
        ]
        rows.extend(
            (f"  ↳ {key} from", value) for key, value in self.sources.items() if value
        )
        return rows


# ---------------------------------------------------------------------------
# .env discovery
# ---------------------------------------------------------------------------
def find_env_files(start: Path | None = None) -> list[Path]:
    """Locate ``.env`` files from the working directory up to the project root.

    Args:
        start: Directory to start from. Defaults to the current working directory.

    Returns:
        Existing ``.env`` paths, nearest first (duplicates removed).
    """
    current = Path(start or Path.cwd()).expanduser().resolve()
    found: list[Path] = []
    for _ in range(ENV_SEARCH_DEPTH + 1):
        candidate = current / ".env"
        if candidate.is_file():
            found.append(candidate)
            # A project root marker means we stop climbing.
            if any((current / marker).exists() for marker in (".git", "pyproject.toml", "setup.py")):
                break
        if current.parent == current:
            break
        current = current.parent
    return found


def _load_env_files(start: Path | None = None) -> list[Path]:
    """Load discovered ``.env`` files into ``os.environ`` without overriding."""
    files = find_env_files(start)
    # Load farthest first so the nearest .env wins when we set defaults below.
    merged: dict[str, str] = {}
    for env_file in reversed(files):
        try:
            values = dotenv_values(env_file)
        except (OSError, UnicodeDecodeError):
            continue
        for key, value in values.items():
            if value is not None and key not in merged:
                merged[key] = value
    for key, value in merged.items():
        # Environment always wins over files.
        os.environ.setdefault(key, value)
    return files


def _first_value(names: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Return ``(value, name)`` for the first non-empty env variable."""
    for name in names:
        raw = os.environ.get(name)
        if raw is not None and raw.strip():
            return raw.strip(), name
    return None, None


def _parse_int(value: str | None, default: int, *, name: str) -> int:
    if value is None or not str(value).strip():
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc
    return parsed if parsed > 0 else default


def _parse_float(value: str | None, *, name: str) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number, got {value!r}") from exc


def _parse_bool(value: str | None, *, default: bool, name: str) -> bool:
    """Parse a boolean-ish environment value."""
    if value is None or not str(value).strip():
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled", "disable"}:
        return False
    raise ConfigError(f"{name} must be a boolean (true/false), got {value!r}")


def _normalise_base_url(url: str) -> str:
    """Normalise an endpoint.

    DeepSeek serves the OpenAI-compatible API at ``https://api.deepseek.com``
    (a trailing ``/v1`` also works and is kept as-is); other providers keep
    whatever path the user supplied. Only the scheme and trailing slash are
    normalised here -- never adding ``/v1`` silently, because that breaks
    providers served at the root path.
    """
    cleaned = url.strip().rstrip("/")
    if not cleaned:
        return DEFAULT_BASE_URL
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    return cleaned


def load_config(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    max_steps: int | None = None,
    load_env: bool = True,
    cwd: Path | None = None,
) -> XieteConfig:
    """Resolve the XIETE configuration.

    Args:
        model: Explicit model override (CLI flag).
        base_url: Explicit base URL override (CLI flag).
        api_key: Explicit API key override (CLI flag).
        max_steps: Explicit step budget override (CLI flag).
        load_env: When ``True`` (default) ``.env`` files are loaded into the process.
        cwd: Directory used for ``.env`` discovery and as the workspace root.

    Returns:
        A fully populated :class:`XieteConfig`.

    Raises:
        ConfigError: If a numeric environment variable cannot be parsed.
    """
    workspace = Path(cwd or Path.cwd()).expanduser().resolve()
    env_files = _load_env_files(workspace) if load_env else []

    sources: dict[str, str] = {}

    resolved_key, key_source = _first_value(API_KEY_VARS)
    if api_key and api_key.strip():
        resolved_key, key_source = api_key.strip(), "--api-key flag"
    if key_source:
        sources["api_key"] = key_source

    resolved_base, url_source = _first_value(BASE_URL_VARS)
    if base_url and base_url.strip():
        resolved_base, url_source = base_url.strip(), "--base-url flag"
    if url_source:
        sources["base_url"] = url_source

    resolved_model, model_source = _first_value(MODEL_VARS)
    if model and model.strip():
        resolved_model, model_source = model.strip(), "--model flag"
    if model_source:
        sources["model"] = model_source

    if max_steps is not None:
        resolved_max_steps = int(max_steps)
        sources["max_steps"] = "--max-steps flag"
    else:
        raw_steps, steps_source = _first_value(MAX_STEPS_VARS)
        resolved_max_steps = _parse_int(raw_steps, DEFAULT_MAX_STEPS, name="XIETE_MAX_STEPS")
        if steps_source:
            sources["max_steps"] = steps_source

    raw_timeout, timeout_source = _first_value(TIMEOUT_VARS)
    resolved_timeout = _parse_int(raw_timeout, DEFAULT_TIMEOUT, name="XIETE_TIMEOUT")
    if timeout_source:
        sources["timeout"] = timeout_source

    raw_temperature, temperature_source = _first_value(TEMPERATURE_VARS)
    resolved_temperature = _parse_float(raw_temperature, name="XIETE_TEMPERATURE")
    if temperature_source:
        sources["temperature"] = temperature_source

    raw_thinking, thinking_source = _first_value(THINKING_VARS)
    resolved_thinking = _parse_bool(raw_thinking, default=True, name="XIETE_THINKING")
    if thinking_source:
        sources["thinking"] = thinking_source

    raw_effort, effort_source = _first_value(REASONING_EFFORT_VARS)
    resolved_effort = (raw_effort or "").strip().lower() or None
    if resolved_effort and resolved_effort not in REASONING_EFFORTS:
        raise ConfigError(
            f"XIETE_REASONING_EFFORT must be one of {', '.join(REASONING_EFFORTS)}; got {raw_effort!r}"
        )
    if effort_source and resolved_effort:
        sources["reasoning_effort"] = effort_source
    # ``none`` is a documented way to disable thinking mode.
    if resolved_effort == "none":
        resolved_thinking = False

    if not resolved_base:
        resolved_base = DEFAULT_BASE_URL
        sources["base_url"] = "default"
    if not resolved_model:
        resolved_model = DEFAULT_MODEL
        sources["model"] = "default"

    return XieteConfig(
        api_key=resolved_key,
        base_url=_normalise_base_url(resolved_base),
        model=resolved_model,
        max_steps=resolved_max_steps,
        timeout=resolved_timeout,
        temperature=resolved_temperature,
        thinking=resolved_thinking,
        reasoning_effort=resolved_effort if resolved_effort != "none" else None,
        workspace=workspace,
        env_files=env_files,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# smolagents imports (version tolerant)
# ---------------------------------------------------------------------------
# smolagents renamed OpenAIModel -> OpenAIServerModel (1.x) and back to
# OpenAIModel (>=1.26). Resolve whichever one this install provides.
try:  # pragma: no cover - depends on the installed smolagents version
    from smolagents import CodeAgent  # type: ignore[attr-defined]
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "XIETE requires the 'smolagents' package. Install it with: pip install 'xiete'"
    ) from exc

from smolagents.models import ApiModel  # noqa: E402

OpenAICompatibleModel: type[ApiModel]
try:  # smolagents <= 1.25
    from smolagents import OpenAIServerModel as OpenAICompatibleModel  # type: ignore[attr-defined]
except ImportError:  # smolagents >= 1.26
    try:
        from smolagents import OpenAIModel as OpenAICompatibleModel  # type: ignore[attr-defined,no-redef]
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Could not import OpenAIServerModel/OpenAIModel from smolagents. "
            "Please install smolagents>=1.26: pip install -U smolagents"
        ) from exc


class DeepSeekModel(OpenAICompatibleModel):  # type: ignore[misc,valid-type]
    """``OpenAIModel`` tuned for the DeepSeek V4 chat completions API.

    DeepSeek's thinking mode (the default) imposes three rules that plain
    ``OpenAIModel`` breaks:

    1. ``tool_choice="required"`` is rejected with HTTP 400 in thinking mode,
       while smolagents asks for ``"required"`` by default.
    2. With ``tools`` present, the API requires every assistant turn's
       ``reasoning_content`` to be sent back, otherwise it returns HTTP 400.
       smolagents rebuilds messages from scratch and drops it.
    3. ``temperature`` has no effect (and is documented as unsupported) while
       thinking is enabled.

    This subclass fixes all three through ``_prepare_completion_kwargs``, which
    smolagents calls right before ``chat.completions.create``.
    """

    #: DeepSeek rejects ``user`` messages that are not the final message, and it
    #: wants tool results as plain text, which smolagents already produces.
    deepseek_thinking: bool = True
    deepseek_reasoning_effort: str | None = None

    def _prepare_completion_kwargs(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Build the request kwargs, then apply DeepSeek's thinking-mode rules.

        Returns:
            The request payload for ``chat.completions.create``.
        """
        # smolagents <= 1.26 passes ``tool_choice`` as a keyword with default
        # "required"; older builds may not accept it at all.
        try:
            completion_kwargs = super()._prepare_completion_kwargs(*args, **kwargs)
        except TypeError:
            kwargs.pop("tool_choice", None)
            completion_kwargs = super()._prepare_completion_kwargs(*args, **kwargs)

        if not self.deepseek_thinking:
            return completion_kwargs

        # (1) "required" / named tool choice is a 400 in thinking mode.
        if completion_kwargs.get("tools"):
            completion_kwargs["tool_choice"] = "auto"

        # (3) Deterministic sampling knobs are ignored in thinking mode; drop
        # them so the payload matches the documented contract.
        completion_kwargs.pop("temperature", None)
        completion_kwargs.pop("top_p", None)

        # Explicitly pin thinking + effort (default is enabled/high server side).
        # DeepSeek documents ``extra_body={"thinking": ...}``; the OpenAI SDK
        # merges it into the request JSON as a top-level field.
        extra_body = dict(completion_kwargs.get("extra_body") or {})
        extra_body.setdefault("thinking", {"type": "enabled"})
        completion_kwargs["extra_body"] = extra_body
        completion_kwargs.pop("thinking", None)
        if self.deepseek_reasoning_effort and "reasoning_effort" not in completion_kwargs:
            completion_kwargs["reasoning_effort"] = self.deepseek_reasoning_effort

        # (2) Re-attach reasoning_content to assistant messages, in order.
        completion_kwargs["messages"] = _reattach_reasoning_content(
            completion_kwargs.get("messages") or [],
            getattr(self, "_deepseek_reasoning_queue", None) or [],
        )
        return completion_kwargs

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        """Call the API and remember each assistant turn's ``reasoning_content``.

        Returns:
            A smolagents ``ChatMessage``.
        """
        message = super().generate(*args, **kwargs)
        try:
            record = message.raw
            reasoning = None
            if isinstance(record, dict):
                reasoning = record.get("reasoning_content")
            else:  # openai ChatCompletion object
                choices = getattr(record, "choices", None)
                if choices:
                    reasoning = getattr(choices[0].message, "reasoning_content", None)
            queue = getattr(self, "_deepseek_reasoning_queue", None)
            if queue is None:
                queue = []
                self._deepseek_reasoning_queue = queue
            queue.append(reasoning or "")
        except Exception:  # pragma: no cover - never break generation over bookkeeping
            pass
        return message


def _role_of(message: dict[str, Any]) -> str:
    """Return the plain string role of ``message``.

    smolagents may hand us ``MessageRole`` enum members rather than plain
    strings, so compare against the enum value rather than the enum itself.
    """
    role = message.get("role", "")
    return getattr(role, "value", role)


def _reattach_reasoning_content(messages: list[dict[str, Any]], queue: list[str]) -> list[dict[str, Any]]:
    """Attach recorded ``reasoning_content`` to assistant messages, in order.

    The API model is stateless, so previously observed reasoning is kept in a
    per-model queue and replayed onto the assistant turns smolagents rebuilds
    from memory.

    Args:
        messages: Messages prepared for the request.
        queue: Reasoning strings captured from earlier ``generate`` calls.

    Returns:
        A new list of messages with ``reasoning_content`` added where needed.
    """
    if not queue:
        return messages

    result = list(messages)
    pending = iter(queue)
    for index, message in enumerate(result):
        if _role_of(message) != "assistant":
            continue
        reasoning = next(pending, None)
        if reasoning is None:
            break
        if reasoning and "reasoning_content" not in message:
            result[index] = {**message, "reasoning_content": reasoning}
    return result


def _normalise_model_id(model_id: str) -> str:
    """Map user friendly DeepSeek aliases onto the canonical API model id."""
    key = (model_id or "").strip().lower()
    return MODEL_ALIASES.get(key, model_id.strip())


def build_model(config: XieteConfig) -> ApiModel:
    """Create the model driver for ``config``.

    DeepSeek endpoints get :class:`DeepSeekModel` (thinking-mode aware); any other
    OpenAI compatible endpoint gets the plain ``OpenAIModel``.

    Args:
        config: Resolved XIETE configuration.

    Returns:
        An instance of ``OpenAIModel`` (or ``OpenAIServerModel`` on older builds).

    Raises:
        ConfigError: If no API key is configured.
    """
    if not config.has_api_key:
        raise ConfigError(
            "No API key configured. Set XIETE_API_KEY (or DEEPSEEK_API_KEY / OPENAI_API_KEY) "
            "in your environment or .env file."
        )

    model_id = _normalise_model_id(config.model)
    kwargs: dict[str, Any] = {
        "model_id": model_id,
        "api_base": config.base_url,
        "api_key": config.api_key,
        "client_kwargs": {"timeout": config.timeout, "max_retries": 2},
    }
    if config.temperature is not None and not config.thinking:
        kwargs["temperature"] = config.temperature

    model_class: Any = DeepSeekModel if config.is_deepseek else OpenAICompatibleModel
    try:
        model = model_class(**kwargs)
    except TypeError:
        # Older signatures may not accept ``client_kwargs``.
        kwargs.pop("client_kwargs", None)
        model = model_class(**kwargs)  # type: ignore[operator]

    if isinstance(model, DeepSeekModel):
        model.deepseek_thinking = config.thinking
        model.deepseek_reasoning_effort = config.reasoning_effort
    return model  # type: ignore[return-value]


def build_agent(
    config: XieteConfig | None = None,
    *,
    callable_tools: list[Callable[..., Any]] | None = None,
    verbosity_level: int | None = None,
    planning_interval: int | None = None,
) -> Any:
    """Build a ready to use :class:`smolagents.CodeAgent`.

    Args:
        config: Resolved configuration; loaded from the environment when omitted.
        callable_tools: Extra ``@tool`` functions to mount next to the defaults.
        verbosity_level: smolagents ``LogLevel`` numeric value (``0`` keeps the
            console clean so Rich can own the UI).
        planning_interval: Optional step interval for smolagents planning.

    Returns:
        A configured ``CodeAgent`` instance.

    Raises:
        ConfigError: If the API key is missing or the agent cannot be built.
    """
    from smolagents import LogLevel  # local import keeps module import light

    cfg = config or load_config()
    configure_tools(workspace=cfg.workspace)
    model = build_model(cfg)

    tools = list(DEFAULT_TOOLS)
    if callable_tools:
        tools.extend(callable_tools)

    level = LogLevel.OFF if verbosity_level is None else verbosity_level
    agent_kwargs: dict[str, Any] = {
        "tools": tools,
        "model": model,
        "max_steps": cfg.max_steps,
        "verbosity_level": level,
        "additional_authorized_imports": AUTHORIZED_IMPORTS,
        "instructions": resolve_system_prompt(cfg.workspace)[0],
        "name": "xiete",
        "description": "A terminal coding agent that reads, writes and runs code in the user's working directory.",
    }
    if planning_interval:
        agent_kwargs["planning_interval"] = planning_interval

    try:
        return CodeAgent(**agent_kwargs)
    except Exception as exc:  # pragma: no cover - surfaces as a friendly panel
        raise ConfigError(f"Failed to initialise CodeAgent: {type(exc).__name__}: {exc}") from exc


def reset_agent_memory(agent: Any) -> bool:
    """Clear the conversation memory of ``agent`` in place.

    Args:
        agent: A ``smolagents`` agent instance.

    Returns:
        ``True`` when the memory was reset successfully.
    """
    memory = getattr(agent, "memory", None)
    if memory is None:
        return False
    reset = getattr(memory, "reset", None)
    if callable(reset):
        reset()
    else:  # pragma: no cover - very old smolagents builds
        steps = getattr(memory, "steps", None)
        if isinstance(steps, list):
            steps.clear()
        else:
            return False
    if hasattr(agent, "python_executor") and hasattr(agent.python_executor, "reset"):
        try:
            agent.python_executor.reset()
        except Exception:  # pragma: no cover - best effort only
            pass
    return True


__all__ = [
    "AGENT_INSTRUCTIONS",
    "AUTHORIZED_IMPORTS",
    "ConfigError",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DeepSeekModel",
    "MODEL_ALIASES",
    "OpenAICompatibleModel",
    "REASONING_EFFORTS",
    "SYSTEM_PROMPT_FILENAMES",
    "SYSTEM_PROMPT_VARS",
    "XieteConfig",
    "build_agent",
    "build_model",
    "find_env_files",
    "load_config",
    "resolve_system_prompt",
    "reset_agent_memory",
]
