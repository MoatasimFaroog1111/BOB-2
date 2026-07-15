from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.core import AuthSession, Organization, User
from app.security.auth import decode_access_token
from app.security.roles import role_has_permission

security = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _revoke_invalid_session(
    db: Session,
    auth_session: AuthSession | None,
    reason: str,
) -> None:
    if auth_session is None or auth_session.revoked_at is not None:
        return
    auth_session.revoked_at = datetime.utcnow()
    auth_session.revocation_reason = reason[:100]
    db.commit()


def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise _unauthorized()

    session_id = payload.get("sid")
    access_jti = payload.get("jti")
    if not isinstance(session_id, str) or not session_id or not isinstance(access_jti, str):
        raise _unauthorized()

    auth_session = (
        db.query(AuthSession)
        .filter(
            AuthSession.id == session_id,
            AuthSession.access_jti == access_jti,
        )
        .first()
    )
    if (
        not auth_session
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= datetime.utcnow()
    ):
        raise _unauthorized()

    user = db.query(User).filter(User.id == auth_session.user_id).first()
    if not user or not user.is_active or user.email != payload.get("sub"):
        _revoke_invalid_session(db, auth_session, "user_identity_or_status_changed")
        raise _unauthorized()

    organization = None
    if user.organization_id is not None:
        organization = (
            db.query(Organization)
            .filter(Organization.id == user.organization_id)
            .first()
        )
    if not organization or not organization.is_active:
        _revoke_invalid_session(db, auth_session, "organization_inactive_or_missing")
        raise _unauthorized()

    try:
        token_security_version = int(payload.get("sv"))
    except (TypeError, ValueError):
        _revoke_invalid_session(db, auth_session, "missing_security_version")
        raise _unauthorized()

    current_security_version = int(user.security_version or 1)
    if (
        auth_session.organization_id != user.organization_id
        or auth_session.user_security_version != current_security_version
        or token_security_version != current_security_version
    ):
        _revoke_invalid_session(db, auth_session, "security_version_mismatch")
        raise _unauthorized()

    # JWT role is informational only. Every authorization decision below this
    # boundary receives the current database role and tenant identity.
    payload["user_id"] = user.id
    payload["organization_id"] = user.organization_id
    payload["role"] = user.role
    payload["security_version"] = current_security_version
    return payload


def require_permission(permission: str):
    def checker(payload: dict = Depends(get_current_token_payload)) -> dict:
        if not role_has_permission(payload.get("role"), permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role permissions.",
            )
        return payload

    return checker


def _required_financial_permission(request: Request) -> str:
    """Map every finance route to a minimum permission."""
    method = request.method.upper()
    path = request.url.path.lower().rstrip("/")

    erp_settings_paths = {
        "/api/v1/erp/connection",
        "/api/v1/erp/test-connection",
        "/api/v1/erp/test-saved",
        "/api/v1/erp/discover",
    }
    if path in erp_settings_paths or (
        method == "DELETE" and path.startswith("/api/v1/erp/connection")
    ):
        return "manage_settings"

    if method in {"GET", "HEAD", "OPTIONS"}:
        return "view_financials"

    if path.startswith("/api/v1/communication-tools"):
        return "approve_actions"

    posting_markers = (
        "/journal-entry/",
        "/bank-posting",
        "/post-entry",
        "/post-selected",
        "/post-all",
        "/reverse-and-replace",
        "/reset-to-draft",
    )
    if any(marker in path for marker in posting_markers):
        return "post_odoo_entries"

    upload_markers = (
        "/upload",
        "/match-documents",
        "/bank-statement-parse",
    )
    if any(marker in path for marker in upload_markers):
        return "upload_documents"

    return "create_entries"


def enforce_financial_route_permission(
    request: Request,
    payload: dict = Depends(get_current_token_payload),
) -> dict:
    # Several legacy ERP modules still address organization 1 internally. Until
    # those modules are fully parameterized, users from another tenant are denied
    # instead of being allowed to read or mutate organization 1 data.
    if payload.get("organization_id") != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This legacy financial integration is not enabled for the authenticated "
                "organization. Tenant-isolated journal APIs remain available."
            ),
        )

    permission = _required_financial_permission(request)
    if not role_has_permission(payload.get("role"), permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient role permissions for this financial operation ({permission}).",
        )
    return payload
