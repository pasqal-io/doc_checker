# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

doc_checker - Documentation drift detection for mkdocs projects. Detects undocumented APIs, broken mkdocstrings references, invalid HTTP/local links, mkdocs.yml nav errors, undocumented parameters, and LLM-based quality issues.

## Commands

```bash
# Install
pip install -e ".[dev]"           # all dev deps (recommended)
pip install -e ".[async]"         # async link checking (aiohttp)
pip install -e ".[llm]"           # LLM quality (ollama)
pip install -e ".[llm-openai]"    # LLM quality (openai)
pip install -e ".[llm-all]"       # LLM quality (ollama + openai)

# Tests
pytest                            # all
pytest tests/test_checkers.py -v  # single file
pytest tests/test_checkers.py::TestDriftDetector::test_name -v  # single test
pytest -v --cov=doc_checker       # coverage

# Lint
pre-commit run --all-files
mypy src/doc_checker              # type check only

# Run
doc-checker --modules my_pkg --root .                          # all checks
doc-checker --modules my_pkg --check-basic --root .            # basic only
doc-checker --modules my_pkg --check-external-links --root .   # links only
doc-checker --modules my_pkg --check-quality --root .          # LLM quality
doc-checker --modules my_pkg --ignore-submodules my_pkg.internal --root .
doc-checker --modules my_pkg --check-basic --warn-only --root .
```

## Architecture

Source lives in `src/doc_checker/`.

```
CLI (cli.py) -> DriftDetector (checkers.py) -> checkers_folder/*.py -> DriftReport (models.py) -> formatters.py
```

Supporting modules: `utils/parsers.py` (MarkdownParser/YamlParser), `utils/code_analyzer.py`, `utils/link_checker.py`, `llm_backends.py` (OllamaBackend/OpenAIBackend), `prompts.py` (LLM prompt templates).

**Checker hierarchy** (`checkers_folder/base.py`):
- `Checker` — abstract base, `check(report)` mutates `DriftReport`
- `ApiChecker(Checker)` — iterates public APIs via `_iter_apis()`, subclasses implement `check_api()`; optional `setup()` runs once before the loop (build lookup tables / ref sets)
- `DocArtifactChecker(Checker)` — iterates doc artifacts via `collect()`, subclasses implement `validate()`

**Extracted checkers** (all in `checkers_folder/`):
- `api_coverage.py` — `ApiCoverageChecker(ApiChecker)`: missing API docs
- `references.py` — `ReferencesChecker(DocArtifactChecker)`: broken `:::` refs
- `doc_params.py` — `ParamDocsChecker(ApiChecker)`: undocumented params
- `local_links.py` — `LocalLinksChecker(DocArtifactChecker)`: broken file paths
- `docstrings_links.py` — `DocstringsLinksChecker(ApiChecker)`: broken links in docstrings
- `nav_paths.py` — `NavPathsChecker(DocArtifactChecker)`: mkdocs.yml nav validation
- `external_links.py` — `ExternalLinksChecker(DocArtifactChecker)`: HTTP link validation
- `quality.py` — `LLMQualityChecker(Checker)` + `QualityChecker`: LLM docstring quality; catches ImportError/RuntimeError to skip gracefully when ollama/openai not installed

`DriftDetector.check_all()` orchestrates all checkers; all imported at module level in `checkers.py`.

**Key internals:**
- `CodeAnalyzer.get_all_public_apis()` discovers APIs via `pkgutil.walk_packages()`; cached by `(module, ignore_submodules)` tuple
- `MarkdownParser` uses single-pass scanning: `_ensure_scanned()` populates refs/external/local caches in one traversal
- `LinkChecker` uses async aiohttp with urllib fallback; HEAD first, GET on 405; 403/429 accepted as not broken; concurrency capped at 5
- Reference validation (`ReferencesChecker._is_valid_reference`): progressively imports dotted path — tries `importlib.import_module("a.b.c")`, then `"a.b"` + `getattr(mod, "c")`, etc.
- Local link resolution order: direct relative from file dir -> `../` from docs root -> absolute from project root -> mkdocs URL-style with auto `.ipynb` extension
- `PULSER_REEXPORTS`, `IGNORE_PARAMS`, `ENUM_IGNORE_PARAMS`, and `SEVERITY_RANK` live in `constants.py`. `ENUM_IGNORE_PARAMS` (value, names, module, qualname, ...) is the enum functional-API machinery, dropped only for `Enum` subclasses via the `is_enum` gate in `_extract_class_signature`
- `SignatureInfo.signature` holds inspect.signature's faithful rendering (keeps `*`, keyword-only markers, full annotations), populated by both extractors; `_check_api_info` prefers it (`def <name><signature>`) over the reconstructed `parameters`/`return_annotation` form when building the prompt signature
- `OpenAIBackend` is gpt-5.x only (default `gpt-5.6-sol`); uses Responses API (`client.responses.create`, `max_output_tokens=16384`). gpt-5.x reasoning models reject custom `temperature`, so `generate()` sends none (the `temperature` param was removed from the backend interface). OllamaBackend hardcodes `temperature=0.1`. Older non-reasoning chat models (gpt-4o etc.) are unsupported.
- `prompts.py` has a single template, `get_combined_quality_prompt` (one LLM call per API). It requests only an `issues` array (no `score`/`summary` — those were unused) and instructs the model not to assert behavior it cannot see. Checks include input-variable alignment (params documented, names/types/defaults match, descriptions match usage) and code alignment.
- Code-vs-docstring alignment: source is fetched on demand, NOT during discovery — `get_public_apis`/`get_all_public_apis` leave `SignatureInfo.source_excerpt=None` so basic checkers pay no `inspect.getsource` cost. The quality checker calls `CodeAnalyzer.get_source_excerpt(module, name)` (public; re-imports + `getattr`, delegates to `_get_source_excerpt`) per unique API after dedup, capturing up to `MAX_SOURCE_LINES` (25) of source (classes prefer their own `__init__`); `_check_api_info` uses `api_info.source_excerpt or get_source_excerpt(...)` and forwards it as the prompt's `code_snippet`. Inherited/parent-class behavior is still a blind spot.
- `QualityChecker._check_api_info(SignatureInfo)` runs the docstring/LLM checks on an already-resolved API; `check_module_quality` calls it directly (no re-lookup, so submodule-only APIs don't get false "not found"), reports the API's real module path, and dedupes re-exports by canonical identity — `CodeAnalyzer.get_canonical_key(module, name)` returns `(defining_module, qualname)` so re-exports of the same object collapse while distinct same-named objects stay separate, falling back to the content tuple `(name, parameters, return_annotation, docstring)` when the object can't be resolved. Sampling rounds up (`max(1, math.ceil(len*rate))`) so a positive `sample_rate` always checks ≥1 API. `check_api_quality(name, module)` is the public lookup wrapper.
- `--quality-min-severity` (`suggestion`|`warning`|`critical`) filters quality issues in `LLMQualityChecker.check()` via `SEVERITY_RANK` before they reach the report, so it also affects exit code; unknown severities are always kept. Default is `critical` everywhere (CLI, `check_all`, `LLMQualityChecker`) — only the most important issues. The prompt's severity guide classifies code/docstring contradictions and mismatched/undocumented params as `critical`, and structural failures (no docstring, LLM/backend error, no public APIs) are emitted as `critical`, so both survive the filter
- A returned-but-unparseable/empty LLM response (`generate_json` puts an `error` key + empty `issues`) is surfaced by `_check_api_info` as a `critical` `error` issue instead of being silently treated as a clean API (matters for reasoning models that can exhaust `max_output_tokens` on reasoning and return empty `output_text`).
- No check flags -> runs all checks; `--check-basic` skips external/quality
- `--warn-only` always exits 0
- Notebook links: `.md` -> `.ipynb` required; `.ipynb` -> `.ipynb` forbidden

## Tests

Tests use `tmp_path` fixtures in `conftest.py` (`tmp_docs`, `sample_markdown`, `sample_notebook`, `sample_mkdocs_yml`). Each test creates isolated temp project structure with fake modules and docs. Test files mirror source modules: `test_checkers.py`, `test_parsers.py`, `test_code_analyzer.py`, `test_link_checker.py`, `test_external_links.py`, `test_llm_checker.py`, `test_llm_backends.py`, `test_prompts.py`, `test_integration.py`.

## Config

- line-length: 90 (black/ruff)
- mypy: strict (excludes tests/, ignores ollama/openai imports)
- pre-commit: black, ruff (--fix), mypy, trailing-whitespace, end-of-file-fixer
- Python >=3.9
