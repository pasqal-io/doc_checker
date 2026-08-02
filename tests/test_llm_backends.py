"""Tests for LLM backends."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from doc_checker.llm_backends import (
    AnthropicBackend,
    LLMBackend,
    OllamaBackend,
    OpenAIBackend,
    get_backend,
)
from doc_checker.prompts import ISSUES_SCHEMA


def _anthropic_response(text: str = '{"issues": []}', stop_reason: str = "end_turn"):
    """Fake anthropic Message: one text content block + stop_reason."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return MagicMock(content=[block], stop_reason=stop_reason)


def test_llm_backend_abstract():
    """Test LLMBackend cannot be instantiated directly."""
    with pytest.raises(TypeError):
        LLMBackend()  # type: ignore


def test_ollama_backend_init():
    """Test OllamaBackend initialization."""
    with patch("ollama.list") as mock_list:
        mock_list.return_value = []
        backend = OllamaBackend(model="something")
    assert backend.model == "something"


def test_ollama_backend_default_model():
    """Test OllamaBackend uses correct default model."""
    with patch("ollama.list") as mock_list:
        mock_list.return_value = []
        backend = OllamaBackend()
    assert backend.model == "qwen3:1.7b"


@pytest.mark.skipif(True, reason="Requires ollama package - tested via integration")
def test_ollama_backend_generate():
    """Test OllamaBackend generates responses."""
    assert False  # this test needs to be inplemented, but wouldn't run without ollama.


def test_ollama_backend_missing_package():
    """Test OllamaBackend raises error if ollama not installed."""
    with patch.dict("sys.modules", {"ollama": None}):
        with pytest.raises(ImportError, match="ollama package required"):
            OllamaBackend()


def test_ollama_backend_service_not_running():
    with patch("ollama.list") as mock_list:

        def side_effect():
            raise ValueError("Service not running")

        mock_list.side_effect = side_effect
        with pytest.raises(RuntimeError, match="service not running"):
            OllamaBackend()


def test_openai_backend_init():
    """Test OpenAIBackend initialization."""
    with patch("openai.OpenAI") as mock_openai_class:
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        backend = OpenAIBackend(model="gpt-4o", api_key="test-key")

        assert backend.model == "gpt-4o"
        assert backend.api_key == "test-key"
        mock_openai_class.assert_called_once_with(api_key="test-key")


def test_openai_backend_default_model():
    """Test OpenAIBackend uses correct default model."""
    with patch("openai.OpenAI") as mock_openai_class:
        mock_openai_class.return_value = MagicMock()
        backend = OpenAIBackend(api_key="test-key")
        assert backend.model == "gpt-5.6-sol"


def test_openai_backend_api_key_from_env():
    """Test OpenAIBackend reads API key from environment."""
    with patch("openai.OpenAI") as mock_openai_class:
        with patch("os.environ", {"OPENAI_API_KEY": "test-key"}):
            mock_openai_class.return_value = MagicMock()
            backend = OpenAIBackend(model="gpt-4o")

            assert backend.model == "gpt-4o"
            assert backend.api_key == "test-key"
            mock_openai_class.assert_called_once_with(api_key="test-key")


def test_openai_backend_no_api_key():
    """Test OpenAIBackend raises error if no API key provided."""
    with (
        patch("openai.OpenAI") as mock_openai_class,
        patch.dict("os.environ", {}, clear=True),
    ):
        mock_openai_class.return_value = MagicMock()
        with pytest.raises(ValueError, match="OpenAI API key required"):
            OpenAIBackend(model="gpt-4o")


def test_openai_backend_generate():
    """Test OpenAIBackend generates responses via the Responses API."""
    with patch("openai.OpenAI") as mock_openai_class:
        mock_client = MagicMock()
        mock_client.responses.create.return_value = MagicMock(output_text="hello")
        mock_openai_class.return_value = mock_client

        backend = OpenAIBackend(model="gpt-5.6-sol", api_key="test-key")
        result = backend.generate("prompt")

        assert result == "hello"
        mock_client.responses.create.assert_called_once_with(
            model="gpt-5.6-sol",
            input="prompt",
            max_output_tokens=16384,
        )


def test_openai_backend_missing_package():
    """Test OpenAIBackend raises error if openai not installed."""
    with patch.dict("sys.modules", {"openai": None}):
        with pytest.raises(ImportError, match="openai package required"):
            OpenAIBackend(api_key="test-key")


def test_anthropic_backend_init():
    """Test AnthropicBackend initialization."""
    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_anthropic_class.return_value = MagicMock()

        backend = AnthropicBackend(model="claude-sonnet-5", api_key="test-key")

        assert backend.model == "claude-sonnet-5"
        assert backend.api_key == "test-key"
        assert backend.effort == "medium"
        mock_anthropic_class.assert_called_once_with(api_key="test-key")


def test_anthropic_backend_default_model():
    """Test AnthropicBackend uses correct default model."""
    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_anthropic_class.return_value = MagicMock()
        backend = AnthropicBackend(api_key="test-key")
        assert backend.model == "claude-opus-5"


def test_anthropic_backend_api_key_from_env():
    """Test AnthropicBackend reads API key from environment."""
    with patch("anthropic.Anthropic") as mock_anthropic_class:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}, clear=True):
            mock_anthropic_class.return_value = MagicMock()
            backend = AnthropicBackend()
            assert backend.api_key == "env-key"


def test_anthropic_backend_no_api_key():
    """Test AnthropicBackend raises error if no API key provided."""
    with (
        patch("anthropic.Anthropic") as mock_anthropic_class,
        patch.dict("os.environ", {}, clear=True),
    ):
        mock_anthropic_class.return_value = MagicMock()
        with pytest.raises(ValueError, match="Anthropic API key required"):
            AnthropicBackend()


def test_anthropic_backend_invalid_effort():
    """Test AnthropicBackend rejects unknown effort levels."""
    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_anthropic_class.return_value = MagicMock()
        with pytest.raises(ValueError, match="Invalid effort"):
            AnthropicBackend(api_key="test-key", effort="turbo")


def test_anthropic_backend_missing_package():
    """Test AnthropicBackend raises error if anthropic not installed."""
    with patch.dict("sys.modules", {"anthropic": None}):
        with pytest.raises(ImportError, match="anthropic package required"):
            AnthropicBackend(api_key="test-key")


def test_anthropic_backend_generate():
    """Test AnthropicBackend generates via Messages API with structured outputs."""
    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _anthropic_response('{"issues": []}')
        mock_anthropic_class.return_value = mock_client

        backend = AnthropicBackend(api_key="test-key", effort="low")
        result = backend.generate("prompt")

        assert result == '{"issues": []}'
        mock_client.messages.create.assert_called_once_with(
            model="claude-opus-5",
            max_tokens=16384,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": ISSUES_SCHEMA},
            },
            messages=[{"role": "user", "content": "prompt"}],
        )
        # Claude Opus 5 rejects sampling params with a 400 — must not be sent
        assert "temperature" not in mock_client.messages.create.call_args.kwargs


def test_anthropic_backend_generate_refusal():
    """Test refusal stop_reason maps to the error-JSON contract."""
    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _anthropic_response(
            text="", stop_reason="refusal"
        )
        mock_anthropic_class.return_value = mock_client

        backend = AnthropicBackend(api_key="test-key")
        parsed = backend.generate_json("prompt")

        assert parsed["issues"] == []
        assert "refusal" in parsed["error"]


def test_anthropic_backend_generate_truncated():
    """Test max_tokens stop_reason maps to the error-JSON contract."""
    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _anthropic_response(
            text='{"issues": [{"sev', stop_reason="max_tokens"
        )
        mock_anthropic_class.return_value = mock_client

        backend = AnthropicBackend(api_key="test-key")
        parsed = backend.generate_json("prompt")

        assert parsed["issues"] == []
        assert "max_tokens" in parsed["error"]


@patch("doc_checker.llm_backends.OllamaBackend")
def test_get_backend_ollama_default(mock_ollama_class):
    """Test get_backend returns OllamaBackend by default."""
    mock_backend = MagicMock()
    mock_ollama_class.return_value = mock_backend

    backend = get_backend()

    assert backend == mock_backend
    mock_ollama_class.assert_called_once_with("qwen3:1.7b")


@patch("doc_checker.llm_backends.OllamaBackend")
def test_get_backend_ollama_custom_model(mock_ollama_class):
    """Test get_backend with custom Ollama model."""
    mock_backend = MagicMock()
    mock_ollama_class.return_value = mock_backend

    backend = get_backend(backend_type="ollama", model="llama3.2:3b")

    assert backend == mock_backend
    mock_ollama_class.assert_called_once_with("llama3.2:3b")


@patch("doc_checker.llm_backends.OpenAIBackend")
def test_get_backend_openai(mock_openai_class):
    """Test get_backend returns OpenAIBackend."""
    mock_backend = MagicMock()
    mock_openai_class.return_value = mock_backend

    backend = get_backend(backend_type="openai", api_key="test-key")

    assert backend == mock_backend
    mock_openai_class.assert_called_once_with("gpt-5.6-sol", "test-key")


@patch("doc_checker.llm_backends.OpenAIBackend")
def test_get_backend_openai_custom_model(mock_openai_class):
    """Test get_backend with custom OpenAI model."""
    mock_backend = MagicMock()
    mock_openai_class.return_value = mock_backend

    backend = get_backend(backend_type="openai", model="gpt-4o", api_key="test-key")

    assert backend == mock_backend
    mock_openai_class.assert_called_once_with("gpt-4o", "test-key")


@patch("doc_checker.llm_backends.AnthropicBackend")
def test_get_backend_anthropic(mock_anthropic_class):
    """Test get_backend returns AnthropicBackend with default model/effort."""
    mock_backend = MagicMock()
    mock_anthropic_class.return_value = mock_backend

    backend = get_backend(backend_type="anthropic", api_key="test-key")

    assert backend == mock_backend
    mock_anthropic_class.assert_called_once_with(
        "claude-opus-5", "test-key", effort="medium"
    )


@patch("doc_checker.llm_backends.AnthropicBackend")
def test_get_backend_anthropic_custom_model_and_effort(mock_anthropic_class):
    """Test get_backend forwards custom model and effort to AnthropicBackend."""
    mock_backend = MagicMock()
    mock_anthropic_class.return_value = mock_backend

    backend = get_backend(
        backend_type="anthropic",
        model="claude-sonnet-5",
        api_key="test-key",
        effort="high",
    )

    assert backend == mock_backend
    mock_anthropic_class.assert_called_once_with(
        "claude-sonnet-5", "test-key", effort="high"
    )


def test_get_backend_unknown():
    """Test get_backend raises error for unknown backend."""
    with pytest.raises(ValueError, match="ollama, openai, anthropic"):
        get_backend(backend_type="invalid")
