import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from daw2bms.bridge import handle,options_from_json,BridgeCancelled
from daw2bms.keysounds import sha256_file
from test_flp import fixture


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'工程 & input.flp';self.source.write_bytes(fixture());self.events=[]
    def tearDown(self):self.tmp.cleanup()
    def request(self,action='convert'):
        return {'protocol':1,'action':action,'source':str(self.source),'out':str(self.root/'out'),
                'language':'en','options':{'source_sha256':sha256_file(self.source),'play_tracks':[],'exclude_tracks':[]}}
    def test_inspect_is_structured_and_does_not_render(self):
        with patch('daw2bms.bridge.convert') as render:
            self.assertEqual(handle(self.request('inspect'),self.events.append),0)
        render.assert_not_called();self.assertEqual(self.events[-1]['type'],'tracks')
        self.assertEqual(self.events[-1]['data']['arrangements'][0]['tracks'][0]['id'],1)
    def test_midi_fallback_emits_terminal_result(self):
        with patch('daw2bms.pipeline.find_fl_executable',return_value=None):
            self.assertEqual(handle(self.request(),self.events.append),0)
        result=self.events[-1];self.assertEqual(result['type'],'result');self.assertEqual(result['data']['status'],'midi_only')
        self.assertTrue((self.root/'out/song.mid').is_file())
        self.assertTrue(any(e.get('level')=='warning' for e in self.events))
        json.dumps(self.events,allow_nan=False)
    def test_cancel_preserves_generated_midi_and_report(self):
        flag=threading.Event()
        def convert(source,destination,progress,**kwargs):
            destination.mkdir();(destination/'song.mid').write_bytes(b'preserved')
            (destination/'conversion.json').write_text(json.dumps({'status':'running','output_directory':str(destination),'midi':'song.mid','chart':None}))
            flag.set();progress('next operation')
        with patch('daw2bms.bridge.convert',side_effect=convert):
            self.assertEqual(handle(self.request(),self.events.append,flag),0)
        self.assertEqual(self.events[-1]['type'],'cancelled')
        self.assertEqual(json.loads((self.root/'out/conversion.json').read_text())['status'],'cancelled')
        self.assertEqual((self.root/'out/song.mid').read_bytes(),b'preserved')
    def test_stale_project_and_unknown_options_rejected(self):
        request=self.request();self.source.write_bytes(fixture(version='26.0'))
        with self.assertRaises(Exception):handle(request,self.events.append)
        for extra in ({'play_tracks':[True]},{'command':'arbitrary'},{'source_sha256':'bad'}):
            with self.assertRaises(ValueError):options_from_json({**request['options'],**extra})

    def test_cancel_monitor_does_not_deadlock_audio_library_import(self):
        import importlib.util, subprocess, sys
        if importlib.util.find_spec('numpy') is None:self.skipTest('Install audio dependencies')
        code="""import threading
from daw2bms.bridge import monitor_control
cancelled,finished=threading.Event(),threading.Event()
t=threading.Thread(target=monitor_control,args=(cancelled,finished),daemon=True);t.start()
import numpy,soundfile
print('READY',flush=True)
finished.set();t.join(1)
"""
        process=subprocess.Popen([sys.executable,'-u','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            # Keep stdin open throughout: closing it would mask this regression.
            process.wait(timeout=15)
            self.assertEqual(process.returncode,0)
            self.assertIn(b'READY',process.stdout.read())
        finally:
            if process.poll() is None:process.kill();process.wait()
            process.stdin.close();process.stdout.close();process.stderr.close()
