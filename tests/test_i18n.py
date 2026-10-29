import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
from pathlib import Path
import re
from string import Formatter
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from daw2bms.__main__ import main
from daw2bms.flp import FlpError
from daw2bms.i18n import (LANGUAGES, JoinedMessages, Message, catalog, language_context,
    msg, normalize_language, render, resolve_language, split_language_args, system_language, tr)
from test_flp import fixture
from test_gui import QT_AVAILABLE


class CatalogTests(unittest.TestCase):
    def test_all_languages_have_identical_keys_and_placeholders(self):
        english = catalog("en")
        def placeholders(text):
            braces = Counter((name, spec, conversion) for _, name, spec, conversion in Formatter().parse(text) if name is not None)
            percent = Counter(re.findall(r"%(?:\([a-z_]+\))?[rsdi]", text))
            return braces, percent
        for language in LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(set(catalog(language)), set(english))
                for key, value in catalog(language).items():
                    self.assertTrue(value, key)
                    self.assertEqual(placeholders(value), placeholders(english[key]), (language, key))

    def test_application_message_literals_are_in_catalog(self):
        root = Path(__file__).resolve().parents[1] / "daw2bms"
        for path in root.glob("*.py"):
            if path.name == "i18n.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    arg = node.args[0] if name in ("msg", "tr", "self.t", "self._label", "self._button", "self._checkbox") and node.args else None
                    if name == "self._bind" and len(node.args) > 2:
                        arg = node.args[2]
                    if name == "self._add_row" and len(node.args) > 1:
                        arg = node.args[1]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        self.assertIn(arg.value, catalog("en"), (path.name, node.lineno))

    def test_missing_translation_falls_back_to_english(self):
        english = catalog("en")
        with patch("daw2bms.i18n.catalog", side_effect=lambda language: english if language == "en" else {}):
            self.assertEqual(tr("Output: {p0}", "ja", p0="x"), "Output: x")

    def test_parameters_are_raw_data_and_nested_messages_translate(self):
        filename = r"C:\音楽 {p0}\한국어\No placed notes match the selection.flp"
        self.assertEqual(tr("Output: {p0}", "ja", p0=filename), "出力先：" + filename)
        details = JoinedMessages([msg("Plugin identity is unavailable"), "Vendor Plugin.vst3"])
        outer = msg("WARNING: {p0}", p0=details)
        for language in LANGUAGES:
            self.assertIn(catalog(language)["Plugin identity is unavailable"], render(outer, language))
            self.assertIn("Vendor Plugin.vst3", render(outer, language))
        self.assertEqual(render("External library error: raw", "ko"), "External library error: raw")

    def test_machine_json_and_exception_values_stay_english(self):
        message = msg("Output: {p0}", p0="file")
        with language_context("ja"):
            self.assertEqual(json.loads(json.dumps({"message": message}))["message"], "Output: file")
            self.assertEqual(str(FlpError(msg("Invalid manifest timing"))), "Invalid manifest timing")
            self.assertEqual(render(FlpError(msg("Invalid manifest timing"))), catalog("ja")["Invalid manifest timing"])

    def test_context_is_thread_local(self):
        def translate(language):
            with language_context(language):
                time.sleep(0.01)
                return tr("Ready")
        with ThreadPoolExecutor(4) as pool:
            values = list(pool.map(translate, LANGUAGES))
        self.assertEqual(values, [catalog(lang)["Ready"] for lang in LANGUAGES])

    def test_manual_selection_overrides_system(self):
        with patch.dict(os.environ, {"DAW2BMS_LANG": ""}), patch("daw2bms.i18n.system_language", return_value="ja"):
            self.assertEqual(resolve_language(), "ja")
            self.assertEqual(resolve_language(saved="ko"), "ko")
            self.assertEqual(resolve_language("en", saved="ko"), "en")
            with patch.dict(os.environ, {"DAW2BMS_LANG": "zh-TW"}):
                self.assertEqual(resolve_language(saved="ko"), "zh-TW")
                self.assertEqual(resolve_language("en"), "en")
        self.assertEqual(normalize_language("ko_KR.UTF-8"), "ko")
        self.assertEqual(normalize_language("zh-Hant-TW"), "zh-TW")
        self.assertEqual(normalize_language("fr_FR"), "en")

    @unittest.skipUnless(sys.platform == "win32", "Windows UI-language API")
    def test_windows_uses_ui_language_not_regional_number_format(self):
        with patch("ctypes.windll.kernel32.GetUserDefaultUILanguage", return_value=0x0411), \
                patch("locale.getlocale", return_value=("en_US", "UTF-8")):
            self.assertEqual(system_language(), "ja")

    def test_language_option_positions_and_boundary(self):
        for args in (["--lang", "ko", "extract", "a.flp"], ["extract", "a.flp", "--lang=ko"]):
            self.assertEqual(split_language_args(args), ("ko", ["extract", "a.flp"], "ko"))
        self.assertEqual(split_language_args(["--lang", "en", "extract", "--", "--lang"])[1], ["extract", "--", "--lang"])
        with self.assertRaises(ValueError):
            split_language_args(["--lang", "fr"])


class CliLanguageTests(unittest.TestCase):
    def test_localized_error_keeps_path_and_diagnostic_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "日本語 한국어.flp"
            source.write_bytes(b"FLhd")
            for language in LANGUAGES:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = main(["extract", str(source), "--lang", language])
                self.assertEqual(code, 1)
                self.assertIn(catalog(language)["Truncated FLP header (need at least 22 bytes)"], err.getvalue())

    def test_written_summary_uses_selected_language(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "project.flp"
            source.write_bytes(fixture())
            for language in LANGUAGES:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["extract", str(source), "--out", str(root / language), "--lang", language]), 0)
                summary = (root / language / "summary.txt").read_text(encoding="utf-8")
                self.assertIn(catalog(language)["DAW2BMS — FLP structure report"], summary)
                self.assertIn(catalog(language)["Conventions and limitations:"], summary)

    def test_help_and_argument_errors_in_every_language(self):
        original = argparse._
        for language in LANGUAGES:
            with self.subTest(language=language):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stopped:
                    main(["convert", "--lang", language, "--help"])
                self.assertEqual(stopped.exception.code, 0)
                self.assertIn(catalog(language)["show this help message and exit"], out.getvalue())
                self.assertIn("--initial-tail", out.getvalue())
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                    main(["--lang", language, "convert"])
                self.assertIn(catalog(language)["the following arguments are required: %s"] % "source", err.getvalue())
        self.assertIs(argparse._, original)

    def test_system_language_is_default_without_a_manual_flag(self):
        with patch.dict(os.environ, {"DAW2BMS_LANG": ""}), patch("daw2bms.i18n.system_language", return_value="ko"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                main(["--help"])
            self.assertIn("사용법", out.getvalue())

    def test_real_cli_pipeline_warnings_and_midi_in_every_language(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "音樂 日本語 한국어.flp"
            source.write_bytes(fixture())
            for language in LANGUAGES:
                out, err = io.StringIO(), io.StringIO()
                with patch("daw2bms.pipeline.find_fl_executable", return_value=None), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(["convert", str(source), "--out", str(root / language), "--lang", language])
                self.assertEqual(code, 0)
                self.assertIn(tr("Result: {p0}", language, p0="midi_only"), out.getvalue())
                self.assertIn(str(source), out.getvalue())
                self.assertIn(catalog(language)["WARNING: {p0}"].split("{p0}")[0], err.getvalue())
                result = json.loads((root / language / "conversion.json").read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "midi_only")
                self.assertTrue(all(warning.startswith("WARNING:") for warning in result["warnings"]))
                self.assertTrue((root / language / "song.mid").exists())


@unittest.skipUnless(QT_AVAILABLE, "Install [gui] extra")
class GuiLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        from daw2bms.gui import configure_application
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)

    def setUp(self):
        from PyQt6.QtCore import QSettings
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "prefs.ini"), QSettings.Format.IniFormat)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            if window.worker:
                window.worker.requestInterruption()
                window.worker.wait(5000)
                self.app.processEvents()
            window.close()
            window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def window(self, **kwargs):
        from daw2bms.gui import MainWindow
        window = MainWindow(settings=self.settings, **kwargs)
        self.windows.append(window)
        return window

    def test_system_default_manual_persistence_and_reset(self):
        with patch.dict(os.environ, {"DAW2BMS_LANG": ""}), patch("daw2bms.gui.system_language", return_value="ja"):
            window = self.window()
            self.assertEqual(window.language, "ja")
            self.assertEqual(window.language_combo.currentData(), "system")
            window.set_language("ko")
            self.assertEqual(self.settings.value("language"), "ko")
            second = self.window()
            self.assertEqual(second.language, "ko")
            second.set_language("system")
            self.assertEqual(second.language, "ja")
            self.assertEqual(self.window().language, "ja")
            self.assertEqual(self.window(language="en").language, "en")

    def test_retranslation_preserves_user_data_and_progress(self):
        window = self.window(language="en")
        filename = r"C:\Projects\日本語 한국어 {test}.flp"
        window.source_edit.setText(filename)
        window.title_edit.setText("My 曲名")
        window.max_tail.setValue(17.5)
        progress = msg("Attempt {p0}: {p1} keys; {p2} already validated.", p0=2, p1=3, p2=4)
        window.on_message(progress)
        window.on_message(msg("WARNING: {p0}", p0=msg("Plugin identity is unavailable")))
        for language in LANGUAGES:
            window.set_language(language)
            self.assertEqual(window.source_edit.text(), filename)
            self.assertEqual(window.title_edit.text(), "My 曲名")
            self.assertEqual(window.max_tail.value(), 17.5)
            self.assertEqual(window.start_button.text(), catalog(language)["Start conversion"])
            self.assertEqual(window.warning_count, 1)
            self.assertIn(render(progress, language), window.log.toPlainText())
            self.assertEqual(window.operation_title.text(), tr("Processing attempt {p0}", language, p0="2"))
            for message in window._bindings.values():
                if isinstance(message, Message):
                    self.assertIn(message.source, catalog("en"))

    def test_switch_language_during_worker_job(self):
        from PyQt6.QtTest import QTest
        entered, release = threading.Event(), threading.Event()
        def converter(source, destination, progress, **options):
            entered.set()
            release.wait(2)
            progress(msg("[2/3] Checking resources and creating adaptive keysounds"))
            return {"status": "midi_only", "midi_only_notes": 3}
        source = Path(self.temp.name) / "input.flp"
        source.write_bytes(fixture())
        window = self.window(language="en", converter=converter)
        window.source_edit.setText(str(source))
        window.output_edit.setText(str(Path(self.temp.name) / "out"))
        from daw2bms.track_selection import inspect_tracks
        window.set_track_preview(inspect_tracks(source))
        window.start_conversion()
        self.assertTrue(entered.wait(1))
        worker = window.worker
        window.set_language("ja")
        self.assertIs(window.worker, worker)
        self.assertFalse(window.start_button.isEnabled())
        release.set()
        until = time.monotonic() + 4
        while window.is_running() and time.monotonic() < until:
            QTest.qWait(10)
        self.assertFalse(window.is_running())
        self.assertEqual(window.operation_title.text(), catalog("ja")["MIDI preserved"])
