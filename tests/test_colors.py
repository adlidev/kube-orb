"""
Tests for colors.py — golden angle color assignment.
"""
import pytest
from kube_illume.colors import assign_colors, get_color


class TestAssignColors:
    def test_returns_dict_keyed_by_pod_name(self):
        pods = ["api-gateway-abc", "auth-service-xyz"]
        result = assign_colors(pods)
        assert set(result.keys()) == set(pods)

    def test_hex_format(self):
        result = assign_colors(["pod-a"])
        color = result["pod-a"]
        assert color.startswith("#")
        assert len(color) == 7
        assert all(c in "0123456789abcdef" for c in color[1:])

    def test_deterministic(self):
        pods = ["a", "b", "c", "d", "e"]
        assert assign_colors(pods) == assign_colors(pods)

    def test_empty_list(self):
        assert assign_colors([]) == {}

    def test_single_pod(self):
        result = assign_colors(["only-pod"])
        assert len(result) == 1

    def test_colors_are_distinct(self):
        """With 5+ pods, no two should have the same color."""
        pods = [f"pod-{i}" for i in range(10)]
        colors = list(assign_colors(pods).values())
        assert len(set(colors)) == len(colors), "Duplicate colors detected"

    def test_two_pods_not_identical(self):
        pods = ["pod-1", "pod-2"]
        colors = assign_colors(pods)
        assert colors["pod-1"] != colors["pod-2"]


class TestGetColor:
    def test_returns_mapped_color(self):
        color_map = {"my-pod": "#aabbcc"}
        assert get_color("my-pod", color_map) == "#aabbcc"

    def test_fallback_for_unknown_pod(self):
        result = get_color("unknown-pod", {})
        assert result == "#ffffff"
