from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / "local_env" / "runtime_env.csv"
EXAMPLE_ENV_FILE = PROJECT_ROOT / "config" / "runtime_env.example.csv"
LOCAL_TMP_DIR = PROJECT_ROOT / "local_env" / ".tmp"
PATH_LIKE_KEYS = {
    "DATA_DIR",
    "PYTHONPATH",
    "DATA_AUDIT_REPORT_PATH",
    "DATA_QUALITY_SUMMARY_PATH",
}
SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
TRUE_VALUES = {"1", "true", "yes", "y", "是"}


@dataclass(frozen=True)
class RuntimeEnvEntry:
    key: str
    value: str
    required: bool
    note: str = ""
    resolved_value: str | None = None
    status: str = "loaded"
    message: str = ""

    @property
    def display_value(self) -> str:
        value = self.resolved_value if self.resolved_value is not None else self.value
        if not value:
            return "<empty>"
        if is_secret_key(self.key):
            return f"<set; {len(value)} chars>"
        return value


@dataclass(frozen=True)
class RuntimeEnvLoadResult:
    env_file: Path
    used_example: bool
    entries: tuple[RuntimeEnvEntry, ...] = ()
    missing_required: tuple[RuntimeEnvEntry, ...] = ()
    loaded_count: int = 0
    skipped_count: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.missing_required


class RuntimeEnvError(ValueError):
    """Raised when the local runtime environment table is malformed."""


def load_runtime_env(
    env_file: Path | None = None,
    *,
    base_dir: Path = PROJECT_ROOT,
    apply: bool = True,
) -> RuntimeEnvLoadResult:
    """Load local runtime variables from CSV and optionally inject os.environ."""
    target_file = env_file or DEFAULT_ENV_FILE
    used_example = False
    warnings: list[str] = []

    if not target_file.exists():
        used_example = True
        target_file = EXAMPLE_ENV_FILE
        warnings.append(
            "local_env/runtime_env.csv not found; using config/runtime_env.example.csv as template."
        )

    rows = _read_rows(target_file)
    entries: list[RuntimeEnvEntry] = []
    missing_required: list[RuntimeEnvEntry] = []
    loaded_count = 0
    skipped_count = 0

    for row_number, row in enumerate(rows, start=2):
        key = _clean(row.get("key"))
        if not key:
            continue
        value = _clean(row.get("value"))
        required = _is_true(row.get("required"))
        note = _clean(row.get("note"))

        if not value:
            entry = RuntimeEnvEntry(
                key=key,
                value="",
                required=required,
                note=note,
                status="missing" if required else "skipped",
                message=f"row {row_number}: value is empty",
            )
            entries.append(entry)
            if required:
                missing_required.append(entry)
            else:
                skipped_count += 1
            continue

        resolved = resolve_runtime_value(key, value, base_dir=base_dir)
        entry = RuntimeEnvEntry(
            key=key,
            value=value,
            required=required,
            note=note,
            resolved_value=resolved,
            status="loaded",
            message=f"row {row_number}: loaded",
        )
        entries.append(entry)
        loaded_count += 1
        if apply:
            os.environ[key] = resolved

    ensure_local_pythonpath(base_dir=base_dir, apply=apply)

    return RuntimeEnvLoadResult(
        env_file=target_file,
        used_example=used_example,
        entries=tuple(entries),
        missing_required=tuple(missing_required),
        loaded_count=loaded_count,
        skipped_count=skipped_count,
        warnings=tuple(warnings),
    )


def resolve_runtime_value(key: str, value: str, *, base_dir: Path = PROJECT_ROOT) -> str:
    if key == "PYTHONPATH":
        return os.pathsep.join(
            str(_resolve_path_token(token, base_dir))
            for token in value.split(os.pathsep)
            if token.strip()
        )
    if key in PATH_LIKE_KEYS:
        return str(_resolve_path_token(value, base_dir))
    return value


def ensure_local_pythonpath(*, base_dir: Path = PROJECT_ROOT, apply: bool = True) -> str:
    package_dir = base_dir / ".python_packages"
    existing = os.environ.get("PYTHONPATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    package_text = str(package_dir)
    if package_dir.exists() and package_text not in parts:
        parts.insert(0, package_text)
    value = os.pathsep.join(parts)
    if apply and value:
        os.environ["PYTHONPATH"] = value
    return value


def is_secret_key(key: str) -> bool:
    upper_key = key.upper()
    return any(marker in upper_key for marker in SECRET_MARKERS)


def env_snapshot(keys: tuple[str, ...]) -> Mapping[str, str]:
    return {key: _display_env_value(key, os.environ.get(key)) for key in keys}


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or ())
            required_headers = {"key", "value", "required", "note"}
            missing = required_headers - headers
            if missing:
                joined = ", ".join(sorted(missing))
                raise RuntimeEnvError(f"{path} missing required columns: {joined}")
            return list(reader)
    except OSError as exc:
        raise RuntimeEnvError(f"Cannot read runtime env file {path}: {exc}") from exc


def _resolve_path_token(value: str, base_dir: Path) -> Path:
    path = Path(value.strip())
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _is_true(value: object) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def _clean(value: object) -> str:
    return str(value or "").strip()


def _display_env_value(key: str, value: str | None) -> str:
    if not value:
        return "<unset>"
    if is_secret_key(key):
        return f"<set; {len(value)} chars>"
    return value
