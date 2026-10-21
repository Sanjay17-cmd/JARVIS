"""Load optional project-local provider credentials from the ignored .env file."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_api_environment(env_file: Path | None = None) -> bool:
    """Load dotenv values without overriding the user's existing environment."""
    if env_file is None:
        env_file = Path(__file__).resolve().parents[2] / ".env"
    return load_dotenv(env_file, override=False)
