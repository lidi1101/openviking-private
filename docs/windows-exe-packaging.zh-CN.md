# Windows EXE 打包说明

English version: `docs/windows-exe-packaging.md`

本项目可以使用 PyInstaller 打包为可双击执行的 Windows 程序。

推荐的入口是：

- `openviking_cli/server_bootstrap.py`

当前打包链路同时支持 `onefile` 和 `onedir`，默认使用 `onefile`。该方案默认假设 AGFS 运行在 `binding-client` 模式。

## 前置条件

请使用具备构建依赖的 Python 环境。

如果缺少运行时产物，打包脚本会自动尝试使用 `OV_DISABLE_OV_CLI=1` 进行构建。

脚本当前会显式检查：

- Python 打包相关依赖
- 当需要重建原生产物时，会检查 `go`、`cmake`、`gcc`、`g++`
- 当前实际生效的 `ov.conf`
- `storage.agfs.mode` 是否为 `"binding-client"`

先安装 PyInstaller：

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
pip install -U pyinstaller
```

## 打包

默认以 `onefile` 模式打包：

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\build_exe.ps1
```

如果要使用 `onedir`：

```powershell
.\build_exe.ps1 -Mode onedir
```

先清理旧产物再重新打包：

```powershell
.\build_exe.ps1 -Clean
```

如果要强制重建服务端运行时产物后再打包：

```powershell
.\build_exe.ps1 -Clean -RebuildArtifacts
```

## 输出

生成结果如下：

- `onefile` 模式：`dist\OpenVikingServer.exe`
- `onedir` 模式：`dist\OpenVikingServer\OpenVikingServer.exe`

双击该可执行文件即可启动 OpenViking 服务。

## 示例配置

适用于当前 `binding-client` 路线的示例配置文件：

- `docs\ov-binding-client.example.conf`

请将其复制到你实际使用的 `ov.conf` 路径，并根据需要修改：

- API Key
- 模型名称
- `workspace`

## 发布包

生成发布目录和 zip 包：

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\package_release.ps1
```

先重打可执行文件再生成发布包：

```powershell
.\package_release.ps1 -RebuildExe
```

如果要打 `onedir` 版本的发布包：

```powershell
.\package_release.ps1 -Mode onedir -RebuildExe
```

输出如下：

- `release\OpenVikingServer\`
- `release\OpenVikingServer-onefile.zip` 或 `release\OpenVikingServer-onedir.zip`

## 说明

- 当前打包链路只针对服务端可执行文件。
- 当缺少运行时产物时，脚本会自动执行 `pip install -e .`，并设置 `OV_DISABLE_OV_CLI=1`。
- 脚本也会设置 `OV_DISABLE_AGFS_SERVER=1`，因此当前打包路线不再依赖 `agfs-server.exe`。
- `-RebuildArtifacts` 会先删除 `libagfsbinding.dll`，然后自动重建。
- 当前路线要求 `storage.agfs.mode = "binding-client"`。
- `-Clean` 还会清理旧的 `dist\OpenVikingServer\` onedir 历史目录。
- 当设置 `OV_DISABLE_OV_CLI=1` 时，服务端打包不依赖 `ov.exe`。
- `onefile` 模式在运行时仍会先解包到临时目录，这是正常行为。
- 如果你希望保留传统目录结构而不是单文件，可使用 `-Mode onedir`。
- `--with-bot` 仍然要求目标环境中可用 `vikingbot`。
- 如果程序启动后立即退出，请先在 PowerShell 中运行，以便查看错误输出。
