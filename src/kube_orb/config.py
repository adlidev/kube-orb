"""
Config management for kube-orb.

Storage layout under ~/.config/kube-orb/:
  strings.yaml               — global saved string lists (filters/highlights/monitors)
  namespaces/<ns>.yaml       — per-namespace saved session configs
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import HealthConfig, LogMode, SavedStrings, SessionConfig

CONFIG_DIR = Path.home() / ".config" / "kube-orb"
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


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            normalized.append(item)
        elif isinstance(item, list):
            # A hand-edited strings.yaml with an unquoted bracketed literal
            # like "[debug]" parses as YAML flow-sequence syntax (a nested
            # list) instead of the string the user meant. Reconstruct the
            # original bracketed text rather than losing the pattern or
            # emitting Python's list repr (e.g. "['debug']").
            normalized.append(f"[{', '.join(str(x) for x in item)}]")
        elif item is not None:
            normalized.append(str(item))
    return normalized


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


def compile_pattern(s: str, ignore_case: bool = False) -> re.Pattern:
    """
    Compile a match string into a regex Pattern.
    /pattern/ strings are compiled as regex.
    Plain strings are compiled as literal (re.escape).
    """
    flags = re.IGNORECASE if ignore_case else 0
    if is_regex_pattern(s):
        return re.compile(s[1:-1], flags)
    return re.compile(re.escape(s), flags)


def matches(line: str, patterns: list[re.Pattern]) -> bool:
    """Return True if line matches any of the compiled patterns."""
    return any(p.search(line) for p in patterns)


def compile_patterns(strings: list[str], ignore_case: bool = False) -> list[re.Pattern]:
    return [compile_pattern(s, ignore_case) for s in strings]


# ─── Saved strings ────────────────────────────────────────────────────────────

def load_saved_strings() -> SavedStrings:
    data = _load_yaml(STRINGS_FILE)
    return SavedStrings(
        filters=_normalize_string_list(data.get("filters", [])),
        highlights=_normalize_string_list(data.get("highlights", [])),
        monitors=_normalize_string_list(data.get("monitors", [])),
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


def list_all_saved_configs() -> list[tuple[str, str]]:
    """Return (namespace, name) for every saved config across all namespaces."""
    if not NAMESPACES_DIR.exists():
        return []
    result = []
    for ns_dir in sorted(NAMESPACES_DIR.iterdir()):
        if ns_dir.is_dir():
            for p in sorted(ns_dir.glob("*.yaml")):
                result.append((ns_dir.name, p.stem))
    return result


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
        filters=_normalize_string_list(data.get("filters", [])),
        highlights=_normalize_string_list(data.get("highlights", [])),
        monitors=_normalize_string_list(data.get("monitors", [])),
        filters_ignore_case=data.get("filters_ignore_case", False),
        highlights_ignore_case=data.get("highlights_ignore_case", False),
        monitors_ignore_case=data.get("monitors_ignore_case", False),
        line_wrap=data.get("line_wrap", True),
        color_full_line=data.get("color_full_line", False),
        json_format=data.get("json_format", False),
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
        "filters_ignore_case": config.filters_ignore_case,
        "highlights_ignore_case": config.highlights_ignore_case,
        "monitors_ignore_case": config.monitors_ignore_case,
        "line_wrap": config.line_wrap,
        "color_full_line": config.color_full_line,
        "json_format": config.json_format,
        "health": {
            "enabled": config.health.enabled,
            "interval_minutes": config.health.interval_minutes,
            "restart_threshold": config.health.restart_threshold,
        },
    })
