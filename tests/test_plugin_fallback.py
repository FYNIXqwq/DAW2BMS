import contextlib
import io
import struct
from unittest.mock import patch

from daw2bms.__main__ import main
from daw2bms.adaptive import cut
from daw2bms.flp import read_events
from daw2bms.keysounds import encode_event
from daw2bms.resources import inspect_plugin, resource_warnings
from test_flp import event, fixture, text
from test_keysounds import BankFixture


def plugin_fixture(name, state=b"opaque state", *, effect=False):
    raw = fixture()
    _, events = read_events(raw)
    result = bytearray()
    for e in events:
        if effect and e.id == 98:
            result += event(201, text(name)) + event(213, state)
        result += encode_event(e.id, e.data)
        if not effect and e.id == 64:
            result += event(201, text(name)) + event(213, state)
    return raw[:18] + struct.pack("<I", len(result)) + result


def wrapper(path):
    data = str(path).encode("utf-8")
    return struct.pack("<IIQ", 12, 55, len(data)) + data


class UniversalPluginFallbackTests(BankFixture):
    def test_arbitrary_missing_native_generator_keeps_midi(self):
        manifest = self.make_bank(plugin_fixture("Uninstalled New Synth"), fl_exe=self.root / "FL/FL64.exe")
        self.assertIsNone(manifest["bank"])
        self.assertEqual(len(manifest["fallback"]["notes"]), 1)
        self.assertIn("Uninstalled New Synth", "\n".join(resource_warnings(manifest["resources"])))
        self.assertTrue((self.destination / "fallback.mid").exists())

    def test_arbitrary_installed_native_generator_is_not_downgraded(self):
        dll = self.root / "FL/Plugins/Fruity/Generators/New Synth/New Synth_x64.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"test binary presence")
        manifest = self.make_bank(plugin_fixture("New Synth"), fl_exe=self.root / "FL/FL64.exe")
        self.assertEqual(len(manifest["keys"]), 1)
        self.assertEqual(manifest["fallback"]["notes"], [])

    def test_missing_vst2_and_vst3_have_identical_fallback(self):
        for extension in ("dll", "vst3"):
            with self.subTest(extension=extension):
                self.destination = self.root / extension
                manifest = self.make_bank(plugin_fixture("Fruity Wrapper", wrapper(self.root / f"Missing.{extension}")))
                self.assertIsNone(manifest["bank"])
                self.assertEqual(len(manifest["fallback"]["notes"]), 1)
                self.assertIn(f"Missing.{extension}", "\n".join(resource_warnings(manifest["resources"])))

    def test_unknown_wrapper_state_is_not_assumed_available(self):
        manifest = self.make_bank(plugin_fixture("Fruity Wrapper", b"unsupported encoding"))
        self.assertIsNone(manifest["bank"])
        self.assertEqual(manifest["resources"][0]["missing"], [])
        self.assertTrue(manifest["resources"][0]["blockers"])
        self.assertIn("unverified", next(resource_warnings(manifest["resources"])))

    def test_missing_effect_in_first_slot_keeps_entire_selection_as_midi(self):
        manifest = self.make_bank(plugin_fixture("Missing Effect", effect=True), fl_exe=self.root / "FL/FL64.exe")
        self.assertIsNone(manifest["bank"])
        effect = manifest["resources"][0]["blocking_effects"][0]
        self.assertEqual(effect["slot_index"], 0)
        self.assertEqual(effect["plugin"], "Missing Effect")
        warning = next(resource_warnings(manifest["resources"]))
        self.assertIn("all selected notes kept as MIDI", warning)

    def test_installed_effect_does_not_block(self):
        dll = self.root / "FL/Plugins/Fruity/Effects/Present Effect/Present Effect_x64.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"test binary presence")
        manifest = self.make_bank(plugin_fixture("Present Effect", effect=True), fl_exe=self.root / "FL/FL64.exe")
        self.assertEqual(len(manifest["keys"]), 1)
        self.assertFalse(manifest["resources"][0]["blocking_effects"])

    def test_missing_vst_effect_skips_renderer_and_warns_in_cut(self):
        self.source.write_bytes(plugin_fixture("Fruity Wrapper", wrapper(self.root / "LostFx.vst3"), effect=True))
        messages = []
        with patch("daw2bms.adaptive.render") as renderer:
            result = cut(self.source, self.destination, self.root / "FL/FL64.exe", progress=messages.append)
        self.assertEqual(result["status"], "midi_only")
        renderer.assert_not_called()
        self.assertTrue((self.destination / "fallback.mid").exists())
        self.assertTrue(any("WARNING" in message and "LostFx.vst3" in message for message in messages))

    def test_cli_native_plugin_warning_is_on_stderr(self):
        self.source.write_bytes(plugin_fixture("Generic Missing Plugin"))
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(["--lang", "en", "prepare", str(self.source), "--out", str(self.destination), "--fl-exe", str(self.root / "FL/FL64.exe")])
        self.assertEqual(code, 0)
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("Generic Missing Plugin", err.getvalue())
        self.assertIn("MIDI only", err.getvalue())

    def test_empty_vst3_directory_is_not_an_installed_plugin(self):
        bundle = self.root / "Empty.vst3"
        bundle.mkdir()
        checked = inspect_plugin("Fruity Wrapper", wrapper(bundle), {}, [])
        self.assertTrue(checked["missing"])
        binary = bundle / "Contents/x86_64-win/Plugin.vst3"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"test bundle binary presence")
        self.assertFalse(inspect_plugin("Fruity Wrapper", wrapper(bundle), {}, [])["missing"])

    def test_patcher_with_unverified_nested_plugins_uses_midi(self):
        checked = inspect_plugin("Patcher", b"nested opaque data", {"patcher": self.root / "Patcher_x64.dll"}, [])
        self.assertFalse(checked["missing"])
        self.assertTrue(checked["blockers"])
