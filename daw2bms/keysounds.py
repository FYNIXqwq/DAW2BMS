"""Isolated-note FLP banks and a reproducible mapping back to song events."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct

from .flp import FlpError, extract_file, read_events, text_value
from .midi import write_midi
from .resources import check_resources, generator_states


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def tick_to_frame(ticks: int, ppq: int, bpm: float, sample_rate: int) -> int:
    """Round absolute positions once; avoid accumulated per-slot rounding drift."""
    value = Fraction(ticks * 60 * sample_rate, ppq) / Fraction(str(bpm))
    return (value.numerator * 2 + value.denominator) // (2 * value.denominator)


def seconds_to_ticks(seconds: float, ppq: int, bpm: float) -> int:
    return math.ceil(Fraction(str(seconds)) * Fraction(str(bpm)) * ppq / 60)


def encode_event(event_id: int, payload: bytes) -> bytes:
    result = bytes([event_id])
    if event_id >= 192:
        size = len(payload)
        while size >= 128:
            result += bytes([(size & 127) | 128])
            size >>= 7
        result += bytes([size])
    return result + payload


def replace_vst_path(state: bytes, path: str) -> bytes:
    result = bytearray(state[:4])
    position = 4
    while position + 12 <= len(state):
        kind, size = struct.unpack_from("<IQ", state, position)
        position += 12
        if size > len(state) - position:
            raise FlpError("Invalid VST wrapper record while relocating its binary path")
        payload = path.encode("utf-8") if kind == 55 else state[position:position + size]
        result.extend(struct.pack("<IQ", kind, len(payload)))
        result.extend(payload)
        position += size
    result.extend(state[position:])
    return bytes(result)


def _bank_clip(pattern_id: int, length: int) -> bytes:
    return (struct.pack("<IHHIHHHHIiiI", 0, 20480, 20480 + pattern_id, length, 499, 0,
                        120, 64, 0x80806440, -1, -1, 1)
            + bytes(28) + struct.pack("<d", 1.0) + bytes(8))


def build_bank(source: Path, source_bytes: bytes, manifest: dict) -> bytes:
    """Modify only sequencing fields in a new file; retain opaque plugin state."""
    _, events = read_events(source_bytes)
    pattern_id = manifest["bank"]["pattern_id"]
    arrangement_id = manifest["arrangement_id"]
    length = manifest["bank"]["length_ticks"]
    notes = b"".join(struct.pack("<I", key["onset_ticks"]) + bytes.fromhex(key["note_record_hex"])[4:]
                     for key in manifest["keys"])
    # FL's CLI can end at the final populated bar, ignoring a stretched clip's
    # empty tail. A note on an EMPTY, DISABLED Sampler anchors the render end.
    # It is not a keysound and cannot produce audio, even in velocity-insensitive synths.
    anchor_channel = manifest["bank"]["anchor_channel_id"]
    notes += struct.pack("<IHHIHH8B", length - 1, 0x4000, anchor_channel, 1, 60, 0,
                         120, 0, 64, 0, 64, 0, 128, 128)
    neutralized = set(manifest.get("neutralized_channel_ids", []))
    resources = {r["channel_id"]: r for r in manifest.get("resources", [])}
    states = generator_states(source_bytes)
    sampler_wrapper = next((s[212] for s in states.values() if s.get(201) in (b"", b"\0\0") and 212 in s), None)
    current_pattern = current_channel = current_arrangement = None
    scope = "project"
    wrote_notes = wrote_playlist = False
    output = bytearray()
    anchor_inserted = False
    for e in events:
        payload = e.data
        if e.id == 99 and manifest["bank"]["add_anchor_channel"] and not anchor_inserted:
            for anchor_id, anchor_payload in [(64, struct.pack("<H", anchor_channel)), (21, b"\0"),
                    (201, b"\0\0"), (203, "DAW2BMS silent end anchor\0".encode("utf-16-le")),
                    (0, b"\0"), (196, b"\0\0")]:
                output.extend(encode_event(anchor_id, anchor_payload))
            anchor_inserted = True
        if e.id == 64:
            scope, current_channel = "channel", e.uint
        elif e.id == 65:
            scope, current_pattern = "pattern", e.uint
        elif e.id == 99:
            scope, current_arrangement = "arrangement", e.uint
        elif e.id == 98:
            scope = "mixer"
        if scope == "channel" and current_channel in neutralized:
            # Muting alone still loads a missing instrument/library. Turn only
            # the WORKING COPY's inactive channels into empty Samplers.
            if e.id == 213:
                continue
            if e.id == 212:
                if sampler_wrapper is None:
                    continue
                payload = sampler_wrapper
            elif e.id in (201, 196):
                payload = b"\0\0"
            elif e.id in (0, 21):
                payload = b"\0"
        elif e.id == 224 and scope == "pattern":
            payload = notes if current_pattern == pattern_id else b""
            wrote_notes |= current_pattern == pattern_id
        elif e.id == 26 and scope == "pattern":
            if current_pattern == pattern_id:
                payload = b"\0"  # Never enable channel/pattern looping in a bank.
        elif e.id == 164 and scope == "pattern" and current_pattern == pattern_id:
            payload = bytes(4)  # Auto length; the silent end anchor determines it.
        elif e.id == 193 and scope == "pattern" and current_pattern == pattern_id:
            payload = "DAW2BMS isolated keys\0".encode("utf-16-le")
        elif e.id == 233 and scope == "arrangement":
            payload = _bank_clip(pattern_id, length) if current_arrangement == arrangement_id else b""
            wrote_playlist |= current_arrangement == arrangement_id
        elif e.id == 241 and scope == "arrangement" and current_arrangement == arrangement_id:
            payload = "DAW2BMS render bank\0".encode("utf-16-le")
        elif e.id == 238 and scope == "arrangement":
            # Only track 1 has our generated bank clip.
            if struct.unpack_from("<I", payload)[0] == 1:
                payload = payload[:12] + b"\x01" + payload[13:]
        elif e.id == 67:
            payload = struct.pack("<H", pattern_id)
        elif e.id == 100:
            payload = struct.pack("<H", manifest["bank"]["arrangement_index"])
        elif e.id == 9 and scope == "project":
            payload = b"\x01"  # Song mode
        elif e.id == 169 and scope == "project" and manifest["bank"]["add_anchor_channel"]:
            payload = struct.pack("<I", e.uint + 1)
        elif e.id == 217:
            payload = struct.pack("<II", 0, 0)  # Clear render/playlist selection
        elif e.id == 152 and scope == "project":
            payload = bytes(4)
        elif e.id == 202 and scope == "project":
            # Do not carry the original machine's project folder into the copy.
            payload = (manifest["bank"]["directory"] + "\0").encode("utf-16-le")
        elif e.id == 196 and scope == "channel":
            sample = text_value(e)
            resolved_sample = resources.get(current_channel, {}).get("resolved_sample")
            if resolved_sample:
                payload = (resolved_sample + "\0").encode("utf-16-le")
            elif sample and "%" not in sample and not Path(sample).is_absolute():
                resolved = (source.parent / sample).resolve()
                if not resolved.is_file():
                    raise FlpError(f"Missing relative sample for channel {current_channel}: {sample}")
                payload = (str(resolved) + "\0").encode("utf-16-le")
        elif e.id == 213 and scope == "channel" and resources.get(current_channel, {}).get("resolved_vst"):
            payload = replace_vst_path(payload, resources[current_channel]["resolved_vst"])
        output.extend(encode_event(e.id, payload))
    if not wrote_notes or not wrote_playlist:
        raise FlpError("Cannot locate the note/playlist blocks required to build the render bank")
    header = bytearray(source_bytes[:18])
    if manifest["bank"]["add_anchor_channel"]:
        struct.pack_into("<H", header, 10, struct.unpack_from("<H", header, 10)[0] + 1)
    return header + struct.pack("<I", len(output)) + output


def prepare(source: Path, destination: Path, *, tail_seconds: float = 3.0, gap_seconds: float = 0.5,
            channels: set[int] | None = None, arrangement_id: int | None = None, deduplicate: bool = True,
            fl_exe: Path | None = None, resource_dirs: tuple[Path, ...] = (), midi_only: set[int] | None = None,
            tail_overrides: dict[str, float] | None = None, key_ids: set[str] | None = None) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise FlpError(f"Bank destination already exists; choose a new directory: {destination}")
    if not math.isfinite(tail_seconds) or tail_seconds < 0.1 or not math.isfinite(gap_seconds) or gap_seconds < 0.1:
        raise FlpError("Tail and gap must be finite and at least 0.1 seconds")
    document = extract_file(source)
    source_bytes = source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != document["source"]["sha256"]:
        raise FlpError("Source changed during extraction; retry with a stable file")
    project = document["project"]
    bpm, ppq = project["stored_tempo_bpm"], project["ppq"]
    if bpm is None or not 1 <= bpm <= 999:
        raise FlpError("A valid stored tempo is required")
    if project["swing_raw"] or any(w["code"] == "AUTOMATION_NOT_EVALUATED" for w in document["warnings"]):
        raise FlpError("Swing/automation requires contextual rendering and is not supported by isolated-note banks yet")
    if project["time_signature"] != {"numerator": 4, "denominator": 4}:
        raise FlpError("The initial render-bank implementation requires a fixed 4/4 project")
    arrangements = document["arrangements"]
    if not arrangements:
        raise FlpError("No Playlist arrangement to sample")
    arrangement = next((a for a in arrangements if a["id"] == arrangement_id), None) if arrangement_id is not None else arrangements[0]
    if arrangement is None:
        raise FlpError(f"Unknown arrangement {arrangement_id}")
    for a in arrangements:
        if a["markers"]:
            raise FlpError("Arrangement markers require explicit render-range handling; not yet supported")
    patterns = {p["id"]: p for p in document["patterns"]}
    known_channels = {c["id"] for c in document["channels"]}
    if channels is not None and (not channels or not channels <= known_channels):
        raise FlpError("--channels must name existing Channel Rack IDs")
    if midi_only is not None and not midi_only <= known_channels:
        raise FlpError("--midi-only must name existing Channel Rack IDs")
    for p in patterns.values():
        for marker in p["markers"]:
            if marker["position_ticks"] or marker["kind"] != "signature" or (marker["numerator"], marker["denominator"]) != (4, 4):
                raise FlpError("Changing pattern time signatures/markers is not supported in the render bank")
    for clip in arrangement["clips"]:
        if clip["kind"] != "pattern" or clip["expansion_status"] != "single_pass":
            raise FlpError("The selected arrangement must contain supported, single-pass Pattern clips only")
        if clip["flags_raw"] & ~0x8000 != 0x40:
            raise FlpError("A playlist clip has unverified flags/mute state; refusing to guess what should sound")
    timeline = [n for n in arrangement["timeline_notes"] if channels is None or n["channel_id"] in channels]
    if not timeline:
        raise FlpError("No placed notes match the selection")
    resources = check_resources(document, source, source_bytes, fl_exe=fl_exe,
                                resource_dirs=resource_dirs, midi_only=midi_only)
    missing_ids = {r["channel_id"] for r in resources if r["status"] == "midi_only"}
    fallback_notes = [n for n in timeline if n["channel_id"] in missing_ids]
    fallback_ids = {n["channel_id"] for n in fallback_notes}
    render_timeline = [n for n in timeline if n["channel_id"] not in missing_ids]
    rendered_channels = {n["channel_id"] for n in render_timeline}
    keys, mapped, seen = [], [], {}
    tail_ticks = seconds_to_ticks(tail_seconds, ppq, bpm)
    gap_ticks = seconds_to_ticks(gap_seconds, ppq, bpm)
    cursor = ppq * 4  # One full bar of silence for plugin/PDC diagnostics.
    for placement in render_timeline:
        if placement["overlaps_left_edge"] or placement["overlaps_right_edge"]:
            raise FlpError("A cropped sustained note requires contextual rendering; isolated-note duration would be ambiguous")
        if placement["channel_enabled"] is False or placement["track_enabled"] is False:
            raise FlpError("Disabled channels/tracks must be resolved explicitly before sampling this selection")
        note = patterns[placement["pattern_id"]]["notes"][placement["note_index"]]
        if note["slide"] or note["flags_raw"] not in (0, 0x4000):
            raise FlpError("Slide/unknown note flags require contextual rendering")
        raw = source_bytes[note["source_byte_offset"]:note["source_byte_offset"] + 24]
        signature = raw[4:] if deduplicate else (placement["clip_index"], placement["note_index"])
        if signature not in seen:
            key_id = f"k{len(keys) + 1:04d}"
            key_tail = (tail_overrides or {}).get(key_id, tail_seconds)
            if not math.isfinite(key_tail) or key_tail < 0.1:
                raise FlpError("Per-key tail windows must be finite and at least 0.1 seconds")
            key_tail_ticks = seconds_to_ticks(key_tail, ppq, bpm)
            key = {"id": key_id, "file": key_id + ".wav", "onset_ticks": cursor,
                   "cut_end_ticks": cursor + note["length_ticks"] + key_tail_ticks,
                   "tail_seconds_requested": key_tail,
                   "channel_id": note["channel_id"], "channel_name": placement["channel_name"],
                   "key": note["key"], "key_name_fl": note["key_name_fl"],
                   "length_ticks": note["length_ticks"], "velocity_raw": note["velocity_raw"],
                   "note_record_hex": raw.hex(), "source_notes": []}
            keys.append(key)
            seen[signature] = key
            cursor = math.ceil((key["cut_end_ticks"] + gap_ticks) / ppq) * ppq
        key = seen[signature]
        reference = {"pattern_id": placement["pattern_id"], "note_index": placement["note_index"]}
        if reference not in key["source_notes"]:
            key["source_notes"].append(reference)
        mapped.append({**placement, "key_id": key["id"], "key_file": key["file"]})
    if key_ids is not None:
        if not key_ids or not key_ids <= {k["id"] for k in keys}:
            raise FlpError("Adaptive retry requested unknown key IDs; resources or source may have changed")
        keys = [k for k in keys if k["id"] in key_ids]
        mapped = [n for n in mapped if n["key_id"] in key_ids]
        cursor = ppq * 4
        for key in keys:
            window = key["cut_end_ticks"] - key["onset_ticks"]
            key["onset_ticks"], key["cut_end_ticks"] = cursor, cursor + window
            cursor = math.ceil((key["cut_end_ticks"] + gap_ticks) / ppq) * ppq
        rendered_channels = {k["channel_id"] for k in keys}
    total_ticks = math.ceil(cursor / (ppq * 4)) * ppq * 4
    if total_ticks > 0x7fffffff:
        raise FlpError("Render bank exceeds the supported timeline length")
    first_pattern = next((p for p in patterns.values() if p["notes"] and p["length_ticks_declared"] is not None), None)
    if first_pattern is None:
        raise FlpError("No reusable Pattern note block and length metadata found")
    manifest = {
        "schema_version": 1, "bank_revision": 2, "kind": "daw2bms-isolated-note-bank",
        "source": document["source"], "arrangement_id": arrangement["id"],
        "timing": {"ppq": ppq, "bpm": bpm, "tail_seconds_requested": tail_seconds,
                   "gap_seconds_requested": gap_seconds, "tail_ticks": tail_ticks, "gap_ticks": gap_ticks},
        "bank": {"project": "render_bank.flp", "wav": "render_bank.wav", "directory": str(destination),
                 "pattern_id": first_pattern["id"], "arrangement_index": arrangements.index(arrangement),
                 "length_ticks": total_ticks},
        "deduplication": "identical_note_record_except_position" if deduplicate else "per_placement",
        "selected_channels": sorted(channels) if channels is not None else sorted({n["channel_id"] for n in timeline}),
        "keys": keys, "timeline": mapped, "resources": resources,
        "neutralized_channel_ids": sorted(known_channels - rendered_channels),
        "fallback": {"channel_ids": sorted(fallback_ids), "notes": fallback_notes,
                     "midi_file": "fallback.mid" if fallback_notes else None,
                     "json_file": "fallback_notes.json" if fallback_notes else None},
        "limitations": ["Fixed tempo and isolated notes. Automation, slide and context-dependent effects are not reproduced.",
            "Original generator, insert and master state is retained. Summed isolated renders can differ from the original mix.",
            "Deduplicated occurrences reuse one performance; use --no-dedupe for random/round-robin variations.",
            "FL export must use the complete song, WAV, insert/master FX enabled, and Trim PDC silence. No normalization.",
            "Cut positions preserve attack silence. No transient detection is used to move note timing."],
    }
    neutralized = sorted(known_channels - rendered_channels)
    manifest["bank"]["anchor_channel_id"] = neutralized[0] if neutralized else max(known_channels) + 1
    manifest["bank"]["add_anchor_channel"] = not bool(neutralized)
    bank_bytes = None
    if keys:
        bank_bytes = build_bank(source, source_bytes, manifest)
        read_events(bank_bytes)  # Validate event boundaries before writing any files.
        manifest["bank"]["sha256"] = hashlib.sha256(bank_bytes).hexdigest()
    else:
        manifest["bank"] = None
    destination.mkdir(parents=True)
    if bank_bytes is not None:
        (destination / "render_bank.flp").write_bytes(bank_bytes)
    manifest["midi_warnings"] = write_midi(destination / "song.mid", timeline, ppq, bpm)
    if fallback_notes:
        write_midi(destination / "fallback.mid", fallback_notes, ppq, bpm)
        write_json(destination / "fallback_notes.json", {"source": document["source"], "notes": fallback_notes,
                   "resources": [r for r in resources if r["channel_id"] in fallback_ids]})
    write_json(destination / "manifest.json", manifest)
    (destination / "render_instructions.txt").write_text(
        "DAW2BMS 独立键音采样工程\n\n"
        f"键音：{len(keys)}，映射到原曲的音符记录：{len(mapped)}，仅 MIDI：{len(fallback_notes)}\n"
        f"BPM：{bpm}，PPQ：{ppq}，预计工程时长：{total_ticks / ppq * 60 / bpm:.3f} 秒\n\n"
        "用 FL Studio 打开 render_bank.flp，按整首 Song 导出为 render_bank.wav。\n"
        "开启 insert/master effects 和 Trim PDC silence；关闭 normalization，不改变采样工程 BPM。\n"
        "建议 44.1/48 kHz、24-bit 或 32-bit float WAV。不要裁掉开头的预留静音。\n"
        "也可通过 python -m daw2bms render manifest.json --fl-exe <FL64.exe路径> 调用命令行渲染。\n"
        "随后 python -m daw2bms slice manifest.json。\n"
        "若切分检查发现尾音或间隔仍有声音，增大 prepare 的 --tail 后重新生成/渲染。\n"
        "缺失资源通道仅保留在 fallback.mid / fallback_notes.json 中，采样副本已禁用对应插件。\n"
        "song.mid 包含本次选中通道的全部音符；所有通道均缺失时不生成采样 FLP，也不启动渲染。\n"
        "此模式不保证独立音色相加后与有侧链/压缩/连奏的原混音等价。\n", encoding="utf-8")
    return manifest


def local_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        raise FlpError("Manifest paths must remain within the bank directory")
    return candidate


def load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["kind"] != "daw2bms-isolated-note-bank" or data["schema_version"] != 1:
            raise FlpError("Unsupported keysound manifest")
        timing = data["timing"]
        if not isinstance(timing["ppq"], int) or timing["ppq"] <= 0 or not 1 <= timing["bpm"] <= 999:
            raise FlpError("Invalid manifest timing")
        if not data["keys"]:
            if data["bank"] is None and data.get("fallback", {}).get("notes"):
                return data
            raise FlpError("Empty keysound bank")
        end = 0
        names = set()
        for key in data["keys"]:
            if Path(key["file"]).name != key["file"] or key["file"] in names or not key["file"].endswith(".wav"):
                raise FlpError("Invalid/duplicate keysound filename")
            names.add(key["file"])
            if not isinstance(key["onset_ticks"], int) or not isinstance(key["cut_end_ticks"], int) or not end < key["onset_ticks"] < key["cut_end_ticks"]:
                raise FlpError("Manifest key windows must be positive and ordered with gaps")
            end = key["cut_end_ticks"]
        bank_path = local_path(path.parent, data["bank"]["project"])
        if sha256_file(bank_path) != data["bank"]["sha256"]:
            raise FlpError("Render bank FLP changed after preparation; regenerate the manifest")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise FlpError(f"Malformed keysound manifest: {exc}") from exc
    return data
