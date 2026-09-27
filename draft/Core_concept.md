# Deck Page Description Schema

Status: **investigated (2026-09-27)**. This document defines how one deck page is
described as data, how a page is authored as a JSON file, how it is turned into a
real slide, and what the hard constraints are. It is the contract the
`tf-ppt-master` skill's page-generation loop is built on.

<br />

## 1. TL;DR — decisions

1. **One page = one JSON file.** The page-generation loop authoring unit is a
   single slide record written to `pages/NN-slug.json`. This is the recovery
   checkpoint: if the agent session dies, only that page's file is re-edited and
   the deck is re-assembled.
2. **A single JSON file IS sufficient** to generate a deck page — *provided* two
   authoring shorthands are used for assets:
   - `image` → the local file must be inlined as a base64 `imageData` data URL
     (the importer ignores a bare `path`).
   - `svg` → the SVG must be converted to **native DrawingML** (not rasterized)
     by the scripts under `skills/tf-ppt-master/scripts/`.
   Both are handled automatically by the new assembler
   `scripts/pptx_json/page_build.py` (§6), so the page file itself stays small
   and human/agent-readable.
3. **Import is idempotent** (`import_from_json` with `mode:"replace"`), so the
   loop is: write/repair one page file → assemble → replace-import → render →
   check → next page. No slide is ever duplicated.
4. **Never hand-write base64 or raw SVG geometry** in a page file. Use the
   `image`/`svg` shorthand; the assembler resolves them.

<br />

## 2. The pipeline

```
deck_plan.md                (outline: one entry per page)
      │
      ▼  agent authors one file per page
pages/01-cover.json
pages/02-agenda.json         (bare slide records; image/svg shorthands)
pages/03-....json
      │
      ▼  assemble + resolve shorthands (offline, deterministic)
python -m pptx_json.page_build pages deck.build.json
      │
      ▼  import (replaces the whole deck; idempotent)
pptx_run_tool import_from_json { path: deck.build.json, mode: "replace" }
      │
      ▼  render one slide, inspect, iterate
pptx_render_slide  →  fix the failing page file  →  re-assemble  →  re-import
      │
      ▼
pptx_save
```

Why files instead of inline JSON: a long PPT build is many tool calls; an agent
session can fail mid-way. With one file per page, the build is resumable and each
page is independently reviewable/diffable. The assembled `deck.build.json` is a
derived artifact — it can be deleted and regenerated at any time.

<br />

## 3. Deck document schema (`pptx-viewer-json`, version 1)

Assembled output / `import_from_json` input:

```jsonc
{
  "format": "pptx-viewer-json",   // required, literal
  "version": 1,                   // required
  "slideCount": 3,                // required
  "presentation": {               // optional
    "width": 1280,                // px @ 96 dpi
    "height": 720
  },
  "generator": "ppt-master-plus", // optional
  "createdAt": "2026-09-27T...",  // optional
  "slides": [ /* Slide[] */ ]     // required
}
```

Do not call a `set_canvas_size` tool; the canvas is `presentation.width/height`.

<br />

## 4. Slide schema

```jsonc
{
  "name": "Cover",                 // slide name (NOT "title")
  "backgroundColor": "#0B1220",    // optional, solid hex
  "elements": [ /* Element[] */ ], // required (may be empty)
  "notes": "speaker notes",        // optional

  // Authoring-only sidecar: folded into equation elements on import, then removed.
  "equations": [
    { "latex": "\\frac{a}{b}", "equationNumber": "(1)",
      "x": 100, "y": 200, "width": 400, "height": 80,
      "fontSize": 24, "fontColor": "#FFFFFF" }
  ]
}
```

Canonical slide fields are also accepted for backgrounds (`backgroundImage`,
`backgroundGradient`, `backgroundPattern`), transitions/animations, comments,
`hidden`, `sectionName`, etc. **Any slide key outside the canonical set is
reported in the import `notes` under `scope:"slide"` / `ignoredFields`** — always
check for that.

<br />

## 5. Element schema

### 5.1 Common fields (all elements)

| field | type | notes |
|---|---|---|
| `type` | string | **required**, the discriminant |
| `id` | string | optional — minted if missing |
| `x`,`y`,`width`,`height` | number | px @ 96 dpi |
| `rotation` | number | degrees |
| `flipHorizontal`,`flipVertical` | bool | |
| `opacity` | number | 0..1 |
| `hidden` | bool | |
| `name` | string | non-visual name |

### 5.2 Element types

| `type` | content fields | notes |
|---|---|---|
| `text` | `text` **or** `textSegments:[{text, style}]`; `textStyle` | plain text box |
| `shape` | `shapeType` (`rect`,`roundRect`,`ellipse`,…); `shapeStyle`; optional custom geometry (`pathData`,`pathWidth`,`pathHeight`); optional text | |
| `connector` | `shapeStyle.connectorStartArrow`/`connectorEndArrow` | flat `startArrow`/`endArrow` also folded |
| `image` / `picture` | `imageData` (base64 data URL) | **content requires `imageData`**; a bare `path`/`src`/`file` is ignored |
| `table` | `tableData` | see §5.4 |
| `chart` | `chartData` | |
| `group` | `children:[Element]` | children are positioned in slide? no — local/window coords |
| `equation` | `latex` (+ `equationNumber`,`fontSize`,`fontColor`) | **authoring-only**; folded into a `shape` named `Equation`. Not a canonical type. |

Rarely authored: `media`, `ole`, `zoom`, `ink`, `unknown`.

### 5.3 Style objects

```jsonc
// text style
"textStyle": { "fontSize": 36, "fontFamily": "Inter", "color": "#FFFFFF",
               "bold": true, "italic": false, "underline": false, "align": "left" }

// shape style
"shapeStyle": { "fillColor": "#00AA55", "strokeColor": "#1E293B",
                "strokeWidth": 1,
                "connectorStartArrow": "triangle", "connectorEndArrow": "triangle" }
```

### 5.4 Table

```jsonc
{
  "type": "table",
  "tableData": {
    "rows": [
      { "height": 40, "cells": [ { "text": "Name" }, { "text": "Score" } ] },
      { "height": 40, "cells": [ { "text": "Alice" }, { "text": "95" } ] }
    ],
    "columnWidths": [0.5, 0.5],   // fractions, length MUST equal column count, all > 0
    "firstRowHeader": true
  }
}
```

<br />

## 6. Authoring vocabulary (flat aliases) — what the importer folds

`import_from_json` runs a tolerant normalizer that folds the *task-level* flat
vocabulary (the same vocabulary as `add_element`) into the canonical model. These
flat keys are therefore **valid in a page file**:

| flat key(s) | folds into |
|---|---|
| `fontSize`, `fontFamily`, `bold`, `italic`, `underline` | `textStyle.*` |
| `fontColor` | `textStyle.color` |
| `alignment` | `textStyle.align` |
| `fillColor`, `strokeColor`, `strokeWidth` | `shapeStyle.*` |
| `startArrow`, `endArrow` | `shapeStyle.connectorStartArrow`/`connectorEndArrow` |
| `rows`, `columns`, `cellData` (matrix), `headerRow` | `tableData` |

If an element has `text`/`textSegments`, the flat text keys are also written into
the first text segment's `style`.

Reserved authoring `type`s / shorthands handled by our assembler (not the
importer):

| shorthand | result |
|---|---|
| `{"type":"image","path":"assets/x.png",...}` | reads the file → `imageData` data URL |
| `{"type":"svg","path":"icons/x.svg","x","y","width","height","color"?,"fit"?,"keep_aspect"?,"as"?}` | SVG → native DrawingML: a `group` (`as:"group"`, default) or the flat element list (`as:"flat"`); `color` resolves `currentColor` |

<br />

## 7. Hard constraints & gotchas (all verified)

1. **SVG must become DrawingML.** An SVG dropped in as an `<image>` is not
   editable and does not carry native geometry. Convert it through
   `scripts/pptx_json/svg_insert.py` → `svg_model.py` (`svg_to_slide`). The
   assembler does this for `type:"svg"`.
2. **`currentColor` must be resolved before conversion.** Pass `color`
   (`svg_insert`'s `current_color`) or the icon renders with no fill. Verified:
   the `chunk-filled` knight takes the requested `#38BDF8`.
3. **Custom-geometry shapes need three fields together.** The renderer
   (`packages/react/src/viewer/utils/vector-shape-renderer.tsx`) requires
   `pathData` **and** `pathWidth` **and** `pathHeight`; without them a path shape
   renders as a plain rectangle. `svg_model` now emits all three.
4. **Images need `imageData`.** `import_from_json` silently drops a bare `path`
   (`ignoredFields:["path"]`). The assembler inlines the file as a data URL
   (`data:<mime>;base64,…`), supporting png/jpg/jpeg/gif/webp/bmp/svg.
5. **Import path must be inside an allowed PPTX root.** `/tmp` is rejected with
   `Path is outside the allowed PPTX roots`. Put `pages/` and `deck.build.json`
   inside the project/deck directory.
6. **`import_from_json` takes the document inline** as `json`; the `pptx_run_tool`
   wrapper additionally accepts `args.path` (used above) so large embedded images
   never have to be pasted through the agent. Prefer `path`.
7. **Equations use literal LaTeX.** `latex:"\\frac{1}{2}"` works; `\boldsymbol`
   is unsupported; unicode math must be converted to LaTeX. An equation is folded
   into a `shape` named `Equation`, so it does not round-trip as `type:"equation"`.
8. **Tables need a usable `columnWidths`.** If it is missing or mismatched, the
   importer backfills equal shares; `firstRowHeader` defaults to `false`. Always
   set both explicitly.
9. **Always read the import `notes`.** `ignoredFields` must be empty. Anything
   listed is a typo/unsupported key that was silently dropped — fix the page file
   and re-import.
10. **Slide names use `name`, not `title`.** A slide-level `title` is reported as
    an ignored slide field.
11. **Gradient stop positions** are 0..100 in the canonical model; authoring 0..1
    fractions are auto-normalized.

<br />

## 8. Per-page authoring recipe

1. Write `pages/NN-slug.json` (a bare slide record, or a full document, or an
   array of slides):

   ```jsonc
   {
     "name": "Agenda",
     "backgroundColor": "#0B1220",
     "elements": [
       { "type": "text", "id": "title",
         "x": 80, "y": 56, "width": 1000, "height": 80,
         "text": "Agenda", "fontSize": 44, "fontColor": "#FFFFFF",
         "bold": true, "alignment": "left" },
       { "type": "svg", "id": "icon",
         "path": "assets/knight.svg",
         "x": 980, "y": 220, "width": 120, "height": 120,
         "color": "#38BDF8" },
       { "type": "image", "id": "logo",
         "path": "assets/badge.png",
         "x": 140, "y": 260, "width": 220, "height": 220 }
     ]
   }
   ```
   Asset `path`s are resolved relative to the pages directory (or a base dir).
2. Assemble: `python -m pptx_json.page_build <pages_dir> <out.json>
   [--width 1280] [--height 720] [--current-color …]`.
3. Import: `pptx_run_tool import_from_json { path: <out.json>, mode: "replace" }`.
4. Render the page (`pptx_render_slide`) and inspect; on a defect, edit only that
   page file and repeat 2–4.
5. `pptx_save` when the deck is complete.

<br />

## 9. Open questions / follow-ups

- **`edit` workflow parity**: decide whether per-page files are the source of
  truth for edits too (re-assemble + replace) or whether targeted MCP edits are
  used and files re-exported via `export_to_json`.
- **`deck_plan.md` contract**: fix the exact outline fields (page id, slug,
  intent, style tokens, assets) the page generator consumes.
- **Determinism**: `page_build` currently relies on `document.build_document`;
  confirm byte-stable output when `createdAt` is omitted.
- **Lint/type**: the repo has no configured Python type-check command for
  `scripts/`; LSP diagnostics on `page_build.py` were observed to be stale. Add a
  `ruff`/`pyright` target if we want CI coverage for the scripts.
- **SVG coverage**: `svg_model` handles the shapes used by our icon sets; confirm
  coverage for gradients/filters/masks before promising arbitrary SVG import.
