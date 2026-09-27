"""Light dataclasses for building ``pptx-viewer-json`` slides and elements.

These mirror the subset of the ``PptxData`` / ``PptxElement`` model that the
SVG→model mapper emits. They are deliberately permissive: unknown-but-valid
model fields can be passed through ``extra``, and ``raw_xml`` carries residual
OOXML for constructs the typed model cannot express (the C1-Hybrid strategy).

Keys are serialized to the canonical camelCase the importer expects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

_PASSTHROUGH_FIELDS: dict[str, str] = {
    "id": "id",
    "name": "name",
    "shape_id": "shapeId",
    "x": "x",
    "y": "y",
    "width": "width",
    "height": "height",
    "rotation": "rotation",
    "text": "text",
    "text_style": "textStyle",
    "text_segments": "textSegments",
    "shape_style": "shapeStyle",
    "shape_type": "shapeType",
    "path_data": "pathData",
    "path_width": "pathWidth",
    "path_height": "pathHeight",
    "image_data": "imageData",
    "table_data": "tableData",
    "chart_data": "chartData",
    "raw_xml": "rawXml",
    "ext_lst_xml": "extLstXml",
}


@dataclass
class Element:
    """One slide element (``type`` is required by the format)."""

    type: str
    id: str | None = None
    name: str | None = None
    shape_id: str | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    rotation: float | None = None
    text: str | None = None
    text_style: dict[str, Any] | None = None
    text_segments: list[dict[str, Any]] | None = None
    shape_style: dict[str, Any] | None = None
    shape_type: str | None = None
    path_data: str | None = None
    path_width: float | None = None
    path_height: float | None = None
    image_data: str | None = None
    table_data: Any | None = None
    chart_data: Any | None = None
    raw_xml: Any | None = None
    ext_lst_xml: list[Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {}
        for attr, key in _PASSTHROUGH_FIELDS.items():
            value = getattr(self, attr)
            if value is not None:
                record[key] = value
        record["type"] = self.type
        for key, value in self.extra.items():
            record[key] = value
        return record


@dataclass
class Slide:
    """One slide record."""

    elements: list[Element] = field(default_factory=list)
    id: str | None = None
    notes: str | None = None
    raw_xml: Any | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {}
        if self.id is not None:
            record["id"] = self.id
        if self.notes is not None:
            record["notes"] = self.notes
        if self.raw_xml is not None:
            record["rawXml"] = self.raw_xml
        record["elements"] = [element.to_dict() for element in self.elements]
        for key, value in self.extra.items():
            record[key] = value
        return record


def slides_to_records(slides: Iterable[Slide | dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a mix of :class:`Slide` and raw dicts into slide records."""
    return [slide.to_dict() if isinstance(slide, Slide) else dict(slide) for slide in slides]


def element_from_raw_xml(
    element_type: str,
    raw_xml: Any,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    shape_id: str | None = None,
    name: str | None = None,
) -> Element:
    """Build an element whose markup is carried verbatim on ``raw_xml``.

    ``raw_xml`` must be the **inner** node (see ``xml_to_obj_node``); wrapping it
    in its own tag would double-nest on save. Geometry is still supplied so the
    element participates in transforms and selection.
    """
    return Element(
        type=element_type,
        x=x,
        y=y,
        width=width,
        height=height,
        shape_id=shape_id,
        name=name,
        raw_xml=raw_xml,
    )
