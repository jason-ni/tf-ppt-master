---
name: tf-ppt-master
description: AI-driven presentation workflow for generating editable PPTX decks and slides. Use when the user asks to create, generate, reconstruct, regenerate, beautify, redesign, template, fill, or enhance a presentation, PPT, PPTX, slide deck, or courseware.
---

# TF-PPT Master

AI-driven presentation workflow for generating editable PPTX decks and slides.

## Architecture

Three phases:

1. **Plan**—ask the user for design preferences, then write `deck_plan.md` to
   disk (a **source-structure map** with a head-page decision per section, then
   one short line per page) and get it approved.
2. **Build**—create the slides **one page at a time**: `add_slide` + `add_element`
   for that page, then **render and validate that page** with `render_slide`
   before moving on. Loop until the last page.
3. **Final sweep**—a full-deck render pass, `pptx_save`, report the .pptx path.

**Hard user gates — never skip any:**

* **Style gate (Step 2)**: you MUST ask the user which visual style / brand /
  palette / occasion / aspect ratio to use. Never pick a style silently, even
  for a "simple" deck; if the user says "你来定", state your choice in the spec.
* **Spec gate (Step 3)**: write `deck_plan.md` **to disk** — a source-structure
  map (every chapter/section/subsection, each with an explicit head-page
  decision) plus a simple per-page description (title, key content,
  carrier/images) and global design tokens — then wait for explicit approval
  before any slide is built. Confirm the file exists; a plan that lives only in
  the chat is not a plan, and a missing structure map is how whole sections get
  dropped.
* **Build gate (Step 4)**: never batch-generate the whole deck. Build page by
  page, rendering + validating each page with `render_slide` before advancing.

## Images & large payloads: pass a FILE PATH, never inline base64

The `tf-assistant-pptx` transport reads local files for you. Do **not** hand-type
base64 (it is enormous and floods the context):

* **Image element** → use `"path": "<local file>"` (not `imageData`, not `src`).
  The backend reads the file, base64-encodes it, and injects `imageData`.
  Note: this works through `add_element`/`add_elements` — **not** via
  `import_from_json`, which ignores an image element's `path`.
* **`import_from_json`** → use `args.path` (or `args.file`) pointing at a JSON
  file, instead of the inline `json` string.
* `update_slide_properties.backgroundImage` and `replace_ole_file.fileData` also
  accept file paths.

The path must resolve inside an allowed root (repository roots, the workspaces /
chats / data dirs — your chat directory qualifies; `/tmp` often does not).

## Equations: use native LaTeX, never type formulas as text

Mathematical formulas must be real equations, not Unicode characters in a text
box. Use `add_equation` (or `add_element` / `add_elements` with `type: "equation"`):

* `latex` is **raw LaTeX math** (e.g. `\frac{\partial \rho}{\partial t} +
  \nabla \cdot (\rho \mathbf{u}) = 0`) — do NOT pre-escape and do NOT wrap in `$…$`.
* It renders as an editable native equation (Cambria Math).
* `equationNumber` (e.g. `"(4)"`) centres the equation and right-aligns the number.
* Use it for any *displayed* formula; keep only short inline symbols (e.g. "ω = ∇ × u")
  in body text, since equation elements are block-level, not inline.
Details + examples: `references/mcp-mapping.md` §Images & Large Payloads.

## Asset Locations

| Path                                        | Content                                                         |
| ------------------------------------------- | --------------------------------------------------------------- |
| `${SKILL_DIR}/templates/brands/`            | 25+ brand design specs (colors, fonts, logos)                   |
| `${SKILL_DIR}/templates/styles/`            | 15 style templates (consulting, keynote, product-launch…)       |
| `${SKILL_DIR}/templates/icons/`             | 5 icon libraries (tabler, phosphor, chunk-filled, simple-icons) |
| `${SKILL_DIR}/templates/charts/`            | 33 chart types vocabulary                                       |
| `${SKILL_DIR}/templates/tables/`            | 6 table types vocabulary                                        |
| `${SKILL_DIR}/templates/layouts/`           | 8 layout templates                                              |
| `${SKILL_DIR}/references/modes/`            | 5 narrative modes (pyramid, narrative, showcase…)               |
| `${SKILL_DIR}/references/visual-styles/`    | 18+ visual style definitions                                    |
| `${SKILL_DIR}/references/canvas-formats.md` | Canvas size mappings                                            |

## Routing

| Intent                            | Workflow                |
| --------------------------------- | ----------------------- |
| Generate a new deck               | `workflows/generate.md` |
| Edit an existing deck (insert / delete / reorder pages, renumber, tweak) | `workflows/edit.md` |

Editing an existing deck is a distinct workflow — see `workflows/edit.md` for the
verified techniques (structural inserts, page-number renumbering via a surgical
XML edit, single-page content edits). **Trust the MCP tool schemas and their
`applied`/`saved` return flags — never depend on viewer source, which is not
available in a real deployment.**

## Prerequisites

* tf-ppt-master MCP must be running (provides `pptx_open`, `pptx_run_tool`, `pptx_render_slide`, etc.)
* User provides topic/content, or approves topic-research
* User answers the style/preference intake (Step 2) and approves `deck_plan.md`
  (Step 3) — both are blocking gates
