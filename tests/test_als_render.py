"""Generated fixtures and simulated audio; real desktop runs remain opt-in."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

try:
    import numpy as np
    import soundfile as sf
except ImportError:
    np = sf = None

from test_als import fixture, element
from daw2bms.als import extract_file, read_xml
from daw2bms.als_bank import make_keys, prepare_track, set_value, write_bank
from daw2bms.als_render import convert_als_audio
from daw2bms.ableton_ui import AbletonUIError, WindowsExporter, NativeExporter
from daw2bms.keysounds import sha256_file


def native_fixture():
    root = ET.fromstring(fixture([{'notes': [{'time': 0}, {'time': 2}]}]))
    t = root.find('LiveSet/Tracks/MidiTrack')
    set_value(t, 'DeviceChain/AudioOutputRouting/Target', 'AudioOut/Main')
    chain = element(t.find('DeviceChain'), 'DeviceChain')
    element(element(chain, 'Devices'), 'Operator', Id='9')
    # Groove MIDI is data, not an Arrangement or Session source.
    groove = element(element(element(root.find('LiveSet'), 'GroovePool'), 'Grooves'), 'Groove', Id='4')
    groove.append(deepcopy(next(root.iter('MidiClip'))))
    return root


class FakeExporter:
    calls = []
    fail = False
    release = 0.1
    def __init__(self, *args, **kwargs): pass
    def render(self, project, wav, *, bars, bpm):
        self.calls.append(project)
        if self.fail:
            raise AbletonUIError('Simulated missing device dialog')
        manifest = json.loads((project.parent / 'manifest.json').read_text())
        rate = 44100
        audio = np.zeros((round(bars * 4 * 60 / bpm * rate), 2), dtype=np.float32)
        for k in manifest['keys']:
            start = round(k['onset_ticks'] / manifest['timing']['ppq'] * 60 / bpm * rate)
            gate = k['length_ticks'] / manifest['timing']['ppq'] * 60 / bpm
            length = min(round((gate + self.release) * rate), len(audio) - start)
            t = np.arange(length) / rate
            envelope = np.where(t < gate, .2, .2 * np.maximum(0, 1 - (t-gate)/self.release))
            audio[start:start+length] += (envelope * np.sin(t * 440 * 2 * np.pi))[:, None]
        sf.write(wav, audio, rate, subtype='PCM_24')


@unittest.skipIf(np is None or sf is None, 'Install [audio] extra')
class AlsRenderingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'arbitrary 音楽.als'
        self.exe = self.root / 'Live.exe'; self.exe.touch()
        self.xml = native_fixture()
        self.store()
        FakeExporter.calls = []; FakeExporter.fail = False; FakeExporter.release = .1

    def tearDown(self): self.tmp.cleanup()

    def store(self):
        self.source.write_bytes(gzip.compress(ET.tostring(self.xml), mtime=0))

    def convert(self, **kwargs):
        return convert_als_audio(self.source, self.root/'out', ableton_exe=self.exe,
            progress=lambda m: None, exporter_factory=FakeExporter, **kwargs)

    def test_bank_preserves_groove_devices_and_source(self):
        before = sha256_file(self.source)
        doc = extract_file(self.source)
        prepared = prepare_track(self.xml, doc, 7, self.source)
        self.assertEqual(ET.tostring(prepared.find('LiveSet/GroovePool')), ET.tostring(self.xml.find('LiveSet/GroovePool')))
        keys, mapped, missing = make_keys(doc, 7, 960)
        self.assertEqual(len(keys), 1); self.assertEqual(len(mapped), 2)
        bank = write_bank(prepared, self.xml, doc, 7, keys, self.root/'bank', 960, 120, {keys[0]['id']: .3})
        parsed, *_ = read_xml(self.root/'bank'/bank['bank']['project'])
        clip = parsed.find('LiveSet/Tracks/MidiTrack/DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events/MidiClip')
        self.assertEqual(clip.find('Notes/NoteIdGenerator/NextId').get('Value'), '1')
        self.assertNotIn('NextId', clip.find('Notes/NoteIdGenerator').attrib)
        self.assertIsNone(parsed.find('LiveSet/Tracks/MidiTrack/DeviceChain/MainSequencer/IsArmed'))
        self.assertEqual(sha256_file(self.source), before)
        self.assertEqual(ET.tostring(parsed.find('.//Operator')), ET.tostring(self.xml.find('.//Operator')))

    def test_full_pipeline_maps_original_ticks(self):
        result = self.convert()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['audio_events'], 2)
        self.assertEqual(result['keysounds'], 1)
        self.assertTrue(result['audio_complete'])
        mapping = json.loads((self.root/'out/chart/mapping.json').read_text())
        self.assertEqual(mapping['schema_version'], 2)
        self.assertEqual(mapping['chart_sha256'], sha256_file(self.root/'out/chart/test.bme'))
        self.assertIn('Operator', mapping['events'][0]['source_note']['instrument_name'])
        self.assertEqual([e['original_tick'] for e in mapping['events']], [0, 1920])
        self.assertEqual([e['bms_tick'] for e in mapping['events']], [3840, 5760])

    def test_tail_retries_and_no_dedupe(self):
        FakeExporter.release = .4
        result = self.convert(initial_tail=.1, max_tail=2, max_attempts=5, deduplicate=False)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['keysounds'], 2)
        self.assertGreater(len(FakeExporter.calls), 1)

    def test_tail_limit_preserves_midi(self):
        FakeExporter.release = 1
        result = self.convert(initial_tail=.1, max_tail=.1, max_attempts=1)
        self.assertEqual(result['status'], 'midi_only')
        self.assertEqual(result['midi_only_notes'], 2)
        self.assertFalse((self.root/'out/chart').exists())

    def test_unknown_dialog_preserves_midi_and_stops(self):
        FakeExporter.fail = True
        result = self.convert()
        self.assertEqual(result['status'], 'midi_only')
        self.assertIn('Simulated missing device', result['audio_error'])
        self.assertTrue((self.root/'out/song.mid').is_file())
        self.assertEqual(len(FakeExporter.calls), 1)

    def test_external_plugin_is_warned_before_opening_live(self):
        element(self.xml.find('.//Operator'), 'PluginDevice')
        self.store()
        result = self.convert()
        self.assertEqual(result['status'], 'midi_only')
        self.assertTrue(any('unidentified Ableton plug-in' in str(w) for w in result['warnings']))
        self.assertEqual(FakeExporter.calls, [])

    def test_missing_sample_is_warned_before_opening_live(self):
        ref = element(element(self.xml.find('.//Operator'), 'SampleRef'), 'FileRef')
        element(ref, 'Path', str(self.root/'missing.wav'))
        self.store()
        result = self.convert()
        self.assertTrue(any('Missing or unresolved Ableton sample' in str(w) for w in result['warnings']))
        self.assertEqual(FakeExporter.calls, [])

    def test_clipped_note_and_probability_stay_midi_only(self):
        clip = next(self.xml.iter('MidiClip'))
        clip.find('CurrentEnd').set('Value','2.5')
        self.store()
        result = self.convert()
        self.assertEqual(result['status'], 'midi_only')
        self.assertEqual(FakeExporter.calls, [])

    def test_cancellation_is_not_wrapped_as_render_failure(self):
        from daw2bms.flp import FlpError
        class Stop(FlpError):pass
        def progress(message):
            if str(message).startswith('ALS track'):raise Stop('cancelled')
        with self.assertRaises(Stop):
            convert_als_audio(self.source,self.root/'out',ableton_exe=self.exe,progress=progress,exporter_factory=FakeExporter)
        self.assertTrue((self.root/'out/song.mid').exists())

    def test_loss_of_focus_blocks_input(self):
        from unittest.mock import Mock
        ui = WindowsExporter.__new__(WindowsExporter)
        ui.win = Mock(); ui._owned = lambda handle: False
        ui.p = Mock()
        with self.assertRaises(AbletonUIError): ui._keys('enter')
        ui.p.hotkey.assert_not_called()

    def test_existing_wav_never_launches_helper(self):
        wav = self.root / 'old.wav'; wav.write_bytes(b'old')
        with patch('daw2bms.ableton_ui.subprocess.Popen') as launch:
            with self.assertRaises(AbletonUIError):
                NativeExporter(self.exe).render(self.source, wav, bars=1, bpm=120)
        launch.assert_not_called()
        self.assertEqual(wav.read_bytes(), b'old')

    def test_missing_track_does_not_block_available_track(self):
        track = deepcopy(self.xml.find('LiveSet/Tracks/MidiTrack'))
        track.set('Id', '8')
        track.find('DeviceChain/DeviceChain/Devices').clear()
        self.xml.find('LiveSet/Tracks').append(track)
        self.store()
        result = self.convert()
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['audio_complete'])
        self.assertEqual(result['midi_only_notes'], 2)
        self.assertEqual(result['audio_events'], 2)
        self.assertEqual(len(FakeExporter.calls), 1)
        import mido
        fallback = mido.MidiFile(self.root/'out/chart/fallback.mid')
        notes = [m for t in fallback.tracks for m in t if m.type=='note_on' and m.velocity]
        self.assertEqual([m.velocity for m in notes], [100,100])

    def test_inventory_audio_marks_chart_incomplete(self):
        track = element(self.xml.find('LiveSet/Tracks'), 'AudioTrack', Id='8')
        events = element(element(element(element(element(track, 'DeviceChain'), 'MainSequencer'), 'Sample'), 'ArrangerAutomation'), 'Events')
        clip = element(events, 'AudioClip', Id='1', Time='0')
        element(clip, 'CurrentStart', 0); element(clip, 'CurrentEnd', 4)
        self.store()
        result = self.convert()
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['audio_complete'])
        chart = json.loads((self.root/'out/chart/export_report.json').read_text())
        self.assertFalse(chart['audio_complete'])
        self.assertIn('[MISSING AUDIO]',chart['title'])
