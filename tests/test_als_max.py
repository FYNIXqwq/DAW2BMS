from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from daw2bms.als import AlsError
from daw2bms.als_max import (MAX_TYPES, prepare_max, max_requirements, verify_snapshot,
                           verify_files, check_max_log, wait_for_max, bridge_read)
from daw2bms.als_bank import set_value
from test_als_render import native_fixture
import test_als_render as render_tests


def max_device(path, kind='MxDeviceInstrument'):
    d = ET.Element(kind,Id='5')
    set_value(d,'On/Manual','true')
    set_value(d,'PatchSlot/Value/MxPatchRef/FileRef/Path',str(path))
    set_value(d,'PatchSlot/Value/MxPatchRef/FileRef/RelativePath',path.name)
    p = ET.SubElement(ET.SubElement(ET.SubElement(d,'ParameterList'),'ParameterList'),'MxDFloatParameter',Id='0')
    set_value(p,'Name','Gain');set_value(p,'Timeable/Manual','0.375');set_value(p,'IsStored','true')
    set_value(d,'BlobSlot/Value/MxDBlob/Blob','opaque saved state')
    set_value(d,'Routables/InRoutings/MxDInRoutable/Routable/Target','AudioIn/None')
    return d


class MaxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.amxd=self.root/'Synth.amxd';self.amxd.write_bytes(b'ampf'+b'\0'*20)
        self.source=self.root/'source.als'
        self.xml=native_fixture();self.container=self.xml.find('LiveSet/Tracks/MidiTrack/DeviceChain/DeviceChain/Devices')
        self.container.clear();self.device=max_device(self.amxd);self.container.append(self.device)

    def tearDown(self):self.tmp.cleanup()

    def snapshot(self):
        return {'schema':'ableton_mcp_snapshot_v2','tracks':[{'devices':[{'name':'Synth',
            'class_name':'MxDeviceInstrument','parameters':[{'index':0,'name':'Device On','value':1},
            {'index':1,'name':'Gain','value':.375,'is_enabled':True}]}], 'arrangement_clips':[{'name':'key0'}]}]}

    def test_all_three_max_classes_and_relative_relocation(self):
        original=ET.tostring(self.device.find('BlobSlot'))
        for kind in MAX_TYPES:
            with self.subTest(kind=kind):
                self.device.tag=kind
                set_value(self.device,'PatchSlot/Value/MxPatchRef/FileRef/Path','Z:/lost/Synth.amxd')
                set_value(self.device,'PatchSlot/Value/MxPatchRef/FileRef/RelativePath','Synth.amxd')
                prepare_max(self.xml,self.root/'moved/source.als',(self.root,))
                req=max_requirements(self.xml)[0]
                self.assertEqual(req['class_name'],kind)
                self.assertEqual(req['files'][0]['path'],str(self.amxd.resolve()))
                self.assertEqual(ET.tostring(self.device.find('BlobSlot')),original)
                self.assertEqual(req['parameters'],[{'name':'Gain','value':.375,'index':1}])

    def test_missing_device_and_file_drop_dependency(self):
        set_value(self.device,'FileDropList/FileDropList/Entry/FileRef/Path',str(self.root/'absent.wav'))
        with self.assertRaises(AlsError):prepare_max(self.xml,self.source,())
        self.device.remove(self.device.find('FileDropList'));self.amxd.unlink()
        with self.assertRaises(AlsError):prepare_max(self.xml,self.source,())

    def test_invalid_amxd_and_changed_file(self):
        req=max_requirements(self.xml)
        self.amxd.write_bytes(b'not a device')
        with self.assertRaises(AlsError):prepare_max(self.xml,self.source,())
        with self.assertRaises(AlsError):verify_files(req)

    def test_hidden_max_indices_and_duplicate_long_names(self):
        plist=self.device.find('ParameterList/ParameterList')
        parameter=plist[0];set_value(parameter,'Name','Delay');set_value(parameter,'Index',0)
        hidden=ET.SubElement(plist,'MxDRemoteableIntParameter');set_value(hidden,'Index',1);set_value(hidden,'Name','Hidden')
        second=deepcopy(parameter);set_value(second,'Index',40);set_value(second,'ShortName','Second Delay');set_value(second,'Timeable/Manual',.75);plist.append(second)
        req=max_requirements(self.xml)
        self.assertEqual([p['index'] for p in req[0]['parameters']],[1,2])
        s=self.snapshot();params=s['tracks'][0]['devices'][0]['parameters'];params[1]['name']='Delay'
        params.append({'index':2,'name':'Second Delay','value':.75,'is_enabled':True})
        self.assertTrue(verify_snapshot(s,req,['key0']))
        params[2]['value']=.375
        self.assertFalse(verify_snapshot(s,req,['key0']))

    def test_ambiguous_relocation_is_rejected(self):
        one=self.root/'a';two=self.root/'b';one.mkdir();two.mkdir()
        for folder in (one,two):(folder/'Synth.amxd').write_bytes(b'ampf'+b'\0'*20)
        self.amxd.unlink()
        with self.assertRaises(AlsError):prepare_max(self.xml,self.root/'lost/source.als',(one,two))

    def test_cross_device_mapping_and_additional_routing_rejected(self):
        set_value(self.device,'IdRefList/IdRefList/Entry/PointeeId',123)
        with self.assertRaises(AlsError):prepare_max(self.xml,self.source,())
        self.device.remove(self.device.find('IdRefList'))
        set_value(self.device,'Routables/InRoutings/MxDInRoutable/Routable/Target','AudioIn/Track.9')
        with self.assertRaises(AlsError):prepare_max(self.xml,self.source,())

    def test_snapshot_rejects_wrong_song_device_parameters_and_disabled_parameter(self):
        req=max_requirements(self.xml);s=self.snapshot()
        self.assertTrue(verify_snapshot(s,req,['key0']))
        for field,val in (('name','Other'),('class_name','PluginDevice')):
            wrong=deepcopy(s);wrong['tracks'][0]['devices'][0][field]=val
            self.assertFalse(verify_snapshot(wrong,req,['key0']))
        wrong=deepcopy(s);wrong['tracks'][0]['devices'][0]['parameters'][1]['value']=0
        self.assertFalse(verify_snapshot(wrong,req,['key0']))
        wrong=deepcopy(s);wrong['tracks'][0]['devices'][0]['parameters'][1]['is_enabled']=False
        self.assertFalse(verify_snapshot(wrong,req,['key0']))
        self.assertFalse(verify_snapshot(s,req,['other-job']))

    def test_nested_return_and_master_locations(self):
        self.container.remove(self.device)
        rack=ET.SubElement(self.container,'InstrumentGroupDevice')
        branch=ET.SubElement(ET.SubElement(rack,'Branches'),'InstrumentBranch')
        nested=ET.SubElement(ET.SubElement(ET.SubElement(branch,'DeviceChain'),'MidiToAudioDeviceChain'),'Devices')
        nested.append(self.device)
        master=self.xml.find('LiveSet/MasterTrack/DeviceChain')
        ET.SubElement(ET.SubElement(master,'DeviceChain'),'Devices').append(max_device(self.amxd,'MxDeviceAudioEffect'))
        req=max_requirements(self.xml)
        self.assertEqual(req[0]['location'],['tracks',0,0,'chains',0,0])
        self.assertEqual(req[1]['location'],['master_track',0])
        s=self.snapshot();d=s['tracks'][0]['devices'][0]
        s['tracks'][0]['devices']=[{'chains':[{'kind':'chains','index':0,'devices':[d]}]}]
        s['master_track']={'devices':[{**d,'class_name':'MxDeviceAudioEffect'}]}
        self.assertTrue(verify_snapshot(s,req,['key0']))

    def test_old_log_and_max_errors_rejected(self):
        marker='Loading document "'+str(self.source.resolve())+'"\n'
        check_max_log(marker+'info: Max: ready\n',self.source)
        for text in ('old job',marker+'error: Max: missing external object\n',marker+'info: patcher: no such object\n',marker+'Loading document "other"'):
            with self.assertRaises(AlsError):check_max_log(text,self.source)

    def test_bridge_requires_stable_readback_and_never_writes(self):
        calls=[]
        def read(command,params=None,**kwargs):
            calls.append(command)
            if command=='get_script_info':return {'protocol_version':1,'snapshot_schema':'ableton_mcp_snapshot_v2','capabilities':['get_session_snapshot']}
            return self.snapshot()
        with patch('daw2bms.als_max.bridge_read',side_effect=read),patch('daw2bms.als_max.time.sleep'):
            result=wait_for_max(max_requirements(self.xml),['key0'],timeout=2)
        self.assertEqual(result['instances'],1)
        self.assertEqual(calls,['get_script_info','get_session_snapshot','get_session_snapshot'])
        with self.assertRaises(ValueError):bridge_read('set_device_parameter')

    def test_malformed_stored_parameter_is_not_ignored(self):
        set_value(self.device.find('ParameterList/ParameterList/*'),'Timeable/Manual','NaN')
        with self.assertRaises(AlsError):max_requirements(self.xml)

    def test_bridge_absent_or_parameter_mismatch_never_succeeds(self):
        with patch('daw2bms.als_max.socket.create_connection',side_effect=OSError('offline')):
            with self.assertRaises(AlsError):bridge_read('get_script_info')
        with patch('daw2bms.als_max.verify_bridge'),patch('daw2bms.als_max.bridge_read',return_value=self.snapshot()):
            with self.assertRaises(AlsError):wait_for_max(max_requirements(self.xml),['wrong clip'],timeout=.1)

    def test_parameterless_and_unknown_nodes_are_not_silently_accepted(self):
        self.device.remove(self.device.find('ParameterList'))
        with self.assertRaises(AlsError):max_requirements(self.xml)
        self.device.tag='MxDeviceUnknown'
        with self.assertRaises(AlsError):prepare_max(self.xml,self.source,())

    def test_missing_max_track_keeps_midi_without_blocking_native(self):
        # Reuse the existing fake renderer to test the public conversion result.
        test=render_tests.AlsRenderingTests();test.setUp()
        try:
            clone=deepcopy(test.xml.find('LiveSet/Tracks/MidiTrack'));clone.set('Id','8')
            ds=clone.find('DeviceChain/DeviceChain/Devices');ds.clear();ds.append(max_device(test.root/'missing.amxd'))
            test.xml.find('LiveSet/Tracks').append(clone);test.store()
            result=test.convert()
            self.assertEqual(result['audio_events'],2);self.assertEqual(result['midi_only_notes'],2)
            self.assertFalse(result['audio_complete'])
            self.assertTrue(any('Max for Live file' in str(w) for w in result['warnings']))
        finally:test.tearDown()
