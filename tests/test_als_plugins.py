from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from daw2bms.als import AlsError
from daw2bms.als_plugins import plugin_requirements, read_inventory, verify_inventory, verify_load_log
from daw2bms.als_bank import prepare_track
from test_als_render import native_fixture


UID = '12345678-0123-4567-89ab-cdef12345678'


def plugin(kind='vst3', name='Test Synth'):
    device = ET.Element('PluginDevice', Id='1')
    desc = ET.SubElement(device, 'PluginDesc')
    info = ET.SubElement(desc, 'Vst3PluginInfo' if kind == 'vst3' else 'VstPluginInfo', Id='0')
    ET.SubElement(info, 'Name' if kind == 'vst3' else 'PlugName', Value=name)
    if kind == 'vst3':
        uid = ET.SubElement(info, 'Uid')
        for i, n in enumerate((0x12345678,0x01234567,0x89abcdef,0x12345678)):
            ET.SubElement(uid, 'Fields.'+str(i), Value=str(n))
    else:
        ET.SubElement(info, 'UniqueId', Value='-1')
    preset = ET.SubElement(ET.SubElement(info, 'Preset'), 'Vst3Preset' if kind == 'vst3' else 'VstPreset')
    ET.SubElement(preset, 'ProcessorState').text = 'DEADBEEF0123456789'
    return device


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.module = self.root/'test.vst3';self.module.touch()
        self.req = plugin_requirements(plugin())
        self.row = dict(dev_identifier='device:vst3:instr:'+UID,name='Test Synth',scanstate=1,
                        enabled=1,module_scanstate=1,domain_enabled=1,arch=3,path=str(self.module))
        self.project = self.root/'unique-job.als'

    def tearDown(self):self.tmp.cleanup()

    def log(self):
        return ('info: Loading document "'+str(self.project)+'"\n'
                "info: VST3: plugin processor successfully loaded: Vendor 'Test Synth' v1 (cid: {"+UID+"})\n"
                'info: VST3: Restored: Test Synth\n')

    def test_vst3_and_signed_vst2_ids(self):
        self.assertEqual(self.req[0]['identity'],UID)
        req = plugin_requirements(plugin('vst'))
        self.assertEqual(req[0]['identity'],'4294967295')
        row = {**self.row,'dev_identifier':'device:vst:instr:4294967295?n=Test%20Synth','arch':2}
        self.assertEqual(verify_inventory(req,[row])[0]['format'],'vst')

    def test_disabled_failed_missing_and_wrong_arch_rejected(self):
        for field in ('enabled','scanstate','module_scanstate','domain_enabled','arch'):
            with self.subTest(field=field), self.assertRaises(AlsError):
                verify_inventory(self.req,[{**self.row,field:0}])
        self.module.unlink()
        with self.assertRaises(AlsError):verify_inventory(self.req,[self.row])

    def test_same_name_wrong_id_is_never_substituted(self):
        with self.assertRaises(AlsError):verify_inventory(self.req,[{**self.row,'dev_identifier':'device:vst3:instr:00000000-0000-0000-0000-000000000000'}])

    def test_nested_plugin_and_fx_state_remain_unchanged(self):
        root = native_fixture();track = root.find('LiveSet/Tracks/MidiTrack')
        rack = ET.SubElement(track.find('DeviceChain/DeviceChain/Devices'),'InstrumentGroupDevice')
        rack.append(plugin())
        master = root.find('LiveSet/MasterTrack');master.append(plugin())
        before = ET.tostring(root)
        doc = {'tracks':[{'id':7,'group_id':-1}]}
        with patch('daw2bms.als_plugins.read_inventory',return_value=[self.row]):
            prepared = prepare_track(root,doc,7,self.root/'source.als')
        self.assertEqual(ET.tostring(root),before)
        self.assertEqual([e.text for e in prepared.iter('ProcessorState')],['DEADBEEF0123456789']*2)
        self.assertEqual(len(plugin_requirements(prepared)),2)

    def test_fresh_id_and_restored_instance_required(self):
        verified=verify_inventory(self.req,[self.row])
        self.assertEqual(verify_load_log(self.log(),self.project,verified)['instances'],1)
        for text in (self.log().replace('Restored:','Created:'),self.log().replace(UID,'0'*36),
                     self.log().replace(str(self.project),'old.als'),self.log()+'info: Loading document "other.als"\n'):
            with self.assertRaises(AlsError):verify_load_log(text,self.project,verified)
        with self.assertRaises(AlsError):verify_load_log(self.log(),self.project,verified*2)

    def test_bus_warning_requires_subsequent_success_and_state_errors_fail(self):
        verified=verify_inventory(self.req,[self.row])
        warning='error: VST3: plugin processor output audio bus 0 could not be deactivated (error: false)\n'
        self.assertEqual(verify_load_log(self.log()+warning,self.project,verified)['instances'],1)
        with self.assertRaises(AlsError):verify_load_log(self.log()+'error: VST3: failed to restore state\n',self.project,verified)

    def test_unknown_format_and_bad_uid_fail_closed(self):
        bad=plugin();bad.find('PluginDesc/Vst3PluginInfo/Uid/Fields.2').set('Value','NaN')
        with self.assertRaises(AlsError):plugin_requirements(bad)
        bad.find('PluginDesc/Vst3PluginInfo').tag='AuPluginInfo'
        with self.assertRaises(AlsError):plugin_requirements(bad)

    def test_vst2_requires_restoration_and_scanned_dll_path(self):
        req = plugin_requirements(plugin('vst'))
        row = {**self.row,'dev_identifier':'device:vst:instr:4294967295?n=Test%20Synth','arch':2}
        verified = verify_inventory(req,[row])
        log = ('info: Loading document "'+str(self.project)+'"\n'
               'info: VST2: Plugin Path: "'+str(self.module)+'"\n'
               'info: VST2: Restored: Test Synth\n')
        self.assertEqual(verify_load_log(log,self.project,verified)['instances'],1)
        with self.assertRaises(AlsError):verify_load_log(log.replace(str(self.module),'other.dll'),self.project,verified)

    def test_shell_client_name_disambiguates_shared_id(self):
        device=plugin('vst');ET.SubElement(device.find('PluginDesc/VstPluginInfo'),'IsShellClient',Value='true')
        req=plugin_requirements(device)
        row={**self.row,'dev_identifier':'device:vst:instr:4294967295?n=Other','arch':2}
        with self.assertRaises(AlsError):verify_inventory(req,[row])
        row['dev_identifier']='device:vst:instr:4294967295?n=Test%20Synth'
        self.assertEqual(verify_inventory(req,[row])[0]['loaded_name'],'Test Synth')

    def test_database_is_read_only_and_unknown_schema_rejected(self):
        path=self.root/'plugins.db'
        with sqlite3.connect(path) as db:db.execute('CREATE TABLE version(version INT,platform INT)');db.execute('INSERT INTO version VALUES(99,1)')
        before=path.read_bytes()
        with self.assertRaises(AlsError):read_inventory(path)
        self.assertEqual(path.read_bytes(),before)
        with self.assertRaises(AlsError):read_inventory(self.root/'missing.db')
        self.assertFalse((self.root/'missing.db').exists())

    def test_helper_error_keeps_localizable_message(self):
        import json
        from daw2bms.ableton_ui import _pack_message, _unpack_message
        from daw2bms.i18n import msg, render
        error=AlsError(msg('Cannot identify Ableton plug-in {p0}; MIDI is preserved.',p0='Test Synth'))
        restored=_unpack_message(json.loads(json.dumps(_pack_message(error))))
        self.assertIn('無法識別',render(restored,'zh-TW'))
        self.assertIn('Test Synth',render(restored,'ja'))
        self.assertEqual(str(restored),str(error))
