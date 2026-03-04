"""Shared constants for the telemetry package."""

# Allowed base directories for log files.
# Paths are relative or absolute; configure_* functions resolve them at call
# time using Path.resolve(), so the effective directory depends on the process
# working directory for relative entries like ".data/".
ALLOWED_LOG_DIRS: tuple[str, ...] = ("/var/log/", ".data/")
