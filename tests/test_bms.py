from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave

from daw2bms.bms import LANES, export_bms, object_id, read_exported_events
from daw2bms.flp import FlpError


class BmsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pack = self.root / "input"
        self.pack.mkdir()
        self.out = self.root / "chart"

    def tearDown(self):
        self.tmp.cleanup()

    def package(self, ticks=(0, 32, 96), missing=False, ppq=96):
        wav = self.pack / "key.wav"
        with wave.open(str(wav), "wb") as audio:
            audio.setparams((1, 2, 1000, 100, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x10" * 100)
        notes = [{"arrangement_id": 0, "absolute_onset_ticks": t, "channel_id": 0, "channel_name": "Test",
                  "key_id": "key", "key_file": "key.wav", "key": 60, "length_ticks": 24,
                  "visible_start_ticks": t, "visible_end_ticks": t + 24, "velocity_raw": 100,
                  "clip_index": 0, "pattern_id": 1, "note_index": i} for i, t in enumerate(ticks)]
        timeline = {"timing": {"ppq": ppq, "bpm": 120}, "notes": notes,
                    "midi_only_notes": [dict(notes[0], channel_id=1)] if missing else []}
        report = {"status": "complete", "source": {"file": "test.flp"}, "keys": [
            {"key_id": "key", "file": "key.wav", "frames": 100, "sha256": hashlib.sha256(wav.read_bytes()).hexdigest()}]}
        (self.pack / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
        (self.pack / "keysounds.json").write_text(json.dumps(report), encoding="utf-8")
        return timeline, report

    def test_exact_subdivision_and_lead_in(self):
        self.package(ticks=(0, 1, 32, 383, 384))
        report = export_bms(self.pack, self.out)
        events = read_exported_events((self.out / "test.bme").read_text(), 96)
        self.assertEqual(sorted(t for t, channel, wav in events.elements()), [384, 385, 416, 767, 768])
        self.assertEqual(report["audio_events"], 5)
        self.assertEqual(report["lead_in_ticks"], 384)
        mapping = json.loads((self.out / "mapping.json").read_text())
        self.assertEqual(mapping['schema_version'], 2)
        self.assertEqual(mapping['ppq'], 96)
        self.assertEqual(mapping['chart_sha256'], report['chart_sha256'])

    def test_chord_overflow_uses_parallel_bgm_without_losing_notes(self):
        self.package(ticks=(0,) * 10)
        report = export_bms(self.pack, self.out)
        parsed = read_exported_events((self.out / "test.bme").read_text(), 96)
        self.assertEqual(report["playable_notes"], 7)
        self.assertEqual(report["bgm_events"], 3)
        self.assertEqual(sum(parsed.values()), 10)
        self.assertEqual({channel for _, channel, _ in parsed if channel != "01"}, set(LANES))
        self.assertEqual(sum(line.startswith("#00101:") for line in (self.out / "test.bme").read_text().splitlines()), 3)

    def test_overlapping_sample_reuse_gets_distinct_voices(self):
        self.package(ticks=(0, 1, 96))
        report = export_bms(self.pack, self.out)
        mapping = json.loads((self.out / "mapping.json").read_text())
        ids = [e["wav_id"] for e in mapping["events"]]
        self.assertEqual(report["wav_definitions"], 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual(ids[0], ids[2])
        self.assertEqual((self.out / "audio/01.wav").read_bytes(), (self.out / "audio/02.wav").read_bytes())

    def test_missing_audio_keeps_midi_and_marks_title(self):
        self.package(missing=True)
        report = export_bms(self.pack, self.out)
        self.assertFalse(report["audio_complete"])
        self.assertEqual(report["audio_events"], 3)
        self.assertTrue(report["warnings"])
        self.assertIn("MISSING AUDIO", (self.out / "test.bme").read_text())
        self.assertTrue((self.out / "fallback.mid").read_bytes().startswith(b"MThd"))
        self.assertEqual(json.loads((self.out / "missing_notes.json").read_text())["notes"][0]["absolute_onset_ticks"], 0)

    def test_background_channel_selection_and_no_quantization(self):
        self.package(ticks=(1, 5), ppq=100)
        report = export_bms(self.pack, self.out, lead_in_bars=0, play_channels=set())
        self.assertEqual(report["bgm_events"], 2)
        self.assertEqual(sorted(t for t, _, _ in read_exported_events((self.out / "test.bme").read_text(), 100)), [1, 5])

    def test_selected_missing_track_does_not_block_bgm_audio(self):
        timeline,_=self.package(missing=True)
        for n in timeline['notes']:n['track_id']=1
        for n in timeline['midi_only_notes']:n['track_id']=2
        (self.pack/'timeline.json').write_text(json.dumps(timeline))
        result=export_bms(self.pack,self.out,play_tracks={2})
        self.assertEqual(result['playable_notes'],0)
        self.assertEqual(result['bgm_events'],3)
        self.assertFalse(result['audio_complete'])
        self.assertTrue((self.out/'fallback.mid').exists())

    def test_tampered_audio_rejected_without_output(self):
        self.package()
        with (self.pack / "key.wav").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(FlpError, "changed"):
            export_bms(self.pack, self.out)
        self.assertFalse(self.out.exists())

    def test_partial_package_and_invalid_references_are_rejected(self):
        timeline, report = self.package()
        for field, value in (("status", "partial"), ("status", "complete")):
            report[field] = value
            (self.pack / "keysounds.json").write_text(json.dumps(report))
            if value == "complete":
                timeline["notes"][0]["key_id"] = "missing"
                (self.pack / "timeline.json").write_text(json.dumps(timeline))
            with self.assertRaises(FlpError):
                export_bms(self.pack, self.out)

    def test_path_escape_is_rejected(self):
        timeline, report = self.package()
        report["keys"][0]["file"] = "../outside.wav"
        for n in timeline["notes"]:
            n["key_file"] = "../outside.wav"
        (self.pack / "keysounds.json").write_text(json.dumps(report))
        (self.pack / "timeline.json").write_text(json.dumps(timeline))
        with self.assertRaises(FlpError):
            export_bms(self.pack, self.out)

    def test_invalid_tempo_is_reported_cleanly(self):
        timeline, _ = self.package()
        for bpm in (None, "bad", "NaN", 0):
            timeline["timing"]["bpm"] = bpm
            (self.pack / "timeline.json").write_text(json.dumps(timeline))
            with self.subTest(bpm=bpm), self.assertRaises(FlpError):
                export_bms(self.pack, self.out)
            self.assertFalse(self.out.exists())

    def test_metadata_injection_and_range_rejected_before_writing(self):
        self.package()
        for kwargs in ({"title": "Title\n#BPM 1"}, {"lead_in_bars": -1}, {"lead_in_bars": 999}):
            with self.subTest(kwargs=kwargs), self.assertRaises(FlpError):
                export_bms(self.pack, self.out, **kwargs)
            self.assertFalse(self.out.exists())
        self.assertEqual(object_id(35), "0Z")
        self.assertEqual(object_id(36), "10")
        self.assertEqual(object_id(1295), "ZZ")
        with self.assertRaises(FlpError):
            object_id(1296)

    def test_deterministic_output_and_existing_directory_protection(self):
        self.package()
        export_bms(self.pack, self.out)
        second = self.root / "second"
        export_bms(self.pack, second)
        self.assertEqual((self.out / "test.bme").read_bytes(), (second / "test.bme").read_bytes())
        with self.assertRaises(FlpError):
            export_bms(self.pack, self.out)


if __name__ == "__main__":
    unittest.main()
