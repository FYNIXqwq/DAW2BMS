import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from daw2bms.als import AlsError, extract_file
from daw2bms.als_export import make_midi
from daw2bms.__main__ import main
from daw2bms.pipeline import convert

try:
    import mido
except ImportError:
    mido = None


def element(parent, tag, value=None, **attrs):
    if value is not None:
        attrs["Value"] = str(value)
    return ET.SubElement(parent, tag, attrs)


def fixture(clips=None, *, version=11, track_enabled=True, tempo_events=(), meter_events=()):
    root = ET.Element("Ableton", MajorVersion="5", MinorVersion=f"{version}.0_test", Creator=f"Ableton Live {version}.0")
    live = element(root, "LiveSet")
    tracks = element(live, "Tracks")
    t = element(tracks, "MidiTrack", Id="7")
    element(element(t, "Name"), "EffectiveName", "測試 日本語 한국어")
    element(t, "TrackGroupId", -1)
    chain = element(t, "DeviceChain")
    mixer = element(chain, "Mixer")
    element(element(mixer, "Speaker"), "Manual", str(track_enabled).lower())
    sequencer = element(chain, "MainSequencer")
    arranged = element(element(element(sequencer, "Sample" if version >= 12 else "ClipTimeable"), "ArrangerAutomation"), "Events")
    session = element(element(element(element(sequencer, "ClipSlotList"), "ClipSlot"), "ClipSlot"), "Value")
    frozen = element(element(chain, "FreezeSequencer"), "Events")
    takes = element(element(t, "TakeLanes"), "TakeLane")
    for index, spec in enumerate(clips if clips is not None else [{}]):
        container = {"arrangement": arranged, "session": session, "freeze": frozen, "take": takes}.get(spec.get("scope", "arrangement"))
        if container is None:
            container = element(sequencer, "UnknownContainer")
        c = element(container, spec.get("kind", "MidiClip"), Id=str(index), Time=str(spec.get("start", 0)))
        element(c, "Name", "Clip")
        element(c, "CurrentStart", spec.get("start", 0))
        element(c, "CurrentEnd", spec.get("end", 4))
        element(c, "Disabled", str(spec.get("disabled", False)).lower())
        loop = element(c, "Loop")
        for tag, value in (("LoopStart", spec.get("loop_start", 0)), ("LoopEnd", spec.get("loop_end", 4)),
                           ("StartRelative", spec.get("relative", 0)), ("LoopOn", str(spec.get("looped", False)).lower())):
            element(loop, tag, value)
        if c.tag == "AudioClip":
            element(element(element(c, "SampleRef"), "FileRef"), "Path", "missing audio.wav")
            continue
        key_tracks = element(element(c, "Notes"), "KeyTracks")
        for i, note in enumerate(spec.get("notes", [{}])):
            kt = element(key_tracks, "KeyTrack", Id=str(i))
            element(kt, "MidiKey", note.get("key", 60))
            element(element(kt, "Notes"), "MidiNoteEvent", Time=str(note.get("time", 0)),
                    Duration=str(note.get("duration", 1)), Velocity=str(note.get("velocity", 100)),
                    OffVelocity=str(note.get("off_velocity", 64)), Probability=str(note.get("probability", 1)),
                    VelocityDeviation=str(note.get("deviation", 0)), IsEnabled=str(note.get("enabled", True)).lower(), NoteId=str(i + 1))
    master = element(live, "MainTrack" if version >= 12 else "MasterTrack")
    mix = element(element(master, "DeviceChain"), "Mixer")
    for tag, value, target in (("Tempo", 120, 8), ("TimeSignature", 201, 10)):
        p = element(mix, tag)
        element(p, "Manual", value)
        element(p, "AutomationTarget", Id=str(target))
    envelopes = element(element(master, "AutomationEnvelopes"), "Envelopes")
    for points, target, tag in ((tempo_events, 8, "FloatEvent"), (meter_events, 10, "EnumEvent")):
        if points:
            envelope = element(envelopes, "AutomationEnvelope")
            element(element(envelope, "EnvelopeTarget"), "PointeeId", target)
            events = element(element(envelope, "Automation"), "Events")
            for time, value in points:
                element(events, tag, Time=str(time), Value=str(value))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class AlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "任意 project.als"

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, xml=None, compressed=True):
        xml = fixture() if xml is None else xml
        raw = gzip.compress(xml, mtime=0) if compressed else xml
        self.source.write_bytes(raw)
        result = extract_file(self.source)
        self.assertEqual(self.source.read_bytes(), raw)
        json.dumps(result, allow_nan=False)
        return result

    def test_plain_and_gzip_live11_and_live12(self):
        for version in (11, 12):
            for compressed in (True, False):
                with self.subTest(version=version, compressed=compressed):
                    d = self.read(fixture(version=version), compressed)
                    self.assertEqual(d["summary"]["eligible_midi_notes"], 1)
                    self.assertEqual(d["timeline_notes"][0]["key"], 60)
                    self.assertEqual(d["timeline_notes"][0]["velocity"], "100")
                    self.assertEqual(d["project"]["initial_tempo_bpm"], "120")

    def test_loop_start_and_relative_offset_repeat_on_absolute_timeline(self):
        d = self.read(fixture([{"start": 4, "end": 12, "loop_start": 1, "loop_end": 3, "relative": 1,
                                "looped": True, "notes": [{"time": 1, "duration": 0.25}, {"time": 2, "duration": 0.25}]}]))
        self.assertEqual([n["visible_start_beats"] for n in d["timeline_notes"]], [str(n) for n in range(4, 12)])
        self.assertEqual(d["clips"][0]["expansion_status"], "loop_expanded")

    def test_pickup_before_loop_start_is_played_only_in_first_pass(self):
        d = self.read(fixture([{"end": 6, "loop_start": 2, "loop_end": 4, "relative": -2, "looped": True,
                                "notes": [{"time": 0, "duration": 0.25}, {"time": 2, "duration": 0.25}]}]))
        self.assertEqual([n["visible_start_beats"] for n in d["timeline_notes"]], ["0", "2", "4"])

    def test_clip_boundaries_and_source_offset_preserve_original_lengths(self):
        d = self.read(fixture([{"start": 8, "end": 10, "loop_start": 2,
                                "notes": [{"time": 1, "duration": 2}, {"time": 3, "duration": 2}, {"time": 4}]}]))
        notes = d["timeline_notes"]
        self.assertEqual([(n["visible_start_beats"], n["visible_end_beats"]) for n in notes], [("8", "9"), ("9", "10")])
        self.assertEqual(notes[0]["absolute_onset_beats"], "7")
        self.assertEqual(notes[0]["duration_beats"], "2")
        self.assertTrue(all(n["boundary_clipped"] for n in notes))
        self.assertTrue(any(w["code"] == "ALS_BOUNDARY_NOTES" for w in d["warnings"]))

    def test_session_freeze_take_and_unknown_are_not_flattened(self):
        d = self.read(fixture([{}, {"scope": "session"}, {"scope": "freeze"}, {"scope": "take"}, {"scope": "unknown"}]))
        self.assertEqual(d["summary"]["timeline_notes"], 1)
        self.assertEqual(d["summary"]["session_clips"], 1)
        self.assertEqual(d["summary"]["ignored_freeze_clips"], 1)
        self.assertEqual(d["summary"]["ignored_take_clips"], 1)
        self.assertEqual(len(d["unplaced_clip_xml"]), 1)

    def test_disabled_probability_and_zero_duration_notes_remain_in_json(self):
        d = self.read(fixture([{"notes": [{"enabled": False}, {"probability": 0}, {"velocity": 0},
                                          {"duration": 0}, {"probability": 0.5, "deviation": 10}]}]))
        self.assertEqual(len(d["timeline_notes"]), 5)
        self.assertEqual(d["summary"]["eligible_midi_notes"], 1)
        self.assertTrue(any(w["code"] == "ALS_RANDOM_NOTES" for w in d["warnings"]))
        d = self.read(fixture(track_enabled=False))
        self.assertEqual(d["summary"]["eligible_midi_notes"], 0)

    def test_muted_group_disables_child_notes(self):
        root = ET.fromstring(fixture())
        child = root.find("LiveSet/Tracks/MidiTrack")
        child.find("TrackGroupId").set("Value", "2")
        group = element(root.find("LiveSet/Tracks"), "GroupTrack", Id="2")
        element(element(element(element(group, "DeviceChain"), "Mixer"), "Speaker"), "Manual", "false")
        d = self.read(ET.tostring(root))
        self.assertFalse(d["tracks"][0]["effective_enabled"])
        self.assertEqual(d["summary"]["eligible_midi_notes"], 0)

    def test_audio_clip_keeps_reference_without_invented_midi(self):
        d = self.read(fixture([{"kind": "AudioClip"}]))
        self.assertEqual(d["summary"]["audio_clips"], 1)
        self.assertEqual(d["timeline_notes"], [])
        self.assertIn("missing audio.wav", d["clips"][0]["sample_ref_xml"])

    def test_tempo_automation_retained_with_explicit_midi_limitation(self):
        d = self.read(fixture(tempo_events=[(-63072000, 90), (4, 120)]))
        self.assertEqual(d["project"]["tempo_manual"], "120")
        self.assertEqual(d["project"]["initial_tempo_bpm"], "90")
        self.assertEqual(d["project"]["tempo_export"], "initial_only")
        self.assertEqual(len(d["project"]["tempo_automation"]), 2)
        self.assertTrue(any(w["code"] == "ALS_TEMPO_AUTOMATION" for w in d["warnings"]))

    def test_negative_tempo_changes_and_duplicate_initial_events_are_not_hidden(self):
        d = self.read(fixture(tempo_events=[(-63072000, 120), (-2, 90), (-2, 80)]))
        self.assertEqual(d["project"]["initial_tempo_bpm"], "80")
        self.assertEqual(d["project"]["tempo_export"], "initial_only")

    def test_empty_expression_container_does_not_produce_false_warning(self):
        root = ET.fromstring(fixture())
        element(element(root.find('.//MidiClip/Notes'), 'PerNoteEventStore'), 'EventLists')
        d = self.read(ET.tostring(root))
        self.assertFalse(any(w["code"] == "ALS_EXPRESSION_NOT_APPLIED" for w in d["warnings"]))

    def test_precision_is_retained_and_midi_rounding_is_reported(self):
        d = self.read(fixture([{"notes": [{"time": "0.3333333333333333", "duration": "0.00000001"}]}]))
        self.assertEqual(d["timeline_notes"][0]["absolute_onset_beats"], "3333333333333333/10000000000000000")
        _, report, warnings = make_midi(d)
        self.assertFalse(report["timing_exact"])
        self.assertEqual(report["minimum_duration_extensions"], 1)
        self.assertTrue(warnings)
        d = self.read(fixture([{"notes": [{"time": "0.125", "duration": "0.25"}]}]))
        self.assertTrue(make_midi(d)[1]["timing_exact"])

    def test_negative_song_positions_are_shifted_only_for_midi(self):
        d = self.read(fixture([{"start": -2, "end": 2}]))
        _, report, warnings = make_midi(d)
        self.assertEqual(d["timeline_notes"][0]["absolute_onset_beats"], "-2")
        self.assertEqual(report["beat_offset"], "2")
        self.assertEqual(report["events"][0]["start_tick"], 0)
        self.assertTrue(warnings)

    def test_file_limits_group_cycles_and_track_selection(self):
        with patch("daw2bms.als.MAX_FILE_BYTES", 20), self.assertRaises(AlsError):
            self.read()
        root = ET.fromstring(fixture())
        root.find("LiveSet/Tracks/MidiTrack/TrackGroupId").set("Value", "7")
        with self.assertRaises(AlsError):
            self.read(ET.tostring(root))
        d = self.read()
        with self.assertRaises(AlsError):
            make_midi(d, {999})
        self.assertEqual(make_midi(d, {7})[1]["note_count"], 1)

    def test_empty_loop_region_does_not_repeat_outside_notes(self):
        d = self.read(fixture([{"looped": True, "loop_start": 0, "loop_end": 1, "end": 9999,
                                "notes": [{"time": 8, "duration": 1}]}]))
        self.assertEqual(d["timeline_notes"], [])
        self.assertEqual(d["clips"][0]["expansion_status"], "loop_expanded")

    def test_invalid_loops_preserve_notes_without_guessing(self):
        d = self.read(fixture([{"looped": True, "loop_start": 1, "loop_end": 1}]))
        self.assertEqual(len(d["clips"][0]["notes"]), 1)
        self.assertFalse(d["timeline_notes"])
        self.assertEqual(d["clips"][0]["expansion_status"], "unsupported_loop")

    def test_malformed_xml_entities_numbers_and_expansion_limits(self):
        for raw in (b"broken", b'<!DOCTYPE Ableton [<!ENTITY x "bad">]><Ableton><LiveSet/></Ableton>',
                    fixture([{"notes": [{"time": "NaN"}]}]), fixture([{"notes": [{"duration": -1}]}]),
                    fixture([{"notes": [{"time": "1e-1000000"}]}]), fixture([{"looped": True, "loop_end": "0.0000001"}])):
            with self.subTest(size=len(raw)), self.assertRaises(AlsError):
                self.read(raw)
        with patch("daw2bms.als.MAX_XML_BYTES", 100), self.assertRaises(AlsError):
            self.read()
        self.source.write_bytes(b"\x1f\x8bBAD")
        with self.assertRaises(AlsError):
            extract_file(self.source)

    @unittest.skipIf(mido is None, "Install [test] extra")
    def test_midi_reader_confirms_pitch_velocity_timing_and_meter_changes(self):
        d = self.read(fixture([{"start": 2, "end": 6, "notes": [{"key": 72, "time": "0.25", "duration": "0.5", "velocity": 127, "off_velocity": 77}]}],
                              meter_events=[(-63072000, 201), (4, 297)]))
        data, report, _ = make_midi(d)
        midi = mido.MidiFile(file=io.BytesIO(data))
        note_events = [(m.type, m.note, m.velocity, m.time) for m in midi.tracks[1] if m.type in ("note_on", "note_off")]
        self.assertEqual(note_events, [("note_on", 72, 127, 2160), ("note_off", 72, 77, 480)])
        meters = [m for m in midi.tracks[0] if m.type == "time_signature"]
        self.assertEqual([(m.numerator, m.denominator) for m in meters], [(4, 4), (1, 8)])

    def test_cli_and_pipeline_do_not_discover_or_launch_a_renderer(self):
        self.read()
        with patch("daw2bms.pipeline.find_fl_executable", side_effect=AssertionError("Must not discover FL")), \
                patch("daw2bms.adaptive.cut", side_effect=AssertionError("Must not render")):
            messages = []
            report = convert(self.source, self.root / "converted", fl_exe=self.root / "absent.exe", progress=messages.append)
        self.assertEqual(report["status"], "midi_only")
        self.assertEqual(report["daw"], "ableton_live")
        self.assertEqual(report["midi_only_notes"], 1)
        self.assertFalse((self.root / "converted/chart").exists())
        self.assertTrue(any("MIDI-only" in m for m in messages))
        for lang in ("zh-TW", "en", "ja", "ko"):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main(["extract", str(self.source), "--out", str(self.root / lang), "--lang", lang]), 0)
            self.assertTrue((self.root / lang / "song.mid").exists())
            self.assertTrue(err.getvalue())


class ExternalAlsTests(unittest.TestCase):
    def test_external_als_when_configured(self):
        configured = os.environ.get("DAW2BMS_TEST_ALS")
        if not configured:
            self.skipTest("Set DAW2BMS_TEST_ALS to validate an external ALS project")
        path = Path(configured)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        document = extract_file(path)
        data, report, _ = make_midi(document)
        self.assertEqual(report["note_count"], document["summary"]["eligible_midi_notes"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        if mido:
            midi = mido.MidiFile(file=io.BytesIO(data))
            self.assertEqual(sum(m.type == "note_on" and m.velocity > 0 for t in midi.tracks for m in t), report["note_count"])


if __name__ == "__main__":
    unittest.main()
