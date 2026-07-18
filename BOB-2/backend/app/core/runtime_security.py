"""Runtime-only production checks that depend on the deployment environment.

These checks intentionally run when the web process starts. Railway volumes are
not mounted during image build or pre-deploy commands, so validating them there
would reject a correctly configured deployment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol


class RuntimeSettings(Protocol):
    APP_ENV: str
    STORAGE_DIR: str

    @property
    def is_production(self) -> bool: ...

    def validate_runtime_security(self) -> None: ...


_RAILWAY_ENVIRONMENT_VARIABLES = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
)


def _is_railway_environment(environ: Mapping[str, str]) -> bool:
    return any(environ.get(name, "").strip() for name in _RAILWAY_ENVIRONMENT_VARIABLES)


def _absolute_path(raw_path: str, *, field_name: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path in production")
    return Path(os.path.normpath(str(path)))


def validate_persistent_storage(
    settings_obj: RuntimeSettings,
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Require production files to live under a declared persistent mount."""
    if not settings_obj.is_production:
        return

    runtime_environ = os.environ if environ is None else environ
    storage_path = _absolute_path(settings_obj.STORAGE_DIR, field_name="STORAGE_DIR")

    if _is_railway_environment(runtime_environ):
        mount_variable = "RAILWAY_VOLUME_MOUNT_PATH"
    else:
        mount_variable = "PERSISTENT_STORAGE_MOUNT_PATH"

    raw_mount = runtime_environ.get(mount_variable, "").strip()
    if not raw_mount:
        raise ValueError(
            f"{mount_variable} is required for persistent production storage"
        )

    mount_path = _absolute_path(raw_mount, field_name=mount_variable)
    if storage_path != mount_path and mount_path not in storage_path.parents:
        raise ValueError(
            "STORAGE_DIR must be the persistent mount path or a directory below it"
        )

    if storage_path == Path("/"):
        raise ValueError("STORAGE_DIR cannot be the filesystem root")


def validate_runtime_security(
    settings_obj: RuntimeSettings,
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Run configuration checks followed by runtime mount validation."""
    settings_obj.validate_runtime_security()
    validate_persistent_storage(settings_obj, environ=environ)
