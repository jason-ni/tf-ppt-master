# TF PPT Master

Turn source material into **natively editable** PowerPoint decks (`.pptx`) whose
text, shapes, charts, tables, images and icons are real DrawingML objects — not
flattened images — so they stay editable in PowerPoint.

## What it does

Given a topic or source documents plus a set of design preferences, the project
plans a deck, builds it one page at a time, renders and checks each page, and
writes a fully editable `.pptx`. It ships as an agent **skill**
(`skills/tf-ppt-master/`) that drives the `tf-assistant-pptx` MCP service and the
`pptx-viewer` rendering/editing engine.

> **Use this skill together with
> [tf-assistant-app](https://github.com/jason-ni/tf-assistant-app)** — the
> companion app that hosts the `tf-assistant-pptx` MCP service this skill calls.

## Repository layout

```text
AGENTS.md                 # agent entry point — read this first
skills/tf-ppt-master/     # the skill (the product)
  SKILL.md                #   skill entry: architecture, hard gates, routing
  workflows/
    generate.md           #   Plan → Build (per-page) → Final sweep
    edit.md               #   edit an existing deck
  references/
    shared-standards-core.md  # units, normative type ramp, viewBox grammar
    canvas-formats.md         # canvas sizes + per-canvas body anchor
    mcp-mapping.md            # JSON schema ↔ MCP tool mapping
    modes/                    # 5 narrative modes
    visual-styles/            # 18 visual style definitions
  templates/
    brands/                   # 21 brand presets
    styles/                   # 14 style presets
    layouts/                  # 7 layout families (SVG prototypes)
    charts/                   # 35 chart SVG prototypes + vocabulary
    tables/                   # 6 table SVG prototypes + vocabulary
    icons/                    # 5 icon libraries
    scaffolds/                # design-spec / spec-lock scaffolds
  scripts/pptx_json/          # Python helpers (pure stdlib)
    page_build.py             #   assemble per-page JSON files into one deck
    svg_insert.py             #   place an SVG as native DrawingML
    svg_model.py              #   SVG → DrawingML element conversion
    document.py / canvas.py / model.py / units.py / ...
draft/                    # design notes (e.g. the deck-page schema)
openspec/                 # spec-driven change workflow
.opencode/                # editor/agent configuration for this repo
```

## Pipeline

1. **Plan** — ask the user for design preferences, then write `deck_plan.md`
   (a source-structure map plus one line per page) to disk and get it approved.
2. **Build** — create the slides **one page at a time**: add that page's
   elements, then render and validate it before moving on. Loop to the last page.
3. **Final sweep** — a full-deck render pass, save, and report the `.pptx` path.

Three gates are mandatory and blocking: the style intake, the on-disk
`deck_plan.md`, and the per-page build loop (never batch-generate ahead of
validation).

## Prerequisites

* [tf-assistant-app](https://github.com/jason-ni/tf-assistant-app) — the
  companion app this skill is designed to run with. It hosts the
  `tf-assistant-pptx` MCP service, which provides `pptx_open`, `pptx_list_tools`,
  `pptx_run_tool`, `pptx_render_slide`, `pptx_save`, `pptx_promote_session`, and
  the authoring tool catalog.
* Python 3 (the helpers under `skills/tf-ppt-master/scripts/pptx_json/` use the
  standard library only).

## Using it

Agents should start from [`AGENTS.md`](./AGENTS.md), which points at
[`skills/tf-ppt-master/SKILL.md`](./skills/tf-ppt-master/SKILL.md). From there,
routing selects `workflows/generate.md` for a new deck or `workflows/edit.md` to
modify an existing one.

## Development

This skill is tightly coupled with two sibling projects:

* **tf-assistant-app**
  ([github.com/jason-ni/tf-assistant-app](https://github.com/jason-ni/tf-assistant-app))
  — exposes the `tf-assistant-pptx` MCP service the skill calls.
* **pptx-viewer** — parses, renders and edits the underlying deck; owns the
  `pptx-viewer-json` document model and the DrawingML output.

Both may be modified when a behavior needs fixing at the source (for example,
"points vs px" unit normalization or how a JSON field is folded into a style
object).
