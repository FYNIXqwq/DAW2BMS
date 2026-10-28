# DAW2BMS

<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop application. The existing Python command line remains supported.

## Stack

The user explicitly requested PyQt6. The GUI calls the existing Python conversion pipeline.

## Users and purpose

The user is developing a DAW-project-to-BMS tool, starting with FL Studio. The desktop surface makes
the existing one-command workflow available through file selection, progress, logs and result links.

## Confirmed workflow

Select one FLP, choose an output location, optionally adjust settings, convert and inspect the result.
Missing plugins retain MIDI and produce warnings. Adaptive audio cutting must not use a fixed release duration.
The source FLP stays unchanged. Sample projects and generated output stay out of Git.

## Confirmed GUI direction

The user approved a single window: project/settings on the left, progress/logs on the right,
The initial Chinese interface is now expanded, at the user's request, to zh-TW, en, ja and ko.
The default must follow the operating system's UI language unless manually overridden; a manual GUI choice is remembered.
The user rejected green accents; the current direction uses neutral charcoal with restrained blue. Batch conversion is not in this first version.
No computer-use automation may be used; testing can exercise this application's own code offscreen.

## Evidence and boundaries

The repository implements FLP extraction, dependency checks, adaptive rendering, MIDI fallback and 7-key test charts.
ALS is now supported for read-only Arrangement extraction and MIDI/JSON export without Ableton Live.
ALS instrument rendering remains disabled; Session, frozen and take-lane material must not be mistaken for Arrangement playback.
The GUI must distinguish complete audio, partial audio with MIDI fallback, MIDI-only results, failure and cancellation.
FL rendering is a blocking subprocess in the current backend. Cooperative stopping waits for the current render to finish.
