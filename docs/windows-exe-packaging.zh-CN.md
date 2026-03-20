# Windows 打包指导

英文版：`docs/windows-exe-packaging.md`

本文档用于说明如何在 Windows 环境下将当前项目打包为 `ClawMemory.exe`，主要覆盖以下内容：

- 打包环境准备
- 打包命令的使用
- 打包过程中的注意事项

## 1. 打包目标

当前打包目标是服务端程序：

- 入口文件：`openviking_cli/server_bootstrap.py`
- 包名配置：`packaging_config.ps1`
- 当前默认包名：`ClawMemory`

当前打包路线假设：

- AGFS 运行模式为 `binding-client`
- 不依赖 `ov.exe`
- 打包时会携带 `FileProtectDriver`

## 2. 打包环境准备

### 2.1 Python 环境

建议先准备一个独立的 Python 环境，并至少安装：

```powershell
pip install -U pyinstaller
pip install -U pybind11 setuptools wheel
```

脚本在运行时会显式检查：

- `PyInstaller`
- `pybind11`
- `setuptools`
- `wheel`

如果缺少这些依赖，重建运行时产物时会直接失败。

### 2.2 Go 环境

当前 `libagfsbinding.dll` 是通过 Go 构建的，因此机器上还需要：

- `go`

脚本在需要重建运行时产物时会检查 `go` 是否可用。

### 2.3 C/C++ 工具链

当前项目使用 CMake + MinGW 路线构建本地扩展，因此需要：

- `cmake`
- `gcc`
- `g++`
- `mingw32-make`

你有两种准备方式：

1. 系统已安装 `cmake/gcc/g++`
2. 仓库内提供工具链

当前脚本优先支持仓库内工具链：

- 已解压目录：`third_party\mingw64\`
- 分卷压缩包入口文件：`third_party\mingw64.7z.001`
- 压缩包：`third_party\mingw64.7z`
- 压缩包：`third_party\mingw64.zip`

如果仓库中存在 `third_party\mingw64\bin`，脚本会自动把它加入 `PATH`，并优先使用仓库内工具链。

如果仓库中只有压缩包，脚本会在需要重建运行时产物时自动解压。

### 2.4 压缩包解压能力

如果你把工具链保存为压缩包，脚本会按以下顺序尝试解压：

1. `7z` / `7za` / `7zr` / `C:\Program Files\7-Zip\7z.exe`
2. 对 `.7z`：Windows 自带 `tar.exe`
3. 对 `.zip`：PowerShell `Expand-Archive`
4. Windows Shell 解压能力

因此：

- `mingw64.7z.001/.002/...` 这类分卷包也会被识别
- `mingw64.7z` 和 `mingw64.zip` 都支持
- 不一定强依赖单独安装 7-Zip

但对于 `7z.001` 分卷包，最稳妥的方式仍然是使用 7-Zip。脚本会把 `.001` 视为入口卷并从这里开始解压。

### 2.5 运行配置

打包前请确认实际生效的 `ov.conf` 可用。

脚本会优先检查：

1. `OPENVIKING_CONFIG_FILE`
2. `%USERPROFILE%\.openviking\ov.conf`

并要求：

```json
"storage": {
  "agfs": {
    "mode": "binding-client"
  }
}
```

如果当前配置还是 `http-client`，打包脚本会直接中止。

如果 `%USERPROFILE%\.openviking\ov.conf` 不存在，打包脚本会自动基于以下示例文件创建默认配置：

- `docs\ov-binding-client.example.conf`

## 3. 打包命令

### 3.1 默认打包

默认是 `onefile` 模式：

```powershell
cd d:\HClawCode\HClawMemory\ClawMemory
.\build_exe.ps1
```

对应批处理入口：

```bat
build_exe.bat
```

### 3.2 指定 `onedir`

如果你希望输出传统目录结构，而不是单文件：

```powershell
.\build_exe.ps1 -Mode onedir
```

### 3.3 清理旧产物

先清理旧的 `build\` 和 `dist\`：

```powershell
.\build_exe.ps1 -clean
```

### 3.4 强制重建运行时产物

删除 `libagfsbinding.dll` 后重新构建，再打包：

```powershell
.\build_exe.ps1 -clean -rebuild
```

这个命令最适合用于验证离线打包链路是否完整。

### 3.5 允许自动安装

当前默认是离线优先模式：

- 先尝试本地执行 `setup.py build_ext --inplace`
- 不自动回退到 `pip install -e .`

如果你明确允许脚本在失败时回退到 editable install：

```powershell
.\build_exe.ps1 -AutoInstall
```

## 4. 发布包命令

### 4.1 基于现有产物生成发布包

```powershell
.\package_release.ps1
```

对应批处理入口：

```bat
package_release.bat
```

### 4.2 先重打再生成发布包

```powershell
.\package_release.ps1 -rebuild
```

### 4.3 生成 `onedir` 发布包

```powershell
.\package_release.ps1 -Mode onedir -rebuild
```

## 5. 输出结果

### 5.1 `build_exe.ps1` 输出

- `onefile`：`dist\ClawMemory.exe`
- `onedir`：`dist\ClawMemory\ClawMemory.exe`

### 5.2 `package_release.ps1` 输出

- `release\ClawMemory\`
- `release\ClawMemory-onefile.zip`
- `release\ClawMemory-onedir.zip`

## 6. 打包过程中的注意事项

### 6.1 先看工具链解析结果

`build_exe.ps1` 启动时会打印：

```text
Resolved toolchain:
  cmake -> ...
  gcc -> ...
  g++ -> ...
  mingw32-make -> ...
```

这里非常重要。你需要确认：

- 是不是命中了仓库内工具链
- 还是误用了系统中的旧版 `cmake/gcc/g++`

如果这里打印的还是系统路径，通常说明：

- 仓库内工具链还没解压
- 或者解压失败
- 或者缺少 `gcc.exe/g++.exe`

### 6.2 `onefile` 与 `onedir` 的区别

`onefile`：

- 产物只有一个 `exe`
- 分发更方便
- 运行时会先解包到临时目录
- 更容易被安全软件拦截

`onedir`：

- 输出为目录结构
- 启动更直接
- 排障更容易
- 分发时需要整个目录一起带走

如果你要更稳定地调试或交付，通常更推荐：

```powershell
.\package_release.ps1 -Mode onedir -rebuild
```

### 6.3 不能只复制单个 exe

如果是 `onedir` 模式，不要只复制：

- `ClawMemory.exe`

要复制整个目录：

- `dist\ClawMemory\`

### 6.4 `FileProtectDriver` 会参与运行流程

当前程序启动和退出时会自动调用：

- 启动前：`FileProtectDriver\FilterUpdate.cmd`
- 退出时：`FileProtectDriver\FilterUninstall.cmd`

因此要注意：

- 打包产物中必须包含 `FileProtectDriver`
- 如果这些脚本需要管理员权限，直接双击运行时可能失败

### 6.5 离线环境要点

如果你在离线环境打包，建议优先确认：

- Python 依赖已提前装好
- `go` 已可用
- `PyInstaller` 已可用
- `ov.conf` 已配置正确
- `third_party\mingw64\` 或其压缩包已存在

最适合离线验证的命令是：

```powershell
.\build_exe.ps1 -clean -rebuild
```

### 6.6 没有 `git` 也可以打包

脚本已经支持在没有 `git` 的情况下：

- 从 `openviking\_version.py` 读取版本号
- 自动设置 `setuptools-scm` 的回退版本

因此离线机器不必额外安装 `git`，但要确保：

- `openviking\_version.py` 存在

### 6.7 中文乱码不一定是文档坏了

如果你在 PowerShell 里看到中文文档内容乱码，通常是终端编码问题，不一定是文件内容本身有问题。优先在 IDE 中查看 Markdown 文件。

## 7. 推荐使用方式

### 7.1 本地快速打包

```powershell
.\build_exe.ps1
```

### 7.2 本地完整重建后打包

```powershell
.\build_exe.ps1 -clean -rebuild
```

### 7.3 生成目录版发布包

```powershell
.\package_release.ps1 -Mode onedir -rebuild
```

### 7.4 生成单文件发布包

```powershell
.\package_release.ps1 -rebuild
```

## 8. 相关文件

- `build_exe.ps1`
- `build_exe.bat`
- `package_release.ps1`
- `package_release.bat`
- `packaging_config.ps1`
- `OpenVikingServer.spec`
- `docs\ov-binding-client.example.conf`
