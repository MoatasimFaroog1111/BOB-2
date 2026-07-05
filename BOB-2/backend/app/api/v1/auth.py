from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.core import User
from app.security.auth import create_access_token, create_refresh_token, verify_password, validate_password_strength
from app.security.dependencies import require_permission, get_current_token_payload
from app.security.roles import UserRole, role_has_permission
from app.security.rate_limiter import login_rate_limiter, get_client_identifier

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db)
):
    # Get client identifier for rate limiting (IP + email combination)
    ip_identifier = get_client_identifier(request)
    email_identifier = payload.email.lower()
    combined_identifier = f"{ip_identifier}:{email_identifier}"

    # Check rate limit
    login_rate_limiter.check_rate_limit(combined_identifier)
    login_rate_limiter.check_rate_limit(ip_identifier)  # Also check by IP alone

    # Generic error message to prevent user enumeration
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = db.query(User).filter(User.email == payload.email).first()

    # Record failed attempt if user not found
    if not user:
        login_rate_limiter.record_attempt(combined_identifier, success=False)
        login_rate_limiter.record_attempt(ip_identifier, success=False)
        raise invalid_credentials

    # Verify password
    if not verify_password(payload.password, user.hashed_password):
        login_rate_limiter.record_attempt(combined_identifier, success=False)
        login_rate_limiter.record_attempt(ip_identifier, success=False)
        raise invalid_credentials

    # Check if account is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled. Please contact your administrator.",
        )

    # Record successful login
    login_rate_limiter.record_attempt(combined_identifier, success=True)
    login_rate_limiter.record_attempt(ip_identifier, success=True)

    # Generate tokens
    access_token = create_access_token(subject=user.email, role=user.role)
    refresh_token = create_refresh_token(subject=user.email)

    from app.core.config import settings

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=user.role,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
def refresh_access_token(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """Refresh access token using a valid refresh token."""
    from app.security.auth import decode_refresh_token
    from jose import JWTError
    from app.core.config import settings

    try:
        # Decode and validate refresh token
        token_data = decode_refresh_token(payload.refresh_token)
        email = token_data.get("sub")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token.",
            )

        # Get user from database
        user = db.query(User).filter(User.email == email).first()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive.",
            )

        # Generate new access token
        new_access_token = create_access_token(subject=user.email, role=user.role)

        return RefreshTokenResponse(
            access_token=new_access_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )


@router.get("/roles")
def list_roles():
    return {
        "roles": [role.value for role in UserRole],
        "note": "Enterprise RBAC foundation is active.",
    }


@router.get("/check-permission/{permission}")
def check_permission(
    permission: str,
    current_user: dict = Depends(require_permission("manage_users"))
):
    """Check if current user has a specific permission."""
    return {
        "requested_permission": permission,
        "current_role": current_user.get("role"),
        "allowed": role_has_permission(current_user.get("role"), permission),
    }


@router.post("/logout")
def logout(current_user: dict = Depends(get_current_token_payload)):
    """
    Logout endpoint - in a stateless JWT system, this is mainly for client-side cleanup.
    In a full implementation, you might want to maintain a token blacklist.
    """
    return {
        "message": "Logout successful. Please clear your tokens on the client side.",
        "user": current_user.get("sub"),
    }
