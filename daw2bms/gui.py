"""PyQt6 desktop frontend; the conversion engine remains UI-independent."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
from collections import deque
from .i18n import (LANGUAGES, Message, msg, render, tr, resolve_language, normalize_language, system_language,
                   language_context, split_language_args, argparse_translations, configure_console)

try:
    from PyQt6.QtCore import Qt, QSettings, QThread, QTimer, QUrl, QTranslator, QLibraryInfo, pyqtSignal
    from PyQt6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QKeySequence, QPalette, QShortcut
    from PyQt6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout,
        QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar,
        QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTabWidget, QToolButton, QComboBox,
        QVBoxLayout, QWidget)
except ImportError as exc:
    try:
        requested = split_language_args(sys.argv[1:])[0]
    except ValueError:
        requested = resolve_language()
    raise SystemExit(tr('GUI dependencies missing. Install with: python -m pip install -e ".[gui]"', requested)) from exc

from . import __version__
from .flp import FlpError
from .keysounds import write_json
from .pipeline import convert


STYLE = """
QMainWindow, QWidget { background: #17191d; color: #edf0f5; }
QLabel { background: transparent; }
QLabel#productTitle { font-size: 24px; font-weight: 600; }
QLabel#sectionTitle { font-size: 18px; font-weight: 600; }
QLabel#operationTitle { font-size: 21px; font-weight: 600; }
QLabel[role="secondary"] { color: #b7bfcc; }
QLabel[role="hint"] { color: #a0abba; font-size: 12px; }
QFrame#settingsPane, QFrame#monitorPane { background: #202329; border: 1px solid #3d444f; border-radius: 10px; }
QWidget#formContent, QWidget#advancedContent { background: #202329; }
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QComboBox {
    background: #171a20; border: 1px solid #3d444f; border-radius: 6px;
    padding: 8px; color: #edf0f5; selection-background-color: #354965;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus { border: 1px solid #9ab8fa; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QPushButton:disabled { color: #8795a8; background: #292d35; }
QPushButton, QToolButton {
    background: #2b3039; color: #edf0f5; border: 1px solid #48515f;
    border-radius: 6px; padding: 8px 12px; min-height: 20px;
}
QPushButton:hover, QToolButton:hover { background: #363e4b; border-color: #7d90ac; }
QPushButton:focus, QToolButton:focus { border: 2px solid #9ab8fa; }
QPushButton#startButton { background: #9ab8fa; color: #172035; border-color: #9ab8fa; font-weight: 600; min-height: 30px; }
QPushButton#startButton:hover { background: #b8cdfa; }
QPushButton#startButton:disabled { background: #374154; color: #aab6cc; border-color: #48566d; }
QToolButton#advancedToggle { border: none; text-align: left; padding-left: 0; background: transparent; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox:focus { color: #9ab8fa; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: #202329; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #626d7e; min-height: 28px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #17191d; width: 12px; }
QProgressBar { background: #2b3039; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #9ab8fa; border-radius: 3px; }
QLabel[stage="idle"] { color: #a0abba; padding: 10px 8px; background: #2a2e36; border-radius: 5px; }
QLabel[stage="active"] { color: #d4e2ff; padding: 10px 8px; background: #2e3e59; border-radius: 5px; }
QLabel[stage="done"] { color: #d4e2ff; padding: 10px 8px; background: #29374e; border-radius: 5px; }
QLabel[stage="error"] { color: #ffadad; padding: 10px 8px; background: #482e36; border-radius: 5px; }
QLabel[tone="normal"] { color: #b7bfcc; }
QLabel[tone="warning"] { color: #ffd18a; }
QLabel[tone="error"] { color: #ffadad; }
QLabel[tone="success"] { color: #d4e2ff; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #b7bfcc; padding: 10px 14px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #edf0f5; border-bottom: 2px solid #9ab8fa; }
QTabBar::tab:hover { color: #9ab8fa; }
QPlainTextEdit#warningLog { color: #ffd18a; }
QToolTip { color: #edf0f5; background: #2b3039; border: 1px solid #52647d; padding: 6px; }
"""


def label(text="", name=None, role=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    if role:
        widget.setProperty("role", role)
    return widget


def property_value(widget, name, value):
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def next_output(source: Path, parent: Path) -> Path:
    base = parent / (source.stem + "-bms")
    candidate, suffix = base, 2
    while candidate.exists():
        candidate = base.with_name(base.name + f"-{suffix}")
        suffix += 1
    return candidate.resolve()


class Cancelled(FlpError):
    pass


class ConversionWorker(QThread):
    message = pyqtSignal(object)
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(self, source, destination, options, converter=convert, parent=None, language="en"):
        super().__init__(parent)
        self.source, self.destination, self.options, self.converter = source, destination, options, converter
        self.language = language

    def progress(self, message):
        if self.isInterruptionRequested():
            raise Cancelled(msg('Conversion stopped by user after the current operation; existing output retained'))
        self.message.emit(message)

    def run(self):
        try:
            self.progress(msg('Preparing conversion task'))
            with language_context(self.language):
                result = self.converter(self.source, self.destination, progress=self.progress, **self.options)
            self.succeeded.emit(result)
        except Cancelled:
            report_path = self.destination / "conversion.json"
            if report_path.is_file():
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    report["status"] = "cancelled"
                    write_json(report_path, report)
                except (OSError, ValueError):
                    self.message.emit(msg('WARNING: Could not save the stopped status. Existing files were kept.'))
            self.cancelled.emit()
        except (FlpError, OSError) as exc:
            self.failed.emit(exc)
        except Exception as exc:
            self.message.emit(traceback.format_exc())
            self.failed.emit(msg('Unexpected error: {p0}', p0=exc))


class ProjectDropArea(QFrame):
    projectDropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).suffix.lower() in (".flp", ".als"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).suffix.lower() in (".flp", ".als"):
            self.projectDropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self, *, converter=convert, settings=None, language=None):
        super().__init__()
        self.converter = converter
        self.settings = settings if settings is not None else QSettings("DAW2BMS", "Desktop")
        saved = self.settings.value("language", "", type=str)
        self.language_setting = language or os.environ.get("DAW2BMS_LANG") or saved or "system"
        self.language = system_language() if self.language_setting == "system" else normalize_language(self.language_setting)
        self._bindings = {}
        self._log_messages = deque(maxlen=2000)
        self._warning_messages = deque(maxlen=2000)
        self.qt_translator = None
        self.worker = None
        self.pending_outcome = None
        self.result = None
        self.run_directory = None
        self.warning_count = 0
        self.current_stage = -1
        self.active_format = None
        self.started_at = None
        self._bind(self, 'setWindowTitle', 'DAW2BMS · Project to chart')
        self.setMinimumSize(960, 700)
        self.resize(1240, 820)
        self.setStyleSheet(STYLE)
        self._build()
        self.source_edit.textChanged.connect(self.update_source_type)
        self.update_source_type()
        self.set_language(self.language_setting, persist=False)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self.update_elapsed)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.browse_source)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.start_conversion)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

    def t(self, source, **params):
        return tr(source, self.language, **params)

    def _bind(self, widget, method, value):
        value = msg(value) if isinstance(value, str) and not isinstance(value, Message) else value
        self._bindings[widget, method] = value
        getattr(widget, method)(render(value, self.language))

    def _label(self, text, name=None, role=None):
        widget = label("", name, role)
        self._bind(widget, "setText", text)
        return widget

    def _button(self, text):
        widget = QPushButton()
        self._bind(widget, "setText", text)
        return widget

    def _checkbox(self, text):
        widget = QCheckBox()
        self._bind(widget, "setText", text)
        return widget

    def _add_row(self, layout, text, field):
        caption = self._label(text)
        caption.setBuddy(field)
        layout.addRow(caption, field)

    def _refresh_tabs(self):
        self.tabs.setTabText(0, self.t("Log"))
        self.tabs.setTabText(1, self.t("Warnings · {p0}", p0=self.warning_count))

    def set_language(self, language, persist=True):
        self.language_setting = language or "system"
        if self.language_setting != "system":
            self.language_setting = normalize_language(self.language_setting)
        self.language = system_language() if self.language_setting == "system" else normalize_language(self.language_setting)
        if persist:
            self.settings.setValue("language", self.language_setting)
            self.settings.sync()
        app = QApplication.instance()
        if self.qt_translator is not None:
            app.removeTranslator(self.qt_translator)
            self.qt_translator.deleteLater()
        self.qt_translator = QTranslator(self)
        if self.language != "en" and self.qt_translator.load("qtbase_" + self.language.replace("-", "_"),
                QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(self.qt_translator)
        families = {"en": "Segoe UI", "zh-TW": "Microsoft JhengHei UI", "ja": "Yu Gothic UI", "ko": "Malgun Gothic"}
        self.setFont(QFont(families[self.language], 10))
        for (widget, method), value in self._bindings.items():
            getattr(widget, method)(render(value, self.language))
        self.language_combo.blockSignals(True)
        self.language_combo.setItemText(0, self.t("System default"))
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language_setting))
        self.language_combo.blockSignals(False)
        self._refresh_tabs()
        for widget, messages in ((self.log, self._log_messages), (self.warning_log, self._warning_messages)):
            old = widget.verticalScrollBar().value()
            following = old >= widget.verticalScrollBar().maximum() - 4
            widget.setPlainText("\n".join(render(message, self.language) for message in messages))
            widget.verticalScrollBar().setValue(widget.verticalScrollBar().maximum() if following else old)

    def _path_row(self, field, callback, text='Browse…'):
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        button = self._button(text)
        button.clicked.connect(callback)
        layout.addWidget(field, 1)
        layout.addWidget(button)
        return widget

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(18)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(self._label('DAW2BMS', 'productTitle'))
        subtitle = self._label('FL Studio to BMS · Ableton Arrangement to MIDI', role='secondary')
        subtitle.setWordWrap(False)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch()
        self.language_combo = QComboBox()
        self.language_combo.addItem(self.t("System default"), "system")
        for code, title in LANGUAGES.items():
            self.language_combo.addItem(title, code)
        self._bind(self.language_combo, "setAccessibleName", "Language")
        self.language_combo.currentIndexChanged.connect(lambda: self.set_language(self.language_combo.currentData()))
        header.addWidget(self.language_combo)
        version = self._label(msg('PyQt6 desktop  ·  v{p0}', p0=__version__), role='hint')
        version.setWordWrap(False)
        header.addWidget(version)
        outer.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)
        left = QFrame()
        left.setObjectName("settingsPane")
        left.setMinimumWidth(350)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(14)
        left_layout.addWidget(self._label('Convert project', 'sectionTitle'))
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form_content = ProjectDropArea()
        self.form_content.setObjectName("formContent")
        self.form_content.projectDropped.connect(self.set_source)
        form = QVBoxLayout(self.form_content)
        form.setContentsMargins(0, 0, 6, 0)
        form.setSpacing(10)
        self.source_edit = QLineEdit()
        self._bind(self.source_edit, 'setPlaceholderText', 'Choose or drop an .flp or .als project')
        self._bind(self.source_edit, 'setAccessibleName', 'FLP / ALS project file')
        self.source_edit.setText(self.settings.value("last_source", "", type=str))
        source_label = self._label('FLP / ALS project file')
        source_label.setBuddy(self.source_edit)
        form.addWidget(source_label)
        form.addWidget(self._path_row(self.source_edit, self.browse_source))
        self.format_hint = self._label('Drop one FLP or ALS file here. The source project stays unchanged.', role='hint')
        form.addWidget(self.format_hint)
        form.addSpacing(8)
        self.output_edit = QLineEdit(self.settings.value("output_parent", str(Path.cwd() / "output"), type=str))
        self._bind(self.output_edit, 'setAccessibleName', 'Output parent directory')
        output_label = self._label('Output location')
        output_label.setBuddy(self.output_edit)
        form.addWidget(output_label)
        form.addWidget(self._path_row(self.output_edit, self.browse_output))
        form.addWidget(self._label('Create a folder named after the project. Existing output is never overwritten.', role='hint'))
        form.addSpacing(10)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("advancedToggle")
        self._bind(self.advanced_toggle, 'setText', 'Advanced settings')
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        form.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        self.advanced.setObjectName("advancedContent")
        settings_layout = QFormLayout(self.advanced)
        settings_layout.setContentsMargins(0, 4, 0, 4)
        settings_layout.setSpacing(12)
        settings_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.fl_edit = QLineEdit(self.settings.value("fl_exe", "", type=str))
        self._bind(self.fl_edit, 'setPlaceholderText', 'Leave blank to find FL Studio automatically')
        self._bind(self.fl_edit, 'setAccessibleName', 'FL Studio executable')
        self.fl_row = self._path_row(self.fl_edit, self.browse_fl)
        self._add_row(settings_layout, 'FL Studio', self.fl_row)
        self.title_edit, self.artist_edit = QLineEdit(), QLineEdit()
        self._bind(self.title_edit, 'setPlaceholderText', 'Use the project title or filename')
        self._bind(self.artist_edit, 'setPlaceholderText', 'Use the project author')
        self._add_row(settings_layout, 'Chart title', self.title_edit)
        self._add_row(settings_layout, 'Artist', self.artist_edit)
        self.resources_edit = QPlainTextEdit()
        self._bind(self.resources_edit, 'setPlaceholderText', 'Extra resource folders, one per line (optional)')
        self.resources_edit.setMaximumHeight(78)
        self._bind(self.resources_edit, 'setAccessibleName', 'Extra resource folders')
        self.resource_row = self._path_row(self.resources_edit, self.browse_resource, 'Add…')
        self._add_row(settings_layout, 'Resource folders', self.resource_row)
        self.lead_in = QSpinBox()
        self.lead_in.setRange(0, 998)
        self.lead_in.setValue(1)
        self._bind(self.lead_in, 'setSuffix', ' bars')
        self._add_row(settings_layout, 'Lead-in', self.lead_in)
        self.initial_tail = self._double(0.1, 120, 1, ' s')
        self._bind(self.initial_tail, 'setToolTip', 'Initial probe only; release tails adapt to the measured decay.')
        self._add_row(settings_layout, 'Initial tail probe', self.initial_tail)
        self.max_tail = self._double(0.1, 1200, 30, ' s')
        self._add_row(settings_layout, 'Maximum tail probe', self.max_tail)
        self.attempts = QSpinBox()
        self.attempts.setRange(1, 20)
        self.attempts.setValue(5)
        self._add_row(settings_layout, 'Maximum attempts', self.attempts)
        self.threshold = self._double(-120, -20, -60, " dBFS")
        self._add_row(settings_layout, 'Silence threshold', self.threshold)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 7200)
        self.timeout.setValue(600)
        self._bind(self.timeout, 'setSuffix', ' s')
        self._add_row(settings_layout, 'Render timeout', self.timeout)
        self.dedupe = self._checkbox('Reuse identical keysounds')
        self.dedupe.setChecked(True)
        self._bind(self.dedupe, 'setToolTip', 'Reuse notes with identical channel, pitch, velocity, duration and parameters. Disable for random sounds.')
        settings_layout.addRow(self.dedupe)
        form.addWidget(self.advanced)
        self.advanced.hide()
        form.addStretch()
        self.form_scroll.setWidget(self.form_content)
        left_layout.addWidget(self.form_scroll, 1)
        left_layout.addWidget(self._label('Missing instruments keep MIDI and produce warnings. Available instruments continue.', role='hint'))
        self.start_button = self._button('Start conversion')
        self.start_button.setObjectName("startButton")
        self._bind(self.start_button, 'setToolTip', 'Ctrl+Enter')
        self.start_button.clicked.connect(self.start_conversion)
        left_layout.addWidget(self.start_button)
        self.stop_button = self._button('Stop after this step')
        self._bind(self.stop_button, 'setToolTip', 'Stop after the current render finishes; retain existing output.')
        self.stop_button.clicked.connect(self.stop_conversion)
        self.stop_button.setEnabled(False)
        left_layout.addWidget(self.stop_button)
        splitter.addWidget(left)

        right = QFrame()
        right.setObjectName("monitorPane")
        right.setMinimumWidth(470)
        monitor = QVBoxLayout(right)
        monitor.setContentsMargins(22, 20, 22, 20)
        monitor.setSpacing(14)
        heading = QHBoxLayout()
        heading.addWidget(self._label('Conversion progress', 'sectionTitle'))
        heading.addStretch()
        self.elapsed_label = self._label('Ready', role='hint')
        heading.addWidget(self.elapsed_label)
        self.save_log_button = self._button('Save log')
        heading.addWidget(self.save_log_button)
        monitor.addLayout(heading)
        steps = QHBoxLayout()
        steps.setSpacing(8)
        self.stage_labels = []
        for text in ('1  Read project', '2  Render and slice', '3  Export chart'):
            step = self._label(text)
            step.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step.setProperty("stage", "idle")
            steps.addWidget(step, 1)
            self.stage_labels.append(step)
        monitor.addLayout(steps)
        monitor.addSpacing(4)
        self.operation_title = self._label('Choose a project to begin', 'operationTitle')
        self.operation_detail = self._label('Choose a project and start converting. Progress and warnings appear here.', role='secondary')
        self.operation_detail.setMinimumHeight(44)
        monitor.addWidget(self.operation_title)
        monitor.addWidget(self.operation_detail)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        monitor.addWidget(self.progress_bar)
        self.tabs = QTabWidget()
        self.log = QPlainTextEdit()
        self.warning_log = QPlainTextEdit()
        self.warning_log.setObjectName("warningLog")
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed_font.setPointSize(9)
        for widget in (self.log, self.warning_log):
            widget.setReadOnly(True)
            widget.setFont(fixed_font)
            widget.setMaximumBlockCount(4000)
        self._bind(self.log, 'setPlaceholderText', 'Conversion logs will appear here in real time.')
        self._bind(self.warning_log, 'setPlaceholderText', 'No warnings yet. Missing plugins and MIDI fallback information appear here.')
        self.tabs.addTab(self.log, self.t('Log'))
        self.tabs.addTab(self.warning_log, self.t('Warnings · {p0}', p0=0))
        monitor.addWidget(self.tabs, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.folder_button = self._button('Output folder')
        self.chart_button = self._button('Chart folder')
        self.midi_button = self._button('MIDI')
        self.report_button = self._button('Report')
        for button in (self.folder_button, self.chart_button, self.midi_button, self.report_button):
            button.setEnabled(False)
            actions.addWidget(button)
        actions.addStretch()
        self.folder_button.clicked.connect(lambda: self.open_path(self.run_directory))
        self.chart_button.clicked.connect(lambda: self.open_result("chart", directory=True))
        self.midi_button.clicked.connect(lambda: self.open_result("fallback_midi" if self.result and self.result.get("fallback_midi") else "midi"))
        self.report_button.clicked.connect(lambda: self.open_path(self.run_directory / "conversion.json" if self.run_directory else None))
        self.save_log_button.clicked.connect(self.save_log)
        monitor.addLayout(actions)
        splitter.addWidget(right)
        splitter.setSizes([430, 740])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def _double(self, minimum, maximum, value, suffix):
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(1)
        widget.setValue(value)
        self._bind(widget, 'setSuffix', suffix)
        return widget

    def toggle_advanced(self, checked):
        self.advanced.setVisible(checked)
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def set_source(self, path):
        if not self.is_running():
            self.source_edit.setText(path)

    def update_source_type(self):
        als = Path(self.source_edit.text().strip().strip('"')).suffix.lower() == ".als"
        for widget in (self.fl_row, self.resource_row, self.title_edit, self.artist_edit, self.lead_in,
                       self.initial_tail, self.max_tail, self.attempts, self.threshold, self.timeout, self.dedupe):
            widget.setEnabled(not als)
        self._bind(self.format_hint, "setText", "ALS exports Arrangement MIDI and JSON only; Live is not required and audio rendering is disabled."
                   if als else "Drop one FLP or ALS file here. The source project stays unchanged.")
        if self.active_format is None:
            self._bind(self.stage_labels[1], "setText", "2  Export MIDI" if als else "2  Render and slice")

    def browse_source(self):
        if self.is_running():
            return
        path, _ = QFileDialog.getOpenFileName(self, self.t('Choose DAW project'), self.source_edit.text(), self.t('DAW projects (*.flp *.FLP *.als *.ALS)'), options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            self.set_source(path)

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, self.t('Choose output parent directory'), self.output_edit.text(), options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            self.output_edit.setText(path)

    def browse_fl(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t('Choose FL Studio executable'), self.fl_edit.text(), self.t('Executables (*.exe)'), options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            self.fl_edit.setText(path)

    def browse_resource(self):
        path = QFileDialog.getExistingDirectory(self, self.t('Add resource folder'), options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            current = self.resources_edit.toPlainText().strip()
            self.resources_edit.setPlainText(current + "\n" + path if current else path)

    def is_running(self):
        return self.worker is not None

    def collect_request(self):
        source = Path(self.source_edit.text().strip().strip('"')).expanduser()
        if not source.is_file() or source.suffix.lower() not in (".flp", ".als"):
            raise FlpError(msg('Choose an existing .flp or .als project file.'))
        als = source.suffix.lower() == ".als"
        root_text = self.output_edit.text().strip().strip('"')
        if not root_text:
            raise FlpError(msg('Choose an output location.'))
        parent = Path(root_text).expanduser().resolve()
        if parent.exists() and not parent.is_dir():
            raise FlpError(msg('The output location must be a directory.'))
        fl_text = self.fl_edit.text().strip().strip('"')
        fl_exe = Path(fl_text).expanduser().resolve() if fl_text and not als else None
        if fl_exe and (not fl_exe.is_file() or fl_exe.suffix.lower() != ".exe"):
            raise FlpError(msg('Invalid FL Studio path. Choose an .exe file or leave blank for automatic discovery.'))
        if not als and self.max_tail.value() < self.initial_tail.value():
            raise FlpError(msg('The maximum tail probe cannot be shorter than the initial probe.'))
        resources = tuple(Path(line.strip().strip('"')).expanduser().resolve()
                          for line in self.resources_edit.toPlainText().splitlines() if line.strip()) if not als else ()
        if any(not path.is_dir() for path in resources):
            raise FlpError(msg('A resource folder does not exist. Check Advanced settings.'))
        options = {"fl_exe": fl_exe, "title": self.title_edit.text().strip() or None,
                   "artist": self.artist_edit.text().strip() or None, "resource_dirs": resources,
                   "initial_tail": self.initial_tail.value(), "max_tail": self.max_tail.value(),
                   "max_attempts": self.attempts.value(), "threshold_db": self.threshold.value(),
                   "timeout": self.timeout.value(), "lead_in_bars": self.lead_in.value(),
                   "deduplicate": self.dedupe.isChecked()}
        return source.resolve(), next_output(source, parent), options

    def start_conversion(self):
        if self.is_running():
            return
        try:
            source, destination, options = self.collect_request()
        except (FlpError, OSError) as exc:
            self._bind(self.operation_title, 'setText', 'Cannot start conversion')
            self._bind(self.operation_detail, 'setText', exc)
            property_value(self.operation_detail, "tone", "error")
            return
        self.settings.setValue("last_source", str(source))
        self.settings.setValue("output_parent", str(destination.parent))
        self.settings.setValue("fl_exe", self.fl_edit.text().strip())
        self.settings.sync()
        self.run_directory, self.result, self.pending_outcome = destination, None, None
        self.active_format = source.suffix.lower()
        self.log.clear()
        self.warning_log.clear()
        self._log_messages.clear()
        self._warning_messages.clear()
        self.warning_count = 0
        self._refresh_tabs()
        self.tabs.tabBar().setTabTextColor(1, QColor("#b7bfcc"))
        self.started_at = time.monotonic()
        self.update_elapsed()
        self.elapsed_timer.start()
        self.set_stage(0)
        self._bind(self.operation_title, 'setText', 'Preparing')
        self._bind(self.operation_detail, 'setText', msg('Output: {p0}', p0=destination))
        property_value(self.operation_detail, "tone", "normal")
        self.progress_bar.setRange(0, 0)
        self.form_content.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._bind(self.stop_button, 'setText', 'Stop after this step')
        for button in (self.folder_button, self.chart_button, self.midi_button, self.report_button):
            button.setEnabled(False)
        self.worker = ConversionWorker(source, destination, options, self.converter, self, language=self.language)
        self.worker.message.connect(self.on_message)
        self.worker.succeeded.connect(lambda result: self.record_outcome("success", result))
        self.worker.failed.connect(lambda message: self.record_outcome("error", message))
        self.worker.cancelled.connect(lambda: self.record_outcome("cancelled", None))
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def record_outcome(self, kind, payload):
        self.pending_outcome = (kind, payload)

    def set_stage(self, current, error=False):
        self.current_stage = current
        for index, widget in enumerate(self.stage_labels):
            self._bind(widget, 'setText', ('1  Read project', '2  Render and slice', '3  Export chart')[index])
            if index == 1 and self.active_format == ".als":
                self._bind(widget, 'setText', '2  Export MIDI')
            state = "done" if index < current else "active" if index == current else "idle"
            if error and index == current:
                state = "error"
            property_value(widget, "stage", state)

    def append_log(self, widget, text):
        (self._warning_messages if widget is self.warning_log else self._log_messages).append(text)
        bar = widget.verticalScrollBar()
        following = bar.value() >= bar.maximum() - 4
        widget.appendPlainText(render(text, self.language))
        if following:
            bar.setValue(bar.maximum())

    def on_message(self, message):
        self.append_log(self.log, message)
        if message.startswith("WARNING:"):
            self.warning_count += 1
            self.append_log(self.warning_log, message)
            self._refresh_tabs()
            self.tabs.tabBar().setTabTextColor(1, QColor("#ffd18a"))
        if self.worker and self.worker.isInterruptionRequested():
            return
        if message.startswith("[2/3] Exporting ALS Arrangement MIDI"):
            self.set_stage(1)
            self._bind(self.operation_title, "setText", "Exporting Arrangement MIDI")
            self._bind(self.operation_detail, "setText", "ALS notes remain in MIDI/JSON; no instrument rendering is performed.")
            return
        if self.active_format == ".als" and message.startswith("[3/3] BMS export skipped"):
            self.set_stage(2)
            self._bind(self.stage_labels[2], "setText", "3  Chart skipped")
            self._bind(self.operation_title, "setText", "MIDI preserved")
            self._bind(self.operation_detail, "setText", "ALS notes remain in MIDI/JSON; no instrument rendering is performed.")
            return
        for prefix, stage, title, detail in (
            ("[1/3]", 0, 'Reading project', 'Extracting notes, Playlist clips and resource references.'),
            ("[2/3]", 1, 'Rendering and slicing', 'Adapting windows to measured tails. Validated keysounds are retained.'),
            ("[3/3]", 2, 'Exporting chart', 'Mapping keysounds to the original timeline and validating the chart.'),
        ):
            if message.startswith(prefix):
                self.set_stage(stage)
                self._bind(self.operation_title, 'setText', title)
                self._bind(self.operation_detail, 'setText', detail)
        match = re.match(r"Attempt (\d+): (\d+) keys; (\d+) already validated\.", message)
        if match:
            attempt, keys, accepted = match.groups()
            self._bind(self.operation_title, 'setText', msg('Processing attempt {p0}', p0=attempt))
            self._bind(self.operation_detail, 'setText', msg('This attempt: {p0} keys · Validated: {p1}. Tail lengths follow the actual audio.', p0=keys, p1=accepted))

    def stop_conversion(self):
        if self.worker:
            self.worker.requestInterruption()
            self.stop_button.setEnabled(False)
            self._bind(self.stop_button, 'setText', 'Waiting for this step…')
            self._bind(self.operation_title, 'setText', 'Stopping')
            self._bind(self.operation_detail, 'setText', 'Waiting for the current render or slice to finish. Existing files will be kept.')
            property_value(self.operation_detail, "tone", "warning")

    def on_finished(self):
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        self.elapsed_timer.stop()
        self.update_elapsed()
        self.form_content.setEnabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._bind(self.stop_button, 'setText', 'Stop after this step')
        self.progress_bar.setRange(0, 1)
        kind, payload = self.pending_outcome or ("error", 'The task returned no result. Check the log.')
        if kind == "success":
            self.result = payload
            self.progress_bar.setValue(1)
            self.set_stage(3)
            if payload["status"] == "midi_only":
                self._bind(self.operation_title, 'setText', 'MIDI preserved')
                self._bind(self.operation_detail, 'setText', msg('{p0} notes preserved as MIDI. No audio is available, so no empty chart was created.', p0=payload.get('midi_only_notes', 0)))
                property_value(self.operation_detail, "tone", "warning")
                property_value(self.stage_labels[2], "stage", "idle")
                self._bind(self.stage_labels[2], 'setText', '3  Chart skipped')
            else:
                incomplete = not payload.get("audio_complete", True)
                self._bind(self.operation_title, 'setText', 'Chart created · some audio missing' if incomplete else 'Conversion complete')
                self._bind(self.operation_detail, 'setText', msg('{p0} playable notes · {p1} BGM · {p2} MIDI-only notes', p0=payload.get('playable_notes', 0), p1=payload.get('bgm_events', 0), p2=payload.get('midi_only_notes', 0)))
                property_value(self.operation_detail, "tone", "warning" if incomplete else "success")
        else:
            self.progress_bar.setValue(0)
            self._bind(self.operation_title, 'setText', 'Conversion stopped' if kind == 'cancelled' else 'Conversion failed')
            self._bind(self.operation_detail, 'setText', 'Existing output was kept. Open the output folder to inspect it.' if kind == 'cancelled' else payload)
            property_value(self.operation_detail, "tone", "warning" if kind == "cancelled" else "error")
            self.set_stage(max(0, self.current_stage), error=kind == "error")
            if payload:
                self.append_log(self.log, msg("ERROR: {p0}", p0=payload))
            report_path = self.run_directory / "conversion.json" if self.run_directory else None
            if report_path and report_path.is_file():
                try:
                    self.result = json.loads(report_path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    pass
        self.refresh_result_actions()

    def update_elapsed(self):
        if self.started_at is not None:
            seconds = int(time.monotonic() - self.started_at)
            self._bind(self.elapsed_label, 'setText', msg('Elapsed {p0:02d}:{p1:02d}', p0=seconds // 60, p1=seconds % 60))

    def result_path(self, key):
        if not self.result or not self.run_directory or not self.result.get(key):
            return None
        path = (self.run_directory / self.result[key]).resolve()
        if not path.is_relative_to(self.run_directory.resolve()) or not path.is_file():
            return None
        return path

    def refresh_result_actions(self):
        self.folder_button.setEnabled(bool(self.run_directory and self.run_directory.is_dir()))
        self.chart_button.setEnabled(self.result_path("chart") is not None)
        self.midi_button.setEnabled(self.result_path("midi") is not None or self.result_path("fallback_midi") is not None)
        self.report_button.setEnabled(bool(self.run_directory and (self.run_directory / "conversion.json").is_file()))

    def open_result(self, key, directory=False):
        path = self.result_path(key)
        self.open_path(path.parent if path and directory else path)

    def open_path(self, path):
        if path and path.exists() and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            self.append_log(self.log, msg('Cannot open: {p0}', p0=path))

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, self.t('Save conversion log'), str((self.run_directory or Path.cwd()) / 'gui_log.txt'), self.t('Text files (*.txt)'), options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            try:
                Path(path).write_text(self.log.toPlainText(), encoding="utf-8")
            except OSError as exc:
                self.append_log(self.log, msg('Cannot save log: {p0}', p0=exc))

    def closeEvent(self, event):
        if self.is_running():
            self._bind(self.operation_detail, 'setText', 'A task is running. Stop after this step and wait for the render to finish before closing.')
            property_value(self.operation_detail, "tone", "warning")
            event.ignore()
        else:
            event.accept()


def configure_application(app):
    app.setApplicationName("DAW2BMS")
    app.setOrganizationName("DAW2BMS")
    app.setStyle("Fusion")
    # Qt's Windows offscreen backend has no automatic system font discovery.
    # Register installed fonts only when the database is empty (no OS changes).
    if sys.platform == "win32" and not QFontDatabase.families():
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("msjh.ttc", "msjhbd.ttc", "msyh.ttc", "msyhbd.ttc", "consola.ttf", "segoeui.ttf", "YuGothR.ttc", "YuGothM.ttc", "malgun.ttf"):
            path = fonts / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    palette = app.palette()
    for role, color in ((QPalette.ColorRole.Window, "#17191d"), (QPalette.ColorRole.WindowText, "#edf0f5"),
                        (QPalette.ColorRole.Base, "#171a20"), (QPalette.ColorRole.Text, "#edf0f5"),
                        (QPalette.ColorRole.Button, "#2b3039"), (QPalette.ColorRole.ButtonText, "#edf0f5"),
                        (QPalette.ColorRole.Highlight, "#354965"), (QPalette.ColorRole.HighlightedText, "#edf0f5"),
                        (QPalette.ColorRole.PlaceholderText, "#a0abba")):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)


def main(argv=None):
    configure_console()
    try:
        language, cleaned, explicit = split_language_args(list(sys.argv[1:] if argv is None else argv))
    except ValueError as exc:
        print(render(exc, resolve_language()), file=sys.stderr)
        return 2
    with language_context(language), argparse_translations():
        parser = argparse.ArgumentParser(description=tr("DAW2BMS PyQt6 desktop application"))
        parser.add_argument("source", nargs="?", type=Path, help=tr("Optional project to prefill; conversion does not start automatically"))
        parser.add_argument("--lang", choices=list(LANGUAGES), help=tr("Display language: zh-TW, en, ja or ko"))
        args = parser.parse_args(cleaned)
    app = QApplication([sys.argv[0]])
    configure_application(app)
    window = MainWindow(language=explicit)
    if args.source:
        window.set_source(str(args.source.resolve()))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
