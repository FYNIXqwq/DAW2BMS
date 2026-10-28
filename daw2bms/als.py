"""Bounded, read-only ALS import. Beat positions are exact rational strings.

Arrangement clips are read only from MainSequencer containers. Session clips,
frozen renders and take lanes are never silently added to the song timeline.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
import gzip
import hashlib
import io
import math
import zlib
from pathlib import Path
import xml.etree.ElementTree as ET

from .flp import FlpError
from .i18n import msg

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_TIMELINE_NOTES = 500000
MAX_LOOP_PASSES = 100000


class AlsError(FlpError):
    pass


def number(value, field: str, default=None) -> Fraction:
    if value is None:
        if isinstance(default, Fraction):
            return default
        value = default
    try:
        if value is None or len(str(value)) > 128:
            raise ValueError()
        decimal = Decimal(str(value))
        if not decimal.is_finite() or decimal.copy_abs() > 100000000 or decimal.as_tuple().exponent < -24:
            raise ValueError()
        return Fraction(decimal)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise AlsError(msg("Invalid ALS numeric value for {p0}: {p1}", p0=field, p1=value)) from exc


def value(node, path: str, default=None):
    child = node.find(path) if node is not None else None
    return child.get("Value", default) if child is not None else default


def boolean(value, field, default=False):
    if value is None:
        return default
    if str(value).lower() in ("true", "1"):
        return True
    if str(value).lower() in ("false", "0"):
        return False
    raise AlsError(msg("Invalid ALS boolean value for {p0}: {p1}", p0=field, p1=value))


def raw_events(node):
    if node is None:
        return []
    return [{"type": event.tag, "attributes": dict(event.attrib)} for event in node.iter()
            if event.tag in ("FloatEvent", "BoolEvent", "EnumEvent")]


def parameter_events(owner, parameter):
    if parameter is None:
        return []
    events = raw_events(parameter.find("ArrangerAutomation/Events"))
    target = parameter.find("AutomationTarget")
    if target is not None:
        for envelope in owner.findall("AutomationEnvelopes/Envelopes/AutomationEnvelope"):
            if value(envelope, "EnvelopeTarget/PointeeId") == target.get("Id"):
                events.extend(raw_events(envelope.find("Automation/Events")))
    return events


def decode_meter(encoded):
    code = number(encoded, "TimeSignature")
    if code.denominator != 1 or not 0 <= code < 99 * 8:
        raise AlsError(msg("Unsupported ALS time signature value: {p0}", p0=encoded))
    return {"numerator": int(code) % 99 + 1, "denominator": 2 ** (int(code) // 99)}


def read_xml(source: Path):
    if source.stat().st_size > MAX_FILE_BYTES:
        raise AlsError(msg("ALS file exceeds the size limit of {p0} bytes", p0=MAX_FILE_BYTES))
    with source.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise AlsError(msg("ALS file exceeds the size limit of {p0} bytes", p0=MAX_FILE_BYTES))
    try:
        if data.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                xml = stream.read(MAX_XML_BYTES + 1)
        else:
            xml = data
        if len(xml) > MAX_XML_BYTES:
            raise AlsError(msg("Decompressed ALS XML exceeds the size limit of {p0} bytes", p0=MAX_XML_BYTES))
        text = xml.decode("utf-8-sig")
        if "\0" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise AlsError(msg("ALS XML must be UTF-8 and must not contain DTD or entity declarations"))
        root = ET.fromstring(text)
    except (OSError, EOFError, UnicodeError, ET.ParseError, zlib.error) as exc:
        raise AlsError(msg("Cannot decode ALS XML: {p0}", p0=exc)) from exc
    if root.tag != "Ableton" or root.find("LiveSet") is None:
        raise AlsError(msg("Expected an Ableton LiveSet XML document"))
    return root, data, len(xml)


def extract_file(path: str | Path) -> dict:
    source = Path(path)
    root, original, xml_size = read_xml(source)
    live = root.find("LiveSet")
    warnings = []
    warning_keys = set()

    def warn(code, message, **context):
        key = (code, tuple(sorted(context.items())))
        if key not in warning_keys:
            warnings.append({"code": code, "message": message, **context})
            warning_keys.add(key)

    creator = root.get("Creator", "")
    version = root.get("MinorVersion", "")
    if not version.startswith(("11.", "12.")):
        warn("ALS_VERSION_UNVERIFIED", msg("ALS version {p0} is not validated; only recognized fields are imported", p0=version or creator))
    master = live.find("MainTrack")
    if master is None:
        master = live.find("MasterTrack")
    tempo_node = master.find("DeviceChain/Mixer/Tempo") if master is not None else None
    tempo_raw = value(tempo_node, "Manual")
    tempo_events = parameter_events(master, tempo_node) if master is not None else []
    tempo = number(tempo_raw, "Tempo", 120)
    points = []
    for event in tempo_events:
        attrs = event["attributes"]
        if event["type"] == "FloatEvent":
            points.append((number(attrs.get("Time"), "Tempo.Time"), number(attrs.get("Value"), "Tempo.Value")))
    before = [(time, order, bpm) for order, (time, bpm) in enumerate(points) if time <= 0]
    if before:
        tempo = max(before, key=lambda point: (point[0], point[1]))[2]
    elif tempo_raw is None:
        warn("ALS_DEFAULT_TEMPO", msg("ALS has no initial tempo; the MIDI file uses the standard default of 120 BPM"))
    tempo_changed = any(bpm != tempo for _, bpm in points)
    if tempo_changed:
        warn("ALS_TEMPO_AUTOMATION", msg("ALS tempo automation is retained in JSON; MIDI uses the initial tempo of {p0} BPM", p0=str(tempo)))
    if not 4 <= tempo <= 999:
        raise AlsError(msg("ALS initial tempo cannot be represented by this MIDI exporter: {p0}", p0=str(tempo)))

    signature_node = master.find("DeviceChain/Mixer/TimeSignature") if master is not None else None
    signature_raw = value(signature_node, "Manual", "201")
    meters = [{"time_beats": "0", **decode_meter(signature_raw)}]
    signature_events = parameter_events(master, signature_node) if master is not None else []
    meter_points = {}
    initial_meter = None
    for event in signature_events:
        if event["type"] != "EnumEvent":
            continue
        attrs = event["attributes"]
        beat = number(attrs.get("Time"), "TimeSignature.Time")
        meter = decode_meter(attrs.get("Value"))
        if beat <= 0:
            if initial_meter is None or beat >= initial_meter[0]:
                initial_meter = (beat, meter)
        else:
            meter_points[beat] = meter
    if initial_meter:
        meters[0].update(initial_meter[1])
    meters.extend({"time_beats": str(time), **meter} for time, meter in sorted(meter_points.items()))

    tracks, clips, timeline, recognized = [], [], [], set()
    track_ids = set()
    tracks_node = live.find("Tracks")
    if tracks_node is None:
        raise AlsError(msg("ALS LiveSet has no Tracks container"))
    for node in tracks_node:
        if not node.tag.endswith("Track"):
            continue
        ident = number(node.get("Id"), "Track.Id")
        if ident.denominator != 1 or ident < 0:
            raise AlsError(msg("Invalid ALS track identifier: {p0}", p0=node.get("Id")))
        track_id = int(ident)
        if track_id in track_ids:
            raise AlsError(msg("Duplicate ALS track identifier: {p0}", p0=track_id))
        track_ids.add(track_id)
        group_id = number(value(node, "TrackGroupId", "-1"), "TrackGroupId")
        if group_id.denominator != 1 or group_id < -1:
            raise AlsError(msg("Invalid ALS group hierarchy for track {p0}", p0=track_id))
        track = {"id": track_id, "kind": node.tag, "name": value(node, "Name/UserName") or value(node, "Name/EffectiveName") or node.tag,
                 "group_id": int(group_id),
                 "enabled": boolean(value(node, "DeviceChain/Mixer/Speaker/Manual"), "Speaker", True),
                 "solo": boolean(value(node, "DeviceChain/Mixer/SoloSink"), "SoloSink", False),
                 "automation": raw_events(node.find("AutomationEnvelopes")), "devices": [], "file_references": []}
        devices = node.find("DeviceChain/DeviceChain/Devices")
        if devices is not None:
            track["devices"] = [{"type": d.tag, "id": d.get("Id"), "name": value(d, "UserName"),
                                  "plugin_names": [e.get("Value") for e in d.iter() if e.tag in ("PlugName", "PluginName") and e.get("Value")]} for d in devices]
        for ref in node.iter("FileRef"):
            track["file_references"].append({tag: value(ref, tag) for tag in ("Path", "RelativePath", "RelativePathType", "Name")})
        tracks.append(track)
        main = node.find("DeviceChain/MainSequencer")
        if main is None:
            continue
        for container_path in ("ClipTimeable/ArrangerAutomation/Events", "Sample/ArrangerAutomation/Events", "ArrangerAutomation/Events"):
            container = main.find(container_path)
            if container is not None:
                for clip_node in container:
                    if clip_node.tag in ("MidiClip", "AudioClip"):
                        clips.append(parse_clip(clip_node, track_id, "arrangement", len(clips), warn))
                        recognized.add(clip_node)
        slots = main.find("ClipSlotList")
        if slots is not None:
            for clip_node in slots.iter():
                if clip_node.tag in ("MidiClip", "AudioClip"):
                    clips.append(parse_clip(clip_node, track_id, "session", len(clips), warn))
                    recognized.add(clip_node)

    track_map = {t["id"]: t for t in tracks}
    for track in tracks:
        enabled, visited, parent = track["enabled"], {track["id"]}, track["group_id"]
        while parent != -1:
            if parent in visited or parent not in track_map:
                raise AlsError(msg("Invalid ALS group hierarchy for track {p0}", p0=track["id"]))
            visited.add(parent)
            enabled &= track_map[parent]["enabled"]
            parent = track_map[parent]["group_id"]
        track["effective_enabled"] = enabled
    for clip in clips:
        if clip["scope"] == "arrangement" and clip["kind"] == "midi":
            expand_clip(clip, track_map[clip["track_id"]], timeline, warn)
    timeline.sort(key=lambda n: (Fraction(n["visible_start_beats"]), n["track_id"], n["clip_index"], n["note_index"]))
    frozen = {c for node in tracks_node for seq in node.findall("DeviceChain/FreezeSequencer") for c in seq.iter() if c.tag in ("MidiClip", "AudioClip")}
    takes = {c for seq in live.iter("TakeLanes") for c in seq.iter() if c.tag in ("MidiClip", "AudioClip")}
    unknown = [c for c in tracks_node.iter() if c.tag in ("MidiClip", "AudioClip") and c not in recognized | frozen | takes]
    if unknown:
        warn("ALS_UNPLACED_CLIPS", msg("{p0} ALS clips have unknown containers; their XML is retained but they are not placed on the Arrangement", p0=len(unknown)))
    sessions = sum(c["scope"] == "session" for c in clips)
    if sessions:
        warn("ALS_SESSION_NOT_ARRANGED", msg("{p0} Session clips are retained in JSON and are not assigned an invented playback order", p0=sessions))
    audio_count = sum(c["scope"] == "arrangement" and c["kind"] == "audio" for c in clips)
    if audio_count:
        warn("ALS_AUDIO_NOT_RENDERED", msg("{p0} Arrangement audio clips are inventoried only; no audio-to-MIDI inference or rendering is performed", p0=audio_count))
    if any(t["solo"] or t["automation"] for t in tracks):
        warn("ALS_TRACK_AUTOMATION", msg("ALS track automation and solo routing are retained but are not simulated in MIDI"))
    if not timeline:
        warn("ALS_EMPTY_ARRANGEMENT", msg("No Arrangement MIDI placements were produced; Session, audio and unplaced clips remain in JSON"))
    return {"schema_version": 1, "daw": "ableton_live",
            "source": {"file": source.name, "size_bytes": len(original), "sha256": hashlib.sha256(original).hexdigest()},
            "project": {"creator": creator, "saved_version": version, "xml_attributes": dict(root.attrib),
                        "time_unit": "quarter_note_beats", "beat_encoding": "exact rational string",
                        "tempo_manual": tempo_raw, "initial_tempo_bpm": str(tempo), "tempo_automation": tempo_events,
                        "tempo_export": "initial_only" if tempo_changed else "constant",
                        "time_signatures": meters, "time_signature_events": signature_events,
                        "master_automation": raw_events(master.find("AutomationEnvelopes")) if master is not None else []},
            "tracks": tracks, "clips": clips, "timeline_notes": timeline, "warnings": warnings,
            "unplaced_clip_xml": [ET.tostring(c, encoding="unicode") for c in unknown],
            "summary": {"tracks": len(tracks), "midi_tracks": sum(t["kind"] == "MidiTrack" for t in tracks),
                        "arrangement_clips": sum(c["scope"] == "arrangement" for c in clips), "session_clips": sessions,
                        "raw_midi_notes": sum(len(c["notes"]) for c in clips), "timeline_notes": len(timeline),
                        "eligible_midi_notes": sum(n["midi_eligible"] for n in timeline), "audio_clips": audio_count,
                        "ignored_freeze_clips": len(frozen), "ignored_take_clips": len(takes), "unplaced_clips": len(unknown),
                        "xml_bytes": xml_size}}


def parse_clip(node, track_id, scope, index, warn):
    kind = "midi" if node.tag == "MidiClip" else "audio"
    start = number(value(node, "CurrentStart", node.get("Time")), "CurrentStart", 0)
    end = number(value(node, "CurrentEnd"), "CurrentEnd", start)
    if scope == "arrangement" and (value(node, "CurrentStart", node.get("Time")) is None or value(node, "CurrentEnd") is None or end < start):
        raise AlsError(msg("Invalid ALS Arrangement clip bounds on track {p0}", p0=track_id))
    loop = {tag: value(node, "Loop/" + tag) for tag in ("LoopStart", "LoopEnd", "StartRelative", "LoopOn", "OutMarker", "HiddenLoopStart", "HiddenLoopEnd")}
    clip = {"index": index, "id": node.get("Id"), "track_id": track_id, "scope": scope, "kind": kind,
            "name": value(node, "Name"), "attributes": dict(node.attrib), "start_beats": str(start), "end_beats": str(end),
            "loop": loop, "disabled": boolean(value(node, "Disabled"), "Disabled"), "notes": [],
            "automation": raw_events(node.find("Envelopes")), "groove_id": value(node, "GrooveSettings/GrooveId", "-1"),
            "time_signature_xml": ET.tostring(node.find("TimeSignature"), encoding="unicode") if node.find("TimeSignature") is not None else None}
    if scope == "arrangement" and node.get("Time") is not None and number(node.get("Time"), "Clip.Time") != start:
        warn("ALS_CLIP_TIME_MISMATCH", msg("ALS clip {p0} has different Time and CurrentStart values; CurrentStart is used and both are retained", p0=index), clip_index=index)
    if kind == "audio":
        clip["sample_ref_xml"] = ET.tostring(node.find("SampleRef"), encoding="unicode") if node.find("SampleRef") is not None else None
        clip["warp_markers"] = [dict(e.attrib) for e in node.findall("WarpMarkers/WarpMarker")]
        clip["is_warped"] = value(node, "IsWarped")
        clip["expansion_status"] = "audio_inventory_only"
        return clip
    for key_track in node.findall("Notes/KeyTracks/KeyTrack"):
        key = number(value(key_track, "MidiKey"), "MidiKey")
        if key.denominator != 1 or not 0 <= key <= 127:
            raise AlsError(msg("Invalid ALS MIDI key: {p0}", p0=str(key)))
        for event in key_track.findall("Notes/MidiNoteEvent"):
            attrs = dict(event.attrib)
            time = number(attrs.get("Time"), "MidiNoteEvent.Time")
            duration = number(attrs.get("Duration"), "MidiNoteEvent.Duration")
            velocity = number(attrs.get("Velocity"), "MidiNoteEvent.Velocity", 100)
            release = number(attrs.get("OffVelocity"), "OffVelocity", 64)
            probability = number(attrs.get("Probability"), "Probability", 1)
            if duration < 0 or not 0 <= velocity <= 127 or not 0 <= release <= 127 or not 0 <= probability <= 1:
                raise AlsError(msg("Invalid ALS note range in clip {p0}", p0=index))
            clip["notes"].append({"index": len(clip["notes"]), "note_id": attrs.get("NoteId"), "key": int(key),
                                  "time_beats": str(time), "duration_beats": str(duration), "velocity": str(velocity),
                                  "off_velocity": str(release), "probability": str(probability),
                                  "enabled": boolean(attrs.get("IsEnabled"), "IsEnabled", True), "attributes": attrs})
    expressions = node.find("Notes/PerNoteEventStore")
    clip["note_expression_xml"] = ET.tostring(expressions, encoding="unicode") if expressions is not None else None
    has_expression = expressions is not None and any(event.attrib for event in expressions.iter())
    if clip["automation"] or has_expression or clip["groove_id"] != "-1" or value(node, "VelocityAmount", "0") != "0":
        warn("ALS_EXPRESSION_NOT_APPLIED", msg("ALS clip {p0}: groove, envelopes or note expression are retained but not applied to the MIDI notes", p0=index), clip_index=index)
    if any(Fraction(n["probability"]) not in (0, 1) or number(n["attributes"].get("VelocityDeviation"), "VelocityDeviation", 0) != 0 for n in clip["notes"]):
        warn("ALS_RANDOM_NOTES", msg("ALS clip {p0}: MIDI exports potential notes at base velocity; probability and velocity variation remain in JSON", p0=index), clip_index=index)
    clip["expansion_status"] = "session_inventory_only" if scope == "session" else "pending"
    return clip


def expand_clip(clip, track, output, warn):
    start, end = Fraction(clip["start_beats"]), Fraction(clip["end_beats"])
    loop = clip["loop"]
    left = number(loop["LoopStart"], "LoopStart", 0)
    right = number(loop["LoopEnd"], "LoopEnd", end - start + left)
    relative = number(loop["StartRelative"], "StartRelative", 0)
    looped = boolean(loop["LoopOn"], "LoopOn")
    source_start = left + relative if looped else left
    if looped and (right <= left or source_start >= right):
        clip["expansion_status"] = "unsupported_loop"
        warn("ALS_LOOP_UNSUPPORTED", msg("ALS clip {p0} has an unsupported loop window; raw notes are retained without guessed placement", p0=clip["index"]), clip_index=clip["index"])
        return
    if looped and math.ceil((end - start) / (right - left)) > MAX_LOOP_PASSES:
        raise AlsError(msg("ALS loop expansion exceeds the limit of {p0} passes", p0=MAX_LOOP_PASSES))
    windows = [(note, Fraction(note["time_beats"]), Fraction(note["duration_beats"])) for note in clip["notes"]]
    loop_windows = [(n, t, d) for n, t, d in windows if t < right and (t + d > left or d == 0 and t >= left)] if looped else windows
    cursor, repeat = start, 0
    while cursor < end:
        span = min(right - source_start, end - cursor) if looped else end - cursor
        source_end = source_start + span
        candidates = loop_windows if repeat else windows
        if repeat and not candidates:
            break
        for note, onset, duration in candidates:
            intersects = onset < source_end and onset + duration > source_start
            if duration == 0:
                intersects = source_start <= onset < source_end
            if not intersects:
                continue
            absolute = cursor + onset - source_start
            visible_start = max(cursor, absolute)
            visible_end = min(cursor + span, absolute + duration)
            clipped = visible_start != absolute or visible_end != absolute + duration
            enabled = track["effective_enabled"] and not clip["disabled"] and note["enabled"]
            eligible = enabled and duration > 0 and Fraction(note["velocity"]) > 0 and Fraction(note["probability"]) > 0
            output.append({"track_id": track["id"], "track_name": track["name"], "clip_index": clip["index"],
                           "clip_id": clip["id"], "note_index": note["index"], "note_id": note["note_id"], "repeat": repeat,
                           "key": note["key"], "velocity": note["velocity"], "off_velocity": note["off_velocity"],
                           "probability": note["probability"], "enabled": enabled, "midi_eligible": eligible,
                           "absolute_onset_beats": str(absolute), "duration_beats": str(duration),
                           "visible_start_beats": str(visible_start), "visible_end_beats": str(visible_end),
                           "boundary_clipped": clipped})
            if len(output) > MAX_TIMELINE_NOTES:
                raise AlsError(msg("ALS timeline exceeds the limit of {p0} notes", p0=MAX_TIMELINE_NOTES))
            if clipped:
                warn("ALS_BOUNDARY_NOTES", msg("ALS clip {p0}: MIDI uses clipped visible note spans; sustained-note chase may differ from Live", p0=clip["index"]), clip_index=clip["index"])
        cursor += span
        source_start = left
        repeat += 1
    clip["expansion_status"] = "loop_expanded" if looped else "single_pass"
