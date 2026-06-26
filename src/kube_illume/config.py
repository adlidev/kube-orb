"""
Config management for kube-illume.

Storage layout under ~/.config/kube-illume/:
  strings.yaml               — global saved string lists (filters/highlights/monitors)
  namespaces/<ns>.yaml       — per-namespace saved session configs
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import HealthConfig, LogMode, SavedStrings, SessionConfig

CONFIG_DIR = Path.home() / ".config" / "kube-illume"
STRINGS_FILE = CONFIG_DIR / "strings.yaml"
NAMESPACES_DIR = CONFIG_DIR / "namespaces"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    NAMESPACES_DIR.mkdir(parents=True, exist_ok=True)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _save_yaml(path: Path, data: dict) -> None:
    _ensure_dirs()
    with path.open("w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ─── String parsing ───────────────────────────────────────────────────────────

def parse_string_input(raw: str) -> list[str]:
    """
    Parse a comma-separated input string into individual match patterns.
    Quoted tokens (for strings containing commas) are handled.
    Each token is stripped of whitespace.

    Examples:
        'ERROR, timeout'         → ['ERROR', 'timeout']
        '/5[0-9]{2}/, WARN'     → ['/5[0-9]{2}/', 'WARN']
        '"GET /api, POST /api"'  → ['GET /api, POST /api']
    """
    tokens: list[str] = []
    current = ""
    in_quote = False

    for char in raw:
        if char == '"':
            in_quote = not in_quote
        elif char == "," and not in_quote:
            token = current.strip()
            if token:
                tokens.append(token)
            current = ""
        else:
            current += char

    token = current.strip()
    if token:
        tokens.append(token)

    return tokens


def is_regex_pattern(s: str) -> bool:
    """Return True if the string uses /pattern/ regex syntax."""
    return s.startswith("/") and s.endswith("/") and len(s) > 2


def compile_pattern(s: str) -> re.Pattern:
    """
    Compile a match string into a regex Pattern.
    /pattern/ strings are compiled as regex.
    Plain strings are compiled as literal (re.escape).
    """
    if is_regex_pattern(s):
        return re.compile(s[1:-1])
    return re.compile(re.escape(s))


def matches(line: str, patterns: list[re.Pattern]) -> bool:
    """Return True if line matches any of the compiled patterns."""
    return any(p.search(line) for p in patterns)


def compile_patterns(strings: list[str]) -> list[re.Pattern]:
    return [compile_pattern(s) for s in strings]


# ─── Saved strings ────────────────────────────────────────────────────────────

def load_saved_strings() -> SavedStrings:
    data = _load_yaml(STRINGS_FILE)
    return SavedStrings(
        filters=data.get("filters", []),
        highlights=data.get("highlights", []),
        monitors=data.get("monitors", []),
    )


def save_saved_strings(strings: SavedStrings) -> None:
    _save_yaml(STRINGS_FILE, {
        "filters": strings.filters,
        "highlights": strings.highlights,
        "monitors": strings.monitors,
    })


def add_to_saved_strings(
    category: str,
    new_strings: list[str],
) -> None:
    """
    Append new_strings to the given category ('filters'|'highlights'|'monitors')
    in the global strings file, deduplicating.
    """
    saved = load_saved_strings()
    existing = getattr(saved, category)
    merged = existing + [s for s in new_strings if s not in existing]
    setattr(saved, category, merged)
    save_saved_strings(saved)


# ─── Session configs ──────────────────────────────────────────────────────────

def _ns_config_path(namespace: str, name: str) -> Path:
    safe_name = re.sub(r"[^\w\-]", "_", name)
    return NAMESPACES_DIR / namespace / f"{safe_name}.yaml"


def list_saved_configs(namespace: str) -> list[str]:
    """Return names of saved configs for a namespace."""
    ns_dir = NAMESPACES_DIR / namespace
    if not ns_dir.exists():
        return []
    return [p.stem for p in sorted(ns_dir.glob("*.yaml"))]


def load_session_config(namespace: str, name: str) -> SessionConfig | None:
    path = _ns_config_path(namespace, name)
    data = _load_yaml(path)
    if not data:
        return None

    health_data = data.get("health", {})
    return SessionConfig(
        namespace=namespace,
        deployments=data.get("deployments", []),
        mode=LogMode(data.get("mode", "stream")),
        tail=data.get("tail"),
        since=data.get("since"),
        filters=data.get("filters", []),
        highlights=data.get("highlights", []),
        monitors=data.get("monitors", []),
        health=HealthConfig(
            enabled=health_data.get("enabled", False),
            interval_minutes=health_data.get("interval_minutes", 5),
            restart_threshold=health_data.get("restart_threshold", 1),
        ),
        name=name,
    )


def save_session_config(config: SessionConfig) -> None:
    """Save a session config under its namespace. config.name must be set."""
    if not config.name:
        raise ValueError("SessionConfig.name must be set before saving")

    ns_dir = NAMESPACES_DIR / config.namespace
    ns_dir.mkdir(parents=True, exist_ok=True)

    path = _ns_config_path(config.namespace, config.name)
    _save_yaml(path, {
        "deployments": config.deployments,
        "mode": config.mode.value,
        "tail": config.tail,
        "since": config.since,
        "filters": config.filters,
        "highlights": config.highlights,
        "monitors": config.monitors,
        "health": {
            "enabled": config.health.enabled,
            "interval_minutes": config.health.interval_minutes,
            "restart_threshold": config.health.restart_threshold,
        },
    })
