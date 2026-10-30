"""Process boundaries shared by source and frozen desktop distributions."""
from contextlib import contextmanager
import os
import sys


def ableton_helper_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--ableton-ui']
    return [sys.executable, '-m', 'daw2bms.ableton_ui']


@contextmanager
def external_daw_environment():
    """Do not let bundled Python DLLs override a DAW's own native libraries.

    Only external DAWs use this boundary; our frozen helper keeps its runtime.
    Restore the loader path even when process creation fails.
    """
    env = os.environ.copy()
    frozen = getattr(sys, 'frozen', False)
    bundle = getattr(sys, '_MEIPASS', '')
    if frozen and bundle:
        base = os.path.normcase(os.path.abspath(bundle))
        env['PATH'] = os.pathsep.join(p for p in env.get('PATH', '').split(os.pathsep)
            if p and not (os.path.normcase(os.path.abspath(p)) == base or
                          os.path.normcase(os.path.abspath(p)).startswith(base + os.sep)))
    setter = None
    previous = None
    if frozen and os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        get = kernel.GetDllDirectoryW
        get.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        get.restype = ctypes.c_uint32
        size = get(0, None)
        buffer = ctypes.create_unicode_buffer(size + 1)
        get(len(buffer), buffer)
        previous = buffer.value or None
        setter = kernel.SetDllDirectoryW
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_int
        if not setter(None):
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield env
    finally:
        if setter is not None:
            setter(previous)
