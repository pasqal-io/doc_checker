"""Tests for the LLM response cache."""

from __future__ import annotations

from pathlib import Path

from doc_checker.cache import ResponseCache, default_cache_dir


def test_roundtrip(tmp_path: Path):
    cache = ResponseCache(tmp_path / "cache")
    key = ResponseCache.make_key("model", "prompt")
    assert cache.get(key) is None
    cache.set(key, {"issues": [{"severity": "critical"}]})
    assert cache.get(key) == {"issues": [{"severity": "critical"}]}


def test_disabled_is_noop(tmp_path: Path):
    cache = ResponseCache(tmp_path / "cache", enabled=False)
    key = ResponseCache.make_key("model", "prompt")
    cache.set(key, {"issues": []})
    assert cache.get(key) is None
    assert not (tmp_path / "cache").exists()


def test_key_varies_by_model_and_prompt():
    a = ResponseCache.make_key("m1", "p")
    b = ResponseCache.make_key("m2", "p")
    c = ResponseCache.make_key("m1", "p2")
    assert len({a, b, c}) == 3


def test_get_tolerates_corrupt_entry(tmp_path: Path):
    cache = ResponseCache(tmp_path / "cache")
    key = ResponseCache.make_key("model", "prompt")
    cache.set(key, {"issues": []})
    (tmp_path / "cache" / f"{key}.json").write_text("not json{")
    assert cache.get(key) is None


def test_default_cache_dir_honors_xdg(monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/xdg-cache-test")
    assert default_cache_dir() == Path("/tmp/xdg-cache-test/doc_checker")
