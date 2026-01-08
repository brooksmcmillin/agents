"""Environment variable utilities.

Common utilities for checking and validating environment variables.
"""

from pathlib import Path


def check_env_vars(env_file: Path, required_vars: list[str]) -> list[str]:
    """Check which required variables are missing from .env file.

    Args:
        env_file: Path to the .env file
        required_vars: List of required environment variable names

    Returns:
        List of missing variable names (empty if all present)
    """
    if not env_file.exists():
        return required_vars

    env_content = env_file.read_text()
    return [var for var in required_vars if f"{var}=" not in env_content]


def env_file_exists(env_file: Path) -> bool:
    """Check if .env file exists.

    Args:
        env_file: Path to the .env file

    Returns:
        True if file exists, False otherwise
    """
    return env_file.exists()
