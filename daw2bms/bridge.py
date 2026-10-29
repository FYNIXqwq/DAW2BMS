"""Versioned JSON-lines process interface for desktop hosts such as BMSE.

The first stdin line is a request. During conversion, a subsequent
{"action":"cancel"} line requests cooperative cancellation. Stdout is only
protocol events; human progress messages retain their presentation language.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import threading

from . import __version__
from .flp import FlpError
from .i18n import configure_console, language_context, msg, render, resolve_language
from .keysounds import write_json
from .pipeline import convert
from .track_selection import inspect_tracks

PROTOCOL = 1


class BridgeCancelled(FlpError):
    pass


def monitor_control(cancelled, finished):
    """Do not hold a Windows CRT stdin lock while waiting for cancellation.

    NumPy's extension initialization can inspect standard streams. A blocking
    read on another thread deadlocks that initialization on Windows Python 3.10.
    Peek/select first, then read only bytes already available on the pipe.
    """
    fd = sys.stdin.fileno()
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        import msvcrt
        peek = ctypes.WinDLL('kernel32', use_last_error=True).PeekNamedPipe
        peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        peek.restype = wintypes.BOOL
        pipe = msvcrt.get_osfhandle(fd)
        def available():
            count = wintypes.DWORD()
            if not peek(pipe,None,0,None,ctypes.byref(count),None): return -1
            return count.value
    else:
        import select
        def available():
            return 4096 if select.select([fd],[],[],0)[0] else 0
    pending = bytearray()
    try:
        while not finished.is_set():
            count = available()
            if count < 0: cancelled.set(); return
            if not count:
                finished.wait(.05); continue
            chunk = os.read(fd,min(count,4096))
            if not chunk: cancelled.set(); return
            pending.extend(chunk)
            if len(pending)>4096: cancelled.set(); return
            while b'\n' in pending:
                raw,_,rest = pending.partition(b'\n');pending=bytearray(rest)
                try: command=json.loads(raw)
                except (ValueError,UnicodeError): continue
                if isinstance(command,dict) and command.get('action')=='cancel':
                    cancelled.set(); return
    except OSError:
        cancelled.set()


def options_from_json(value):
    if not isinstance(value, dict):
        raise ValueError('options must be an object')
    allowed = {'fl_exe', 'ableton_exe', 'ableton_render', 'initial_tail', 'max_tail', 'max_attempts',
               'threshold_db', 'timeout', 'channels', 'midi_only', 'resource_dirs', 'deduplicate',
               'arrangement_id', 'title', 'artist', 'lead_in_bars', 'play_channels', 'play_tracks',
               'exclude_tracks', 'source_sha256', 'encoding'}
    if set(value) - allowed:
        raise ValueError('Unknown conversion option')
    result = dict(value)
    for name in ('fl_exe', 'ableton_exe'):
        if name in result:
            if not isinstance(result[name], str): raise ValueError(name + ' must be a path')
            result[name] = Path(result[name]) if result[name] else None
    for name in ('channels', 'midi_only', 'play_channels', 'play_tracks', 'exclude_tracks'):
        if name in result:
            ids = result[name]
            if not isinstance(ids, list) or len(ids) > 10000 or any(type(i) is not int or i < 0 for i in ids):
                raise ValueError(name + ' must be an array of nonnegative IDs')
            result[name] = set(ids)
    if 'resource_dirs' in result:
        dirs = result['resource_dirs']
        if not isinstance(dirs, list) or len(dirs) > 100 or any(not isinstance(p,str) for p in dirs):
            raise ValueError('resource_dirs must be an array of paths')
        result['resource_dirs'] = tuple(Path(p) for p in dirs)
    for name in ('ableton_render', 'deduplicate'):
        if name in result and type(result[name]) is not bool: raise ValueError(name + ' must be boolean')
    for name in ('max_attempts', 'lead_in_bars', 'arrangement_id'):
        if name in result and type(result[name]) is not int: raise ValueError(name + ' must be an integer')
    for name in ('initial_tail', 'max_tail', 'threshold_db', 'timeout'):
        if name in result and type(result[name]) not in (int, float): raise ValueError(name + ' must be numeric')
    for name in ('title', 'artist', 'encoding'):
        if name in result and not isinstance(result[name],str): raise ValueError(name + ' must be text')
    if not re.fullmatch('[0-9a-f]{64}', str(result.get('source_sha256', ''))):
        raise ValueError('Read tracks first; source_sha256 is required')
    return result


def handle(request, emit, cancelled=None):
    cancelled = cancelled or threading.Event()
    if not isinstance(request, dict) or request.get('protocol') != PROTOCOL:
        raise ValueError('Unsupported DAW2BMS bridge protocol')
    action = request.get('action')
    source = request.get('source')
    if not isinstance(source, str) or not source or Path(source).suffix.lower() not in ('.flp','.als'):
        raise ValueError('An FLP or ALS source path is required')
    source = Path(source).expanduser().resolve()
    language = resolve_language(request.get('language'))
    with language_context(language):
        emit({'type':'hello','protocol':PROTOCOL,'version':__version__,'language':language})
        if action == 'inspect':
            emit({'type':'tracks','data':inspect_tracks(source)})
            return 0
        if action != 'convert': raise ValueError('Unknown bridge action')
        output = request.get('out')
        if not isinstance(output,str) or not output: raise ValueError('A new output directory is required')
        destination = Path(output).expanduser().resolve()
        options = options_from_json(request.get('options'))
        def progress(message):
            if cancelled.is_set():
                raise BridgeCancelled(msg('Conversion stopped by user after the current operation; existing output retained'))
            canonical = str(message)
            stage = re.match(r'\[([123])/3\]',canonical)
            emit({'type':'progress','message':render(message),'canonical':canonical,
                  'level':'warning' if canonical.startswith('WARNING:') else 'info',
                  'stage':int(stage[1]) if stage else None})
        try:
            progress(msg('Preparing conversion task'))
            result = convert(source,destination,progress=progress,**options)
            # Do not publish a chart as the completed job after cancellation.
            if cancelled.is_set():
                raise BridgeCancelled(msg('Conversion stopped by user after the current operation; existing output retained'))
            emit({'type':'result','data':result})
            return 0
        except BridgeCancelled as exc:
            report_path = destination/'conversion.json'
            report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {
                'output_directory':str(destination),'chart':None,'midi':None,'fallback_midi':None}
            report.update(status='cancelled',audio_complete=False)
            if destination.is_dir(): write_json(report_path,report)
            emit({'type':'cancelled','message':render(exc),'data':report})
            return 0


def main():
    configure_console()
    cancelled = threading.Event()
    finished = threading.Event()
    listener = None
    def emit(event):
        print(json.dumps(event,ensure_ascii=False,allow_nan=False),flush=True)
    try:
        # Unbuffered first-line read cannot consume a following cancel command.
        line = sys.stdin.buffer.raw.readline(1024*1024+1)
        if len(line)>1024*1024: raise ValueError('Bridge request exceeds 1 MiB')
        request = json.loads(line)
        if isinstance(request,dict) and request.get('action')=='convert':
            listener = threading.Thread(target=monitor_control,args=(cancelled,finished),daemon=True)
            listener.start()
        code = handle(request,emit,cancelled)
        finished.set()
        if listener is not None: listener.join(timeout=2)
        return code
    except Exception as exc:
        with language_context(resolve_language(request.get('language') if isinstance(locals().get('request'),dict) else None)):
            emit({'type':'error','message':render(exc)})
        finished.set()
        if listener is not None: listener.join(timeout=2)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
