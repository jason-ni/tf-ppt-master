"""Parse a ``pptx-viewer`` ``export_to_json`` result for intake and analysis.

Consumers in the read/intake path (Phase A) replace the legacy
``pptx_intake`` / ``pptx_to_svg`` output with a normalized view over the
exported document, without touching ``python-pptx``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .document import load, loads

__all__ = [
    "load_export",
    "presentation_of",
    "deck_size",
    "theme_of",
    "theme_colors",
    "theme_fonts",
    "slide_count",
    "element_type_counts",
    "slide_elements",
    "find_element",
    "deck_summary",
]


def load_export(source: str | Path) -> dict[str, Any]:
    """Load an export document from a path or from raw JSON text."""
    if isinstance(source, Path):
        return load(source)
    text = str(source)
    if "\n" not in text and "{" not in text:
        path = Path(text)
        if path.exists():
            return load(path)
    return loads(text)


def presentation_of(document: dict[str, Any]) -> dict[str, Any]:
    return document.get("presentation") or {}


def deck_size(document: dict[str, Any]) -> tuple[float, float]:
    presentation = presentation_of(document)
    return float(presentation.get("width", 0)), float(presentation.get("height", 0))


def theme_of(document: dict[str, Any]) -> dict[str, Any]:
    return presentation_of(document).get("theme") or {}


def theme_colors(document: dict[str, Any]) -> dict[str, str]:
    return theme_of(document).get("colorScheme") or {}


def theme_fonts(document: dict[str, Any]) -> dict[str, Any]:
    return theme_of(document).get("fontScheme") or {}


def slide_count(document: dict[str, Any]) -> int:
    return len(document.get("slides") or [])


def element_type_counts(slide: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element in slide.get("elements") or []:
        element_type = str(element.get("type", "unknown"))
        counts[element_type] = counts.get(element_type, 0) + 1
    return counts


def slide_elements(document: dict[str, Any], index: int) -> list[dict[str, Any]]:
    slides = document.get("slides") or []
    if not 0 <= index < len(slides):
        raise IndexError(f"slide index {index} out of range 0..{len(slides) - 1}")
    return list(slides[index].get("elements") or [])


def find_element(
    document: dict[str, Any], index: int, element_id: str
) -> dict[str, Any] | None:
    for element in slide_elements(document, index):
        if element.get("id") == element_id:
            return element
    return None


def deck_summary(document: dict[str, Any]) -> dict[str, Any]:
    """A compact, layout-oriented summary suitable for ``analysis/`` output."""
    width, height = deck_size(document)
    colors = theme_colors(document)
    slides = document.get("slides") or []
    outline = []
    for index, slide in enumerate(slides):
        outline.append(
            {
                "index": index,
                "id": slide.get("id"),
                "layoutPath": slide.get("layoutPath"),
                "name": slide.get("name"),
                "hidden": bool(slide.get("hidden", False)),
                "hasNotes": bool(slide.get("notes")),
                "elementCounts": element_type_counts(slide),
            }
        )
    return {
        "slideCount": len(slides),
        "width": width,
        "height": height,
        "themeColors": colors,
        "themeFonts": theme_fonts(document),
        "slides": outline,
    }


def dumps_summary(document: dict[str, Any]) -> str:
    return json.dumps(deck_summary(document), ensure_ascii=False, indent=2)
