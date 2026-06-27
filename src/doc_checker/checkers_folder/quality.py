from __future__ import annotations

import random
from pathlib import Path

from doc_checker.constants import SEVERITY_RANK
from doc_checker.llm_backends import get_backend
from doc_checker.models import DriftReport, QualityIssue, SignatureInfo
from doc_checker.prompts import get_combined_quality_prompt
from doc_checker.utils.code_analyzer import CodeAnalyzer

from .base import Checker


class LLMQualityChecker(Checker):
    """LLM-based docstring quality analysis.

    Supports ollama and openai backends. Checks docstring completeness,
    clarity, and accuracy for public APIs.
    """

    def __init__(
        self,
        root_path: Path,
        modules: list[str],
        ignore_submodules: set[str],
        backend_type: str = "ollama",
        model: str | None = None,
        api_key: str | None = None,
        sample_rate: float = 1.0,
        min_severity: str = "critical",
        verbose: bool = False,
    ):
        self.root_path = root_path
        self.modules = modules
        self.ignore_submodules = ignore_submodules
        self.backend_type = backend_type
        self.model = model
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.min_severity = min_severity
        self.verbose = verbose

    def check(self, report: DriftReport) -> None:
        """Run LLM quality checks; skip with warning if deps missing."""
        try:
            checker = QualityChecker(
                self.root_path,
                self.backend_type,
                self.model,
                self.api_key,
                ignore_submodules=self.ignore_submodules,
            )
        except (ImportError, RuntimeError, ValueError) as e:
            report.warnings.append(f"Quality checks skipped: {e}")
            return
        if self.verbose:
            print(f"LLM quality checks ({self.backend_type}, {checker.backend.model})...")
        threshold = SEVERITY_RANK[self.min_severity]
        for module in self.modules:
            issues = checker.check_module_quality(module, self.verbose, self.sample_rate)
            report.quality_issues.extend(
                issue
                for issue in issues
                if SEVERITY_RANK.get(issue.severity, 99) >= threshold
            )


class QualityChecker:
    """Check documentation quality using LLMs."""

    def __init__(
        self,
        root_path: Path,
        backend_type: str = "ollama",
        model: str | None = None,
        api_key: str | None = None,
        ignore_submodules: set[str] | None = None,
    ):
        """Initialize quality checker.

        Args:
            root_path: Project root path
            backend_type: "ollama" (default) or "openai"
            model: Model name (uses defaults if None)
            api_key: API key for cloud backends
            ignore_submodules: Submodule names to skip.

        Raises:
            ImportError: If backend package not installed
            RuntimeError: If backend not available
        """
        self.root_path = root_path
        self.code_analyzer = CodeAnalyzer(root_path)
        self.backend = get_backend(backend_type, model, api_key)
        self.ignore_submodules = ignore_submodules

    def check_api_quality(
        self, api_name: str, module_name: str, verbose: bool = False
    ) -> list[QualityIssue]:
        """Check quality of single API documentation.

        Args:
            api_name: API name (e.g., "MPS.evolve")
            module_name: Module name (e.g., "emu_mps")
            verbose: Print progress

        Returns:
            List of quality issues found
        """
        # Get API info
        apis = self.code_analyzer.get_public_apis(module_name)
        api_info = next((api for api in apis if api.name == api_name), None)

        if not api_info:
            return [
                QualityIssue(
                    api_name=f"{module_name}.{api_name}",
                    severity="critical",
                    category="error",
                    message=f"API {api_name} not found in module {module_name}",
                    suggestion="Check API name spelling",
                    line_reference=None,
                )
            ]

        return self._check_api_info(api_info, verbose)

    def _check_api_info(
        self, api_info: SignatureInfo, verbose: bool = False
    ) -> list[QualityIssue]:
        """Run quality checks on an already-resolved API.

        Takes the SignatureInfo directly (no re-lookup), so callers that already
        discovered the API — e.g. via get_all_public_apis across submodules — do
        not get spurious "not found" results. The reported name uses the API's
        real module so submodule APIs are labelled correctly.
        """
        display_name = f"{api_info.module}.{api_info.name}"

        if not api_info.docstring:
            return [
                QualityIssue(
                    api_name=display_name,
                    severity="critical",
                    category="completeness",
                    message="No docstring found",
                    suggestion="Add docstring explaining what this API does",
                    line_reference=None,
                )
            ]

        # Build signature string
        params_str = ", ".join(api_info.parameters)
        return_str = (
            f" -> {api_info.return_annotation}" if api_info.return_annotation else ""
        )
        signature = f"def {api_info.name}({params_str}){return_str}"

        if verbose:
            print(f"  Checking {display_name}...")

        # Get LLM evaluation
        prompt = get_combined_quality_prompt(
            signature=signature,
            docstring=api_info.docstring,
            api_name=display_name,
            code_snippet=api_info.source_excerpt,
        )

        try:
            response = self.backend.generate_json(prompt)
        except Exception as e:
            return [
                QualityIssue(
                    api_name=display_name,
                    severity="critical",
                    category="error",
                    message=f"LLM check failed: {e}",
                    suggestion="Check LLM backend connection",
                    line_reference=None,
                )
            ]

        # Parse response
        issues = []
        for issue_data in response.get("issues", []):
            issues.append(
                QualityIssue(
                    api_name=display_name,
                    severity=issue_data.get("severity", "warning"),
                    category=issue_data.get("category", "unknown"),
                    message=issue_data.get("message", "No message"),
                    suggestion=issue_data.get("suggestion", "No suggestion"),
                    line_reference=issue_data.get("line_reference"),
                )
            )

        if verbose and issues:
            print(f"    Found {len(issues)} issues")

        return issues

    def check_module_quality(
        self, module_name: str, verbose: bool = False, sample_rate: float = 1.0
    ) -> list[QualityIssue]:
        """Check quality of all APIs in a module.

        Args:
            module_name: Module to check (e.g., "emu_mps")
            verbose: Print progress
            sample_rate: Check only this fraction of APIs (0.0-1.0)

        Returns:
            List of all quality issues found
        """
        apis, _ = self.code_analyzer.get_all_public_apis(
            module_name, self.ignore_submodules
        )

        if not apis:
            if verbose:
                print(f"No public APIs found in {module_name}")
            return [
                QualityIssue(
                    api_name=module_name,
                    severity="critical",
                    category="error",
                    message=f"No public APIs found in module {module_name}",
                    suggestion="Check module name or ensure it is installed",
                    line_reference=None,
                )
            ]

        # Collapse re-exports: the same object can be discovered both at the
        # top level and in its defining submodule (different module paths). Key
        # on the full contract (name + signature + docstring) so genuinely
        # distinct same-named APIs are still checked separately.
        unique_apis: list[SignatureInfo] = []
        seen: set[tuple[str, tuple[str, ...], str | None, str | None]] = set()
        for api in apis:
            key = (api.name, tuple(api.parameters), api.return_annotation, api.docstring)
            if key not in seen:
                seen.add(key)
                unique_apis.append(api)

        if sample_rate < 1.0:
            unique_apis = random.sample(unique_apis, int(len(unique_apis) * sample_rate))

        if verbose:
            print(f"Checking {len(unique_apis)} APIs in {module_name}...")

        all_issues = []
        for api in unique_apis:
            all_issues.extend(self._check_api_info(api, verbose))

        return all_issues
