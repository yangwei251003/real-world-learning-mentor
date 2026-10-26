from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_TOOL = ROOT / ".agents" / "skills" / "real-world-learning-mentor" / "scripts" / "state_tool.py"
FIXTURES = Path(__file__).with_name("state_fixtures.json")


class FixtureError(RuntimeError):
    pass


def load_fixtures() -> dict[str, dict[str, Any]]:
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return {item["fixture_id"]: item for item in payload["fixtures"]}


def run_tool(state_dir: Path, *args: str) -> dict[str, Any]:
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    completed = subprocess.run(
        [sys.executable, str(STATE_TOOL), "--state-dir", str(state_dir), *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise FixtureError(completed.stderr.strip() or completed.stdout.strip())
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise FixtureError("state tool returned non-object JSON")
    return value


def ensure_new_target(state_dir: Path) -> None:
    if state_dir.exists() and any(state_dir.iterdir()):
        raise FixtureError("state-dir must be absent or empty; fixture builder never overwrites existing state")


def build_valid(fixture: dict[str, Any], state_dir: Path) -> int:
    initialized = run_tool(state_dir, "init")
    revision = int(initialized["revision"])
    for index, operation in enumerate(fixture["operations"], start=1):
        command = operation["command"]
        key = f"fixture-{fixture['fixture_id']}-{index}"
        if command == "begin":
            args = [
                "begin", "--track-id", operation["track_id"],
                "--goal", operation["goal"],
                "--authentic-outcome", operation["authentic_outcome"],
                "--primary-adapter", operation["primary_adapter"],
                "--mvc", operation["mvc"],
                "--expected-revision", str(revision), "--idempotency-key", key,
            ]
            for option, field in (("--secondary-adapter", "secondary_adapter"), ("--next-action", "next_action")):
                if operation.get(field):
                    args += [option, operation[field]]
        elif command == "record":
            args = [
                "record", "--track-id", operation["track_id"],
                "--event-type", operation["event_type"],
                "--payload", json.dumps(operation["payload"], ensure_ascii=False),
                "--expected-revision", str(revision), "--idempotency-key", key,
            ]
        elif command == "finish":
            args = [
                "finish", "--track-id", operation["track_id"],
                "--outcome", operation["outcome"], "--summary", operation["summary"],
                "--expected-revision", str(revision), "--idempotency-key", key,
            ]
        else:  # protected by repository tests
            raise FixtureError(f"unsupported fixture command: {command}")
        result = run_tool(state_dir, *args)
        revision = int(result["revision"])
    run_tool(state_dir, "validate")
    return revision


def inject_fault(fixture: dict[str, Any], state_dir: Path) -> None:
    fault = fixture["fault_injection"]
    target = state_dir / fault["target"]
    if target.resolve().parent != state_dir.resolve():
        raise FixtureError("fault target must be a direct child of state-dir")
    value = json.loads(target.read_text(encoding="utf-8"))
    cursor: Any = value
    pointer = fault["json_pointer"]
    if not isinstance(pointer, list) or not pointer:
        raise FixtureError("fault json_pointer must be a non-empty array")
    for key in pointer[:-1]:
        cursor = cursor[key]
    cursor[pointer[-1]] = fault["value"]
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_fixture(fixture_id: str, state_dir: Path) -> dict[str, Any]:
    fixtures = load_fixtures()
    if fixture_id not in fixtures:
        raise FixtureError(f"unknown fixture_id: {fixture_id}")
    ensure_new_target(state_dir)
    fixture = fixtures[fixture_id]
    if fixture["kind"] == "fault-injection":
        base = fixtures[fixture["base_fixture"]]
        revision = build_valid(base, state_dir)
        inject_fault(fixture, state_dir)
        return {"ok": True, "fixture_id": fixture_id, "revision": revision, "integrity": "intentionally-invalid"}
    revision = build_valid(fixture, state_dir)
    return {"ok": True, "fixture_id": fixture_id, "revision": revision, "integrity": "valid"}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build an isolated blind-test learner-state fixture")
    parser.add_argument("fixture_id")
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_fixture(args.fixture_id, args.state_dir.resolve())
    except (FixtureError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
