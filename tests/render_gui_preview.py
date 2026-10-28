"""Render our own widgets offscreen; no desktop/computer-use automation.

python tests/render_gui_preview.py --out output/gui-preview [--report path/conversion.json]
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from daw2bms.gui import MainWindow, configure_application


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--lang", choices=("zh-TW", "en", "ja", "ko"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    configure_application(app)
    with tempfile.TemporaryDirectory() as temporary:
        settings = QSettings(str(Path(temporary) / "preview.ini"), QSettings.Format.IniFormat)
        window = MainWindow(settings=settings, language=args.lang)
        window.show()
        app.processEvents()
        window.grab().save(str(args.out / "desktop.png"))
        window.resize(1000, 720)
        window.advanced_toggle.setChecked(True)
        app.processEvents()
        window.grab().save(str(args.out / "compact-advanced.png"))
        if args.report:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            if report.get("daw") == "ableton_live":
                window.active_format = ".als"
            window.resize(1240, 820)
            window.advanced_toggle.setChecked(False)
            window.run_directory = args.report.resolve().parent
            for message in report.get("warnings", []):
                window.on_message(message)
            window.record_outcome("success", report)
            window.on_finished()
            window.tabs.setCurrentIndex(1)
            app.processEvents()
            window.grab().save(str(args.out / "result.png"))
        window.close()


if __name__ == "__main__":
    main()
