"""ov 命令的极简 Python 包装器

设计原则：
1. 职责单一：仅负责查找二进制并 execv
2. 无网络依赖：不实现下载功能
3. 极简代码：尽可能减少启动开销
4. 快速失败：找不到立即提示用户

性能说明：
- Python 虚拟机启动 + 导入基础模块：约 30-50ms
- 一旦 execv 执行，后续为纯 Rust 二进制，零开销

Rust CLI 独立发布能力完全保留，用户可通过以下方式获取：
- 官方安装脚本（零开销）
- GitHub Releases 手动下载（零开销）
- cargo install（零开销）
- 包管理器（未来）
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import which


DLL_NOT_FOUND_EXIT_CODE = 0xC0000135
PYTHON_FALLBACK_COMMANDS = {"build-index", "summarize"}


def _extract_option(args: list[str], name: str) -> tuple[bool, list[str]]:
    remaining: list[str] = []
    found = False
    for arg in args:
        if arg == name:
            found = True
            continue
        remaining.append(arg)
    return found, remaining


def _extract_option_value(args: list[str], name: str) -> tuple[str | None, list[str]]:
    remaining: list[str] = []
    value: str | None = None
    skip_next = False

    for idx, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue

        if arg == name:
            if idx + 1 >= len(args):
                raise SystemExit(f"Error: {name} requires a value")
            value = args[idx + 1]
            skip_next = True
            continue

        if arg.startswith(f"{name}="):
            value = arg.split("=", 1)[1]
            continue

        remaining.append(arg)

    return value, remaining


def _python_http_fallback(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in PYTHON_FALLBACK_COMMANDS:
        return -1

    command = argv[1]
    args = argv[2:]

    wait, args = _extract_option(args, "--wait")
    no_vectorize, args = _extract_option(args, "--no-vectorize")
    compact, args = _extract_option(args, "--compact")
    timeout_str, args = _extract_option_value(args, "--timeout")
    output_format, args = _extract_option_value(args, "--output")

    if command == "build-index" and no_vectorize:
        raise SystemExit("Error: --no-vectorize is only valid for 'ov summarize'")

    resource_uris = [arg for arg in args if not arg.startswith("-")]
    if not resource_uris:
        raise SystemExit(f"Error: 'ov {command}' requires at least one resource URI")

    timeout = float(timeout_str) if timeout_str else None

    from openviking_cli.client.sync_http import SyncHTTPClient

    client = SyncHTTPClient()
    client.initialize()
    try:
        if command == "build-index":
            result = client.build_index(resource_uris, wait=wait, timeout=timeout)
        else:
            result = client.summarize(
                resource_uris,
                wait=wait,
                timeout=timeout,
                skip_vectorization=no_vectorize,
            )
    finally:
        client.close()

    if output_format == "json":
        if compact:
            print(
                json.dumps(
                    {"ok": True, "result": result},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0


def _candidate_runtime_dirs() -> list[str]:
    candidates: list[str] = []

    env_path = os.environ.get("PATH", "")
    path_entries = env_path.split(os.pathsep) if env_path else []

    gcc_path = which("gcc")
    if gcc_path:
        candidates.append(str(Path(gcc_path).resolve().parent))

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        candidates.extend(
            [
                str(Path(conda_prefix) / "Library" / "mingw-w64" / "bin"),
                str(Path(conda_prefix) / "Library" / "bin"),
                str(Path(conda_prefix) / "Scripts"),
            ]
        )

    candidates.extend(
        [
            r"C:\msys64\ucrt64\bin",
            r"C:\msys64\mingw64\bin",
        ]
    )

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        normalized_candidate = str(candidate_path)
        if (
            candidate_path.exists()
            and normalized_candidate not in seen
            and normalized_candidate not in path_entries
        ):
            seen.add(normalized_candidate)
            normalized.append(normalized_candidate)
    return normalized


def _run_native_binary(binary_path: Path) -> int:
    args = [str(binary_path)] + sys.argv[1:]
    child_env = os.environ.copy()
    extra_runtime_dirs = _candidate_runtime_dirs()
    if extra_runtime_dirs:
        child_env["PATH"] = os.pathsep.join(extra_runtime_dirs + [child_env.get("PATH", "")])

    if sys.platform == "win32":
        exit_code = subprocess.call(args, env=child_env)
        if exit_code == DLL_NOT_FOUND_EXIT_CODE:
            print(
                "错误: ov.exe 启动失败，缺少 GNU 运行时 DLL。"
                "请重新激活 conda 环境，或确认以下目录在 PATH 中: "
                "C:\\msys64\\ucrt64\\bin / C:\\msys64\\mingw64\\bin / %CONDA_PREFIX%\\Library\\mingw-w64\\bin",
                file=sys.stderr,
            )
        return exit_code
    os.execv(str(binary_path), args)
    return 0


def _is_self_binary(candidate_path: Path) -> bool:
    if not sys.argv or not sys.argv[0]:
        return False
    try:
        return candidate_path == Path(sys.argv[0]).resolve()
    except Exception:
        return False


def main():
    """
    极简入口点：查找 ov 二进制并执行

    按优先级查找：
    0. ./target/release/ov（开发环境）
    1. Wheel 自带：{package_dir}/openviking/bin/ov
    2. PATH 查找：系统全局安装的 ov
    """
    # 0. 检查开发环境（仅在直接运行脚本时有效）
    fallback_exit_code = _python_http_fallback(sys.argv)
    if fallback_exit_code >= 0:
        return fallback_exit_code

    try:
        # __file__ is openviking_cli/rust_cli.py, so parent is openviking_cli directory
        dev_binary = Path(__file__).parent.parent / "target" / "release" / "ov"
        if dev_binary.exists() and os.access(dev_binary, os.X_OK):
            return _run_native_binary(dev_binary)
    except Exception:
        pass

    # 1. 检查 Wheel 自带（不导入 openviking，避免额外开销）
    try:
        # __file__ is openviking_cli/rust_cli.py, so parent is openviking_cli directory
        package_dir = Path(__file__).parent.parent / "openviking"
        package_bin = package_dir / "bin"
        for binary_name in ["ov", "ov.exe"]:
            binary = package_bin / binary_name
            if binary.exists() and os.access(binary, os.X_OK):
                return _run_native_binary(binary)
    except Exception:
        pass

    # 2. 检查 PATH，但跳过当前 Python 脚本
    path_binary = which("ov")
    if path_binary:
        # 检查文件是否是 Python 脚本（避免无限循环）
        try:
            candidate_path = Path(path_binary).resolve()
            if not _is_self_binary(candidate_path):
                with open(candidate_path, "rb") as f:
                    first_bytes = f.read(2)
                # Skip if it starts with #! (shebang, likely Python script)
                if first_bytes != b"#!":
                    return _run_native_binary(candidate_path)
        except Exception:
            pass

    # 都找不到，提示用户
    print(
        """错误: 未找到 ov 二进制文件。

        请选择以下方式之一安装：

        1. 使用预构建 wheel（推荐）：
   pip install openviking --upgrade --force-reinstall

        2. 使用官方安装脚本（零 Python 开销）：
   curl -fsSL https://raw.githubusercontent.com/volcengine/OpenViking/main/crates/ov_cli/install.sh | bash

        3. 从 GitHub Releases 下载（零 Python 开销）：
   https://github.com/volcengine/OpenViking/releases

        4. 从源码构建（零 Python 开销）：
   cargo install --git https://github.com/volcengine/OpenViking ov_cli""",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
