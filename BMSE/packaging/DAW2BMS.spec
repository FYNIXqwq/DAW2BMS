from pathlib import Path
import sys
from importlib.metadata import distribution, PackageNotFoundError
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent.parent
datas = collect_data_files('daw2bms', includes=['locales/*.json'])
datas += [(str(root / name), 'licenses/DAW2BMS') for name in ('LICENSE', 'NOTICE')]
datas.append((str(Path(sys.base_prefix) / 'LICENSE.txt'), 'third-party-licenses/Python'))
# Retain notices from the redistributed Python packages, including transitive dependencies.
packages = ['numpy', 'soundfile', 'cffi', 'pycparser', 'PyAutoGUI', 'PyTweening',
            'PyScreeze', 'PyGetWindow', 'PyRect', 'MouseInfo', 'pyperclip',
            'pywinauto', 'comtypes', 'six', 'pywin32', 'pillow', 'setuptools', 'packaging']
for package in packages:
    try:
        dist = distribution(package)
    except PackageNotFoundError:
        if package in ('pillow', 'setuptools', 'packaging'):
            continue
        raise
    datas += copy_metadata(package)
    for file in dist.files or []:
        if any(token in str(file).lower() for token in ('license', 'copying', 'notice')):
            path = Path(dist.locate_file(file))
            if path.is_file():
                datas.append((str(path), 'third-party-licenses/' + package + '/' + str(file.parent).replace('..', '_')))

a = Analysis([str(Path(SPECPATH) / 'engine_entry.py')], pathex=[str(root)],
             binaries=[], datas=datas,
             hiddenimports=collect_submodules('pywinauto', filter=lambda n: '.tests' not in n) + collect_submodules('comtypes', filter=lambda n: '.test' not in n),
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PyQt6', 'PySide6', 'pytest', 'mido', 'daw2bms.gui'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DAW2BMS',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='daw-engine')
