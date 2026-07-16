from dataclasses import dataclass

import pytest

from app.core.runtime_security import validate_persistent_storage


@dataclass
class StubSettings:
    APP_ENV: str = "production"
    STORAGE_DIR: str = "/data/storage"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def validate_runtime_security(self) -> None:
        return None


def test_local_runtime_does_not_require_a_volume():
    validate_persistent_storage(
        StubSettings(APP_ENV="test", STORAGE_DIR="./storage"),
        environ={},
    )


def test_railway_production_requires_attached_volume_metadata():
    with pytest.raises(ValueError, match="RAILWAY_VOLUME_MOUNT_PATH"):
        validate_persistent_storage(
            StubSettings(),
            environ={"RAILWAY_ENVIRONMENT_ID": "production"},
        )


def test_railway_storage_may_be_a_child_of_the_volume_mount():
    validate_persistent_storage(
        StubSettings(STORAGE_DIR="/data/storage"),
        environ={
            "RAILWAY_ENVIRONMENT_ID": "production",
            "RAILWAY_VOLUME_MOUNT_PATH": "/data",
        },
    )


def test_railway_storage_outside_the_volume_is_rejected():
    with pytest.raises(ValueError, match="persistent mount path"):
        validate_persistent_storage(
            StubSettings(STORAGE_DIR="/app/storage"),
            environ={
                "RAILWAY_ENVIRONMENT_ID": "production",
                "RAILWAY_VOLUME_MOUNT_PATH": "/data",
            },
        )


def test_non_railway_production_requires_declared_mount():
    with pytest.raises(ValueError, match="PERSISTENT_STORAGE_MOUNT_PATH"):
        validate_persistent_storage(StubSettings(), environ={})


def test_relative_production_storage_is_rejected():
    with pytest.raises(ValueError, match="absolute path"):
        validate_persistent_storage(
            StubSettings(STORAGE_DIR="storage"),
            environ={"PERSISTENT_STORAGE_MOUNT_PATH": "/srv/guardian"},
        )
