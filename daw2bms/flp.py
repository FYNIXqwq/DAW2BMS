"""A bounded, read-only FLP reader for the FL 25/26 event layout.

Only fields needed for musical structure are interpreted. See docs/flp-format.md
for observations, source references and unverified playback semantics.
"""
from __future__ import annotations

from .i18n import msg

from collections import Counter
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import struct


class FlpError(ValueError):
    """Invalid or unsupported FLP data; never silently resynchronise."""


@dataclass(frozen=True)
class Event:
    id: int
    offset: int
    data_offset: int
    data: bytes

    @property
    def uint(self) -> int:
        return int.from_bytes(self.data, "little")


def read_events(data: bytes) -> tuple[dict, list[Event]]:
    if len(data) < 22:
        raise FlpError(msg('Truncated FLP header (need at least 22 bytes)'))
    magic, size, fmt, channels, ppq = struct.unpack_from("<4sIHHH", data)
    if magic != b"FLhd" or size != 6 or fmt != 0 or data[14:18] != b"FLdt":
        raise FlpError(msg('Expected an FLP project with FLhd(6), format 0 and FLdt'))
    if not ppq:
        raise FlpError(msg('PPQ must be greater than zero'))
    if struct.unpack_from("<I", data, 18)[0] != len(data) - 22:
        raise FlpError(msg('FLdt length does not match file size'))

    events = []
    version = None
    pos = 22
    while pos < len(data):
        offset = pos
        event_id = data[pos]
        pos += 1
        # FL 25.2 uses a three-byte payload here, despite the DWORD range.
        # Do not search forward for plausible events after an error.
        if event_id == 172 and version and version[0] in (25, 26):
            length = 3
        elif event_id < 192:
            length = (1, 2, 4)[event_id // 64]
        else:
            length = 0
            for shift in range(0, 35, 7):
                if pos == len(data):
                    raise FlpError(msg('Truncated event length at byte {p0}', p0=offset))
                byte = data[pos]
                pos += 1
                length |= (byte & 127) << shift
                if byte < 128:
                    break
            else:
                raise FlpError(msg('Oversized event length at byte {p0}', p0=offset))
        if length > len(data) - pos:
            raise FlpError(msg('Event {p0} at byte {p1} exceeds FLdt boundary', p0=event_id, p1=offset))
        event = Event(event_id, offset, pos, data[pos:pos + length])
        if event_id == 199:
            try:
                version_text = event.data.decode("ascii").rstrip("\0")
                version = tuple(int(part) for part in version_text.split("."))
            except (ValueError, UnicodeError) as exc:
                raise FlpError(msg('Invalid FL version string')) from exc
            if len(version) != 4 or version[0] not in (25, 26):
                raise FlpError(msg('This prototype targets FL 25/26 saves, got {p0}', p0=version_text))
        if not version:
            raise FlpError(msg('Expected the FL version event before project data'))
        events.append(event)
        pos += length
    if not events:
        raise FlpError(msg('Empty FLdt event stream'))
    return {"channel_count_header": channels, "ppq": ppq,
            "saved_version": ".".join(map(str, version))}, events


def text_value(event: Event) -> str:
    try:
        return event.data.decode("utf-16-le").rstrip("\0")
    except UnicodeError as exc:
        raise FlpError(msg('Invalid UTF-16 text in event {p0} at byte {p1}', p0=event.id, p1=event.offset)) from exc


def parse_notes(event: Event) -> list[dict]:
    layout = struct.Struct("<IHHIHH8B")
    if len(event.data) % layout.size:
        raise FlpError(msg('Pattern notes at {p0} are not 24-byte records', p0=event.offset))
    result = []
    for index, fields in enumerate(layout.iter_unpack(event.data)):
        pos, flags, channel, length, key, group, fine, reserved, release, color, pan, velocity, mod_x, mod_y = fields
        if key > 131:
            raise FlpError(msg('Invalid FL key {p0} at note block {p1}', p0=key, p1=event.offset))
        result.append({
            "index": index, "channel_id": channel, "position_ticks": pos,
            "length_ticks": length, "key": key,
            "key_name_fl": ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[key % 12] + str(key // 12),
            "velocity_raw": velocity, "pan_raw": pan, "release_raw": release,
            "fine_pitch_raw": fine, "midi_channel_raw": color,
            "mod_x_raw": mod_x, "mod_y_raw": mod_y, "group": group,
            "flags_raw": flags, "reserved_raw": reserved, "slide": bool(flags & 8),
            "zero_length_trigger": length == 0,
            "source_byte_offset": event.data_offset + index * layout.size,
        })
    return result


def parse_clips(event: Event) -> list[dict]:
    stride = 80
    if len(event.data) % stride:
        raise FlpError(msg('Unsupported playlist record layout at byte {p0}: {p1} bytes, expected multiples of 80 for FL 25/26', p0=event.offset, p1=len(event.data)))
    result = []
    for index in range(len(event.data) // stride):
        offset = index * stride
        pos, base, item, length, reversed_track, group, u1, flags, u2 = struct.unpack_from("<IHHIHHHHI", event.data, offset)
        if base != 20480 or reversed_track > 499:
            raise FlpError(msg('Unsupported playlist record at byte {p0}', p0=event.data_offset + offset))
        raw_start, raw_end = struct.unpack_from("<II", event.data, offset + 24)
        is_pattern = item > base
        scale = struct.unpack_from("<d", event.data, offset + 64)[0]
        if not math.isfinite(scale) or scale <= 0:
            raise FlpError(msg('Invalid playlist scale at byte {p0}', p0=event.data_offset + offset))
        clip = {
            "index": index, "native_id": struct.unpack_from("<I", event.data, offset + 32)[0],
            "kind": "pattern" if is_pattern else "channel",
            "pattern_id": item - base if is_pattern else None,
            "channel_id": None if is_pattern else item,
            "track_id": 500 - reversed_track,
            "position_ticks": pos, "length_ticks": length, "end_ticks": pos + length,
            "group": group, "flags_raw": flags, "muted": None,
            "offset_start_bits": f"{raw_start:08x}", "offset_end_bits": f"{raw_end:08x}",
            "source_start_ticks": None, "source_end_ticks": None,
            "scale_raw": scale, "record_size": stride,
            "source_byte_offset": event.data_offset + offset,
            "uninterpreted_core": {"u1": u1, "u2": u2},
            "trailer_hex": event.data[offset + 32:offset + stride].hex(),
        }
        if is_pattern:
            # Pattern offsets are signed integer ticks, NOT float32. The same
            # storage is used differently by audio clips. FFFFFFFF means unset.
            start, end = struct.unpack_from("<ii", event.data, offset + 24)
            clip["source_start_ticks"] = None if start == -1 else start
            clip["source_end_ticks"] = None if end == -1 else end
        else:
            start, end = struct.unpack_from("<ff", event.data, offset + 24)
            clip["channel_offsets_raw_float"] = [v if math.isfinite(v) else None for v in (start, end)]
        result.append(clip)
    return result


def extract_file(path: str | Path) -> dict:
    source = Path(path)
    data = source.read_bytes()
    project, events = read_events(data)
    project.update(stored_tempo_bpm=None, time_signature={"numerator": None, "denominator": None},
                   play_truncated_notes=None, swing_raw=None)
    channels, patterns, arrangements = {}, {}, []
    current_channel = current_pattern = current_arrangement = current_track = marker = None
    scope = "project"
    warnings = []
    handled = Counter()

    def warn(code, message, **context):
        warnings.append({"code": code, "message": message, **context})

    for event in events:
        eid, value = event.id, event.uint if event.id < 192 else None
        used = True
        if eid == 199:
            pass
        elif eid == 64:
            scope = "channel"
            current_pattern = marker = None
            if value in channels:
                raise FlpError(msg('Duplicate channel id {p0}', p0=value))
            current_channel = {"id": value, "name": None, "type_raw": None,
                               "enabled": None, "plugin_internal_name": None, "sample_path": None}
            channels[value] = current_channel
        elif eid == 65:
            scope = "pattern"
            marker = None
            current_pattern = patterns.setdefault(value, {"id": value, "name": None,
                "length_ticks_declared": None, "looped": False, "notes": [], "markers": [],
                "controller_record_count": 0})
        elif eid == 99:
            scope = "arrangement"
            current_channel = current_pattern = current_track = marker = None
            if any(a["id"] == value for a in arrangements):
                raise FlpError(msg('Duplicate arrangement id {p0}', p0=value))
            current_arrangement = {"id": value, "name": None, "tracks": [], "clips": [], "markers": []}
            arrangements.append(current_arrangement)
        elif eid == 98:
            scope = "mixer"
            current_channel = current_pattern = current_track = marker = None
        elif eid == 156 and scope == "project":
            project["stored_tempo_bpm"] = value / 1000
        elif eid in (17, 18) and scope == "project":
            project["time_signature"]["numerator" if eid == 17 else "denominator"] = value
        elif eid == 30 and scope == "project":
            project["play_truncated_notes"] = bool(value)
        elif eid == 11 and scope == "project":
            project["swing_raw"] = value
        elif eid in (194, 206, 207) and scope == "project":
            project[{194: "title", 206: "genre", 207: "artist"}[eid]] = text_value(event)
        elif scope == "channel" and eid in (0, 21, 201, 203, 196):
            key = {0: "enabled", 21: "type_raw", 201: "plugin_internal_name", 203: "name", 196: "sample_path"}[eid]
            current_channel[key] = bool(value) if eid == 0 else value if eid == 21 else text_value(event)
        elif scope == "pattern" and eid in (193, 164, 26, 224, 223):
            if eid == 193:
                current_pattern["name"] = text_value(event)
            elif eid == 164:
                current_pattern["length_ticks_declared"] = value
            elif eid == 26:
                current_pattern["looped"] = bool(value)
            elif eid == 224:
                if current_pattern["notes"]:
                    raise FlpError(msg('Multiple note blocks for pattern {p0}', p0=current_pattern['id']))
                current_pattern["notes"] = parse_notes(event)
            else:
                if len(event.data) % 12:
                    raise FlpError(msg('Unsupported pattern controller layout'))
                current_pattern["controller_record_count"] += len(event.data) // 12
        elif scope == "arrangement" and eid == 241:
            current_arrangement["name"] = text_value(event)
        elif scope == "arrangement" and eid == 233:
            clips = parse_clips(event)
            for clip in clips:
                clip["index"] += len(current_arrangement["clips"])
            current_arrangement["clips"].extend(clips)
        elif scope == "arrangement" and eid == 238:
            if len(event.data) < 13:
                raise FlpError(msg('Truncated playlist track descriptor'))
            current_track = {"id": struct.unpack_from("<I", event.data)[0], "name": None,
                             "enabled": bool(event.data[12]), "source_byte_offset": event.data_offset}
            current_arrangement["tracks"].append(current_track)
            marker = None
        elif scope == "arrangement" and eid == 239 and current_track is not None:
            current_track["name"] = text_value(event)
        elif eid == 148 and scope in ("pattern", "arrangement"):
            marker = {"position_ticks": value & 0x7ffffff, "position_raw": value,
                      "kind": "signature" if value & 0x8000000 else "marker", "name": None,
                      "numerator": None, "denominator": None}
            (current_pattern if scope == "pattern" else current_arrangement)["markers"].append(marker)
        elif marker is not None and eid in (33, 34, 205):
            marker[{33: "numerator", 34: "denominator", 205: "name"}[eid]] = text_value(event) if eid == 205 else value
        else:
            used = False
        if used:
            handled[eid] += 1

    if len(channels) != project["channel_count_header"]:
        raise FlpError(msg('Channel count mismatch: header {p0}, decoded {p1}', p0=project['channel_count_header'], p1=len(channels)))
    for pattern in patterns.values():
        for note in pattern["notes"]:
            if note["channel_id"] not in channels:
                raise FlpError(msg('Pattern {p0} references missing channel {p1}', p0=pattern['id'], p1=note['channel_id']))
    if project["swing_raw"]:
        warn("SWING_NOT_APPLIED", msg('Global swing is present; exported ticks remain stored positions.'))
    if any(p["controller_record_count"] for p in patterns.values()) or any(c["type_raw"] == 5 for c in channels.values()):
        warn("AUTOMATION_NOT_EVALUATED", msg('Automation is present. Tempo and playback modulation are not evaluated.'))
    warn("STRUCTURAL_TIMELINE", msg('Timeline is a geometric, single-pass placement of stored notes, not a playback simulation. Clip mute flags, channel looping, swing, transposition and automation are not applied. No seconds are inferred.'))
    for arrangement in arrangements:
        track_ids = [t["id"] for t in arrangement["tracks"]]
        if len(track_ids) != len(set(track_ids)):
            raise FlpError(msg('Duplicate playlist track identifiers'))
        for clip in arrangement["clips"]:
            if clip["track_id"] not in track_ids:
                raise FlpError(msg('Clip references missing track {p0}', p0=clip['track_id']))
            references = patterns if clip["kind"] == "pattern" else channels
            ref_id = clip["pattern_id"] if clip["kind"] == "pattern" else clip["channel_id"]
            if ref_id not in references:
                raise FlpError(msg('Playlist clip references missing {p0} {p1}', p0=clip['kind'], p1=ref_id))
        arrangement["timeline_notes"] = expand_timeline(arrangement, patterns, channels, project["ppq"], warn)

    histogram = Counter(e.id for e in events)
    return {
        "schema_version": 1,
        "source": {"file": source.name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "project": project, "channels": list(channels.values()), "patterns": list(patterns.values()),
        "arrangements": arrangements, "warnings": warnings,
        "diagnostics": {"event_count": len(events), "event_counts": dict(sorted(histogram.items())),
            "uninterpreted_event_counts": {eid: count - handled[eid] for eid, count in sorted(histogram.items()) if count > handled[eid]}},
        "summary": {"channels": len(channels), "patterns": len(patterns),
                    "pattern_notes": sum(len(p["notes"]) for p in patterns.values()),
                    "arrangements": len(arrangements), "playlist_clips": sum(len(a["clips"]) for a in arrangements),
                    "timeline_notes": sum(len(a["timeline_notes"]) for a in arrangements)},
    }


def expand_timeline(arrangement: dict, patterns: dict, channels: dict, ppq: int, warn) -> list[dict]:
    """Place a single pattern pass per clip; retain provenance and overlap geometry.

    Durations and original onsets are never changed. Visible intersections are
    separate fields, since clip cropping is not equivalent to synth note-off.
    """
    notes = []
    tracks = {t["id"]: t for t in arrangement["tracks"]}
    for clip in arrangement["clips"]:
        clip["position_beats"] = clip["position_ticks"] / ppq
        clip["length_beats"] = clip["length_ticks"] / ppq
        if clip["kind"] != "pattern":
            clip["expansion_status"] = "not_a_pattern"
            continue
        pattern = patterns[clip["pattern_id"]]
        reason = None
        start = clip["source_start_ticks"] or 0
        source_end = clip["source_end_ticks"]
        end = start + clip["length_ticks"]
        if pattern["looped"]:
            reason = msg('Explicit pattern looping is not implemented.')
        elif clip["scale_raw"] != 1.0:
            reason = msg('Non-unit clip scaling is not implemented.')
        elif start < 0 or (source_end is not None and source_end != end):
            reason = msg('Source offsets disagree with the supported single-pass clip window.')
        if reason:
            clip["expansion_status"] = "unsupported"
            warn("CLIP_NOT_EXPANDED", reason, arrangement_id=arrangement["id"], clip_index=clip["index"])
            continue
        clip["expansion_status"] = "single_pass"
        for note in pattern["notes"]:
            onset, length = note["position_ticks"], note["length_ticks"]
            onset_inside = start <= onset < end
            overlaps = length > 0 and onset < end and onset + length > start
            if not (onset_inside or overlaps) or end <= start:
                continue
            absolute = clip["position_ticks"] + onset - start
            visible_start = max(clip["position_ticks"], absolute)
            visible_end = min(clip["end_ticks"], absolute + length)
            notes.append({
                "arrangement_id": arrangement["id"], "track_id": clip["track_id"],
                "clip_index": clip["index"], "pattern_id": pattern["id"], "note_index": note["index"],
                "channel_id": note["channel_id"], "channel_name": channels[note["channel_id"]]["name"],
                "key": note["key"], "key_name_fl": note["key_name_fl"], "velocity_raw": note["velocity_raw"],
                "slide": note["slide"], "zero_length_trigger": note["zero_length_trigger"],
                "pattern_position_ticks": onset, "absolute_onset_ticks": absolute,
                "length_ticks": length, "absolute_end_ticks": absolute + length,
                "absolute_onset_beats": absolute / ppq, "length_beats": length / ppq,
                "visible_start_ticks": visible_start, "visible_end_ticks": visible_end,
                "onset_inside_clip": onset_inside,
                "overlaps_left_edge": absolute < clip["position_ticks"],
                "overlaps_right_edge": absolute + length > clip["end_ticks"],
                "track_enabled": tracks[clip["track_id"]]["enabled"],
                "channel_enabled": channels[note["channel_id"]]["enabled"], "clip_muted": None,
            })
    return sorted(notes, key=lambda n: (n["absolute_onset_ticks"], n["track_id"], n["clip_index"], n["note_index"]))
