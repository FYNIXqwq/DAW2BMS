"""ALS -> MIDI first -> native offline note banks -> validated keysounds -> BMS."""
from __future__ import annotations

import math
from pathlib import Path
import shutil

from .ableton_ui import NativeExporter, find_ableton
from .adaptive import next_tail
from .als import AlsError, extract_file, read_xml
from .als_bank import make_keys, prepare_track, write_bank
from .als_max import max_requirements
from .als_export import export_document, make_midi
from .audio import slice_bank
from .bms import export_bms
from .flp import FlpError
from .i18n import msg, render
from .keysounds import sha256_file, write_json


def convert_als_audio(source, destination, *, ableton_exe=None, channels=None, midi_only=None,
                      arrangement_id=None, initial_tail=1.0, max_tail=30.0, max_attempts=5,
                      threshold_db=-60, timeout=600, resource_dirs=(), deduplicate=True,
                      title=None, artist=None, lead_in_bars=1, play_channels=None,
                      play_tracks=None, exclude_tracks=None, source_sha256=None,
                      encoding="utf-8", progress=print, exporter_factory=NativeExporter):
    if arrangement_id not in (None, 0):
        raise AlsError(msg("ALS contains one Arrangement; use --arrangement 0 or omit it"))
    if not math.isfinite(initial_tail) or not math.isfinite(max_tail) or max_tail < initial_tail or initial_tail < .1 or max_attempts < 1:
        raise AlsError(msg("Invalid adaptive limits: max-tail >= initial-tail >= 0.1, max-attempts >= 1"))
    if not math.isfinite(threshold_db) or not -120 <= threshold_db <= -20:
        raise AlsError(msg("Silence threshold must be between -120 and -20 dBFS"))
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
    unrendered_audio = sum(c["kind"] == "audio" and c["scope"] == "arrangement" and c["track_id"] not in (exclude_tracks or ()) for c in document["clips"])
    if exclude_tracks:
        document["warnings"] = [w for w in document["warnings"] if w["code"] != "ALS_AUDIO_NOT_RENDERED"]
        if unrendered_audio:
            document["warnings"].append({"code": "ALS_AUDIO_NOT_RENDERED", "message": msg("{p0} Arrangement audio clips are inventoried only; no audio-to-MIDI inference or rendering is performed", p0=unrendered_audio)})
    report = export_document(document, destination, selected_tracks=channels)
    report["track_roles"] = roles
    # MIDI is safely on disk before any dependency check or desktop operation.
    report["warnings"] = report["warnings"][1:]
    report.update(rendering="pyautogui", stage="preflight", status="running")
    def emit(message):
        report["warnings"].append(message)
        progress(message)
    def save():
        write_json(destination / "conversion.json", report)
    for warning in report["warnings"]:
        progress(warning)
    selected_notes = [n for n in document["timeline_notes"] if n["midi_eligible"] and (channels is None or n["track_id"] in channels)]
    accepted, mapped = {}, []
    exporter = None
    save()
    try:
        executable = find_ableton(ableton_exe)
        if executable is None:
            raise AlsError(msg("Ableton Live was not found; MIDI is preserved."))
        meters = document["project"]["time_signatures"]
        if len(meters) != 1 or (meters[0]["numerator"], meters[0]["denominator"]) != (4, 4) or any(w["code"] == "ALS_TEMPO_AUTOMATION" for w in document["warnings"]):
            raise AlsError(msg("ALS audio export currently requires constant tempo and 4/4; MIDI is preserved."))
        if any(t["solo"] for t in document["tracks"]):
            raise AlsError(msg("ALS track {p0} uses unsupported group or cross-track routing; MIDI is preserved.", p0="Solo"))
        _, midi_map, _ = make_midi(document, channels)
        if not midi_map["timing_exact"] or midi_map["beat_offset"] != "0":
            raise AlsError(msg("ALS audio export requires exact nonnegative MIDI timing; MIDI is preserved."))
        ppq, bpm = midi_map["ppq"], float(midi_map["initial_tempo_bpm"])
        original, _, _ = read_xml(source)
        roots = tuple(resource_dirs) + (executable.parent.parent / "Resources/Core Library", executable.parent.parent / "Resources/Builtin")
        report.update(stage="cut", ableton_executable=str(executable)); save()
        progress(msg("[2/3] Checking resources and creating adaptive keysounds"))
        for track_id in sorted({n["track_id"] for n in selected_notes}):
            if track_id in (midi_only or set()):
                emit(msg("WARNING: ALS track {p0} was selected as MIDI-only.", p0=track_id)); continue
            try:
                prepared = prepare_track(original, document, track_id, source, roots)
                max_requirements(prepared)
                keys, timeline, excluded = make_keys(document, track_id, ppq, deduplicate=deduplicate)
                if excluded:
                    emit(msg("WARNING: ALS track {p0}: {p1} notes use unsupported clip semantics and remain MIDI-only.", p0=track_id, p1=len(excluded)))
                if not keys:
                    continue
            except AlsError as exc:
                emit(msg("WARNING: {p0}", p0=exc)); continue
            if exporter is None:
                exporter = exporter_factory(executable, timeout=timeout, progress=progress)
                progress(msg("Ableton uses the foreground desktop. Move the mouse to a screen corner to stop automation."))
            pending = list(keys)
            tails = {k["id"]: initial_tail for k in keys}
            for attempt in range(1, max_attempts + 1):
                progress(msg("ALS track {p0}, attempt {p1}: rendering {p2} keys.", p0=track_id, p1=attempt, p2=len(pending)))
                directory = destination / "work" / f"track-{track_id}" / f"attempt-{attempt:02d}"
                manifest = write_bank(prepared, original, document, track_id, pending, directory, ppq, bpm, tails)
                exporter.render(directory / manifest["bank"]["project"], directory / "render.wav", bars=manifest["bank"]["bars"], bpm=bpm)
                sliced = slice_bank(directory / "manifest.json", destination=directory / "validated", threshold_db=threshold_db, allow_partial=True)
                for k in sliced["keys"]:
                    accepted[k["key_id"]] = {**k, "source_file": str(directory / "validated" / k["file"])}
                checks = {k["key_id"]: k for k in sliced["checks"]}
                retry = []
                for key in pending:
                    if key["id"] in accepted:
                        continue
                    failures = {f["reason"] for f in sliced["failures"] if f["key_id"] == key["id"]}
                    if failures <= {"tail_not_finished", "audio_in_guard_gap", "late_audio_after_tail"}:
                        tail = next_tail(checks[key["id"]], threshold_db, max_tail)
                        if tail > tails[key["id"]] and attempt < max_attempts:
                            tails[key["id"]] = tail; retry.append(key); continue
                    emit(msg("WARNING: ALS key {p0} could not be validated ({p1}); its notes remain MIDI-only.", p0=key["id"], p1=", ".join(sorted(failures))))
                pending = retry
                if not pending:
                    break
            mapped.extend(n for n in timeline if n["key_id"] in accepted)
        if sha256_file(source) != document["source"]["sha256"]:
            raise AlsError(msg("Input project changed during conversion; no chart will be published"))
        def identity(n):
            return n["track_id"], n["clip_index"], n["note_index"], n["repeat"]
        voiced = {identity(n) for n in mapped}
        missing = [n for n in selected_notes if identity(n) not in voiced]
        fallback_doc = {**document, "timeline_notes": missing}
        (destination / "fallback.mid").write_bytes(make_midi(fallback_doc)[0])
        write_json(destination / "fallback_notes.json", {"source": document["source"], "notes": missing})
        report["midi_only_notes"] = len(missing)
        if mapped:
            final = destination / "work/keysounds"; final.mkdir(parents=True)
            for k in accepted.values():
                shutil.copy2(k["source_file"], final / k["file"])
            # The BMS exporter only needs placeholder timing for fallback MIDI;
            # replace that file with the ALS writer's exact velocities/releases.
            from fractions import Fraction
            fallback = [{**n, "channel_id": n["track_id"], "channel_name": n["track_name"],
                         "visible_start_ticks": round(Fraction(n["visible_start_beats"]) * ppq),
                         "visible_end_ticks": round(Fraction(n["visible_end_beats"]) * ppq),
                         "length_ticks": max(1, round(Fraction(n["duration_beats"]) * ppq)),
                         "velocity_raw": float(Fraction(n["velocity"]) * 128 / 127)} for n in missing]
            write_json(final / "timeline.json", {"timing": {"ppq": ppq, "bpm": bpm}, "notes": mapped, "midi_only_notes": fallback})
            write_json(final / "keysounds.json", {"status": "complete", "source": document["source"], "keys": list(accepted.values())})
            progress(msg("[3/3] Exporting 7-key BMS test chart"))
            chart = export_bms(final, destination / "chart", title=title, artist=artist or "Unknown", lead_in_bars=lead_in_bars,
                               play_channels=play_channels, encoding=encoding, unrendered_audio_clips=unrendered_audio,
                               play_tracks=play_tracks & {n["track_id"] for n in selected_notes} if play_tracks is not None else None)
            shutil.copy2(destination / "song.mid", destination / "chart/song.mid")
            if missing:
                shutil.copy2(destination / "fallback.mid", destination / "chart/fallback.mid")
            for w in chart["warnings"]: emit(msg("WARNING: {p0}", p0=w))
            report.update(status="complete", stage="finished", chart="chart/" + chart["chart"],
                          audio_complete=not missing and not unrendered_audio, playable_notes=chart["playable_notes"], bgm_events=chart["bgm_events"],
                          audio_events=chart["audio_events"], keysounds=len(accepted))
            emit(msg("WARNING: Isolated ALS notes preserve static device processing; sidechain, legato and nonlinear mix interactions may differ from the original song."))
        else:
            report.update(status="midi_only", stage="finished", audio_complete=False)
            emit(msg("WARNING: No keyed audio is available. MIDI was preserved; no silent/empty BMS chart was generated."))
            progress(msg("[3/3] BMS export skipped (MIDI-only result)"))
    except (AlsError, OSError) as exc:
        emit(msg("WARNING: {p0}", p0=exc))
        report.update(status="midi_only", stage="finished", audio_complete=False, audio_error=str(exc),
                      midi_only_notes=len(selected_notes))
        shutil.copy2(destination / "song.mid", destination / "fallback.mid")
        write_json(destination / "fallback_notes.json", {"source": document["source"], "notes": selected_notes})
    except FlpError as exc:
        report.update(status="error", error=str(exc), audio_complete=False)
        save()
        raise
    finally:
        if exporter is not None and hasattr(exporter, "close"):
            exporter.close()
    save()
    (destination / "summary.txt").write_text("\n".join([render(msg("File: {p0}", p0=source)),
        render(msg("Result: {p0}", p0=report["status"]))] + [render(w) for w in report["warnings"]]) + "\n", encoding="utf-8")
    return report
