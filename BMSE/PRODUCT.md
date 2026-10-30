# BMSE desktop rewrite

<!-- impeccable:product-schema 1 -->

## Platform
Web UI in a Wails 3 desktop application. Windows is the verified target.

## Stack
User requested Web technologies and Wails 3. React, TypeScript and Go are the implementation choices.

## Users and job
Local BMS chart authors edit BMS/BME/BML/PMS files and their keysound and image definitions.

## Confirmed constraints
The user explicitly requested reproducing the original interface and operations item by item as closely as possible. Preserve the menu/toolbar, left information and resource panels, upward timeline, note colours, edit modes, shortcuts and numbering. Original VB files and licence remain authoritative migration references. Do not replace the editor with a dashboard or a marketing page.

## Data integrity
Preserve unknown commands and conditional blocks. Never silently overwrite a file on failed serialization, discard unsupported channel data, or truncate note positions. Show diagnostics and keep unsaved work recoverable.

## DAW import workflow
The user confirmed integrating the DAW2BMS conversion flow into BMSE. Open it through File → Import DAW project or by dropping an FLP/ALS file. Assign tracks to playable notes, BGM or exclusion; supported tracks default to BGM. Conversion runs through DAW2BMS with progress, logs and safe cancellation. The standalone CLI and PyQt6 interface remain available.

The Windows distribution must include the converter and Python runtime in the `daw-engine` folder beside `BMSE3.exe`, so normal use requires no Python installation or path configuration. With the bundle present and no prior settings or explicit environment override, the built-in engine is selected automatically. Existing external Python settings remain usable; the collapsible engine settings retain an explicit built-in/external choice. Missing-bundle recovery explains how to restore that folder or select external Python in all four import-panel languages. Bundling the converter does not supply DAW applications, instruments or project samples, or establish compatibility with every DAW or plugin.

Open a completed conversion as an independent new chart after the editor's existing unsaved-changes confirmation. Do not merge it into the current chart. Keep the generated chart beside its media so relative keysound paths remain valid. MIDI-only results do not open an empty chart, and pending conversion/inspection protects the dialog and application from premature closure.

The import panel supports zh-TW, en, ja and ko, follows the operating system by default and remembers a manual choice. The host editor retains its existing INI language system and compact BMSE visual identity.

## DAW production draft
File → DAW 制作底稿 opens the draft editor; opening a converted chart with valid source mapping also opens it automatically. Entry preserves the chart's current playable/BGM assignments. A separate explicit action moves all editable mapped notes to BGM, and assignments participate in the editor's Undo/Redo history.

Keep DAW source identity attached to each mapped note. Group occurrences by source track, instrument/channel, source key and WAV resource so authors can filter, preview keysounds, select groups, locate them in the chart and assign them to target keys or BGM. Assignment preserves event timing, sound references, note count and source identity. Reject the entire assignment if the destination cannot accommodate it; protect long notes, their endpoints and other special notes.

Save source mapping in compressed ASCII `*BMSE_DAW1` comment metadata bound to the serialized chart's hash. Preserve valid mapping through reopening and Save As; reject stale mapping with a visible warning. This workflow reorganizes mapped chart notes and does not establish universal musical fidelity or compatibility with every source project.
