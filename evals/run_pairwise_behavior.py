#!/usr/bin/env python3
"""Run same-model RED/GREEN response batches in isolated Codex CLI sessions.

This is an explicit evaluation runner. It never scores outputs and never gives
the candidate the rubric, hidden assertions, hard failures, or prior answers.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "blind_cases.json"
FIXTURES_PATH = ROOT / "evals" / "state_fixtures.json"
SCHEMA_PATH = ROOT / "evals" / "batch-candidate-output.schema.json"
RUNS_DIR = ROOT / "docs" / "evaluation" / "runs"
SKILL_PATH = ROOT / ".agents" / "skills" / "real-world-learning-mentor" / "SKILL.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def fixture_map(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("fixtures"), list):
        items = raw["fixtures"]
    elif isinstance(raw, list):
        items = raw
    else:
        return {}
    result: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict):
            key = item.get("fixture_id") or item.get("id") or item.get("name")
            if key:
                result[str(key)] = item
    return result


def candidate_cases() -> list[dict[str, Any]]:
    cases = read_json(CASES_PATH)["cases"]
    fixtures = fixture_map(read_json(FIXTURES_PATH))
    visible: list[dict[str, Any]] = []
    for case in cases:
        item = {
            "case_id": case["case_id"],
            "domain": case["domain"],
            "risk": case["risk"],
            "setup": case["setup"],
            "turns": case["turns"],
        }
        fixture_id = case.get("state_fixture")
        if fixture_id:
            item["provided_state_facts"] = fixtures.get(fixture_id, {"fixture_id": fixture_id})
        visible.append(item)
    return visible


def build_prompt(condition: str, cases: list[dict[str, Any]]) -> str:
    expected_ids = [item["case_id"] for item in cases]
    shared = """
Treat every case as an independent conversation. Produce one assistant response
for each actual user turn; the H case has two user turns and therefore needs two
responses. Do not score, discuss evaluation, or expose hidden reasoning. Each
response should be a natural Chinese answer, concise enough for a real chat but
complete enough to act on. Return only the JSON required by the output schema.
Return exactly one object for every listed case_id, in the given order. Never
duplicate a case object: for H, put both answers inside that one object's
responses array. Do not omit a case.
The following are the only case facts you may use:
""".strip()
    if condition == "red":
        header = """
You are an ordinary conversational assistant in a clean workspace. Do not
search for or use any project-specific learning Skill, learning-state protocol,
rubric, evaluator assertion, hard-failure list, RED summary, or prior candidate.
Respond using your ordinary default behavior.
""".strip()
    else:
        header = """
Use $real-world-learning-mentor from this project to teach or resume these
learning requests. Read its routed references only when needed. Do not read the
project's eval rubric, evaluator assertions, hard-failure list, RED material,
judge reports, or prior candidate outputs. Keep cases independent and do not
write Learner_State; provided state facts are read-only fixtures.
""".strip()
    return (
        f"{header}\n\n{shared}\nExpected case_id order: "
        f"{json.dumps(expected_ids, ensure_ascii=False)}\n\n"
        f"{json.dumps(cases, ensure_ascii=False)}"
    )


def run_batch(
    condition: str,
    batch_index: int,
    cases: list[dict[str, Any]],
    model: str,
    effort: str,
    timeout: int,
) -> dict[str, Any]:
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("codex CLI is not available")
    with tempfile.TemporaryDirectory(prefix=f"rwmentor-{condition}-{batch_index}-") as temp_raw:
        temp = Path(temp_raw)
        output_path = temp / "last-message.json"
        workdir = temp if condition == "red" else ROOT
        command = [
            codex,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--ephemeral",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-c",
            'approval_policy="never"',
            "-s",
            "read-only",
            "-C",
            str(workdir),
            "--output-schema",
            str(SCHEMA_PATH),
            "-o",
            str(output_path),
            "-",
        ]
        started = time.monotonic()
        process = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            input=build_prompt(condition, cases),
            timeout=timeout,
            check=False,
        )
        duration = round(time.monotonic() - started, 3)
        if not output_path.is_file():
            raise RuntimeError(
                f"{condition} produced no output (code={process.returncode}): {process.stderr[-2000:]}"
            )
        output = read_json(output_path)
        returned = output.get("cases") if isinstance(output, dict) else None
        expected_ids = [item["case_id"] for item in cases]
        returned_ids = [item.get("case_id") for item in returned or []]
        if returned_ids != expected_ids:
            raise RuntimeError(
                f"{condition} case IDs differ: expected {expected_ids}, got {returned_ids}"
            )
        for item in returned:
            expected_count = 2 if item["case_id"] == "H-copy-without-explanation" else 1
            if len(item.get("responses", [])) != expected_count:
                raise RuntimeError(
                    f"{condition} {item['case_id']} expected {expected_count} responses"
                )
        return {
            "schema_version": "1.0",
            "run_id": f"pairwise-{condition}-gpt55-batch-{batch_index}",
            "condition": condition,
            "batch_index": batch_index,
            "generated_at_utc": utc_now(),
            "model": model,
            "reasoning_effort": effort,
            "codex_cli": process.args[0],
            "return_code": process.returncode,
            "duration_seconds": duration,
            "skill": None
            if condition == "red"
            else {
                "path": str(SKILL_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": hashlib.sha256(SKILL_PATH.read_bytes()).hexdigest(),
                "invocation": "explicit $real-world-learning-mentor",
            },
            "candidate_protocol": "Candidate saw case/setup/state facts only; evaluation assets and opposite-condition output were hidden.",
            "cases": returned,
            "transport_notes": [
                line
                for line in (process.stderr + "\n" + process.stdout).splitlines()
                if "falling back" in line.lower() or "request timed out" in line.lower()
            ][-20:],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    all_cases = candidate_cases()
    batches = [all_cases[index : index + 6] for index in range(0, len(all_cases), 6)]
    batch_dir = RUNS_DIR / "pairwise_batches"
    tasks: dict[concurrent.futures.Future[dict[str, Any]], tuple[str, int]] = {}
    results: dict[str, list[dict[str, Any]]] = {"red": [], "green": []}
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for condition in ("red", "green"):
            for batch_index, batch in enumerate(batches, start=1):
                batch_path = batch_dir / f"{condition}-{batch_index}.json"
                if batch_path.is_file():
                    existing = read_json(batch_path)
                    expected_ids = [item["case_id"] for item in batch]
                    if [item.get("case_id") for item in existing.get("cases", [])] == expected_ids:
                        results[condition].append(existing)
                        print(
                            json.dumps(
                                {"reused": condition, "batch": batch_index, "cases": len(expected_ids)},
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        continue
                future = pool.submit(
                    run_batch,
                    condition,
                    batch_index,
                    batch,
                    args.model,
                    args.effort,
                    args.timeout,
                )
                tasks[future] = (condition, batch_index)
        for future in concurrent.futures.as_completed(tasks):
            condition, batch_index = tasks[future]
            try:
                result = future.result()
            except Exception as exc:
                errors.append(f"{condition}-{batch_index}: {exc}")
                print(
                    json.dumps(
                        {"failed": condition, "batch": batch_index, "error": str(exc)},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue
            atomic_write(batch_dir / f"{condition}-{batch_index}.json", result)
            results[condition].append(result)
            print(
                json.dumps(
                    {
                        "completed": condition,
                        "batch": batch_index,
                        "cases": len(result["cases"]),
                        "duration": result["duration_seconds"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    if errors:
        raise RuntimeError("batch failures: " + " | ".join(errors))

    merged: dict[str, dict[str, Any]] = {}
    for condition in ("red", "green"):
        ordered = sorted(results[condition], key=lambda item: item["batch_index"])
        merged[condition] = {
            "schema_version": "1.0",
            "run_id": f"pairwise-{condition}-gpt55",
            "condition": condition,
            "generated_at_utc": utc_now(),
            "model": args.model,
            "reasoning_effort": args.effort,
            "skill": ordered[0]["skill"],
            "candidate_protocol": ordered[0]["candidate_protocol"],
            "batch_runs": [item["run_id"] for item in ordered],
            "duration_seconds_total": round(
                sum(item["duration_seconds"] for item in ordered), 3
            ),
            "cases": [case for item in ordered for case in item["cases"]],
            "transport_notes": [note for item in ordered for note in item["transport_notes"]],
        }
    atomic_write(RUNS_DIR / "pairwise-red-gpt55.json", merged["red"])
    atomic_write(RUNS_DIR / "pairwise-green-gpt55.json", merged["green"])
    print(
        json.dumps(
            {
                "ok": True,
                "red_cases": len(merged["red"]["cases"]),
                "green_cases": len(merged["green"]["cases"]),
                "red_duration": merged["red"]["duration_seconds_total"],
                "green_duration": merged["green"]["duration_seconds_total"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
