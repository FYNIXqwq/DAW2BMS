"""ALS-only MIDI/JSON export. No Live or FL renderer is invoked."""
from __future__ import annotations

from collections import defaultdict
import csv
from fractions import Fraction
from math import lcm
from pathlib import Path
import struct

from .als import AlsError, extract_file
from .i18n import msg, render, tr
from .keysounds import sha256_file, write_json
from .midi import meta, track


def make_midi(document: dict, selected_tracks: set[int] | None = None):
    available = {t["id"] for t in document["tracks"] if t["kind"] == "MidiTrack"}
    if selected_tracks is not None and not selected_tracks <= available:
        raise AlsError(msg("ALS --channels must refer to MIDI track IDs"))
    notes = [n for n in document["timeline_notes"] if n["midi_eligible"] and (selected_tracks is None or n["track_id"] in selected_tracks)]
    offset = max(Fraction(0), -min((Fraction(n["visible_start_beats"]) for n in notes), default=Fraction(0)))
    meters = document["project"]["time_signatures"]
    positions = [Fraction(n[key]) + offset for n in notes for key in ("visible_start_beats", "visible_end_beats")]
    positions.extend(Fraction(m["time_beats"]) + offset for m in meters)
    ppq, exact = 960, True  # Export resolution, never an asserted ALS-native PPQ.
    for beat in positions:
        needed = lcm(ppq, beat.denominator)
        if needed > 32767:
            ppq, exact = 960, False
            break
        ppq = needed
    max_error = max((abs(Fraction(round(beat * ppq), ppq) - beat) for beat in positions), default=Fraction(0))
    warnings = []
    if offset:
        warnings.append(msg("ALS MIDI is shifted by {p0} beats to preserve notes before beat zero", p0=str(offset)))
    bpm = Fraction(document["project"]["initial_tempo_bpm"])
    conductor = [(0, 0, meta(3, b"DAW2BMS ALS Arrangement")),
                 (0, 1, meta(0x51, round(Fraction(60000000) / bpm).to_bytes(3, "big")))]
    for index, meter in enumerate(meters):
        position = 0 if index == 0 else round((Fraction(meter["time_beats"]) + offset) * ppq)
        conductor.append((position, 2, meta(0x58, bytes([meter["numerator"], meter["denominator"].bit_length() - 1, 24, 8]))))
    grouped = defaultdict(list)
    for note in notes:
        grouped[note["track_id"]].append(note)
    data_tracks = [track(conductor)]
    mapping, duration_extensions = [], 0
    for index, (track_id, track_notes) in enumerate(sorted(grouped.items())):
        channel, port = index % 16, index // 16
        if port > 127:
            raise AlsError(msg("Too many independent MIDI ports"))
        events = [(0, 0, meta(3, (str(track_id) + ": " + track_notes[0]["track_name"]).encode("utf-8"))),
                  (0, 1, meta(0x21, bytes([port])))]
        for note in track_notes:
            start = round((Fraction(note["visible_start_beats"]) + offset) * ppq)
            end = round((Fraction(note["visible_end_beats"]) + offset) * ppq)
            if end <= start:
                end = start + 1
                duration_extensions += 1
                max_error = max(max_error, abs(Fraction(end, ppq) - Fraction(note["visible_end_beats"]) - offset))
            velocity = max(1, min(127, round(Fraction(note["velocity"]))))
            release = max(0, min(127, round(Fraction(note["off_velocity"]))))
            events += [(start, 3, bytes([0x90 | channel, note["key"], velocity])),
                       (end, 2, bytes([0x80 | channel, note["key"], release]))]
            mapping.append({"track_id": track_id, "clip_index": note["clip_index"], "note_index": note["note_index"],
                            "repeat": note["repeat"], "start_tick": start, "end_tick": end, "key": note["key"],
                            "velocity": velocity, "off_velocity": release, "midi_port": port, "midi_channel": channel})
        data_tracks.append(track(events))
    if not exact or duration_extensions:
        warnings.append(msg("ALS MIDI timing was rounded at PPQ {p0}; maximum error {p1} beats. Exact positions remain in JSON", p0=ppq, p1=str(max_error)))
    report = {"format": "SMF Type 1", "ppq": ppq, "ppq_origin": "chosen_for_export", "beat_offset": str(offset),
              "timing_exact": exact and not duration_extensions, "max_rounding_error_beats": str(max_error),
              "minimum_duration_extensions": duration_extensions, "note_count": len(notes), "tracks_with_notes": len(grouped),
              "initial_tempo_bpm": str(bpm), "time_signatures": meters,
              "tempo_policy": document["project"]["tempo_export"], "events": mapping}
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(data_tracks), ppq) + b"".join(data_tracks), report, warnings


def _csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_document(document: dict, destination: Path, *, selected_tracks=None, force=False):
    destination = destination.resolve()
    names = ("project.json", "clips.csv", "notes.csv", "timeline_notes.csv", "song.mid", "fallback.mid",
             "fallback_notes.json", "midi_mapping.json", "summary.txt", "conversion.json")
    if not force and any((destination / name).exists() for name in names):
        raise AlsError(msg("Output already exists: {p0}. Use --force to replace generated files.", p0=destination))
    midi, midi_report, midi_warnings = make_midi(document, selected_tracks)
    warnings = [w["message"] for w in document["warnings"]] + midi_warnings
    warnings.insert(0, msg("ALS import is MIDI-only. Ableton Live is not required; instrument rendering and BMS audio export are disabled."))
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "project.json", document)
    (destination / "song.mid").write_bytes(midi)
    (destination / "fallback.mid").write_bytes(midi)
    selected = [n for n in document["timeline_notes"] if selected_tracks is None or n["track_id"] in selected_tracks]
    write_json(destination / "fallback_notes.json", {"source": document["source"], "time_unit": "quarter_note_beats", "notes": selected})
    write_json(destination / "midi_mapping.json", midi_report)
    _csv(destination / "clips.csv", document["clips"], ["index", "id", "track_id", "scope", "kind", "name", "start_beats", "end_beats", "disabled", "expansion_status"])
    raw_notes = [{**note, "clip_index": clip["index"], "track_id": clip["track_id"], "scope": clip["scope"]} for clip in document["clips"] for note in clip["notes"]]
    _csv(destination / "notes.csv", raw_notes, ["track_id", "clip_index", "scope", "index", "note_id", "key", "time_beats", "duration_beats", "velocity", "off_velocity", "probability", "enabled"])
    _csv(destination / "timeline_notes.csv", document["timeline_notes"], ["track_id", "track_name", "clip_index", "note_index", "note_id", "repeat", "key", "velocity", "off_velocity", "absolute_onset_beats", "duration_beats", "visible_start_beats", "visible_end_beats", "enabled", "probability", "midi_eligible", "boundary_clipped"])
    summary = document["summary"]
    lines = [tr("ALS Arrangement import report"), tr("File: {p0}", p0=document["source"]["file"]),
             tr("Saved Ableton version: {p0}", p0=document["project"]["creator"]),
             tr("ALS: {p0} tracks, {p1} Arrangement clips, {p2} timeline notes, {p3} MIDI notes", p0=summary["tracks"], p1=summary["arrangement_clips"], p2=summary["timeline_notes"], p3=midi_report["note_count"]),
             tr("ALS beat positions are exact rational strings; MIDI PPQ is chosen for export, not read from Live."),
             tr("Diagnostics:")] + [render(msg("WARNING: {p0}", p0=w)) for w in warnings]
    (destination / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {"schema_version": 1, "status": "midi_only", "stage": "finished", "daw": "ableton_live",
              "source": document["source"], "output_directory": str(destination), "chart": None,
              "midi": "song.mid", "fallback_midi": "fallback.mid", "fallback_notes": "fallback_notes.json",
              "midi_only_notes": midi_report["note_count"], "audio_complete": False, "rendering": "disabled",
              "midi_mapping": "midi_mapping.json", "midi_timing_exact": midi_report["timing_exact"],
              "midi_tempo_policy": midi_report["tempo_policy"],
              "unsupported_clip_count": sum(c["expansion_status"].startswith("unsupported") for c in document["clips"]),
              "warnings": [msg("WARNING: {p0}", p0=w) for w in warnings], "summary": summary}
    write_json(destination / "conversion.json", report)
    return report


def convert_als(source, destination, *, channels=None, arrangement_id=None, play_tracks=None, exclude_tracks=None, source_sha256=None, progress=print):
    if arrangement_id not in (None, 0):
        raise AlsError(msg("ALS contains one Arrangement; use --arrangement 0 or omit it"))
    progress(msg("[1/3] Reading ALS: {p0}", p0=source))
    document = extract_file(source)
    if source_sha256 is not None and document['source']['sha256'] != source_sha256:
        raise AlsError(msg("The project changed. Read tracks again before converting."))
    from .track_selection import track_policy
    roles = track_policy({c["track_id"] for c in document["clips"] if c["scope"] == "arrangement"}, play_tracks, exclude_tracks)
    if exclude_tracks:
        channels = (set(channels) if channels is not None else {t["id"] for t in document["tracks"] if t["kind"] == "MidiTrack"}) - set(exclude_tracks)
        if not channels:
            raise AlsError(msg("Include at least one note track."))
    progress(msg("[2/3] Exporting ALS Arrangement MIDI"))
    if sha256_file(source) != document["source"]["sha256"]:
        raise AlsError(msg("Input project changed during conversion; no chart will be published"))
    report = export_document(document, destination, selected_tracks=channels)
    report["track_roles"] = roles
    write_json(destination / "conversion.json", report)
    for warning in report["warnings"]:
        progress(warning)
    progress(msg("[3/3] BMS export skipped (MIDI-only result)"))
    return report
