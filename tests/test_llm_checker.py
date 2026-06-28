"""Tests for LLM quality checker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doc_checker.checkers_folder.quality import LLMQualityChecker, QualityChecker
from doc_checker.models import DriftReport, QualityIssue, SignatureInfo


def _issue(severity: str) -> QualityIssue:
    return QualityIssue(
        api_name="m.api",
        severity=severity,
        category="clarity",
        message="msg",
        suggestion="fix",
        line_reference=None,
    )


@pytest.fixture
def mock_backend():
    """Mock LLM backend."""
    backend = MagicMock()
    backend.generate_json.return_value = {
        "issues": [
            {
                "severity": "warning",
                "category": "grammar",
                "message": "Test issue",
                "suggestion": "Fix it",
                "line_reference": "test text",
            }
        ],
        "score": 85,
        "summary": "Good overall",
    }
    return backend


@pytest.fixture
def mock_code_analyzer(tmp_path: Path):
    """Mock code analyzer."""
    analyzer = MagicMock()
    apis = [
        SignatureInfo(
            name="test_func",
            module="test_module",
            parameters=["x: int", "y: str = 'default'"],
            return_annotation="bool",
            docstring="Test function docstring.",
            is_public=True,
            kind="function",
        ),
        SignatureInfo(
            name="no_docstring_func",
            module="test_module",
            parameters=[],
            return_annotation=None,
            docstring=None,
            is_public=True,
            kind="function",
        ),
    ]
    analyzer.get_public_apis.return_value = apis
    analyzer.get_all_public_apis.return_value = (apis, set())
    return analyzer


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_init(mock_analyzer_class, mock_get_backend, tmp_path):
    """Test QualityChecker initialization."""
    mock_backend = MagicMock()
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = MagicMock()

    checker = QualityChecker(
        tmp_path, backend_type="ollama", model="qwen2.5:3b", api_key=None
    )

    assert checker.root_path == tmp_path
    assert checker.backend == mock_backend
    mock_get_backend.assert_called_once_with("ollama", "qwen2.5:3b", None)
    mock_analyzer_class.assert_called_once_with(tmp_path)


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_check_api_quality_success(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_backend, mock_code_analyzer
):
    """Test successful API quality check."""
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    issues = checker.check_api_quality("test_func", "test_module", verbose=False)

    assert len(issues) == 1
    assert issues[0].api_name == "test_module.test_func"
    assert issues[0].severity == "warning"
    assert issues[0].category == "grammar"
    assert issues[0].message == "Test issue"
    assert issues[0].suggestion == "Fix it"
    assert issues[0].line_reference == "test text"


@patch("doc_checker.checkers_folder.quality.get_combined_quality_prompt")
@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_forwards_source_excerpt(
    mock_analyzer_class, mock_get_backend, mock_prompt, tmp_path, mock_backend
):
    """check_api_quality passes the API's source excerpt to the prompt builder."""
    api = SignatureInfo(
        name="test_func",
        module="test_module",
        parameters=["x: int"],
        return_annotation="bool",
        docstring="Docstring.",
        is_public=True,
        kind="function",
        source_excerpt="def test_func(x):\n    return x > 0",
    )
    analyzer = MagicMock()
    analyzer.get_public_apis.return_value = [api]
    mock_analyzer_class.return_value = analyzer
    mock_get_backend.return_value = mock_backend
    mock_prompt.return_value = "prompt"

    checker = QualityChecker(tmp_path)
    checker.check_api_quality("test_func", "test_module")

    assert mock_prompt.call_args.kwargs["code_snippet"] == (
        "def test_func(x):\n    return x > 0"
    )


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_api_not_found(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_backend, mock_code_analyzer
):
    """Test quality check for non-existent API."""
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    issues = checker.check_api_quality("nonexistent", "test_module")

    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].category == "error"
    assert "not found" in issues[0].message


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_no_docstring(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_backend, mock_code_analyzer
):
    """Test quality check for API without docstring."""
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    issues = checker.check_api_quality("no_docstring_func", "test_module")

    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].category == "completeness"
    assert "No docstring" in issues[0].message


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_llm_failure(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_code_analyzer
):
    """Test quality check handles LLM failures gracefully."""
    mock_backend = MagicMock()
    mock_backend.generate_json.side_effect = Exception("LLM error")
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    issues = checker.check_api_quality("test_func", "test_module")

    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].category == "error"
    assert "LLM check failed" in issues[0].message


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_surfaces_parse_failure(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_code_analyzer
):
    """An unparseable/empty LLM response is reported, not silently dropped."""
    mock_backend = MagicMock()
    mock_backend.generate_json.return_value = {
        "error": "Failed to parse JSON: Expecting value",
        "raw_response": "",
        "issues": [],
    }
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    issues = checker.check_api_quality("test_func", "test_module")

    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].category == "error"
    assert "could not be parsed" in issues[0].message


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_uses_cache(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_backend, mock_code_analyzer
):
    """A second check of the same API hits the cache instead of the backend."""
    from doc_checker.cache import ResponseCache

    mock_backend.model = "test-model"
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    cache = ResponseCache(tmp_path / "cache")
    checker = QualityChecker(tmp_path, cache=cache)
    checker.check_api_quality("test_func", "test_module")
    checker.check_api_quality("test_func", "test_module")

    assert mock_backend.generate_json.call_count == 1


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_does_not_cache_errors(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_code_analyzer
):
    """Error responses are not cached, so a later run can retry."""
    from doc_checker.cache import ResponseCache

    mock_backend = MagicMock()
    mock_backend.model = "test-model"
    mock_backend.generate_json.return_value = {"error": "boom", "issues": []}
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    cache = ResponseCache(tmp_path / "cache")
    checker = QualityChecker(tmp_path, cache=cache)
    checker.check_api_quality("test_func", "test_module")
    checker.check_api_quality("test_func", "test_module")

    assert mock_backend.generate_json.call_count == 2


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_verbose_output(
    mock_analyzer_class,
    mock_get_backend,
    tmp_path,
    mock_backend,
    mock_code_analyzer,
    capsys,
):
    """Test quality checker verbose output."""
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    checker.check_api_quality("test_func", "test_module", verbose=True)

    captured = capsys.readouterr()
    assert "Checking test_module.test_func" in captured.out
    assert "Found 1 issues" in captured.out


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_check_module_quality(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_backend, mock_code_analyzer
):
    """Test checking entire module quality."""
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    issues = checker.check_module_quality("test_module", verbose=False)

    # Checks both: test_func (LLM issue) and no_docstring_func (no docstring)
    assert len(issues) == 2
    names = {i.api_name for i in issues}
    assert "test_module.test_func" in names
    assert "test_module.no_docstring_func" in names


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_sample_rate(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_backend
):
    """Test quality checker sampling."""
    # Create 10 APIs
    apis = [
        SignatureInfo(
            name=f"func_{i}",
            module="test_module",
            parameters=[],
            return_annotation=None,
            docstring=f"Function {i}",
            is_public=True,
            kind="function",
        )
        for i in range(10)
    ]

    mock_analyzer = MagicMock()
    mock_analyzer.get_public_apis.return_value = apis
    mock_analyzer.get_all_public_apis.return_value = (apis, set())
    mock_analyzer_class.return_value = mock_analyzer
    mock_get_backend.return_value = mock_backend

    checker = QualityChecker(tmp_path)
    issues = checker.check_module_quality("test_module", verbose=False, sample_rate=0.3)

    # Should check ~3 APIs (30% of 10)
    # Each API generates 1 issue, so ~3 issues
    assert 1 <= len(issues) <= 5  # Allow some variance due to random sampling


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_multiple_issues(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_code_analyzer
):
    """Test quality check with multiple issues."""
    mock_backend = MagicMock()
    mock_backend.generate_json.return_value = {
        "issues": [
            {
                "severity": "critical",
                "category": "params",
                "message": "Missing parameter",
                "suggestion": "Add param doc",
                "line_reference": None,
            },
            {
                "severity": "warning",
                "category": "grammar",
                "message": "Typo",
                "suggestion": "Fix spelling",
                "line_reference": "speling",
            },
            {
                "severity": "suggestion",
                "category": "completeness",
                "message": "Add example",
                "suggestion": "Show usage",
                "line_reference": None,
            },
        ],
        "score": 65,
        "summary": "Needs improvement",
    }
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    issues = checker.check_api_quality("test_func", "test_module")

    assert len(issues) == 3
    assert issues[0].severity == "critical"
    assert issues[1].severity == "warning"
    assert issues[2].severity == "suggestion"


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_no_issues(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_code_analyzer
):
    """Test quality check with perfect documentation."""
    mock_backend = MagicMock()
    mock_backend.generate_json.return_value = {
        "issues": [],
        "score": 100,
        "summary": "Perfect documentation",
    }
    mock_get_backend.return_value = mock_backend
    mock_analyzer_class.return_value = mock_code_analyzer

    checker = QualityChecker(tmp_path)
    issues = checker.check_api_quality("test_func", "test_module")

    assert len(issues) == 0


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_quality_checker_empty_module(
    mock_analyzer_class, mock_get_backend, tmp_path, mock_backend
):
    """Test quality check on module with no APIs."""
    mock_analyzer = MagicMock()
    mock_analyzer.get_public_apis.return_value = []
    mock_analyzer.get_all_public_apis.return_value = ([], set())
    mock_analyzer_class.return_value = mock_analyzer
    mock_get_backend.return_value = mock_backend

    checker = QualityChecker(tmp_path)
    issues = checker.check_module_quality("empty_module")

    assert len(issues) == 1
    assert "No public APIs found" in issues[0].message


@patch("doc_checker.checkers_folder.quality.QualityChecker")
def test_llm_quality_checker_filters_below_min_severity(mock_qc_class, tmp_path):
    """LLMQualityChecker drops issues below min_severity before they reach the report."""
    inner = MagicMock()
    inner.backend.model = "fake-model"
    inner.check_module_quality.return_value = [
        _issue("suggestion"),
        _issue("warning"),
        _issue("critical"),
    ]
    mock_qc_class.return_value = inner

    checker = LLMQualityChecker(tmp_path, ["m"], set(), min_severity="warning")
    report = DriftReport()
    checker.check(report)

    kept = {i.severity for i in report.quality_issues}
    assert kept == {"warning", "critical"}


@patch("doc_checker.checkers_folder.quality.QualityChecker")
def test_llm_quality_checker_default_keeps_only_critical(mock_qc_class, tmp_path):
    """Default min_severity is critical; lower severities are dropped, unknown kept."""
    inner = MagicMock()
    inner.backend.model = "fake-model"
    inner.check_module_quality.return_value = [
        _issue("suggestion"),
        _issue("warning"),
        _issue("critical"),
        _issue("mystery"),
    ]
    mock_qc_class.return_value = inner

    checker = LLMQualityChecker(tmp_path, ["m"], set())
    report = DriftReport()
    checker.check(report)

    kept = {i.severity for i in report.quality_issues}
    assert kept == {"critical", "mystery"}
