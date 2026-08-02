"""Prompt templates for LLM quality checks."""

# ruff: noqa: E501
# Prompts contain long lines for readability

from __future__ import annotations

from typing import Any

# JSON schema for the response requested by get_combined_quality_prompt below.
# Used by AnthropicBackend as a structured-outputs schema (API-guaranteed valid
# JSON). Structured outputs require additionalProperties: false and full
# "required" lists on every object.
ISSUES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "suggestion"],
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "grammar",
                            "clarity",
                            "style",
                            "params",
                            "returns",
                            "exceptions",
                            "completeness",
                            "accuracy",
                        ],
                    },
                    "message": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "line_reference": {"type": ["string", "null"]},
                },
                "required": [
                    "severity",
                    "category",
                    "message",
                    "suggestion",
                    "line_reference",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}


def get_combined_quality_prompt(
    signature: str, docstring: str, api_name: str, code_snippet: str | None = None
) -> str:
    """Combined prompt for all quality checks (faster, single LLM call).

    Args:
        signature: Function signature
        docstring: The docstring
        api_name: Full API name
        code_snippet: Optional code body

    Returns:
        Formatted prompt
    """
    code_section = ""
    if code_snippet:
        code_section = f"""
Code implementation (excerpt):
```python
{code_snippet}
```
"""

    return f"""Think longer. You are a senior technical writer reviewing Python documentation for a quantum computing library with 15 years of experience.

Task: Comprehensive quality review of `{api_name}` documentation.

Signature:
```python
{signature}
```

Docstring:
```
{docstring}
```
{code_section}

Check ALL of:
1. **English Quality**: grammar, spelling, clarity, style
2. **Code Alignment**: docstring matches the signature AND the code implementation shown
3. **Input Variables**: every parameter in the signature is documented; names, types, and defaults match the signature; and each description matches how the parameter is actually used in the code (flag undocumented, renamed, mistyped, or wrongly-described parameters)
4. **Completeness**: all parameters, returns, raised exceptions documented
5. **Technical Accuracy**: correct terminology, accurate descriptions

CRITICAL: Use simple, clear language. Provide concrete before/after examples for every issue.

GROUNDING: Base every issue and fix ONLY on the signature, docstring, and code excerpt shown above. The code excerpt may be truncated; if a correct fix would require knowing runtime behavior, default values, or parent-class semantics that are NOT shown here, say so in the message and keep the suggestion tentative. Never assert behavior you cannot see. The signature is rendered faithfully from the code, so do NOT report mismatches between the signature and the implementation.

LIMIT: Report EVERY critical issue you find (never omit a critical one). For warning- and suggestion-level issues, report only the few most important and omit the rest to keep the response focused.

Respond ONLY with valid JSON (no markdown):
{{
  "issues": [
    {{
      "severity": "critical|warning|suggestion",
      "category": "grammar|clarity|style|params|returns|exceptions|completeness|accuracy",
      "message": "Simple explanation anyone can understand",
      "suggestion": "Specific fix with before/after example",
      "line_reference": "exact problematic text or null"
    }}
  ]
}}

Example issue formats:

Grammar issue:
{{
  "message": "Missing article 'the' makes sentence unclear",
  "suggestion": "Change 'Evolves state' to 'Evolves the state'",
  "line_reference": "Evolves state"
}}

Missing parameter:
{{
  "message": "Parameter 'dt' is not documented",
  "suggestion": "Add: 'dt (float): Time step in nanoseconds. Default: 10'",
  "line_reference": null
}}

Incomplete description:
{{
  "message": "Doesn't explain what MPS truncation does",
  "suggestion": "Add: 'Truncation removes small singular values to control memory, trading accuracy for performance'",
  "line_reference": "Performs MPS truncation"
}}

Severity guide:
- critical: Wrong info, code/docstring contradictions, undocumented or mismatched parameters (name, type, or default differs from the signature), missing required docs, major grammar errors
- warning: Unclear phrasing, minor inconsistencies, missing nice-to-haves
- suggestion: Style improvements, additional examples"""
