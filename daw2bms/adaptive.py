"""Render, measure, and retry individual keys until their tails are isolated."""
from __future__ import annotations

from .i18n import msg

import math
import json
from pathlib import Path
import shutil

from .audio import render, slice_bank
from .flp import FlpError, extract_file
from .keysounds import load_manifest, prepare, sha256_file, write_json
from .resources import resource_warnings


def next_tail(check: dict, threshold_db: float, max_tail: float) -> float:
    current = check["release_tail_seconds"]
    slope = check.get("decay_db_per_second")
    level = 20 * math.log10(max(check["tail_peak"], 1e-12))
    if slope is not None and slope < -0.5 and level > threshold_db:
        extra = (level - threshold_db + 3) / -slope
        proposed = current + max(extra * 1.25, current * 0.25)
    else:
        proposed = current * 2
    # Never jump to a fixed number of seconds; grow from measured coverage.
    return min(max_tail, max(current * 1.25, min(proposed, current * 3)))


def _cut_impl(source: Path, destination: Path, fl_exe: Path | None, *, initial_tail: float = 1.0,
        max_tail: float = 30.0, max_attempts: int = 5, threshold_db: float = -60,
        timeout: float = 600, resume: Path | None = None, progress=print, **prepare_options) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise FlpError(msg('Choose a new adaptive output directory: {p0}', p0=destination))
    if not math.isfinite(initial_tail) or not math.isfinite(max_tail) or max_tail < initial_tail or initial_tail < 0.1 or max_attempts < 1:
        raise FlpError(msg('Invalid adaptive limits: max-tail >= initial-tail >= 0.1, max-attempts >= 1'))
    if not math.isfinite(threshold_db) or not -120 <= threshold_db <= -20:
        raise FlpError(msg('Silence threshold must be between -120 and -20 dBFS'))
    destination.mkdir(parents=True)
    status = {"status": "running", "attempts": [], "completed_keys": 0}
    write_json(destination / "result.json", status)
    accepted, key_reference, tails = {}, {}, {}
    pending = None
    first_manifest = None
    output_format = None
    for attempt in range(1, max_attempts + 1):
        attempt_dir = destination / f"attempt-{attempt:02d}"
        if attempt == 1 and resume is not None:
            manifest_path = resume.resolve()
            manifest = load_manifest(manifest_path)
            if manifest["source"]["sha256"] != sha256_file(source):
                raise FlpError(msg('Resume bank belongs to a different source file'))
            if manifest["bank"]:
                parsed_bank = extract_file(manifest_path.parent / manifest["bank"]["project"])
                bank_pattern = next(p for p in parsed_bank["patterns"] if p["id"] == manifest["bank"]["pattern_id"])
                if bank_pattern["looped"]:
                    raise FlpError(msg('Cannot resume an obsolete looping bank; prepare a new bank'))
            attempt_dir.mkdir()
            prepare_options.update(channels=set(manifest["selected_channels"]), arrangement_id=manifest["arrangement_id"],
                                   deduplicate=manifest["deduplication"] != "per_placement",
                                   midi_only=set(manifest.get("fallback", {}).get("channel_ids", [])))
            if "selected_tracks" in manifest:
                prepare_options["tracks"] = set(manifest["selected_tracks"])
        else:
            manifest = prepare(source, attempt_dir, tail_seconds=initial_tail, tail_overrides=tails,
                               key_ids=pending, fl_exe=fl_exe, **prepare_options)
            manifest_path = attempt_dir / "manifest.json"
        if first_manifest is None:
            first_manifest = manifest
            key_reference = {key["id"]: key for key in manifest["keys"]}
            for name in ("song.mid", "fallback.mid", "fallback_notes.json"):
                existing = manifest_path.parent / name
                if existing.is_file():
                    shutil.copy2(existing, destination / name)
            for warning in resource_warnings(manifest.get("resources", [])):
                progress(warning)
            if not key_reference:
                status.update(status="midi_only", midi_only_notes=len(manifest["fallback"]["notes"]))
                write_json(destination / "result.json", status)
                return status
        for key in manifest["keys"]:
            if key["note_record_hex"][8:] != key_reference[key["id"]]["note_record_hex"][8:]:
                raise FlpError(msg('Key identity changed between attempts; resources or source changed'))
        progress(msg('Attempt {p0}: {p1} keys; {p2} already validated.', p0=attempt, p1=len(manifest['keys']), p2=len(accepted)))
        if not (attempt == 1 and resume is not None):
            render(manifest_path, fl_exe, timeout=timeout)
        report = slice_bank(manifest_path, destination=attempt_dir / "validated", threshold_db=threshold_db, allow_partial=True)
        current_format = (report["samplerate"], report["channels"], report["output_subtype"])
        if output_format is not None and current_format != output_format:
            raise FlpError(msg('FL export audio format changed between attempts; cannot combine these renders'))
        output_format = current_format
        for key in report["keys"]:
            accepted[key["key_id"]] = {**key, "source_file": str(attempt_dir / "validated" / key["file"])}
        attempt_status = {"attempt": attempt, "manifest": str(manifest_path),
                          "accepted": len(report["keys"]), "failures": report["failures"], "next_tail_seconds": {}}
        status["attempts"].append(attempt_status)
        status["completed_keys"] = len(accepted)
        if len(accepted) == len(key_reference):
            final = destination / "keysounds"
            final.mkdir()
            for key_id in key_reference:
                key = accepted[key_id]
                shutil.copy2(key["source_file"], final / key["file"])
            write_json(final / "keysounds.json", {"status": "complete", "keys": list(accepted.values()),
                       "threshold_db": threshold_db, "samplerate": report["samplerate"], "channels": report["channels"],
                       "source": first_manifest["source"], "resources": first_manifest["resources"]})
            write_json(final / "timeline.json", {"timing": first_manifest["timing"],
                       "notes": first_manifest["timeline"], "midi_only_notes": first_manifest["fallback"]["notes"]})
            status.update(status="complete", midi_only_notes=len(first_manifest["fallback"]["notes"]))
            write_json(destination / "result.json", status)
            progress(msg('Complete: {p0} isolated keys; {p1} MIDI-only notes.', p0=len(accepted), p1=status['midi_only_notes']))
            return status
        retryable = {"tail_not_finished", "audio_in_guard_gap", "late_audio_after_tail"}
        if any(f["reason"] not in retryable for f in report["failures"]):
            status["status"] = "audio_error"
            write_json(destination / "result.json", status)
            raise FlpError(msg('Non-tail audio failure; see result.json. MIDI is retained; no complete keysound pack published.'))
        pending = set(key_reference) - set(accepted)
        checks = {c["key_id"]: c for c in report["checks"]}
        needs_longer = {f["key_id"] for f in report["failures"] if f["reason"] != "audio_in_guard_gap"}
        for key_id in pending:
            current = checks[key_id]["release_tail_seconds"]
            tails[key_id] = next_tail(checks[key_id], threshold_db, max_tail) if key_id in needs_longer else current
            if key_id in needs_longer and tails[key_id] <= current:
                status["status"] = "tail_limit"
                write_json(destination / "result.json", status)
                raise FlpError(msg('Key {p0} still sounds at the configured max-tail limit; MIDI retained.', p0=key_id))
        attempt_status["next_tail_seconds"] = {key: tails[key] for key in sorted(pending)}
        write_json(destination / "result.json", status)
        progress(msg('Retrying {p0} keys with measured tail windows; keeping {p1} validated keys.', p0=len(pending), p1=len(accepted)))
    status["status"] = "attempt_limit"
    write_json(destination / "result.json", status)
    raise FlpError(msg('Adaptive attempt limit reached; see result.json. MIDI and validated intermediate keys are retained.'))


def cut(source: Path, destination: Path, fl_exe: Path | None, **options) -> dict:
    existed = destination.exists()
    try:
        return _cut_impl(source, destination, fl_exe, **options)
    except (FlpError, OSError) as exc:
        result_path = destination / "result.json"
        if not existed and result_path.is_file():
            status = json.loads(result_path.read_text(encoding="utf-8"))
            if status["status"] == "running":
                status["status"] = "error"
            status["error"] = str(exc)
            write_json(result_path, status)
        raise
