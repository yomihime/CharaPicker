# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

qf_datas, qf_binaries, qf_hiddenimports = collect_all('qfluentwidgets')

block_cipher = None


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=qf_binaries,
    datas=[
        ('i18n', 'i18n'),
        ('res', 'res'),
    ] + qf_datas,
    hiddenimports=qf_hiddenimports,
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
    name='CharaPicker',
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
    icon='res/app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CharaPicker',
)
