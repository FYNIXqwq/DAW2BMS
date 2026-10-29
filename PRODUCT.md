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

Select one FLP or ALS, read its tracks, choose an output location and assign track roles before audio conversion.
FL Studio roles belong to Playlist tracks, not Channel Rack channels; the same instrument can be playable on one
track and BGM on another. Ableton roles belong to Arrangement tracks. Supported tracks default to BGM;
the user chooses playable notes, BGM or exclusion. Structurally unsupported or muted content defaults to exclusion.
BGM plays automatically without occupying playable keys; excluded tracks are omitted from audio and MIDI export.
Then optionally adjust settings, convert and inspect the result.
Missing plugins retain MIDI and produce warnings. Adaptive audio cutting must not use a fixed release duration.
The source FLP/ALS stays unchanged. Sample projects and generated output stay out of Git.

## Confirmed GUI direction

The user approved a single window: project/settings on the left, progress/logs on the right,
The initial Chinese interface is now expanded, at the user's request, to zh-TW, en, ja and ko.
The default must follow the operating system's UI language unless manually overridden; a manual GUI choice is remembered.
The user rejected green accents; the current direction uses neutral charcoal with restrained blue. Batch conversion is not in this first version.
The user subsequently authorized Windows GUI automation of Ableton's native export dialog and explicitly
requested PyAutoGUI for that backend. This permission is scoped to the Ableton rendering workflow.
Testing this application's own GUI can still run offscreen.

## Evidence and boundaries

The repository implements FLP extraction, dependency checks, adaptive rendering, MIDI fallback and 7-key test charts.
ALS is now supported for read-only Arrangement extraction and MIDI/JSON export without Ableton Live.
ALS can optionally render static native, scanned VST2/VST3 and verified Max for Live devices through Windows Live using PyAutoGUI and UIA reads.
The CLI requires --ableton-render; the GUI has an explicit desktop-rendering checkbox, off by default.
Plug-in IDs must match Live's scan database and each generated Set must have fresh successful preset-restoration evidence in Live's log.
Max for Live additionally requires the AbletonMCP Remote Script for read-only device/parameter verification, plus AMXD/dependency hashes and fresh error-log checks.
Missing/disabled/failed devices, Audio Unit devices and unsupported timing/routing remain MIDI-only with warnings.
Session, frozen, groove-pool and take-lane material must not be mistaken for Arrangement playback.
The GUI must distinguish complete audio, partial audio with MIDI fallback, MIDI-only results, failure and cancellation.
FL rendering is a blocking subprocess in the current backend. Cooperative stopping waits for the current render to finish.
