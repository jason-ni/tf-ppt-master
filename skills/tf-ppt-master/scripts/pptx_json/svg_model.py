"""SVG -> ``pptx-viewer-json`` model mapper (C1-Hybrid, v1).

Converts an authored SVG page into a ``pptx-viewer-json`` slide using typed
model fields so every element renders and stays editable in the viewer.

Verified mapper rules (see ``references/svg-to-pptx-mcp-mapping.md``):

* every element needs ``id`` + ``shapeId`` or ``save`` fails;
* arbitrary paths must use ``customGeometryPaths`` (structured segments) —
  ``pathData`` renders but is **dropped on save**;
* set ``text`` alongside ``textSegments`` so the viewer renders the runs;
* gradients live in ``shapeStyle`` (they save but do not render in-preview);
* images use ``imageData`` data URLs.

Element animations are emitted from the ``animations.json`` sidecar (or the
``auto`` heuristic): each top-level ``<g id>`` anchor's ``effect`` becomes a
canonical entrance animation on every element that came from that group, which
the MCP write service serialises to ``p:timing``.

Unsupported in v1 (documented disposition): narration, EMF/WMF, OMML/LaTeX,
effects filters, native chart/table data, nested group transforms, ``arc`` in
paths (approximated by a line), and emphasis/exit/path effects (entrance only).
"""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .animations import build_slide_animations, with_default_effect
from .model import Element

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

# The animation vocabulary (effect -> preset, trigger map, `auto` pools) and the
# group -> element expansion live in :mod:`pptx_json.animations`, shared with the
# native engine. This module only derives the group anchors from top-level
# ``<g id>`` groups.

_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_PATH_TOKEN = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)")


def _tag(elem: ET.Element) -> str:
    return elem.tag.split("}", 1)[-1]


def _attr(elem: ET.Element, name: str, default: str | None = None) -> str | None:
    if name in elem.attrib:
        return elem.attrib[name]
    return elem.attrib.get(f"{{{SVG_NS}}}{name}", default)


def _num(value: str | None, default: float = 0.0) -> float:
    if not value:
        return default
    match = _NUM.search(value)
    return float(match.group()) if match else default


def _style_map(elem: ET.Element) -> dict[str, str]:
    style: dict[str, str] = {}
    raw = _attr(elem, "style")
    if raw:
        for part in raw.split(";"):
            if ":" in part:
                key, _, val = part.partition(":")
                style[key.strip()] = val.strip()
    return style


def _prop(elem: ET.Element, name: str, css: dict[str, str] | None = None) -> str | None:
    """Resolve an SVG presentation property.

    Priority follows the SVG/CSS cascade: inline ``style`` > CSS rules >
    presentation attribute.
    """
    inline = _style_map(elem)
    if name in inline:
        return inline[name]
    if css and name in css:
        return css[name]
    return _attr(elem, name)


def _compile_simple_selector(selector: str) -> tuple[int, dict[str, Any]] | None:
    """Compile a simple selector (``tag``, ``.a.b``, ``#id``) to (spec, matcher).

    Composed/descendant/pseudo selectors return ``None`` (skipped).
    """
    if not selector or any(ch in selector for ch in " >+~[:*"):
        return None
    tag: str | None = None
    element_id: str | None = None
    classes: set[str] = set()
    for name, value in re.findall(r"([.#]?)([A-Za-z0-9_\-]+)", selector):
        if name == ".":
            classes.add(value)
        elif name == "#":
            element_id = value
        else:
            tag = value
    if tag is None and element_id is None and not classes:
        return None
    specificity = (100 if element_id else 0) + 10 * len(classes) + (1 if tag else 0)
    return specificity, {"tag": tag, "id": element_id, "classes": classes}


def _parse_css(root: ET.Element) -> list[tuple[int, dict[str, Any], dict[str, str]]]:
    """Parse ``<style>`` blocks into (specificity, matcher, declarations)."""
    rules: list[tuple[int, dict[str, Any], dict[str, str]]] = []
    for node in root.iter():
        if _tag(node) != "style":
            continue
        text = re.sub(r"/\*.*?\*/", "", "".join(node.itertext()), flags=re.S)
        for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
            props: dict[str, str] = {}
            for declaration in block.group(2).split(";"):
                if ":" in declaration:
                    key, _, value = declaration.partition(":")
                    props[key.strip()] = value.strip()
            if not props:
                continue
            for selector in block.group(1).split(","):
                compiled = _compile_simple_selector(selector.strip())
                if compiled:
                    rules.append((compiled[0], compiled[1], props))
    return rules


def _css_for(elem: ET.Element, rules: list[tuple[int, dict[str, Any], dict[str, str]]]) -> dict[str, str]:
    """Merge the declarations whose selectors match ``elem`` (ascending specificity)."""
    if not rules:
        return {}
    tag = _tag(elem)
    element_id = _attr(elem, "id")
    classes = set((_attr(elem, "class") or "").split())
    merged: dict[str, str] = {}
    for _spec, matcher, props in sorted(rules, key=lambda rule: rule[0]):
        if matcher["tag"] and matcher["tag"] != tag:
            continue
        if matcher["id"] and matcher["id"] != element_id:
            continue
        if matcher["classes"] and not matcher["classes"].issubset(classes):
            continue
        merged.update(props)
    return merged


# ── transforms ──────────────────────────────────────────────────────────────

Matrix = tuple[float, float, float, float, float, float]  # a b c d e f


def _identity() -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _matmul(m1: Matrix, m2: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _parse_transform(value: str | None) -> Matrix:
    matrix = _identity()
    if not value:
        return matrix
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", value):
        nums = [float(n) for n in _NUM.findall(args)]
        if name == "translate" and nums:
            tx = nums[0]
            ty = nums[1] if len(nums) > 1 else 0.0
            matrix = _matmul(matrix, (1, 0, 0, 1, tx, ty))
        elif name == "scale" and nums:
            sx = nums[0]
            sy = nums[1] if len(nums) > 1 else sx
            matrix = _matmul(matrix, (sx, 0, 0, sy, 0, 0))
        elif name == "matrix" and len(nums) == 6:
            matrix = _matmul(matrix, tuple(nums))  # type: ignore[arg-type]
        elif name == "rotate" and nums:
            import math

            ang = math.radians(nums[0])
            cos, sin = math.cos(ang), math.sin(ang)
            rotate: Matrix = (cos, sin, -sin, cos, 0, 0)
            if len(nums) == 3:
                cx, cy = nums[1], nums[2]
                rotate = _matmul(_matmul((1, 0, 0, 1, cx, cy), rotate), (1, 0, 0, 1, -cx, -cy))
            matrix = _matmul(matrix, rotate)
    return matrix


def _apply(matrix: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


# ── path data -> custom geometry segments ───────────────────────────────────

def _tokenize_path(d: str) -> list[Any]:
    tokens: list[Any] = []
    for cmd, num in _PATH_TOKEN.findall(d):
        tokens.append(cmd if cmd else float(num))
    return tokens


def path_d_to_segments(d: str) -> list[dict[str, Any]]:
    """Convert an SVG path ``d`` into ``CustomGeometrySegment`` dicts.

    Supports M/L/H/V/C/S/Q/T/Z (absolute + relative). ``A`` arcs are reduced to
    a straight line to the arc endpoint (v1 limitation).
    """
    tokens = _tokenize_path(d)
    segments: list[dict[str, Any]] = []
    i = 0
    cx = cy = 0.0
    start_x = start_y = 0.0
    prev_ctrl: tuple[float, float] | None = None
    cmd = None

    def point(x: float, y: float) -> dict[str, float]:
        return {"x": x, "y": y}

    while i < len(tokens):
        token = tokens[i]
        if isinstance(token, str):
            cmd = token
            i += 1
            if cmd in "Zz":
                segments.append({"type": "close"})
                cx, cy = start_x, start_y
            continue
        if cmd is None:
            i += 1
            continue

        rel = cmd.islower()
        upper = cmd.upper()

        def take(n: int) -> list[float]:
            nonlocal i
            vals = [float(t) for t in tokens[i : i + n] if not isinstance(t, str)]
            i += n
            return vals

        if upper == "M":
            x, y = take(2)
            if rel:
                x, y = cx + x, cy + y
            segments.append({"type": "moveTo", "pt": point(x, y)})
            cx, cy = start_x, start_y = x, y
            cmd = "l" if rel else "L"
            prev_ctrl = None
        elif upper == "L":
            x, y = take(2)
            if rel:
                x, y = cx + x, cy + y
            segments.append({"type": "lineTo", "pt": point(x, y)})
            cx, cy = x, y
            prev_ctrl = None
        elif upper == "H":
            (x,) = take(1)
            x = cx + x if rel else x
            segments.append({"type": "lineTo", "pt": point(x, cy)})
            cx = x
            prev_ctrl = None
        elif upper == "V":
            (y,) = take(1)
            y = cy + y if rel else y
            segments.append({"type": "lineTo", "pt": point(cx, y)})
            cy = y
            prev_ctrl = None
        elif upper == "C":
            x1, y1, x2, y2, x, y = take(6)
            if rel:
                x1, y1, x2, y2, x, y = cx + x1, cy + y1, cx + x2, cy + y2, cx + x, cy + y
            segments.append({"type": "cubicBezTo", "pts": [point(x1, y1), point(x2, y2), point(x, y)]})
            prev_ctrl = (x2, y2)
            cx, cy = x, y
        elif upper == "S":
            x2, y2, x, y = take(4)
            if rel:
                x2, y2, x, y = cx + x2, cy + y2, cx + x, cy + y
            if prev_ctrl:
                x1, y1 = 2 * cx - prev_ctrl[0], 2 * cy - prev_ctrl[1]
            else:
                x1, y1 = cx, cy
            segments.append({"type": "cubicBezTo", "pts": [point(x1, y1), point(x2, y2), point(x, y)]})
            prev_ctrl = (x2, y2)
            cx, cy = x, y
        elif upper == "Q":
            x1, y1, x, y = take(4)
            if rel:
                x1, y1, x, y = cx + x1, cy + y1, cx + x, cy + y
            segments.append({"type": "quadBezTo", "pts": [point(x1, y1), point(x, y)]})
            prev_ctrl = (x1, y1)
            cx, cy = x, y
        elif upper == "T":
            x, y = take(2)
            if rel:
                x, y = cx + x, cy + y
            if prev_ctrl:
                x1, y1 = 2 * cx - prev_ctrl[0], 2 * cy - prev_ctrl[1]
            else:
                x1, y1 = cx, cy
            segments.append({"type": "quadBezTo", "pts": [point(x1, y1), point(x, y)]})
            prev_ctrl = (x1, y1)
            cx, cy = x, y
        elif upper == "A":
            _rx, _ry, _rot, _fa, _fs, x, y = take(7)
            if rel:
                x, y = cx + x, cy + y
            segments.append({"type": "lineTo", "pt": point(x, y)})
            prev_ctrl = None
            cx, cy = x, y
        else:
            i += 1
    return segments


def segments_to_path_d(segments: list[dict[str, Any]]) -> str:
    """Serialize ``CustomGeometrySegment`` dicts back into an SVG path ``d``.

    Inverse of :func:`path_d_to_segments`, used to populate the viewer's
    ``pathData``. Its custom-geometry renderer needs ``pathData`` +
    ``pathWidth`` + ``pathHeight``; ``customGeometryPaths`` alone renders as a
    plain preset rectangle.
    """
    parts: list[str] = []
    for seg in segments:
        kind = seg.get("type")
        if kind == "moveTo":
            p = seg["pt"]
            parts.append(f"M {p['x']} {p['y']}")
        elif kind == "lineTo":
            p = seg["pt"]
            parts.append(f"L {p['x']} {p['y']}")
        elif kind == "quadBezTo":
            p = seg["pts"]
            parts.append(f"Q {p[0]['x']} {p[0]['y']} {p[1]['x']} {p[1]['y']}")
        elif kind == "cubicBezTo":
            p = seg["pts"]
            parts.append(
                f"C {p[0]['x']} {p[0]['y']} {p[1]['x']} {p[1]['y']} {p[2]['x']} {p[2]['y']}"
            )
        elif kind == "close":
            parts.append("Z")
    return " ".join(parts)


# ── style ───────────────────────────────────────────────────────────────────

def _resolve_color(value: str | None, current_color: str | None = None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.lower() == "currentcolor":
        return current_color
    if value in {"none", "transparent"}:
        return None
    if value.startswith("#"):
        return value.upper()
    named = {
        "black": "#000000", "white": "#FFFFFF", "red": "#FF0000", "green": "#008000",
        "blue": "#0000FF", "gray": "#808080", "grey": "#808080", "yellow": "#FFFF00",
        "orange": "#FFA500", "purple": "#800080",
    }
    if value.lower() in named:
        return named[value.lower()]
    rgb = re.match(r"rgba?\(([^)]+)\)", value)
    if rgb:
        parts = [p.strip() for p in rgb.group(1).split(",")]
        if len(parts) >= 3:
            return "#%02X%02X%02X" % tuple(int(float(p)) for p in parts[:3])
    return value


def _shape_style(elem: ET.Element, gradients: dict[str, dict[str, Any]],
                 css: dict[str, str] | None = None,
                 current_color: str | None = None) -> dict[str, Any]:
    style: dict[str, Any] = {}
    fill = _prop(elem, "fill", css)
    stroke = _prop(elem, "stroke", css)
    stroke_width = _prop(elem, "stroke-width", css)
    opacity = _prop(elem, "opacity", css)
    fill_opacity = _prop(elem, "fill-opacity", css)

    if fill and fill.startswith("url("):
        grad_id = fill[fill.find("#") + 1 : fill.find(")")]
        grad = gradients.get(grad_id)
        if grad:
            style.update(grad)
    else:
        color = _resolve_color(fill, current_color)
        if color:
            style["fillColor"] = color
        elif fill == "none":
            style["fillMode"] = "none"
            style["fillColor"] = None

    stroke_color = _resolve_color(stroke, current_color)
    if stroke_color:
        style["strokeColor"] = stroke_color
        style["strokeWidth"] = _num(stroke_width, 1.0)
    elif stroke_width:
        style["strokeWidth"] = _num(stroke_width, 1.0)

    for source, target in ((opacity, "opacity"), (fill_opacity, "fillOpacity")):
        if source is not None:
            style[target] = float(_num(source, 1.0))
    return style


def _parse_markers(root: ET.Element) -> set[str]:
    """Return the ids of every ``<marker>`` defined in the document."""
    markers: set[str] = set()
    for node in root.iter():
        if _tag(node) == "marker":
            marker_id = _attr(node, "id")
            if marker_id:
                markers.add(marker_id)
    return markers


_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    ".tif": "image/tiff", ".tiff": "image/tiff", ".ico": "image/x-icon",
    ".emf": "image/x-emf", ".wmf": "image/x-wmf", ".svg": "image/svg+xml",
}


def _resolve_image(href: str, base_dir: Path | None) -> str | None:
    """Return a portable ``data:`` URL for an image href, or None.

    ``data:`` URLs pass through; remote URLs are skipped; relative paths are
    resolved against ``base_dir`` (the SVG's directory) and inlined.
    """
    if href.startswith("data:"):
        return href
    if href.startswith(("http://", "https://", "//")):
        return None
    raw = href[7:] if href.startswith("file://") else href
    raw = raw.split("?")[0].split("#")[0]
    path = Path(raw)
    if not path.is_absolute():
        if base_dir is None:
            return None
        path = Path(base_dir) / raw
    if not path.is_file():
        return None
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    mime = _MIME_BY_EXT.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


def _filter_ref(value: str | None) -> str | None:
    return _marker_ref_id(value)


def _parse_filters(root: ET.Element) -> dict[str, dict[str, Any]]:
    """Map ``<filter>`` definitions to typed shadow styles.

    Supports ``feDropShadow`` and the ``feGaussianBlur`` + ``feOffset``
    (optionally ``feFlood``) combination. Other filter primitives are ignored.
    """
    filters: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        if _tag(node) != "filter":
            continue
        filter_id = _attr(node, "id")
        if not filter_id:
            continue
        drop = None
        blur = None
        offset: tuple[str | None, str | None] | None = None
        flood_color = None
        flood_opacity = None
        for child in node.iter():
            child_tag = _tag(child)
            if child_tag == "feDropShadow":
                drop = {
                    "dx": _attr(child, "dx"), "dy": _attr(child, "dy"),
                    "std": _attr(child, "stdDeviation"),
                    "color": _attr(child, "flood-color"),
                    "opacity": _attr(child, "flood-opacity"),
                }
            elif child_tag == "feGaussianBlur":
                blur = _attr(child, "stdDeviation")
            elif child_tag == "feOffset":
                offset = (_attr(child, "dx"), _attr(child, "dy"))
            elif child_tag == "feFlood":
                flood_color = _attr(child, "flood-color")
                flood_opacity = _attr(child, "flood-opacity")

        shadow: dict[str, Any] = {}
        if drop:
            shadow = {
                "shadowColor": _resolve_color(drop["color"]) or "#000000",
                "shadowBlur": _num(drop["std"], 0.0) * 2,
                "shadowOffsetX": _num(drop["dx"], 0.0),
                "shadowOffsetY": _num(drop["dy"], 0.0),
                "shadowOpacity": float(_num(drop["opacity"], 1.0)),
            }
        elif blur is not None and offset is not None:
            shadow = {
                "shadowColor": _resolve_color(flood_color) or "#000000",
                "shadowBlur": _num(blur, 0.0) * 2,
                "shadowOffsetX": _num(offset[0], 0.0),
                "shadowOffsetY": _num(offset[1], 0.0),
                "shadowOpacity": float(_num(flood_opacity, 1.0)),
            }
        if shadow:
            filters[filter_id] = shadow
    return filters


def _marker_ref_id(value: str | None) -> str | None:
    if not value or not value.startswith("url("):
        return None
    inner = value[value.find("#") + 1 : value.find(")")]
    return inner or None


def _apply_markers(style: dict[str, Any], elem: ET.Element, markers: set[str]) -> None:
    """Map ``marker-start`` / ``marker-end`` references to arrowhead fields."""
    if not markers:
        return
    start = _marker_ref_id(_attr(elem, "marker-start"))
    end = _marker_ref_id(_attr(elem, "marker-end"))
    if start and start in markers:
        style["connectorStartArrow"] = "triangle"
    if end and end in markers:
        style["connectorEndArrow"] = "triangle"


def _parse_gradients(root: ET.Element) -> dict[str, dict[str, Any]]:
    gradients: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        tag = _tag(node)
        if tag not in {"linearGradient", "radialGradient"}:
            continue
        grad_id = _attr(node, "id")
        if not grad_id:
            continue
        stops = []
        for stop in node:
            if _tag(stop) != "stop":
                continue
            color = _resolve_color(_prop(stop, "stop-color") or _attr(stop, "stop-color"))
            offset = _attr(stop, "offset") or "0"
            pos = _num(offset, 0.0)
            if "%" in (offset or ""):
                pos = pos
            else:
                pos = pos * 100
            stops.append({"color": color or "#000000", "position": round(pos)})
        if not stops:
            continue
        entry: dict[str, Any] = {
            "fillMode": "gradient",
            "fillGradientStops": stops,
            "fillGradientType": "radial" if tag == "radialGradient" else "linear",
        }
        if tag == "linearGradient":
            entry["fillGradientAngle"] = 0.0
        gradients[grad_id] = entry
    return gradients


# ── element conversion ──────────────────────────────────────────────────────

def _first_family(value: str | None) -> str | None:
    if not value:
        return None
    first = value.split(",")[0].strip().strip('"').strip("'")
    return first or None


def _estimate_width(text: str, font_size: float) -> float:
    """Rough advance width: CJK/fullwidth ≈ 1em, other glyphs ≈ 0.55em."""
    total = 0.0
    for ch in text:
        total += 1.0 if ord(ch) > 0x2E80 else 0.55
    return total * font_size


class _Builder:
    def __init__(self, canvas_w: float, canvas_h: float, markers: set[str] | None = None,
                 base_dir: Path | None = None,
                 css_rules: list[tuple[int, dict[str, Any], dict[str, str]]] | None = None,
                 filters: dict[str, dict[str, Any]] | None = None,
                 current_color: str | None = None) -> None:
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h
        self.current_color = current_color
        self.markers = markers or set()
        self.base_dir = base_dir
        self.css_rules = css_rules or []
        self.filters = filters or {}
        self.next_id = 2
        # element id -> the top-level `<g id>` anchor it was produced from.
        self.group_of_element: dict[str, str] = {}

    def _ids(self) -> tuple[str, str]:
        shape_id = str(self.next_id)
        self.next_id += 1
        return f"el-{shape_id}", shape_id

    def _base(self, x: float, y: float, w: float, h: float) -> dict[str, Any]:
        eid, shape_id = self._ids()
        return {"id": eid, "shape_id": shape_id, "x": round(x, 2), "y": round(y, 2),
                "width": round(w, 2), "height": round(h, 2)}

    def convert(
        self,
        elem: ET.Element,
        matrix: Matrix,
        gradients: dict[str, dict[str, Any]],
        group_id: str | None = None,
    ) -> list[dict[str, Any]]:
        tag = _tag(elem)
        if tag in {"defs", "style", "title", "desc", "metadata"}:
            return []
        if tag in {"linearGradient", "radialGradient", "stop", "clipPath", "filter", "mask"}:
            return []

        matrix = _matmul(matrix, _parse_transform(_attr(elem, "transform")))
        css = _css_for(elem, self.css_rules)
        style = _shape_style(elem, gradients, css, self.current_color)
        _apply_markers(style, elem, self.markers)
        filter_id = _filter_ref(_prop(elem, "filter", css))
        if filter_id and filter_id in self.filters:
            style.update(self.filters[filter_id])

        if tag == "g":
            # A nested group keeps its top-level ancestor's anchor: the sidecar
            # keys are top-level `<g id>` values, so only that scope is tracked.
            out: list[dict[str, Any]] = []
            for child in elem:
                out.extend(self.convert(child, matrix, gradients, group_id))
            return out
        if tag == "svg":
            out = []
            for child in elem:
                out.extend(self.convert(child, matrix, gradients, group_id))
            return out

        produced = self._emit_leaf(tag, elem, matrix, style, gradients, css)
        if group_id:
            for element in produced:
                self.group_of_element[element["id"]] = group_id
        return produced

    def _emit_leaf(
        self,
        tag: str,
        elem: ET.Element,
        matrix: Matrix,
        style: dict[str, Any],
        gradients: dict[str, dict[str, Any]],
        css: dict[str, str],
    ) -> list[dict[str, Any]]:
        if tag == "rect":
            return [self._rect(elem, matrix, style, gradients)]
        if tag in {"circle", "ellipse"}:
            return [self._ellipse(elem, matrix, style, tag)]
        if tag == "line":
            return [self._line(elem, matrix, style)]
        if tag in {"polygon", "polyline"}:
            return [self._poly(elem, matrix, style, closed=(tag == "polygon"))]
        if tag == "path":
            return [self._path(elem, matrix, style, gradients)]
        if tag == "image":
            result = self._image(elem, matrix)
            return [result] if result else []
        if tag == "text":
            result = self._text(elem, matrix, css)
            return [result] if result else []
        return []

    def _rect(self, elem: ET.Element, m: Matrix, style: dict[str, Any], gradients: dict[str, Any]) -> dict[str, Any]:
        x, y = _num(_attr(elem, "x")), _num(_attr(elem, "y"))
        w, h = _num(_attr(elem, "width")), _num(_attr(elem, "height"))
        x, y = _apply(m, x, y)
        w, h = w * abs(m[0]), h * abs(m[3])
        rx = _num(_attr(elem, "rx"))
        element = Element(type="shape", shape_type="roundRect" if rx else "rect",
                          shape_style={k: v for k, v in style.items() if v is not None}, **self._base(x, y, w, h))
        return element.to_dict()

    def _ellipse(self, elem: ET.Element, m: Matrix, style: dict[str, Any], tag: str) -> dict[str, Any]:
        cx, cy = _num(_attr(elem, "cx")), _num(_attr(elem, "cy"))
        if tag == "circle":
            rx = ry = _num(_attr(elem, "r"))
        else:
            rx, ry = _num(_attr(elem, "rx")), _num(_attr(elem, "ry"))
        rx, ry = rx * abs(m[0]), ry * abs(m[3])
        cx, cy = _apply(m, cx, cy)
        return Element(type="shape", shape_type="ellipse", shape_style={k: v for k, v in style.items() if v is not None},
                       **self._base(cx - rx, cy - ry, rx * 2, ry * 2)).to_dict()

    def _line(self, elem: ET.Element, m: Matrix, style: dict[str, Any]) -> dict[str, Any]:
        x1, y1 = _apply(m, _num(_attr(elem, "x1")), _num(_attr(elem, "y1")))
        x2, y2 = _apply(m, _num(_attr(elem, "x2")), _num(_attr(elem, "y2")))
        return Element(type="connector", shape_type="line",
                       shape_style={k: v for k, v in style.items() if v is not None},
                       **self._base(min(x1, x2), min(y1, y2), abs(x2 - x1) or 1, abs(y2 - y1) or 1)).to_dict()

    def _poly(self, elem: ET.Element, m: Matrix, style: dict[str, Any], *, closed: bool) -> dict[str, Any]:
        nums = [float(v) for v in _NUM.findall(_attr(elem, "points") or "")]
        pts = [_apply(m, nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
        xs = [p[0] for p in pts] or [0.0]
        ys = [p[1] for p in pts] or [0.0]
        ox, oy = min(xs), min(ys)
        w, h = (max(xs) - ox) or 1.0, (max(ys) - oy) or 1.0
        segments: list[dict[str, Any]] = []
        for idx, (px, py) in enumerate(pts):
            local = {"x": round(px - ox, 2), "y": round(py - oy, 2)}
            segments.append({"type": "moveTo" if idx == 0 else "lineTo", "pt": local})
        if closed:
            segments.append({"type": "close"})
        base = self._base(ox, oy, w, h)
        return Element(type="shape", shape_style={k: v for k, v in style.items() if v is not None},
                       extra={"customGeometryPaths": [{"width": round(w, 2), "height": round(h, 2), "segments": segments}],
                              "pathData": segments_to_path_d(segments),
                              "pathWidth": round(w, 2), "pathHeight": round(h, 2)},
                       **base).to_dict()

    def _path(self, elem: ET.Element, m: Matrix, style: dict[str, Any], gradients: dict[str, Any]) -> dict[str, Any]:
        d = _attr(elem, "d") or ""
        segments = path_d_to_segments(d)
        # Bake the transform into the points, then normalise to the element box.
        baked: list[dict[str, Any]] = []
        xs: list[float] = []
        ys: list[float] = []
        for seg in segments:
            if "pt" in seg:
                x, y = _apply(m, seg["pt"]["x"], seg["pt"]["y"])
                seg = {**seg, "pt": {"x": x, "y": y}}
            elif "pts" in seg:
                new_pts = []
                for p in seg["pts"]:
                    x, y = _apply(m, p["x"], p["y"])
                    new_pts.append({"x": x, "y": y})
                seg = {**seg, "pts": new_pts}
            baked.append(seg)
            for p in ([seg["pt"]] if "pt" in seg else seg.get("pts", [])):
                xs.append(p["x"])
                ys.append(p["y"])
        if not xs:
            return Element(type="shape", shape_style={k: v for k, v in style.items() if v is not None},
                           **self._base(0, 0, 1, 1)).to_dict()
        ox, oy = min(xs), min(ys)
        w, h = (max(xs) - ox) or 1.0, (max(ys) - oy) or 1.0
        local: list[dict[str, Any]] = []
        for seg in baked:
            if "pt" in seg:
                seg = {**seg, "pt": {"x": round(seg["pt"]["x"] - ox, 2), "y": round(seg["pt"]["y"] - oy, 2)}}
            elif "pts" in seg:
                seg = {**seg, "pts": [{"x": round(p["x"] - ox, 2), "y": round(p["y"] - oy, 2)} for p in seg["pts"]]}
            local.append(seg)
        base = self._base(ox, oy, w, h)
        return Element(type="shape", shape_style={k: v for k, v in style.items() if v is not None},
                       extra={"customGeometryPaths": [{"width": round(w, 2), "height": round(h, 2), "segments": local}],
                              "pathData": segments_to_path_d(local),
                              "pathWidth": round(w, 2), "pathHeight": round(h, 2)},
                       **base).to_dict()

    def _image(self, elem: ET.Element, m: Matrix) -> dict[str, Any] | None:
        href = _attr(elem, "href") or elem.attrib.get(f"{{{XLINK_NS}}}href")
        if not href:
            return None
        x, y = _apply(m, _num(_attr(elem, "x")), _num(_attr(elem, "y")))
        w, h = _num(_attr(elem, "width")) * abs(m[0]), _num(_attr(elem, "height")) * abs(m[3])
        data_url = _resolve_image(href, self.base_dir)
        if not data_url:
            return None
        return Element(type="image", image_data=data_url, **self._base(x, y, w, h)).to_dict()

    def _text(self, elem: ET.Element, m: Matrix, css: dict[str, str] | None = None) -> dict[str, Any] | None:
        css = css or {}
        x = _num(_attr(elem, "x"))
        y = _num(_attr(elem, "y"))
        # Font size is a scalar the transform matrix cannot carry through
        # geometry, so scale it explicitly: this is what lets an SVG be placed
        # at an arbitrary rect via a `<g transform="scale(...)">` wrapper.
        scale = abs(m[0]) or 1.0
        font_size = _num(_prop(elem, "font-size", css), 18.0) * scale
        fill = _resolve_color(_prop(elem, "fill", css), self.current_color) or "#000000"
        family = _first_family(_prop(elem, "font-family", css))
        anchor = (_prop(elem, "text-anchor", css) or "start").strip()
        weight = _prop(elem, "font-weight", css)

        def run_style(size: float, color: str, node: ET.Element | None = None) -> dict[str, Any]:
            node_css = _css_for(node, self.css_rules) if node is not None else None
            style: dict[str, Any] = {"fontSize": size, "color": color}
            family_here = _first_family(_prop(node, "font-family", node_css) if node is not None else None) or family
            if family_here:
                style["fontFamily"] = family_here
            weight_here = (_prop(node, "font-weight", node_css) if node is not None else None) or weight
            if weight_here and (weight_here == "bold" or _num(weight_here, 400) >= 600):
                style["bold"] = True
            return style

        # Group runs into visual lines: a tspan carrying x/dy starts a new line.
        lines: list[list[tuple[str, dict[str, Any]]]] = [[]]
        if elem.text and elem.text.strip():
            lines[-1].append((elem.text, run_style(font_size, fill)))
        for node in elem:
            if _tag(node) != "tspan":
                continue
            starts_line = ("x" in node.attrib or "dy" in node.attrib) and bool(lines[-1])
            txt = "".join(node.itertext())
            if txt:
                if starts_line:
                    lines.append([])
                tspan_size_attr = _attr(node, "font-size")
                tspan_size = (_num(tspan_size_attr, 18.0) * scale) if tspan_size_attr else font_size
                lines[-1].append((txt, run_style(tspan_size,
                                                 _resolve_color(_prop(node, "fill", _css_for(node, self.css_rules)), self.current_color) or fill, node)))
            if node.tail and node.tail.strip():
                lines[-1].append((node.tail, run_style(font_size, fill)))
        lines = [line for line in lines if line]
        if not lines:
            return None

        text = "\n".join("".join(part for part, _ in line) for line in lines)
        segments: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            for part, style in line:
                segments.append({"text": part, "style": style})
            if index < len(lines) - 1:
                segments.append({"text": "\n", "style": line[-1][1]})

        max_width = max(_estimate_width("".join(p for p, _ in line), font_size) for line in lines)
        max_width = max_width * 1.05 + font_size * 0.1
        line_height = font_size * 1.25
        height = line_height * len(lines)
        px, py = _apply(m, x, y)
        if anchor == "middle":
            left = px - max_width / 2
        elif anchor == "end":
            left = px - max_width
        else:
            left = px
        # The source already wraps lines via tspans; a per-element width wide
        # enough for the longest authored line keeps viewer wrapping neutral.
        text_style = {"fontSize": font_size, "color": fill}
        if family:
            text_style["fontFamily"] = family
        text_style["align"] = {"start": "left", "middle": "center", "end": "right"}.get(anchor, "left")
        return Element(type="text", text=text, text_segments=segments, text_style=text_style,
                       **self._base(left, py - font_size, max(max_width, 1.0), height)).to_dict()


def svg_to_slide(
    svg_text: str,
    *,
    canvas_w: float,
    canvas_h: float,
    slide_id: str | None = None,
    start_shape_id: int = 2,
    base_dir: Path | str | None = None,
    animation_groups: dict[str, dict[str, Any]] | None = None,
    animation_auto: bool = False,
    animation_default_effect: str | None = None,
    current_color: str | None = None,
) -> dict[str, Any]:
    """Convert one SVG document into a ``pptx-viewer-json`` slide record.

    ``animation_groups`` is the ``animations.json`` ``slides.<stem>.groups``
    object; ``animation_auto`` synthesises it from the discovered group ids;
    ``animation_default_effect`` applies one effect to every group lacking a
    config. Any of these produces ``slide['animations']`` (entrance effects).
    ``current_color`` resolves SVG ``currentColor`` (icons use it for their
    fill/stroke).
    """
    root = ET.fromstring(svg_text)
    gradients = _parse_gradients(root)
    markers = _parse_markers(root)
    css_rules = _parse_css(root)
    filters = _parse_filters(root)
    builder = _Builder(canvas_w, canvas_h, markers=markers,
                       base_dir=Path(base_dir) if base_dir is not None else None,
                       css_rules=css_rules, filters=filters, current_color=current_color)
    builder.next_id = start_shape_id

    viewbox = _attr(root, "viewBox")
    sx = sy = 1.0
    if viewbox:
        parts = [float(v) for v in _NUM.findall(viewbox)]
        if len(parts) == 4 and parts[2] and parts[3]:
            sx, sy = canvas_w / parts[2], canvas_h / parts[3]
    base_matrix: Matrix = (sx, 0.0, 0.0, sy, 0.0, 0.0)

    elements: list[dict[str, Any]] = []
    for child in root:
        # Only a top-level `<g id>` is an animation anchor.
        group_id = _attr(child, "id") if _tag(child) == "g" else None
        elements.extend(builder.convert(child, base_matrix, gradients, group_id))

    if animation_groups is None and not animation_auto:
        animation_groups = with_default_effect(
            builder.group_of_element, animation_default_effect
        )

    animations = build_slide_animations(
        builder.group_of_element, animation_groups, auto=animation_auto
    )

    slide: dict[str, Any] = {"elements": elements}
    if animations:
        slide["animations"] = animations
    if slide_id:
        slide["id"] = slide_id
    return slide


def svg_files_to_document(
    svg_texts: list[str],
    *,
    canvas_w: float,
    canvas_h: float,
    base_dirs: list[Path | str | None] | None = None,
    slide_stems: list[str] | None = None,
    animations: dict[str, Any] | None = None,
    animation_auto: bool = False,
    animation_default_effect: str | None = None,
    current_color: str | None = None,
) -> dict[str, Any]:
    """Build a full ``pptx-viewer-json`` document from SVG page texts.

    ``animations`` is a parsed ``animations.json`` sidecar; its
    ``slides.<stem>.groups`` object is applied per page (``slide_stems`` names
    each page, defaulting to the caller's order). ``animation_auto`` applies the
    deck-wide ``auto`` heuristic when no per-slide config exists.
    """
    from .document import build_document

    animation_slides = {}
    if isinstance(animations, dict):
        candidate = animations.get("slides")
        if isinstance(candidate, dict):
            animation_slides = candidate

    slides = []
    for index, text in enumerate(svg_texts, start=1):
        base_dir = base_dirs[index - 1] if base_dirs else None
        stem = slide_stems[index - 1] if slide_stems else None
        groups = None
        if stem is not None and isinstance(animation_slides.get(stem), dict):
            groups = animation_slides[stem].get("groups")
        slides.append(svg_to_slide(text, canvas_w=canvas_w, canvas_h=canvas_h,
                                   slide_id=f"ppt/slides/slide{index}.xml", base_dir=base_dir,
                                   animation_groups=groups,
                                   animation_auto=animation_auto and not groups,
                                   animation_default_effect=animation_default_effect,
                                   current_color=current_color))
    return build_document(slides, width=int(canvas_w), height=int(canvas_h))
