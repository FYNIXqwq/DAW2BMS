import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QT_AVAILABLE = importlib.util.find_spec("PyQt6") is not None
if QT_AVAILABLE:
    from PyQt6.QtCore import QSettings
    from PyQt6.QtGui import QCloseEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from daw2bms.gui import MainWindow, configure_application, next_output

from daw2bms.flp import FlpError


@unittest.skipUnless(QT_AVAILABLE, "Install [gui] extra for offscreen desktop tests")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "任意 工程.flp"
        from test_flp import fixture
        self.source.write_bytes(fixture())
        self.settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        self.window = None

    def tearDown(self):
        if self.window:
            if self.window.track_worker:
                self.window.track_worker.wait(5000)
                self.app.processEvents()
            if self.window.worker:
                self.window.worker.requestInterruption()
                self.window.worker.wait(5000)
                self.app.processEvents()
            self.window.close()
            self.window.deleteLater()
            self.app.processEvents()
        self.temp.cleanup()

    def create_window(self, converter):
        self.window = MainWindow(converter=converter, settings=self.settings, language="zh-TW")
        self.window.source_edit.setText(str(self.source))
        self.window.output_edit.setText(str(self.root / "results"))
        from daw2bms.track_selection import inspect_tracks
        self.window.set_track_preview(inspect_tracks(self.source))
        return self.window

    def wait_finished(self):
        limit = time.monotonic() + 5
        while self.window.is_running() and time.monotonic() < limit:
            QTest.qWait(10)
        self.assertFalse(self.window.is_running(), "GUI worker did not finish")

    @staticmethod
    def success(source, destination, progress, **options):
        destination.mkdir(parents=True)
        (destination / "chart").mkdir()
        (destination / "chart/test.bme").write_text("#PLAYER 1\n")
        (destination / "song.mid").write_bytes(b"fixture")
        progress("[1/3] Reading FLP")
        progress("[2/3] Checking resources")
        progress("Attempt 2: 3 keys; 4 already validated.")
        progress("WARNING: missing plugin; MIDI retained")
        progress("[3/3] Exporting")
        report = {"status": "complete", "chart": "chart/test.bme", "midi": "song.mid", "audio_complete": False,
                  "playable_notes": 12, "bgm_events": 3, "midi_only_notes": 2}
        (destination / "conversion.json").write_text(json.dumps(report))
        return report

    def test_background_success_and_warning_are_distinct(self):
        main_thread = threading.get_ident()
        worker_threads = []
        def converter(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            return self.success(*args, **kwargs)
        window = self.create_window(converter)
        window.start_conversion()
        self.assertFalse(window.start_button.isEnabled())
        self.wait_finished()
        self.assertNotEqual(worker_threads[0], main_thread)
        self.assertIn("部分音源缺失", window.operation_title.text())
        self.assertEqual(window.warning_count, 1)
        self.assertIn("missing plugin", window.warning_log.toPlainText())
        self.assertTrue(window.chart_button.isEnabled())
        self.assertTrue(window.midi_button.isEnabled())
        self.assertTrue(window.report_button.isEnabled())
        self.assertTrue(window.start_button.isEnabled())

    def test_midi_only_does_not_offer_a_chart(self):
        def converter(source, destination, progress, **options):
            destination.mkdir(parents=True)
            (destination / "fallback.mid").write_bytes(b"fixture")
            report = {"status": "midi_only", "chart": None, "fallback_midi": "fallback.mid", "midi_only_notes": 8}
            (destination / "conversion.json").write_text(json.dumps(report))
            return report
        window = self.create_window(converter)
        window.start_conversion()
        self.wait_finished()
        self.assertEqual(window.operation_title.text(), "已保留 MIDI")
        self.assertFalse(window.chart_button.isEnabled())
        self.assertTrue(window.midi_button.isEnabled())
        window.set_stage(0)
        self.assertEqual(window.stage_labels[2].text(), "3  匯出譜面")

    def test_validation_does_not_spawn_worker(self):
        converter = unittest.mock.Mock()
        window = self.create_window(converter)
        window.source_edit.clear()
        window.start_conversion()
        self.assertFalse(window.is_running())
        self.assertIn(".flp", window.operation_detail.text())
        converter.assert_not_called()

    def test_real_pipeline_midi_only_runs_through_gui(self):
        from daw2bms.pipeline import convert
        from test_flp import fixture
        self.source.write_bytes(fixture())
        window = self.create_window(convert)
        with patch("daw2bms.pipeline.find_fl_executable", return_value=None):
            window.start_conversion()
            self.wait_finished()
        self.assertEqual(window.operation_title.text(), "已保留 MIDI")
        self.assertTrue((window.run_directory / "song.mid").exists())
        self.assertGreater(window.warning_count, 0)
        self.assertFalse(window.chart_button.isEnabled())

    def test_real_als_pipeline_ignores_fl_render_settings(self):
        from daw2bms.pipeline import convert
        from test_als import fixture
        import gzip
        self.source = self.root / "日本語 한국어.als"
        self.source.write_bytes(gzip.compress(fixture(version=12)))
        window = self.create_window(convert)
        window.fl_edit.setText(str(self.root / "missing.exe"))
        window.initial_tail.setValue(20)
        window.max_tail.setValue(1)
        self.assertFalse(window.fl_row.isEnabled())
        self.assertFalse(window.initial_tail.isEnabled())
        with patch("daw2bms.pipeline.find_fl_executable", side_effect=AssertionError("ALS must not discover FL")):
            window.start_conversion()
            self.wait_finished()
        self.assertEqual(window.operation_title.text(), "已保留 MIDI")
        self.assertEqual(window.result["daw"], "ableton_live")
        self.assertTrue(window.midi_button.isEnabled())
        self.assertFalse(window.chart_button.isEnabled())
        self.assertEqual(window.stage_labels[1].text(), "2  匯出 MIDI")

    def test_bad_tail_limits_are_inline_errors(self):
        window = self.create_window(self.success)
        window.initial_tail.setValue(10)
        window.max_tail.setValue(2)
        window.start_conversion()
        self.assertFalse(window.is_running())
        self.assertIn("不能短於", window.operation_detail.text())

    def test_als_render_is_explicit_and_enables_audio_options(self):
        window = self.create_window(self.success)
        source = self.root / 'chosen.als'
        from test_als import fixture
        source.write_bytes(fixture())
        window.set_source(str(source))
        from daw2bms.track_selection import inspect_tracks
        window.set_track_preview(inspect_tracks(source))
        self.assertFalse(window.ableton_render.isChecked())
        self.assertFalse(window.initial_tail.isEnabled())
        window.ableton_render.setChecked(True)
        self.assertTrue(window.initial_tail.isEnabled())
        self.assertTrue(window.ableton_row.isEnabled())
        self.assertFalse(window.fl_row.isEnabled())
        _, _, options = window.collect_request()
        self.assertTrue(options['ableton_render'])
        self.assertIsNone(options['ableton_exe'])
        window.active_format = '.als'
        window.set_stage(1)
        self.assertEqual(window.stage_labels[1].text(), window.t('2  Render and slice'))
        window.initial_tail.setValue(10)
        window.max_tail.setValue(2)
        with self.assertRaises(FlpError):
            window.collect_request()

    def test_failure_preserves_result_access(self):
        def converter(source, destination, progress, **options):
            destination.mkdir(parents=True)
            (destination / "song.mid").write_bytes(b"fixture")
            (destination / "conversion.json").write_text(json.dumps({"status": "error", "midi": "song.mid"}))
            raise FlpError("missing dependency")
        window = self.create_window(converter)
        window.start_conversion()
        self.wait_finished()
        self.assertEqual(window.operation_title.text(), "轉換失敗")
        self.assertIn("missing dependency", window.log.toPlainText())
        self.assertTrue(window.midi_button.isEnabled())
        self.assertFalse(window.chart_button.isEnabled())

    def test_stop_and_close_wait_for_current_operation(self):
        entered, release = threading.Event(), threading.Event()
        def converter(source, destination, progress, **options):
            destination.mkdir(parents=True)
            (destination / "conversion.json").write_text(json.dumps({"status": "running"}))
            entered.set()
            release.wait(2)
            progress("next step")
            self.fail("Cancellation must be raised before another step")
        window = self.create_window(converter)
        window.start_conversion()
        self.assertTrue(entered.wait(1))
        close_event = QCloseEvent()
        window.closeEvent(close_event)
        self.assertFalse(close_event.isAccepted())
        window.stop_conversion()
        self.assertTrue(window.is_running())
        self.assertFalse(window.stop_button.isEnabled())
        release.set()
        self.wait_finished()
        self.assertEqual(window.operation_title.text(), "已停止轉換")
        self.assertEqual(json.loads((window.run_directory / "conversion.json").read_text())["status"], "cancelled")

    def test_double_start_is_ignored(self):
        release = threading.Event()
        calls = []
        def converter(*args, **kwargs):
            calls.append(1)
            release.wait(2)
            return self.success(*args, **kwargs)
        window = self.create_window(converter)
        window.start_conversion()
        window.start_conversion()
        release.set()
        self.wait_finished()
        self.assertEqual(len(calls), 1)

    def test_result_paths_cannot_escape_output(self):
        window = self.create_window(self.success)
        window.run_directory = self.root / "results"
        window.run_directory.mkdir()
        window.result = {"midi": "../任意 工程.flp"}
        self.assertIsNone(window.result_path("midi"))

    def test_output_names_are_generated_and_preferences_persist(self):
        window = self.create_window(self.success)
        source, destination, options = window.collect_request()
        self.assertEqual(destination.name, "任意 工程-bms")
        destination.mkdir(parents=True)
        self.assertEqual(next_output(source, destination.parent).name, "任意 工程-bms-2")
        window.start_conversion()
        self.wait_finished()
        self.assertEqual(self.settings.value("last_source"), str(self.source))

    def test_open_buttons_only_use_explicit_local_urls(self):
        window = self.create_window(self.success)
        window.start_conversion()
        self.wait_finished()
        with patch("daw2bms.gui.QDesktopServices.openUrl", return_value=True) as opened:
            window.open_result("chart", directory=True)
        self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), window.run_directory / "chart")

    def test_track_roles_default_to_bgm_and_survive_language_switch(self):
        from test_track_selection import playlist_fixture
        from daw2bms.track_selection import inspect_tracks
        self.source.write_bytes(playlist_fixture())
        window=self.create_window(self.success)
        self.assertEqual(window.track_table.rowCount(),3)
        self.assertTrue(all(window.track_table.cellWidget(i,2).currentData()=='bgm' for i in range(3)))
        window.track_table.cellWidget(0,2).setCurrentIndex(0)
        window.track_table.cellWidget(2,2).setCurrentIndex(2)
        window.set_language('ja')
        _,_,options=window.collect_request()
        self.assertEqual(options['play_tracks'],{1})
        self.assertEqual(options['exclude_tracks'],{3})
        window.set_track_preview(inspect_tracks(self.source))
        self.assertEqual(window.track_table.cellWidget(0,2).currentData(),'play')
        self.assertEqual(window.track_table.cellWidget(2,2).currentData(),'exclude')

    def test_changed_project_and_all_excluded_cannot_convert(self):
        window=self.create_window(self.success)
        combo=window.track_table.cellWidget(0,2);combo.setCurrentIndex(2)
        with self.assertRaises(FlpError):window.collect_request()
        combo.setCurrentIndex(1)
        self.source.write_bytes(b'changed')
        with self.assertRaises(FlpError):window.collect_request()

    def test_background_track_reading_populates_real_rows(self):
        from test_track_selection import playlist_fixture
        self.source.write_bytes(playlist_fixture())
        window=self.create_window(self.success);window.invalidate_tracks();window.load_tracks()
        self.assertFalse(window.start_button.isEnabled())
        deadline=time.monotonic()+5
        while window.track_worker is not None and time.monotonic()<deadline:QTest.qWait(10)
        self.assertIsNone(window.track_worker)
        self.assertEqual(window.track_table.rowCount(),3)
        self.assertTrue(window.start_button.isEnabled())

    def test_unsupported_track_cannot_be_bulk_enabled(self):
        from test_track_selection import playlist_fixture
        self.source.write_bytes(playlist_fixture(unsupported_last=True))
        window=self.create_window(self.success);window.set_all_track_roles('play')
        self.assertFalse(window.track_table.cellWidget(2,2).isEnabled())
        self.assertEqual(window.track_table.cellWidget(2,2).currentData(),'exclude')
        _,_,options=window.collect_request()
        self.assertEqual(options['play_tracks'],{1,2})
        self.assertEqual(options['exclude_tracks'],{3})
