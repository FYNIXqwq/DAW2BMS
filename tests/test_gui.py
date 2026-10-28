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
        self.source.write_bytes(b"input fixture; fake converter does not parse")
        self.settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        self.window = None

    def tearDown(self):
        if self.window:
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

    def test_bad_tail_limits_are_inline_errors(self):
        window = self.create_window(self.success)
        window.initial_tail.setValue(10)
        window.max_tail.setValue(2)
        window.start_conversion()
        self.assertFalse(window.is_running())
        self.assertIn("不能短於", window.operation_detail.text())

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
