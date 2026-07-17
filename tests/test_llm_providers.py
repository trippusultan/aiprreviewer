"""LLM provider-selection tests (no network calls)."""
import importlib

import common.config as config
from common.llm import get_llm, OpenAICompatibleLLM, AnthropicLLM, StubLLM


def _set(**kw):
    for k, v in kw.items():
        setattr(config.settings, k, v)


def test_offline_uses_stub():
    _set(run_offline=True)
    assert isinstance(get_llm(), StubLLM)


def test_anthropic_uses_native_client_with_key():
    _set(
        run_offline=False,
        llm_provider="anthropic",
        llm_api_key="sk-ant-xyz",
        llm_model="claude-3-5-sonnet-latest",
    )
    llm = get_llm()
    assert isinstance(llm, AnthropicLLM)
    # construction must not touch the network
    assert llm._model == "claude-3-5-sonnet-latest"


def test_anthropic_without_key_falls_back_to_stub():
    _set(run_offline=False, llm_provider="anthropic", llm_api_key="")
    assert isinstance(get_llm(), StubLLM)


def test_openai_compatible_with_key():
    _set(
        run_offline=False,
        llm_provider="openai-compatible",
        llm_api_key="real-key",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    assert isinstance(get_llm(), OpenAICompatibleLLM)


def test_ollama_no_key_but_base_url_uses_openai_compatible():
    _set(
        run_offline=False,
        llm_provider="openai-compatible",
        llm_api_key="",
        llm_base_url="http://localhost:11434/v1",
        llm_model="llama3.1",
    )
    assert isinstance(get_llm(), OpenAICompatibleLLM)


def test_openrouter_alias_via_openai_compatible():
    _set(
        run_offline=False,
        llm_provider="openai-compatible",
        llm_api_key="sk-or-xyz",
        llm_base_url="https://openrouter.ai/api/v1",
        llm_model="openai/gpt-4o-mini",
    )
    llm = get_llm()
    assert isinstance(llm, OpenAICompatibleLLM)
    assert llm._client.base_url == "https://openrouter.ai/api/v1/"


def test_legacy_openai_env_still_works():
    # Legacy OPENAI_* vars back-fill the LLM_* fields at construction time.
    # Simulate that: clear LLM_* and force the config to read OPENAI_API_KEY.
    import os

    os.environ["OPENAI_API_KEY"] = "sk-legacy"
    _set(
        run_offline=False,
        llm_provider="openai-compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    # Config reads LLM_API_KEY defaulting to OPENAI_API_KEY when unset.
    import importlib as _il

    _il.reload(config)
    assert config.settings.llm_api_key == "sk-legacy"
    assert isinstance(get_llm(), (OpenAICompatibleLLM, StubLLM))
