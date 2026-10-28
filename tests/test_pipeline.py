import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from daw2bms.__main__ import main
from daw2bms.flp import FlpError
from daw2bms.pipeline import convert, default_destination, find_fl_executable
from daw2bms.keysounds import load_manifest, tick_to_frame
from test_flp import fixture, note
from test_keysounds import BankFixture, np, sf
from test_resources_midi import flex_fixture


class PipelineTests(BankFixture):
    def test_fl_detection_prefers_numeric_newest_and_explicit_override(self):
        roots = [self.root / name for name in ("FL Studio 9", "FL Studio 2026", "FL Studio 12")]
        for root in roots:
            root.mkdir()
            (root / "FL64.exe").write_bytes(b"fixture")
        with patch.dict(os.environ, {"DAW2BMS_FL_EXE": ""}), patch("daw2bms.pipeline.installed_fl_roots", return_value=roots):
            self.assertEqual(find_fl_executable(), roots[1] / "FL64.exe")
            self.assertEqual(find_fl_executable(roots[0] / "FL64.exe"), roots[0] / "FL64.exe")
            with patch.dict(os.environ, {"DAW2BMS_FL_EXE": str(roots[2] / "FL64.exe")}):
                self.assertEqual(find_fl_executable(), roots[2] / "FL64.exe")

    def test_missing_fl_exports_midi_without_audio_dependencies_or_process(self):
        self.source.write_bytes(fixture())
        before = self.source.read_bytes()
        messages = []
        with patch("daw2bms.pipeline.find_fl_executable", return_value=None), patch("daw2bms.adaptive.render") as renderer:
            result = convert(self.source, self.destination, progress=messages.append)
        self.assertEqual(result["status"], "midi_only")
        self.assertIsNone(result["chart"])
        self.assertTrue((self.destination / "song.mid").exists())
        self.assertTrue((self.destination / "fallback.mid").exists())
        self.assertTrue((self.destination / "project.json").exists())
        self.assertFalse((self.destination / "chart").exists())
        self.assertTrue(any("FL Studio was not found" in message for message in messages))
        self.assertEqual(before, self.source.read_bytes())
        renderer.assert_not_called()

    def test_all_plugins_missing_skips_chart_and_retains_warning(self):
        self.source.write_bytes(flex_fixture())
        exe = self.root / "FL.exe"
        exe.write_bytes(b"placeholder")
        with patch("daw2bms.adaptive.render") as renderer:
            result = convert(self.source, self.destination, fl_exe=exe, progress=lambda message: None)
        self.assertEqual(result["status"], "midi_only")
        self.assertTrue(any("Absent Pack.flexpack" in warning for warning in result["warnings"]))
        self.assertEqual(result["midi_only_notes"], 1)
        renderer.assert_not_called()

    def test_renderer_failure_keeps_midi_and_reports_failing_stage(self):
        self.source.write_bytes(fixture())
        exe = self.root / "FL.exe"
        exe.write_bytes(b"placeholder")
        with patch("daw2bms.adaptive.render", side_effect=FlpError("render failed")):
            with self.assertRaisesRegex(FlpError, "render failed"):
                convert(self.source, self.destination, fl_exe=exe, progress=lambda message: None)
        report = json.loads((self.destination / "conversion.json").read_text())
        self.assertEqual((report["status"], report["stage"]), ("error", "cut"))
        self.assertEqual(report["midi"], "song.mid")
        self.assertFalse((self.destination / "chart").exists())

    def test_default_directory_is_derived_from_input_and_does_not_overwrite(self):
        with patch("daw2bms.pipeline.Path", wraps=Path):
            # A temporary current directory also exercises spaces and Unicode names.
            previous = Path.cwd()
            try:
                os.chdir(self.root)
                candidate = default_destination(Path("歌曲 demo.flp"))
                self.assertEqual(candidate.name, "歌曲 demo-bms")
                candidate.mkdir(parents=True)
                self.assertEqual(default_destination(Path("歌曲 demo.flp")).name, "歌曲 demo-bms-2")
            finally:
                os.chdir(previous)

    def test_explicit_existing_output_is_untouched(self):
        self.source.write_bytes(fixture())
        self.destination.mkdir()
        marker = self.destination / "keep.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(FlpError, "already exists"):
            convert(self.source, self.destination)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(len(list(self.destination.iterdir())), 1)

    def test_cli_requires_only_project_path_and_warns_on_stderr(self):
        self.source.write_bytes(fixture())
        out, err = io.StringIO(), io.StringIO()
        with patch("daw2bms.pipeline.default_destination", return_value=self.destination), \
                patch("daw2bms.pipeline.find_fl_executable", return_value=None), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["convert", str(self.source)])
        self.assertEqual(code, 0)
        self.assertIn("WARNING:", err.getvalue())
        self.assertNotIn("WARNING:", out.getvalue())
        self.assertIn("Result: midi_only", out.getvalue())

    @unittest.skipIf(sf is None, "Install [audio] extra")
    def test_full_pipeline_with_missing_plugin_keeps_remaining_audio(self):
        self.source.write_bytes(flex_fixture(mixed=True))
        exe = self.root / "FL.exe"
        exe.write_bytes(b"placeholder")

        def fake_render(manifest_path, executable, **options):
            manifest = load_manifest(manifest_path)
            rate = 8000
            timing = manifest["timing"]
            frames = tick_to_frame(manifest["bank"]["length_ticks"], timing["ppq"], timing["bpm"], rate)
            audio = np.zeros((frames, 2), dtype="float32")
            for key in manifest["keys"]:
                onset = tick_to_frame(key["onset_ticks"], timing["ppq"], timing["bpm"], rate)
                audio[onset + 5:onset + 25] = 0.25
            sf.write(manifest_path.parent / "render_bank.wav", audio, rate, subtype="FLOAT")
            return {"status": "rendered"}

        with patch("daw2bms.adaptive.render", side_effect=fake_render):
            result = convert(self.source, self.destination, fl_exe=exe, title="Custom Title", progress=lambda message: None)
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["audio_complete"])
        self.assertEqual((result["audio_events"], result["midi_only_notes"]), (1, 1))
        self.assertTrue((self.destination / result["chart"]).exists())
        self.assertIn("Custom Title", (self.destination / result["chart"]).read_text())
        self.assertTrue((self.destination / "chart/fallback.mid").exists())
        self.assertTrue((self.destination / "fallback.mid").exists())
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
