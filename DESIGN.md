# Desktop conversion workspace

User-approved direction: multilingual PyQt6 desktop tool, neutral charcoal single-window layout with a settings pane
on the left and conversion status/logs on the right. Operate mode; native controls and keyboard use take priority.

## Structure

- Compact product heading and description; no decorative dashboard metrics.
- Left: FLP input with file browsing/drop support, output parent directory, collapsed advanced settings, primary start action.
- Right: three real workflow stages, current operation, indeterminate progress during work, logs and a separate warnings tab.
- Result summary distinguishes incomplete audio and MIDI-only outcomes; only existing results get enabled open buttons.
- Advanced options scroll within the left pane. The splitter resizes; minimum window is 960 × 700 logical pixels.

## Tokens

Background #17191d, panel #202329, input #171a20, border #3d444f.
Primary text #edf0f5, secondary #b7bfcc, muted #a0abba.
The user rejected the previous green/teal accent. Use restrained blue for actions and progress, never green by default.
Action #9ab8fa with dark text #172035; warning #ffd18a; failure #ffadad.
Locale-aware native Windows UI fonts (Segoe UI, Microsoft JhengHei UI, Yu Gothic UI, Malgun Gothic, with Qt fallback),
10pt body, 22px title and 16px section headings. Register installed fonts for offscreen testing when Qt cannot discover them.
Console text uses the system fixed-width font. Spacing follows 8/12/16/24; controls have 6px corners.

## State and interaction contract

No estimated completion percentages. Stage indicators follow actual pipeline events; the progress bar is busy while running.
Only one conversion may run. Inputs lock during it. Stop requests are cooperative and explicitly wait for the current render.
Closing a busy window is deferred until work stops; never terminate a Qt thread or an unrelated FL process.
Warnings remain visible independently of success. Logs are selectable, bounded, and saveable.
Primary actions support keyboard focus and Ctrl+Enter; Ctrl+O opens a project picker.
Default language follows the OS UI language. The language selector also supports remembered manual choices
and a System default option. Text bindings update in place during a job; raw paths, entered metadata, stage codes and
backend messages remain unchanged. Longer English/Japanese/Korean labels may wrap; save-log is in the progress header
so result actions remain usable at compact width.

## Verification

Use Qt's offscreen platform for widget tests and QWidget.grab for screenshots; no desktop automation.
Inspect default and minimum-size views in one pass, fix defects together, and confirm at most once.
