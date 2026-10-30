"""Console/pipe entry point for BMSE's bundled conversion engine."""
import json
import sys


def self_test():
    import tempfile
    from pathlib import Path
    import numpy as np
    import soundfile as sf
    import pyautogui
    import pyperclip
    from pywinauto import Desktop
    from daw2bms.i18n import language_context, tr
    from daw2bms.runtime import ableton_helper_command
    from daw2bms import __version__
    with tempfile.TemporaryDirectory() as directory:
        wav = Path(directory) / 'audio.wav'
        sf.write(wav, np.zeros((441, 2)), 44100, subtype='PCM_24')
        data, rate = sf.read(wav)
        assert data.shape == (441, 2) and rate == 44100
    translated = {}
    for language in ('zh-TW', 'en', 'ja', 'ko'):
        with language_context(language):
            translated[language] = tr('Conversion complete')
    print(json.dumps({'status': 'ok', 'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)),
                      'audio': 'PCM_24 stereo roundtrip', 'languages': translated,
                      'ableton_helper': ableton_helper_command()}, ensure_ascii=False))
    return 0


def main():
    from daw2bms.i18n import configure_console
    configure_console()
    if sys.argv[1:] == ['--self-test']:
        return self_test()
    if sys.argv[1:2] == ['--ableton-ui']:
        del sys.argv[1]
        from daw2bms.ableton_ui import main as run
        return run()
    if sys.argv[1:] == ['--bridge']:
        from daw2bms.bridge import main as run
        return run()
    print('DAW2BMS is the conversion engine bundled with BMSE. Use --bridge or --self-test.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
