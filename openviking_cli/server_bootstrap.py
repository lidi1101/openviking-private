# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Lightweight entry point for openviking-server.

This module lives outside the ``openviking`` package so that importing it
does NOT trigger ``openviking/__init__.py`` (which eagerly imports clients
and initialises the config singleton via module-level loggers).

The real bootstrap logic stays in ``openviking.server.bootstrap``; we just
pre-parse ``--config`` and set the environment variable before that module
is ever imported.
"""

import os
import subprocess
import sys
from pathlib import Path


def _resolve_driver_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        driver_dir = bundle_root / "FileProtectDriver"
        return driver_dir if driver_dir.exists() else None

    project_root = Path(__file__).resolve().parents[1]
    for candidate in (project_root / "FileProtectDriver", project_root / "protector"):
        if candidate.exists():
            return candidate

    return None


def _run_driver_script(script_name: str, *, required: bool) -> None:
    driver_dir = _resolve_driver_dir()
    if driver_dir is None:
        message = "FileProtectDriver directory not found."
        if required:
            raise RuntimeError(message)
        print(f"[WARN] {message}", file=sys.stderr)
        return

    script_path = driver_dir / script_name
    if not script_path.exists():
        message = f"Driver script not found: {script_path}"
        if required:
            raise RuntimeError(message)
        print(f"[WARN] {message}", file=sys.stderr)
        return

    result = subprocess.run(
        ["cmd.exe", "/c", str(script_path)],
        cwd=str(driver_dir),
        check=False,
    )
    if result.returncode != 0:
        message = f"{script_name} failed with exit code {result.returncode}"
        if required:
            raise RuntimeError(message)
        print(f"[WARN] {message}", file=sys.stderr)


def main():
    # Pre-parse --config from sys.argv before any openviking imports,
    # so the env var is visible when the config singleton first initialises.
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            os.environ["OPENVIKING_CONFIG_FILE"] = sys.argv[i + 1]
            break
        if arg.startswith("--config="):
            os.environ["OPENVIKING_CONFIG_FILE"] = arg.split("=", 1)[1]
            break

    _run_driver_script("FilterUpdate.cmd", required=True)

    try:
        from openviking.server.bootstrap import main as _real_main

        _real_main()
    finally:
        _run_driver_script("FilterUninstall.cmd", required=False)


if __name__ == "__main__":
    main()
