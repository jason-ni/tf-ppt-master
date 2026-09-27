"""Convert an SVG into positioned ``pptx-viewer-json`` elements for insertion.

Places an arbitrary SVG's content at an explicit rect ``(x, y, w, h)`` on the
canvas and emits it as typed native elements — vector DrawingML (rect/path/
polygon/ellipse/line → ``shape``/``connector``) and text stays editable text —
optionally wrapped in a single ``group`` element so the whole insertion can be
dropped into one slide atomically.

Unlike the earlier implementation, this module is **self-contained**: it no
longer depends on a vendored ``svg_to_drawingml`` module. Placement is done by
wrapping the source content in ``<g transform="translate(tx,ty) scale(sx,sy)">``
on a canvas-sized stage whose ``viewBox`` equals the canvas (so
:func:`pptx_json.svg_model.svg_to_slide` applies an identity base matrix and every
element comes out in absolute canvas coordinates). Text scales correctly because
``svg_model`` multiplies a run's font-size by the transform's scale factor.

Public API::

    vb = read_view_box("icon.svg")                       # (vb_x, vb_y, vb_w, vb_h)
    els = positioned_elements(svg_text, vb, x=.., y=.., w=.., h=..)   # flat elements
    grp = group_element(svg_text, vb, x=.., y=.., w=.., h=..)         # one group element
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_THIS = Path(__file__).resolve()
_SCRIPTS = _THIS.parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from pptx_json import svg_model  # noqa: E402

_VIEW_BOX_RE = re.compile(r'viewBox\s*=\s*"([^"]+)"', re.I)
_WIDTH_RE = re.compile(r'(?<![\w-])width\s*=\s*"([^"]+)"', re.I)
_HEIGHT_RE = re.compile(r'(?<![\w-])height\s*=\s*"([^"]+)"', re.I)
_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.I | re.S)
_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _first_number(value: str | None) -> float | None:
    if not value:
        return None
    match = _NUM.search(value)
    return float(match.group()) if match else None


def read_view_box_text(svg_text: str):
    """Return an SVG text's ``(vb_x, vb_y, vb_w, vb_h)`` or ``None``.

    Falls back to ``width``/``height`` (origin at 0,0) when there is no
    ``viewBox``.
    """
    match = _VIEW_BOX_RE.search(svg_text)
    if match:
        values = [float(v) for v in _NUM.findall(match.group(1))]
        if len(values) == 4 and values[2] and values[3]:
            return (values[0], values[1], values[2], values[3])
    width_match = _WIDTH_RE.search(svg_text)
    height_match = _HEIGHT_RE.search(svg_text)
    width = _first_number(width_match.group(1)) if width_match else None
    height = _first_number(height_match.group(1)) if height_match else None
    if width and height:
        return (0.0, 0.0, width, height)
    return None


def read_view_box(svg_path: Path | str):
    """Read an SVG file's ``(vb_x, vb_y, vb_w, vb_h)``.

    Raises :class:`ValueError` when the file carries neither a ``viewBox`` nor a
    usable ``width``/``height`` pair.
    """
    view_box = read_view_box_text(Path(svg_path).read_text(encoding="utf-8"))
    if view_box is None:
        raise ValueError(f"{svg_path} has no usable viewBox/width/height")
    return view_box


def _svg_inner(svg_text: str) -> str:
    """Return the markup between the root ``<svg ...>`` and the closing tag.

    A string slice (not an XML round-trip) so ``defs``/``style``/CDATA and every
    attribute survive verbatim.
    """
    open_tag = _SVG_OPEN_RE.search(svg_text)
    if open_tag is None:
        raise ValueError("not an <svg> document")
    close = svg_text.lower().rfind("</svg>")
    if close == -1 or close < open_tag.end():
        raise ValueError("unterminated <svg> document")
    return svg_text[open_tag.end() : close]


def build_stage_svg(
    svg_text: str,
    view_box,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    canvas_w: float,
    canvas_h: float,
    keep_aspect: bool = False,
    fit: str = "contain",
) -> tuple[str, tuple[float, float, float, float]]:
    """Wrap ``svg_text``'s content on a canvas-sized stage placed at ``(x,y,w,h)``.

    Returns ``(stage_svg, (tx, ty, sx, sy))``. ``fit`` is ``contain`` (default),
    ``cover``, ``fill`` or ``stretch``; ``keep_aspect`` forces a uniform scale
    even for ``fill``.
    """
    vx, vy, vw, vh = view_box if view_box else (0.0, 0.0, canvas_w, canvas_h)
    if not vw or not vh:
        raise ValueError(f"degenerate viewBox {view_box!r}")

    uniform = keep_aspect or fit in ("contain", "cover")
    if uniform:
        scale = min(w / vw, h / vh) if fit != "cover" else max(w / vw, h / vh)
        sx = sy = scale
        ox = (w - vw * sx) / 2.0
        oy = (h - vh * sy) / 2.0
    else:
        sx, sy = w / vw, h / vh
        ox = oy = 0.0

    tx = x + ox - vx * sx
    ty = y + oy - vy * sy
    inner = _svg_inner(svg_text)
    stage = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {canvas_w} {canvas_h}" width="{canvas_w}" height="{canvas_h}" '
        f'preserveAspectRatio="none">'
        f'<g transform="translate({tx} {ty}) scale({sx} {sy})">{inner}</g>'
        f"</svg>"
    )
    return stage, (tx, ty, sx, sy)


def positioned_elements(
    svg_text: str,
    view_box,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    canvas_w: float = 1280.0,
    canvas_h: float = 720.0,
    keep_aspect: bool = False,
    fit: str = "contain",
    base_dir: Path | str | None = None,
    current_color: str | None = None,
) -> list[dict[str, Any]]:
    """Return the SVG's content as typed elements placed at ``(x, y, w, h)``.

    ``view_box`` is the source SVG's ``(vb_x, vb_y, vb_w, vb_h)`` (use
    :func:`read_view_box`). ``current_color`` resolves ``currentColor`` in the
    source (icons use it for fill/stroke). The result is a flat list of
    ``pptx-viewer-json`` elements in absolute canvas coordinates.
    """
    stage, _placement = build_stage_svg(
        svg_text,
        view_box,
        x=x,
        y=y,
        w=w,
        h=h,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        keep_aspect=keep_aspect,
        fit=fit,
    )
    slide = svg_model.svg_to_slide(
        stage,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        base_dir=base_dir,
        animation_groups={},
        current_color=current_color,
    )
    return slide["elements"]


def _content_bounds(elements: list[dict[str, Any]]):
    """Return ``(x0, y0, x1, y1)`` — the bounding box of ``elements``.

    Every converted element carries ``x``/``y``/``width``/``height`` in absolute
    canvas coordinates, so the bounds are a simple min/max over those.
    """
    xs0: list[float] = []
    ys0: list[float] = []
    xs1: list[float] = []
    ys1: list[float] = []
    for e in elements:
        if "x" not in e or "y" not in e:
            continue
        ex = float(e["x"])
        ey = float(e["y"])
        ew = float(e.get("width", 0.0))
        eh = float(e.get("height", 0.0))
        xs0.append(ex)
        ys0.append(ey)
        xs1.append(ex + ew)
        ys1.append(ey + eh)
    if not xs0:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def group_element(
    svg_text: str,
    view_box,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    canvas_w: float = 1280.0,
    canvas_h: float = 720.0,
    keep_aspect: bool = False,
    fit: str = "contain",
    base_dir: Path | str | None = None,
    name: str | None = None,
    current_color: str | None = None,
) -> dict[str, Any]:
    """Return a single ``group`` element wrapping the positioned SVG content.

    Matches the viewer's canonical group format (verified via ``export_to_json``
    after ``group_elements``):

    - children live under the ``children`` key (NOT ``elements``);
    - the group's ``x``/``y``/``width``/``height`` are the bounding box of its
      content;
    - each child is in **local** coordinates relative to the group origin, i.e.
      its absolute canvas position minus ``(x0, y0)`` (the content-bounds min).

    The result can be appended directly to a slide's ``elements`` list and
    imported with ``import_from_json``.
    """
    elements = positioned_elements(
        svg_text,
        view_box,
        x=x,
        y=y,
        w=w,
        h=h,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        keep_aspect=keep_aspect,
        fit=fit,
        base_dir=base_dir,
        current_color=current_color,
    )
    if not elements:
        raise ValueError("SVG produced no insertable elements")
    x0, y0, x1, y1 = _content_bounds(elements)
    children: list[dict[str, Any]] = []
    for e in elements:
        child = dict(e)
        if "x" in child:
            child["x"] = child["x"] - x0
        if "y" in child:
            child["y"] = child["y"] - y0
        children.append(child)
    group: dict[str, Any] = {
        "type": "group",
        "x": x0,
        "y": y0,
        "width": x1 - x0,
        "height": y1 - y0,
        "children": children,
    }
    if name:
        group["name"] = name
    return group
