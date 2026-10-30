# BMSE editor surface

Mode: Operate. Scope: the Wails desktop editor, 1280×900 and 1024×768. Mobile is not a shipping target; Wails minimum window is 900×650.

## Direction contract

THESIS: Reproduce the incumbent BMSE editing workflow, not redesign its identity. The human explicitly chose item-by-item interface and operation fidelity.

OWN-WORLD: Native-style light gray menu, toolbar, tab and property chrome; white material list; black timeline with olive timing tracks, gray/blue keys, red scratch, teal BGA and green BGM. Compact square controls and system UI type are deliberate legacy fidelity requirements.

STORY: Open a local chart, select a material, write/select/drag notes, inspect or find objects, save and launch a configured player. Data errors must be visible and unsaved changes recoverable.

FIRST VIEWPORT: Top menu and icon toolbar; approximately 258px left column with metadata tabs above resource tabs; remaining width and height devoted to an upward timeline starting at measure 000 at the bottom; direct text input below; persistent status strip.

FORM: Port within the existing visual world. No new-world concept seed or raster comp applies. Authoritative incumbent evidence: root frmMain.Designer.vb, frmMain.vb, theme/default.ini and lang/chinese_simplified.ini. User confirmed preservation.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

Icons are Lucide vectors. The optional Siromaru Easter egg reuses `frontend/src/legacy/siroani.gif`, copied unchanged from the original `image/siroani.gif` under the retained project LICENSE. The inherited moving mascot is an intentional legacy compatibility exception to the generic animation detector. The user prohibited Computer Use; all later review must use saved headless-browser screenshots and files only.

Compatibility extension: INI theme/language/shortcut configuration, multiple viewers, OCT/FP and independent scratch layouts, BGA source/target canvases, conditional branch extraction, recoverable disk operations and Tips. Mutation dialogs block all dismissal routes while a result is pending; player arguments retain raw drafts and validate before persistence.

## DAW import extension

File → Import DAW project and FLP/ALS drops open the DAW conversion dialog within the incumbent light-gray, compact control chrome. A source/output area and collapsible engine/render settings precede a scrollable track-role table; supported tracks default to BGM, with explicit playable/BGM/exclude choices. Status, selectable logs, inline errors, result counts and output actions stay inside this dialog. Existing timeline styling and lane semantics are unchanged.

The Wails service exchanges JSONL with the bundled converter or the configured external Python engine. While inspection or conversion is pending, mutation controls and dismissal are locked; cancellation reports its pending state and preserves generated work. Opening a completed result invokes the existing unsaved-work guard before installing the generated chart as an independent document. MIDI-only output has no chart-open action. Relative media paths retain the generated output directory as their base.

The import panel's zh-TW/en/ja/ko selection follows the OS unless manually set and remembered; it does not replace the editor's INI localization. Finish-review evidence for this extension is `.impeccable/review/daw/{desktop-zh,compact-zh,desktop-en,compact-en,running,result,imported-editor}.png`. The reviewer returned `ship` for this extension and its supplied screenshots/related frontend code; that scope does not certify every DAW or plugin.

### Bundled engine extension

Keep engine settings collapsed initially for a ready configuration. Inside that section, the compact labeled selector offers Built-in engine and External Python; built-in mode replaces Python path fields with a short ready message or an inline missing-bundle alert. Engine errors expand the section for recovery. External mode retains the existing executable and engine-folder fields. The selector is disabled while work is pending, and changing its value clears the inspected track preview. Preserve the surrounding dialog, timeline, typography and colors; the new label has sufficient width to remain readable in all four supported languages.

The built-in converter and Python runtime live in `daw-engine` beside `BMSE3.exe`, located relative to the executable rather than a saved build-machine path. A fresh configuration chooses it when available unless explicit environment settings request external Python; older saved Python settings retain external mode. Built-in help states that Python setup is unnecessary. Missing-bundle copy instructs users to restore that folder or choose External Python. These messages and the selector are localized in zh-TW, en, ja and ko.

Saved headless-browser evidence is `.impeccable/review/bundled/{en,zh-TW,ja,ko}.png`. After widening the new selector label, the finish reviewer returned `ship` at that fix scope; the unchanged surrounding interface had passed the initial review. This is visual evidence for the captured states. Runtime integration is defined by `dawengine.go`, `dawservice.go`, `frontend/src/daw.ts`, `build-engine.ps1` and `packaging/`; its isolated bundle verifier covers runtime loading, the helper entry point and a small ALS-to-MIDI fixture, not universal DAW or plugin compatibility. No new visual world, raster asset or shared design token is introduced.
