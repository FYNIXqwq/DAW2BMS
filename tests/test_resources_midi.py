import contextlib
import io
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from daw2bms.__main__ import main
from daw2bms.audio import render, slice_bank
from daw2bms.flp import extract_file, read_events
from daw2bms.keysounds import encode_event, load_manifest, prepare
from daw2bms.midi import midi_bytes, vlq
from daw2bms.resources import flex_pack_name, generator_states
from test_flp import event, fixture, note, text
from test_keysounds import BankFixture

try:
    import mido
except ImportError:
    mido = None


def flex_fixture(mixed=False, missing_sample=False):
    payload = fixture(notes=note() + note(96, channel=1) if mixed else note())
    _, events = read_events(payload)
    output = bytearray()
    for e in events:
        output.extend(encode_event(e.id, e.data))
        if e.id == 64:
            output.extend(event(201, text("FLEX")))
            output.extend(event(213, struct.pack("<IIII", 1, 1, 0, 0) + b"Absent Pack\0" + bytes(300)))
            if missing_sample:
                output.extend(event(196, text("missing.wav")))
    if mixed:
        boundary = event(99, 0)
        channel = event(64, 1) + event(21, 0) + event(203, text("Available")) + event(0, 1)
        output = output.replace(boundary, channel + boundary, 1)
    header = bytearray(payload[:18])
    if mixed:
        struct.pack_into("<H", header, 10, 2)
    return header + struct.pack("<I", len(output)) + output


class FallbackTests(BankFixture):
    def test_missing_flex_becomes_midi_only_without_rendering(self):
        result = self.make_bank(flex_fixture(), fl_exe=self.root / "FL/FL64.exe")
        self.assertEqual(result["keys"], [])
        self.assertIsNone(result["bank"])
        self.assertEqual(result["fallback"]["channel_ids"], [0])
        self.assertEqual(len(result["fallback"]["notes"]), 1)
        self.assertTrue((self.destination / "fallback.mid").read_bytes().startswith(b"MThd"))
        self.assertFalse((self.destination / "render_bank.flp").exists())
        path = self.destination / "manifest.json"
        self.assertIsNone(load_manifest(path)["bank"])
        with patch("daw2bms.audio.subprocess.run") as subprocess_run:
            self.assertEqual(render(path, self.root / "not-installed.exe")["status"], "midi_only")
            self.assertEqual(slice_bank(path)["status"], "midi_only")
            subprocess_run.assert_not_called()

    def test_mixed_bank_neutralizes_only_unavailable_or_inactive_channels(self):
        result = self.make_bank(flex_fixture(mixed=True), fl_exe=self.root / "FL/FL64.exe")
        self.assertEqual(len(result["keys"]), 1)
        self.assertEqual(len(result["fallback"]["notes"]), 1)
        bank_bytes = (self.destination / "render_bank.flp").read_bytes()
        self.assertNotIn(b"Absent Pack", bank_bytes)
        states = generator_states(bank_bytes)
        self.assertNotIn(213, states[0])
        parsed = extract_file(self.destination / "render_bank.flp")
        self.assertFalse(parsed["channels"][0]["enabled"])
        self.assertEqual(parsed["channels"][0]["type_raw"], 0)
        self.assertTrue(parsed["channels"][1]["enabled"])
        self.assertEqual(result["timeline"][0]["channel_id"], 1)

    def test_explicit_resource_dir_resolves_flex_pack(self):
        libraries = self.root / "library"
        libraries.mkdir()
        (libraries / "Absent Pack.flexpack").write_bytes(b"test resource presence only")
        dll = self.root / "FL/Plugins/Fruity/Generators/FLEX/FLEX_x64.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"test plugin presence only")
        result = self.make_bank(flex_fixture(), fl_exe=self.root / "FL/FL64.exe", resource_dirs=(libraries,))
        self.assertEqual(len(result["keys"]), 1)
        self.assertEqual(result["fallback"]["notes"], [])

    def test_missing_sample_and_user_override_both_keep_midi(self):
        payload = fixture()
        # Add the sample reference while in channel scope, before pattern metadata.
        encoded = event(203, text("鼓"))
        payload = payload.replace(encoded, encoded + event(196, text("missing.wav")), 1)
        payload = payload[:18] + struct.pack("<I", len(payload) - 22) + payload[22:]
        result = self.make_bank(payload, midi_only={0})
        kinds = {r["kind"] for r in result["resources"][0]["missing"]}
        self.assertEqual(kinds, {"sample", "user_override"})
        self.assertEqual(len(result["fallback"]["notes"]), 1)

    def test_cli_warns_and_succeeds_when_audio_is_unavailable(self):
        self.source.write_bytes(flex_fixture())
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main(["--lang", "en", "prepare", str(self.source), "--out", str(self.destination),
                           "--fl-exe", str(self.root / "FL/FL64.exe")])
        self.assertEqual(status, 0)
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("Absent Pack.flexpack", err.getvalue())
        self.assertIn("MIDI only", err.getvalue())

    def test_unknown_flex_state_is_not_misreported_as_missing(self):
        self.assertIsNone(flex_pack_name(b"unknown state"))

    @unittest.skipIf(mido is None, "Install [test] extra for independent MIDI-reader verification")
    def test_fallback_midi_opens_with_independent_reader(self):
        result = self.make_bank(flex_fixture(mixed=True), fl_exe=self.root / "FL/FL64.exe")
        midi = mido.MidiFile(self.destination / "fallback.mid")
        self.assertEqual(midi.ticks_per_beat, 96)
        self.assertEqual(midi.type, 1)
        notes = [message for tr in midi.tracks for message in tr if message.type == "note_on"]
        self.assertEqual(len(notes), len(result["fallback"]["notes"]))
        self.assertEqual(notes[0].note, 60)
        self.assertEqual(notes[0].velocity, 99)
        full = mido.MidiFile(self.destination / "song.mid")
        self.assertEqual(sum(message.type == "note_on" for tr in full.tracks for message in tr), 2)


class MidiEncodingTests(unittest.TestCase):
    def test_variable_length_encoding_boundaries(self):
        self.assertEqual(vlq(0), b"\0")
        self.assertEqual(vlq(127), b"\x7f")
        self.assertEqual(vlq(128), b"\x81\0")
        self.assertEqual(vlq(16383), b"\xff\x7f")


if __name__ == "__main__":
    unittest.main()
