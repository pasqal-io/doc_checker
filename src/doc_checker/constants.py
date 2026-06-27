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


IGNORE_PARAMS = {
    "value",
    "names",
    "module",
    "qualname",
    "type",
    "start",
    "boundary",
    "cls",
}


# Ordering of quality-issue severities, low to high. Used by --quality-min-severity
# to filter out issues below a threshold. Unknown severities are always kept.
SEVERITY_RANK = {
    "suggestion": 1,
    "warning": 2,
    "critical": 3,
}
