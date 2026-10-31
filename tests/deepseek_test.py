"""DeepSeek V4.1-Flash adapter tests (offline, no API key required).

Verifies the three DeepSeek thinking-mode rules that the plain ``OpenAIModel``
would violate, plus config resolution and model-id aliasing.

Run with:  python tests/deepseek_test.py
"""

from __future__ import annotations

import os
import sys
import traceback

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str):
    def decorator(fn):
        try:
            fn()
        except Exception:  # noqa: BLE001
            FAILED.append((name, traceback.format_exc()))
        else:
            PASSED.append(name)
        return fn

    return decorator


def _clean_env() -> None:
    for key in (
        "XIETE_API_KEY",
        "XIETE_BASE_URL",
        "XIETE_MODEL",
        "XIETE_THINKING",
        "XIETE_REASONING_EFFORT",
        "XIETE_TEMPERATURE",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ):
        os.environ.pop(key, None)


def _config(**overrides):
    from xiete.agent import load_config

    _clean_env()
    return load_config(load_env=False, **overrides)


def main() -> int:
    @check("defaults target DeepSeek V4.1-Flash")
    def _():
        from xiete.agent import DEFAULT_BASE_URL, DEFAULT_MODEL

        assert DEFAULT_BASE_URL == "https://api.deepseek.com", DEFAULT_BASE_URL
        assert DEFAULT_MODEL == "deepseek-flash", DEFAULT_MODEL
        cfg = _config()
        assert cfg.base_url == "https://api.deepseek.com", cfg.base_url
        assert cfg.model == "deepseek-flash", cfg.model
        assert cfg.is_deepseek is True
        assert cfg.thinking is True
        assert cfg.effective_model == "deepseek-flash"

    @check("DEEPSEEK_API_KEY is honoured as a fallback")
    def _():
        _clean_env()
        os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek"
        from xiete.agent import load_config

        cfg = load_config(load_env=False)
        assert cfg.api_key == "sk-deepseek", cfg.api_key

    @check("legacy model aliases collapse to deepseek-flash")
    def _():
        for alias in (
            "deepseek-v4-flash",
            "deepseek-v4.1-flash",
            "deepseek-v4.1-flash-1017",
            "deepseek-4.1-flash",
        ):
            cfg = _config(model=alias)
            assert cfg.effective_model == "deepseek-flash", (alias, cfg.effective_model)
        cfg = _config(model="deepseek-v4-pro")
        assert cfg.effective_model == "deepseek-v4-pro", cfg.effective_model

    @check("thinking can be disabled via XIETE_THINKING")
    def _():
        _clean_env()
        os.environ["XIETE_THINKING"] = "false"
        from xiete.agent import load_config

        cfg = load_config(load_env=False)
        assert cfg.thinking is False, cfg.thinking
        _clean_env()
        os.environ["XIETE_THINKING"] = "on"
        cfg = load_config(load_env=False)
        assert cfg.thinking is True, cfg.thinking

    @check("reasoning_effort parsed and validated")
    def _():
        _clean_env()
        os.environ["XIETE_REASONING_EFFORT"] = "max"
        from xiete.agent import load_config

        cfg = load_config(load_env=False)
        assert cfg.reasoning_effort == "max", cfg.reasoning_effort

        _clean_env()
        os.environ["XIETE_REASONING_EFFORT"] = "none"
        cfg = load_config(load_env=False)
        assert cfg.thinking is False, "effort=none must disable thinking"
        assert cfg.reasoning_effort is None

        _clean_env()
        os.environ["XIETE_REASONING_EFFORT"] = "bogus"
        from xiete.agent import ConfigError

        try:
            load_config(load_env=False)
        except ConfigError:
            pass
        else:
            raise AssertionError("invalid effort was accepted")

    @check("build_model returns a DeepSeek-aware model")
    def _():
        from xiete.agent import DeepSeekModel, build_model

        cfg = _config(api_key="sk-test")
        model = build_model(cfg)
        assert isinstance(model, DeepSeekModel), type(model)
        assert model.model_id == "deepseek-flash", model.model_id
        assert model.deepseek_thinking is True

    @check("non-DeepSeek endpoint keeps the plain OpenAI model")
    def _():
        from xiete.agent import DeepSeekModel, build_model

        cfg = _config(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        model = build_model(cfg)
        assert not isinstance(model, DeepSeekModel), type(model)
        assert model.model_id == "gpt-4o", model.model_id

    @check("RULE 1: tool_choice=required becomes auto in thinking mode")
    def _():
        from xiete.agent import build_model

        model = build_model(_config(api_key="sk-test"))
        from xiete.tools import read_file

        kwargs = model._prepare_completion_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            tools_to_call_from=[read_file],
            tool_choice="required",
        )
        assert kwargs.get("tool_choice") == "auto", kwargs.get("tool_choice")
        assert kwargs.get("extra_body", {}).get("thinking") == {"type": "enabled"}, kwargs.get("extra_body")
        assert "thinking" not in kwargs, "thinking must travel inside extra_body, not as a top-level kwarg"

    @check("RULE 2: reasoning_content is replayed onto assistant turns")
    def _():
        from xiete.agent import build_model

        model = build_model(_config(api_key="sk-test"))
        # Simulate two earlier assistant turns observed from the API.
        model._deepseek_reasoning_queue = ["think-A", "", "think-C"]
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "step1"},
            {"role": "user", "content": "obs1"},
            {"role": "assistant", "content": "step2"},
            {"role": "user", "content": "obs2"},
            {"role": "assistant", "content": "step3"},
        ]
        kwargs = model._prepare_completion_kwargs(messages=messages, tools_to_call_from=[])
        assistants = [m for m in kwargs["messages"] if getattr(m["role"], "value", m["role"]) == "assistant"]
        assert assistants[0].get("reasoning_content") == "think-A", assistants[0]
        # An empty reasoning string is deliberately not attached (nothing to replay),
        # but it still consumes its slot so later turns stay aligned.
        assert "reasoning_content" not in assistants[1], assistants[1]
        assert assistants[2].get("reasoning_content") == "think-C", assistants[2]
        # Non-assistant messages are untouched.
        for message in kwargs["messages"]:
            if getattr(message["role"], "value", message["role"]) != "assistant":
                assert "reasoning_content" not in message, message

    @check("RULE 3: temperature is dropped in thinking mode only")
    def _():
        from xiete.agent import build_model

        thinking_cfg = _config(api_key="sk-test")
        thinking_cfg.temperature = 0.2
        model = build_model(thinking_cfg)
        model.kwargs["temperature"] = 0.2
        kwargs = model._prepare_completion_kwargs(messages=[{"role": "user", "content": "x"}])
        assert "temperature" not in kwargs, kwargs

        off_cfg = _config(api_key="sk-test")
        off_cfg.thinking = False
        off_cfg.temperature = 0.2
        model_off = build_model(off_cfg)
        kwargs_off = model_off._prepare_completion_kwargs(messages=[{"role": "user", "content": "x"}])
        assert kwargs_off.get("temperature") == 0.2, kwargs_off.get("temperature")
        assert "extra_body" not in kwargs_off or "thinking" not in kwargs_off.get("extra_body", {})

    @check("/config rows explain the DeepSeek setup")
    def _():
        cfg = _config(api_key="sk-abcdefghijklmnop", model="deepseek-v4-flash")
        rows = dict(cfg.as_rows())
        assert rows["Provider"] == "DeepSeek", rows["Provider"]
        assert "deepseek-flash" in rows["Model"], rows["Model"]
        assert "enabled" in rows["Thinking"], rows["Thinking"]
        assert "ignored" in rows["Temperature"], rows["Temperature"]

    @check("banner shows the DeepSeek model")
    def _():
        from xiete import ui

        console = ui.make_console(force_terminal=False, width=100)
        panel = ui.render_banner(width=95, cwd=".", model_name="deepseek-flash", base_url="https://api.deepseek.com")
        console.print(panel)

    print(f"\n{'=' * 60}")
    for name in PASSED:
        print(f"  PASS  {name}")
    for name, tb in FAILED:
        print(f"  FAIL  {name}\n{tb}")
    print(f"{'=' * 60}\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
