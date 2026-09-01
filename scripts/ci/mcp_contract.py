from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from research_workbench.service import initialize_project


def main() -> int:
    npx = shutil.which("npx.cmd" if sys.platform == "win32" else "npx")
    if not npx:
        raise RuntimeError("npx is required for MCP Inspector")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        project = root / "project"
        initialize_project(project, "MCP contract test")
        config = root / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {"wenjin": {
            "command": sys.executable,
            "args": ["-m", "research_workbench.cli", "mcp-server", str(project)],
            "cwd": str(Path(__file__).resolve().parents[2]),
        }}}, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run([
            npx, "@modelcontextprotocol/inspector", "--cli", "--strict", "--format", "json",
            "--config", str(config), "--server", "wenjin", "--method", "tools/list",
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if completed.returncode:
            sys.stderr.write(completed.stdout + completed.stderr)
            return completed.returncode
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        names = {tool["name"] for tool in payload["result"]["tools"]}
        required = {"project_status", "library_search", "source_list", "source_detail", "manuscript_list", "manuscript_detail"}
        missing = required - names
        if missing:
            raise RuntimeError(f"MCP contract is missing: {sorted(missing)}")
        print(f"MCP contract passed: {len(names)} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
