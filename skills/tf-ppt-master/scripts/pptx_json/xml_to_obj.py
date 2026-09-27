"""Convert OOXML text into the ``pptx-viewer-json`` ``XmlObject`` dialect.

The dialect matches ``fast-xml-parser`` as configured by ``pptx-viewer``:

===============  =========================================================
OOXML                      dialect
===============  =========================================================
attributes       ``{"@_id": "5", "@_name": "X"}``
repeated child   list under one key: ``{"p:sp": [.., ..]}``
empty element    empty string: ``{"p:nvPr": ""}``
text-only node   the string: ``{"a:t": "Hello"}``
mixed node       ``{"@_w": "6350", "#text": "Hello"}``
namespaces       prefixes preserved verbatim (``p:``, ``a:``, ``r:``)
===============  =========================================================

Two entry points:

* :func:`xml_to_obj` returns the root wrapper ``{"p:sp": {...}}`` — the shape
  used by the slide-level ``rawXml``.
* :func:`xml_to_obj_node` returns the inner content ``{...}`` — the shape an
  **element** ``rawXml`` requires. Wrapping an element rawXml in its own tag
  produces ``<p:sp><p:sp>`` (invalid), so use this for elements.
"""

from __future__ import annotations

import io
from typing import Any, cast
from xml.etree import ElementTree as ET

__all__ = ["xml_to_obj", "xml_to_obj_node"]


def _prefixed(tag: str, ns_by_uri: dict[str, str]) -> str:
    if tag.startswith("{"):
        uri, _, local = tag[1:].partition("}")
        prefix = ns_by_uri.get(uri, "")
        return f"{prefix}:{local}" if prefix else local
    return tag


def _collect_namespaces(text: str) -> dict[str, str]:
    ns_by_uri: dict[str, str] = {}
    try:
        for _event, payload in ET.iterparse(io.StringIO(text), events=("start-ns",)):
            prefix, uri = cast("tuple[str, str]", payload)
            ns_by_uri.setdefault(uri, prefix or "")
    except ET.ParseError:
        pass
    return ns_by_uri


def _append_child(children: dict[str, Any], tag: str, content: Any) -> None:
    if tag in children:
        existing = children[tag]
        if isinstance(existing, list):
            existing.append(content)
        else:
            children[tag] = [existing, content]
    else:
        children[tag] = content


def _convert(elem: ET.Element, ns_by_uri: dict[str, str]) -> Any:
    attrs: dict[str, Any] = {
        f"@_{_prefixed(name, ns_by_uri)}": value for name, value in elem.attrib.items()
    }
    children: dict[str, Any] = {}
    for child in elem:
        _append_child(children, _prefixed(child.tag, ns_by_uri), _convert(child, ns_by_uri))

    text = elem.text or ""
    if children:
        content: dict[str, Any] = dict(attrs)
        content.update(children)
        if text:
            content["#text"] = text
        return content
    if attrs:
        content = dict(attrs)
        if text:
            content["#text"] = text
        return content
    return text


def _parse_root(text: str) -> tuple[str, Any]:
    ns_by_uri = _collect_namespaces(text)
    root = ET.fromstring(text)
    return _prefixed(root.tag, ns_by_uri), _convert(root, ns_by_uri)


def xml_to_obj(text: str) -> dict[str, Any]:
    """Parse OOXML text into ``{root_tag: content}`` (slide-level shape)."""
    tag, content = _parse_root(text)
    return {tag: content}


def xml_to_obj_node(text: str) -> Any:
    """Parse OOXML text into the root element's inner content (element shape)."""
    _tag, content = _parse_root(text)
    return content
