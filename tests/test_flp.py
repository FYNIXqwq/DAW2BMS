import contextlib
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

from daw2bms.__main__ import main
from daw2bms.flp import Event, FlpError, extract_file, parse_clips, parse_notes, read_events


def event(eid, payload):
    if isinstance(payload, int):
        payload = payload.to_bytes(3 if eid == 172 else (1, 2, 4)[eid // 64], "little")
    result = bytes([eid])
    if eid >= 192:
        size = len(payload)
        while size >= 128:
            result += bytes([(size & 127) | 128])
            size >>= 7
        result += bytes([size])
    return result + payload


def text(s):
    return (s + "\0").encode("utf-16-le")


def note(position=0, length=48, key=60, channel=0, flags=0x4000):
    return struct.pack("<IHHIHH8B", position, flags, channel, length, key, 0, 120, 0, 64, 0, 64, 100, 128, 128)


def clip(position=0, length=384, start=-1, end=-1, pattern=1, scale=1.0):
    return (struct.pack("<IHHIHHHHIiiI", position, 20480, 20480 + pattern, length, 499, 0, 120, 64,
                        0x80806440, start, end, 1) + bytes(28) + struct.pack("<d", scale) + bytes(8))


def envelope(stream):
    return struct.pack("<4sIHHH4sI", b"FLhd", 6, 0, 1, 96, b"FLdt", len(stream)) + stream


def fixture(notes=None, clips=None, looped=False, version="25.2.4.5242", channel_enabled=True, track_enabled=True):
    notes = note() if notes is None else notes
    clips = clip() if clips is None else clips
    stream = event(199, (version + "\0").encode()) + event(172, 257) + event(192, text("FL Studio " + version))
    stream += event(156, 130000) + event(17, 4) + event(18, 4) + event(30, 1)
    stream += event(65, 1) + event(224, notes)
    stream += event(64, 0) + event(21, 0) + event(203, text("鼓")) + event(0, int(channel_enabled))
    # Pattern metadata is emitted separately from note data.
    stream += event(65, 1) + event(193, text("旋律")) + event(164, 0) + event(26, int(looped))
    stream += event(99, 0) + event(241, text("编曲")) + event(233, clips)
    stream += event(238, struct.pack("<IIIB", 1, 0, 0, int(track_enabled)) + bytes(57))
    stream += event(239, text("轨道一"))
    # Mixer display names must not overwrite the last Channel Rack name.
    stream += event(98, 0) + event(203, text("Mixer effect"))
    return envelope(stream)


class ExtractorTests(unittest.TestCase):
    def extract(self, payload):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "样本.flp"
            p.write_bytes(payload)
            original = p.read_bytes()
            document = extract_file(p)
            self.assertEqual(p.read_bytes(), original)
            json.dumps(document, allow_nan=False)
            return document

    def test_new_event_alignment_and_pattern_identity(self):
        doc = self.extract(fixture())
        self.assertEqual(doc["project"]["stored_tempo_bpm"], 130)
        self.assertEqual(doc["summary"]["patterns"], 1)
        self.assertEqual(doc["patterns"][0]["name"], "旋律")
        self.assertEqual(doc["channels"][0]["name"], "鼓")
        self.assertEqual(doc["arrangements"][0]["tracks"][0]["name"], "轨道一")

    def test_fl26_profile_with_synthetic_fixture(self):
        doc = self.extract(fixture(version="26.1.7.5654"))
        self.assertEqual(doc["summary"]["pattern_notes"], 1)

    def test_pattern_offsets_are_integer_ticks(self):
        doc = self.extract(fixture(notes=note(1536) + note(1584), clips=clip(6144, 96, 1536, 1632)))
        timeline = doc["arrangements"][0]["timeline_notes"]
        self.assertEqual([n["absolute_onset_ticks"] for n in timeline], [6144, 6192])
        self.assertEqual(doc["arrangements"][0]["clips"][0]["source_start_ticks"], 1536)

    def test_repeated_placements_and_zero_length_trigger(self):
        doc = self.extract(fixture(notes=note(0, 0), clips=clip() + clip(384)))
        timeline = doc["arrangements"][0]["timeline_notes"]
        self.assertEqual([n["absolute_onset_ticks"] for n in timeline], [0, 384])
        self.assertTrue(all(n["zero_length_trigger"] and n["length_ticks"] == 0 for n in timeline))

    def test_clip_right_edge_is_exclusive(self):
        doc = self.extract(fixture(notes=note(0, 0) + note(96, 0), clips=clip(length=96)))
        self.assertEqual(doc["summary"]["timeline_notes"], 1)

    def test_overlapping_note_preserves_original_duration(self):
        doc = self.extract(fixture(notes=note(0, 192), clips=clip(384, 48, 96, 144)))
        n = doc["arrangements"][0]["timeline_notes"][0]
        self.assertEqual((n["absolute_onset_ticks"], n["length_ticks"]), (288, 192))
        self.assertEqual((n["visible_start_ticks"], n["visible_end_ticks"]), (384, 432))
        self.assertTrue(n["overlaps_left_edge"] and n["overlaps_right_edge"])
        self.assertFalse(n["onset_inside_clip"])

    def test_disabled_tracks_and_channels_are_retained(self):
        doc = self.extract(fixture(channel_enabled=False, track_enabled=False))
        n = doc["arrangements"][0]["timeline_notes"][0]
        self.assertFalse(n["track_enabled"])
        self.assertFalse(n["channel_enabled"])
        self.assertIsNone(n["clip_muted"])

    def test_unsupported_loop_scale_and_offsets_are_reported(self):
        for payload in (fixture(looped=True), fixture(clips=clip(scale=2)), fixture(clips=clip(start=0, end=200))):
            with self.subTest(payload=payload[:32]):
                doc = self.extract(payload)
                self.assertEqual(doc["summary"]["playlist_clips"], 1)
                self.assertEqual(doc["summary"]["timeline_notes"], 0)
                self.assertTrue(any(w["code"] == "CLIP_NOT_EXPANDED" for w in doc["warnings"]))

    def test_stride_is_not_guessed_from_divisibility(self):
        doc = self.extract(fixture(clips=clip() * 3))  # 240 is also divisible by 60!
        self.assertEqual(doc["summary"]["playlist_clips"], 3)

    def test_empty_song_and_channel_clip(self):
        doc = self.extract(fixture(notes=b"", clips=b""))
        self.assertEqual(doc["summary"]["timeline_notes"], 0)
        audio = bytearray(clip())
        struct.pack_into("<H", audio, 6, 0)
        doc = self.extract(fixture(clips=bytes(audio)))
        self.assertEqual(doc["arrangements"][0]["clips"][0]["kind"], "channel")
        self.assertEqual(doc["summary"]["timeline_notes"], 0)

    def test_malformed_data_is_rejected(self):
        cases = [b"FLhd", fixture()[:-1], envelope(b"\xc7\x80"),
                 envelope(event(199, b"25.2.4.5242\0") + b"\xe0\xff\xff\xff\xff\xff"),
                 fixture(notes=b"x"), fixture(clips=b"x"), fixture(notes=note(key=200)),
                 fixture(notes=note(channel=10)), fixture(clips=clip(pattern=9)), fixture(version="99.1.0.0")]
        for payload in cases:
            with self.subTest(size=len(payload)):
                with self.assertRaises(FlpError):
                    self.extract(payload)

    def test_header_ppq_and_lengths_are_validated(self):
        for offset, value in ((12, 0), (18, 0)):
            payload = bytearray(fixture())
            struct.pack_into("<H" if offset == 12 else "<I", payload, offset, value)
            with self.assertRaises(FlpError):
                read_events(bytes(payload))

    def test_cli_outputs_are_readable_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            source, out = Path(d) / "示例.flp", Path(d) / "输出"
            source.write_bytes(fixture())
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["extract", str(source), "--out", str(out)]), 0)
                self.assertEqual(main(["extract", str(source), "--out", str(out)]), 1)
                self.assertEqual(main(["extract", str(source), "--out", str(out), "--force"]), 0)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            doc = json.loads((out / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["summary"]["timeline_notes"], 1)
            with (out / "timeline_notes.csv").open(encoding="utf-8-sig", newline="") as f:
                self.assertEqual(next(csv.DictReader(f))["channel_name"], "鼓")
            self.assertEqual(len(list(out.iterdir())), 5)

    def test_two_arrangements_are_kept_separate(self):
        payload = fixture()
        stream = payload[22:] + event(99, 1) + event(241, text("第二编曲")) + event(233, clip(1000))
        stream += event(238, struct.pack("<IIIB", 1, 0, 0, 1) + bytes(57))
        doc = self.extract(envelope(stream))
        self.assertEqual(len(doc["arrangements"]), 2)
        self.assertEqual(doc["arrangements"][1]["timeline_notes"][0]["absolute_onset_ticks"], 1000)


class LocalSampleTests(unittest.TestCase):
    def test_external_flp_if_configured(self):
        configured = os.environ.get("DAW2BMS_TEST_FLP")
        if not configured:
            self.skipTest("Set DAW2BMS_TEST_FLP to opt into an external project integration test")
        sample = Path(configured).expanduser().resolve()
        original = sample.read_bytes()
        header, events = read_events(original)
        doc = extract_file(sample)
        self.assertEqual(doc["summary"]["channels"], header["channel_count_header"])
        self.assertEqual(doc["summary"]["pattern_notes"], sum(len(e.data) // 24 for e in events if e.id == 224))
        self.assertEqual(doc["summary"]["playlist_clips"], sum(len(e.data) // 80 for e in events if e.id == 233))
        for pattern in doc["patterns"]:
            for note in pattern["notes"]:
                position, flags, channel, length = struct.unpack_from("<IHHI", original, note["source_byte_offset"])
                self.assertEqual((note["position_ticks"], note["flags_raw"], note["channel_id"], note["length_ticks"]),
                                 (position, flags, channel, length))
        self.assertEqual(sample.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
