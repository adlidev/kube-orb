"""
Tests for config.py — string parsing, pattern matching, save/load.
"""
from kube_orb.config import (
    add_to_saved_strings,
    compile_pattern,
    compile_patterns,
    is_regex_pattern,
    list_all_saved_configs,
    list_saved_configs,
    load_saved_strings,
    load_session_config,
    matches,
    parse_string_input,
    save_saved_strings,
    save_session_config,
)
from kube_orb.models import HealthConfig, LogMode, SavedStrings, SessionConfig


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
        monkeypatch.setattr("kube_orb.config.CONFIG_DIR", tmp_path / ".config" / "kube-orb")
        monkeypatch.setattr("kube_orb.config.STRINGS_FILE", tmp_path / ".config" / "kube-orb" / "strings.yaml")
        monkeypatch.setattr("kube_orb.config.NAMESPACES_DIR", tmp_path / ".config" / "kube-orb" / "namespaces")

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
        monkeypatch.setattr("kube_orb.config.CONFIG_DIR", tmp_path / ".config" / "kube-orb")
        monkeypatch.setattr("kube_orb.config.STRINGS_FILE", tmp_path / ".config" / "kube-orb" / "strings.yaml")
        monkeypatch.setattr("kube_orb.config.NAMESPACES_DIR", tmp_path / ".config" / "kube-orb" / "namespaces")

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

    def test_add_to_saved_strings_deduplicates_and_appends(self, tmp_path, monkeypatch):
        monkeypatch.setattr("kube_orb.config.CONFIG_DIR", tmp_path / ".config" / "kube-orb")
        monkeypatch.setattr("kube_orb.config.STRINGS_FILE", tmp_path / ".config" / "kube-orb" / "strings.yaml")
        monkeypatch.setattr("kube_orb.config.NAMESPACES_DIR", tmp_path / ".config" / "kube-orb" / "namespaces")

        save_saved_strings(SavedStrings(filters=["ERROR"]))
        add_to_saved_strings("filters", ["ERROR", "WARN"])

        saved = load_saved_strings()
        assert saved.filters == ["ERROR", "WARN"]

    def test_load_saved_strings_handles_legacy_unquoted_bracketed_patterns(self, tmp_path, monkeypatch):
        monkeypatch.setattr("kube_orb.config.CONFIG_DIR", tmp_path / ".config" / "kube-orb")
        monkeypatch.setattr("kube_orb.config.STRINGS_FILE", tmp_path / ".config" / "kube-orb" / "strings.yaml")
        monkeypatch.setattr("kube_orb.config.NAMESPACES_DIR", tmp_path / ".config" / "kube-orb" / "namespaces")

        path = tmp_path / ".config" / "kube-orb" / "strings.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("filters:\n- [debug]\nhighlights: []\nmonitors: []\n")

        saved = load_saved_strings()
        assert saved.filters == ["[debug]"]

    def test_list_saved_configs_reports_all_namespaces(self, tmp_path, monkeypatch):
        monkeypatch.setattr("kube_orb.config.CONFIG_DIR", tmp_path / ".config" / "kube-orb")
        monkeypatch.setattr("kube_orb.config.STRINGS_FILE", tmp_path / ".config" / "kube-orb" / "strings.yaml")
        monkeypatch.setattr("kube_orb.config.NAMESPACES_DIR", tmp_path / ".config" / "kube-orb" / "namespaces")

        save_session_config(SessionConfig(namespace="production", deployments=["api-gateway"], mode=LogMode.STREAM, name="alpha"))
        save_session_config(SessionConfig(namespace="production", deployments=["auth-service"], mode=LogMode.DUMP, name="beta"))
        save_session_config(SessionConfig(namespace="staging", deployments=["worker"], mode=LogMode.STREAM, name="gamma"))

        assert list_saved_configs("production") == ["alpha", "beta"]
        assert list_all_saved_configs() == [("production", "alpha"), ("production", "beta"), ("staging", "gamma")]
