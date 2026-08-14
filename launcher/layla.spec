# PyInstaller spec — run from repo root after `pip install pyinstaller`:
#   pyinstaller launcher/layla.spec
#
# Output: dist/layla.exe — a THIN bootstrapper (layla_boot.py). It runs the external, updatable
# launcher script (launcher/layla_launcher.py, shipped as a plain file in the payload) with the bundled
# Python. Keeping the launcher OUT of the frozen exe is deliberate: launcher fixes/updates become file
# swaps (in-app updater / Repair), never a 410 MB reinstall. Copy next to ``agent/``, ``launcher/`` and
# ``python/`` on end-user machines.

block_cipher = None

a = Analysis(
    ["layla_boot.py"],
    pathex=["launcher"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="layla",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
