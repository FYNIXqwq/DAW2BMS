"""Build-time smoke test: frozen runtime with no Python paths or source checkout."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading


def verify(executable):
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'DAW2BMS_ROOT', 'DAW2BMS_PYTHON'):
        env.pop(key, None)
    env['PATH'] = str(Path(os.environ.get('SYSTEMROOT', 'C:/Windows')) / 'System32')
    with tempfile.TemporaryDirectory(prefix='bmse-bundle-') as temporary:
        root = Path(temporary)
        def command(*args):
            return subprocess.run([str(executable), *args], cwd=root, env=env,
                capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
        report = json.loads(command('--self-test').stdout)
        assert report['status'] == 'ok' and report['frozen']
        command('--ableton-ui', '--help')
        source = root / '工程 test.als'
        source.write_text('<Ableton Creator="Ableton Live 12" MinorVersion="12.0_test"><LiveSet><Tracks><MidiTrack Id="7"><Name><EffectiveName Value="MIDI fixture"/></Name><DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation><Events><MidiClip Id="0" Time="0"><CurrentStart Value="0"/><CurrentEnd Value="4"/><Loop><LoopStart Value="0"/><LoopEnd Value="4"/><StartRelative Value="0"/><LoopOn Value="false"/></Loop><Notes><KeyTracks><KeyTrack><MidiKey Value="60"/><Notes><MidiNoteEvent Time="0" Duration="1" Velocity="100"/></Notes></KeyTrack></KeyTracks></Notes></MidiClip></Events></ArrangerAutomation></ClipTimeable></MainSequencer></DeviceChain></MidiTrack></Tracks></LiveSet></Ableton>', encoding='utf-8')
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        def bridge(request):
            proc = subprocess.Popen([str(executable), '--bridge'], cwd=root, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8')
            events = queue.Queue()
            def read():
                for line in proc.stdout:
                    events.put(line)
                events.put(None)
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                proc.stdin.write(json.dumps(request) + '\n')
                proc.stdin.flush()
                terminal = None
                while True:
                    line = events.get(timeout=30)
                    if line is None:
                        break
                    event = json.loads(line)
                    if event['type'] in ('tracks', 'result', 'error', 'cancelled'):
                        terminal = event
                        break
                proc.stdin.close()
                proc.wait(timeout=10)
                if proc.returncode or terminal is None or terminal['type'] in ('error', 'cancelled'):
                    raise RuntimeError(f'{terminal}: {proc.stderr.read()}')
                return terminal
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                reader.join(timeout=2)
        base = {'protocol': 1, 'source': str(source), 'language': 'ja'}
        preview = bridge(dict(base, action='inspect'))['data']
        assert preview['sha256'] == source_hash
        out = root / 'converted'
        result = bridge(dict(base, action='convert', out=str(out), options={
            'source_sha256': source_hash, 'play_tracks': [7]}))['data']
        assert result['status'] == 'midi_only' and not result['chart']
        assert (out / 'song.mid').read_bytes()[:4] == b'MThd'
        assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
        print('Bundled runtime verified: isolated PATH, audio I/O, four languages, Ableton helper, ALS -> MIDI, source unchanged.')


if __name__ == '__main__':
    verify(Path(sys.argv[1]).resolve())
