"""Stream CI output and attach a short diagnostic when a command fails."""

import os
import subprocess
import sys
from collections import deque


def main():
    command = sys.argv[1:]
    if not command:
        raise SystemExit("Usage: ci_check.py COMMAND [ARG ...]")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    recent = deque(maxlen=20)
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          encoding="utf-8", errors="replace", env=env) as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            recent.append(line[-512:])
        status = process.wait()
    if status:
        detail = f"Command exited with status {status}.\n" + "".join(recent).strip()
        detail = detail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"\n::error::{detail}", flush=True)
    return status if status >= 0 else 128 - status


if __name__ == "__main__":
    raise SystemExit(main())
