"""Unit conversions for native (``pptx-viewer-json``) authoring.

The native authoring medium is CSS pixels at 96 dpi, the same unit the
``tf-assistant-pptx`` MCP tools speak for element geometry and the same unit
``import_from_json`` converts to EMU at :data:`EMU_PER_PX`. A page authored on
the project ``viewBox`` therefore needs no scaling.

``set_canvas_size`` is the one exception: it multiplies its argument by
:data:`EMU_PER_PT` (12700) rather than :data:`EMU_PER_PX` (9525), i.e. it reads
points. Never call it on a loaded deck -- set the canvas from the document's
``presentation.width``/``height`` instead (upstream issue U1).
"""

from __future__ import annotations

EMU_PER_INCH = 914400
EMU_PER_PT = 12700
EMU_PER_PX = 9525

PX_PER_INCH = 96.0
PT_PER_INCH = 72.0

PX_PER_PT = PX_PER_INCH / PT_PER_INCH
PT_PER_PX = PT_PER_INCH / PX_PER_INCH


def px_to_emu(px: float) -> int:
    """Convert CSS pixels (96 dpi) to EMU, rounded to the nearest integer."""
    return int(round(px * EMU_PER_PX))


def emu_to_px(emu: float) -> float:
    """Convert EMU to CSS pixels (96 dpi)."""
    return emu / EMU_PER_PX


def pt_to_px(pt: float) -> float:
    """Convert points to CSS pixels (96 dpi)."""
    return pt * PX_PER_PT


def px_to_pt(px: float) -> float:
    """Convert CSS pixels (96 dpi) to points."""
    return px * PT_PER_PX
