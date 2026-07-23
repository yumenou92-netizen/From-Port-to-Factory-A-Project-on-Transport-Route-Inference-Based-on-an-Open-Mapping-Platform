from __future__ import annotations

from src.data.data_foundation_audit import main
from src.dev.runtime_env import load_runtime_env


if __name__ == "__main__":
    load_runtime_env()
    raise SystemExit(main())
