import logging
import os

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.core import Organization, User
from app.security.auth import hash_password, validate_password_strength

logger = logging.getLogger(__name__)


def _default_organization_names() -> tuple[str, str]:
    name = os.getenv("GUARDIAN_DEFAULT_ORG_NAME", "").strip() or "Default Organization"
    legal_name = (
        os.getenv("GUARDIAN_DEFAULT_ORG_LEGAL_NAME", "").strip()
        or "Default Organization"
    )
    return name, legal_name


def seed_db(db: Session) -> None:
    """Seed non-sensitive baseline data.

    Production deliberately never creates an owner account automatically. A production
    administrator must be provisioned through a controlled bootstrap process after the
    database is deployed.
    """
    org = db.query(Organization).filter(Organization.id == 1).first()
    if not org:
        logger.info("Seeding default organization...")
        org_name, org_legal_name = _default_organization_names()
        org = Organization(
            id=1,
            name=org_name,
            legal_name=org_legal_name,
            country="Saudi Arabia",
            is_active=True,
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        logger.info("Default organization seeded: %s", org.name)

    if settings.is_production:
        logger.info("Automatic owner seeding is disabled in production.")
        return

    seed_email = settings.GUARDIAN_SEED_EMAIL.strip().lower()
    seed_password = settings.GUARDIAN_SEED_PASSWORD.strip()
    if not seed_email and not seed_password:
        logger.info("No development owner bootstrap was requested.")
        return
    if not seed_email or not seed_password:
        raise ValueError(
            "GUARDIAN_SEED_EMAIL and GUARDIAN_SEED_PASSWORD must both be set "
            "for development owner bootstrap"
        )

    is_valid, error = validate_password_strength(seed_password)
    if not is_valid:
        raise ValueError(f"GUARDIAN_SEED_PASSWORD is not strong enough: {error}")

    user = db.query(User).filter(User.email == seed_email).first()
    if user:
        logger.info("Development owner already exists; seed will not change its password.")
        return

    logger.warning("Creating opt-in development owner account: %s", seed_email)
    user = User(
        organization_id=org.id,
        email=seed_email,
        full_name="Development System Owner",
        role="owner",
        hashed_password=hash_password(seed_password),
        is_active=True,
    )
    db.add(user)
    db.commit()


def run_seed() -> None:
    db = SessionLocal()
    try:
        seed_db(db)
    except Exception:
        logger.exception("Error seeding database")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()