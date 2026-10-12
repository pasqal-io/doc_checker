# Parallel LLM Quality Checks (`--quality-jobs`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the per-API LLM quality checks on a bounded thread pool so `--check-quality` on a large module is not N sequential round-trips (GitHub issue #7).

**Architecture:** `QualityChecker.check_module_quality` swaps its sequential loop for `ThreadPoolExecutor.map` (order-preserving) when `max_workers > 1`. The knob is threaded `cli --quality-jobs` → `DriftDetector.check_all(quality_jobs=)` → `LLMQualityChecker(max_workers=)` → `QualityChecker(max_workers=)`. `_check_api_info` is untouched; it already turns backend exceptions into a single critical issue, so one failing task never kills the pool.

**Tech Stack:** Python >=3.9, stdlib `concurrent.futures`, pytest, `unittest.mock`.

## Global Constraints

- Default pool size is **5** everywhere (CLI, `check_all`, `LLMQualityChecker`, `QualityChecker`).
- `max_workers <= 1` must take the exact current list-comprehension path (no executor constructed).
- Returned issue order must equal the sequential order (`unique_apis` order).
- Verbose per-API prints stay as they are; interleaving is accepted and documented in the flag help.
- Sampling (`--quality-sample`) stays before the pool; no change there.
- `quality_jobs < 1` is rejected in `DriftDetector.validate_args` with `ValueError`; the CLI maps it to `parser.error` (exit 2).
- line-length 90 (black/ruff); `mypy src/doc_checker` strict must pass.
- Spec: `docs/superpowers/specs/2026-10-12-quality-jobs-thread-pool-design.md`.

---

### Task 1: Thread pool in `QualityChecker.check_module_quality`

**Files:**
- Modify: `src/doc_checker/checkers_folder/quality.py:1-12` (imports), `:139-170` (`QualityChecker.__init__`), `:272-314` (`check_module_quality`)
- Test: `tests/test_llm_checker.py` (append after `test_quality_checker_sample_rate_small_module_checks_at_least_one`, ~line 386)

**Interfaces:**
- Consumes: existing `QualityChecker._check_api_info(api_info: SignatureInfo, verbose: bool) -> list[QualityIssue]`.
- Produces: `QualityChecker.__init__(..., effort: str = "medium", max_workers: int = 5)` storing `self.max_workers: int`. Task 2 passes `max_workers=` from `LLMQualityChecker`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_checker.py` (after `test_quality_checker_sample_rate_small_module_checks_at_least_one`, before `test_quality_checker_multiple_issues`):

```python
def _documented_apis(n: int) -> list[SignatureInfo]:
    """n documented functions func_0..func_{n-1} in module 'm'."""
    return [
        SignatureInfo(
            name=f"func_{i}",
            module="m",
            parameters=[],
            return_annotation=None,
            docstring=f"Docstring {i}.",
            is_public=True,
            kind="function",
        )
        for i in range(n)
    ]


def _analyzer_with(apis: list[SignatureInfo]) -> MagicMock:
    analyzer = MagicMock()
    analyzer.get_all_public_apis.return_value = (apis, set())
    analyzer.get_canonical_key.return_value = None
    return analyzer


class _PeakCounter:
    """Backend stub that records how many generate_json calls overlap."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def __call__(self, prompt: str) -> dict:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return {"issues": []}


@pytest.mark.parametrize(("max_workers", "expect_parallel"), [(5, True), (1, False)])
@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_check_module_quality_concurrency(
    mock_analyzer_class, mock_get_backend, tmp_path, max_workers, expect_parallel
):
    """Default workers overlap LLM calls; max_workers=1 never does."""
    counter = _PeakCounter()
    backend = MagicMock()
    backend.generate_json.side_effect = counter
    mock_get_backend.return_value = backend
    mock_analyzer_class.return_value = _analyzer_with(_documented_apis(4))

    checker = QualityChecker(tmp_path, max_workers=max_workers)
    checker.check_module_quality("m")

    assert backend.generate_json.call_count == 4
    assert (counter.peak > 1) is expect_parallel


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_check_module_quality_order_is_deterministic(
    mock_analyzer_class, mock_get_backend, tmp_path
):
    """Issues come back in unique_apis order even when later APIs finish first."""
    mock_get_backend.return_value = MagicMock()
    apis = _documented_apis(4)
    mock_analyzer_class.return_value = _analyzer_with(apis)
    checker = QualityChecker(tmp_path, max_workers=5)

    def slow_first(api: SignatureInfo, verbose: bool = False) -> list[QualityIssue]:
        # func_0 sleeps longest so completion order is the reverse of input order
        time.sleep(0.05 * (len(apis) - int(api.name.split("_")[1])))
        return _single_issue_for(api.name)

    def _single_issue_for(name: str) -> list[QualityIssue]:
        return [
            QualityIssue(
                api_name=f"m.{name}",
                severity="critical",
                category="x",
                message=name,
                suggestion="",
                line_reference=None,
            )
        ]

    with patch.object(checker, "_check_api_info", side_effect=slow_first):
        issues = checker.check_module_quality("m")

    assert [i.message for i in issues] == ["func_0", "func_1", "func_2", "func_3"]


@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_one_failing_api_does_not_abort_others(
    mock_analyzer_class, mock_get_backend, tmp_path
):
    """A backend exception for one API yields one error issue; the rest complete."""
    backend = MagicMock()

    def flaky(prompt: str) -> dict:
        if "m.func_1" in prompt:
            raise RuntimeError("boom")
        return {"issues": []}

    backend.generate_json.side_effect = flaky
    mock_get_backend.return_value = backend
    mock_analyzer_class.return_value = _analyzer_with(_documented_apis(3))

    checker = QualityChecker(tmp_path, max_workers=5)
    issues = checker.check_module_quality("m")

    assert backend.generate_json.call_count == 3
    assert [(i.api_name, i.category) for i in issues] == [("m.func_1", "error")]
    assert "boom" in issues[0].message


@patch("doc_checker.checkers_folder.quality.ThreadPoolExecutor")
@patch("doc_checker.checkers_folder.quality.get_backend")
@patch("doc_checker.checkers_folder.quality.CodeAnalyzer")
def test_max_workers_one_is_sequential(
    mock_analyzer_class, mock_get_backend, mock_pool_class, tmp_path
):
    """max_workers=1 takes the plain loop: no executor is ever constructed."""
    backend = MagicMock()
    backend.generate_json.return_value = {"issues": []}
    mock_get_backend.return_value = backend
    mock_analyzer_class.return_value = _analyzer_with(_documented_apis(3))

    QualityChecker(tmp_path, max_workers=1).check_module_quality("m")

    mock_pool_class.assert_not_called()
    assert backend.generate_json.call_count == 3
```

Add to the imports at the top of `tests/test_llm_checker.py`:

```python
import threading
import time
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_checker.py -k "concurrency or deterministic or failing_api or sequential" -v`
Expected: 5 FAIL. Three with `TypeError: __init__() got an unexpected keyword argument 'max_workers'`, the sequential one with `AttributeError: ... does not have the attribute 'ThreadPoolExecutor'`.

- [ ] **Step 3: Implement**

In `src/doc_checker/checkers_folder/quality.py`, add to the imports:

```python
from concurrent.futures import ThreadPoolExecutor
```

Change `QualityChecker.__init__` signature and body:

```python
    def __init__(
        self,
        root_path: Path,
        backend_type: str = "ollama",
        model: str | None = None,
        api_key: str | None = None,
        ignore_submodules: set[str] | None = None,
        effort: str = "medium",
        max_workers: int = 5,
    ):
        """Initialize quality checker.

        Args:
            root_path: Project root path
            backend_type: "ollama" (default), "openai" or "anthropic"
            model: Model name (uses defaults if None)
            api_key: API key for cloud backends
            ignore_submodules: Submodule names to skip.
            effort: Effort level for the anthropic backend (ignored by others).
            max_workers: Parallel LLM calls per module; 1 = sequential.

        Raises:
            ImportError: If backend package not installed
            RuntimeError: If backend not available
        """
        self.root_path = root_path
        self.code_analyzer = CodeAnalyzer(root_path)
        self.backend = get_backend(backend_type, model, api_key, effort=effort)
        self.ignore_submodules = ignore_submodules
        self.max_workers = max_workers
```

Replace the tail of `check_module_quality` (from `all_issues = []` to `return all_issues`):

```python
        # Each API is an independent blocking LLM call, so run them on a bounded
        # thread pool. pool.map preserves input order, keeping issue ordering
        # deterministic; _check_api_info already swallows backend exceptions into
        # a single error issue, so one failure never aborts the rest.
        if self.max_workers <= 1 or len(unique_apis) <= 1:
            results = [self._check_api_info(api, verbose) for api in unique_apis]
        else:
            workers = min(self.max_workers, len(unique_apis))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(
                    pool.map(lambda api: self._check_api_info(api, verbose), unique_apis)
                )

        return [issue for issues in results for issue in issues]
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_llm_checker.py -v`
Expected: all PASS (existing tests included; the module-quality tests exercise the pool path with the default of 5).

- [ ] **Step 5: Lint and type-check**

Run: `pre-commit run --all-files && mypy src/doc_checker`
Expected: all hooks pass, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add src/doc_checker/checkers_folder/quality.py tests/test_llm_checker.py
git commit -m "Run per-API LLM quality checks on a bounded thread pool (#7)"
```

---

### Task 2: Thread `--quality-jobs` through `LLMQualityChecker`, `check_all`, `validate_args`, CLI, and docs

**Files:**
- Modify: `src/doc_checker/checkers_folder/quality.py:46-90` (`LLMQualityChecker.__init__`)
- Modify: `src/doc_checker/checkers.py:60-117` (`validate_args`), `:119-212` (`check_all`)
- Modify: `src/doc_checker/cli.py:60-67` (new argument after `--quality-min-severity`), `:120-131` (`validate_args` call), `:146-156` (`check_all` call)
- Modify: `README.md:58`, `CLAUDE.md:38`, `CLAUDE.md:83`
- Test: `tests/test_llm_checker.py`, `tests/test_checkers.py:743-766`, `tests/test_integration.py:520-530`

**Interfaces:**
- Consumes: `QualityChecker(..., max_workers: int = 5)` from Task 1.
- Produces: `LLMQualityChecker(..., effort: str = "medium", max_workers: int = 5)`; `DriftDetector.validate_args(..., quality_effort=None, quality_jobs: int = 5)`; `DriftDetector.check_all(..., quality_effort=None, quality_jobs: int = 5, verbose=False, skip_basic_checks=False)`; CLI flag `--quality-jobs N` (default 5).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_checker.py` (end of file):

```python
@patch("doc_checker.checkers_folder.quality.QualityChecker")
def test_llm_quality_checker_forwards_max_workers(mock_qc_class, tmp_path):
    """max_workers reaches the inner QualityChecker (default 5)."""
    LLMQualityChecker(tmp_path, ["m"], set())
    assert mock_qc_class.call_args.kwargs["max_workers"] == 5
    LLMQualityChecker(tmp_path, ["m"], set(), max_workers=2)
    assert mock_qc_class.call_args.kwargs["max_workers"] == 2
```

In `tests/test_checkers.py`, add two rows to the `test_check_all_rejects_invalid_quality_args` parametrize list (after the `"anthropic backend"` row):

```python
            ({"quality_jobs": 0}, "quality jobs must be >= 1"),
            ({"quality_jobs": -3}, "quality jobs must be >= 1"),
```

In `tests/test_checkers.py`, after `test_check_all_effort_with_anthropic_is_valid`, add:

```python
    def test_check_all_passes_quality_jobs(self, test_project: Path):
        """quality_jobs reaches LLMQualityChecker as max_workers."""
        from unittest.mock import patch

        detector = DriftDetector(test_project, modules=["test_pkg"])
        with patch("doc_checker.checkers.LLMQualityChecker") as mock_cls:
            mock_cls.return_value.check.return_value = None
            detector.check_all(check_quality=True, quality_jobs=3)
        assert mock_cls.call_args.kwargs["max_workers"] == 3
```

In `tests/test_integration.py`, add two rows to the `test_invalid_combination_exits_two` parametrize list (after the `--quality-sample 2` row):

```python
            (["--check-quality", "--quality-jobs", "0"], "quality jobs"),
            (["--check-quality", "--quality-jobs", "-1"], "quality jobs"),
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_checker.py::test_llm_quality_checker_forwards_max_workers tests/test_checkers.py -k "quality_jobs or rejects_invalid_quality_args" tests/test_integration.py -k "quality-jobs" -v`
Expected: the new cases FAIL (`KeyError: 'max_workers'`, `TypeError: unexpected keyword argument 'quality_jobs'`, and the CLI cases exit 2 with `unrecognized arguments: --quality-jobs` so the needle `quality jobs` is missing). Pre-existing rows still PASS.

- [ ] **Step 3: Implement `LLMQualityChecker.max_workers`**

In `src/doc_checker/checkers_folder/quality.py`, `LLMQualityChecker.__init__`:

```python
        verbose: bool = False,
        effort: str = "medium",
        max_workers: int = 5,
    ):
```

After `self.verbose = verbose` add `self.max_workers = max_workers`, and in the `QualityChecker(...)` construction add `max_workers=self.max_workers,` after `effort=self.effort,`.

- [ ] **Step 4: Implement `validate_args` and `check_all`**

In `src/doc_checker/checkers.py`, `validate_args` signature and docstring:

```python
    @staticmethod
    def validate_args(
        check_quality: bool = False,
        quality_backend: str = "ollama",
        quality_sample_rate: float = 1.0,
        quality_min_severity: str = "critical",
        quality_effort: str | None = None,
        quality_jobs: int = 5,
    ) -> None:
        """Reject invalid or silently-ignored quality option combinations.

        Called at the start of check_all; the CLI calls it too so bad flags fail
        before any API-key pre-flight or network call.

        Raises:
            ValueError: Unknown backend/severity, sample rate outside (0, 1],
                quality_jobs < 1, or an effort given without check_quality /
                with a non-anthropic backend (effort is only honoured by the
                anthropic backend).
        """
```

After the sample-rate check add:

```python
        if quality_jobs < 1:
            raise ValueError(f"quality jobs must be >= 1, got {quality_jobs}")
```

In `check_all`, add the parameter after `quality_effort`:

```python
        quality_effort: str | None = None,
        quality_jobs: int = 5,
        verbose: bool = False,
```

Docstring, after the `quality_min_severity` entry:

```
            quality_jobs: Parallel LLM calls per module (default 5; 1 = sequential).
```

Update the `self.validate_args(...)` call to pass `quality_jobs` as the last positional arg:

```python
        self.validate_args(
            check_quality,
            quality_backend,
            quality_sample_rate,
            quality_min_severity,
            quality_effort,
            quality_jobs,
        )
```

In the `LLMQualityChecker(...)` construction add `max_workers=quality_jobs,` after `effort=quality_effort or "medium",`.

- [ ] **Step 5: Implement the CLI flag**

In `src/doc_checker/cli.py`, after the `--quality-min-severity` argument:

```python
    parser.add_argument(
        "--quality-jobs",
        type=int,
        default=5,
        metavar="N",
        help="Parallel LLM quality calls per module (default: 5). With N > 1, "
        "--verbose progress lines may interleave; use 1 for sequential output.",
    )
```

In the `DriftDetector.validate_args(...)` call add `quality_jobs=args.quality_jobs,` after `quality_effort=args.llm_effort,`. In the `detector.check_all(...)` call add `quality_jobs=args.quality_jobs,` after `quality_effort=args.llm_effort,`.

- [ ] **Step 6: Run the tests**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 7: Docs**

`README.md`, after line 58 (`--quality-sample 0.1` example):

```bash
doc-checker --modules my_package --check-quality --quality-jobs 10 --root .   # 10 parallel LLM calls (default 5, 1 = sequential)
```

`CLAUDE.md` line 38, extend the flag list:

```
#   --quality-sample RATE, --quality-min-severity LEVEL, --quality-jobs N, --verbose
```

`CLAUDE.md`, add a bullet directly after the `--quality-min-severity` bullet (line 83):

```
- `--quality-jobs N` (default 5) runs the per-API LLM calls in `QualityChecker.check_module_quality` on a `ThreadPoolExecutor` (`pool.map`, so issue order matches the sequential order); `N <= 1` or a single API takes the plain loop. Threaded `--quality-jobs` → `check_all(quality_jobs=...)` → `LLMQualityChecker`/`QualityChecker(max_workers=...)`; `validate_args` rejects `< 1`. Sampling shrinks the list before the pool. Verbose per-API prints interleave under concurrency. Backends are blocking SDK calls, so threads (not asyncio) are the right tool.
```

- [ ] **Step 8: Lint and type-check**

Run: `pre-commit run --all-files && mypy src/doc_checker`
Expected: all hooks pass, `Success: no issues found`.

- [ ] **Step 9: Commit**

```bash
git add src/doc_checker/checkers_folder/quality.py src/doc_checker/checkers.py src/doc_checker/cli.py README.md CLAUDE.md tests/test_llm_checker.py tests/test_checkers.py tests/test_integration.py
git commit -m "Add --quality-jobs to bound parallel LLM quality calls (#7)"
```

---

## Self-review

- Spec coverage: pool + order + sequential path (Task 1); knob plumbing, `validate_args`, CLI exit 2, verbose help text, docs (Task 2); sampling untouched; non-goals untouched. Thread-safety note needs no code.
- Placeholders: none.
- Type consistency: `max_workers: int = 5` on both checker classes; `quality_jobs: int = 5` on `validate_args` and `check_all`; CLI `args.quality_jobs`. Error string `quality jobs must be >= 1` matches both test needles.
