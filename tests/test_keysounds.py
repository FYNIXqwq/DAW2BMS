import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from daw2bms.audio import render, slice_bank
from daw2bms.flp import FlpError, extract_file, read_events
from daw2bms.keysounds import load_manifest, prepare, tick_to_frame
from test_flp import clip, envelope, event, fixture, note

try:
    import numpy as np
    import soundfile as sf
except ImportError:
    np = sf = None


class BankFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.flp"
        self.destination = self.root / "bank"

    def tearDown(self):
        self.temp.cleanup()

    def make_bank(self, payload=None, **options):
        self.source.write_bytes(fixture() if payload is None else payload)
        before = self.source.read_bytes()
        result = prepare(self.source, self.destination, tail_seconds=0.25, gap_seconds=0.1, **options)
        self.assertEqual(self.source.read_bytes(), before)
        return result


class BankTests(BankFixture):
    def test_deduplication_keeps_mapping_for_all_occurrences(self):
        result = self.make_bank(fixture(notes=note() + note(96), clips=clip() + clip(384)))
        self.assertEqual(len(result["keys"]), 1)
        self.assertEqual(len(result["timeline"]), 4)
        self.assertEqual(len(result["keys"][0]["source_notes"]), 2)
        self.assertEqual({n["key_id"] for n in result["timeline"]}, {"k0001"})

    def test_velocity_length_channel_parameters_distinguish_keys(self):
        original = note()
        velocity = bytearray(note(96))
        velocity[21] = 80
        pan = bytearray(note(192))
        pan[20] = 20
        result = self.make_bank(fixture(notes=original + bytes(velocity) + bytes(pan) + note(288, 24)))
        self.assertEqual(len(result["keys"]), 4)

    def test_no_dedupe_renders_every_placement(self):
        result = self.make_bank(fixture(clips=clip() + clip(384)), deduplicate=False)
        self.assertEqual(len(result["keys"]), 2)

    def test_generated_bank_preserves_notes_and_opaque_data(self):
        raw = fixture(notes=note(0, 0) + note(96, 48, 63))
        raw = envelope(raw[22:] + event(213, b"opaque plugin state\0\xff"))
        result = self.make_bank(raw)
        parsed = extract_file(self.destination / "render_bank.flp")
        pattern = parsed["patterns"][0]
        self.assertEqual([n["position_ticks"] for n in pattern["notes"][:-1]], [k["onset_ticks"] for k in result["keys"]])
        self.assertEqual([n["length_ticks"] for n in pattern["notes"][:-1]], [0, 48])
        anchor = pattern["notes"][-1]
        self.assertEqual(anchor["position_ticks"] + anchor["length_ticks"], result["bank"]["length_ticks"])
        self.assertEqual(anchor["channel_id"], result["bank"]["anchor_channel_id"])
        self.assertFalse(next(c for c in parsed["channels"] if c["id"] == anchor["channel_id"])["enabled"])
        self.assertEqual(pattern["length_ticks_declared"], 0)
        self.assertFalse(pattern["looped"])
        _, bank_events = read_events((self.destination / "render_bank.flp").read_bytes())
        self.assertEqual(next(e.data for e in bank_events if e.id == 213), b"opaque plugin state\0\xff")
        self.assertEqual(len(parsed["arrangements"][0]["clips"]), 1)
        self.assertEqual(parsed["arrangements"][0]["clips"][0]["length_ticks"], result["bank"]["length_ticks"])

    def test_prepare_refuses_existing_directory_and_invalid_timing(self):
        self.source.write_bytes(fixture())
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(tail=value), self.assertRaises(FlpError):
                prepare(self.source, self.destination, tail_seconds=value)
        self.destination.mkdir()
        with self.assertRaises(FlpError):
            prepare(self.source, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_unsupported_playback_states_fail_before_writing(self):
        cases = [fixture(looped=True), fixture(notes=note(flags=0x4008)),
                 fixture(channel_enabled=False), fixture(track_enabled=False),
                 fixture(notes=note(0, 192), clips=clip(0, 48, 96, 144)),
                 fixture(clips=clip(scale=2))]
        for payload in cases:
            self.source.write_bytes(payload)
            with self.subTest(size=len(payload)), self.assertRaises(FlpError):
                prepare(self.source, self.destination)
            self.assertFalse(self.destination.exists())

    def test_manifest_hash_and_path_safety(self):
        result = self.make_bank()
        manifest = self.destination / "manifest.json"
        self.assertEqual(load_manifest(manifest)["bank"]["sha256"], result["bank"]["sha256"])
        result["bank"]["project"] = "../source.flp"
        manifest.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaises(FlpError):
            load_manifest(manifest)

    def test_absolute_frame_rounding_does_not_accumulate_drift(self):
        # 1 quarter = 60/130 seconds; the 130th quarter is exactly 60 seconds.
        self.assertEqual(tick_to_frame(130 * 96, 96, 130, 44100), 2646000)
        self.assertNotEqual(130 * tick_to_frame(96, 96, 130, 44100), 2646000)


@unittest.skipIf(sf is None, "Install the [audio] extra to run audio tests")
class AudioTests(BankFixture):
    def write_audio(self, result, *, subtype="FLOAT", modifier=None):
        rate = 8000
        samples = np.zeros((tick_to_frame(result["bank"]["length_ticks"], 96, 130, rate), 2), dtype="float32")
        for key in result["keys"]:
            start = tick_to_frame(key["onset_ticks"], 96, 130, rate)
            samples[start + 5] = [0.5, -0.25]
        if modifier:
            modifier(samples, rate)
        path = self.destination / "render_bank.wav"
        sf.write(path, samples, rate, subtype=subtype)
        return path

    def test_float_input_cutting_preserves_leading_silence_and_gain(self):
        result = self.make_bank(fixture(notes=note() + note(96, key=61)))
        wav = self.write_audio(result)
        before = hashlib.sha256(wav.read_bytes()).hexdigest()
        report = slice_bank(self.destination / "manifest.json", tail_pad_ms=0, fade_ms=0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(report["keys"]), 2)
        audio, rate = sf.read(self.destination / "keysounds" / "k0001.wav", always_2d=True)
        self.assertEqual(audio.shape, (6, 2))
        np.testing.assert_array_equal(audio[:5], 0)
        np.testing.assert_allclose(audio[5], [0.5, -0.25], atol=1 / (2**23))
        self.assertEqual(hashlib.sha256(wav.read_bytes()).hexdigest(), before)
        mapping = json.loads((self.destination / "keysounds" / "timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(len(mapping["notes"]), 2)

    def test_pcm_input_and_tail_fade(self):
        result = self.make_bank()
        self.write_audio(result, subtype="PCM_16")
        report = slice_bank(self.destination / "manifest.json", subtype="PCM_16")
        path = self.destination / "keysounds" / "k0001.wav"
        self.assertEqual(sf.info(path).subtype, "PCM_16")
        data, _ = sf.read(path)
        np.testing.assert_array_equal(data[-1], 0)
        self.assertEqual(report["keys"][0]["first_active_frame"], 5)

    def test_silent_missing_instrument_is_rejected(self):
        result = self.make_bank()
        self.write_audio(result, modifier=lambda samples, rate: samples.fill(0))
        with self.assertRaisesRegex(FlpError, "silent_key"):
            slice_bank(self.destination / "manifest.json")
        self.assertFalse((self.destination / "keysounds").exists())
        self.assertTrue((self.destination / "slice_diagnostics.json").exists())

    def test_tail_and_gap_contamination_are_rejected(self):
        result = self.make_bank(fixture(notes=note() + note(96, key=61)))
        def contaminate(samples, rate):
            end = tick_to_frame(result["keys"][0]["cut_end_ticks"], 96, 130, rate)
            samples[end - 1:end + 100] = 0.2
        self.write_audio(result, modifier=contaminate)
        with self.assertRaisesRegex(FlpError, "tail_not_finished"):
            slice_bank(self.destination / "manifest.json")
        report = json.loads((self.destination / "slice_diagnostics.json").read_text())
        self.assertEqual({f["reason"] for f in report["failures"]}, {"tail_not_finished", "audio_in_guard_gap", "late_audio_after_tail"})
        self.assertFalse((self.destination / "keysounds").exists())

    def test_clipping_and_nonfinite_samples_are_rejected(self):
        result = self.make_bank()
        for value, reason in ((1.2, "would_clip_pcm"), (float("nan"), "non_finite_audio")):
            def inject(samples, rate):
                samples[tick_to_frame(result["keys"][0]["onset_ticks"], 96, 130, rate) + 2] = value
            self.write_audio(result, modifier=inject)
            with self.subTest(value=value), self.assertRaisesRegex(FlpError, reason):
                slice_bank(self.destination / "manifest.json")

    def test_short_render_is_rejected(self):
        self.make_bank()
        sf.write(self.destination / "render_bank.wav", np.zeros(20), 8000)
        with self.assertRaisesRegex(FlpError, "too short"):
            slice_bank(self.destination / "manifest.json")

    def test_cli_renderer_uses_argument_list_and_records_timeout(self):
        self.make_bank()
        executable = self.root / "FL with space.exe"
        executable.write_bytes(b"test placeholder, never executed")
        with patch("daw2bms.audio.subprocess.run", side_effect=subprocess.TimeoutExpired(["FL"], 1)) as mocked:
            with self.assertRaisesRegex(FlpError, "timed out"):
                render(self.destination / "manifest.json", executable, timeout=1)
            self.assertIsInstance(mocked.call_args.args[0], list)
            self.assertEqual(mocked.call_args.args[0][0], str(executable.resolve()))
        receipt = json.loads((self.destination / "render_receipt.json").read_text())
        self.assertEqual(receipt["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
