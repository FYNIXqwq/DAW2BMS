"""Generate isolated MIDI banks from copies of supported constant-tempo Sets."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import gzip
import math
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

from .als import AlsError, read_xml, value
from .i18n import msg
from .keysounds import sha256_file, write_json
from .als_plugins import plugin_requirements, verify_inventory
from .als_max import prepare_max, max_requirements


CONTAINERS = ("ClipTimeable/ArrangerAutomation/Events", "Sample/ArrangerAutomation/Events", "ArrangerAutomation/Events")


def set_value(node, path, val):
    current = node
    for part in path.split("/"):
        child = current.find(part)
        if child is None:
            child = ET.SubElement(current, part)
        current = child
    current.set("Value", str(val))


def active_automation(node):
    return any(e.get("Time") is not None and Fraction(e.get("Time")) >= 0
               for e in node.iter() if e.tag in ("FloatEvent", "BoolEvent", "EnumEvent"))


def resolve_samples(node, source, roots):
    """Only actual SampleRef references; old preset metadata is not a dependency."""
    for sample in node.iter("SampleRef"):
        for ref in sample.iter("FileRef"):
            absolute, relative = value(ref, "Path", ""), value(ref, "RelativePath", "")
            name = value(ref, "Name", "")
            candidates = [Path(absolute)] if absolute else []
            if relative:
                candidates += [source.parent / relative] + [root / relative for root in roots]
            if name:
                candidates += [source.parent / name] + [root / name for root in roots]
            match = next((p.resolve() for p in candidates if p.is_file()), None)
            if match is None:
                raise AlsError(msg("Missing or unresolved Ableton sample: {p0}", p0=absolute or relative or name or "SampleRef"))
            set_value(ref, "Path", str(match))
            set_value(ref, "RelativePathType", 0)
            set_value(ref, "RelativePath", "")


def prepare_track(root, document, track_id, source, resource_dirs=()):
    """Preserve static devices; require scanned VST IDs, including nested FX."""
    result = deepcopy(root)
    live = result.find("LiveSet")
    tracks = live.find("Tracks")
    track = next(t for t in tracks if t.get("Id") == str(track_id))
    info = next(t for t in document["tracks"] if t["id"] == track_id)
    if info["group_id"] != -1 or value(track, "DeviceChain/AudioOutputRouting/Target") not in ("AudioOut/Main", "AudioOut/Master"):
        raise AlsError(msg("ALS track {p0} uses unsupported group or cross-track routing; MIDI is preserved.", p0=track_id))
    devices = track.find("DeviceChain/DeviceChain/Devices")
    if devices is None or not len(devices):
        raise AlsError(msg("ALS track {p0} has no available instrument; MIDI is preserved.", p0=track_id))
    for other in list(tracks):
        if other is not track and other.tag != "ReturnTrack":
            tracks.remove(other)
    for owner in list(tracks) + [x for x in (live.find("MainTrack"), live.find("MasterTrack")) if x is not None]:
        if active_automation(owner):
            raise AlsError(msg("ALS track {p0} has automation or modulation that cannot be isolated; MIDI is preserved.", p0=track_id))
        for element in owner.iter():
            if element.tag == "AuPluginDevice":
                raise AlsError(msg("ALS track {p0} contains an unsupported Max or Audio Unit device; MIDI is preserved.", p0=track_id))
            if element.tag == "SideChain" and value(element, "On/Manual", "false") == "true":
                raise AlsError(msg("ALS track {p0} uses unsupported group or cross-track routing; MIDI is preserved.", p0=track_id))
        prepare_max(owner, source, resource_dirs)
        resolve_samples(owner, source, resource_dirs)
        verify_inventory(plugin_requirements(owner))
    # Restrict edits to sequencer containers. GroovePool contains MidiClip
    # objects too; removing those corrupts the groove definition in Live.
    for owner in tracks:
        scopes = [owner.find("DeviceChain/MainSequencer/" + p) for p in CONTAINERS]
        scopes += [owner.find(p) for p in ("DeviceChain/MainSequencer/ClipSlotList", "DeviceChain/FreezeSequencer", "TakeLanes")]
        for scope in (s for s in scopes if s is not None):
            for parent in list(scope.iter()):
                for child in list(parent):
                    if child.tag in ("MidiClip", "AudioClip"):
                        parent.remove(child)
    for node in tracks:
        set_value(node, "DeviceChain/Mixer/SoloSink", "false")
    set_value(live, "Transport/LoopOn", "false")
    set_value(live, "Transport/CurrentTime", 0)
    set_value(live, "SelectedDocumentViewInMainWindow", 0)
    return result


def make_keys(document, track_id, ppq, *, deduplicate=True):
    clips = {c["index"]: c for c in document["clips"]}
    keys, by_identity, timeline, fallback = [], {}, [], []
    for n in document["timeline_notes"]:
        if n["track_id"] != track_id or not n["midi_eligible"]:
            continue
        clip = clips[n["clip_index"]]
        # Reader diagnostics identify semantics we cannot relocate safely.
        bad_clip = any(w.get("clip_index") == n["clip_index"] for w in document["warnings"])
        start, end = Fraction(n["visible_start_beats"]) * ppq, Fraction(n["visible_end_beats"]) * ppq
        if bad_clip or n["boundary_clipped"] or Fraction(n["probability"]) != 1 or start < 0 or start.denominator != 1 or end.denominator != 1:
            fallback.append(n)
            continue
        # Clips may carry different program/scale state even when their notes
        # match. Reuse only within the same clip (including loop repetitions).
        identity = (n["clip_index"], n["key"], n["velocity"], n["off_velocity"], str(end-start))
        key = by_identity.get(identity) if deduplicate else None
        if key is None:
            ident = f"t{track_id}-k{len(keys):06d}"
            key = {"id": ident, "file": ident + ".wav", "channel_id": track_id, "key": n["key"],
                   "velocity": n["velocity"], "off_velocity": n["off_velocity"], "length_ticks": int(end-start),
                   "clip_index": n["clip_index"]}
            keys.append(key); by_identity[identity] = key
        timeline.append({**n, "arrangement_id": 0, "channel_id": track_id, "channel_name": n["track_name"],
                         "absolute_onset_ticks": int(start), "visible_start_ticks": int(start), "visible_end_ticks": int(end),
                         "length_ticks": int(end-start), "velocity_raw": float(Fraction(n["velocity"]) * 128 / 127),
                         "key_id": key["id"], "key_file": key["file"]})
    return keys, timeline, fallback


def write_bank(prepared, original, document, track_id, keys, directory, ppq, bpm, tails):
    directory.mkdir(parents=True)
    root = deepcopy(prepared)
    live = root.find("LiveSet")
    track = next(t for t in live.find("Tracks") if t.get("Id") == str(track_id))
    source_track = next(t for t in original.find("LiveSet/Tracks") if t.get("Id") == str(track_id))
    templates = [c for path in CONTAINERS for c in source_track.findall("DeviceChain/MainSequencer/" + path + "/MidiClip")]
    if not templates:
        raise AlsError(msg("ALS track {p0} has no available instrument; MIDI is preserved.", p0=track_id))
    main = track.find("DeviceChain/MainSequencer")
    container = next((main.find(p) for p in CONTAINERS if main.find(p) is not None), None)
    if container is None:
        raise AlsError(msg("Unrecognized ALS Arrangement container."))
    template_by_id = {c.get("Id"): c for c in templates}
    clip_info = {c["index"]: c for c in document["clips"]}
    cursor = ppq * 4  # One silent bar verifies there is no background source.
    bank_keys = []
    for index, key in enumerate(keys):
        tail = math.ceil(tails[key["id"]] * bpm / 60 * ppq)
        end = cursor + key["length_ticks"] + tail
        bank_keys.append({**key, "onset_ticks": cursor, "cut_end_ticks": end})
        template = template_by_id[str(clip_info[key["clip_index"]]["id"])]
        clip = deepcopy(template)
        clip.set("Id", str(index)); clip.set("Time", str(cursor / ppq))
        duration = key["length_ticks"] / ppq
        for path, val in (("CurrentStart", cursor / ppq), ("CurrentEnd", (cursor + key["length_ticks"]) / ppq),
                          ("Loop/LoopStart", 0), ("Loop/LoopEnd", duration), ("Loop/StartRelative", 0),
                          ("Loop/LoopOn", "false"), ("Loop/OutMarker", duration),
                          ("Loop/HiddenLoopStart", 0), ("Loop/HiddenLoopEnd", duration),
                          ("GrooveSettings/GrooveId", -1), ("Disabled", "false"), ("Name", key["id"])):
            set_value(clip, path, val)
        notes = clip.find("Notes")
        key_tracks = notes.find("KeyTracks"); key_tracks.clear()
        kt = ET.SubElement(key_tracks, "KeyTrack", Id="0")
        ET.SubElement(ET.SubElement(kt, "Notes"), "MidiNoteEvent", Time="0", Duration=str(duration),
                      Velocity=str(float(Fraction(key["velocity"]))), OffVelocity=str(float(Fraction(key["off_velocity"]))),
                      NoteId="0", IsEnabled="true", Probability="1")
        ET.SubElement(kt, "MidiKey", Value=str(key["key"]))
        set_value(notes, "NoteIdGenerator/NextId", 1)
        for path in ("PerNoteEventStore/EventLists", "NoteProbabilityGroups"):
            node = notes.find(path)
            if node is not None:
                node.clear()
        for env in clip.findall("Envelopes/Envelopes"):
            env.clear()
        container.append(clip)
        cursor = end + math.ceil(0.5 * bpm / 60 * ppq)
    bars = math.ceil(cursor / (ppq * 4))
    set_value(live, "Transport/LoopStart", 0); set_value(live, "Transport/LoopLength", bars * 4)
    filename = "daw2bms-" + uuid.uuid4().hex + ".als"
    project = directory / filename
    project.write_bytes(gzip.compress(ET.tostring(root, encoding="utf-8", xml_declaration=True), mtime=0))
    manifest = {"schema_version": 1, "kind": "daw2bms-isolated-note-bank", "daw": "ableton_live",
                "source": document["source"], "arrangement_id": 0, "timing": {"ppq": ppq, "bpm": bpm},
                "bank": {"project": filename, "wav": "render.wav", "sha256": sha256_file(project), "bars": bars},
                "keys": bank_keys, "timeline": [], "fallback": {"notes": []},
                "plugins": plugin_requirements(root), "max_devices": max_requirements(root)}
    write_json(directory / "manifest.json", manifest)
    return manifest
