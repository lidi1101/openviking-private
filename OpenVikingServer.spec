# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve()


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

agfs_server = PROJECT_ROOT / "openviking" / "bin" / "agfs-server.exe"
agfs_binding = PROJECT_ROOT / "openviking" / "lib" / "libagfsbinding.dll"
ov_binary = PROJECT_ROOT / "openviking" / "bin" / "ov.exe"

if agfs_server.exists():
    datas.append((relpath(agfs_server), "openviking/bin"))

if ov_binary.exists():
    datas.append((relpath(ov_binary), "openviking/bin"))

if agfs_binding.exists():
    binaries.append((str(agfs_binding), "openviking/lib"))


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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenVikingServer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    name="OpenVikingServer",
)
