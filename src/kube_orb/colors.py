"""
Color assignment for pods using the golden angle method.

Distributes hues at 137.508° (the golden angle) intervals in HSL space,
which mathematically maximises perceptual distance between consecutive colors
regardless of how many pods are selected.

With 2 pods  → hues ~180° apart (near-complementary)
With 5 pods  → hues evenly spread ~137° apart
With 10 pods → still well-separated, no two adjacent colors look alike

Saturation and lightness are fixed for good readability on dark terminals.
"""
from __future__ import annotations

import colorsys

# Golden angle in degrees
GOLDEN_ANGLE = 137.508

# HSL fixed axes — tuned for dark terminal backgrounds
SATURATION = 0.75   # vivid but not neon
LIGHTNESS   = 0.65  # bright enough to read, not washed out

# Starting hue offset — avoids starting at pure red (0°) which can look like error color
_START_HUE = 30.0  # degrees


def _hsl_to_rgb(h_deg: float, s: float, l: float) -> tuple[int, int, int]:
    """Convert HSL (h in degrees, s and l in [0,1]) to RGB tuple (0–255)."""
    h = h_deg / 360.0
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def assign_colors(pod_names: list[str]) -> dict[str, str]:
    """
    Return a mapping of pod_name → hex color string.

    Colors are assigned in the order pods appear in the list.
    The same pod list always produces the same colors (deterministic).
    """
    result: dict[str, str] = {}
    for i, name in enumerate(pod_names):
        hue = (_START_HUE + i * GOLDEN_ANGLE) % 360.0
        rgb = _hsl_to_rgb(hue, SATURATION, LIGHTNESS)
        result[name] = _rgb_to_hex(*rgb)
    return result


def get_color(pod_name: str, color_map: dict[str, str]) -> str:
    """
    Look up a pod's color, returning a safe fallback if not found.
    The fallback is white, which is always readable on dark backgrounds.
    """
    return color_map.get(pod_name, "#ffffff")
