# Parallel LLM quality checks (`--quality-jobs`)

Implements GitHub issue #7.

## Problem

`QualityChecker.check_module_quality` calls the LLM once per public API,
sequentially. Each call is blocking network I/O and independent of the others,
so wall-clock time scales linearly with the number of APIs.

## Design

- **Core change**: in `check_module_quality`, run `_check_api_info` over
  `unique_apis` on a `concurrent.futures.ThreadPoolExecutor` via `pool.map`.
  `map` preserves input order, so issue ordering is identical to the sequential
  version. When `max_workers <= 1` or there is at most one API, use the plain
  list comprehension (exact current behaviour).
- **No change to `_check_api_info`**: it already converts backend exceptions
  into a single critical issue, so one failing API never aborts the pool.
- **Thread safety**: `CodeAnalyzer.get_source_excerpt` runs inside the task
  and uses `importlib.import_module` + `inspect`; the import lock covers it.
  The analyzer's API cache is only written before the pool starts. The ollama,
  openai and anthropic clients are safe for concurrent calls.
- **Knob**: `max_workers: int = 5` on `QualityChecker` and `LLMQualityChecker`,
  `quality_jobs: int = 5` on `DriftDetector.check_all`, `--quality-jobs N` on
  the CLI. `DriftDetector.validate_args` rejects `N < 1` with `ValueError`,
  which the CLI maps to `parser.error` (exit 2) like the other quality flags.
- **Verbose**: per-API prints are unchanged and may interleave across threads.
  The help text says to pass `--quality-jobs 1` for sequential output.
- **Sampling** happens before the pool, so `--quality-sample` composes with
  no change.

## Tests (`tests/test_llm_checker.py`)

- peak concurrency > 1 with default workers, == 1 with `max_workers=1`
- returned issue order matches `unique_apis` order under per-call jitter
- one raising API yields a single `error` issue, the others still complete
- `max_workers=1` never constructs a `ThreadPoolExecutor`
- `validate_args` rejects `quality_jobs=0`

## Docs

One bullet in CLAUDE.md, the flag in the README options list.

## Non-goals

Async backends, cross-module parallelism, on-disk cache (issue #6).
