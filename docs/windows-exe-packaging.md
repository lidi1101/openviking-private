# Windows Packaging Guide

Chinese version: `docs/windows-exe-packaging.zh-CN.md`

This document explains how to package the current project into `ClawMemory.exe` on Windows. It focuses on:

- packaging environment preparation
- how to use the packaging commands
- important caveats during the packaging process

## 1. Packaging Target

The current packaging target is the server executable:

- entrypoint: `openviking_cli/server_bootstrap.py`
- package-name config: `packaging_config.ps1`
- current default package name: `ClawMemory`

The current packaging route assumes:

- AGFS runs in `binding-client` mode
- `ov.exe` is not required
- `FileProtectDriver` is included in the package

## 2. Environment Preparation

### 2.1 Python environment

Prepare an isolated Python environment and install at least:

```powershell
pip install -U pyinstaller
pip install -U pybind11 setuptools wheel
```

The script explicitly checks for:

- `PyInstaller`
- `pybind11`
- `setuptools`
- `wheel`

If any of these are missing, runtime-artifact rebuilds will fail immediately.

### 2.2 Go environment

`libagfsbinding.dll` is built with Go, so the machine also needs:

- `go`

The script checks `go` whenever runtime artifacts need rebuilding.

### 2.3 C/C++ toolchain

The project currently builds the native extension through CMake + MinGW, so it needs:

- `cmake`
- `gcc`
- `g++`
- `mingw32-make`

You can prepare this in one of two ways:

1. install `cmake/gcc/g++` system-wide
2. keep the toolchain inside the repository

The script prefers the repository toolchain and supports:

- extracted directory: `third_party\mingw64\`
- split archive entry file: `third_party\mingw64.7z.001`
- archive: `third_party\mingw64.7z`
- archive: `third_party\mingw64.zip`

If `third_party\mingw64\bin` exists, the script prepends it to `PATH` automatically and prefers that toolchain.

If only an archive is present, the script extracts it automatically before rebuilding runtime artifacts.

### 2.4 Archive extraction support

If the toolchain is stored as an archive, the script tries extractors in this order:

1. `7z` / `7za` / `7zr` / `C:\Program Files\7-Zip\7z.exe`
2. for `.7z`: Windows `tar.exe`
3. for `.zip`: PowerShell `Expand-Archive`
4. Windows Shell extraction support

So:

- split `mingw64.7z.001/.002/...` archives are recognized
- both `mingw64.7z` and `mingw64.zip` are supported
- a standalone 7-Zip installation is not always required

For split `7z.001` archives, the most reliable path is still 7-Zip. The script recognizes the `.001` file as the archive entry file and extracts from there.

### 2.5 Runtime configuration

Before packaging, make sure the effective `ov.conf` is valid.

The script checks, in order:

1. `OPENVIKING_CONFIG_FILE`
2. `%USERPROFILE%\.openviking\ov.conf`

and requires:

```json
"storage": {
  "agfs": {
    "mode": "binding-client"
  }
}
```

If the active config still uses `http-client`, packaging stops immediately.

If `%USERPROFILE%\.openviking\ov.conf` does not exist, the build script creates it automatically from:

- `docs\ov-binding-client.example.conf`

## 3. Build Commands

### 3.1 Default build

Default mode is `onefile`:

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\build_exe.ps1
```

Equivalent batch wrapper:

```bat
build_exe.bat
```

### 3.2 Build as `onedir`

If you want the traditional extracted directory layout:

```powershell
.\build_exe.ps1 -Mode onedir
```

### 3.3 Clean previous output

Clean old `build\` and `dist\` output first:

```powershell
.\build_exe.ps1 -clean
```

### 3.4 Force runtime-artifact rebuild

Delete `libagfsbinding.dll`, rebuild it, and then package:

```powershell
.\build_exe.ps1 -clean -rebuild
```

This is the best command for validating the offline packaging path.

### 3.5 Allow automatic install fallback

The default mode is offline-first:

- it first tries `setup.py build_ext --inplace`
- it does not automatically fall back to `pip install -e .`

If you explicitly want the editable-install fallback:

```powershell
.\build_exe.ps1 -AutoInstall
```

## 4. Release Package Commands

### 4.1 Package existing build output

```powershell
.\package_release.ps1
```

Equivalent batch wrapper:

```bat
package_release.bat
```

### 4.2 Rebuild first, then package

```powershell
.\package_release.ps1 -rebuild
```

### 4.3 Build and package `onedir`

```powershell
.\package_release.ps1 -Mode onedir -rebuild
```

## 5. Output

### 5.1 `build_exe.ps1` output

- `onefile`: `dist\ClawMemory.exe`
- `onedir`: `dist\ClawMemory\ClawMemory.exe`

### 5.2 `package_release.ps1` output

- `release\ClawMemory\`
- `release\ClawMemory-onefile.zip`
- `release\ClawMemory-onedir.zip`

## 6. Important Notes

### 6.1 Always inspect the resolved toolchain

At startup, `build_exe.ps1` prints:

```text
Resolved toolchain:
  cmake -> ...
  gcc -> ...
  g++ -> ...
  mingw32-make -> ...
```

This is important. It tells you whether the build is using:

- the repository toolchain
- or an older system toolchain by accident

If these paths still point to system binaries, it usually means:

- the repository toolchain has not been extracted yet
- extraction failed
- or `gcc.exe/g++.exe` are still missing from the extracted directory

The packaging scripts also print colored step markers:

- cyan: step started
- green: step completed successfully
- magenta: step failed

At the end of the run, both scripts print a step summary showing which steps ran and their results, even when the process stops because of an error.

### 6.2 `onefile` vs `onedir`

`onefile`:

- produces a single executable
- easier to distribute
- unpacks to a temporary directory at runtime
- more likely to be flagged by security software

`onedir`:

- produces an extracted directory
- starts more directly
- is easier to debug
- must be distributed as a whole directory

If you want easier debugging or more stable delivery, prefer:

```powershell
.\package_release.ps1 -Mode onedir -rebuild
```

### 6.3 Do not copy only the executable in `onedir`

In `onedir` mode, do not copy only:

- `ClawMemory.exe`

Copy the whole directory instead:

- `dist\ClawMemory\`

### 6.4 `FileProtectDriver` participates in startup and shutdown

The current runtime automatically calls:

- before startup: `FileProtectDriver\FilterUpdate.cmd`
- on shutdown: `FileProtectDriver\FilterUninstall.cmd`

So make sure:

- `FileProtectDriver` is present in the packaged output
- if those scripts require administrator privileges, double-click launch may fail

### 6.5 Offline packaging checklist

For offline packaging, verify in advance:

- Python dependencies are already installed
- `go` is available
- `PyInstaller` is available
- `ov.conf` is valid
- `third_party\mingw64\` or one of its archives is present

The best offline validation command is:

```powershell
.\build_exe.ps1 -clean -rebuild
```

### 6.6 Packaging still works without `git`

The script already supports packaging on machines without `git`:

- it reads the version from `openviking\_version.py`
- it sets the fallback version for `setuptools-scm`

So offline packaging machines do not need `git`, but they do need:

- `openviking\_version.py`

### 6.7 Terminal mojibake does not always mean the file is broken

If Markdown content looks garbled in PowerShell, that is usually a terminal-encoding issue rather than file corruption. Prefer checking the file in the IDE.

## 7. Recommended Commands

### 7.1 Fast local build

```powershell
.\build_exe.ps1
```

### 7.2 Full rebuild and package

```powershell
.\build_exe.ps1 -clean -rebuild
```

### 7.3 Create an `onedir` release package

```powershell
.\package_release.ps1 -Mode onedir -rebuild
```

### 7.4 Create a `onefile` release package

```powershell
.\package_release.ps1 -rebuild
```

## 8. Related Files

- `build_exe.ps1`
- `build_exe.bat`
- `package_release.ps1`
- `package_release.bat`
- `packaging_config.ps1`
- `OpenVikingServer.spec`
- `docs\ov-binding-client.example.conf`
