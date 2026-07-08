"""
Tests for kubectl.py — subprocess argument construction for log streaming.
"""
import asyncio

import pytest

from kube_orb import kubectl as k


class _FakeProcess:
    """Minimal stand-in for asyncio.subprocess.Process with an empty stdout."""

    def __init__(self) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_eof()

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        pass


class TestStreamLogsSinceDefault:
    async def test_defaults_since_to_0s_when_unset(self, monkeypatch):
        captured = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            return _FakeProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        async for _ in k.stream_logs("mypod", "ns"):
            pass

        assert "--since" in captured["args"]
        idx = captured["args"].index("--since")
        assert captured["args"][idx + 1] == "0s"

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
