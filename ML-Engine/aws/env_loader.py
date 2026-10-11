from __future__ import annotations
import os
from pathlib import Path


def load_aws_env():
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip("\"'")
                            if key and key not in os.environ:
                                os.environ[key] = val
                break
            except Exception:
                pass


load_aws_env()
