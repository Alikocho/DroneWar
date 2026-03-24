# dronewar.spec
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[('static', 'static'), ('server.py', '.'), ('dronewar', 'dronewar')],
    hiddenimports=[
        'dronewar.env.airspace',
        'dronewar.env.actions',
        'dronewar.env.observation',
        'dronewar.agents.agents',
        'dronewar.engine.engine',
        'dronewar.scenarios.scenarios',
        'flask', 'flask.templating', 'jinja2',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == 'darwin':
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name='dronewar', debug=False, bootloader_ignore_signals=False,
              strip=False, upx=True, console=True)
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
                   strip=False, upx=True, upx_exclude=[], name='DroneWar')
    app = BUNDLE(coll, name='DroneWar.app', icon=None,
                 bundle_identifier='com.coldalchemy.dronewar',
                 info_plist={
                     'CFBundleShortVersionString': '1.0.0',
                     'CFBundleVersion':            '1.0.0',
                     'NSHighResolutionCapable':    True,
                     # Allow the app to open URLs without subprocess permissions
                     'LSMinimumSystemVersion':     '10.13.0',
                 })
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
              name='dronewar', debug=False, bootloader_ignore_signals=False,
              strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None,
              console=True)
