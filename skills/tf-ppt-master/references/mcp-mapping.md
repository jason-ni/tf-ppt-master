# MCP Tool Mapping Guide

Maps design concepts to MCP tool calls.

## Discovery

Always call `pptx_list_tools(target=<session>)` first to get the full tool catalog
with schemas. The tools below are the expected core set.

## Core Tools

| MCP Tool | Purpose | When to Use |
|----------|---------|-------------|
| `pptx_open` | Open/create a .pptx session | First call |
| `pptx_list_tools` | Discover available tools + schemas | After open, before authoring |
| `pptx_run_tool` | Execute any authoring tool | All authoring actions |
| `pptx_render_slide` | Render slide to image | Quality check |
| `pptx_save` | Flush to disk | Final step |
| `pptx_close_session` | Close session | Cleanup |

## Authoring Tools (discovered via pptx_list_tools)

| Tool Name | Maps To | Notes |
|-----------|---------|-------|
| `add_slide` | New slide | Call before adding elements |
| `add_element` | All visual objects | `type` param: text/shape/image/table/connector |
| `create_chart` | Chart visualization | Specify data + chart type |
| `add_table` | Data tables | Specify rows/cols/data |
| `apply_template` | Full-slide template | If a layout template matches |
| `find_placeholders` | Locate text placeholders | For template-based editing |
| `manage_sections` | Slide sections/grouping | Organization |
| `import_from_json` | Bulk slide import | For complex multi-element slides |
| `export_to_json` | Read current deck structure | Debugging |

## Element Types (`add_element.type`)

| Type | Key Params | Use For |
|------|-----------|---------|
| `text` | `text`, `field` (live field — see below), `font_size`, `font_color`, `bold`, `x`, `y`, `w`, `h` | Headings, body, labels |
| `shape` | `shape_type`, `fill`, `stroke`, `x`, `y`, `w`, `h` | Cards, bands, dividers, backgrounds |
| `image` | **`path`** (local file path — see §Images below), `x`, `y`, `w`, `h` | Icons, photos, diagrams |
| `table` | `rows`, `cols`, `data` (2D array) | Data tables |
| `connector` | `from_x`, `from_y`, `to_x`, `to_y` | Arrows, lines |

## Page Numbers — use a LIVE `field`, never literal text

`add_element` with `type: "text"` accepts a `field` param that inserts a **live OOXML
document field** instead of literal characters. The server writes a real `<a:fld>` run,
so the value is resolved at render time and **auto-renumbers** when slides are added,
removed or reordered.

```
pptx_run_tool(target, "add_element", {
  "slideIndex": N, "type": "text", "field": "slidenum",
  "x": 1190, "y": 690, "w": 50, "h": 20,
  "font_size": 12, "font_color": "#4A5A72", "alignment": "right"
})
```

- Supported `field` values: `slidenum` (page number), `slidetitle`, `datetime`, `header`, `footer`.
- `slidenum` is the correct way to number a slide. **Never hard-code the number as text**:
  literal text does not renumber, so any later insert/reorder leaves every number wrong,
  and the only repair is an OOXML XML patch (see `workflows/edit.md`).
- The cached text is seeded from the slide's current position; the renderer overrides it
  per slide at display time.

## Images & Large Payloads — Pass a FILE PATH, Never Inline Base64

The transport (`tf-assistant-pptx` MCP server, Rust `src-tauri/src/pptx/mcp.rs`)
reads files from disk and inlines them for you. **Never hand-type base64 into an
argument** — it is huge and burns the whole context window.

**Image elements — use `path`:**
```jsonc
// add_element (the top-level object is the element)
{ "slideIndex": 3, "type": "image", "path": "math3101/img/png/web_images_funnel-1.png",
  "x": 80, "y": 160, "width": 520, "height": 166 }
// add_elements (array under "elements") — path is resolved per image element too
```
The backend reads `path`, base64-encodes it, sets `imageData`, and strips `path`
before the viewer sees it. `path` may be absolute or relative; it must resolve
**inside an allowed root**. `.png/.jpg/.jpeg/.gif/.webp/.bmp/.svg/.pdf/.emf/.wmf`
are supported (mime inferred from extension). If `imageData` is already present,
`path` is ignored — so do not pass both.

**`import_from_json` — use `args.path` / `args.file`:**
```jsonc
// instead of {"json": "<tens of KB string>"}
{ "path": "deck/page07.json", "mode": "append" }   // "file" also accepted; mode: replace|append
```
The JSON file is read and inlined as `json` automatically. This is the way to
bulk-import complex slides without inlining their JSON.

> **Caveat — images still need `add_element`.** `import_from_json` inlines the
> *document file* but a `path` on an **image element inside that document is
> ignored** (the import reports it in `ignoredFields`). So: import the text/shape
> skeleton by file if you like, but add every image with `add_element`/
> `add_elements` (where `path` → `imageData` inlining does run).

**Also path-capable:** `update_slide_properties.backgroundImage` and
`replace_ole_file.fileData` take a file path the same way.

**Allowed roots** (`allowed_roots`): every registered repository root path, the
workspaces dir, the chats dir (`~/.local/share/tf-assistant/chats` or the
configured data dir), and the configured `data_dir`. A path outside these
throws *"resolves outside the allowed root"*. Files under your chat/workspace
directory are always in scope; `/tmp` usually is not.

**Getting image dimensions:** size a box to the image's real aspect ratio so it
is never distorted — `sips -g pixelWidth -g pixelHeight <file>` (macOS).

## Equations — use native LaTeX math, not plain text

Real maths should be a **native equation object**, not Unicode characters typed
into a text box. Two ways to make one:

```jsonc
// preferred: dedicated tool
// add_equation({ slideIndex, latex, x, y, width, height, fontSize, fontColor, equationNumber })
// or via add_element / add_elements with type "equation":
{ "type": "equation", "latex": "\\frac{\\partial \\rho}{\\partial t} + \\nabla \\cdot (\\rho \\mathbf{u}) = 0",
  "x": 120, "y": 260, "width": 700, "height": 90, "equationNumber": "(4)" }
```

* `latex` is the equation source in **LaTeX math notation** — pass it raw, do
  **NOT** pre-escape or wrap in `$…$`. Example:
  `\\frac{\\partial u}{\\partial t} + (u \\cdot \\nabla) u = -\\frac{1}{\\rho}\\nabla p + \\nu \\nabla^2 u`
* It renders as an **editable OMML equation** (Cambria Math), so the user can
  open and edit it in PowerPoint.
* `equationNumber` (e.g. `"(4)"`) renders the equation **centred with that number
  right-aligned** — use it for numbered displayed equations.
* `fontSize` (default 18) and `fontColor` control its size/colour.

**When to use which:** put *displayed* formulas in an equation element. For a
short symbol inside a sentence (e.g. "the vorticity ω = ∇ × u"), keep it in the
body text — equation elements are block-level, so they are positioned separately
rather than inline. Avoid writing long formulas as loose text.

**Gotchas:** `\boldsymbol{...}` is **not supported** — it makes the whole equation
degrade into a plain text shape that shows raw LaTeX. Use `\omega`, `\Gamma`,
`\mathbf{...}`, etc. instead. When replacing an equation, delete the old element
first (`delete_elements`) — a failed equation lives on as a `type:"shape"` whose
`text` is the LaTeX source. If a render shows literal backslashes, it was drawn
before the equation settled: re-render (`get_slide`'s markdown shows the correct
`$…$` math, which is the reliable check).

## Chart Types

From `templates/charts/` vocabulary. Common mappings:

| Chart Type | MCP `create_chart` Type |
|-----------------|------------------------|
| bar_chart | `bar` |
| line_chart | `line` |
| pie_chart | `pie` |
| area_chart | `area` |
| scatter | `scatter` |
| radar | `radar` |
| donut | `doughnut` |

## Canvas Sizing

**The session's real canvas is authoritative — read it before authoring:**

`pptx_run_tool(target=<session>, tool="get_presentation_properties")`
→ `{ "width": 1280, "height": 720 }` for a 16:9 deck created via `pptx_open`.

The MCP element schema labels x/y/w/h/fontSize as "points", but the viewer's
coordinate space is its **px** (16:9 = 1280×720). Never hardcode canvas
numbers from memory or from EMU conversions. Unit reference:

| Units | 16:9 slide |
|-------|-----------|
| EMU (python-pptx) | 12192000 × 6858000 (914400/inch) |
| points (72/in) | 960 × 540 |
| viewer px (what MCP x/y/w/h use) | 1280 × 720 (96/in) |

Every slide's first element must be a full-bleed background rect at (0,0)
sized `width+4 × height+4` from the call above.

## Icon / SVG Insertion

Use `pptx_json.svg_insert` to convert any SVG into native positioned elements:

```python
import sys
sys.path.insert(0, f"{SKILL_DIR}/scripts")
from pptx_json.svg_insert import group_element, read_view_box
from pathlib import Path

# 1. Read the SVG
svg_path = Path(f"{SKILL_DIR}/templates/icons/tabler-outline/rocket.svg")
svg_text = svg_path.read_text()
view_box = read_view_box(svg_path)

# 2. Convert to positioned group element (native shapes, not bitmap)
group = group_element(
    svg_text, view_box,
    x=100, y=200, w=64, h=64,   # placement in canvas coords
    canvas_w=1280, canvas_h=720, # matches session canvas
)

# 3. Insert via import_from_json
# pptx_run_tool(target, "import_from_json", {"json": [group], "mode": "append"})
```

**Available libraries** (under `templates/icons/`):
- `tabler-outline/` — 5000+ stroke icons, 24x24 viewBox
- `tabler-filled/` — 1000+ fill icons, 24x24 viewBox
- `phosphor-duotone/` — 1200+ duotone, 256x256 viewBox
- `chunk-filled/` — 640+ fill, 16x16 viewBox
- `simple-icons/` — 3400+ brand logos, 24x24 viewBox

**Other SVGs**: any SVG from `templates/`, user-provided files, or generated
content can be inserted the same way. The converter handles paths, rects,
circles, lines, polygons, text (stays editable), images (data URL), and
gradients.

## Theme / Colors

Colors from plan go directly into element params:
- `text.font_color` = `"#00E5FF"`
- `shape.fill` = `"#0B0F1A"`
- `shape.stroke` = `"#22D3EE"`

No separate theme application step needed.

## Quality Check Pattern

```
After each slide:
  pptx_render_slide(target=<session>, slide_index=N, to_file=true, output_path="/tmp/slide_N.png")
  → Inspect the PNG for overflow, overlap, missing content

If fix needed:
  pptx_run_tool(target=<session>, tool="add_element", args={...})  # or modify
  pptx_render_slide again

Final:
  pptx_save(target=<session>)
```

## Known Tool Gotchas (verified)

- **`delete_slides` applies immediately** (like `add_slide` / `reorder_slides`).
  It used to force approval and, under a host that discards staged proposals,
  silently no-op — that bug is **fixed in pptx-viewer** (`forceApproval` removed
  from the tool registry / `routeWrite`). If you are running an older viewer
  build it may still no-op: reload/restart the viewer. Fallback while stale: size
  the deck up-front and use `delete_elements` (which always applies) to clear an
  unwanted slide's content.
- **`import_from_json` ignores an image element's `path`** — it only adds
  text/shape elements. Add images with `add_element`/`add_elements` (which DO
  honour `path` and inline it). `import_from_json` *does* accept `path`/`file`
  for the JSON document itself (use it to keep big payloads out of the chat).
- **`detect_layout_issues` false positives** — a full-bleed background/nav rect
  sized `W+4 × H+4` at (0,0) is reported as `out_of_bounds` (expected; keep the
  overshoot). `overlap` warnings are expected because content sits on cards.
  Only act on `text_overflow` and genuine off-canvas elements.
- **Rendered PNGs show a bottom UI band** at ~86 % height — that is renderer
  chrome, identical on every slide, not a layout defect.
- **Equation elements**: if a render shows literal LaTeX (backslashes), the
  element was drawn before typesetting — just re-render. `\boldsymbol` is
  unsupported (degrades the whole equation into a shape) — use `\omega`,
  `\Gamma`, `\mathbf{}` instead.
