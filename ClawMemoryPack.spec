# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve()
BUILD_MODE = os.environ.get("OV_PYINSTALLER_MODE", "onefile").strip().lower()
PACKAGE_NAME = os.environ.get("OV_PACKAGE_NAME", "ClawMemory").strip() or "ClawMemory"
if BUILD_MODE not in {"onefile", "onedir"}:
    raise ValueError(f"Unsupported OV_PYINSTALLER_MODE: {BUILD_MODE}")


def relpath(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


datas = []
binaries = []
hiddenimports = []

hiddenimports += collect_submodules("openviking")
hiddenimports += collect_submodules("openviking_cli")
hiddenimports += collect_submodules("litellm")

datas += collect_data_files("openviking", include_py_files=False)
datas += collect_data_files("openviking_cli", include_py_files=False)
datas += collect_data_files("litellm", include_py_files=False)

binaries += collect_dynamic_libs("openviking")
binaries += collect_dynamic_libs("litellm")

agfs_binding = PROJECT_ROOT / "openviking" / "lib" / "libagfsbinding.dll"
protector_dir = PROJECT_ROOT / "protector"

if agfs_binding.exists():
    binaries.append((str(agfs_binding), "openviking/lib"))

if protector_dir.exists():
    for protector_file in protector_dir.iterdir():
        if protector_file.is_file():
            datas.append((str(protector_file), "FileProtectDriver"))


a = Analysis(
    ["openviking_cli/server_bootstrap.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if BUILD_MODE == "onefile":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=PACKAGE_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=PACKAGE_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name=PACKAGE_NAME,
    )
