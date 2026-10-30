from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from test_flp import fixture, clip, envelope, event, text
from test_keysounds import np, sf
import test_als_render as als_tests
from daw2bms.flp import read_events, FlpError
from daw2bms.keysounds import load_manifest, tick_to_frame, sha256_file, prepare
from daw2bms.pipeline import convert
from daw2bms.__main__ import main
from daw2bms.track_selection import inspect_tracks, track_policy, parse_track_ids


def playlist_fixture(unsupported_last=False):
    clips=[]
    for i in range(3):
        record=bytearray(clip(position=i*384,scale=2 if unsupported_last and i==2 else 1))
        struct.pack_into('<H',record,12,499-i)
        clips.append(record)
    raw=fixture(clips=b''.join(clips))
    _,events=read_events(raw)
    data=b''
    for e in events:
        data+=event(e.id,e.data)
        if e.id==239:
            for ident in (2,3):
                data+=event(238,struct.pack('<IIIB',ident,0,0,1)+bytes(57))
                data+=event(239,text('Track '+str(ident)))
    return envelope(data)


class TrackSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'arbitrary.flp';self.source.write_bytes(playlist_fixture())
        self.exe=self.root/'FL64.exe';self.exe.touch()
    def tearDown(self):self.tmp.cleanup()

    def fake_render(self,path,exe,**kwargs):
        m=load_manifest(path);timing=m['timing'];rate=8000
        audio=np.zeros((tick_to_frame(m['bank']['length_ticks'],timing['ppq'],timing['bpm'],rate),2),dtype='float32')
        for key in m['keys']:
            start=tick_to_frame(key['onset_ticks'],timing['ppq'],timing['bpm'],rate)
            audio[start+4:start+30]=.1
        sf.write(path.parent/'render_bank.wav',audio,rate,subtype='FLOAT')
        return {'status':'rendered'}

    def test_inventory_uses_playlist_not_instrument_ids(self):
        before=self.source.read_bytes();preview=inspect_tracks(self.source)
        self.assertEqual([t['id'] for t in preview['arrangements'][0]['tracks']],[1,2,3])
        self.assertEqual([t['notes'] for t in preview['arrangements'][0]['tracks']],[1,1,1])
        self.assertEqual(self.source.read_bytes(),before)

    @unittest.skipIf(np is None,'Install [audio]')
    def test_same_instrument_can_be_playable_bgm_or_excluded(self):
        with patch('daw2bms.adaptive.render',side_effect=self.fake_render):
            r=convert(self.source,self.root/'out',fl_exe=self.exe,play_tracks={1},exclude_tracks={3},progress=lambda m:None)
        self.assertEqual((r['playable_notes'],r['bgm_events']),(1,1))
        mapping=json.loads((self.root/'out/chart/mapping.json').read_text())
        events=mapping['events']
        self.assertEqual([e['source_note']['track_id'] for e in events],[1,2])
        self.assertEqual({e['source_note']['channel_id'] for e in events},{0})
        self.assertEqual([e['reason'] for e in events],['playable','background_track'])
        self.assertEqual([e['original_tick'] for e in events],[0,384])
        self.assertEqual(r['track_roles'],{'1':'play','2':'bgm','3':'exclude'})
        import mido
        self.assertEqual(sum(e.type=='note_on' and e.velocity>0 for t in mido.MidiFile(self.root/'out/song.mid').tracks for e in t),2)
        manifest=json.loads((self.root/'out/work/attempt-01/manifest.json').read_text())
        self.assertEqual(len(manifest['keys']),1)  # Shared sample; distinct placement roles.
        self.assertEqual({n['track_id'] for n in manifest['timeline']},{1,2})
        self.assertTrue(all('instrument_name' in n and 'track_name' in n for n in manifest['timeline']))
        self.assertEqual(next(n['track_name'] for n in manifest['timeline'] if n['track_id']==2), 'Track 2')

    def test_excluded_unsupported_clip_does_not_block_preparation(self):
        self.source.write_bytes(playlist_fixture(unsupported_last=True))
        preview=inspect_tracks(self.source)
        self.assertFalse(preview['arrangements'][0]['tracks'][2]['supported'])
        bank=prepare(self.source,self.root/'bank',tracks={1,2})
        self.assertEqual({n['track_id'] for n in bank['timeline']},{1,2})

    def test_bad_roles_and_stale_source_fail_before_render(self):
        for play,exclude in (({99},None),({1},{1}), (None,{1,2,3})):
            with self.subTest(play=play,exclude=exclude),self.assertRaises(FlpError):
                convert(self.source,self.root/'out',play_tracks=play,exclude_tracks=exclude,progress=lambda m:None)
        old=sha256_file(self.source);self.source.write_bytes(fixture())
        with self.assertRaises(FlpError):convert(self.source,self.root/'out',source_sha256=old,progress=lambda m:None)
        self.assertFalse((self.root/'out').exists())

    def test_cli_lists_tracks_and_preserves_explicit_bgm_only(self):
        self.assertIsNone(parse_track_ids(None));self.assertEqual(parse_track_ids('none'),set())
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=main(['tracks',str(self.source),'--lang','en'])
        self.assertEqual(code,0);self.assertIn('Track 2:',output.getvalue())
        with patch('daw2bms.pipeline.convert',return_value={'output_directory':str(self.root),'status':'midi_only','chart':None,'midi':None}) as run,contextlib.redirect_stdout(io.StringIO()):
            code=main(['convert',str(self.source),'--play-tracks','none','--exclude-tracks','3','--lang','en'])
        self.assertEqual(code,0);self.assertEqual(run.call_args.kwargs['play_tracks'],set());self.assertEqual(run.call_args.kwargs['exclude_tracks'],{3})

    @unittest.skipIf(np is None,'Install [audio]')
    def test_als_roles_share_the_same_behavior(self):
        case=als_tests.AlsRenderingTests();case.setUp()
        try:
            for ident in (8,9):
                t=deepcopy(case.xml.find('LiveSet/Tracks/MidiTrack'));t.set('Id',str(ident));case.xml.find('LiveSet/Tracks').append(t)
            case.store()
            r=case.convert(play_tracks={7},exclude_tracks={9})
            self.assertEqual((r['playable_notes'],r['bgm_events']),(2,2))
            self.assertEqual(r['track_roles'],{'7':'play','8':'bgm','9':'exclude'})
            self.assertEqual(len(als_tests.FakeExporter.calls),2)
        finally:case.tearDown()

    def test_return_fx_are_not_misrepresented_as_excludable_note_tracks(self):
        import xml.etree.ElementTree as ET
        case=als_tests.AlsRenderingTests();case.setUp()
        try:
            ET.SubElement(case.xml.find('LiveSet/Tracks'),'ReturnTrack',Id='20')
            case.store()
            with self.assertRaises(FlpError):case.convert(exclude_tracks={20})
        finally:case.tearDown()
