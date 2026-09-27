# Shared Standards — Core

Cross-cutting normative rules every workflow and binding consumes. Values are
unitless SVG px in the deck's canvas coordinate space (the viewer's px, 96/in).

## 1. Units & coordinate space

* All geometry — `x`/`y`/`width`/`height`, `fontSize`, stroke widths, radii — is
  SVG px in the **canvas coordinate space**. The MCP element schema labels these
  fields "points"; that label is a misnomer. A past bug treated a stale
  EMU→"pt" value (1219.2×685.8) as the canvas and left white slivers on every
  page.
* The canvas is `0 0 W H`; read the real `W`/`H` from
  `get_presentation_properties` at execution time and never hardcode them. See
  [`canvas-formats.md`](./canvas-formats.md) for the registered sizes.
* Every page in one deck shares one canvas.

## 2. Type ramp (normative)

**Every text element MUST carry an explicit `fontSize` chosen from this ramp.
Never rely on the renderer default** (the viewer falls back to 24 px, which is
correct only by accident and is not a design decision).

Pick the **body** size first — the body anchor for the canvas + reading mode in
[`canvas-formats.md`](./canvas-formats.md) §Typography — then take the other
roles from the table. At `ppt169` (1280×720):

| Role | presentation | balanced | text |
| --- | ---: | ---: | ---: |
| Display (cover title) | 72 | 60 | 46 |
| Title (page / action title) | 52 | 44 | 34 |
| Section title | 40 | 34 | 26 |
| Subheading / card title | 34 | 28 | 22 |
| Body | 32 | 24 | 20 |
| Caption / annotation | 22 | 18 | 15 |
| Label / footer / page number | 18 | 14 | 12 |

* **Floor — the `text` column is a hard minimum.** A role must never be smaller
  than its `text`-column value (body ≥ 20, title ≥ 34, caption ≥ 15, label ≥ 12
  at `ppt169`). If content will not fit, cut or stack it — never shrink a
  recurring role below the floor.
* **Other canvases**: multiply every role by `canvas_width / 1280`
  (`ppt43` → ×0.8); for non-PPT canvases use the span-based body anchor from
  `canvas-formats.md` and scale the other roles by `body_anchor / 24`. Never go
  below 11 px absolute.
* A denser "document / desk" treatment is allowed only when the deck's
  **Reading Mode is `text`** and that choice is declared in the spec; it still
  may not breach the floor.
* Font families come from the deck/brand spec; the ramp fixes only sizes.

## 3. Viewing-distance baseline

Choose the reading mode from the real delivery context, then keep it fixed for
the whole deck:

* **presentation** — projected / large screen, read from a distance → the
  `presentation` column.
* **balanced** — shared screen or mixed room → the `balanced` column.
* **text** — desk reading at 100 % zoom → the `text` column.

Do not silently shrink a recurring role to make one page fit, and do not mix
modes across pages.

## 4. Root `viewBox` grammar

### 4.1 Normative grammar

* The root `<svg>` carries `viewBox="0 0 W H"` with positive integer pixels and
  a matching `width`/`height` where the target needs them.
* A page's `viewBox` and its canvas are the same coordinate space; child
  transforms may scale content but never redefine the page canvas.
* Compatibility spellings (`0,0,W,H`, leading `+`, whitespace runs) are accepted
  as **input** and normalised to the canonical form.
* Fail closed: a missing/invalid `viewBox` with no usable `width`/`height` is an
  error, not a default. A fractional canvas is accepted only as compatible input
  for an imported custom PowerPoint slide size.
