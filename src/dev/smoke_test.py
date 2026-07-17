from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from src.dev.runtime_env import (
    DEFAULT_ENV_FILE,
    LOCAL_TMP_DIR,
    PROJECT_ROOT,
    RuntimeEnvLoadResult,
    env_snapshot,
    load_runtime_env,
)


ENV_KEYS_TO_REPORT = (
    "DATA_DIR",
    "TENCENT_MAP_API_KEY",
    "REAL_DATA_DEMO_MANUAL_TIME_HOURS",
    "REAL_DATA_DEMO_MANUAL_TIME_UNIT",
    "PYTHONPATH",
    "PYTHONIOENCODING",
)


@dataclass(frozen=True)
class StepResult:
    name: str
    status: str
    command: tuple[str, ...] = ()
    duration_seconds: float = 0
    returncode: int | None = None
    note: str = ""


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start = time.perf_counter()
    print_header("Developer Smoke Test")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version.split()[0]}")

    env_result = load_runtime_env(args.env_file)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    print_runtime_env(env_result)

    steps: list[StepResult] = []
    if args.skip_pytest:
        steps.append(StepResult("pytest", "skipped", note="--skip-pytest was set"))
    else:
        steps.append(run_pytest(args.pytest_target))

    if args.skip_real_data:
        steps.append(StepResult("real-data smoke", "skipped", note="--skip-real-data was set"))
    elif _is_true(os.environ.get("SMOKE_RUN_REAL_DATA", "true")):
        steps.append(run_real_data_smoke())
    else:
        steps.append(
            StepResult(
                "real-data smoke",
                "skipped",
                note="SMOKE_RUN_REAL_DATA is false in runtime env.",
            )
        )

    if args.run_tencent or _is_true(os.environ.get("SMOKE_RUN_TENCENT_PROBE", "false")):
        steps.append(run_tencent_probe())
    else:
        steps.append(
            StepResult(
                "Tencent probe",
                "skipped",
                note="Set --run-tencent or SMOKE_RUN_TENCENT_PROBE=true to call Tencent Maps.",
            )
        )

    print_summary(steps, total_seconds=time.perf_counter() - start)
    return 1 if any(step.status == "failed" for step in steps) else 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run developer smoke checks with local env loading.")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Local runtime env CSV. Defaults to local_env/runtime_env.csv.",
    )
    parser.add_argument(
        "--pytest-target",
        action="append",
        default=None,
        help="Pytest target. Can be repeated. Defaults to tests.",
    )
    parser.add_argument("--skip-pytest", action="store_true", help="Skip pytest smoke.")
    parser.add_argument("--skip-real-data", action="store_true", help="Skip real-data smoke.")
    parser.add_argument(
        "--run-tencent",
        action="store_true",
        help="Run Tencent public-place probe when TENCENT_MAP_API_KEY is set.",
    )
    return parser.parse_args(argv)


def run_pytest(targets: list[str] | None) -> StepResult:
    basetemp = LOCAL_TMP_DIR / "pytest"
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    command = (
        sys.executable,
        "-B",
        "-m",
        "pytest",
        *(targets or ["tests"]),
        "-q",
        f"--basetemp={basetemp}",
    )
    return run_command("pytest", command)


def run_real_data_smoke() -> StepResult:
    data_dir = os.environ.get("DATA_DIR")
    if not data_dir:
        return StepResult(
            "real-data smoke",
            "skipped",
            note="DATA_DIR is not set. Fill local_env/runtime_env.csv to enable.",
        )
    if not Path(data_dir).exists():
        return StepResult(
            "real-data smoke",
            "skipped",
            note=f"DATA_DIR does not exist: {data_dir}",
        )
    command = (sys.executable, "-B", "-m", "src.demos.real_data_run")
    return run_command("real-data smoke", command)


def run_tencent_probe() -> StepResult:
    if not os.environ.get("TENCENT_MAP_API_KEY"):
        return StepResult(
            "Tencent probe",
            "skipped",
            note="TENCENT_MAP_API_KEY is not set.",
        )
    command = (sys.executable, "-B", "-m", "src.demos.tencent_map_probe")
    return run_command("Tencent probe", command)


def run_command(name: str, command: tuple[str, ...]) -> StepResult:
    print_header(name)
    print("Command:")
    print("  " + " ".join(command))
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    duration = time.perf_counter() - started
    if completed.stdout:
        print("\nstdout:")
        print(completed.stdout.rstrip())
    if completed.stderr:
        print("\nstderr:")
        print(completed.stderr.rstrip())
    status = "passed" if completed.returncode == 0 else "failed"
    print(f"\n{name} status: {status}; returncode={completed.returncode}; seconds={duration:.2f}")
    return StepResult(
        name=name,
        status=status,
        command=command,
        duration_seconds=duration,
        returncode=completed.returncode,
    )


def print_runtime_env(result: RuntimeEnvLoadResult) -> None:
    print_header("Runtime Environment")
    print(f"Runtime env file: {result.env_file}")
    print(f"Using example template: {result.used_example}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")
    print(f"Loaded entries: {result.loaded_count}; skipped empty optional entries: {result.skipped_count}")
    if result.entries:
        print("Entries:")
        for entry in result.entries:
            print(
                f"  - {entry.key}: status={entry.status}; required={entry.required}; "
                f"value={entry.display_value}; note={entry.display_note}"
            )
    if result.missing_required:
        print("Missing required entries:")
        for entry in result.missing_required:
            print(f"  - {entry.key}: {entry.message}")
    print("Environment snapshot:")
    for key, value in env_snapshot(ENV_KEYS_TO_REPORT).items():
        print(f"  - {key}: {value}")


def print_summary(steps: list[StepResult], *, total_seconds: float) -> None:
    print_header("Summary")
    for step in steps:
        if step.status == "skipped":
            print(f"- {step.name}: skipped; {step.note}")
        else:
            print(
                f"- {step.name}: {step.status}; returncode={step.returncode}; "
                f"seconds={step.duration_seconds:.2f}"
            )
    passed = sum(1 for step in steps if step.status == "passed")
    skipped = sum(1 for step in steps if step.status == "skipped")
    failed = sum(1 for step in steps if step.status == "failed")
    print(f"Totals: passed={passed}; skipped={skipped}; failed={failed}; seconds={total_seconds:.2f}")


def print_header(title: str) -> None:
    print("")
    print("=" * 72)
    print(title)
    print("=" * 72)


def _is_true(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


if __name__ == "__main__":
    raise SystemExit(main())
