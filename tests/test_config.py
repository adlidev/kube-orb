"""
Tests for config.py — string parsing, pattern matching, save/load.
"""
import re
import pytest

from kube_illume.config import (
    compile_pattern,
    compile_patterns,
    is_regex_pattern,
    matches,
    parse_string_input,
)


# ─── parse_string_input ───────────────────────────────────────────────────────

class TestParseStringInput:
    def test_single_string(self):
        assert parse_string_input("ERROR") == ["ERROR"]

    def test_comma_separated(self):
        assert parse_string_input("ERROR, timeout, WARN") == ["ERROR", "timeout", "WARN"]

    def test_trims_whitespace(self):
        assert parse_string_input("  ERROR ,  WARN  ") == ["ERROR", "WARN"]

    def test_regex_pattern_preserved(self):
        result = parse_string_input("/5[0-9]{2}/, ERROR")
        assert result == ["/5[0-9]{2}/", "ERROR"]

    def test_quoted_string_with_comma(self):
        result = parse_string_input('"GET /api, POST /api"')
        assert result == ["GET /api, POST /api"]

    def test_empty_string(self):
        assert parse_string_input("") == []

    def test_empty_tokens_skipped(self):
        assert parse_string_input("ERROR,,WARN") == ["ERROR", "WARN"]


# ─── is_regex_pattern ─────────────────────────────────────────────────────────

class TestIsRegexPattern:
    def test_detects_regex(self):
        assert is_regex_pattern("/5[0-9]{2}/") is True

    def test_plain_string(self):
        assert is_regex_pattern("ERROR") is False

    def test_only_slashes(self):
        assert is_regex_pattern("//") is False  # length <= 2 after stripping

    def test_unterminated(self):
        assert is_regex_pattern("/ERROR") is False


# ─── compile_pattern and matches ──────────────────────────────────────────────

class TestPatternMatching:
    def test_plain_substring_match(self):
        p = compile_pattern("ERROR")
        assert p.search("this is an ERROR line") is not None

    def test_plain_no_match(self):
        p = compile_pattern("ERROR")
        assert p.search("this is fine") is None

    def test_regex_match(self):
        p = compile_pattern("/5[0-9]{2}/")
        assert p.search("status 503 upstream") is not None
        assert p.search("status 200 ok") is None

    def test_plain_string_special_chars_escaped(self):
        # Dots in plain strings should be literal, not regex wildcards
        p = compile_pattern("10.0.0.1")
        assert p.search("client 10.0.0.1 connected") is not None
        assert p.search("10X0X0X1") is None

    def test_matches_any_pattern(self):
        patterns = compile_patterns(["ERROR", "/timeout|5[0-9]{2}/"])
        assert matches("upstream 503 error", patterns) is True
        assert matches("connection timeout", patterns) is True
        assert matches("request completed 200", patterns) is False

    def test_matches_empty_patterns(self):
        assert matches("anything", []) is False


# ─── save/load round-trip ─────────────────────────────────────────────────────

class TestConfigPersistence:
    def test_saved_strings_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("kube_illume.config.CONFIG_DIR", tmp_path / ".config" / "kube-illume")
        monkeypatch.setattr("kube_illume.config.STRINGS_FILE",
                            tmp_path / ".config" / "kube-illume" / "strings.yaml")
        monkeypatch.setattr("kube_illume.config.NAMESPACES_DIR",
                            tmp_path / ".config" / "kube-illume" / "namespaces")

        from kube_illume.config import load_saved_strings, save_saved_strings
        from kube_illume.models import SavedStrings

        original = SavedStrings(
            filters=["DEBUG", "/health.*/"],
            highlights=["ERROR", "WARN"],
            monitors=["brute force"],
        )
        save_saved_strings(original)
        loaded = load_saved_strings()

        assert loaded.filters == original.filters
        assert loaded.highlights == original.highlights
        assert loaded.monitors == original.monitors

    def test_session_config_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("kube_illume.config.CONFIG_DIR", tmp_path / ".config" / "kube-illume")
        monkeypatch.setattr("kube_illume.config.STRINGS_FILE",
                            tmp_path / ".config" / "kube-illume" / "strings.yaml")
        monkeypatch.setattr("kube_illume.config.NAMESPACES_DIR",
                            tmp_path / ".config" / "kube-illume" / "namespaces")

        from kube_illume.config import load_session_config, save_session_config
        from kube_illume.models import HealthConfig, LogMode, SessionConfig

        cfg = SessionConfig(
            namespace="production",
            deployments=["api-gateway", "auth-service"],
            mode=LogMode.STREAM,
            filters=["DEBUG"],
            highlights=["ERROR"],
            monitors=["brute force"],
            health=HealthConfig(enabled=True, interval_minutes=2),
            name="my-config",
        )
        save_session_config(cfg)
        loaded = load_session_config("production", "my-config")

        assert loaded is not None
        assert loaded.deployments == cfg.deployments
        assert loaded.mode == LogMode.STREAM
        assert loaded.filters == ["DEBUG"]
        assert loaded.health.enabled is True
        assert loaded.health.interval_minutes == 2
