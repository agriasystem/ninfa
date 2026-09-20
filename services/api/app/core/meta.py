"""Static service metadata."""

from importlib.metadata import PackageNotFoundError, version

SERVICE_NAME = "ninfa-api"
_DISTRIBUTION = "ninfa-api"


def get_version() -> str:
    """Application version, read from the installed package metadata.

    The single source of truth is `version` in services/api/pyproject.toml.
    """
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - only when not installed
        return "0.0.0+unknown"
