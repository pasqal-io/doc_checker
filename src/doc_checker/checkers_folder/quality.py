from __future__ import annotations

import math
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from doc_checker.constants import DEFAULT_QUALITY_JOBS, SEVERITY_RANK, VALID_EFFORTS
from doc_checker.llm_backends import get_backend
from doc_checker.models import DriftReport, QualityIssue, SignatureInfo
from doc_checker.prompts import get_combined_quality_prompt
from doc_checker.utils.code_analyzer import CodeAnalyzer

from .base import Checker


def _single_issue(
    api_name: str,
    message: str,
    suggestion: str,
    *,
    severity: str = "critical",
    category: str = "error",
) -> list[QualityIssue]:
    """One-element issue list for the structural / error early-return paths.

    These returns all carry a single ``critical`` issue with no line reference;
    factoring them out keeps each call site to its meaningful fields (message,
    suggestion) instead of repeating the full QualityIssue construction.
    """
    return [
        QualityIssue(
            api_name=api_name,
            severity=severity,
            category=category,
            message=message,
            suggestion=suggestion,
            line_reference=None,
        )
    ]


class LLMQualityChecker(Checker):
    """LLM-based docstring quality analysis.

    Supports ollama, openai and anthropic backends. Checks docstring
    completeness, clarity, and accuracy for public APIs.
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
        effort: str = "medium",
        max_workers: int = DEFAULT_QUALITY_JOBS,
    ):
        self.root_path = root_path
        self.modules = modules
        self.ignore_submodules = ignore_submodules
        self.backend_type = backend_type
        self.model = model
        self.api_key = api_key
        if effort not in VALID_EFFORTS:
            raise ValueError(
                f"Invalid effort {effort!r}; choose from {sorted(VALID_EFFORTS)}"
            )
        self.effort = effort
        self.sample_rate = sample_rate
        if min_severity not in SEVERITY_RANK:
            raise ValueError(
                f"Invalid min_severity {min_severity!r}; "
                f"choose from {sorted(SEVERITY_RANK)}"
            )
        self.min_severity = min_severity
        self.verbose = verbose
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")
        self.max_workers = max_workers
        # Build the backend now so config errors (missing API key, unknown backend)
        # raise ValueError before any checker runs. Only a missing package or an
        # unreachable local service is a soft skip.
        self._checker: QualityChecker | None = None
        self._skip_reason: str | None = None
        try:
            self._checker = QualityChecker(
                self.root_path,
                self.backend_type,
                self.model,
                self.api_key,
                ignore_submodules=self.ignore_submodules,
                effort=self.effort,
                max_workers=self.max_workers,
            )
        except (ImportError, RuntimeError) as e:
            self._skip_reason = str(e)

    def check(self, report: DriftReport) -> None:
        """Run LLM quality checks; skip with warning if deps missing."""
        if self._checker is None:
            report.warnings.append(f"Quality checks skipped: {self._skip_reason}")
            return
        checker = self._checker
        if self.verbose:
            print(f"LLM quality checks ({self.backend_type}, {checker.backend.model})...")
        threshold = SEVERITY_RANK[self.min_severity]
        issues = checker.check_modules_quality(
            self.modules, self.verbose, self.sample_rate
        )
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
        effort: str = "medium",
        max_workers: int = DEFAULT_QUALITY_JOBS,
    ):
        """Initialize quality checker.

        Args:
            root_path: Project root path
            backend_type: "ollama" (default), "openai" or "anthropic"
            model: Model name (uses defaults if None)
            api_key: API key for cloud backends
            ignore_submodules: Submodule names to skip.
            effort: Effort level for the anthropic backend (ignored by others).
            max_workers: Parallel LLM calls; 1 = sequential.

        Raises:
            ImportError: If backend package not installed
            RuntimeError: If backend not available
        """
        self.root_path = root_path
        self.code_analyzer = CodeAnalyzer(root_path)
        self.backend = get_backend(backend_type, model, api_key, effort=effort)
        self.ignore_submodules = ignore_submodules
        self.max_workers = max_workers

    def _check_api_info(
        self, api_info: SignatureInfo, verbose: bool = False
    ) -> list[QualityIssue]:
        """Run quality checks on one already-discovered API.

        The reported name uses the API's real module so submodule APIs are
        labelled correctly.
        """
        display_name = f"{api_info.module}.{api_info.name}"

        if not api_info.docstring:
            return _single_issue(
                display_name,
                "No docstring found",
                "Add docstring explaining what this API does",
                category="completeness",
            )

        # Prefer inspect.signature's faithful rendering (keeps "*", keyword-only
        # markers, full annotations); fall back to the reconstructed form.
        if api_info.signature is not None:
            signature = f"def {api_info.name}{api_info.signature}"
        else:
            params_str = ", ".join(api_info.parameters)
            return_str = (
                f" -> {api_info.return_annotation}" if api_info.return_annotation else ""
            )
            signature = f"def {api_info.name}({params_str}){return_str}"

        if verbose:
            print(f"  Checking {display_name}...")

        # Everything from source lookup to the backend call is inside the try:
        # this runs on a pool worker, and an escaping exception would abort the
        # whole module instead of producing one error issue for this API.
        try:
            # Source fetched on demand so only APIs reaching the LLM pay the
            # inspect.getsource cost; a pre-set excerpt (e.g. in tests) wins.
            code_snippet = (
                api_info.source_excerpt
                or self.code_analyzer.get_source_excerpt(api_info.module, api_info.name)
            )
            prompt = get_combined_quality_prompt(
                signature=signature,
                docstring=api_info.docstring,
                api_name=display_name,
                code_snippet=code_snippet,
            )
            response = self.backend.generate_json(prompt)
        except Exception as e:
            return _single_issue(
                display_name,
                f"LLM check failed: {e}",
                "Check LLM backend connection",
            )

        # An unparseable/empty response carries an "error" key + no issues; surface
        # it as critical instead of reporting a falsely clean API.
        if response.get("error"):
            return _single_issue(
                display_name,
                f"LLM response could not be parsed: {response['error']}",
                "Model returned malformed or empty output; re-run",
            )

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
            print(f"    Found {len(issues)} issues in {display_name}")

        return issues

    def check_modules_quality(
        self, modules: list[str], verbose: bool = False, sample_rate: float = 1.0
    ) -> list[QualityIssue]:
        """Check quality of all APIs in the given modules.

        APIs from every module share one thread pool, so no worker idles at a
        module boundary, and re-exports are deduped across modules so the same
        object is sent to the LLM once.

        Args:
            modules: Modules to check (e.g., ["emu_mps", "emu_sv"])
            verbose: Print progress
            sample_rate: Check only this fraction of each module's APIs, in (0.0, 1.0]

        Returns:
            List of all quality issues found
        """
        issues: list[QualityIssue] = []
        unique_apis: list[SignatureInfo] = []
        seen: set[object] = set()
        for module_name in modules:
            apis, _ = self.code_analyzer.get_all_public_apis(
                module_name, self.ignore_submodules
            )
            if not apis:
                if verbose:
                    print(f"No public APIs found in {module_name}")
                issues += _single_issue(
                    module_name,
                    f"No public APIs found in module {module_name}",
                    "Check module name or ensure it is installed",
                )
                continue

            # Dedupe re-exports by canonical identity (defining module + qualname)
            # so duplicates merge but distinct same-named APIs stay separate
            # (contract fallback).
            module_apis: list[SignatureInfo] = []
            for api in apis:
                key: object = self.code_analyzer.get_canonical_key(api.module, api.name)
                if key is None:
                    key = (
                        api.name,
                        tuple(api.parameters),
                        api.return_annotation,
                        api.docstring,
                    )
                if key not in seen:
                    seen.add(key)
                    module_apis.append(api)

            if sample_rate < 1.0 and module_apis:
                # Round up so a small module with positive sample_rate still checks
                # at least one API instead of truncating to zero (int(1 * 0.5) == 0).
                k = max(1, math.ceil(len(module_apis) * sample_rate))
                module_apis = random.sample(module_apis, k)

            if verbose:
                print(f"Checking {len(module_apis)} APIs in {module_name}...")
            unique_apis += module_apis

        # Each API is an independent blocking LLM call, so run them on a bounded
        # thread pool (1 worker == sequential). pool.map preserves input order,
        # keeping issue ordering deterministic, and _check_api_info turns any
        # per-API exception into a single error issue so one bad call never
        # aborts the rest. Not a `with` block: on Ctrl-C, __exit__ would join the
        # in-flight calls (unbounded for ollama) before the KeyboardInterrupt
        # could reach cli.main; shutdown(wait=False) lets it propagate at once.
        pool = ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            results = pool.map(
                lambda api: self._check_api_info(api, verbose), unique_apis
            )
            issues += [issue for api_issues in results for issue in api_issues]
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown()

        return issues
