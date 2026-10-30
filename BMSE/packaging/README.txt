BMSE 3 + DAW2BMS (Windows x64)

Extract the entire archive and run BMSE3.exe. Keep the daw-engine directory
beside the executable. Python installation and Python path configuration are
not required. Windows WebView2 Runtime is required for the editor.

File > Import DAW project: choose FLP/ALS, read tracks, choose playable/BGM/
excluded tracks, and convert. Open the result as a new chart to continue editing.
The existing unsaved-work confirmation remains in effect.

FL Studio / Ableton Live and the project's instruments and samples must be
installed separately. Missing devices preserve MIDI with warnings. ALS defaults
to MIDI-only; enabling Ableton rendering operates its foreground export window.
Save the current Live Set before rendering. Max for Live verification requires
the AbletonMCP Remote Script. Audio Unit is not supported.

Generated charts are automatic test layouts, not graded finished charts.
Keep each generated chart with its audio directory. The source DAW project is
read-only. Supported timing and playback semantics are limited; inspect warnings.

The import panel supports zh-TW / en / ja / ko and follows the OS UI language
unless manually selected. Advanced engine settings allow an external Python
environment; select Built-in engine to return to this distribution's runtime.

Project license: GNU Affero General Public License v3.0 or later
(SPDX: AGPL-3.0-or-later). See LICENSE and NOTICE.
Source: https://github.com/FYNIXqwq/DAW2BMS
Original BMSE and retained third-party notices: BMSE-LICENSE.txt.
Python and bundled dependency notices are retained in daw-engine/_internal
(package metadata and third-party-licenses). Their original terms still apply.
