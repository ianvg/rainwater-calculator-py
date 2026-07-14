# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["tkinter_app.py"],
    pathex=[],
    binaries=[],
    datas=[("site", "help"), ("assets/app_icon.png", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "altair",
        "matplotlib",
        "PIL",
        "plotly",
        "pyarrow",
        "pytest",
        "streamlit",
        "watchdog",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,
    name="RainwaterCalculator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app_icon.ico",
)
