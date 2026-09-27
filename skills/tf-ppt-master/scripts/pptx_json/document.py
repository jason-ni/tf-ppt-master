"""The ``pptx-viewer-json`` document format (version 1).

A portable, versioned, self-contained JSON representation of a presentation.
Binary payloads are embedded (base64 data URLs) so a document round-trips
without the original ``.pptx`` archive.

Top-level shape::

    {
      "format": "pptx-viewer-json",
      "version": 1,
      "generator": "ppt-master-plus",
      "createdAt": "2026-09-22T00:00:00.000Z",
      "slideCount": 3,
      "assets": {"count": 0, "totalBytes": 0},
      "presentation": {"width": 1280, "height": 720},
      "slides": [{"elements": [...]}, ...]
    }

The validation here mirrors the ``pptx-viewer`` core ``parsePptxJsonDocument``
rules (format marker, version, object shapes, per-element ``type``) so a
document rejected locally would also be rejected by ``import_from_json``.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

FORMAT = "pptx-viewer-json"
VERSION = 1


class DocumentError(ValueError):
    """Raised when a candidate document fails ``pptx-viewer-json`` validation."""


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def build_document(
    slides: Iterable[Mapping[str, Any]],
    *,
    width: int,
    height: int,
    presentation: Mapping[str, Any] | None = None,
    generator: str = "ppt-master-plus",
    created_at: str | None = None,
) -> dict[str, Any]:
    """Assemble a valid ``pptx-viewer-json`` document from slide records.

    ``presentation`` extra keys are merged over ``width``/``height`` (which win,
    since they are validated on import).
    """
    slide_list = [copy.deepcopy(dict(slide)) for slide in slides]
    _normalize_tables(slide_list)
    presentation_obj: dict[str, Any] = dict(presentation or {})
    presentation_obj["width"] = int(width)
    presentation_obj["height"] = int(height)
    if created_at is None:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    assets = _count_assets(slide_list)
    return {
        "format": FORMAT,
        "version": VERSION,
        "generator": generator,
        "createdAt": created_at,
        "slideCount": len(slide_list),
        "assets": assets,
        "presentation": presentation_obj,
        "slides": slide_list,
    }


def _table_column_count(table: Mapping[str, Any]) -> int:
    """Widest row (in cells) of a ``tableData`` record, 0 when empty."""
    rows = table.get("rows")
    return max(
        (
            len(row.get("cells") or [])
            for row in rows or []
            if isinstance(row, dict)
        ),
        default=0,
    )


def _normalize_tables(slides: list[dict[str, Any]]) -> None:
    """Fill the viewer-required table fields so an import can never crash.

    ``tableData.columnWidths`` is **required** by the viewer: when it is
    missing the renderer throws and the session webview disconnects, after
    which the following ``pptx_save`` reports only ``session webview is not
    connected`` (see ``docs/pptx-viewer-mcp-change-requests.md`` #9). We always
    emit it, defaulting to equal columns sized to the widest row, and default
    ``firstRowHeader`` so the record matches the round-trip export shape.
    """
    for slide in slides:
        for element in slide.get("elements") or []:
            if not isinstance(element, dict) or element.get("type") != "table":
                continue
            table = element.get("tableData")
            if not isinstance(table, dict):
                continue
            widths = table.get("columnWidths")
            if not isinstance(widths, list) or not widths:
                columns = _table_column_count(table)
                if columns:
                    table["columnWidths"] = [1.0 / columns] * columns
            table.setdefault("firstRowHeader", False)


def _count_assets(slides: list[dict[str, Any]]) -> dict[str, int]:
    """Best-effort asset accounting (base64 data URLs) for the envelope."""

    count = 0
    total_bytes = 0

    def visit(value: Any, key: str | None = None) -> None:
        nonlocal count, total_bytes
        if isinstance(value, str):
            if key in {"imageData", "backgroundImage"} and value.startswith("data:"):
                count += 1
                _, _, payload = value.partition(",")
                total_bytes += (len(payload) * 3) // 4
            return
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    for slide in slides:
        visit(slide)
    return {"count": count, "totalBytes": total_bytes}


def _validate_table(element: Mapping[str, Any], index: int, element_index: int) -> None:
    """Reject a table the viewer cannot parse.

    The viewer needs ``tableData.columnWidths``; without it the render is not a
    soft failure but a webview crash, so we fail fast here instead (mirroring
    the ``pptx-viewer`` requirement per ``parsePptxJsonDocument``).
    """
    table = element.get("tableData")
    if not isinstance(table, dict):
        raise DocumentError(
            f'slide {index} element {element_index} table is missing "tableData"'
        )
    widths = table.get("columnWidths")
    if _table_column_count(table) and not (isinstance(widths, list) and widths):
        raise DocumentError(
            f'slide {index} element {element_index} "tableData" is missing "columnWidths"'
            " (the viewer requires it; a table without it crashes the import)"
        )


def validate(document: Any) -> None:
    """Validate a parsed document; raise :class:`DocumentError` on failure."""
    if not _is_record(document):
        raise DocumentError("expected a JSON object at the top level")
    if document.get("format") != FORMAT:
        raise DocumentError(f'missing format marker "{FORMAT}"')
    if document.get("version") != VERSION:
        raise DocumentError(
            f"unsupported version {document.get('version')!r}; this build supports {VERSION}"
        )
    presentation = document.get("presentation")
    if not _is_record(presentation):
        raise DocumentError('"presentation" must be an object')
    slides = document.get("slides")
    if not isinstance(slides, list):
        raise DocumentError('"slides" must be an array')
    for index, slide in enumerate(slides):
        if not _is_record(slide):
            raise DocumentError(f"slide {index} is not an object")
        elements = slide.get("elements")
        if elements is not None and not isinstance(elements, list):
            raise DocumentError(f'slide {index} "elements" must be an array')
        for element_index, element in enumerate(elements or []):
            if not _is_record(element):
                raise DocumentError(f"slide {index} element {element_index} is not an object")
            element_type = element.get("type")
            if not isinstance(element_type, str) or not element_type:
                raise DocumentError(
                    f"slide {index} element {element_index} must carry a non-empty string \"type\""
                )
            if element_type == "table":
                _validate_table(element, index, element_index)
    declared = document.get("slideCount")
    if isinstance(declared, int) and declared != len(slides):
        raise DocumentError(
            f"slideCount {declared} does not match {len(slides)} slides"
        )


def dumps(document: Mapping[str, Any], *, pretty: bool = True) -> str:
    """Serialize a document to text (validating first)."""
    validate(document)
    if pretty:
        return json.dumps(document, ensure_ascii=False, indent=2)
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def dump(document: Mapping[str, Any], path: str | Path, *, pretty: bool = True) -> Path:
    """Write a document to ``path`` as UTF-8 text."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps(document, pretty=pretty), encoding="utf-8")
    return target


def loads(text: str) -> dict[str, Any]:
    """Parse and validate document text."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise DocumentError(f"not valid JSON: {error}") from error
    validate(parsed)
    return parsed


def load(path: str | Path) -> dict[str, Any]:
    """Read, parse, and validate a document from ``path``."""
    return loads(Path(path).read_text(encoding="utf-8"))
