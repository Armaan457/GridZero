from __future__ import annotations
import os
from pathlib import Path


def load_aws_env():
    """
    Loads .env file from ML-Engine/.env or root repository without external dependencies.
    Sets AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION, and related variables.
    """
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


# Automatically run on import
load_aws_env()
