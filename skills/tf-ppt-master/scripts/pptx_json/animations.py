#!/usr/bin/env python3
"""Entrance-animation mapping shared by the SVG bridge and the native engine.

Both authoring routes converge on the viewer's ``PptxElementAnimation`` record
(``slide["animations"]``), which the MCP serialises to ``p:timing``:

    {"elementId": "title", "entrance": "fadeIn", "order": 0, "trigger": "onClick",
     "durationMs": 600, "delayMs": 200}

This module owns the one vocabulary: the skill's ``animations.json`` effect names,
the ``auto`` heuristic, and the group -> element expansion. The SVG bridge
(:mod:`pptx_json.svg_model`) derives groups from top-level ``<g id>`` anchors; the
native engine (:mod:`native_pages`) derives them from each element's ``id``.
"""

from __future__ import annotations

from typing import Any, Mapping

# ── Effect vocabulary ───────────────────────────────────────────────────────
# The skill's ``animations.json`` effect name (seconds for duration/delay) maps
# onto the canonical presets the MCP write service serialises to `p:timing`.
# Entrance only: the viewer model also carries exit/emphasis/path, but the skill
# sidecar's documented contract is per-group entrance reveals.
EFFECT_TO_PRESET: dict[str, str] = {
    "appear": "appear",
    "fade": "fadeIn",
    "fly": "flyIn",
    "zoom": "zoomIn",
    "wipe": "wipeIn",
    "split": "splitIn",
    "dissolve": "dissolveIn",
    "circle": "circleIn",
    "box": "boxIn",
    "diamond": "diamondIn",
    "wheel": "wheelIn",
    "float": "floatIn",
    "rise": "riseUp",
    "rise-up": "riseUp",
    "swivel": "swivel",
    "bounce": "bounceIn",
}

TRIGGER_MAP: dict[str, str] = {
    "on-click": "onClick",
    "with-previous": "withPrevious",
    "after-previous": "afterPrevious",
}

# `auto` effect pools, mirroring the skill's documented heuristic.
AUTO_IMAGE_POOL = ("zoom", "dissolve", "circle", "box", "diamond", "wheel")
AUTO_GENERIC_POOL = ("fade", "wipe", "fly", "zoom")

IMAGE_GROUP_TOKENS = ("hero", "figure", "image", "img", "kpi", "photo", "icon")

# Top-level groups that look like page chrome (background, header/footer,
# decorations, watermark, page number, nav, logo, dividing rule) skip the
# entrance cascade and appear together with the slide. Matched per token after
# splitting the id on `-` and `_` (see references/animations.md).
CHROME_TOKENS = frozenset(
    {
        "background",
        "bg",
        "decoration",
        "decorations",
        "decor",
        "header",
        "footer",
        "chrome",
        "watermark",
        "pagenumber",
        "pagenum",
        "nav",
        "logo",
        "rule",
    }
)


def is_chrome_anchor(anchor_id: str) -> bool:
    """Whether an animation anchor id names page chrome (never in the cascade)."""
    return any(token in CHROME_TOKENS for token in anchor_id.lower().replace("_", "-").split("-"))


def auto_effect_for_group(group_id: str, index: int) -> str:
    """Pick an entrance effect for a group id, mirroring the skill's ``auto`` rule."""
    low = group_id.lower()
    if "chart" in low or "data" in low:
        return "wipe"
    if low.startswith(("card", "step", "pillar")):
        return "fly"
    if any(token in low for token in ("title", "takeaway", "headline")):
        return "fade"
    if any(token in low for token in IMAGE_GROUP_TOKENS):
        return AUTO_IMAGE_POOL[index % len(AUTO_IMAGE_POOL)]
    return AUTO_GENERIC_POOL[index % len(AUTO_GENERIC_POOL)]


def with_default_effect(
    group_of_element: Mapping[str, str],
    default_effect: str | None,
    *,
    skip_chrome: bool = False,
) -> dict[str, dict[str, Any]] | None:
    """Synthesise a ``groups_config`` applying one effect to every group.

    ``None`` when ``default_effect`` is empty or ``none`` (nothing to apply).
    """
    if not default_effect or default_effect.strip().lower() in ("", "none"):
        return None
    seen: list[str] = []
    for group_id in group_of_element.values():
        if not group_id or group_id in seen:
            continue
        if skip_chrome and is_chrome_anchor(group_id):
            continue
        seen.append(group_id)
    return {
        group_id: {"effect": default_effect, "order": index + 1}
        for index, group_id in enumerate(seen)
    }


def build_slide_animations(
    group_of_element: Mapping[str, str],
    groups_config: Mapping[str, Any] | None,
    *,
    auto: bool = False,
    default_trigger: str | None = None,
    skip_chrome: bool = False,
) -> list[dict[str, Any]]:
    """Build a slide's ``animations`` array from a group-id -> element-id map.

    ``groups_config`` is the ``animations.json`` ``slides.<stem>.groups`` object
    (``{gid: {effect, order, duration, delay, trigger}}``; ``duration``/``delay``
    in seconds). With ``auto`` the config is synthesised from the discovered
    group ids. Every element inside a group receives the group's entrance so the
    flattened viewer model reproduces the group reveal as one click group.

    ``default_trigger`` is the fallback Start mode for a group that omits
    ``trigger`` (default ``on-click``). ``skip_chrome`` drops page-chrome groups
    from the ``auto`` cascade (explicitly configured groups are always honoured).
    """
    if auto:
        seen: list[str] = []
        for group_id in group_of_element.values():
            if not group_id or group_id in seen:
                continue
            if skip_chrome and is_chrome_anchor(group_id):
                continue
            seen.append(group_id)
        groups_config = {
            group_id: {"effect": auto_effect_for_group(group_id, index), "order": index + 1}
            for index, group_id in enumerate(seen)
        }
    if not groups_config:
        return []

    fallback_trigger = default_trigger or "on-click"

    def _order_key(item: tuple[str, Any]) -> float:
        spec = item[1]
        value = spec.get("order") if isinstance(spec, dict) else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

    ordered = sorted(groups_config.items(), key=_order_key)
    animations: list[dict[str, Any]] = []
    order_index = 0
    for group_id, raw_spec in ordered:
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        effect = str(spec.get("effect", "none")).strip().lower()
        if effect in ("", "none"):
            continue
        preset = EFFECT_TO_PRESET.get(effect)
        if preset is None:
            continue
        duration = spec.get("duration")
        delay = spec.get("delay")
        trigger = TRIGGER_MAP.get(str(spec.get("trigger", fallback_trigger)), "onClick")
        elements = [eid for eid, gid in group_of_element.items() if gid == group_id]
        if not elements:
            continue
        for element_id in elements:
            entry: dict[str, Any] = {
                "elementId": element_id,
                "entrance": preset,
                "order": order_index,
                "trigger": trigger,
            }
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                entry["durationMs"] = int(round(duration * 1000))
            if isinstance(delay, (int, float)) and not isinstance(delay, bool):
                entry["delayMs"] = int(round(delay * 1000))
            animations.append(entry)
        order_index += 1
    return animations


# ── Native-engine helpers ───────────────────────────────────────────────────


def animation_anchors(slide: Mapping[str, Any]) -> dict[str, str]:
    """Map a native page's element id -> animation anchor id.

    A top-level element's own ``id`` is its anchor; a ``group`` element stays one
    anchor (the group shape) so the whole group reveals as one click, mirroring
    an SVG top-level ``<g id>``. An element without an ``id`` cannot be
    referenced (the importer mints an opaque one) and is skipped, so an element
    that should animate must carry an explicit ``id``.
    """
    anchors: dict[str, str] = {}
    for element in slide.get("elements") or []:
        if not isinstance(element, dict):
            continue
        element_id = element.get("id")
        if isinstance(element_id, str) and element_id:
            anchors[element_id] = element_id
    return anchors


def resolve_animation_mode(mode: str | None) -> tuple[bool, str | None]:
    """Split an ``--animation`` mode into ``(auto, default_effect)``.

    ``none``/empty -> ``(False, None)``; ``auto`` -> ``(True, None)``; any other
    value is validated against :data:`EFFECT_TO_PRESET` and returned as the
    deck-wide default effect. Raises :class:`ValueError` for an unknown effect so
    a typo fails fast instead of silently emitting nothing.
    """
    value = (mode or "").strip().lower()
    if value in ("", "none"):
        return False, None
    if value == "auto":
        return True, None
    if value in EFFECT_TO_PRESET:
        return False, value
    known = ", ".join(sorted(EFFECT_TO_PRESET))
    raise ValueError(f"unknown animation effect {mode!r}; use none, auto, or one of: {known}")


def apply_slide_animations(
    slide: Mapping[str, Any],
    groups_config: Mapping[str, Any] | None,
    *,
    auto: bool = False,
    default_effect: str | None = None,
    default_trigger: str | None = None,
    skip_chrome: bool = True,
) -> int:
    """Attach ``slide["animations"]`` to a native page; return the effect count.

    Precedence mirrors the SVG bridge: an explicit per-page ``groups_config``
    wins; otherwise ``auto`` synthesises from the element ids; otherwise
    ``default_effect`` applies to every element. Writes nothing when all three
    are empty, so an unanimated deck carries no ``animations`` key.
    """
    anchors = animation_anchors(slide)
    if not anchors:
        return 0
    if groups_config is None and not auto:
        groups_config = with_default_effect(anchors, default_effect, skip_chrome=skip_chrome)
    animations = build_slide_animations(
        anchors,
        groups_config,
        auto=auto and not groups_config,
        default_trigger=default_trigger,
        skip_chrome=skip_chrome,
    )
    if isinstance(slide, dict):
        if animations:
            slide["animations"] = animations
        else:
            slide.pop("animations", None)
    return len(animations)
