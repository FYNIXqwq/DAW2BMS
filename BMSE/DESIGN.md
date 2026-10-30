---
name: BMSE desktop editor
description: The existing BMSE desktop editing world carried into a Web and Wails 3 implementation.
colors:
  panel: "#f0f0f0"
  line: "#b5b5b5"
  focus: "#0078d4"
  selected: "#cce8ff"
  text: "#202020"
  muted: "#555"
  input: "#fff"
  button: "#f4f4f4"
  button-hover: "#e5f1fb"
  button-active: "#cce4f7"
  button-active-border: "#005a9e"
  button-disabled: "#e9e9e9"
  text-disabled: "#858585"
  tab: "#e5e5e5"
  timeline: "#000"
  timing-track: "#303000"
  timing-note: "#d8d830"
  white-key-track: "#202020"
  white-key-note: "#d0d0d0"
  blue-key-track: "#000028"
  blue-key-note: "#7373ff"
  scratch-track: "#300000"
  scratch-note: "#ff6868"
  bga-track: "#002828"
  bga-note: "#57d3d3"
  bgm-track: "#102410"
  bgm-note: "#65d765"
  long-note: "#69d264"
  long-body: "#267820"
  mine-note: "#ff55cc"
  pms-white: "#eee"
  pms-yellow: "#efb74a"
  pms-green: "#67ce63"
typography:
  body:
    fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
  label-small:
    fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "11px"
  title:
    fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "19px"
    fontWeight: 600
  resource:
    fontFamily: 'Consolas, "Microsoft YaHei", monospace'
    fontSize: "12px"
  timeline-label:
    fontFamily: "Consolas, monospace"
    fontSize: "11px"
rounded:
  square: "0"
  button: "2px"
  dialog: "3px"
spacing:
  tight: "2px"
  control: "4px"
  field: "5px"
  row: "6px"
  group: "8px"
  dialog: "16px"
components:
  button:
    backgroundColor: "{colors.button}"
    textColor: "{colors.text}"
    rounded: "{rounded.button}"
    padding: "4px 10px"
  button-hover:
    backgroundColor: "{colors.button-hover}"
  button-active:
    backgroundColor: "{colors.button-active}"
  button-disabled:
    backgroundColor: "{colors.button-disabled}"
    textColor: "{colors.text-disabled}"
  toolbar-button:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.button}"
    padding: "3px"
    width: "28px"
    height: "27px"
  input:
    backgroundColor: "{colors.input}"
    textColor: "{colors.text}"
    rounded: "{rounded.square}"
    padding: "3px 5px"
  tab:
    backgroundColor: "{colors.tab}"
    textColor: "{colors.text}"
    padding: "3px 12px"
  tab-selected:
    backgroundColor: "{colors.panel}"
  resource-row-selected:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.text}"
    typography: "{typography.resource}"
    padding: "0 4px"
    height: "21px"
  dialog:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.dialog}"
    width: "460px"
---

# Design System: BMSE desktop editor

## Overview

**Creative North Star: "Preserve the original BMSE editing workspace"**

This is the human-selected legacy visual world, documented from the current implementation. It is not a new concept or a redesign. Windows-like light gray menus, toolbars and property panels surround a dark, upward-running chart timeline. Compact controls keep chart information and editing tools visible together. The classic density is intentional fidelity.

The authoritative migration references remain the original VB interface, default theme and language files named in the editor surface brief. This document records implemented visual conventions; it does not certify complete functional or pixel parity with the original application.

Key characteristics:

- Dense desktop chrome with system fonts and restrained borders.
- White resource lists beside a dark, color-coded chart.
- Square fields, minimally rounded controls, explicit focus and selection states.
- Lucide vector icons and user-supplied chart media previews, with an optional inherited Siromaru raster Easter egg.

## Colors

The palette separates application controls from chart semantics. Frontmatter values are extracted from `frontend/src/style.css`, `frontend/src/model.ts` and `frontend/src/ChartCanvas.tsx`; they are documentation tokens, not newly introduced CSS variables.

These retained baseline tokens do not replace imported legacy theme values. Theme configuration can change chart rendering; the compatibility dialogs reuse the existing light control chrome.

### Primary

Windows blue (`focus`) identifies keyboard focus and control interaction. Pale blue (`selected`) identifies selected resources. Button hover and pressed fills belong to this same control family.

### Secondary

Chart colors encode lane and object meaning: olive timing tracks with yellow notes, charcoal keys with gray notes, navy keys with blue notes, dark red scratch with red notes, dark teal BGA with cyan notes, and dark green BGM with green notes. Long notes use green endpoints and a darker body; mines use pink. PMS keys use the existing symmetric white, yellow, green, blue, red sequence.

### Neutral

`panel`, `input`, `text` and `muted` provide light chrome, white editable areas and readable labels. The timeline uses black around the lane backgrounds. Gray grid lines establish subdivisions; brighter measure lines separate measures. Selected notes have a white outline, so selection is distinguishable from lane color.

**The Lane Meaning Rule.** Preserve the existing association between lane, background and note color. These colors communicate editing semantics rather than brand decoration.

## Typography

System UI type uses Segoe UI with Microsoft YaHei and sans-serif fallbacks. The normal interface is compact body text; secondary hints, status text and captions use the smaller label role. The title role appears inside information dialogs, not as a large application heading.

Consolas provides aligned resource identifiers, numeric controls, chart labels and source text. Resource lists include Microsoft YaHei as a fallback for filenames. Numeric inputs and status fields use tabular numerals where declared. Retain these small desktop roles rather than adding a display typeface or a promotional hierarchy.

## Layout

The editor fills the window height. A fixed menu row (26px) and toolbar (at least 36px) sit above a flexible workspace; a status strip (25px) remains at the bottom. The left sidebar starts at 258px, is horizontally resizable within 225–360px, and stacks information tabs above resource tabs and lists. The chart takes remaining space, with its own controls above and direct text input below.

At widths up to 1100px, the initial sidebar width becomes 245px, toolbar spacing tightens, icon buttons narrow to 26px, and supplementary caption/document-title text hides. The Wails minimum window is 900×650; the CSS editor floor is 800px. These are different constraints. Saved review evidence covers 1280×900 and 1024×768. Mobile is not a target, and no mobile navigation pattern is specified.

The chart scrolls internally in both directions. Time increases upward, with measure 000 at the beginning at the bottom. Its fixed label band is 25px high and the measure gutter is 48px wide. At default zoom, lane widths range from 38px for keys to 46px for BGA, and one normal measure is 192px high. Zoom scales the chart rather than the surrounding controls.

The saved `desktop.png`, `desktop-1024.png`, `oct-desktop.png`, `preferences.png` and `bga-editor.png` in `.impeccable/review/` confirm the retained desktop hierarchy, OCT lane arrangement and wide configuration/BGA dialogs. OCT's additional lanes and independent scratch columns remain inside the same horizontally scrolling chart. These screenshots are visual evidence for the captured states, not evidence of every workflow or platform.

The audit captures `audit-source.png` and `audit-find.png` record the conditional-source notice and expanded find controls in this same visual world. Review uses saved headless-browser screenshots and source files; Computer Use was not used. Native file pickers, physical drag-and-drop gestures and third-party player interaction still require manual acceptance. The functional audit and its verification scope are recorded in `AUDIT_2026-10-28.md`.

## Elevation & Depth

Most surfaces are flat, separated by one-pixel borders, pale fills and compact gaps. Dropdown menus use a small offset shadow; dialogs use a broader shadow and translucent backdrop. Shadows denote temporary overlays, not permanent panels. Exact overlay shadow values live in the sidecar because the frontmatter component schema does not represent shadows.

Ordinary control states and chart scrolling change immediately. Optional legacy Easter eggs are an intentional exception: the staff roll uses a 45-second linear loop, the Siromaru image uses a 5-second alternating ease-in-out motion, and canvas effects use animation frames. Reduced-motion CSS stops the staff/image CSS motion and hides the effects canvas. These effects remain inside the chart area with an explicit close button.

## Shapes

Fields, lists and chart geometry are rectangular. Buttons have only a slight corner radius; tabs round their upper corners and join the panel edge. Dialogs have a small radius. Avoid pills, oversized cards or large rounded containers: the user selected the original compact desktop interface.

## Components

### Menus and toolbar

Text menus sit in a narrow horizontal bar. Dropdowns align beneath their trigger, show command text and shortcut labels, and scroll if necessary. Toolbar buttons are compact icon squares with transparent resting backgrounds, blue hover borders and pale blue pressed fills. Lucide toolbar icons use 17px geometry and a 1.6 stroke width; material action icons use 14px geometry. Preserve accessible command names and pressed state.

### Tabs and panels

Tabs have light gray fills, slightly rounded upper corners and a shared bottom edge. The selected tab takes the panel fill and semibold text. The two left tab groups retain their information/resource roles. These panels are tools within one editor, not independent cards.

### Fields and buttons

Fields use white backgrounds, gray borders and square corners. Labels align beside controls; resource and chart identifiers use monospace. Keyboard focus is a two-pixel Windows-blue inset outline. Buttons share the compact neutral, hover, pressed and disabled states documented above.

The reusable buffered Field commits on blur or Enter and restores its prior value on Escape without committing. This statement applies to that Field component, not every raw input or dialog setting. Preserve the cancellation behavior when extending it.

### Resource list

Resources are single-line rows with a fixed identifier column, clipped long filenames, white resting fill and pale blue selection. Arrow navigation within the list changes the resource selection without also moving selected chart notes. Keep keyboard handling scoped to its intended control.

The extended information panel exposes dedicated `WAV00 地雷音` and `BMP00 MISS` fields for the mine sound and miss image. Preserve their special meanings rather than treating zero as an ordinary numbered note resource.

### Chart canvas

Horizontal note bars carry their encoded identifier or event value. Invisible notes are outlines; long-note pairs have a connecting body; selected notes have white borders. Lane headings, measure labels and the grid remain visible aids to editing. A translucent blue selection rectangle and white write-position outline communicate pointer operations without changing the lane palette.

Selection edits preserve timing and group relationships. Horizontal movement keeps each object's exact time and stored fraction; vertical movement keeps group spacing and rejects an out-of-bounds move as a whole. Hidden tracks are not guessed into visible lanes. Grid drawing and snapping use the same fixed `192 / grid` time step, including measures with nonstandard lengths.

### Dialogs and feedback

Dialogs use a white title strip above light gray content, an accessible name matching the title, a close control and right-aligned action buttons. Native modal behavior contains interaction. Standard dialogs are 460px wide and wide dialogs 760px, bounded by the viewport. Error and recovery notices appear as persistent inline strips above the workspace, with distinct red and amber treatments and explicit actions.

Settings persistence, asset operations and branch generation guard dialog dismissal while their result is pending. Cancel, the title-bar close button and Escape must all respect that pending state. Keep errors inline and retain the draft so the user can correct it.

Errors arising while a dialog is open remain visible inside the modal, where its interaction is contained. Measure validation uses the same inline alert convention. Initial configuration and recovery loading block editor input and expose the busy state until initialization finishes. A discovered old recovery backup remains protected until the user handles its explicit Restore or Discard action; the amber notice explains that new edits need saving while that choice is pending. Restoration checks current unsaved edits before replacing the document.

### Conditional source protection

Conditional files show a persistent amber source-protection notice above the workspace. Visual mutation controls are disabled or guarded to preserve branch order and definitions; chart inspection and selection remain available. The notice points to the full `BMS 文本` editor and `展开随机 / 条件分支`, which generates an independent branch copy for visual editing. The full source remains editable. Applying unchanged source closes the dialog without creating an edit or dirty state.

### Find and replace

The compact named dialog combines start/end measures, a selected-objects-only checkbox, an identifier/value field with an optional upper bound, a five-row multiple-track selector, an object-kind filter and a replacement field. Its track label explains Ctrl multi-selection. A match count precedes Select, Delete and Replace All actions; Replace All requires a replacement value. BPM decimals and numeric event values such as SCROLL zero use numeric matching rather than resource-number decoding.

### Bulk measure length

The measure panel opens a standard dialog with start/end measures in the `000–999` range and a length field accepting a multiplier or fraction, such as `0.75` or `3/4`. Adjacent explanatory text states the timing behavior: retain time within the original measure and carry overflowing objects into later measures, with Undo available. If the result would carry an object beyond `#999`, show an inline error, keep the dialog open and leave the chart unchanged.

### Configuration

The wide settings dialog reuses the panel tabs for Theme, Language, Shortcuts, Players and Options. Theme, language and shortcut content is editable/importable/exportable INI text in a square, vertically resizable monospace editor (300px initial height). Legacy configuration import and compact button rows sit above the editing controls. Player configuration uses a selector, reorder/add/remove actions, named paths and three argument fields. Raw argument drafts remain visible even when invalid; Save validates JSON string arrays before persisting. Validation appears in the existing red inline error treatment.

### BGA crop and position

Two labeled square canvases sit side by side with a 20px gap: a source-image crop view and a 256 × 256 output view. Both canvas elements are 256px square; the source image is scaled to fit, while its caption reports its natural dimensions. A red rectangle marks the source crop. The output is black behind the selected image region and can show a 32px preview grid. Pointer dragging selects the source region or shifts the output position; compact coordinate fields underneath use a three-column grid. Apply and Cancel retain the standard dialog action row.

### Disk operations and branch extraction

The asset dialog presents a mode selector and explanatory text before the preview action. A generated plan shows source and destination filenames in the existing bordered white data table, within a scroll region capped at 280px. Warnings remain adjacent to the plan; the execution button includes the item count. The recovery action is explicit, and execution is unavailable without a nonempty plan. Branch extraction uses labeled numeric fields with ranges and a separate generation action; it shares the inline error and pending-dismissal conventions.

### Tips and inherited effects

Tips use wrapped system-font text with generous line spacing inside the existing dialog frame. The optional Siromaru Easter egg imports `frontend/src/legacy/siroani.gif`, copied unchanged from the repository's original `image/siroani.gif` under the retained root `LICENSE` (zlib). The original and shipped copy have matching SHA-256 hashes. Preserve that provenance; this inherited raster does not replace the Lucide command icons or establish a new decorative illustration style.

## Do's and Don'ts

- **Do** preserve the existing menu, toolbar, sidebar, timeline and status-strip hierarchy.
- **Do** keep chart colors, numbering, upward time and edit-mode affordances consistent with the existing implementation and original references.
- **Do** retain visible keyboard focus, resource keyboard isolation, Field cancellation and named dialogs.
- **Do** preserve raw invalid player arguments until corrected and guard all dismissal routes while a dialog mutation is pending.
- **Do** keep conditional-source protection and recovery choices explicit, with errors visible inside the active dialog.
- **Do** preserve object timing, selection spacing and complete-operation rejection at chart boundaries.
- **Do** review desktop density at both documented viewport sizes when changing shared controls.
- **Don't** substitute a dashboard, marketing composition or a new visual identity for the human-selected editor.
- **Don't** generalize the optional inherited Easter eggs into decorative motion or raster styling for ordinary editor controls.
- **Don't** treat the documented visual review as evidence of complete original-application parity.
