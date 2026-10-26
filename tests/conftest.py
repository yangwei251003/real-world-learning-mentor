from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "real-world-learning-mentor"
STATE_TOOL = SKILL_ROOT / "scripts" / "state_tool.py"
METHOD_TOOL = SKILL_ROOT / "scripts" / "method_tool.py"


def _json_stream(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise AssertionError("CLI 没有返回 JSON")
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"CLI 输出不是单一 JSON 文档: {stripped[:500]}") from exc
    if not isinstance(value, dict):
        raise AssertionError("CLI 顶层输出必须是 JSON object")
    return value


def run_python_cli(
    script: Path,
    *args: str,
    ok: bool = True,
    timeout: float = 20,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    assert script.is_file(), f"缺少 CLI 脚本: {script.relative_to(ROOT)}"
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    completed = subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if ok:
        assert completed.returncode == 0, completed.stderr or completed.stdout
        payload = _json_stream(completed.stdout)
    else:
        assert completed.returncode != 0, completed.stdout
        payload = _json_stream(completed.stderr or completed.stdout)
    return completed, payload


def run_state(state_dir: Path, *args: str, ok: bool = True, timeout: float = 20):
    return run_python_cli(
        STATE_TOOL,
        "--state-dir",
        str(state_dir),
        *args,
        ok=ok,
        timeout=timeout,
    )


def run_method(*args: str, ok: bool = True, timeout: float = 20):
    return run_python_cli(METHOD_TOOL, *args, ok=ok, timeout=timeout)


def find_revision(payload: dict[str, Any]) -> int:
    candidates: Iterable[Any] = (
        payload.get("revision"),
        payload.get("state", {}).get("revision")
        if isinstance(payload.get("state"), dict)
        else None,
        payload.get("result", {}).get("revision")
        if isinstance(payload.get("result"), dict)
        else None,
    )
    for candidate in candidates:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    raise AssertionError(f"响应中缺少整数 revision: {payload}")


def file_snapshot(directory: Path) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    if not directory.exists():
        return result
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        data = path.read_bytes()
        result[path.relative_to(directory).as_posix()] = (
            path.stat().st_mtime_ns,
            hashlib.sha256(data).hexdigest(),
        )
    return result


@pytest.fixture
def initialized_state(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    state_dir = tmp_path / "学习档案-初始"
    _, initialized = run_state(state_dir, "init")
    return state_dir, initialized

