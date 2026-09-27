"""Convert an SVG into positioned ``pptx-viewer-json`` elements for insertion.

The native workflow (``native_to_pptx_mcp.py``) authors slides directly as the
JSON element model and imports them — it does not render per-slide SVGs. This
module bridges the two: it places an arbitrary SVG's content at an explicit
rect ``(x, y, w, h)`` on the canvas and emits it as typed elements (text stays
editable text), optionally wrapped in a single ``group`` element so the whole
insertion can be dropped into one slide atomically.

It reuses two proven pieces:

- ``svg_to_drawingml.build_stage_svg`` (vendor) — positions the SVG content at
  ``(x, y, w, h)`` on a canvas-sized stage. Two tiers: no-text SVGs get a
  ``<g transform>`` wrapper; SVGs with text have the placement baked into the
  geometry (so font-sizes land at their final pixel size).
- ``pptx_json.svg_model.svg_to_slide`` — converts a stage SVG (whose viewBox
  equals the canvas, i.e. identity mapping) into typed JSON elements.

Because the stage viewBox equals the canvas, ``svg_to_slide`` applies an
identity matrix and every element comes out already at its final position and
size — text included.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_THIS = Path(__file__).resolve()
_SCRIPTS = _THIS.parents[1]
_VENDOR = _THIS.parents[2] / "vendor" / "ppt-master" / "scripts"
for _p in (_SCRIPTS, _VENDOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from pptx_json import svg_model  # noqa: E402
import svg_to_drawingml as dml  # noqa: E402


def read_view_box(svg_path: Path | str):
    """Read an SVG's ``(vb_x, vb_y, vb_w, vb_h)`` (delegates to the vendor helper)."""
    return dml.read_source_view_box(Path(svg_path))


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
) -> list[dict[str, Any]]:
    """Return the SVG's content as typed elements placed at ``(x, y, w, h)``.

    ``view_box`` is the source SVG's ``(vb_x, vb_y, vb_w, vb_h)`` (use
    :func:`read_view_box`). The content is scaled/positioned to fit the rect
    (``keep_aspect`` + ``fit`` control the mapping) and returned as a flat list
    of ``pptx-viewer-json`` elements in absolute canvas coordinates.
    """
    stage, _placement = dml.build_stage_svg(
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
