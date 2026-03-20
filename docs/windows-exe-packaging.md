# Windows EXE Packaging

Chinese version: `docs/windows-exe-packaging.zh-CN.md`

This project can be packaged as a double-clickable Windows executable with PyInstaller.

The recommended entrypoint is:

- `openviking_cli/server_bootstrap.py`

The package name is centralized in:

- `packaging_config.ps1`

The current package name is `ClawMemory`. To rename the packaged app later, change that file only.

The build supports both `onefile` and `onedir`, and defaults to `onefile`. The current route assumes AGFS runs in `binding-client` mode.

## Prerequisites

Prepare a Python environment with the required packaging dependencies installed.

The build script explicitly checks:

- `PyInstaller`
- when runtime artifacts need rebuilding: `pybind11`, `setuptools`, `wheel`
- system tools needed for rebuilding artifacts: `go`
- C/C++ toolchain for rebuilding artifacts: either install `cmake`, `gcc`, and `g++`, or keep the bundled `third_party\mingw64` directory in the repository
- the active `ov.conf`
- `storage.agfs.mode == "binding-client"`

Install PyInstaller first:

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
pip install -U pyinstaller
```

## Build

Default build:

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\build_exe.ps1
```

Equivalent batch wrapper:

```bat
build_exe.bat
```

Build as `onedir`:

```powershell
.\build_exe.ps1 -Mode onedir
```

Clean previous build output first:

```powershell
.\build_exe.ps1 -clean
```

Force rebuild runtime artifacts before packaging:

```powershell
.\build_exe.ps1 -clean -rebuild
```

Offline-safe mode is the default: the script first tries local artifact build via `setup.py build_ext --inplace` and does not fall back to `pip install -e .` unless you explicitly allow it.

Allow the editable-install fallback:

```powershell
.\build_exe.ps1 -AutoInstall
```

If `third_party\mingw64\bin` exists, the build script prepends it to `PATH` automatically and `setup.py` prefers that bundled MinGW toolchain. This lets you avoid installing `cmake`, `gcc`, and `g++` system-wide. If you use bundled `cmake.exe`, keep `third_party\mingw64\share\cmake-*` intact.

## Output

The executable is generated at:

- `dist\ClawMemory.exe` in `onefile` mode
- `dist\ClawMemory\ClawMemory.exe` in `onedir` mode

Double-clicking that file starts the OpenViking server in a console window.

## Example Config

A sample binding-client configuration is available at:

- `docs\ov-binding-client.example.conf`

Copy it to your actual `ov.conf` location and adjust API keys, models, and workspace path as needed.

## Release Package

Prepare a distributable folder and zip archive:

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\package_release.ps1
```

Equivalent batch wrapper:

```bat
package_release.bat
```

Rebuild the executable first and then package:

```powershell
.\package_release.ps1 -rebuild
```

Package an `onedir` build:

```powershell
.\package_release.ps1 -Mode onedir -rebuild
```

This produces:

- `release\ClawMemory\`
- `release\ClawMemory-onefile.zip` or `release\ClawMemory-onedir.zip`

## Notes

- This packaging route targets the server executable only.
- `protector` files are bundled into `FileProtectDriver\`.
- At runtime, `ClawMemory.exe` runs `FileProtectDriver\FilterUpdate.cmd` before the server starts.
- At shutdown, `ClawMemory.exe` runs `FileProtectDriver\FilterUninstall.cmd`.
- `-rebuild` in `build_exe.ps1` deletes `libagfsbinding.dll` first, then rebuilds it.
- `-clean` removes old `build\` and `dist\` output.
- `ov.exe` is not required for server packaging when `OV_DISABLE_OV_CLI=1` is used during build.
- `onefile` still unpacks runtime files to a temporary directory at startup.
- Use `-Mode onedir` if you want the traditional extracted app directory instead of a single executable.
- `build_exe.bat` and `package_release.bat` are thin wrappers around the PowerShell scripts.
- `--with-bot` still depends on `vikingbot` being available in the runtime environment.
- If the executable exits immediately, run it from PowerShell first so you can read the error output.
