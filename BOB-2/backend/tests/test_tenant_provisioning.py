"""Tests for tenant slug derivation."""
from __future__ import annotations

import pytest

from app.onboarding.tenant_provisioner import TenantProvisioner


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Acme Holdings", "acme-holdings"),
        ("Bob's Books", "bob-s-books"),
        ("  spaces  ", "spaces"),
        ("UPPER lower 123", "upper-lower-123"),
        ("a", "a"),  # min 1 char
    ],
)
def test_derive_slug_handles_common_names(name: str, expected: str) -> None:
    assert TenantProvisioner.derive_slug(name) == expected


def test_derive_slug_rejects_empty() -> None:
    with pytest.raises(ValueError):
        TenantProvisioner.derive_slug("")
    with pytest.raises(ValueError):
        TenantProvisioner.derive_slug("   ")


def test_derive_slug_rejects_all_special_chars() -> None:
    with pytest.raises(ValueError):
        TenantProvisioner.derive_slug("!!!@@@###")


@pytest.mark.parametrize(
    "reserved",
    ["www", "api", "admin", "guardianai", "bob-2", "default", "system"],
)
def test_derive_slug_rejects_reserved(reserved: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        TenantProvisioner.derive_slug(reserved)


def test_derive_slug_enforces_length_bounds() -> None:
    # 33-char slug is over the cap of 32
    too_long = "a" * 33
    with pytest.raises(ValueError, match="not DNS-safe"):
        TenantProvisioner.derive_slug(too_long)