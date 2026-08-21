from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_TASK_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _codex_executable() -> str | None:
    for name in ("codex.cmd", "codex.exe", "codex"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    return None


def _codex_command_prefix() -> list[str]:
    executable = _codex_executable()
    if not executable:
        return []
    path = Path(executable)
    if path.suffix.casefold() in {".cmd", ".bat"}:
        node = shutil.which("node.exe") or shutil.which("node")
        script = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if node and script.is_file():
            return [node, str(script)]
    return [executable]


def _wenjin_mcp_command(project_root: Path, library_root: Path | None = None) -> list[str]:
    if getattr(sys, "frozen", False):
        command = [sys.executable, "mcp-server", str(project_root.resolve())]
    else:
        command = [
            sys.executable, "-m", "research_workbench.cli", "mcp-server",
            str(project_root.resolve()),
        ]
    if library_root:
        command.extend(["--library-root", str(library_root.resolve())])
    return command


def codex_capability(project_root: Path, library_root: Path | None = None) -> dict[str, Any]:
    prefix = _codex_command_prefix()
    executable = _codex_executable()
    command = _wenjin_mcp_command(project_root, library_root)
    return {
        "installed": bool(prefix),
        "executable": str(Path(executable).resolve()) if executable else "",
        "inbound_mode": "wenjin_mcp_stdio",
        "outbound_mode": "codex_exec_jsonl",
        "mcp_server_command": command,
        "boundary": (
            "Codex uses Wenjin's MCP server to read qualified project objects. Wenjin starts Codex "
            "only after an explicit user action and never reads Codex credentials."
        ),
    }


def _registration_name(project_root: Path) -> str:
    digest = hashlib.sha256(str(project_root.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"wenjin-{digest}"


def register_with_codex(
    project_root: Path,
    library_root: Path | None = None,
    *,
    name: str = "",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    prefix = _codex_command_prefix()
    if not prefix:
        raise RuntimeError("Codex CLI is not installed or not available on PATH")
    server_name = name.strip() or _registration_name(project_root)
    existing = runner(
        [*prefix, "mcp", "get", server_name], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=20,
    )
    if existing.returncode == 0:
        return {"status": "already_registered", "name": server_name}
    command = [*prefix, "mcp", "add", server_name, "--", *_wenjin_mcp_command(project_root, library_root)]
    result = runner(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Codex MCP registration failed").strip())
    return {"status": "registered", "name": server_name, "server_command": _wenjin_mcp_command(project_root, library_root)}


def build_codex_exec_command(
    project_root: Path,
    output_file: Path,
    *,
    sandbox: str = "read-only",
) -> list[str]:
    if sandbox not in {"read-only", "workspace-write"}:
        raise ValueError("Codex task sandbox must be read-only or workspace-write")
    prefix = _codex_command_prefix()
    if not prefix:
        raise RuntimeError("Codex CLI is not installed or not available on PATH")
    return [
        *prefix, "-a", "never", "exec", "--json", "--skip-git-repo-check", "-s", sandbox,
        "-C", str(project_root.resolve()), "-o", str(output_file.resolve()), "-",
    ]


def _task_root(project_root: Path) -> Path:
    return project_root.resolve() / "runtime" / "codex_tasks"


def _task_receipt(project_root: Path, task_id: str) -> Path:
    if not task_id.startswith("CDX_") or any(value in task_id for value in ("/", "\\", "..")):
        raise ValueError("invalid Codex task id")
    return _task_root(project_root) / task_id / "task.json"


def codex_task_status(project_root: Path, task_id: str) -> dict[str, Any]:
    receipt_path = _task_receipt(project_root, task_id)
    if not receipt_path.is_file():
        raise KeyError(f"unknown Codex task: {task_id}")
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    final_path = receipt_path.parent / "final.txt"
    if final_path.is_file():
        value["final_message"] = final_path.read_text(encoding="utf-8", errors="replace")[-30000:]
    return value


def _run_codex_task(
    project_root: Path,
    task_id: str,
    prompt: str,
    sandbox: str,
    timeout_seconds: int,
) -> None:
    receipt_path = _task_receipt(project_root, task_id)
    task_dir = receipt_path.parent
    stdout_path, stderr_path, final_path = (
        task_dir / "events.jsonl", task_dir / "stderr.log", task_dir / "final.txt"
    )
    command = build_codex_exec_command(project_root, final_path, sandbox=sandbox)
    receipt = codex_task_status(project_root, task_id)
    receipt.update({"status": "running", "started_at": _now()})
    _atomic_json(receipt_path, receipt)
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=project_root.resolve(),
                env=os.environ.copy(),
            )
            try:
                process.communicate(prompt, timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
                raise TimeoutError(f"Codex task exceeded {timeout_seconds} seconds")
        receipt.update({
            "status": "completed" if process.returncode == 0 else "failed",
            "exit_code": process.returncode,
            "completed_at": _now(),
            "events_path": stdout_path.relative_to(project_root.resolve()).as_posix(),
            "stderr_path": stderr_path.relative_to(project_root.resolve()).as_posix(),
            "final_path": final_path.relative_to(project_root.resolve()).as_posix(),
        })
    except Exception as error:
        receipt.update({"status": "failed", "error": str(error), "completed_at": _now()})
    _atomic_json(receipt_path, receipt)


def start_codex_task(
    project_root: Path,
    prompt: str,
    *,
    sandbox: str = "read-only",
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Codex task prompt is required")
    if len(prompt) > 20000:
        raise ValueError("Codex task prompt is limited to 20000 characters")
    if timeout_seconds < 30 or timeout_seconds > 7200:
        raise ValueError("Codex task timeout must be between 30 and 7200 seconds")
    _ = build_codex_exec_command(project_root, _task_root(project_root) / "probe.txt", sandbox=sandbox)
    task_id = f"CDX_{uuid.uuid4().hex}"
    receipt_path = _task_receipt(project_root, task_id)
    receipt = {
        "task_id": task_id,
        "status": "queued",
        "sandbox": sandbox,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_preview": prompt[:300],
        "created_at": _now(),
        "timeout_seconds": timeout_seconds,
    }
    _atomic_json(receipt_path, receipt)
    thread = threading.Thread(
        target=_run_codex_task,
        args=(project_root.resolve(), task_id, prompt, sandbox, timeout_seconds),
        daemon=True,
        name=f"wenjin-{task_id}",
    )
    with _TASK_LOCK:
        thread.start()
    return receipt
