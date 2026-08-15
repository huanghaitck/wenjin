from __future__ import annotations

import argparse
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # PyInstaller one-file executables use a parent/child process pair. A
        # plain terminate() only stops the bootloader and leaves the extracted
        # service running, which also keeps the source executable locked.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sidecar", type=Path)
    args = parser.parse_args()
    sidecar = args.sidecar.resolve()
    if not sidecar.is_file():
        raise FileNotFoundError(sidecar)
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="wenjin-sidecar-smoke-") as directory:
        process = subprocess.Popen(
            [str(sidecar), "desktop-serve", "--data-root", directory, "--host", "127.0.0.1", "--port", str(port), "--desktop-build", "smoke"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 30
            last_error = ""
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=2)
                    raise RuntimeError(f"sidecar exited during smoke test\nstdout:\n{stdout}\nstderr:\n{stderr}")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                        if response.status == 200 and b'"status": "ok"' in response.read():
                            return 0
                except Exception as exc:
                    last_error = str(exc)
                time.sleep(0.1)
            raise TimeoutError(f"sidecar health check timed out: {last_error}")
        finally:
            terminate_process_tree(process)


if __name__ == "__main__":
    raise SystemExit(main())
