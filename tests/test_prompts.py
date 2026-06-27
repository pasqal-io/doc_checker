"""Tests for prompt templates."""

from __future__ import annotations

from doc_checker.prompts import get_combined_quality_prompt


def test_combined_quality_prompt_basic():
    """Test combined quality prompt generation."""
    signature = "def combined(x: int, y: str) -> bool"
    docstring = "Combined test function."
    api_name = "module.combined"

    prompt = get_combined_quality_prompt(signature, docstring, api_name)

    assert "module.combined" in prompt
    assert signature in prompt
    assert docstring in prompt
    assert "English Quality" in prompt
    assert "Code Alignment" in prompt
    assert "Completeness" in prompt
    assert "Technical Accuracy" in prompt


def test_combined_quality_prompt_with_code():
    """Test combined quality prompt includes code snippet."""
    signature = "def func(x: int) -> int"
    docstring = "Returns doubled value."
    api_name = "module.func"
    code_snippet = "    return x * 2"

    prompt = get_combined_quality_prompt(signature, docstring, api_name, code_snippet)

    assert "return x * 2" in prompt
    assert "Code implementation" in prompt


def test_combined_quality_prompt_no_code_snippet():
    """Test combined quality prompt omits code section without snippet."""
    prompt = get_combined_quality_prompt("def f() -> None", "Test", "module.f")

    assert "Code implementation" not in prompt


def test_combined_quality_prompt_requests_json_issues():
    """Test prompt requests JSON with issue fields."""
    prompt = get_combined_quality_prompt("def f() -> None", "Test", "module.f")

    assert "JSON" in prompt
    assert "issues" in prompt
    assert "severity" in prompt


def test_combined_quality_prompt_requests_examples():
    """Test prompt asks for concrete before/after examples."""
    prompt = get_combined_quality_prompt("def f() -> None", "Test", "module.f")

    assert (
        "example" in prompt.lower()
        or "before/after" in prompt.lower()
        or "concrete" in prompt.lower()
    )


def test_combined_quality_prompt_specifies_severity_levels():
    """Test prompt specifies all severity levels."""
    prompt = get_combined_quality_prompt("def f() -> None", "Test", "module.f")

    assert "critical" in prompt
    assert "warning" in prompt
    assert "suggestion" in prompt


def test_combined_quality_prompt_includes_api_name():
    """Test prompt includes the API name."""
    prompt = get_combined_quality_prompt(
        "def unique_api_name_12345() -> None",
        "Test docstring",
        "module.unique_api_name_12345",
    )

    assert "unique_api_name_12345" in prompt


def test_combined_quality_prompt_grounding_instruction():
    """Test prompt instructs the model not to assert unseen behavior."""
    prompt = get_combined_quality_prompt("def f() -> None", "Test", "module.f")

    assert "Never assert behavior you cannot see." in prompt


def test_combined_quality_prompt_omits_score():
    """Test prompt no longer requests an unused score/summary."""
    prompt = get_combined_quality_prompt("def f() -> None", "Test", "module.f")

    assert "score" not in prompt.lower()
    assert "summary" not in prompt.lower()
