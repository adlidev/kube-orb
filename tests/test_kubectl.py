"""
Tests for kubectl.py — subprocess argument construction for log streaming.
"""
import asyncio
from datetime import datetime, timezone

import pytest

from kube_orb import kubectl as k
from kube_orb.kubectl import _normalize_since, _split_timestamp, wants_backfill


class _FakeProcess:
    """Minimal stand-in for asyncio.subprocess.Process with an empty stdout."""

    def __init__(self) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_eof()

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        pass


class _FeedProcess:
    """Stand-in whose stdout yields pre-supplied lines, then EOF."""

    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = asyncio.StreamReader()
        for line in lines:
            self.stdout.feed_data(line)
        self.stdout.feed_eof()

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        pass


class TestSplitTimestamp:
    def test_parses_z_suffixed_nanosecond_timestamp(self):
        ts, content = _split_timestamp("2026-07-08T12:34:56.789012345Z hello world")
        assert content == "hello world"
        assert ts == datetime(2026, 7, 8, 12, 34, 56, 789012, tzinfo=timezone.utc)

    def test_parses_offset_timestamp(self):
        ts, content = _split_timestamp("2026-07-08T12:34:56+02:00 hello")
        assert content == "hello"
        assert ts.utcoffset().total_seconds() == 2 * 3600

    def test_no_fractional_seconds(self):
        ts, content = _split_timestamp("2026-07-08T12:34:56Z hello")
        assert content == "hello"
        assert ts == datetime(2026, 7, 8, 12, 34, 56, tzinfo=timezone.utc)

    def test_non_timestamped_line_returned_unchanged(self):
        ts, content = _split_timestamp("just a plain log line")
        assert ts is None
        assert content == "just a plain log line"

    def test_blank_content_after_timestamp_preserved(self):
        ts, content = _split_timestamp("2026-07-08T12:34:56Z ")
        assert ts is not None
        assert content == ""


class TestStreamLogsSinceDefault:
    async def test_defaults_since_to_1s_when_unset(self, monkeypatch):
        # kubectl treats an all-zero --since exactly like omitting the flag
        # entirely ("no limit" -> full buffered history), so the "only new
        # lines" default must be a small positive duration, not "0s".
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            return _FakeProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        async for _ in k.stream_logs("mypod", "ns"):
            pass

        assert "--since" in captured["args"]
        idx = captured["args"].index("--since")
        assert captured["args"][idx + 1] == "1s"

    async def test_normalizes_a_literal_zero_since_to_1s(self, monkeypatch):
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            return _FakeProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        async for _ in k.stream_logs("mypod", "ns", since="0"):
            pass

        idx = captured["args"].index("--since")
        assert captured["args"][idx + 1] == "1s"

    async def test_preserves_explicit_since(self, monkeypatch):
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            return _FakeProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        async for _ in k.stream_logs("mypod", "ns", since="1h"):
            pass

        idx = captured["args"].index("--since")
        assert captured["args"][idx + 1] == "1h"

    async def test_requests_timestamps_for_backfill_ordering(self, monkeypatch):
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            return _FakeProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        async for _ in k.stream_logs("mypod", "ns"):
            pass

        assert "--timestamps=true" in captured["args"]

    async def test_yields_lines_with_parsed_log_timestamp_and_clean_content(self, monkeypatch):
        async def fake_create_subprocess_exec(*args, **kwargs):
            return _FeedProcess([
                b"2026-07-08T12:34:56.000000000Z first line\n",
                b"2026-07-08T12:34:57.500000000Z second line\n",
            ])

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        lines = [line async for line in k.stream_logs("mypod", "ns")]

        assert [l.content for l in lines] == ["first line", "second line"]
        assert lines[0].log_timestamp == datetime(2026, 7, 8, 12, 34, 56, tzinfo=timezone.utc)
        assert lines[1].log_timestamp == datetime(2026, 7, 8, 12, 34, 57, 500000, tzinfo=timezone.utc)


class TestNormalizeSince:
    @pytest.mark.parametrize("since", [None, "", "0", "0s", "0h", "0m", "00", "0.0s"])
    def test_zero_and_empty_values_become_1s(self, since):
        assert _normalize_since(since) == "1s"

    @pytest.mark.parametrize("since", ["1s", "1h", "30m", "10s", "2h30m"])
    def test_real_durations_pass_through_unchanged(self, since):
        assert _normalize_since(since) == since


class TestWantsBackfill:
    @pytest.mark.parametrize("since", [None, "", "0", "0s", "0h", "00"])
    def test_zero_and_empty_values_do_not_want_backfill(self, since):
        assert wants_backfill(since) is False

    @pytest.mark.parametrize("since", ["1s", "1h", "30m", "10s"])
    def test_real_durations_want_backfill(self, since):
        assert wants_backfill(since) is True


class TestStreamLogsDumpMode:
    async def test_dump_logs_has_no_since_default(self, monkeypatch):
        """Unlike stream_logs, dump_logs should omit --since entirely when unset
        (a one-shot fetch should return full history, not just new lines)."""
        captured = {}

        class _FakeDumpProcess(_FakeProcess):
            async def communicate(self):
                return b"", b""

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            return _FakeDumpProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        await k.dump_logs("mypod", "ns")

        assert "--since" not in captured["args"]
