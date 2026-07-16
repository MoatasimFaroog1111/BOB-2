from datetime import date, timedelta

from app.models.core import AuditLog, Organization
from app.models.organization_offboarding import OrganizationOffboardingCase


def _payload():
    return {
        "reason": "Customer requested controlled service termination and retention review.",
        "retention_until": (date.today() + timedelta(days=365)).isoformat(),
        "legal_hold": False,
    }


def test_offboarding_requires_exact_organization_name(
    client,
    auth_headers,
    seeded_user,
    db,
):
    response = client.post(
        f"/api/v1/system/organization/{seeded_user['organization_id']}/offboarding",
        json=_payload(),
        headers={**auth_headers, "X-Confirm-Organization-Name": "Wrong Name"},
    )
    assert response.status_code == 400
    organization = db.get(Organization, seeded_user["organization_id"])
    assert organization.is_active is True


def test_offboarding_is_tenant_scoped_and_retention_aware(
    client,
    auth_headers,
    seeded_user,
    db,
):
    other = Organization(
        name="Unrelated Tenant",
        legal_name="Unrelated Tenant",
        country="SA",
        is_active=True,
    )
    db.add(other)
    db.commit()
    db.refresh(other)

    organization = db.get(Organization, seeded_user["organization_id"])
    response = client.post(
        f"/api/v1/system/organization/{organization.id}/offboarding",
        json=_payload(),
        headers={
            **auth_headers,
            "X-Confirm-Organization-Name": organization.name,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "retention_hold"
    assert body["access_disabled"] is True
    assert body["physical_deletion_performed"] is False

    db.expire_all()
    assert db.get(Organization, organization.id).is_active is False
    assert db.get(Organization, other.id).is_active is True
    case = (
        db.query(OrganizationOffboardingCase)
        .filter(OrganizationOffboardingCase.organization_id == organization.id)
        .one()
    )
    assert case.retention_until == date.today() + timedelta(days=365)
    assert case.completed_at is None
    event = (
        db.query(AuditLog)
        .filter(AuditLog.action == "organization_offboarding_started")
        .one()
    )
    assert event.organization_id == organization.id
    assert event.details["physical_deletion_performed"] is False


def test_offboarding_cannot_target_another_tenant(
    client,
    auth_headers,
    db,
):
    other = Organization(
        name="Protected Other Tenant",
        legal_name="Protected Other Tenant",
        country="SA",
        is_active=True,
    )
    db.add(other)
    db.commit()
    db.refresh(other)

    response = client.post(
        f"/api/v1/system/organization/{other.id}/offboarding",
        json=_payload(),
        headers={
            **auth_headers,
            "X-Confirm-Organization-Name": other.name,
        },
    )
    assert response.status_code == 404
    db.expire_all()
    assert db.get(Organization, other.id).is_active is True


def test_offboarding_requires_future_retention_or_legal_hold(
    client,
    auth_headers,
    seeded_user,
):
    response = client.post(
        f"/api/v1/system/organization/{seeded_user['organization_id']}/offboarding",
        json={
            "reason": "A valid reason that is long enough.",
            "retention_until": date.today().isoformat(),
            "legal_hold": False,
        },
        headers={**auth_headers, "X-Confirm-Organization-Name": "Test Organization"},
    )
    assert response.status_code == 422
