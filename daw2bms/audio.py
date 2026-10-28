"""Command-line FL rendering and sample-accurate cutting of isolated banks."""
from __future__ import annotations

from .i18n import msg

import math
import os
from pathlib import Path
import subprocess
import time

from .flp import FlpError
from .keysounds import load_manifest, local_path, sha256_file, tick_to_frame, write_json


def audio_modules():
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise FlpError(msg('Audio dependencies missing. Install with: python -m pip install -e ".[audio]"')) from exc
    return np, sf


def render(manifest_path: Path, fl_exe: Path, *, timeout: float = 600) -> dict:
    manifest_path, fl_exe = manifest_path.resolve(), fl_exe.resolve()
    manifest = load_manifest(manifest_path)
    if not manifest["keys"]:
        return {"status": "midi_only"}
    _, sf = audio_modules()
    if not fl_exe.is_file() or fl_exe.suffix.lower() != ".exe":
        raise FlpError(msg('FL Studio executable not found: {p0}', p0=fl_exe))
    if not math.isfinite(timeout) or timeout <= 0:
        raise FlpError(msg('Render timeout must be positive and finite'))
    root = manifest_path.parent
    project = local_path(root, manifest["bank"]["project"])
    wav = local_path(root, manifest["bank"]["wav"])
    if wav.exists():
        raise FlpError(msg('Render output already exists; use a fresh bank or move the existing WAV: {p0}', p0=wav))
    # A list with shell=False is intentional: no command interpolation and no
    # window automation. FL itself controls loading plugins and exporting WAV.
    command = [str(fl_exe), "/Ewav", "/R" + str(wav), str(project)]
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    start = time.monotonic()
    receipt_path = root / "render_receipt.json"
    receipt = {"status": "started", "bank_sha256": manifest["bank"]["sha256"], "command": command}
    write_json(receipt_path, receipt)
    with (root / "render.log").open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(command, cwd=fl_exe.parent, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=timeout, startupinfo=startupinfo, check=False)
        except subprocess.TimeoutExpired as exc:
            receipt.update(status="timeout", elapsed_seconds=time.monotonic() - start)
            write_json(receipt_path, receipt)
            raise FlpError(msg('FL command-line render timed out. A plugin or export dialog may be blocking it. The launched process was stopped; no UI automation was used. Check render.log or export render_bank.flp manually to render_bank.wav.')) from exc
    receipt.update(elapsed_seconds=time.monotonic() - start, exit_code=result.returncode)
    if result.returncode != 0 or not wav.is_file():
        receipt["status"] = "failed"
        write_json(receipt_path, receipt)
        raise FlpError(msg('FL render did not produce the expected WAV (exit {p0}). See {p1}', p0=result.returncode, p1=root / 'render.log'))
    try:
        info = sf.info(wav)
    except (RuntimeError, OSError) as exc:
        receipt["status"] = "invalid_wav"
        write_json(receipt_path, receipt)
        raise FlpError(msg('FL output is not a readable audio file')) from exc
    required = tick_to_frame(manifest["keys"][-1]["cut_end_ticks"], manifest["timing"]["ppq"],
                             manifest["timing"]["bpm"], info.samplerate)
    if info.frames < required:
        receipt.update(status="too_short", frames=info.frames, required_frames=required)
        write_json(receipt_path, receipt)
        raise FlpError(msg('Rendered WAV is too short. Check Song mode and the render selection/range.'))
    receipt.update(status="rendered", wav_sha256=sha256_file(wav), samplerate=info.samplerate,
                   channels=info.channels, frames=info.frames, subtype=info.subtype)
    write_json(receipt_path, receipt)
    return receipt


def slice_bank(manifest_path: Path, *, wav_path: Path | None = None, destination: Path | None = None,
               threshold_db: float = -60, tail_pad_ms: float = 20, fade_ms: float = 3,
               subtype: str = "PCM_24", offset_ms: float = 0, allow_partial: bool = False) -> dict:
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    if not manifest["keys"]:
        return {"status": "midi_only"}
    np, sf = audio_modules()
    root = manifest_path.parent
    wav_path = (wav_path or local_path(root, manifest["bank"]["wav"])).resolve()
    destination = (destination or root / "keysounds").resolve()
    if destination.exists():
        raise FlpError(msg('Keysound output already exists; choose a fresh --out: {p0}', p0=destination))
    if not math.isfinite(threshold_db) or not -120 <= threshold_db <= -20:
        raise FlpError(msg('Silence threshold must be between -120 and -20 dBFS'))
    if any(not math.isfinite(v) or v < 0 or v > 1000 for v in (tail_pad_ms, fade_ms)):
        raise FlpError(msg('Tail padding and fade must be between 0 and 1000 ms'))
    if not math.isfinite(offset_ms) or abs(offset_ms) > 10000:
        raise FlpError(msg('Alignment offset must be finite and within +/- 10 seconds'))
    if subtype not in ("PCM_16", "PCM_24", "FLOAT"):
        raise FlpError(msg('Supported WAV output types: PCM_16, PCM_24, FLOAT'))
    threshold = 10 ** (threshold_db / 20)
    timing = manifest["timing"]
    checks, failures = [], []
    try:
        audio = sf.SoundFile(wav_path)
    except (RuntimeError, OSError) as exc:
        raise FlpError(msg('Cannot read render WAV: {p0}', p0=wav_path)) from exc
    with audio:
        if audio.format not in ("WAV", "WAVEX", "RF64") or audio.channels not in (1, 2):
            raise FlpError(msg('Expected mono/stereo WAV, WAVEX or RF64'))
        rate = audio.samplerate
        offset = round(offset_ms * rate / 1000)
        frame_at = lambda tick: tick_to_frame(tick, timing["ppq"], timing["bpm"], rate) + offset
        required = frame_at(manifest["keys"][-1]["cut_end_ticks"])
        if audio.frames < required:
            raise FlpError(msg('Render is too short: {p0} frames, need at least {p1}', p0=audio.frames, p1=required))
        check_frames = max(1, round(rate * 0.05))
        padding = round(rate * tail_pad_ms / 1000)
        fade = round(rate * fade_ms / 1000)
        previous_end = 0
        previous_key = None
        for key in manifest["keys"]:
            start, end = frame_at(key["onset_ticks"]), frame_at(key["cut_end_ticks"])
            if start < 0 or end <= start:
                raise FlpError(msg('Alignment offset produces invalid sample windows'))
            audio.seek(start)
            samples = audio.read(end - start, dtype="float32", always_2d=True)
            if not np.isfinite(samples).all():
                failures.append({"key_id": key["id"], "reason": "non_finite_audio"})
                continue
            magnitude = np.max(np.abs(samples), axis=1)
            peak = float(magnitude.max(initial=0))
            active = np.flatnonzero(magnitude > threshold)
            tail_peak = float(magnitude[-check_frames:].max(initial=0))
            # Check the entire quiet gap, not just the last few milliseconds.
            audio.seek(previous_end)
            gap = audio.read(start - previous_end, dtype="float32", always_2d=True)
            gap_peak = float(np.abs(gap).max(initial=0))
            if not np.isfinite(gap).all():
                failures.append({"key_id": key["id"], "reason": "non_finite_gap"})
            if not len(active):
                failures.append({"key_id": key["id"], "reason": "silent_key", "peak": peak})
            if tail_peak > threshold:
                failures.append({"key_id": key["id"], "reason": "tail_not_finished", "peak": tail_peak})
            if gap_peak > threshold:
                failures.append({"key_id": key["id"], "reason": "audio_in_guard_gap", "peak": gap_peak})
                if previous_key is not None:
                    failures.append({"key_id": previous_key, "reason": "late_audio_after_tail", "peak": gap_peak})
            if subtype != "FLOAT" and peak >= 1:
                failures.append({"key_id": key["id"], "reason": "would_clip_pcm", "peak": peak})
            # Preserve all leading/attack silence. Trim only trailing silence,
            # retain padding, and put the fade inside that padding when possible.
            retained = min(len(samples), int(active[-1]) + 1 + max(padding, fade)) if len(active) else len(samples)
            # Estimate only the observed late envelope. Flat/rising envelopes
            # deliberately yield no prediction and the adaptive driver uses
            # bounded geometric growth instead of inventing an end time.
            release_frame = frame_at(key["onset_ticks"] + key["length_ticks"]) - start
            envelope_start = max(release_frame, len(magnitude) - round(rate * 1.5))
            block = max(1, round(rate * 0.1))
            levels = [20 * math.log10(max(float(magnitude[i:i + block].max(initial=0)), 1e-12))
                      for i in range(envelope_start, len(magnitude), block)]
            slope = float(np.polyfit(np.arange(len(levels)) * block / rate, levels, 1)[0]) if len(levels) >= 4 else None
            checks.append({"key_id": key["id"], "file": key["file"], "start_frame": start,
                           "window_end_frame": end, "frames": retained, "peak": peak,
                           "first_active_frame": int(active[0]) if len(active) else None,
                           "last_active_frame": int(active[-1]) if len(active) else None,
                           "tail_peak": tail_peak, "guard_peak": gap_peak,
                           "decay_db_per_second": slope,
                           "release_tail_seconds": (key["cut_end_ticks"] - key["onset_ticks"] - key["length_ticks"]) / timing["ppq"] * 60 / timing["bpm"]})
            previous_end = end
            previous_key = key["id"]
        report = {"schema_version": 1, "status": "failed" if failures else "validated",
                  "input_wav": str(wav_path), "input_wav_sha256": sha256_file(wav_path),
                  "manifest_sha256": sha256_file(manifest_path), "samplerate": rate,
                  "channels": audio.channels, "source_subtype": audio.subtype,
                  "output_subtype": subtype, "threshold_db": threshold_db,
                  "offset_ms": offset_ms, "tail_pad_ms": tail_pad_ms, "fade_ms": fade_ms,
                  "keys": checks, "checks": checks, "failures": failures}
        if failures:
            # A failed check is a diagnostic, never a partial success package.
            write_json(root / "slice_diagnostics.json", report)
            reasons = sorted({f["reason"] for f in failures})
            if not allow_partial:
                raise FlpError(msg("Audio validation failed ({p0} findings: {p1}). No keysounds written. See slice_diagnostics.json; use 'cut' for adaptive tail retries.", p0=len(failures), p1=', '.join(reasons)))
            failed_ids = {f["key_id"] for f in failures}
            checks = [c for c in checks if c["key_id"] not in failed_ids]
            report["keys"] = checks
        destination.mkdir(parents=True)
        for check in checks:
            audio.seek(check["start_frame"])
            samples = audio.read(check["frames"], dtype="float32", always_2d=True)
            fade_count = min(fade, len(samples) - check["last_active_frame"] - 1)
            if fade_count:
                samples[-fade_count:] *= np.linspace(1, 0, fade_count, dtype=np.float32)[:, None]
            key_path = destination / check["file"]
            sf.write(key_path, samples, rate, subtype=subtype, format="WAV")
            check["sha256"] = sha256_file(key_path)
        write_json(destination / "timeline.json", {"source": manifest["source"], "arrangement_id": manifest["arrangement_id"],
                   "timing": timing, "notes": manifest["timeline"], "midi_only_notes": manifest.get("fallback", {}).get("notes", [])})
        report["status"] = "partial" if failures else "complete"
        write_json(destination / "keysounds.json", report)
    return report
