"""Small helpers for reading settings out of the environment.

Values come from the process environment, with a ``.env`` file in the project
root loaded first (for local development only -- in production, set real
environment variables and do not ship a ``.env``).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


class MissingSetting(Exception):
    """Raised when a required environment variable has no value."""


_UNSET = object()


def env(name, default=_UNSET):
    """Return ``name`` from the environment, or ``default`` if it is unset."""
    value = os.environ.get(name)
    if value is None or value == "":
        if default is _UNSET:
            raise MissingSetting(
                f"Environment variable {name} is required. "
                "See .env.example for the full list of settings."
            )
        return default
    return value


def env_bool(name, default=False):
    """Return ``name`` as a boolean. Accepts 1/true/yes/on (case-insensitive)."""
    value = env(name, None)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    """Return ``name`` as an integer."""
    value = env(name, None)
    return default if value is None else int(value)


def env_list(name, default=""):
    """Return ``name`` split on commas, with blank entries dropped."""
    value = env(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]
