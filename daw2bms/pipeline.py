"""One-command FLP -> extraction -> adaptive keysounds -> player test chart."""
from __future__ import annotations

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
            raise FlpError(f"Configured FL Studio executable does not exist: {path}")
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
            initial_tail: float = 1.0, max_tail: float = 30.0, max_attempts: int = 5,
            threshold_db: float = -60, timeout: float = 600,
            channels: set[int] | None = None, midi_only: set[int] | None = None,
            resource_dirs: tuple[Path, ...] = (), deduplicate: bool = True,
            arrangement_id: int | None = None, title: str | None = None, artist: str | None = None,
            lead_in_bars: int = 1, play_channels: set[int] | None = None,
            encoding: str = "utf-8", progress=print) -> dict:
    source = source.expanduser().resolve()
    destination = (destination.resolve() if destination is not None else default_destination(source))
    if destination.exists():
        raise FlpError(f"Output directory already exists; choose a new --out: {destination}")
    executable = find_fl_executable(fl_exe)
    progress(f"[1/3] Reading FLP: {source}")
    document = extract_file(source)
    selected_title = header_text(title if title is not None else document["project"].get("title") or source.stem)
    selected_artist = header_text(artist if artist is not None else document["project"].get("artist") or "Unknown")
    if not isinstance(lead_in_bars, int) or not 0 <= lead_in_bars <= 998:
        raise FlpError("Lead-in must be an integer number of bars from 0 to 998")
    if encoding not in ("utf-8", "cp932"):
        raise FlpError("Supported BMS encodings: utf-8, cp932")
    destination.mkdir(parents=True)
    report = {"schema_version": 1, "status": "running", "stage": "extract",
              "source": document["source"], "output_directory": str(destination),
              "fl_executable": str(executable) if executable else None,
              "warnings": [], "chart": None, "midi": None, "fallback_midi": None}
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
            emit("WARNING: FL Studio was not found. Keeping selected notes as MIDI only; audio rendering and BMS export will be skipped. "
                 "Use --fl-exe or DAW2BMS_FL_EXE for a custom installation.")
            overrides.update(c["id"] for c in document["channels"])
            fallback_reason = "FL Studio executable unavailable; MIDI-only conversion"
        else:
            progress(f"FL Studio: {executable}")
        report["stage"] = "cut"
        write_json(report_path, report)
        progress("[2/3] Checking resources and creating adaptive keysounds")
        outcome = cut(source, destination / "work", executable, initial_tail=initial_tail, max_tail=max_tail,
                      max_attempts=max_attempts, threshold_db=threshold_db, timeout=timeout,
                      channels=channels, midi_only=overrides or None, resource_dirs=resource_dirs,
                      deduplicate=deduplicate, arrangement_id=arrangement_id,
                      midi_only_reason=fallback_reason, progress=emit)
        report["cut_status"] = outcome["status"]
        report["midi_only_notes"] = outcome.get("midi_only_notes", 0)
        preserve_midi()
        if sha256_file(source) != document["source"]["sha256"]:
            raise FlpError("Input project changed during conversion; no chart will be published")
        if outcome["status"] == "midi_only":
            report.update(status="midi_only", stage="finished", audio_complete=False)
            emit("WARNING: No keyed audio is available. MIDI was preserved; no silent/empty BMS chart was generated.")
            progress("[3/3] BMS export skipped (MIDI-only result)")
        elif outcome["status"] == "complete":
            report["stage"] = "bms"
            write_json(report_path, report)
            progress("[3/3] Exporting 7-key BMS test chart")
            bms_report = export_bms(destination / "work/keysounds", destination / "chart",
                                    title=selected_title, artist=selected_artist, lead_in_bars=lead_in_bars,
                                    play_channels=play_channels, encoding=encoding)
            for message in bms_report["warnings"]:
                emit("WARNING: " + message)
            report.update(status="complete", stage="finished", chart="chart/" + bms_report["chart"],
                          audio_complete=bms_report["audio_complete"], playable_notes=bms_report["playable_notes"],
                          bgm_events=bms_report["bgm_events"], audio_events=bms_report["audio_events"],
                          keysounds=outcome["completed_keys"])
        else:
            raise FlpError(f"Adaptive cutting did not complete: {outcome['status']}")
        write_json(report_path, report)
        return report
    except (FlpError, OSError) as exc:
        preserve_midi()
        report.update(status="error", error=str(exc))
        write_json(report_path, report)
        raise
