"""
Core domain models for kube-orb.
All data passed between layers is typed via these dataclasses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class LogMode(str, Enum):
    STREAM = "stream"
    DUMP = "dump"


# ─── Kubernetes objects ───────────────────────────────────────────────────────

@dataclass
class Deployment:
    name: str
    namespace: str
    pod_count: int
    selector: dict[str, str]  # label selector used to find pods


@dataclass
class Pod:
    name: str
    namespace: str
    deployment: str          # owning deployment name
    phase: str               # Running, Pending, Failed, etc.
    restart_count: int
    ready: bool


@dataclass
class PodStatus:
    """Snapshot of a pod's health at a point in time."""
    name: str
    deployment: str
    phase: str
    restart_count: int
    ready: bool
    age_seconds: float

    @property
    def is_healthy(self) -> bool:
        return self.phase == "Running" and self.ready


# ─── Log lines ────────────────────────────────────────────────────────────────

@dataclass
class LogLine:
    pod_name: str
    content: str             # raw log text
    received_at: datetime = field(default_factory=datetime.now)
    # The real per-line timestamp Kubernetes attaches (from kubectl
    # --timestamps=true), parsed and stripped back out of `content`. None
    # when unavailable (dump mode doesn't request it) or unparseable.
    # received_at is "when kube-orb read this"; log_timestamp is "when the
    # container actually emitted it" — used to interleave a backfill burst
    # (see ViewerApp._handle_backfill_line) since arrival order across
    # concurrent per-pod streams doesn't reflect true chronological order.
    log_timestamp: datetime | None = None

    @property
    def display(self) -> str:
        return f"[{self.pod_name}] {self.content}"


# ─── String matching ─────────────────────────────────────────────────────────

@dataclass
class SavedStrings:
    """
    Global saved string lists, persisted to ~/.config/kube-orb/strings.yaml.
    Strings prefixed and suffixed with '/' are treated as regex patterns.
    """
    filters: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    monitors: list[str] = field(default_factory=list)


# ─── Session config ───────────────────────────────────────────────────────────

@dataclass
class HealthConfig:
    enabled: bool = False
    interval_minutes: int = 5
    restart_threshold: int = 1   # CLI-only tuning knob, default 1


@dataclass
class SessionConfig:
    """
    Complete configuration for one viewer session.
    Produced by the wizard or assembled from CLI flags.
    Persisted per-namespace to ~/.config/kube-orb/namespaces/<ns>.yaml.
    """
    namespace: str
    deployments: list[str]       # selected deployment names
    mode: LogMode = LogMode.STREAM

    tail: int | None = None      # last N lines (dump mode only)
    # kubectl --since value, e.g. "1h", "30m". Used by both modes: bounds how
    # far back dump mode fetches (None = full history). In stream mode, a
    # None/zero value is normalized to "1s" (see kubectl._normalize_since)
    # so a live session only collects new lines instead of replaying
    # history -- kubectl treats an all-zero --since as "no limit", not
    # "since now".
    since: str | None = None

    # Active string sets for this session
    filters: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    monitors: list[str] = field(default_factory=list)   # stream only

    # Case sensitivity (False = case-sensitive, True = ignore case)
    filters_ignore_case: bool = False
    highlights_ignore_case: bool = False
    monitors_ignore_case: bool = False

    health: HealthConfig = field(default_factory=HealthConfig)

    # Display options
    color_full_line: bool = False  # True = color entire line; False = color pod name prefix only
    line_wrap: bool = True
    json_format: bool = False  # True = reformat detected JSON lines (level/message/time); False = raw
    collapse_repeats: bool = False  # True = collapse consecutive identical lines (journalctl-style)

    # Config name — set when user chooses to save
    name: str | None = None
