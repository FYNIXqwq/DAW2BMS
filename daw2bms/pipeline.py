"""One-command FLP -> extraction -> adaptive keysounds -> player test chart."""
from __future__ import annotations

from .i18n import msg

import os
from pathlib import Path
import re
import shutil

from .adaptive import cut
from .bms import export_bms, header_text
from .flp import FlpError, extract_file
from .keysounds import sha256_file, write_json
from .resources import installed_fl_roots


def find_fl_executable(explicit: Path | None = None) -> Path | None:
    """Explicit argument > environment > newest installed folder > PATH."""
    configured = explicit or os.environ.get("DAW2BMS_FL_EXE")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".exe":
            raise FlpError(msg('Configured FL Studio executable does not exist: {p0}', p0=path))
        return path
    roots = sorted(installed_fl_roots(), key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.name)), reverse=True)
    for root in roots:
        executable = root / "FL64.exe"
        if executable.is_file():
            return executable.resolve()
    on_path = shutil.which("FL64.exe")
    return Path(on_path).resolve() if on_path else None


def default_destination(source: Path) -> Path:
    base = Path("output") / (source.stem + "-bms")
    candidate = base
    index = 2
    while candidate.exists():
        candidate = base.with_name(base.name + f"-{index}")
        index += 1
    return candidate.resolve()


def convert(source: Path, destination: Path | None = None, *, fl_exe: Path | None = None,
            ableton_render: bool = False, ableton_exe: Path | None = None,
            initial_tail: float = 1.0, max_tail: float = 30.0, max_attempts: int = 5,
            threshold_db: float = -60, timeout: float = 600,
            channels: set[int] | None = None, midi_only: set[int] | None = None,
            resource_dirs: tuple[Path, ...] = (), deduplicate: bool = True,
            arrangement_id: int | None = None, title: str | None = None, artist: str | None = None,
            lead_in_bars: int = 1, play_channels: set[int] | None = None,
            play_tracks: set[int] | None = None, exclude_tracks: set[int] | None = None,
            source_sha256: str | None = None,
            encoding: str = "utf-8", progress=print) -> dict:
    source = source.expanduser().resolve()
    if source_sha256 is not None and sha256_file(source) != source_sha256:
        raise FlpError(msg("The project changed. Read tracks again before converting."))
    destination = (destination.resolve() if destination is not None else default_destination(source))
    if destination.exists():
        raise FlpError(msg('Output directory already exists; choose a new --out: {p0}', p0=destination))
    if source.suffix.lower() == ".als":
        if ableton_render:
            from .als_render import convert_als_audio
            return convert_als_audio(source, destination, ableton_exe=ableton_exe, channels=channels,
                midi_only=midi_only, arrangement_id=arrangement_id, initial_tail=initial_tail,
                max_tail=max_tail, max_attempts=max_attempts, threshold_db=threshold_db, timeout=timeout,
                resource_dirs=resource_dirs, deduplicate=deduplicate, title=title, artist=artist,
                lead_in_bars=lead_in_bars, play_channels=play_channels, play_tracks=play_tracks,
                exclude_tracks=exclude_tracks, source_sha256=source_sha256, encoding=encoding, progress=progress)
        from .als_export import convert_als
        return convert_als(source, destination, channels=channels, arrangement_id=arrangement_id,
                           play_tracks=play_tracks, exclude_tracks=exclude_tracks, source_sha256=source_sha256, progress=progress)
    executable = find_fl_executable(fl_exe)
    progress(msg('[1/3] Reading FLP: {p0}', p0=source))
    document = extract_file(source)
    if source_sha256 is not None and document['source']['sha256'] != source_sha256:
        raise FlpError(msg("The project changed. Read tracks again before converting."))
    from .track_selection import track_policy
    arrangement = next((a for a in document["arrangements"] if arrangement_id is None or a["id"] == arrangement_id), None)
    if arrangement is None:
        raise FlpError(msg('Unknown arrangement {p0}', p0=arrangement_id))
    known_tracks = {c["track_id"] for c in arrangement["clips"]} | {n["track_id"] for n in arrangement["timeline_notes"]}
    roles = track_policy(known_tracks, play_tracks, exclude_tracks)
    included_tracks = known_tracks - set(exclude_tracks or ())
    if not included_tracks:
        raise FlpError(msg("Include at least one note track."))
    placed_tracks = {n["track_id"] for n in arrangement["timeline_notes"] if n["track_id"] in included_tracks
                     and (channels is None or n["channel_id"] in channels)}
    selected_title = header_text(title if title is not None else document["project"].get("title") or source.stem)
    selected_artist = header_text(artist if artist is not None else document["project"].get("artist") or "Unknown")
    if not isinstance(lead_in_bars, int) or not 0 <= lead_in_bars <= 998:
        raise FlpError(msg('Lead-in must be an integer number of bars from 0 to 998'))
    if encoding not in ("utf-8", "cp932"):
        raise FlpError(msg('Supported BMS encodings: utf-8, cp932'))
    destination.mkdir(parents=True)
    report = {"schema_version": 1, "status": "running", "stage": "extract",
              "source": document["source"], "output_directory": str(destination),
              "fl_executable": str(executable) if executable else None,
              "warnings": [], "chart": None, "midi": None, "fallback_midi": None}
    report["track_roles"] = roles
    report["arrangement_id"] = arrangement["id"]
    report_path = destination / "conversion.json"

    def emit(message):
        if message.startswith("WARNING:"):
            report["warnings"].append(message)
        progress(message)

    def preserve_midi():
        for name, field in (("song.mid", "midi"), ("fallback.mid", "fallback_midi"), ("fallback_notes.json", "fallback_notes")):
            path = destination / "work" / name
            if path.is_file():
                shutil.copy2(path, destination / name)
                report[field] = name

    write_json(destination / "project.json", document)
    write_json(report_path, report)
    try:
        overrides = set(midi_only or ())
        fallback_reason = None
        if executable is None:
            emit(msg('WARNING: FL Studio was not found. Keeping selected notes as MIDI only; audio rendering and BMS export will be skipped. Use --fl-exe or DAW2BMS_FL_EXE for a custom installation.'))
            overrides.update(c["id"] for c in document["channels"])
            fallback_reason = msg("FL Studio executable unavailable; MIDI-only conversion")
        else:
            progress(msg('FL Studio: {p0}', p0=executable))
        report["stage"] = "cut"
        write_json(report_path, report)
        progress(msg('[2/3] Checking resources and creating adaptive keysounds'))
        outcome = cut(source, destination / "work", executable, initial_tail=initial_tail, max_tail=max_tail,
                      max_attempts=max_attempts, threshold_db=threshold_db, timeout=timeout,
                      channels=channels, midi_only=overrides or None, resource_dirs=resource_dirs,
                      deduplicate=deduplicate, arrangement_id=arrangement_id, tracks=included_tracks,
                      midi_only_reason=fallback_reason, progress=emit)
        report["cut_status"] = outcome["status"]
        report["midi_only_notes"] = outcome.get("midi_only_notes", 0)
        preserve_midi()
        if sha256_file(source) != document["source"]["sha256"]:
            raise FlpError(msg('Input project changed during conversion; no chart will be published'))
        if outcome["status"] == "midi_only":
            report.update(status="midi_only", stage="finished", audio_complete=False)
            emit(msg('WARNING: No keyed audio is available. MIDI was preserved; no silent/empty BMS chart was generated.'))
            progress(msg('[3/3] BMS export skipped (MIDI-only result)'))
        elif outcome["status"] == "complete":
            report["stage"] = "bms"
            write_json(report_path, report)
            progress(msg('[3/3] Exporting 7-key BMS test chart'))
            bms_report = export_bms(destination / "work/keysounds", destination / "chart",
                                    title=selected_title, artist=selected_artist, lead_in_bars=lead_in_bars,
                                    play_channels=play_channels, encoding=encoding,
                                    play_tracks=play_tracks & placed_tracks if play_tracks is not None else None)
            for message in bms_report["warnings"]:
                emit(msg("WARNING: {p0}", p0=message))
            report.update(status="complete", stage="finished", chart="chart/" + bms_report["chart"],
                          audio_complete=bms_report["audio_complete"], playable_notes=bms_report["playable_notes"],
                          bgm_events=bms_report["bgm_events"], audio_events=bms_report["audio_events"],
                          keysounds=outcome["completed_keys"])
        else:
            raise FlpError(msg('Adaptive cutting did not complete: {p0}', p0=outcome['status']))
        write_json(report_path, report)
        return report
    except (FlpError, OSError) as exc:
        preserve_midi()
        report.update(status="error", error=str(exc))
        write_json(report_path, report)
        raise
