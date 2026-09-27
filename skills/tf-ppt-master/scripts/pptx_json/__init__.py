"""PPT Master Plus — `pptx-viewer-json` bridge helpers.

Pure-Python substrate shared by the read, native-edit, and export paths that
talk to the ``tf-assistant-pptx`` MCP. Nothing here imports ``python-pptx``,
``PIL``, or the ``pptx-viewer`` JavaScript packages; it only builds, validates,
and reads the portable ``pptx-viewer-json`` document format (version 1).

Public modules:
    - :mod:`pptx_json.document` — envelope build / validate / (de)serialize
    - :mod:`pptx_json.xml_to_obj` — OOXML text -> ``XmlObject`` dialect
    - :mod:`pptx_json.model` — light dataclasses for building slides/elements
    - :mod:`pptx_json.read_export` — parse an ``export_to_json`` result
    - :mod:`pptx_json.units` — px @96dpi <-> pt / EMU
    - :mod:`pptx_json.canvas` — canvas EMU + saved-deck ``sldSz`` assertion
"""

from .canvas import assert_deck_canvas, canvas_emu, read_deck_canvas
from .document import (
    FORMAT,
    VERSION,
    DocumentError,
    build_document,
    dump,
    dumps,
    load,
    loads,
    validate,
)

__all__ = [
    "FORMAT",
    "VERSION",
    "DocumentError",
    "build_document",
    "validate",
    "dumps",
    "dump",
    "loads",
    "load",
    "canvas_emu",
    "read_deck_canvas",
    "assert_deck_canvas",
]
