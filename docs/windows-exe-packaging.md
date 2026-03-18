# Windows EXE Packaging

This project can be packaged as a double-clickable Windows executable with PyInstaller.

The recommended target is the server entrypoint:

- `openviking_cli/server_bootstrap.py`

The build uses `onedir`, not `onefile`. This project ships native runtime artifacts and DLLs, so `onedir` is the more reliable Windows packaging mode.

## Prerequisites

Use a Python environment with build dependencies available.

The packaging script will automatically try to build the required runtime artifacts with `OV_DISABLE_OV_CLI=1` if they are missing.

Install PyInstaller first:

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
pip install -U pyinstaller
```

## Build

Run:

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\build_exe.ps1
```

Clean previous build output first:

```powershell
.\build_exe.ps1 -Clean
```

Force rebuild the server runtime artifacts and then package:

```powershell
.\build_exe.ps1 -Clean -RebuildArtifacts
```

## Output

The executable is generated at:

- `dist\OpenVikingServer\OpenVikingServer.exe`

Double-clicking that file starts the OpenViking server in a console window.

## Notes

- This packaging targets the server executable only.
- The script automatically runs `pip install -e .` with `OV_DISABLE_OV_CLI=1` when server runtime artifacts are missing.
- `-RebuildArtifacts` deletes `agfs-server.exe` and `libagfsbinding.dll` first, then lets the script rebuild them automatically.
- `ov.exe` is not required for server packaging when `OV_DISABLE_OV_CLI=1` is set during build/install.
- `--with-bot` still depends on `vikingbot` being available in the runtime environment.
- If the executable exits immediately, run it from PowerShell first so you can read the error output.
