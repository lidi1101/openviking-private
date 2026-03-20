# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parent / "run_localdb_ingest_query.py"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Post-restart LocalDB re-verification. "
            "This first clears target JSONL outputs, then runs health -> ingest -> wait -> query."
        )
    )
    parser.add_argument(
        "--profile",
        choices=["yoyo", "user_preference", "all"],
        default="all",
        help="Built-in verification profile.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:1933",
        help="OpenViking server base url",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENVIKING_API_KEY"),
        help="API key (or set env OPENVIKING_API_KEY)",
    )
    parser.add_argument(
        "--user-space",
        default="default/default",
        help="User space used for ingest/query APIs",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds passed to /api/v1/system/wait",
    )
    parser.add_argument(
        "--read-limit",
        type=int,
        default=200000,
        help="Byte limit passed to /api/v1/content/read during query verification",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override db_path for single-profile runs",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Override mapping config path for single-profile runs",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Override source for single-profile runs",
    )

    args = parser.parse_args()

    command = [
        sys.executable,
        str(RUNNER_PATH),
        "--profile",
        args.profile,
        "--base-url",
        args.base_url,
        "--user-space",
        args.user_space,
        "--wait-timeout",
        str(args.wait_timeout),
        "--read-limit",
        str(args.read_limit),
        "--reset-output",
        "--ignore-missing",
    ]
    if args.api_key:
        command.extend(["--api-key", args.api_key])
    if args.db_path:
        command.extend(["--db-path", args.db_path])
    if args.config_path:
        command.extend(["--config-path", args.config_path])
    if args.source:
        command.extend(["--source", args.source])

    print("Re-verify command:", flush=True)
    print(" ".join(f'"{part}"' if " " in part else part for part in command), flush=True)
    print("", flush=True)

    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
