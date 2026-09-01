from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory, ZipFile(args.bundle) as archive:
        archive.extractall(directory)
        roots = [path for path in Path(directory).iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise RuntimeError("offline bundle must contain exactly one root directory")
        root = roots[0]
        manifest = json.loads((root / "build-manifest.json").read_text(encoding="utf-8-sig"))
        required = {"install-wenjin.cmd", "双击这里离线安装问津.cmd", "MicrosoftEdgeWebView2RuntimeInstallerX64.exe", "USER_MANUAL_ZH.md", "USER_MANUAL_EN.md"}
        declared = {item["name"] for item in manifest["files"]}
        if required - declared:
            raise RuntimeError(f"offline bundle is missing: {sorted(required - declared)}")
        for item in manifest["files"]:
            path = root / item["name"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.stat().st_size != item["bytes"] or digest != item["sha256"]:
                raise RuntimeError(f"bundle hash mismatch: {item['name']}")
        if args.install:
            completed = subprocess.run([str(root / "install-wenjin.cmd"), "/S"], cwd=root, timeout=600)
            if completed.returncode:
                return completed.returncode
        print(f"Offline bundle verified: {manifest['version']}+{manifest['build_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
