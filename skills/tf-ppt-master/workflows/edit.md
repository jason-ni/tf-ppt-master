# TF-PPT Master — Edit Workflow

Editing an **existing** deck (add/remove/reorder pages, renumber, tweak a page)
is a different game from generating one. This file records the techniques that
are *verified to work* so you never need to read the ppt-viewer source — in a
real deployment you cannot see it, and you must not depend on it.

## Core principle: the MCP contract is the source of truth

Trust the tool **schemas** and the tool **return values**, not viewer internals.

* Every write tool returns a JSON result. Read it:
  * `"applied": true` — the change is live.
  * a `"proposalId"` in the result — the change was only **staged** and is **NOT
    applied** (e.g. an approval-gated tool under a wrapper with no approval UI).
    Verify with `get_deck_overview` rather than assuming.
* `pptx_save` → `result.saved: true` means flushed to disk.
* After any structural change, call `get_deck_overview` and re-read the outline
  to learn the new indices. Never carry stale indices forward.

## Structural edits: insert / add pages

* **Insert a page**: `add_slide` with `{ "insertAfterIndex": N }` puts the new
  slide at page `N+1` (0-based index `N+1`). `{ "insertAfterIndex": -1 }` appends.
  The result's `newSlideIndex` is authoritative.
* **Order of operations per inserted page**: `add_slide` → `add_elements` (author
  that page) → `render_slide` (validate) → next page.
* **NEVER batch a render — or any index-addressed write — together with a
  structural change in the same message.** A structural change shifts every index
  after it, so a `render_slide(slide_index=k)` issued in the same batch can land on
  the *neighbouring* slide. (Verified failure: a render meant for the newly inserted
  head page captured the old next page instead.)
* **When inserting several pages, insert in DESCENDING target order** (insert the
  latest one first). Then earlier indices never move, and every insert lands where
  you planned.
* Removing pages: use the delete tool and **confirm `applied: true`** (see core
  principle). If a delete is only staged, it did not happen.

## Page numbers / renumbering

**Preferred — make the number a LIVE field, not text.** Author each page number with
`add_element({type:"text", field:"slidenum", ...})` (see `references/mcp-mapping.md`
§Page Numbers). The server writes a real `<a:fld type="slidenum">` run, so the renderer
resolves it per slide and it **renumbers automatically** on any insert / delete /
reorder — nothing else to do.

**Only if the number is already a literal text box** (a deck authored before the
`field` option existed, including this chapter's first build) do you have to patch it by
hand. In that case the numbers are stale the moment you insert or delete a page, and
something must rewrite them. Facts (verified on a 1280×720 deck):

* **Reference geometry**: the number box sits bottom-right at **px (1190, 690)**,
  size **50×20**, right-aligned (`algn="r"`), 9 pt (`sz="900"`), colour `4A5A72`
  on a light background. In OOXML EMU (px × 9525): `off x="11334750" y="6572250"`.
* **File ↔ page mapping is NOT `slideN.xml` = page N.** The viewer appends newly
  inserted slides as *new* files (e.g. `slide26.xml`, `slide27.xml`, …) and fixes
  the running order in `ppt/presentation.xml` → `<p:sldIdLst>` → `r:id` →
  `ppt/_rels/presentation.xml.rels` → `slides/slideK.xml`. **Always number by
  display order, never by filename.** (Verified failure: numbering by filename put
  "32" on the §1.1 divider and "1" on the §1.7 divider.)

**How to renumber — a surgical zip edit, not a library round-trip:**

1. Resolve the **display order**: read `ppt/presentation.xml`, take the
   `<p:sldId ... r:id="rIdX">` list in order, map each `rId` through
   `ppt/_rels/presentation.xml.rels` to its `slides/slideK.xml`.
2. For each file at 1-based display index `i`, locate the shape whose `<a:off>` is
   `x="11334750" y="6572250"` and set its `<a:t>` value to `i`.
3. Unzip → edit the XML bytes → rezip. This touches **only the digit runs**; every
   other part (native equations, images) stays byte-identical.

Slides with no anchor (cover, chapter divider) simply have no page number — skip
them.

Do **not**:
* use **python-pptx** — it has *no* slide-number / renumber API (it can only fill
  layout placeholders), and a full `save()` re-serialises the whole package, a
  needless risk for native OMML equations; or
* loop `update_element` over every slide (N × 2 MCP calls — slow and noisy).

A one-liner shape of the edit (illustrative):

```python
# 1) display order:  presentation.xml <p:sldId r:id="rIdX">  in order
pres  = z.read("ppt/presentation.xml").decode()
rels  = z.read("ppt/_rels/presentation.xml.rels").decode()
rid2f = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="slides/(slide\d+\.xml)"', rels))
files = ["ppt/slides/" + rid2f[r] for r in re.findall(r'<p:sldId[^>]*r:id="(rId\d+)"', pres)]
display_no = {f: i for i, f in enumerate(files, 1)}   # file -> page number

# 2) in each slide file, the page-number box is the shape right after the anchor
pat = re.compile(r'(11334750" y="6572250".*?<a:t>)\d+(</a:t>)', re.S)
xml = pat.sub(lambda m: m.group(1) + str(display_no[filename]) + m.group(2), xml, count=1)
# 3) rezip (skip files with no match — cover / divider have no number)
```

**Auto-updating numbers — now supported by the toolset.** A page number that updates
itself uses the OOXML field `<a:fld type="slidenum">` (not a literal `<a:t>`), which the
viewer renders live. `add_element({type:"text", field:"slidenum"})` authors exactly that,
so prefer it over any XML patch. (Verified: the field round-trips through save/load and
renumbers when slides are added, removed or reordered.)

## Editing a single page's content

* Locate the element id (from `get_slide` / `get_deck_overview` text, or a prior
  `add_elements` return), then `update_element` with **flat** fields:
  `{ slideIndex, elementId, x, y, width, height, text, fontSize, fontColor,
  bold, italic, alignment, fillColor, strokeColor, strokeWidth, opacity, altText }`.
* **Equation elements render block-level.** If a render shows literal LaTeX or a
  clipped formula, re-render first; if still clipped, grow the element `height`
  (never shrink the font of an equation to force a fit).
* **`\boldsymbol` is unsupported** in the equation renderer — it degrades the
  whole equation into a plain shape. Use `\mathbf{}` and single-symbol commands
  (`\omega`, `\Gamma`) instead.

## Head-page (section divider) pattern

When a source has numbered sections, give each an explicit head page before its
content. Reusable recipe on a 1280×720 canvas:

| Element        | Geometry (px)     | Style                                   |
| -------------- | ----------------- | --------------------------------------- |
| bg rect        | 0,0, 1284×724     | `#EEF2F7`                               |
| navy panel     | 0,0, 470×724      | `#0A3D91`                               |
| teal cap bar   | 0,0, 470×10       | `#0E9E8E`                               |
| kicker         | 64,150, 400×26    | "SECTION x.y", 18pt bold, `#7FB2F0`     |
| big number     | 60,176, 380×175   | "x.y", 130pt bold, `#FFFFFF`            |
| title          | 60,386, 390×140   | 40pt bold, `#FFFFFF`                    |
| "SECTION OVERVIEW" | 540,150, 500×26 | 18pt bold, `#0E9E8E`                  |
| rule           | 540,186, 120×4    | `#1B6FE0`                               |
| overview list  | 540,202, 700×300  | 22pt, `#14213D`, items joined by `\n\n` |
| footer         | 56,690, 800×20    | 12pt, `#4A5A72`                         |
| page number    | 1190,690, 50×20   | 12pt right, `#4A5A72`                   |

## Finish

`render_slide` the changed pages → `pptx_save` → `pptx_promote_session` (so the
user can edit) → report the path. If the viewer swapped its webview during a
promote, a follow-up `pptx_save` may be needed (an occasional
`session webview disconnected` error is transient — retry).
