# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for building a Windows/macOS/Linux GUI bundle.
# Build on the target OS/architecture (PyInstaller does not cross-compile).
#
# Usage (Windows):
#   py -m venv .venv
#   .\\.venv\\Scripts\\activate
#   pip install -r requirements.txt
#   pip install pyinstaller
#   pyinstaller --noconfirm --clean packaging\\draft2craift.spec
#
from pathlib import Path

block_cipher = None

project_root = Path(__file__).resolve().parent.parent

datas = [
    (str(project_root / "data"), "data"),
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
]

hiddenimports = [
    # Imported dynamically (inside a worker thread) → help PyInstaller include it.
    "llama_cpp",
    "llama_cpp.llama_cpp",
]

a = Analysis(
    [str(project_root / "studio" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="draft2craift",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="draft2craift",
)
