"""Canvas (slide-size) helpers for native (``pptx-viewer-json``) authoring.

Native decks are authored at the project ``viewBox`` size in CSS px at 96 dpi;
``import_from_json`` maps that to EMU through :func:`pptx_json.units.px_to_emu`.
This module is the single place that turns a canvas into the EMU a saved deck
must carry, and the verifier that asserts a saved ``.pptx`` actually has it::

    expected = canvas_emu(1280, 720)          # (12192000, 6858000)
    assert_deck_canvas(deck_path, 1280, 720)  # raises DocumentError on mismatch

Never call ``set_canvas_size`` to set the canvas -- it scales by ``EMU_PER_PT``
(12700) rather than ``EMU_PER_PX`` (9525), i.e. it reads points and misframes a
px-authored deck. Set ``presentation.width`` / ``height`` instead (issue U1).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .document import DocumentError
from .units import px_to_emu

_PRESENTATION_XML = "ppt/presentation.xml"
_SLD_SZ_TAG_RE = re.compile(r"<p:sldSz\b[^>]*>")
_ATTR_RE = re.compile(r'([A-Za-z_][\w.-]*)="([^"]*)"')


def canvas_emu(width: float, height: float) -> tuple[int, int]:
    """The ``sldSz`` EMU a deck authored at ``width`` x ``height`` px must carry."""
    return (px_to_emu(width), px_to_emu(height))


def read_deck_canvas(deck_path: str | Path) -> tuple[int, int]:
    """Read the ``(cx, cy)`` EMU of a saved ``.pptx``'s ``p:sldSz``.

    Raises :class:`DocumentError` when the file is not a readable OOXML package
    or carries no ``p:sldSz``.
    """
    path = Path(deck_path)
    try:
        with zipfile.ZipFile(path) as archive:
            presentation = archive.read(_PRESENTATION_XML).decode("utf-8")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise DocumentError(f"cannot read {_PRESENTATION_XML} from {path}: {error}") from error

    tag = _SLD_SZ_TAG_RE.search(presentation)
    if tag is None:
        raise DocumentError(f"{path} has no <p:sldSz> in {_PRESENTATION_XML}")
    attributes = dict(_ATTR_RE.findall(tag.group(0)))
    cx, cy = attributes.get("cx"), attributes.get("cy")
    if cx is None or cy is None or not cx.isdigit() or not cy.isdigit():
        raise DocumentError(f"{path} <p:sldSz> has no numeric cx/cy: {tag.group(0)!r}")
    return (int(cx), int(cy))


def assert_deck_canvas(
    deck_path: str | Path, width: float, height: float
) -> tuple[int, int]:
    """Assert a saved deck's ``sldSz`` equals ``canvas_emu(width, height)``.

    Returns the observed ``(cx, cy)`` on success; raises :class:`DocumentError`
    naming the expected and observed EMU on mismatch (the canvas was almost
    certainly set with ``set_canvas_size`` rather than the document).
    """
    expected = canvas_emu(width, height)
    observed = read_deck_canvas(deck_path)
    if observed != expected:
        raise DocumentError(
            f"{deck_path} canvas is cx={observed[0]} cy={observed[1]} EMU, "
            f"expected cx={expected[0]} cy={expected[1]} for {int(width)}x{int(height)} px; "
            "set the canvas via presentation.width/height, never set_canvas_size"
        )
    return observed
