# TF-PPT Master — Generate Workflow

Three-phase pipeline: P-L (Plan) → D (Do) → C (Check).

---

## Phase P-L: Plan (Steps 1–3)

### Step 1 — Source Content

**Input forms**:
- Topic-only (e.g. "介绍一下 XX 产品")
- User-provided material (text, files, docs)
- Combination of both

For topic-only: generate a content brief (5–8 key points organized by narrative mode)
and present to user for confirmation before proceeding.

### Step 2 — Style & Preference Intake (MANDATORY ASK)

**Never infer the visual style silently.** Before planning, ask the user. Use the
`question` tool (fall back to plain text if unavailable) and offer concrete
options, not open questions:

1. **视觉风格** — 3–5 candidates read from `references/visual-styles/_index.md`,
   each with a one-line look description (e.g. dark-tech / swiss-minimal /
   editorial / glassmorphism). Always include a "你来定" option.
2. **品牌规范** — any brand from `templates/brands/`? If the user names a
   company/product, check for a matching brand spec and offer it.
3. **明暗基调** — dark / light / brand palette
4. **场景与受众** — occasion (keynote / internal report / sales pitch / teaching)
   and audience — this selects the narrative mode
5. **画布比例** — 16:9 / 4:3 / 1:1 (actual size is confirmed in Phase D step 2)
6. **语言** — zh / en / bilingual

Record the answers as locked design inputs for Step 3. If the user says
"随便/你决定", state the concrete choice explicitly in the Step 3 spec so the
user can still veto it — never leave style implicit.

### Step 3 — Slide Plan (`deck_plan.md`) & Review Gate

**MANDATORY, and the output is a real FILE — not a chat message.** Write
**`deck_plan.md`** into the deck folder (next to the `.pptx`). It is the single
source of truth for the Build loop and the only record that the deck's structure
is complete. If you never wrote the file to disk, you have not done this step.

Keep it **simple**, but it MUST open with a **source-structure map**, then the
page list. The map is what stops a whole sub-chapter (or its head page) from
being silently dropped:

```markdown
# <Deck title> — plan
canvas: ppt169 (1280×720) · style: <name> · palette: <hexes> · fonts: <names> · 16:9

## Source structure  ← map FIRST, then plan pages
Source = <N> chapters / <M> sections / <K> subsections:
- §1.1 <name>        → head page: yes
- §1.2 <name>        → head page: yes  (1.2.1/1.2.2/1.2.3 covered on P06–P07)
- ...
(Every chapter / section / subsection in the source appears here, each with an
explicit head-page decision. If the source has sections, the deck gets a head
page for each — or the reason it doesn't is written right here.)

## Pages
P01 | <title> | <carrier/layout> | <1-2 line key content>
P02 | <title> | <carrier/layout> | <1-2 line key content + images>
...
```

Each page line: `PNN | title | carrier/layout | key content & images`. One line
per page is enough (add a second line only when a page is image-heavy or needs
more than a sentence of copy).

**Consistency rule:** if the deck uses section head/dedicated divider pages at
all, it uses one for **every** section in the structure map — never just some.
(Chapter 1 with a lone §1.8 head page is the bug this rule prevents.)

**Hard gate — wait for explicit user approval ("确认"/"OK"/"go on") before Phase D.**
- **Write the file to disk FIRST and confirm it exists** (read it back / `ls` the
  deck folder). A plan that only lives in the chat does NOT satisfy this step.
- If the user edits a page, update `deck_plan.md` on disk and re-present it.
- Never silently change pages the user did not mention.
- Do not call any slide-creation tool (`add_slide`/`add_element`/`import_from_json`)
  until the plan is approved. `pptx_open`, `pptx_list_tools` and read-only discovery
  calls are always allowed.

**Planning references** (load on demand):
- `references/modes/_index.md` → pick communication mode
- `references/visual-styles/_index.md` → pick visual style
- `references/canvas-formats.md` → canvas size
- `references/shared-standards-core.md` → units, normative type ramp + floor, viewing-distance baseline
- `templates/brands/<brand>/templates/design_spec.md` → if user mentions a brand
- `templates/styles/<style>/templates/design_spec.md` → if a matching style exists

---

## Phase D: Build (Step 4)

### Step 4 — Build Loop (one page at a time)

**Core rule: build exactly ONE page → render it → validate it → then the next.
Never generate multiple pages ahead of validation.** This catches overflow,
clipping, off-canvas elements and broken images early, when they are cheap to fix.

Before the loop:
1. `pptx_open` to create/attach a session.
2. `pptx_list_tools` to discover tool schemas.
3. **Read the real canvas size — never hardcode it.** Call
   `get_presentation_properties` and use the returned `width`/`height` as the
   coordinate space W/H. The MCP schema labels units "points" but the viewer's
   space is its px (16:9 → 1280×720). A past bug: a stale EMU→"pt" conversion
   gave 1219.2×685.8 "pt"; backgrounds built on it left white slivers at the
   bottom/right of every slide.

Then, for **each page `PNN` in `deck_plan.md` order**, run this loop:

1. `add_slide`.
2. **First element is always a full-bleed background rect** at (0,0) sized W+4 ×
   H+4 (overshoot is harmless). It doubles as a canvas self-check: a white sliver
   at the bottom/right of a render = undersized background.
3. Add the page's elements per the plan line:
   - Text → `add_element` (type: `text`)
   - Shapes → `add_element` (type: `shape`)
   - Images/icons → `add_element` (type: `image`) with a **`path`** to the local
     file — the backend reads it and inlines `imageData` for you (see below).
     Size each image by its real aspect ratio (`sips -g pixelWidth -g pixelHeight`)
     so it is never distorted.
   - Equations (displayed formulas) → `add_equation` with **raw LaTeX** in
     `latex` (+ optional `equationNumber`, e.g. `"(4)"`) — renders a native,
     editable equation; do NOT pre-escape and never type a long formula as text
   - Charts → `create_chart`
   - Tables → `add_table` or `add_element` (type: `table`)

**Typography — every text element sets an explicit `fontSize` from the ramp.**
Never rely on the renderer default. Read the body anchor for the canvas + reading
mode from `references/canvas-formats.md`, then take the other roles from the
normative ramp in `references/shared-standards-core.md` §2. At `ppt169`
(1280×720), `presentation` mode that is: display 72 · title 52 · section 40 ·
subheading 34 · body 32 · caption 22 · label 18 (the `balanced` / `text` columns
and the hard floor are in that file). The rendered slide is the check: if the
body looks small, it is — raise the size, and cut or stack content rather than
shrinking a recurring role below the floor.

4. **Render this page**: `pptx_render_slide(target, slide_index=PNN-1,
   to_file=true, output_path=...)`.
5. **Validate the render by looking at the image**:
   - bottom/right edges fully covered by the background (no white sliver);
   - no text overflow, clipping, or wrapped past its box;
   - no element off-canvas; images present and correctly proportioned;
   - `detect_layout_issues` (act only on `text_overflow`/off-canvas; `overlap`
     warnings are expected because content sits on cards).
6. **If issues → fix (add/`update_element`) and re-render until clean.**
   Only then advance to `PNN+1`.

**Image insertion — pass a `path`, never inline base64.** For an `image` element,
set `"path"` to the local file (e.g. `"math3101/img/png/foo.png"`). The
`tf-assistant-pptx` transport reads the file, base64-encodes it, and injects
`imageData`; the viewer only ever sees `imageData`. Do **not** hand-type base64 or
use `src`. The path must resolve inside an allowed root (your chat/workspace dir is
in scope — `/tmp` usually is not). If `imageData` is present, `path` is ignored.

For a whole slide/paragraph of JSON, use `import_from_json` with `args.path`
(or `args.file`) pointing at a JSON file instead of inlining `json`. Full details:
`references/mcp-mapping.md` §Images & Large Payloads.

**MCP Tool Mapping** — see `references/mcp-mapping.md` for full mapping.

**Icon / SVG insertion** (see `references/mcp-mapping.md` §Icon / SVG Insertion):
1. Pick SVG from `templates/icons/<library>/<name>.svg` (or any SVG source)
2. Convert: `from pptx_json.svg_insert import group_element, read_view_box`
3. Insert: `pp

---

## Phase C: Final sweep (Step 5)

Each page is already render-validated in the build loop, so this step is a
whole-deck consistency pass, not a fresh build:

1. Render the full deck (or spot-check) → confirm page order, section dividers,
   and cross-slide consistency (headings, footer, colors all aligned).
2. **Hard check** on every slide: bottom & right edges fully covered by the
   background — any sliver = undersized rect, resize from
   `get_presentation_properties` and re-render.
3. Fix + re-render any residual issue via `add_element` / `update_element`.
4. `pptx_save`.
5. **Promote the session out of preview** (`pptx_promote_session`) so the user
   can edit it, then report the final .pptx path.

---

## Global Rules

- **Serial execution**: follow steps in order
- **Blocking at Step 1**: topic-only requires user approval of content brief before proceeding
- **Blocking at Step 2**: style/preference intake is a mandatory ask — never choose a style silently, even for a "simple" deck
- **Blocking after Step 3**: write `deck_plan.md` **to disk** (a source-structure map with a head-page decision per section + one simple line per page), confirm the file exists, then wait for explicit approval. If the deck has any section head page, every section in the map gets one.
- **Build loop (Step 4)**: one page at a time — `add_slide` → elements → `render` → validate → only then the next page. Never batch-generate pages ahead of validation.
- **No speculative execution**: don't create slides before the plan is approved
- **Images use a local file `path`** (the transport inlines `imageData` for you) — never hand-type base64, never a `src`; size each box to the image's real aspect ratio so it is never distorted
- **Re-review on change**: if the user edits a page after approval, update the plan and re-confirm before building
- **Canvas constants**: never hardcode — read `width`/`height` from
  `get_presentation_properties` at execution time (Phase D)
