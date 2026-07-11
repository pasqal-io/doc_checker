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


# Params always skipped by the undocumented-parameter check. Kept minimal:
# self/cls are already stripped during signature extraction, so this is only
# belt-and-suspenders. Enum-machinery names live in ENUM_IGNORE_PARAMS below and
# must NOT be listed here, or real non-enum params of those names (e.g. a
# `values` or `type` argument) would silently escape documentation checks.
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
