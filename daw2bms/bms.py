"""Export a constant-tempo 7-key BME test chart with exact FL tick placement."""
from __future__ import annotations

from .i18n import msg, tr

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
from math import gcd
from pathlib import Path
import re
import shutil
import wave

from .flp import FlpError
from .keysounds import local_path, sha256_file, write_json
from .midi import write_midi


LANES = ("11", "12", "13", "14", "15", "18", "19")
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def object_id(index: int) -> str:
    if not 1 <= index <= 1295:
        raise FlpError(msg('Classic base-36 BMS supports at most 1295 WAV definitions (01..ZZ)'))
    return ALPHABET[index // 36] + ALPHABET[index % 36]


def header_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise FlpError(msg('BMS title/artist must be nonempty single-line text'))
    return value.strip()


def data_lines(events: list[dict], ticks_per_measure: int) -> list[str]:
    """Multiple channel-01 rows retain simultaneous BGM; never overwrite events."""
    buckets = defaultdict(list)
    for event in events:
        measure, offset = divmod(event["bms_tick"], ticks_per_measure)
        if not 0 <= measure <= 999:
            raise FlpError(msg('BMS measure number exceeds 000..999; shorten the chart or lead-in'))
        channel = event["bms_channel"]
        rows = buckets[measure, channel]
        row = next((row for row in rows if offset not in row), None)
        if row is None:
            if channel != "01" and rows:
                raise FlpError(msg('Two playable notes occupy the same lane and tick'))
            row = {}
            rows.append(row)
        row[offset] = event["wav_id"]
    lines = []
    for (measure, channel), rows in sorted(buckets.items()):
        for row in rows:
            step = ticks_per_measure
            for tick in row:
                step = gcd(step, tick)
            slots = ticks_per_measure // step
            if slots > 65536:
                raise FlpError(msg('Exact BMS grid exceeds 65536 subdivisions in one measure'))
            cells = ["00"] * slots
            for tick, wav_id in row.items():
                cells[tick // step] = wav_id
            lines.append(f"#{measure:03d}{channel}:" + "".join(cells))
    return lines


def read_exported_events(chart: str, ppq: int) -> Counter:
    """Read back the restricted emitted format, independently of grid construction."""
    result = Counter()
    for line in chart.splitlines():
        match = re.fullmatch(r"#(\d{3})(01|11|12|13|14|15|18|19):([0-9A-Z]+)", line)
        if not match:
            continue
        measure, channel, cells = match.groups()
        if len(cells) % 2:
            raise FlpError(msg('Odd-length BMS object data'))
        count = len(cells) // 2
        for index in range(count):
            value = cells[index * 2:index * 2 + 2]
            if value != "00":
                tick = (Fraction(int(measure)) + Fraction(index, count)) * ppq * 4
                result[tick, channel, value] += 1
    return result


def export_bms(keysounds_dir: Path, destination: Path, *, title: str | None = None,
               artist: str = "Unknown", lead_in_bars: int = 1,
               play_channels: set[int] | None = None, encoding: str = "utf-8",
               unrendered_audio_clips: int = 0, play_tracks: set[int] | None = None) -> dict:
    root, destination = keysounds_dir.resolve(), destination.resolve()
    if destination.exists():
        raise FlpError(msg('Choose a new BMS package directory: {p0}', p0=destination))
    if not isinstance(lead_in_bars, int) or not 0 <= lead_in_bars <= 998:
        raise FlpError(msg('Lead-in must be an integer number of bars from 0 to 998'))
    if encoding not in ("utf-8", "cp932"):
        raise FlpError(msg('Supported BMS encodings: utf-8, cp932'))
    try:
        timeline = json.loads((root / "timeline.json").read_text(encoding="utf-8"))
        sounds = json.loads((root / "keysounds.json").read_text(encoding="utf-8"))
        if sounds["status"] != "complete":
            raise FlpError(msg('Only a complete, validated keysound package can be exported'))
        ppq = timeline["timing"]["ppq"]
        bpm = Decimal(str(timeline["timing"]["bpm"]))
        if not isinstance(ppq, int) or ppq <= 0 or not bpm.is_finite() or not 1 <= bpm <= 999:
            raise FlpError(msg('Invalid constant-tempo timing'))
        notes = timeline["notes"]
        missing = timeline.get("midi_only_notes", [])
        if not notes:
            raise FlpError(msg('No keyed audio notes available; keep the MIDI fallback until audio is available'))
        entries = {key["key_id"]: key for key in sounds["keys"]}
        if len(entries) != len(sounds["keys"]):
            raise FlpError(msg('Duplicate key IDs in keysounds.json'))
        arrangements = {n["arrangement_id"] for n in notes}
        if len(arrangements) != 1:
            raise FlpError(msg('Export one arrangement at a time'))
        available_channels = {n["channel_id"] for n in notes}
        known_channels = available_channels | {n["channel_id"] for n in missing}
        if play_channels is not None and not play_channels <= known_channels:
            raise FlpError(msg('--play-channels must refer to channels with available keyed audio'))
        if play_tracks is not None:
            known_tracks = {n.get("track_id") for n in notes + missing}
            if any("track_id" not in n for n in notes) or not play_tracks <= known_tracks:
                raise FlpError(msg("Track selections must refer to IDs in the selected Arrangement."))
        for note in notes:
            tick = note["absolute_onset_ticks"]
            if not isinstance(tick, int) or tick < 0:
                raise FlpError(msg('Note onsets must be nonnegative integer ticks'))
            if note.get("overlaps_left_edge") or note.get("overlaps_right_edge") or note.get("slide"):
                raise FlpError(msg('Cropped/slide playback semantics are not supported by this test-chart exporter'))
            if note.get("channel_enabled") is False or note.get("track_enabled") is False or note.get("clip_muted") is True:
                raise FlpError(msg('Disabled or muted notes cannot be silently exported as playable audio'))
            if note["key_id"] not in entries or note["key_file"] != entries[note["key_id"]]["file"]:
                raise FlpError(msg('Timeline key reference does not match the validated audio manifest'))
        used_keys = {note["key_id"] for note in notes}
        audio_info = {}
        for key_id in sorted(used_keys):
            entry = entries[key_id]
            source = local_path(root, entry["file"])
            if sha256_file(source) != entry["sha256"]:
                raise FlpError(msg('Keysound changed after validation: {p0}', p0=entry['file']))
            with wave.open(str(source), "rb") as audio:
                if audio.getsampwidth() not in (2, 3) or audio.getnchannels() not in (1, 2) or not audio.getnframes():
                    raise FlpError(msg('Player test export requires nonempty mono/stereo PCM 16/24-bit WAV'))
                if audio.getnframes() != entry["frames"]:
                    raise FlpError(msg('WAV frame count disagrees with keysound validation report'))
                audio_info[key_id] = {"source": source, "frames": audio.getnframes(),
                                      "rate": audio.getframerate(), "width": audio.getsampwidth()}
    except (KeyError, TypeError, InvalidOperation, json.JSONDecodeError, wave.Error) as exc:
        raise FlpError(msg('Invalid keysound package: {p0}', p0=exc)) from exc

    source_name = sounds.get("source", {}).get("file", "DAW2BMS")
    display_title = header_text(title or Path(source_name).stem) + " [AUTO TEST]"
    if missing or unrendered_audio_clips:
        display_title += " [MISSING AUDIO]"
    artist = header_text(artist)
    bar_ticks, shift = ppq * 4, lead_in_bars * ppq * 4
    ordered = sorted(enumerate(notes), key=lambda item: (item[1]["absolute_onset_ticks"],
                     item[1]["channel_id"], item[1]["key"], item[0]))
    channel_order = {channel: index for index, channel in enumerate(sorted(available_channels))}
    last_lane = [-1] * 7
    taken, current_tick = set(), None
    definitions, voice_pools, mapped = [], defaultdict(list), []
    last_sound_end = Fraction(0)
    for source_index, note in ordered:
        tick = note["absolute_onset_ticks"]
        if tick != current_tick:
            current_tick, taken = tick, set()
        candidates = [lane for lane in range(7) if lane not in taken]
        preferred = (channel_order[note["channel_id"]] + note["key"]) % 7
        background_track = play_tracks is not None and note["track_id"] not in play_tracks
        playable = candidates and not background_track and (play_channels is None or note["channel_id"] in play_channels)
        if playable:
            lane = min(candidates, key=lambda lane: (last_lane[lane], (lane - preferred) % 7))
            taken.add(lane)
            last_lane[lane] = tick
            channel, reason = LANES[lane], "playable"
        else:
            channel, reason = "01", ("background_track" if background_track else "background_channel"
                if play_channels is not None and note["channel_id"] not in play_channels else "chord_overflow")
        info = audio_info[note["key_id"]]
        onset = Fraction(tick * 60, ppq) / Fraction(bpm)
        duration = Fraction(info["frames"], info["rate"])
        # Separate filenames/IDs for overlapping reuses of the same sample keep
        # players that retrigger a WAV voice from cutting off its preceding tail.
        pool = voice_pools[note["key_id"]]
        voice = next((v for v in pool if v["busy_until"] <= onset), None)
        if voice is None:
            wav_id = object_id(len(definitions) + 1)
            definition = {"wav_id": wav_id, "file": f"audio/{wav_id}.wav", "key_id": note["key_id"],
                          "sha256": entries[note["key_id"]]["sha256"], "frames": info["frames"], "samplerate": info["rate"]}
            definitions.append(definition)
            voice = {"wav_id": wav_id, "busy_until": Fraction(0)}
            pool.append(voice)
        voice["busy_until"] = onset + duration
        last_sound_end = max(last_sound_end, (onset + duration) * Fraction(bpm) * ppq / 60 + shift)
        mapped.append({"source_index": source_index, "source_note": note,
                       "original_tick": tick, "bms_tick": tick + shift, "bms_channel": channel,
                       "wav_id": voice["wav_id"], "reason": reason})
    lines = ["*---------------------- HEADER ----------------------*", "#PLAYER 1", "#GENRE DAW2BMS TEST",
             f"#TITLE {display_title}", f"#ARTIST {artist}", f"#BPM {format(bpm, 'f')}",
             "#PLAYLEVEL 1", "#RANK 2", "#TOTAL 300", "#VOLWAV 100", "", "* Test chart: ungraded automatic lane allocation.",
             f"* Original ticks preserved; lead-in {lead_in_bars} measures; MIDI-only notes omitted from audio: {len(missing)}."]
    lines += [f"#WAV{d['wav_id']} {d['file']}" for d in definitions]
    lines += ["", "*----------------------- DATA -----------------------*"] + data_lines(mapped, bar_ticks)
    end_measure = max(int(last_sound_end // bar_ticks) + 1, max(e["bms_tick"] // bar_ticks for e in mapped) + 2)
    if end_measure > 999:
        raise FlpError(msg('Audio tail exceeds BMS measure 999'))
    lines += [f"#{end_measure:03d}01:00", ""]
    chart = "\r\n".join(lines)
    expected = Counter((Fraction(e["bms_tick"]), e["bms_channel"], e["wav_id"]) for e in mapped)
    if read_exported_events(chart, ppq) != expected:
        raise FlpError(msg('BMS round-trip validation failed: timing or note multiplicity changed'))
    try:
        encoded = chart.encode(encoding)
    except UnicodeEncodeError as exc:
        raise FlpError(msg('Metadata is not representable in the requested encoding; use --encoding utf-8')) from exc
    warnings = []
    if unrendered_audio_clips:
        warnings.append(msg("{p0} Arrangement audio clips are inventoried only; no audio-to-MIDI inference or rendering is performed", p0=unrendered_audio_clips))
    if missing:
        warnings.append(msg("{p0} MIDI-only notes have no keysounds and are omitted from this chart's audio. See fallback.mid / missing_notes.json.", p0=len(missing)))
    bgm = sum(e["bms_channel"] == "01" for e in mapped)
    if bgm == len(mapped):
        warnings.append(msg("This chart contains BGM only; no playable notes were selected or available."))
    report = {"status": "complete", "chart": "test.bme", "format": "7-key BME, ordinary notes, base36 WAV IDs",
              "title": display_title, "source": sounds.get("source"), "bpm": float(bpm), "ppq": ppq,
              "lead_in_bars": lead_in_bars, "lead_in_ticks": shift,
              "playable_notes": len(mapped) - bgm, "bgm_events": bgm, "audio_events": len(mapped),
              "midi_only_notes": len(missing), "audio_complete": not missing and not unrendered_audio_clips,
              "unique_keys": len(used_keys), "wav_definitions": len(definitions), "encoding": encoding,
              "warnings": warnings, "roundtrip": "Every audio event matched its original tick plus lead-in exactly",
              "play_tracks": sorted(play_tracks) if play_tracks is not None else None,
              "input_timeline_sha256": sha256_file(root / "timeline.json"),
              "input_keysounds_sha256": sha256_file(root / "keysounds.json")}
    destination.mkdir(parents=True)
    (destination / "audio").mkdir()
    for definition in definitions:
        shutil.copy2(audio_info[definition["key_id"]]["source"], destination / definition["file"])
    (destination / "test.bme").write_bytes(encoded)
    report["chart_sha256"] = sha256_file(destination / "test.bme")
    write_json(destination / "mapping.json", {"definitions": definitions, "events": mapped})
    if missing:
        write_midi(destination / "fallback.mid", missing, ppq, float(bpm))
        write_json(destination / "missing_notes.json", {"notes": missing, "timeline_offset_ticks": 0})
    write_json(destination / "export_report.json", report)
    instructions = [display_title, "",
        tr("Add this folder to your BMS player's song library, refresh it, and select test.bme. Keep the audio subfolder."),
        tr("7-key test chart; no scratch or long notes."),
        tr("Exported {p0} playable notes + {p1} BGM events; {p2} notes kept as MIDI only.", p0=report['playable_notes'], p1=bgm, p2=len(missing)),
        tr("BPM {p0}; lead-in bars: {p1}. Original note timing is not quantized.", p0=bpm, p1=lead_in_bars),
        tr("Use AUTO PLAY to check rhythm and audio before testing the key layout."),
        tr("PLAYLEVEL 1 is a placeholder, not a difficulty rating. The automatic layout has not been manually charted."),
        tr("MIDI fallback keeps original song positions without the lead-in. mapping.json traces every event to its source."),
        tr("Audio hashes and event timing were validated. The player GUI has not been tested automatically.")]
    (destination / "README.txt").write_text("\n".join(instructions) + "\n", encoding="utf-8")
    return report
