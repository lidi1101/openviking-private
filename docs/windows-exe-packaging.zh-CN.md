# Windows EXE 打包说明

英文版：`docs/windows-exe-packaging.md`

本项目可以通过 PyInstaller 打包为可双击运行的 Windows 可执行文件。

推荐入口：

- `openviking_cli/server_bootstrap.py`

包名统一配置在：

- `packaging_config.ps1`

当前包名为 `ClawMemory`。如果后续需要改名，只需要修改这一个文件。

当前打包方案同时支持 `onefile` 和 `onedir`，默认使用 `onefile`。当前路线假设 AGFS 运行在 `binding-client` 模式。

## 前置条件

请先准备好用于打包的 Python 环境。

脚本会显式检查：

- `PyInstaller`
- 当需要重建运行时产物时：`pybind11`、`setuptools`、`wheel`
- 重建产物依赖的系统工具：`go`
- 重建产物依赖的 C/C++ 工具链：要么系统已安装 `cmake`、`gcc` 和 `g++`，要么仓库中保留 `third_party\mingw64`
- 当前生效的 `ov.conf`
- `storage.agfs.mode == "binding-client"`

先安装 PyInstaller：

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
pip install -U pyinstaller
```

如果仓库中存在 `third_party\mingw64\bin`，`build_exe.ps1` 会自动把它加入 `PATH`，`setup.py` 也会优先使用这套仓库内的 MinGW 工具链。因此可以不在系统里单独安装 `cmake`、`gcc` 和 `g++`。如果你使用仓库内的 `cmake.exe`，请保留 `third_party\mingw64\share\cmake-*` 目录。

## 打包

默认打包：

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\build_exe.ps1
```

对应的批处理包装脚本：

```bat
build_exe.bat
```

使用 `onedir` 模式：

```powershell
.\build_exe.ps1 -Mode onedir
```

先清理旧产物：

```powershell
.\build_exe.ps1 -clean
```

先重建运行时产物再打包：

```powershell
.\build_exe.ps1 -clean -rebuild
```

当前默认是离线优先模式：脚本会先尝试执行 `setup.py build_ext --inplace` 本地构建，不会自动回退到 `pip install -e .`。

如果你明确允许回退到 editable install：

```powershell
.\build_exe.ps1 -AutoInstall
```

## 输出

生成结果如下：

- `onefile` 模式：`dist\ClawMemory.exe`
- `onedir` 模式：`dist\ClawMemory\ClawMemory.exe`

双击该文件即可在控制台窗口中启动 OpenViking 服务。

## 示例配置

适用于当前 `binding-client` 路线的示例配置文件：

- `docs\ov-binding-client.example.conf`

请将它复制到你实际使用的 `ov.conf` 路径，并按需修改：

- API Key
- 模型名称
- `workspace`

## 发布包

生成发布目录和 zip 包：

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\package_release.ps1
```

对应的批处理包装脚本：

```bat
package_release.bat
```

先重打可执行文件再生成发布包：

```powershell
.\package_release.ps1 -rebuild
```

如果要打 `onedir` 版本的发布包：

```powershell
.\package_release.ps1 -Mode onedir -rebuild
```

输出如下：

- `release\ClawMemory\`
- `release\ClawMemory-onefile.zip` 或 `release\ClawMemory-onedir.zip`

## 说明

- 当前打包路线只针对服务端可执行文件。
- `protector` 目录中的文件会被打进包内的 `FileProtectDriver\` 目录。
- 运行时，`ClawMemory.exe` 会在服务启动前执行 `FileProtectDriver\FilterUpdate.cmd`。
- 程序退出时，`ClawMemory.exe` 会执行 `FileProtectDriver\FilterUninstall.cmd`。
- `build_exe.ps1` 中的 `-rebuild` 会先删除 `libagfsbinding.dll`，然后重建。
- `build_exe.ps1` 中的 `-clean` 会清理旧的 `build\` 和 `dist\` 目录。
- 当设置 `OV_DISABLE_OV_CLI=1` 时，服务端打包不依赖 `ov.exe`。
- `onefile` 模式在运行时仍会先解包到临时目录，这是正常行为。
- 如果你希望保留传统目录结构而不是单文件，可使用 `-Mode onedir`。
- `build_exe.bat` 和 `package_release.bat` 只是对 PowerShell 脚本的薄包装。
- `--with-bot` 仍然要求目标环境中可用 `vikingbot`。
- 如果程序启动后立刻退出，请先在 PowerShell 中运行，以便查看错误输出。
