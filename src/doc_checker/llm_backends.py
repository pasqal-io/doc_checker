"""LLM backend abstraction layer."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, cast

from doc_checker.constants import DEFAULT_MODELS, VALID_EFFORTS

if TYPE_CHECKING:
    from anthropic.types import OutputConfigParam


class LLMBackend(ABC):
    """Abstract base for LLM backends."""

    model: str

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate completion from prompt."""
        pass

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        """json.loads that only accepts an object and tolerates raw control chars.

        strict=False: local models often emit literal newlines/tabs inside string
        values, which strict JSON rejects ("Invalid control character").
        """
        result = json.loads(text, strict=False)
        if not isinstance(result, dict):
            raise TypeError(f"expected a JSON object, got {type(result).__name__}")
        return result

    def generate_json(self, prompt: str) -> dict[str, Any]:
        """Generate and parse JSON response."""
        response: str = self.generate(prompt)
        # Clean JSON (structured outputs, or a well-behaved model) parses as-is.
        # Only fall back to the fence/<think> heuristics when it does not, so a
        # ``` inside a JSON string value is never mistaken for a fence.
        try:
            return self._parse_json_object(response)
        except (json.JSONDecodeError, TypeError):
            pass
        # Strip reasoning-model <think>...</think> blocks (qwen3, etc.)
        if "<think>" in response:
            end = response.rfind("</think>")
            if end != -1:
                response = response[end + len("</think>") :].strip()
        # Extract JSON from markdown code blocks if present
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            response = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            response = response[start:end].strip()

        try:
            return self._parse_json_object(response)
        except (json.JSONDecodeError, TypeError) as e:
            # Fallback: return error structure
            return {
                "error": f"Failed to parse JSON: {e}",
                "raw_response": response,
                "issues": [],
            }


class OllamaBackend(LLMBackend):
    """Ollama local LLM backend (default)."""

    def __init__(self, model: str = DEFAULT_MODELS["ollama"]):
        """Initialize Ollama backend.

        Args:
            model: Model name (qwen3:1.7b, llama3.2:3b, phi3.5, gemma2:2b)

        Raises:
            ImportError: If ollama package not installed
            RuntimeError: If Ollama service not running
        """
        try:
            import ollama  # TODO: ollama should be in requirements.txt
        except ImportError:
            raise ImportError(
                "ollama package required. Install with: pip install ollama\n"
                "Then install Ollama: https://ollama.ai/download"
            )
        self.client = ollama
        self.model = model

        # Test connection
        try:
            self.client.list()
        except Exception as e:
            raise RuntimeError(
                f"Ollama service not running. Start with: ollama serve\n" f"Error: {e}"
            )

    def generate(self, prompt: str) -> str:
        """Generate completion via Ollama."""
        response = self.client.generate(
            model=self.model,
            prompt=prompt,
            options={
                "temperature": 0.1,  # low, for deterministic JSON output
                "num_predict": 4096,
            },
        )
        result: str = response["response"]
        return result


class OpenAIBackend(LLMBackend):
    """OpenAI API backend."""

    def __init__(self, model: str = DEFAULT_MODELS["openai"], api_key: str | None = None):
        """Initialize OpenAI backend.

        Args:
            model: Model name (gpt-6.1-sol recommended)
            api_key: API key (defaults to OPENAI_API_KEY env var)

        Raises:
            ImportError: If openai package not installed
            ValueError: If API key not provided
        """
        try:
            from openai import (
                OpenAI,
            )  # TODO: openai should be in requirements.txt or others like anthropic
        except ImportError:
            raise ImportError("openai package required. Install with: pip install openai")

        # Get API key with priority: explicit > env var
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var:\n"
                "  export OPENAI_API_KEY='sk-proj-...'\n"
                "Or pass api_key parameter explicitly."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    def generate(self, prompt: str) -> str:
        """Generate completion via OpenAI Responses API.

        gpt-5.x/6.x reasoning models only accept the default ``temperature``, so
        none is sent.
        """
        response = self.client.responses.create(
            model=self.model,
            input=prompt,
            max_output_tokens=16384,
        )
        return response.output_text or ""


class AnthropicBackend(LLMBackend):
    """Anthropic (Claude) API backend with structured outputs."""

    def __init__(
        self,
        model: str = DEFAULT_MODELS["anthropic"],
        api_key: str | None = None,
        effort: str = "medium",
    ):
        """Initialize Anthropic backend.

        Args:
            model: Model name (claude-opus-5-5 recommended)
            api_key: API key (defaults to ANTHROPIC_API_KEY env var)
            effort: Thinking/output effort level (low|medium|high|xhigh|max).
                The speed/cost lever: Claude Opus 5.5 always thinks; lower effort
                caps thinking depth.

        Raises:
            ValueError: If API key not provided or effort invalid
        """
        from anthropic import Anthropic

        if effort not in VALID_EFFORTS:
            raise ValueError(
                f"Invalid effort {effort!r}; choose from {sorted(VALID_EFFORTS)}"
            )

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var:\n"
                "  export ANTHROPIC_API_KEY='sk-ant-api03-...'\n"
                "Or pass api_key parameter explicitly."
            )

        self.client = Anthropic(api_key=self.api_key)
        self.model = model
        self.effort = effort

    def generate(self, prompt: str) -> str:
        """Generate completion via the Anthropic Messages API.

        Sends the ISSUES_SCHEMA as a structured-outputs format, so a normal
        completion is guaranteed valid JSON and the shared ``generate_json``
        parses it without fallback. No sampling params: Claude Opus 5.5 rejects
        ``temperature``/``top_p``/``top_k`` with a 400.
        """
        from doc_checker.prompts import ISSUES_SCHEMA

        response = self.client.messages.create(
            model=self.model,
            max_tokens=16384,
            output_config=cast(
                "OutputConfigParam",
                {
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": ISSUES_SCHEMA},
                },
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        # Anything but a clean end_turn (refusal, max_tokens,
        # model_context_window_exceeded, ...) means truncated or absent text:
        # surface through the error-JSON contract so the quality checker reports
        # a critical issue instead of a falsely clean API or a vague parse error.
        if response.stop_reason != "end_turn":
            return json.dumps(
                {
                    "error": f"LLM stopped early: stop_reason={response.stop_reason}",
                    "issues": [],
                }
            )
        return next((b.text for b in response.content if b.type == "text"), "")


def get_backend(
    backend_type: str = "ollama",
    model: str | None = None,
    api_key: str | None = None,
    effort: str = "medium",
) -> LLMBackend:
    """Factory to get LLM backend.

    Args:
        backend_type: "ollama" (default, local), "openai" or "anthropic" (API)
        model: Model name (uses sensible defaults if None)
        api_key: API key for cloud backends
        effort: Effort level for the anthropic backend (ignored by others)

    Returns:
        Configured LLM backend

    Raises:
        ValueError: If backend_type unknown
        ImportError: If required package not installed
        RuntimeError: If backend not available
    """
    if backend_type == "ollama":
        return OllamaBackend(model or DEFAULT_MODELS["ollama"])
    elif backend_type == "openai":
        return OpenAIBackend(model or DEFAULT_MODELS["openai"], api_key)
    elif backend_type == "anthropic":
        return AnthropicBackend(
            model or DEFAULT_MODELS["anthropic"], api_key, effort=effort
        )
    else:
        raise ValueError(
            f"Unknown backend: {backend_type}. " "Choose from: ollama, openai, anthropic"
        )
