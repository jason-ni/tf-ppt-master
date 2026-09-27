"""Assemble per-page JSON files into one importable ``pptx-viewer-json`` deck.

The TF-PPT Master build loop authors each deck page as its own file under a
``pages/`` directory and then assembles them into a single document for an
idempotent ``import_from_json`` (``mode: "replace"``). Keeping one file per page
means a failed agent session can resume by fixing that page's file and
re-importing — nothing is lost and no slide is duplicated.

A page file is either:

- a bare slide record ``{"elements": [...], "backgroundColor"?, "notes"?}``, or
- a full ``pptx-viewer-json`` document ``{"format": ..., "slides": [...]}``, or
- a JSON array of slide records.

The assembler resolves two authoring shorthands so the agent never hand-writes
base64 or raw SVG geometry:

- ``{"type": "image", "path": "assets/pic.png", ...}`` — the local file is read
  and inlined as ``imageData`` (``import_from_json`` ignores ``path``).
- ``{"type": "svg", "path": "icons/knight.svg", "x":, "y":, "width":, "height":,
  "color"?, "fit"?, "keep_aspect"?, "as"?}`` — the SVG is converted to native
  DrawingML by :mod:`pptx_json.svg_insert` (``as: "group"`` default, or
  ``"flat"`` for the raw element list). ``color`` resolves ``currentColor``.

Usage::

    python -m pptx_json.page_build <pages_dir> <out.json> [--width 1280] [--height 720]
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any, Iterable

from . import svg_insert
from .document import build_document, dumps

__all__ = [
    "resolve_element",
    "resolve_slide",
    "assemble_document",
    "assemble_pages",
    "load_pages",
]

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def _resolve_asset(value: str, base_dirs: Iterable[Path]) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        if candidate.exists():
            return candidate
        raise FileNotFoundError(value)
    for directory in base_dirs:
        resolved = (directory / candidate).resolve()
        if resolved.exists():
            return resolved
    looked = ", ".join(str(d) for d in base_dirs)
    raise FileNotFoundError(f"asset not found: {value} (looked in {looked})")


def _image_data(path: Path) -> str:
    mime = _MIME.get(path.suffix.lower())
    if mime is None:
        raise ValueError(f"unsupported image type: {path.suffix} ({path})")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def resolve_element(
    element: dict[str, Any],
    *,
    canvas_w: float,
    canvas_h: float,
    base_dirs: list[Path],
    current_color: str | None = None,
) -> list[dict[str, Any]]:
    """Expand one authoring element into canonical element(s)."""
    kind = element.get("type")

    if kind == "svg":
        source = element.get("path") or element.get("file") or element.get("svg")
        if not source:
            raise ValueError("svg element needs a 'path'/'file'")
        svg_path = _resolve_asset(str(source), base_dirs)
        svg_text = svg_path.read_text(encoding="utf-8")
        view_box = svg_insert.read_view_box_text(svg_text)
        color = element.get("color") or element.get("currentColor") or current_color
        x = float(element.get("x", 0.0))
        y = float(element.get("y", 0.0))
        width = float(element["width"])
        height = float(element["height"])
        fit = str(element.get("fit", "contain"))
        keep_aspect = bool(element.get("keep_aspect", False))
        if element.get("as", "group") == "flat":
            return svg_insert.positioned_elements(
                svg_text,
                view_box,
                x=x,
                y=y,
                w=width,
                h=height,
                canvas_w=canvas_w,
                canvas_h=canvas_h,
                fit=fit,
                keep_aspect=keep_aspect,
                base_dir=svg_path.parent,
                current_color=color,
            )
        group = svg_insert.group_element(
            svg_text,
            view_box,
            x=x,
            y=y,
            w=width,
            h=height,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            fit=fit,
            keep_aspect=keep_aspect,
            base_dir=svg_path.parent,
            current_color=color,
            name=element.get("name"),
        )
        if element.get("id"):
            group["id"] = element["id"]
        return [group]

    if kind == "group":
        out = {k: v for k, v in element.items() if k != "children"}
        children: list[dict[str, Any]] = []
        for child in element.get("children", []):
            children.extend(
                resolve_element(
                    child,
                    canvas_w=canvas_w,
                    canvas_h=canvas_h,
                    base_dirs=base_dirs,
                    current_color=current_color,
                )
            )
        out["children"] = children
        return [out]

    if kind == "image":
        out = {k: v for k, v in element.items() if k not in ("path", "src", "file")}
        if "imageData" not in out:
            source = element.get("path") or element.get("src") or element.get("file")
            if not source:
                raise ValueError("image element needs 'imageData' or a 'path'/'src'/'file'")
            out["imageData"] = _image_data(_resolve_asset(str(source), base_dirs))
        return [out]

    return [dict(element)]


def resolve_slide(
    slide: dict[str, Any],
    *,
    canvas_w: float,
    canvas_h: float,
    base_dirs: list[Path],
    current_color: str | None = None,
) -> dict[str, Any]:
    """Expand a slide record's shorthand elements into canonical elements."""
    out = {k: v for k, v in slide.items() if k != "elements"}
    elements: list[dict[str, Any]] = []
    for element in slide.get("elements", []) or []:
        elements.extend(
            resolve_element(
                element,
                canvas_w=canvas_w,
                canvas_h=canvas_h,
                base_dirs=base_dirs,
                current_color=current_color,
            )
        )
    out["elements"] = elements
    return out


def assemble_pages(
    pages: Iterable[dict[str, Any]],
    *,
    canvas_w: float = 1280.0,
    canvas_h: float = 720.0,
    base_dirs: list[Path] | None = None,
    current_color: str | None = None,
) -> list[dict[str, Any]]:
    """Resolve each page record to a canonical slide record."""
    dirs = list(base_dirs or [])
    return [
        resolve_slide(
            page,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            base_dirs=dirs,
            current_color=current_color,
        )
        for page in pages
    ]


def assemble_document(
    pages: Iterable[dict[str, Any]],
    *,
    canvas_w: float = 1280.0,
    canvas_h: float = 720.0,
    base_dirs: list[Path] | None = None,
    generator: str = "ppt-master-plus",
    current_color: str | None = None,
) -> dict[str, Any]:
    """Resolve pages and wrap them in a validated deck document."""
    slides = assemble_pages(
        pages,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        base_dirs=base_dirs,
        current_color=current_color,
    )
    return build_document(
        slides, width=int(canvas_w), height=int(canvas_h), generator=generator
    )


def _pages_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [page for page in value]
    if isinstance(value, dict):
        if isinstance(value.get("slides"), list):
            return list(value["slides"])
        return [value]
    raise ValueError("page file must be a slide object, an array, or a document")


def load_pages(pages_dir: str | Path, pattern: str = "*.json") -> list[dict[str, Any]]:
    """Load every page file under ``pages_dir`` (sorted by filename)."""
    directory = Path(pages_dir)
    pages: list[dict[str, Any]] = []
    for path in sorted(directory.glob(pattern)):
        value = json.loads(path.read_text(encoding="utf-8"))
        pages.extend(_pages_from_value(value))
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble pages/*.json into one deck JSON")
    parser.add_argument("pages_dir", help="directory holding one JSON file per page")
    parser.add_argument("out", help="output deck JSON path")
    parser.add_argument("--width", type=float, default=1280.0)
    parser.add_argument("--height", type=float, default=720.0)
    parser.add_argument("--pattern", default="*.json")
    parser.add_argument("--generator", default="ppt-master-plus")
    parser.add_argument(
        "--current-color",
        default=None,
        help="default color used to resolve SVG currentColor",
    )
    args = parser.parse_args(argv)

    pages_dir = Path(args.pages_dir)
    pages = load_pages(pages_dir, pattern=args.pattern)
    if not pages:
        parser.error(f"no pages matched {args.pattern} under {pages_dir}")
    document = assemble_document(
        pages,
        canvas_w=args.width,
        canvas_h=args.height,
        base_dirs=[pages_dir],
        generator=args.generator,
        current_color=args.current_color,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(document), encoding="utf-8")
    print(f"assembled {len(document['slides'])} page(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
