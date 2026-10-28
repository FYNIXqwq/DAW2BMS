"""Standard MIDI File export without loading instruments or audio libraries."""
from __future__ import annotations

from .i18n import msg

from collections import defaultdict
from pathlib import Path
import struct

from .flp import FlpError


def vlq(value: int) -> bytes:
    if not 0 <= value <= 0x0fffffff:
        raise FlpError(msg('MIDI delta outside supported range: {p0}', p0=value))
    result = bytes([value & 127])
    value >>= 7
    while value:
        result = bytes([(value & 127) | 128]) + result
        value >>= 7
    return result


def meta(kind: int, data: bytes) -> bytes:
    return bytes([255, kind]) + vlq(len(data)) + data


def track(events: list[tuple[int, int, bytes]]) -> bytes:
    result = bytearray()
    last = 0
    for tick, priority, data in sorted(events, key=lambda e: (e[0], e[1])):
        result.extend(vlq(tick - last))
        result.extend(data)
        last = tick
    result.extend(b"\0\xff\x2f\0")
    return b"MTrk" + struct.pack(">I", len(result)) + result


def midi_bytes(notes: list[dict], ppq: int, bpm: float) -> tuple[bytes, list[str]]:
    if not 1 <= ppq <= 32767 or not 4 <= bpm <= 999:
        raise FlpError(msg('MIDI export needs PPQ <= 32767 and a representable tempo (4..999 BPM)'))
    microseconds = round(60000000 / bpm)
    conductor = track([(0, 0, meta(3, b"DAW2BMS")),
                       (0, 1, meta(0x51, microseconds.to_bytes(3, "big"))),
                       (0, 2, meta(0x58, bytes([4, 2, 24, 8])))])
    grouped = defaultdict(list)
    warnings = set()
    for note in notes:
        grouped[note["channel_id"]].append(note)
    tracks = [conductor]
    for index, (channel_id, channel_notes) in enumerate(sorted(grouped.items())):
        channel, port = index % 16, index // 16
        if port > 127:
            raise FlpError(msg('Too many independent MIDI ports'))
        name = f"{channel_id}: {channel_notes[0].get('channel_name') or 'Channel'}"
        events = [(0, 0, meta(3, name.encode("utf-8"))), (0, 1, meta(0x21, bytes([port])))]
        for note in channel_notes:
            key = note["key"]
            if not 0 <= key <= 127:
                warnings.add(msg('FL key {p0} is outside MIDI 0..127 and was not emitted; JSON retains it.', p0=key))
                continue
            onset = max(0, note["visible_start_ticks"])
            duration = note["visible_end_ticks"] - note["visible_start_ticks"]
            if note["length_ticks"] == 0:
                duration = max(1, ppq // 4)
                warnings.add(msg('Zero-length FL step triggers use a 1/16-note MIDI gate; original lengths remain in JSON.'))
            duration = max(1, duration)
            velocity = max(1, min(127, round(note["velocity_raw"] * 127 / 128)))
            if note["velocity_raw"] == 0:
                warnings.add(msg('Zero-velocity source notes are retained in JSON but omitted from MIDI (MIDI velocity 0 means note-off).'))
                continue
            events += [(onset, 3, bytes([0x90 | channel, key, velocity])),
                       (onset + duration, 2, bytes([0x80 | channel, key, 0]))]
        tracks.append(track(events))
    return (b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), ppq) + b"".join(tracks), sorted(warnings))


def write_midi(path: Path, notes: list[dict], ppq: int, bpm: float) -> list[str]:
    data, warnings = midi_bytes(notes, ppq, bpm)
    path.write_bytes(data)
    return warnings
