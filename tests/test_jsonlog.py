"""
Tests for jsonlog.py — JSON log-line detection, field extraction, formatting.
"""
from kube_orb.jsonlog import parse_json_log_line


class TestParseJsonLogLine:
    def test_detects_and_extracts_standard_fields(self):
        line = '{"timestamp": "2026-07-08T12:34:56+00:00", "level": "INFO", "msg": "hello", "status": 200}'
        parsed = parse_json_log_line(line)
        assert parsed is not None
        assert parsed.level == "INFO"
        assert parsed.message == "hello"
        assert parsed.timestamp == "12:34:56"
        assert parsed.extras == {"status": 200}

    def test_alternate_key_names(self):
        line = '{"severity": "warn", "message": "disk almost full", "ts": 1751980800}'
        parsed = parse_json_log_line(line)
        assert parsed is not None
        assert parsed.level == "warn"
        assert parsed.message == "disk almost full"
        assert parsed.timestamp == "13:20:00"

    def test_z_suffixed_timestamp(self):
        line = '{"time": "2026-07-08T12:00:00Z", "level": "DEBUG", "msg": "tick"}'
        parsed = parse_json_log_line(line)
        assert parsed.timestamp == "12:00:00"

    def test_missing_message_falls_back_to_placeholder(self):
        line = '{"level": "INFO", "count": 3}'
        parsed = parse_json_log_line(line)
        assert parsed.message == "(no message field)"
        assert parsed.extras == {"count": 3}

    def test_non_json_returns_none(self):
        assert parse_json_log_line("plain text line") is None
        assert parse_json_log_line("[2026-01-01] [INFO] worker: did a thing") is None
        assert parse_json_log_line("") is None

    def test_json_array_returns_none(self):
        assert parse_json_log_line('["not", "an", "object"]') is None

    def test_malformed_json_returns_none(self):
        assert parse_json_log_line('{"level": "INFO", "msg": }') is None

    def test_empty_object_returns_none(self):
        assert parse_json_log_line("{}") is None

    def test_extra_whitespace_tolerated(self):
        parsed = parse_json_log_line('   {"level": "INFO", "msg": "hi"}   \n')
        assert parsed is not None
        assert parsed.message == "hi"

    def test_display_text_format(self):
        line = '{"timestamp": "2026-07-08T12:34:56+00:00", "level": "error", "msg": "boom", "code": 500}'
        parsed = parse_json_log_line(line)
        assert parsed.display_text == "12:34:56  ERROR  boom  code=500"

    def test_pretty_is_valid_reparseable_json(self):
        import json
        line = '{"level": "INFO", "msg": "hi", "nested": {"a": 1}}'
        parsed = parse_json_log_line(line)
        assert json.loads(parsed.pretty) == {"level": "INFO", "msg": "hi", "nested": {"a": 1}}

    def test_nested_extras_rendered_compactly(self):
        line = '{"level": "INFO", "msg": "hi", "meta": {"a": 1, "b": [1, 2]}}'
        parsed = parse_json_log_line(line)
        assert parsed.extras_text == 'meta={"a":1,"b":[1,2]}'
