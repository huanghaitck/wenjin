from __future__ import annotations

import hashlib
import json
import os
from collections import deque
import shutil
import subprocess
import sys
import tempfile
import uuid
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings(
    "ignore",
    message="Field 'lifespan' has an incomplete definition.*",
)

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from PIL import ImageGrab
import uiautomation as automation


server = FastMCP("wenjin-computer-use")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
ACT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
EXEC = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)


def _working_executable(candidates: list[Path | str], *version_args: str) -> dict[str, Any] | None:
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate)
        resolved = shutil.which(value) if not Path(value).is_absolute() else value
        if not resolved or resolved.casefold() in seen:
            continue
        seen.add(resolved.casefold())
        path = Path(resolved)
        try:
            if not path.is_file() or path.stat().st_size == 0:
                continue
            completed = subprocess.run(
                [str(path), *version_args], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            version = (completed.stdout or completed.stderr).strip().splitlines()
            return {"path": str(path.resolve()), "version": version[0] if version else "available"}
    return None


def _python_candidates() -> list[Path | str]:
    values: list[Path | str] = []
    if os.environ.get("WENJIN_PYTHON"):
        values.append(os.environ["WENJIN_PYTHON"])
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    values.extend(sorted((appdata / "uv/python").glob("*/python.exe"), reverse=True))
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    values.extend(sorted((local / "Programs/Python").glob("*/python.exe"), reverse=True))
    values.extend(["python.exe", "python3.exe"])
    return values


def _powershell_candidates() -> list[Path | str]:
    values: list[Path | str] = []
    if os.environ.get("WENJIN_PWSH"):
        values.append(os.environ["WENJIN_PWSH"])
    values.extend([
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PowerShell/7/pwsh.exe",
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Microsoft/PowerShell/7/pwsh.exe",
        "pwsh.exe",
    ])
    return values


def _rect(control: Any) -> dict[str, int]:
    value = control.BoundingRectangle
    return {
        "left": int(value.left), "top": int(value.top),
        "right": int(value.right), "bottom": int(value.bottom),
        "width": int(value.width()), "height": int(value.height()),
    }


def _node(control: Any, reference: str) -> dict[str, Any]:
    password = bool(getattr(control, "IsPassword", False))
    return {
        "ref": reference,
        "name": "[password]" if password else str(getattr(control, "Name", ""))[:300],
        "control_type": str(getattr(control, "ControlTypeName", "")),
        "automation_id": str(getattr(control, "AutomationId", ""))[:300],
        "window_handle": int(getattr(control, "NativeWindowHandle", 0) or 0),
        "enabled": bool(getattr(control, "IsEnabled", False)),
        "offscreen": bool(getattr(control, "IsOffscreen", False)),
        "password": password,
        "rect": _rect(control),
    }


def _walk(control: Any, reference: str, depth: int, limit: int, output: list[dict[str, Any]]) -> None:
    if len(output) >= limit:
        return
    output.append(_node(control, reference))
    if depth <= 0:
        return
    for index, child in enumerate(control.GetChildren()):
        if len(output) >= limit:
            break
        _walk(child, f"{reference}.{index}", depth - 1, limit, output)


def _resolve(reference: str) -> Any:
    parts = reference.split(".")
    if not parts or not parts[0].startswith("w"):
        raise ValueError("computer control ref must start with a window handle")
    try:
        control = automation.ControlFromHandle(int(parts[0][1:]))
        for part in parts[1:]:
            control = control.GetChildren()[int(part)]
    except (ValueError, IndexError, OSError) as error:
        raise ValueError("computer control ref is stale; take a new desktop snapshot") from error
    return control


@server.tool(annotations=READ)
def computer_status() -> dict[str, Any]:
    """Return the bounded Windows Computer Use backend status."""
    return {
        "backend": "Windows UI Automation",
        "screen_width": automation.GetScreenSize()[0],
        "screen_height": automation.GetScreenSize()[1],
        "process_id": os.getpid(),
    }


@server.tool(annotations=READ)
def runtime_status() -> dict[str, Any]:
    """Report Wenjin's self-contained backend and optional local script runtimes."""
    python = _working_executable(_python_candidates(), "--version")
    powershell = _working_executable(_powershell_candidates(), "--version")
    return {
        "wenjin_backend": {
            "available": True,
            "self_contained": bool(getattr(sys, "frozen", False)),
            "executable": str(Path(sys.executable).resolve()),
            "note": "Core Wenjin and self-contained Domain Agent tools do not require system Python or PowerShell.",
        },
        "optional_script_runtimes": {
            "python": python or {"available": False},
            "powershell7": powershell or {"available": False},
        },
        "repairable_components": [
            name for name, value in (("python", python), ("powershell7", powershell)) if value is None
        ],
        "boundary": "Optional runtimes are needed only for explicit external scripts, not for packaged Wenjin or Domain Agent tools.",
    }


@server.tool(annotations=EXEC)
def repair_runtime(component: str) -> dict[str, Any]:
    """Install an optional Python or PowerShell runtime with winget after permission approval."""
    component = component.strip().casefold()
    current = runtime_status()
    if component == "python" and current["optional_script_runtimes"]["python"].get("path"):
        return {"changed": False, "status": current}
    if component in {"powershell", "powershell7", "pwsh"} and current["optional_script_runtimes"]["powershell7"].get("path"):
        return {"changed": False, "status": current}
    winget = shutil.which("winget.exe") or shutil.which("winget")
    if not winget:
        raise RuntimeError("Windows Package Manager is unavailable; install the optional runtime manually or use packaged tools")
    package = "Python.Python.3.13" if component == "python" else "Microsoft.PowerShell" if component in {"powershell", "powershell7", "pwsh"} else ""
    if not package:
        raise ValueError("component must be python or powershell7")
    completed = subprocess.run(
        [winget, "install", "--id", package, "--exact", "--silent",
         "--accept-package-agreements", "--accept-source-agreements"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "runtime installation failed")[-4000:])
    return {"changed": True, "component": component, "status": runtime_status()}


@server.tool(annotations=READ)
def window_list(limit: int = 50) -> dict[str, Any]:
    """List visible top-level desktop windows without reading password values."""
    windows = []
    for control in automation.GetRootControl().GetChildren():
        if control.IsOffscreen or not control.Name:
            continue
        windows.append(_node(control, f"w{int(control.NativeWindowHandle)}"))
        if len(windows) >= max(1, min(limit, 100)):
            break
    return {"windows": windows, "count": len(windows)}


@server.tool(annotations=READ)
def desktop_snapshot(window_handle: int = 0, depth: int = 4, limit: int = 250) -> dict[str, Any]:
    """Return a bounded accessibility tree for one window or all top-level windows."""
    depth, limit = max(0, min(depth, 8)), max(1, min(limit, 1000))
    controls: list[dict[str, Any]] = []
    if window_handle:
        root = automation.ControlFromHandle(window_handle)
        _walk(root, f"w{window_handle}", depth, limit, controls)
    else:
        for root in automation.GetRootControl().GetChildren():
            if root.IsOffscreen or not root.Name:
                continue
            _walk(root, f"w{int(root.NativeWindowHandle)}", min(depth, 2), limit, controls)
            if len(controls) >= limit:
                break
    return {"controls": controls, "count": len(controls), "truncated": len(controls) >= limit}


@server.tool(annotations=READ)
def screen_capture() -> dict[str, Any]:
    """Capture the current desktop to a local PNG and return its identity."""
    target = Path(tempfile.gettempdir()) / "wenjin-computer-use" / "screenshots"
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"screen-{uuid.uuid4().hex}.png"
    image = ImageGrab.grab(all_screens=True)
    image.save(path, "PNG")
    data = path.read_bytes()
    return {
        "path": str(path), "width": image.width, "height": image.height,
        "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
    }


@server.tool(annotations=READ)
def filesystem_roots() -> dict[str, Any]:
    """List available local drive roots and common user folders without enumerating their contents."""
    drives = [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]
    user = Path.home()
    common = []
    for name in ("Desktop", "Documents", "Downloads"):
        path = user / name
        if path.is_dir():
            common.append({"name": name, "path": str(path.resolve())})
    common.insert(0, {"name": "User home", "path": str(user.resolve())})
    for drive in drives:
        root = Path(drive)
        for name in (user.name, "AI_Workflows"):
            path = root / name
            if path.is_dir() and str(path.resolve()) not in {item["path"] for item in common}:
                common.append({"name": f"{root.drive} {name}", "path": str(path.resolve())})
    return {"drives": drives, "common_folders": common}


@server.tool(annotations=READ)
def file_search(
    roots: list[str], query: str = "", extensions: list[str] | None = None,
    max_results: int = 200, max_scanned: int = 50000, include_hidden: bool = False,
) -> dict[str, Any]:
    """Search explicitly named local folders with bounded traversal and no file-content reads."""
    if not roots or len(roots) > 8:
        raise ValueError("roots must contain 1-8 explicit folders")
    selected = []
    for value in roots:
        path = Path(value).expanduser().resolve()
        if not path.is_absolute() or not path.is_dir():
            raise FileNotFoundError(f"search root is unavailable: {path}")
        selected.append(path)
    needle = query.strip().casefold()
    suffixes = {
        value.casefold() if value.startswith(".") else "." + value.casefold()
        for value in (extensions or []) if value.strip()
    }
    max_results = max(1, min(int(max_results), 500))
    max_scanned = max(1, min(int(max_scanned), 200000))
    matches: list[dict[str, Any]] = []
    scanned = 0
    skipped = 0
    priority = [Path(item["path"]) for item in filesystem_roots()["common_folders"]]
    queue = deque([path for path in priority if any(path == root or root in path.parents for root in selected)] + selected)
    visited: set[Path] = set()
    while queue and scanned < max_scanned and len(matches) < max_results:
        directory = queue.popleft()
        if directory in visited:
            continue
        visited.add(directory)
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except (OSError, PermissionError):
            skipped += 1
            continue
        directories: list[Path] = []
        for entry in entries:
            if scanned >= max_scanned or len(matches) >= max_results:
                break
            if not include_hidden and entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    directories.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                scanned += 1
                path = Path(entry.path)
                if suffixes and path.suffix.casefold() not in suffixes:
                    continue
                if needle and needle not in entry.name.casefold() and needle not in str(path.parent).casefold():
                    continue
                stat = entry.stat(follow_symlinks=False)
                matches.append({
                    "name": entry.name, "path": str(path.resolve()),
                    "extension": path.suffix.casefold(), "size": stat.st_size,
                    "modified_ns": stat.st_mtime_ns,
                })
            except (OSError, PermissionError):
                skipped += 1
        priority_terms = ("wechat", "wx", "download", "document", "desktop", "project", "research", "msg", "file", "资料", "文档", "下载", "桌面", "项目")
        for child in reversed(directories):
            if any(term in child.name.casefold() for term in priority_terms):
                queue.appendleft(child)
            else:
                queue.append(child)
    return {
        "roots": [str(path) for path in selected], "query": query,
        "extensions": sorted(suffixes), "matches": matches,
        "returned_count": len(matches), "scanned_files": scanned,
        "skipped_entries": skipped,
        "truncated": bool(queue) or scanned >= max_scanned or len(matches) >= max_results,
        "boundary": "File names and metadata only; file contents were not opened.",
    }


@server.tool(annotations=ACT)
def focus_control(ref: str) -> dict[str, Any]:
    """Focus a control from the latest accessibility snapshot."""
    control = _resolve(ref)
    control.SetFocus()
    return {"focused": True, "control": _node(control, ref)}


@server.tool(annotations=ACT)
def click_control(ref: str) -> dict[str, Any]:
    """Click a control from the latest accessibility snapshot."""
    control = _resolve(ref)
    control.Click()
    return {"clicked": True, "control": _node(control, ref)}


@server.tool(annotations=ACT)
def click_coordinates(x: int, y: int, button: str = "left") -> dict[str, Any]:
    """Click visible screen coordinates."""
    if button not in {"left", "right"}:
        raise ValueError("button must be left or right")
    if button == "left":
        automation.Click(x, y)
    else:
        automation.RightClick(x, y)
    return {"clicked": True, "x": x, "y": y, "button": button}


@server.tool(annotations=ACT)
def type_text(ref: str, text: str) -> dict[str, Any]:
    """Focus a non-password control and enter Unicode text."""
    control = _resolve(ref)
    if bool(getattr(control, "IsPassword", False)):
        raise ValueError("Computer Use never enters password controls")
    control.SetFocus()
    control.SendKeys(text, waitTime=0.01)
    return {"typed": True, "characters": len(text), "control": _node(control, ref)}


@server.tool(annotations=ACT)
def press_keys(keys: str) -> dict[str, Any]:
    """Send a uiautomation key sequence to the currently focused control."""
    if not keys or len(keys) > 200:
        raise ValueError("keys must contain 1-200 characters")
    automation.SendKeys(keys, waitTime=0.01)
    return {"sent": True, "keys": keys}


@server.tool(annotations=EXEC)
def launch_program(executable: str, args: list[str] | None = None, cwd: str = "") -> dict[str, Any]:
    """Launch one explicit executable without invoking a shell."""
    path = Path(executable).expanduser().resolve()
    if not path.is_file() or path.suffix.casefold() not in {".exe", ".com", ".bat", ".cmd"}:
        raise FileNotFoundError("executable is unavailable or unsupported")
    process = subprocess.Popen([str(path), *(args or [])], cwd=cwd or None)
    return {"launched": True, "process_id": process.pid, "executable": str(path)}


@server.tool(annotations=EXEC)
def run_command(executable: str, args: list[str] | None = None, cwd: str = "", timeout: int = 120) -> dict[str, Any]:
    """Run one explicit executable without shell expansion and return bounded output."""
    path = Path(executable).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("executable is unavailable")
    completed = subprocess.run(
        [str(path), *(args or [])], cwd=cwd or None, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=max(1, min(timeout, 1800)),
    )
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-20000:], "stderr": completed.stderr[-10000:],
        "executable": str(path),
    }


def main() -> None:
    server.run(transport="stdio")
