# Windows Packaging Guide

Chinese version: `docs/windows-exe-packaging.zh-CN.md`

This document describes the current Windows packaging layout for `ClawMemory.exe`.

## 1. Packaging Layout

The packaging files are now centralized under:

- `pack\build_exe.ps1`
- `pack\package_release.ps1`
- `pack\packaging_config.ps1`
- `pack\ClawMemoryPack.spec`
- `pack\ov-binding-client.example.conf`

The root directory only keeps the release entrypoints:

- `pack.ps1`
- `pack.bat`

Packaging output is now written under:

- `pack\dist\`

## 2. Packaging Target

Current assumptions:

- entrypoint: `openviking_cli/server_bootstrap.py`
- package name: `ClawMemory`
- AGFS mode: `binding-client`
- `FileProtectDriver` is bundled into the package

## 3. Environment Preparation

### 3.1 Python

Install at least:

```powershell
pip install -U pyinstaller
pip install -U pybind11 setuptools wheel
```

The scripts explicitly check:

- `PyInstaller`
- `pybind11`
- `setuptools`
- `wheel`

Python 3.12 is recommended for release builds. Python 3.14 currently produces Pydantic V1 compatibility warnings and should be treated as high risk.

### 3.2 Go

`libagfsbinding.dll` is built with Go, so the machine also needs:

- `go`

### 3.3 C/C++ toolchain

The build uses CMake + MinGW and needs:

- `cmake`
- `gcc`
- `g++`
- `mingw32-make`

The script prefers the repository toolchain and supports:

- extracted toolchain: `third_party\mingw64\`
- split archive entry: `third_party\mingw64.7z.001`
- archive: `third_party\mingw64.7z`
- archive: `third_party\mingw64.zip`

If only an archive exists, the build script extracts it before rebuilding runtime artifacts.

### 3.4 Runtime config

The active config file is resolved in this order:

1. `OPENVIKING_CONFIG_FILE`
2. `%USERPROFILE%\.openviking\ov.conf`

The build requires:

```json
"storage": {
  "agfs": {
    "mode": "binding-client"
  }
}
```

Before validation, the build script syncs `%USERPROFILE%\.openviking\ov.conf` from:

- `pack\ov-binding-client.example.conf`

If the user config directory or file does not exist, it is created automatically. If the file already exists, it is overwritten by the packaged sample.

## 4. Commands

### 4.1 Root entrypoint: `pack.ps1`

[`pack.ps1`](d:/HClawCode/LiDi/openviking-private/pack.ps1) is the unified release entrypoint at the repository root. It internally calls [`pack/package_release.ps1`](d:/HClawCode/LiDi/openviking-private/pack/package_release.ps1).

Available commands:

`.\pack.ps1`  
Purpose: generate a release package in default `onefile` mode from the existing build output. If usable output already exists, no rebuild happens first.

`.\pack.ps1 -Mode onefile`  
Purpose: explicitly select `onefile`. Same behavior as the default command.

`.\pack.ps1 -rebuild`  
Purpose: rebuild `ClawMemory.exe` first, then generate the `onefile` release package.

`.\pack.ps1 -Mode onefile -rebuild`  
Purpose: explicitly rebuild and package in `onefile` mode.

`.\pack.ps1 -Mode onedir`  
Purpose: generate an `onedir` release package from the existing directory-style build output.

`.\pack.ps1 -Mode onedir -rebuild`  
Purpose: rebuild the `onedir` variant first, then generate the directory-style release package.

Equivalent batch entrypoint:

```bat
pack.bat
```

Recommended usage:

- normal onefile release: `.\pack.ps1 -rebuild`
- more stable onedir release: `.\pack.ps1 -Mode onedir -rebuild`

### 4.2 Internal build script: `pack\build_exe.ps1`

Default `onefile` build only:

```powershell
.\pack.ps1
```

.\pack\build_exe.ps1
```

Build `onedir`:

```powershell
.\pack\build_exe.ps1 -Mode onedir
```

Clean old output:

```powershell
.\pack\build_exe.ps1 -clean
```

Force runtime-artifact rebuild and then build:

```powershell
.\pack\build_exe.ps1 -clean -rebuild
```

Allow fallback to `pip install -e .`:

```powershell
.\pack\build_exe.ps1 -AutoInstall
```

`pack.ps1` currently exposes only:

- `-Mode onefile|onedir`
- `-rebuild`

It does not expose a standalone `-clean`, because the root entrypoint is intended as a release command. Fine-grained clean/rebuild control stays in `pack\build_exe.ps1`.

The most important distinction in `pack\build_exe.ps1` is `-clean` vs `-rebuild`:

- `-clean`: only clears packaging output
- `-rebuild`: forces runtime-artifact rebuild

Concretely:

- `-clean` removes `pack\build` and `pack\dist`
- `-clean` does not proactively remove `openviking\lib\libagfsbinding.dll`
- if `libagfsbinding.dll` still exists, it is reused
- `-rebuild` additionally removes `openviking\lib\libagfsbinding.dll`
- after removal, the script rebuilds `libagfsbinding.dll` and then continues packaging

Examples:

```powershell
.\pack\build_exe.ps1 -clean
```

This:

- clears `pack\build`
- clears `pack\dist`
- rebuilds the package
- reuses `libagfsbinding.dll` if it already exists

```powershell
.\pack\build_exe.ps1 -clean -rebuild
```

This:

- clears `pack\build`
- clears `pack\dist`
- removes `libagfsbinding.dll`
- rebuilds `libagfsbinding.dll`
- rebuilds the package

### 4.3 Internal release script: `pack\package_release.ps1`

Package existing build output:

```powershell
.\pack\package_release.ps1
```

Rebuild first, then package:

```powershell
.\pack\package_release.ps1 -rebuild
```

Create an `onedir` release package:

```powershell
.\pack\package_release.ps1 -Mode onedir -rebuild
```

## 5. Output Paths

Relevant outputs for `pack.ps1` / `pack\package_release.ps1`:

- `onefile`: `pack\dist\ClawMemory.exe`
- `onedir`: `pack\dist\ClawMemory\ClawMemory.exe`
- `pack\dist\release\ClawMemory\`
- `pack\dist\release\ClawMemory-onefile.zip`
- `pack\dist\release\ClawMemory-onedir.zip`

## 6. Important Notes

### 6.1 Inspect the resolved toolchain

At startup, `pack\build_exe.ps1` prints:

```text
Resolved toolchain:
  cmake -> ...
  gcc -> ...
  g++ -> ...
  mingw32-make -> ...
```

Use this to confirm whether the build is using the bundled repository toolchain or older system binaries by accident.

### 6.2 Colored step markers

The packaging scripts print colored steps:

- cyan: step started
- green: step completed
- magenta: step failed

At the end of the run, both scripts print a numbered step summary in execution order.

### 6.3 `onefile` vs `onedir`

`onefile`:

- produces a single executable
- is easier to distribute
- extracts to a temporary directory at runtime

`onedir`:

- produces a directory layout
- is easier to debug
- should be distributed as a whole directory

### 6.4 `FileProtectDriver`

The packaged runtime automatically calls:

- before startup: `FileProtectDriver\FilterUpdate.cmd`
- on shutdown: `FileProtectDriver\FilterUninstall.cmd`

So the packaged output must include `FileProtectDriver`, and runtime execution may require administrator privileges depending on the driver install path.

### 6.5 Offline packaging

For offline packaging, make sure in advance:

- Python dependencies are already installed
- `go` is available
- `PyInstaller` is available
- `openviking\_version.py` exists
- `third_party\mingw64\` or one of its archives exists

The best offline validation command is:

```powershell
.\pack\build_exe.ps1 -clean -rebuild
```

If you only want to clear old packaging output while keeping the existing `libagfsbinding.dll`, use:

```powershell
.\pack\build_exe.ps1 -clean
```

### 6.6 Split archives

Split `7z` archives such as:

- `third_party\mingw64.7z.001`
- `third_party\mingw64.7z.002`
- `third_party\mingw64.7z.003`

are supported. The `.001` file is treated as the archive entry file.

## 7. Related Files

- `pack.ps1`
- `pack.bat`
- `pack\build_exe.ps1`
- `pack\package_release.ps1`
- `pack\packaging_config.ps1`
- `pack\ClawMemoryPack.spec`
- `pack\ov-binding-client.example.conf`

