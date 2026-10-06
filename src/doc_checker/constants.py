PULSER_REEXPORTS = {  # TODO: make configurable via CLI
    "BitStrings",
    "CorrelationMatrix",
    "Energy",
    "EnergyVariance",
    "EnergySecondMoment",
    "Expectation",
    "Fidelity",
    "Occupation",
    "StateResult",
    "Results",
}


# Params always skipped by the undocumented-param check (self/cls already stripped).
# Enum-machinery names go in ENUM_IGNORE_PARAMS below, NOT here, not to mask real params.
IGNORE_PARAMS = {
    "cls",
}


# Enum functional-API machinery params (not user-facing). Dropped only for
# Enum subclasses, gated by `is_enum` in the signature extractor.
ENUM_IGNORE_PARAMS = {
    "value",
    "values",
    "names",
    "module",
    "qualname",
    "type",
    "start",
    "boundary",
}


# Ordering of quality-issue severities, low to high. Used by --quality-min-severity
# to filter out issues below a threshold. Unknown severities are always kept.
SEVERITY_RANK = {
    "suggestion": 1,
    "warning": 2,
    "critical": 3,
}

# Default model per LLM backend. Single source for get_backend(), the report's
# llm_model field, and the CLI help text.
DEFAULT_MODELS = {
    "ollama": "qwen3:1.7b",
    "openai": "gpt-6.1-sol",
    "anthropic": "claude-opus-5-5",
}

# Effort levels accepted by the anthropic backend (--llm-effort).
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
