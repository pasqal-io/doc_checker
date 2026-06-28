"""Persistent on-disk cache for LLM quality responses.

Re-running quality checks on an unchanged codebase otherwise re-pays every
LLM call. Entries are keyed by a hash of ``(model, prompt)`` and the prompt
embeds the signature, docstring, and code excerpt — so the cache
self-invalidates whenever any of those (or the prompt template) change.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def default_cache_dir() -> Path:
    """Return the cache directory (honors ``XDG_CACHE_HOME``)."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "doc_checker"


class ResponseCache:
    """Disk cache mapping ``(model, prompt)`` to a parsed LLM JSON response.

    One JSON file per entry, named by the sha256 of the key. Disabled caches
    are no-ops. Read/write errors are swallowed so caching never breaks a run.
    """

    def __init__(self, cache_dir: Path, enabled: bool = True):
        """Initialize the cache.

        Args:
            cache_dir: Directory where entries are stored (created on first write).
            enabled: If False, get/set are no-ops.
        """
        self.cache_dir = cache_dir
        self.enabled = enabled

    @staticmethod
    def make_key(model: str, prompt: str) -> str:
        """Return the sha256 cache key for a model + prompt pair."""
        return hashlib.sha256(f"{model}\x00{prompt}".encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached response for key, or None on miss/disabled/error."""
        if not self.enabled:
            return None
        try:
            with self._path(key).open(encoding="utf-8") as f:
                result: dict[str, Any] = json.load(f)
                return result
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        """Store a response for key. No-op if disabled; errors are swallowed."""
        if not self.enabled:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with self._path(key).open("w", encoding="utf-8") as f:
                json.dump(value, f)
        except OSError:
            pass
