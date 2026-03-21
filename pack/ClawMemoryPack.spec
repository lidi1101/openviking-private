# -*- mode: python ; coding: utf-8 -*-
import os
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


PACK_ROOT = Path(SPECPATH).resolve()
PROJECT_ROOT = PACK_ROOT.parent
BUILD_MODE = os.environ.get("OV_PYINSTALLER_MODE", "onefile").strip().lower()
PACKAGE_NAME = os.environ.get("OV_PACKAGE_NAME", "ClawMemory").strip() or "ClawMemory"
if BUILD_MODE not in {"onefile", "onedir"}:
    raise ValueError(f"Unsupported OV_PYINSTALLER_MODE: {BUILD_MODE}")


def relpath(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


def append_data_tree(source_root: Path, target_root: str) -> None:
    if not source_root.exists():
        return
    for file_path in source_root.rglob("*"):
        if not file_path.is_file():
            continue
        relative_parent = file_path.relative_to(source_root).parent
        destination = Path(target_root)
        if str(relative_parent) != ".":
            destination = destination / relative_parent
        datas.append((str(file_path), str(destination)))


datas = []
binaries = []
hiddenimports = []

hiddenimports += collect_submodules("openviking")
hiddenimports += collect_submodules("openviking_cli")
hiddenimports += collect_submodules("litellm", on_error="ignore")
hiddenimports += collect_submodules("fastapi", on_error="ignore")
hiddenimports += collect_submodules("starlette", on_error="ignore")
hiddenimports += collect_submodules("uvicorn", on_error="ignore")
hiddenimports += collect_submodules("anyio", on_error="ignore")
hiddenimports += collect_submodules("json_repair", on_error="ignore")
hiddenimports += collect_submodules("multipart", on_error="ignore")
hiddenimports.append("openviking.server.startup_e2e")

datas += collect_data_files("openviking", include_py_files=False)
datas += collect_data_files("openviking_cli", include_py_files=False)
datas += collect_data_files("litellm", include_py_files=False)
datas += collect_data_files("fastapi", include_py_files=False)
datas += collect_data_files("starlette", include_py_files=False)
datas += collect_data_files("uvicorn", include_py_files=False)
datas += collect_data_files("json_repair", include_py_files=False)
datas += copy_metadata("fastapi")
datas += copy_metadata("starlette")
datas += copy_metadata("uvicorn")
datas += copy_metadata("json-repair")
datas += copy_metadata("pydantic")
datas += copy_metadata("python_multipart", recursive=True)
append_data_tree(
    PROJECT_ROOT / "openviking" / "prompts" / "templates",
    "openviking/prompts/templates",
)

bundle_internal_embed_source = os.environ.get(
    "OV_BUNDLE_INTERNAL_HONOR_SOURCE_FILE", ""
).strip().lower() in {"1", "true", "yes", "on"}
internal_embed_source = PROJECT_ROOT / "emb_requests.py"
if bundle_internal_embed_source and internal_embed_source.exists():
    datas.append((str(internal_embed_source), "."))


binaries += collect_dynamic_libs("openviking")
binaries += collect_dynamic_libs("litellm")

agfs_binding = PROJECT_ROOT / "openviking" / "lib" / "libagfsbinding.dll"
vectordb_engine = (
    PROJECT_ROOT
    / "openviking"
    / "storage"
    / "vectordb"
    / f"engine{sysconfig.get_config_var('EXT_SUFFIX') or ''}"
)
protector_dir = PROJECT_ROOT / "protector"

if agfs_binding.exists():
    binaries.append((str(agfs_binding), "openviking/lib"))

if vectordb_engine.exists():
    binaries.append((str(vectordb_engine), "openviking/storage/vectordb"))

if protector_dir.exists():
    for protector_file in protector_dir.iterdir():
        if protector_file.is_file():
            datas.append((str(protector_file), "FileProtectDriver"))


a = Analysis(
    [str(PROJECT_ROOT / "openviking_cli" / "server_bootstrap.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "openviking.eval",
        "openviking.eval.ragas",
        "openviking.eval.recorder",
        "ragas",
        "datasets",
        "pytest",
        "scipy",
        "scipy.stats",
    ],
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

