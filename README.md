# doc_checker

Check documentation drift: broken links, undocumented APIs, invalid references.

**Requires:** Python >=3.9, mkdocs project with `mkdocs.yml` containing a `nav:` section and `docs/` directory. Works with [mkdocstrings](https://mkdocstrings.github.io/) `::: module.Class` syntax for API documentation.

## Features

- **API Coverage**: Ensure all public APIs have mkdocstrings references (recursive submodule discovery)
- **Reference Validation**: Check `::: module.Class` references resolve to valid Python objects
- **Link Checking**: Verify external HTTP links (async)
- **Local Links**: Validate file paths in markdown/notebooks and Python docstrings
- **Docstring Links**: Validate links embedded in Python docstrings
- **Parameter Docs**: Check function parameters mentioned in docstrings
- **mkdocs.yml Validation**: Verify nav paths exist
- **LLM Quality Checks**: Evaluate docstring quality — English, completeness, and code alignment. The model is shown the signature, docstring, and a short source excerpt, and flags code/docstring contradictions and mismatched or undocumented parameters. Reports only `critical` issues by default (see below)

## Installation

```bash
# From GitHub
pip install git+https://github.com/murogrande/doc_checker.git

# Or clone and install
git clone https://github.com/murogrande/doc_checker.git
cd doc_checker
pip install -e .

# Optional extras
pip install -e ".[async]"         # async link checking (recommended)
pip install -e ".[llm]"           # LLM quality checks (ollama)
pip install -e ".[llm-openai]"    # LLM quality checks (openai)
pip install -e ".[llm-anthropic]" # LLM quality checks (anthropic/claude)
pip install -e ".[llm-all]"       # LLM quality checks (ollama + openai + anthropic)
# claude-cli backend needs no extra — just the claude binary on PATH (claude login)
pip install -e ".[dev]"           # all dev dependencies
```

## Usage

```bash
# All checks (basic + external links + LLM quality)
doc-checker --modules my_package --root /path/to/project

# Explicitly run all checks
doc-checker --modules my_package --check-all --root /path/to/project

# Basic checks only (API coverage, references, params, local links, mkdocs)
doc-checker --modules my_package --check-basic --root /path/to/project

# External HTTP link validation only (slow)
doc-checker --modules my_package --check-external-links --root /path/to/project

# LLM quality checks (defaults: ollama/qwen3:1.7b, openai/gpt-5.6-sol,
# anthropic/claude-opus-5, claude-cli/claude-opus-5)
doc-checker --modules my_package --check-quality --root /path/to/project
doc-checker --modules my_package --check-quality --llm-backend openai --root .
doc-checker --modules my_package --check-quality --llm-backend anthropic --root .
doc-checker --modules my_package --check-quality --llm-backend anthropic --llm-effort low --root .
doc-checker --modules my_package --check-quality --llm-backend claude-cli --root .
doc-checker --modules my_package --check-quality --llm-model gpt-5.6-sol --root .
doc-checker --modules my_package --check-quality --quality-sample 0.1 --root .

# Quality reports only critical issues by default; widen to see more:
doc-checker --modules my_package --check-quality --quality-min-severity warning --root .

# Multiple modules
doc-checker --modules my_package other_pkg --root /path/to/project

# Skip specific submodules (fully qualified paths)
doc-checker --modules my_package --ignore-submodules my_package.internal --root .

# Skip Pulser re-exported APIs
doc-checker --modules my_package --ignore-pulser-reexports --root .

# JSON output
doc-checker --modules my_package --json --root /path/to/project

# Non-blocking (report issues but exit 0)
doc-checker --modules my_package --check-basic --warn-only --root /path/to/project

# Verbose
doc-checker --modules my_package --check-basic -v --root /path/to/project
```

> **OpenAI backend: gpt-5.x only.** The `openai` backend targets the gpt-5.x
> reasoning models (default `gpt-5.6-sol`) via the Responses API. These models only
> accept the default `temperature`, so the backend does not send a `temperature`
> parameter. Pointing `--llm-model` at older non-reasoning chat models
> (e.g. `gpt-4o`) is unsupported *by the openai backend*. For non-reasoning /
> non-thinking or local models, use the `ollama` backend, which runs any model.

> **Anthropic backend.** The `anthropic` backend (default `claude-opus-5`) needs
> `ANTHROPIC_API_KEY` set. It uses structured outputs, so responses are
> API-guaranteed valid JSON. `--llm-effort {low,medium,high,xhigh,max}`
> (default `medium`) is the speed/cost lever — Claude Opus 5 always thinks, and
> lower effort caps thinking depth. Sampling params (`temperature` etc.) are
> not sent; Claude Opus 5 rejects them. Thinking counts against the response
> token budget, so if an API is reported as `LLM stopped early:
> stop_reason=max_tokens`, re-run with `--llm-effort low`.

> **Claude CLI backend (dev/validation).** The `claude-cli` backend shells out
> to a local headless `claude -p` (Claude Code CLI) per API checked. Auth comes
> from your `claude login` subscription session — no `ANTHROPIC_API_KEY`, no
> pip extra, just the `claude` binary on PATH. Trade-offs vs `anthropic`: no
> structured outputs (JSON validity is best-effort), serial subprocess calls
> (slow), and it consumes your subscription quota. Use it to validate the
> quality pipeline locally; use `anthropic` for CI/production.

### Quality severity

Every quality issue the model returns is rated `critical`, `warning`, or
`suggestion`. `--quality-min-severity` drops everything below the threshold
*before* it reaches the report, so it also affects the exit code.

- **Default is `critical`** — only the most important issues (code/docstring
  contradictions, mismatched or undocumented parameters, missing docstrings,
  wrong info). Most runs stay quiet.
- Use `--quality-min-severity warning` or `suggestion` to also see clarity and
  style feedback.

Structural failures (missing docstring, LLM/backend error, no public APIs found,
or an unparseable/empty model response) are always emitted as `critical`, so a
broken backend can never look "clean".

### Stochastic results

Each API is checked with an independent LLM call, capped at the few most
important issues, so results are **non-deterministic across runs**: precision is
high (few false positives), but a single run may not surface *every* real issue —
different runs can catch different ones. For a more exhaustive audit, run a few
times and combine the results rather than trusting one run to be complete.

## Pre-commit Hook

Add to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/murogrande/doc_checker
  rev: main  # use a tag for stable usage
  hooks:
    # Basic checks: API coverage, broken refs, params, local links, mkdocs nav
    - id: doc-checker-basic
      args: ["--modules", "my_package"]

    # External link validation (slower, runs async HTTP requests)
    - id: doc-checker-links
      args: ["--modules", "my_package"]
      verbose: true
```

Hooks use `language: system`, so `doc-checker` must be installed in your environment.

Use `--warn-only` for non-blocking checks:

```yaml
    - id: doc-checker-basic
      args: ["--modules", "my_package", "--warn-only"]
```

## Architecture

```
CLI -> DriftDetector -> checkers_folder/ -> DriftReport -> formatters
                            |
                            ├── utils/parsers.py      (MarkdownParser, YamlParser)
                            ├── utils/code_analyzer.py (CodeAnalyzer)
                            ├── utils/link_checker.py  (async HTTP)
                            ├── llm_backends.py        (Ollama/OpenAI/Anthropic/ClaudeCli backends)
                            └── prompts.py             (LLM prompt templates)
```

**Modules:**
- `checkers.py` - DriftDetector orchestrates checkers from `checkers_folder/`
- `checkers_folder/` - Individual checker implementations (ApiCoverageChecker, ReferencesChecker, ParamDocsChecker, LocalLinksChecker, DocstringsLinksChecker, NavPathsChecker, ExternalLinksChecker, LLMQualityChecker)
- `utils/parsers.py` - MarkdownParser (single-pass scan, cached) / YamlParser
- `utils/code_analyzer.py` - Introspect Python modules via importlib/inspect (cached)
- `utils/link_checker.py` - Async HTTP validation (aiohttp or urllib fallback)
- `llm_backends.py` - OllamaBackend / OpenAIBackend / AnthropicBackend / ClaudeCliBackend abstraction
- `prompts.py` - LLM prompt templates
- `models.py` - Dataclasses (SignatureInfo, DocReference, DriftReport, etc.)
- `formatters.py` - Report rendering (text/JSON)
- `cli.py` - Command-line interface

## Example Output

```
============================================================
DOCUMENTATION DRIFT REPORT
============================================================

Missing from docs (2):
  - my_package.MyClass.some_method
  - my_package.utils.helper_func

Broken references (1):
  - my_package.OldClass in docs/api.md:42

Broken local links (1):
  docs/guide.md:15: ../missing-file.md

External links: 1/42 broken
  docs/guide.md:20: https://example.com/broken (status: 404)

Undocumented parameters (1):
  - my_package.MyClass.__init__: timeout, retries

============================================================
```
