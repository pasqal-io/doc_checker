# LLM Quality Checks - Quick Start Guide

LLM quality checks read each public API's **signature + docstring + a short
source excerpt** and flag docstring problems: code/docstring contradictions,
mismatched or undocumented parameters, missing docstrings, and clarity/style
issues. Two backends are supported: **ollama** (local, default) and **openai**.

## Local backend (ollama)

### 1. Install Ollama

```bash
# Linux/Mac
curl -fsSL https://ollama.ai/install.sh | sh

# Start service
ollama serve
```

### 2. Pull the model

The default model is **`qwen3:1.7b`** (a small reasoning/"thinking" model, ~1.4 GB):

```bash
ollama pull qwen3:1.7b
```

Any ollama model works via `--llm-model`. Bigger, code-capable models give
noticeably better results if you have the VRAM — e.g. `qwen2.5-coder:14b`
(~12 GB) or `gpt-oss:20b` (~16 GB).

### 3. Install doc-checker with LLM support

```bash
cd /path/to/doc_checker
pip install -e ".[llm]"        # ollama backend
# or ".[llm-openai]" for openai, ".[llm-all]" for both
```

### 4. Run quality checks

```bash
# Default: ollama / qwen3:1.7b
doc-checker --modules my_package --check-quality --root /path/to/project

# Verbose (per-API progress)
doc-checker --modules my_package --check-quality --verbose --root .

# Check only 10% of APIs (faster spot-check)
doc-checker --modules my_package --check-quality --quality-sample 0.1 --root .

# Pick a different local model
doc-checker --modules my_package --check-quality --llm-model qwen2.5-coder:14b --root .

# Run alongside all other checks
doc-checker --modules my_package --check-all --root .
```

> **Note on reasoning models.** `qwen3:1.7b` emits an internal `<think>` block.
> The ollama backend strips it before parsing and allocates enough output
> tokens (`num_predict=4096`) for the reasoning + JSON, so responses parse
> cleanly. If you swap in your own model and see empty/garbled output, raise the
> token budget or use a non-thinking model.

## Severity filtering

Every issue is rated `critical`, `warning`, or `suggestion`.
`--quality-min-severity` drops everything below the threshold *before* it
reaches the report, so it also affects the exit code.

- **Default is `critical`** — only the most important issues (code/docstring
  contradictions, mismatched or undocumented parameters, missing docstrings).
  Most runs stay quiet.
- Widen to also see clarity/style feedback:

```bash
doc-checker --modules my_package --check-quality --quality-min-severity warning --root .
doc-checker --modules my_package --check-quality --quality-min-severity suggestion --root .
```

Structural failures (missing docstring, backend error, no public APIs, or an
unparseable/empty model response) are always emitted as `critical`, so a broken
backend can never look "clean".

## Stochastic results

Each API is checked with an independent LLM call, capped at the few most
important issues, so results are **non-deterministic across runs**: precision is
high (few false positives), but one run may not surface *every* real issue.
For a thorough audit, run a few times and combine results.

## Example output

Running with the default `critical` threshold:

```
Running documentation drift detection...
LLM quality checks (ollama, qwen3:1.7b)...
Checking 2 APIs in emu_mps...
  Checking emu_mps.inner...
    Found 2 issues
  Checking emu_mps.MPS...
    Found 4 issues
============================================================
DOCUMENTATION DRIFT REPORT
============================================================
LLM: ollama / qwen3:1.7b

Quality issues (2):

  ✘ CRITICAL (2):
    emu_mps.MPS [params]
      Issue: The `num_gpus_to_use` parameter is not documented in the docstring.
      Fix: Add: 'num_gpus_to_use (int): Number of GPUs to use. Default: 0 (CPU).'
      Text: num_gpus_to_use

    emu_mps.MPS [completeness]
      Issue: No exception is documented for __init__, which may raise on invalid tensors.
      Fix: Add: 'Raises ValueError if factors are not valid MPS tensors'
      Text: Raises ValueError if factors are not valid MPS tensors

============================================================
```

Each issue shows the API name and `[category]`, an `Issue:` description, a
`Fix:` suggestion, and (when available) a `Text:` line quoting the offending
docstring text. Add `--quality-min-severity warning` (or `suggestion`) to also
see `⚠ WARNING` and `ℹ SUGGESTION` entries.

## Cloud backend (openai)

The `openai` backend targets **gpt-5.x reasoning models** (default
`gpt-5.6-sol`) via the Responses API. Older non-reasoning chat models
(e.g. `gpt-4o`) are **not supported**.

```bash
# Set API key (never hard-code it)
export OPENAI_API_KEY='sk-proj-...'

# Run with OpenAI (default gpt-5.6-sol)
doc-checker --modules my_package --check-quality --llm-backend openai --root .

# Pick a specific gpt-5.x model
doc-checker --modules my_package --check-quality --llm-backend openai --llm-model gpt-5.6-sol --root .
```

## Troubleshooting

### "Ollama service not running"
```bash
ollama serve
# Wait a couple seconds, then retry doc-checker
```

### "Model not found"
```bash
ollama list              # Check installed models
ollama pull qwen3:1.7b   # Install the default model
```

### Empty / unparseable LLM response
Reported as a `critical` `error` issue ("Model returned malformed or empty
output; re-run"). Usually a reasoning model that ran out of output tokens — try
a larger/non-thinking model, or re-run.

### Out of memory
```bash
# Use a smaller model
doc-checker --modules my_package --check-quality --llm-model gemma2:2b --root .

# Or check fewer APIs
doc-checker --modules my_package --check-quality --quality-sample 0.2 --root .
```

### GPU not used (CPU fallback)
```bash
nvidia-smi     # Check CUDA is available
pkill ollama && ollama serve
```

## Security note

- Ollama runs **locally** — no data leaves your machine.
- The openai backend sends signatures, docstrings, and source excerpts to the
  OpenAI API — set `OPENAI_API_KEY` via env var, never in code.

## Next steps

1. Spot-check with `--quality-sample 0.1`.
2. Review output; widen `--quality-min-severity` if you want more feedback.
3. Run on the full codebase.
4. Integrate into CI/CD (see CLAUDE.md).
