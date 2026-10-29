"""Windows Live export: UI Automation reads controls; PyAutoGUI sends all input.

No coordinates, localized labels, Remote Script, or user preferences are patched.
The supported export form is recognized by its control structure and readable
values. Unknown forms and loss of focus stop the job instead of sending keys.
"""
from __future__ import annotations

import math
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .als import AlsError
from .flp import FlpError
from .i18n import Message, msg
from .keysounds import sha256_file, write_json


def find_ableton(explicit=None):
    configured = explicit or os.environ.get("DAW2BMS_ABLETON_EXE")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".exe":
            raise AlsError(msg("Ableton executable not found: {p0}", p0=path))
        return path
    base = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Ableton"
    candidates = list(base.glob("Live */Program/Ableton Live *.exe"))
    return max(candidates, key=lambda p: p.stat().st_mtime).resolve() if candidates else None


class AbletonUIError(AlsError):
    """An unknown UI state requires stopping all further desktop input."""


def _pack_message(value):
    if isinstance(value, Exception):
        value = value.args[0] if len(value.args) == 1 else str(value)
    if isinstance(value, Message):
        return {"source": value.source, "params": {k: _pack_message(v) for k, v in value.params.items()}}
    return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)


def _unpack_message(value):
    if isinstance(value, dict) and isinstance(value.get("source"), str) and isinstance(value.get("params"), dict):
        return msg(value["source"], **{k: _unpack_message(v) for k, v in value["params"].items()})
    return value


class NativeExporter:
    """Own UIA's COM objects in a short-lived process, never in a Qt worker.

    Cancellation terminates only our input helper. It does not kill Live or
    discard the Set; an already running native audio export can finish there.
    """
    def __init__(self, executable, *, timeout=600, progress=print):
        self.executable, self.timeout, self.progress = Path(executable), timeout, progress

    def render(self, project, wav, *, bars, bpm):
        command = [sys.executable, "-m", "daw2bms.ableton_ui", str(project.resolve()), str(wav.resolve()),
                   "--exe", str(self.executable), "--bars", str(bars), "--bpm", str(bpm), "--timeout", str(self.timeout)]
        receipt_path = wav.parent / "render_receipt.json"
        if wav.exists() or receipt_path.exists():
            raise AbletonUIError(msg("Choose a fresh Ableton render output and an existing generated project."))
        # Works both from editable source and from an installed distribution.
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent) + os.pathsep + environment.get("PYTHONPATH", "")
        with (wav.parent / "automation.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                deadline, next_update = time.monotonic() + self.timeout * 3 + 90, time.monotonic() + 5
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise AbletonUIError(msg("Ableton export timed out; MIDI is preserved."))
                    if time.monotonic() >= next_update:
                        self.progress(msg("Ableton: waiting for native export."))
                        next_update = time.monotonic() + 5
                    time.sleep(.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
        if process.returncode != 0 or receipt.get("status") != "rendered":
            detail = _unpack_message(receipt.get("error_message", receipt.get("error", "automation.log")))
            raise AbletonUIError(msg("Ableton automation stopped: {p0}. MIDI is preserved.", p0=detail))
        if receipt.get("project_sha256") != sha256_file(project) or receipt.get("wav_sha256") != sha256_file(wav):
            raise AbletonUIError(msg("Ableton rendered an unexpected WAV format or duration; MIDI is preserved."))
        return receipt


class WindowsExporter:
    def __init__(self, executable, *, timeout=600, progress=print):
        if os.name != "nt":
            raise AbletonUIError(msg("Ableton GUI rendering requires Windows."))
        if not math.isfinite(timeout) or timeout <= 0:
            raise AbletonUIError(msg("Render timeout must be positive and finite"))
        try:
            import pyautogui
            import pyperclip
            import win32gui
            import win32process
            import win32api
            import pythoncom
            from pywinauto import Desktop
        except ImportError as exc:
            raise AbletonUIError(msg('Install Ableton rendering dependencies with: python -m pip install -e ".[ableton]"')) from exc
        self.p, self.clipboard = pyautogui, pyperclip
        self.com, self.com_owned = pythoncom, False
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            self.com_owned = True
        except pythoncom.com_error as exc:
            if exc.hresult != -2147417850:  # RPC_E_CHANGED_MODE: already initialized STA.
                raise
        self.win, self.process, self.api = win32gui, win32process, win32api
        self.desktop = Desktop(backend="uia")
        self.executable = Path(executable).resolve()
        self.timeout, self.progress = timeout, progress
        self.p.FAILSAFE = True
        self.handle = None

    def close(self):
        if self.com_owned:
            self.com.CoUninitialize()
            self.com_owned = False

    def _owned(self, handle):
        try:
            _, pid = self.process.GetWindowThreadProcessId(handle)
            proc = self.api.OpenProcess(0x410, False, pid)
            try:
                import win32process
                path = win32process.GetModuleFileNameEx(proc, 0)
                return Path(path).resolve() == self.executable
            finally:
                proc.Close()
        except Exception:
            return False

    def _foreground(self):
        handle = self.win.GetForegroundWindow()
        # During a native window handoff Windows can briefly report no HWND.
        # Wait for that transition, but never wait through another app taking focus.
        deadline = time.monotonic() + 1
        while not handle and time.monotonic() < deadline:
            self.p.failSafeCheck()
            time.sleep(.05)
            handle = self.win.GetForegroundWindow()
        if not self._owned(handle):
            raise AbletonUIError(msg("Ableton lost foreground focus; desktop automation stopped. MIDI is preserved."))
        return self.desktop.window(handle=handle).wrapper_object()

    def _guard(self):
        w = self._foreground()
        if self.handle is not None and w.handle != self.handle:
            raise AbletonUIError(msg("Unexpected Ableton dialog: {p0}. MIDI is preserved.", p0=w.window_text()))
        return w

    def _click(self, control, double=False):
        self._guard()
        control = self._fresh(control)
        if not control.is_enabled() or not control.is_visible():
            raise AbletonUIError(msg("Ableton export control is unavailable: {p0}", p0=control.window_text()))
        rect = control.rectangle()
        if rect.width() <= 0 or rect.height() <= 0:
            raise AbletonUIError(msg("Unrecognized Ableton export dialog; MIDI is preserved."))
        self.p.click(rect.mid_point().x, rect.mid_point().y, clicks=2 if double else 1, interval=0.08)

    def _keys(self, *keys):
        self._guard()
        self.p.hotkey(*keys)

    def _fresh(self, control):
        if not hasattr(control, "_daw_ref"):
            control._daw_ref = (control.element_info.control_type, control.window_text())
        kind, name = control._daw_ref
        matches = [c for c in self._foreground().descendants(control_type=kind) if c.window_text() == name]
        if len(matches) != 1:
            raise AbletonUIError(msg("Unrecognized Ableton export dialog; MIDI is preserved."))
        return matches[0]

    def _value(self, control):
        return str(self._fresh(control).iface_value.CurrentValue)

    def _number(self, control, value):
        if self._value(control) == str(value):
            return
        label = control._daw_ref[1]
        self._click(control, double=True)
        self._keys("ctrl", "a")
        self._guard()
        self.p.write(str(value), interval=0.03)
        self._keys("enter")
        deadline = time.monotonic() + 2
        while self._value(control) != str(value):
            if time.monotonic() >= deadline:
                raise AbletonUIError(msg("Ableton export value could not be verified: {p0}", p0=label))
            time.sleep(.1)

    def _toggle(self, control, enabled):
        # UIA Value is localized; both states are explicitly recognized.
        states = {"on": True, "off": False, "开": True, "关": False,
                  "開": True, "關": False, "オン": True, "オフ": False,
                  "켜기": True, "끄기": False, "켬": True, "끔": False}
        before = states.get(self._value(control).lower())
        if before is None:
            raise AbletonUIError(msg("Ableton export value could not be verified: {p0}", p0=control.window_text()))
        if before != enabled:
            self._click(control)
        if states.get(self._value(control).lower()) != enabled:
            raise AbletonUIError(msg("Ableton export value could not be verified: {p0}", p0=control.window_text()))

    def _combo(self, control, target):
        targets = (target,) if isinstance(target, str) else target
        if self._value(control) in targets:
            return
        self._click(control)
        items = [c for c in self._guard().descendants(control_type="MenuItem")
                 if c.window_text().split(",")[0] in targets]
        if len(items) != 1:
            self._keys("esc")
            raise AbletonUIError(msg("Ableton export value could not be verified: {p0}", p0=control.window_text()))
        self._click(items[0])
        if self._value(control) not in targets:
            raise AbletonUIError(msg("Ableton export value could not be verified: {p0}", p0=control.window_text()))

    def _wait(self, predicate, timeout=None):
        deadline = time.monotonic() + (timeout or self.timeout)
        next_update = time.monotonic() + 5
        while time.monotonic() < deadline:
            if time.monotonic() >= next_update:
                self.progress(msg("Ableton: waiting for native export."))
                next_update = time.monotonic() + 5
            self.p.failSafeCheck()
            result = predicate()
            if result:
                return result
            time.sleep(0.2)
        raise AbletonUIError(msg("Ableton export timed out; MIDI is preserved."))

    def _main(self, stem=None):
        windows = [w for w in self.p.getAllWindows() if " - Ableton Live " in w.title and self._owned(w._hWnd)]
        if stem:
            windows = [w for w in windows if w.title.split(" - Ableton Live ")[0].rstrip(" *") == stem]
        return windows[0] if len(windows) == 1 else None

    def _activate_main(self, window):
        if window.isMinimized:
            window.restore()
        try:
            window.activate()
        except Exception:
            # SetForegroundWindow may return zero for an already foreground
            # window. Trust the observed handle, not its stale Win32 error code.
            if self.win.GetForegroundWindow() != window._hWnd:
                if not self._owned(window._hWnd):
                    raise
                # Windows releases its foreground lock after an ALT input.
                # Target the already verified Live window; never cycle apps.
                self.p.press("alt")
                window.activate()

    def _reject_message_dialog(self):
        """Report a blocking native error promptly, without dismissing it."""
        w = self._foreground()
        if " - Ableton Live " in w.window_text():
            return
        buttons = [c for c in w.descendants(control_type="Button") if c.is_enabled()]
        texts = [c.window_text() for c in w.descendants(control_type="Text") if c.window_text()]
        if buttons and texts and not w.descendants(control_type="Edit"):
            raise AbletonUIError(msg("Unexpected Ableton dialog: {p0}. MIDI is preserved.", p0=" | ".join(texts)[:2000]))

    def _file_dialog_path(self, path):
        self.handle = None
        def file_dialog():
            w = self._foreground()
            if self.win.GetClassName(w.handle) != "#32770":
                return None
            filename = [e for e in w.descendants(control_type="Edit") if e.element_info.automation_id in ("1001", "1148")]
            return (w, filename[0]) if len(filename) == 1 else None
        dialog, edit = self._wait(file_dialog, 15)
        self.handle = dialog.handle
        self._click(edit)
        previous = self.clipboard.paste()
        try:
            self.clipboard.copy(str(path))
            self._keys("ctrl", "a"); self._keys("ctrl", "v")
            if self._value(edit) != str(path):
                raise AbletonUIError(msg("Ableton export value could not be verified: {p0}", p0=edit.window_text()))
            self._keys("enter")
        finally:
            if self.clipboard.paste() == str(path):
                self.clipboard.copy(previous)
        self.handle = None

    def render(self, project: Path, wav: Path, *, bars: int, bpm: float):
        project, wav = project.resolve(), wav.resolve()
        if not project.is_file() or wav.exists() or bars < 1:
            raise AbletonUIError(msg("Choose a fresh Ableton render output and an existing generated project."))
        receipt_path = wav.parent / "render_receipt.json"
        receipt = {"status": "started", "backend": "pyautogui-uia", "project_sha256": sha256_file(project),
                   "project": str(project), "wav": str(wav), "bars": bars, "bpm": bpm}
        write_json(receipt_path, receipt)
        try:
            from .als import read_xml
            from .als_plugins import plugin_requirements, verify_inventory, log_paths, verify_live_log, read_live_load_log
            from .als_max import max_requirements, verify_files, wait_for_max, check_max_log
            root, _, _ = read_xml(project)
            requirements = verify_inventory(plugin_requirements(root))
            max_devices = max_requirements(root)
            max_clips = []
            if max_devices:
                manifest = json.loads((project.parent / "manifest.json").read_text(encoding="utf-8"))
                if manifest.get("max_devices") != max_devices:
                    raise AbletonUIError(msg("Max for Live file changed or disappeared: {p0}; MIDI is preserved.", p0=project))
                max_clips = [k["id"] for k in manifest["keys"]]
            main = self._main()
            if main is None:
                subprocess.Popen([str(self.executable)], cwd=str(project.parent))
                main = self._wait(self._main)
            if main:
                self._activate_main(main)
                time.sleep(0.3)
                self.handle = main._hWnd
                self._guard()  # A modal save/plugin dialog must not be bypassed.
                if main.title.split(" - Ableton Live ")[0].endswith("*"):
                    raise AbletonUIError(msg("Save your current Ableton Set before starting automated rendering."))
            log_offsets = {str(p): p.stat().st_size for p in log_paths()} if requirements or max_devices else {}
            self._keys("ctrl", "o")
            self._file_dialog_path(project)
            def loaded():
                self._reject_message_dialog()
                w = self._main(project.stem)
                if w:
                    # Recognize the uniquely named job Set, then reject any modal.
                    self._activate_main(w)
                    self.handle = w._hWnd
                    self._guard()
                    return w
                return None
            main = self._wait(loaded)
            if max_devices:
                def checkpoint():
                    self._guard()
                    self.p.failSafeCheck()
                receipt["max_load"] = wait_for_max(max_devices, max_clips, timeout=self.timeout, checkpoint=checkpoint)
                check_max_log(read_live_load_log(project, log_offsets), project)
                write_json(receipt_path, receipt)
            if requirements:
                receipt["plugin_load"] = verify_live_log(project, requirements, log_offsets)
                write_json(receipt_path, receipt)
            self._keys("ctrl", "shift", "r")
            self.handle = None
            def export_dialog():
                w = self._foreground()
                sliders = w.descendants(control_type="Slider")
                combos = w.descendants(control_type="ComboBox")
                if len(sliders) == 6 and len(combos) == 6:
                    return w
                return None
            dialog = self._wait(export_dialog, 15)
            self.handle = dialog.handle
            sliders = dialog.descendants(control_type="Slider")
            combos = dialog.descendants(control_type="ComboBox")
            buttons = []
            for c in dialog.descendants(control_type="Button"):
                try:
                    self._value(c)
                    buttons.append(c)
                except Exception:
                    pass
            if len(buttons) != 8:
                raise AbletonUIError(msg("Unrecognized Ableton export dialog; MIDI is preserved."))
            self._combo(combos[0], ("Main", "Master"))
            for c, val in zip(sliders, (1, 1, 1, bars, 0, 0)):
                self._number(c, val)
            # Main already includes returns/master effects (first toggle disabled).
            for c, state in zip(buttons[1:], (False, False, False, False, True, False, False)):
                self._toggle(c, state)
            self._combo(combos[1], "44100")
            self._combo(combos[2], "WAV")
            self._combo(combos[3], "24")
            self._combo(combos[4], ("None", "No Dither", "无", "無", "なし", "없음"))
            actions = [c for c in dialog.descendants(control_type="Button") if c.is_enabled() and c.rectangle().top > max(x.rectangle().bottom for x in combos)]
            if len(actions) != 2:
                raise AbletonUIError(msg("Unrecognized Ableton export dialog; MIDI is preserved."))
            self._click(actions[0])
            self._file_dialog_path(wav)
            last, changed = None, time.monotonic()
            def finished():
                nonlocal last, changed
                self._foreground()
                if not wav.is_file():
                    return False
                stat = wav.stat()
                current = (stat.st_size, stat.st_mtime_ns)
                if current != last:
                    last, changed = current, time.monotonic()
                    return False
                if time.monotonic() - changed < 1:
                    return False
                # Native completion AND a fully readable newly created file.
                if self.win.GetForegroundWindow() != main._hWnd:
                    return False
                from .audio import audio_modules
                np, sf = audio_modules()
                expected = round(bars * 4 * 60 / bpm * 44100)
                with sf.SoundFile(wav) as audio:
                    if audio.samplerate != 44100 or audio.channels != 2 or audio.subtype != "PCM_24" or abs(audio.frames - expected) > 2:
                        raise AbletonUIError(msg("Ableton rendered an unexpected WAV format or duration; MIDI is preserved."))
                    for block in audio.blocks(blocksize=65536):
                        if not np.isfinite(block).all():
                            raise AbletonUIError(msg("Ableton rendered an unexpected WAV format or duration; MIDI is preserved."))
                    return {"frames": audio.frames, "samplerate": audio.samplerate, "channels": audio.channels}
            info = self._wait(finished)
            if max_devices:
                verify_files(max_devices)
                check_max_log(read_live_load_log(project, log_offsets), project)
            receipt.update(status="rendered", wav_sha256=sha256_file(wav), **info)
            write_json(receipt_path, receipt)
            return receipt
        except Exception as exc:
            receipt.update(status="failed", error=str(exc), error_message=_pack_message(exc))
            write_json(receipt_path, receipt)
            if isinstance(exc, FlpError):
                raise
            raise AbletonUIError(msg("Ableton automation stopped: {p0}. MIDI is preserved.", p0=exc)) from exc


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--bars", type=int, required=True)
    parser.add_argument("--bpm", type=float, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    exporter = None
    try:
        exporter = WindowsExporter(args.exe, timeout=args.timeout)
        exporter.render(args.project, args.wav, bars=args.bars, bpm=args.bpm)
        return 0
    except (FlpError, OSError) as exc:
        receipt_path = args.wav.parent / "render_receipt.json"
        if not receipt_path.exists():
            write_json(receipt_path, {"status": "failed", "error": str(exc), "error_message": _pack_message(exc)})
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if exporter is not None:
            exporter.close()


if __name__ == "__main__":
    raise SystemExit(main())
