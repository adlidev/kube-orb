"""
Detection and readable-formatting for structured JSON log lines.

Most k8s services that emit structured logs use JSON — nearly unreadable as
a raw line. parse_json_log_line() detects a JSON object line and extracts
common level/message/timestamp fields (checking a few conventional key
names, since loggers disagree on naming), leaving everything else as
trailing key=value context. The caller decides whether to actually display
the formatted form or the raw line — detection always runs regardless, so
the "press Enter for full JSON" detail view works even in raw mode.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Checked in order; first key present wins. Covers the common structured
# logging libraries (zap, logrus, structlog, bunyan, stdlib json logging, ...).
_LEVEL_KEYS = ("level", "lvl", "severity", "loglevel", "log.level")
_MESSAGE_KEYS = ("message", "msg", "text")
_TIME_KEYS = ("timestamp", "time", "ts", "@timestamp", "asctime")

# Level name -> Rich style, for coloring the level token in the main stream.
LEVEL_STYLES = {
    "TRACE": "dim",
    "DEBUG": "dim cyan",
    "INFO": "cyan",
    "NOTICE": "cyan",
    "WARN": "bold yellow",
    "WARNING": "bold yellow",
    "ERROR": "bold red",
    "FATAL": "bold white on red",
    "CRITICAL": "bold white on red",
    "PANIC": "bold white on red",
}


@dataclass
class ParsedJsonLine:
    raw: dict                      # the full decoded object, for the detail modal
    level: str | None              # as found in the data, original casing
    message: str                   # falls back to a placeholder if no message-like key found
    timestamp: str | None          # already shortened to HH:MM:SS where parseable
    extras: dict = field(default_factory=dict)  # remaining top-level keys

    @property
    def extras_text(self) -> str:
        return " ".join(f"{k}={_format_value(v)}" for k, v in self.extras.items())

    @property
    def display_text(self) -> str:
        """Single-line readable rendering: `HH:MM:SS LEVEL  message  k=v k=v`."""
        parts = []
        if self.timestamp:
            parts.append(self.timestamp)
        if self.level:
            parts.append(f"{self.level.upper():<5}")
        parts.append(self.message)
        if self.extras:
            parts.append(self.extras_text)
        return "  ".join(parts)

    @property
    def pretty(self) -> str:
        """Full pretty-printed JSON, for the detail modal."""
        return json.dumps(self.raw, indent=2, sort_keys=False, default=str)


def parse_json_log_line(content: str) -> ParsedJsonLine | None:
    """
    Return a ParsedJsonLine if `content` is a single JSON object, else None.
    Cheap to call on every line: bails before attempting to parse anything
    that doesn't even look like an object.
    """
    stripped = content.strip()
    if len(stripped) < 2 or stripped[0] != "{" or stripped[-1] != "}":
        return None
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or not data:
        return None

    level_key = _first_key(data, _LEVEL_KEYS)
    message_key = _first_key(data, _MESSAGE_KEYS)
    time_key = _first_key(data, _TIME_KEYS)

    level = str(data[level_key]) if level_key else None
    message = str(data[message_key]) if message_key else "(no message field)"
    timestamp = _short_time(data[time_key]) if time_key else None

    used = {k for k in (level_key, message_key, time_key) if k is not None}
    extras = {k: v for k, v in data.items() if k not in used}

    return ParsedJsonLine(raw=data, level=level, message=message,
                          timestamp=timestamp, extras=extras)


def _first_key(data: dict, candidates: tuple[str, ...]) -> str | None:
    for key in candidates:
        if key in data and data[key] not in (None, ""):
            return key
    return None


def _short_time(value: object) -> str:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%H:%M:%S")
        except (ValueError, OSError, OverflowError):
            return str(value)
    s = str(value)
    iso = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M:%S")
    except ValueError:
        return s


def _format_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), default=str)
    return str(value)
