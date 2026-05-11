from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
from pdf2zh_next.translator.translator_impl.openai import OpenAITranslator


class FakeRateLimiter:
    def wait(self, rate_limit_params: dict | None = None):
        pass


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="translated"))],
            usage=None,
        )


class FakeOpenAIClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def build_deepseek_settings(
    model: str,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
) -> SettingsModel:
    settings = SettingsModel(
        translate_engine_settings=DeepSeekSettings(
            deepseek_model=model,
            deepseek_api_key="dummy-key",
            deepseek_thinking_enabled=thinking_enabled,
            deepseek_reasoning_effort=reasoning_effort,
        )
    )
    settings.validate_settings()
    return settings


def build_translator(settings: SettingsModel) -> tuple[OpenAITranslator, FakeOpenAIClient]:
    fake_client = FakeOpenAIClient()
    with patch(
        "pdf2zh_next.translator.translator_impl.openai.openai.OpenAI",
        return_value=fake_client,
    ):
        translator = OpenAITranslator(settings, FakeRateLimiter())
    return translator, fake_client


def test_deepseek_v4_disabled_sends_extra_body_without_reasoning_effort():
    settings = build_deepseek_settings("deepseek-v4-flash", thinking_enabled=False)
    translator, fake_client = build_translator(settings)

    translator.do_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in request_kwargs


def test_deepseek_v4_enabled_sends_extra_body_and_configured_effort():
    settings = build_deepseek_settings(
        "deepseek-v4-flash",
        thinking_enabled=True,
        reasoning_effort="high",
    )
    translator, fake_client = build_translator(settings)

    translator.do_llm_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request_kwargs["reasoning_effort"] == "high"


def test_deepseek_v4_enabled_without_effort_omits_reasoning_effort():
    settings = build_deepseek_settings("deepseek-v4-flash", thinking_enabled=True)
    translator, fake_client = build_translator(settings)

    translator.do_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "reasoning_effort" not in request_kwargs


def test_deepseek_alias_models_do_not_send_extra_body_thinking():
    for model in ("deepseek-chat", "deepseek-reasoner"):
        settings = build_deepseek_settings(
            model,
            thinking_enabled=True,
            reasoning_effort="high",
        )
        translator, fake_client = build_translator(settings)

        translator.do_translate("hello")

        request_kwargs = fake_client.completions.calls[0]
        assert "extra_body" not in request_kwargs
        assert "reasoning_effort" not in request_kwargs


def test_deepseek_v4_cache_impact_distinguishes_thinking_modes():
    disabled_settings = build_deepseek_settings("deepseek-v4-flash", False)
    enabled_settings = build_deepseek_settings("deepseek-v4-flash", True)
    disabled_translator, _ = build_translator(disabled_settings)
    enabled_translator, _ = build_translator(enabled_settings)

    assert disabled_translator.cache.params["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert enabled_translator.cache.params["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert (
        disabled_translator.cache.translate_engine_params
        != enabled_translator.cache.translate_engine_params
    )
