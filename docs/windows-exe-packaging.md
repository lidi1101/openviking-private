# Windows EXE Packaging

中文版本：`docs/windows-exe-packaging.zh-CN.md`

This project can be packaged as a double-clickable Windows executable with PyInstaller.

The recommended target is the server entrypoint:

- `openviking_cli/server_bootstrap.py`

The build supports both `onefile` and `onedir`, and defaults to `onefile`. It assumes AGFS runs in `binding-client` mode.

## Prerequisites

Use a Python environment with build dependencies available.

The packaging script will automatically try to build the required runtime artifact with `OV_DISABLE_OV_CLI=1` if it is missing.
It now performs explicit prerequisite checks for Python packaging, and when artifact rebuild is needed it also checks for `go`, `cmake`, `gcc`, and `g++`.
It also validates the active `ov.conf` and requires `storage.agfs.mode = "binding-client"` for this packaging route.

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

Equivalent batch wrapper:

```bat
build_exe.bat
```

Build as `onedir` instead of the default `onefile`:

```powershell
.\build_exe.ps1 -Mode onedir
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

- `dist\OpenVikingServer.exe` in `onefile` mode
- `dist\OpenVikingServer\OpenVikingServer.exe` in `onedir` mode

Double-clicking that file starts the OpenViking server in a console window.

## Example Config

A sample binding-client configuration is available at:

- `docs\ov-binding-client.example.conf`

Copy it to your actual `ov.conf` location and adjust API keys, models, and workspace path as needed.

## Release Package

To prepare a distributable folder and zip archive:

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\package_release.ps1
```

Equivalent batch wrapper:

```bat
package_release.bat
```

To rebuild the exe first and then package:

```powershell
.\package_release.ps1 -RebuildExe
```

To package an `onedir` build:

```powershell
.\package_release.ps1 -Mode onedir -RebuildExe
```

This produces:

- `release\OpenVikingServer\`
- `release\OpenVikingServer-onefile.zip` or `release\OpenVikingServer-onedir.zip`

## Notes

- This packaging targets the server executable only.
- The script automatically runs `pip install -e .` with `OV_DISABLE_OV_CLI=1` when server runtime artifacts are missing.
- The script also sets `OV_DISABLE_AGFS_SERVER=1`, so packaging follows the `binding-client` route and does not require `agfs-server.exe`.
- `-RebuildArtifacts` deletes `libagfsbinding.dll` first, then lets the script rebuild it automatically.
- This route assumes `storage.agfs.mode = "binding-client"`.
- `-Clean` now also removes any legacy `dist\OpenVikingServer\` onedir output left by older builds.
- `ov.exe` is not required for server packaging when `OV_DISABLE_OV_CLI=1` is set during build/install.
- `onefile` still unpacks runtime files to a temporary directory at startup.
- Use `-Mode onedir` if you want the traditional extracted app directory instead of a single executable.
- `build_exe.bat` and `package_release.bat` are thin wrappers around the PowerShell scripts.
- `--with-bot` still depends on `vikingbot` being available in the runtime environment.
- If the executable exits immediately, run it from PowerShell first so you can read the error output.
