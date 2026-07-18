from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SecretStoreError(RuntimeError):
    def __init__(
        self,
        reason: str,
        public_message: str = "The secure secret store operation failed.",
    ) -> None:
        super().__init__(public_message)
        self.reason = reason
        self.public_message = public_message


class SecretNotConfigured(SecretStoreError):
    def __init__(self) -> None:
        super().__init__(
            "secret_not_configured",
            "The requested secret is not configured.",
        )


@dataclass(frozen=True, slots=True)
class RemoteSecretVersion:
    name: str
    version: str


class SecretProvider(Protocol):
    provider_name: str

    def set_secret(
        self,
        name: str,
        value: str,
        *,
        tags: dict[str, str],
    ) -> RemoteSecretVersion: ...

    def get_secret(self, name: str, version: str) -> str: ...

    def disable_secret(self, name: str, version: str) -> None: ...
