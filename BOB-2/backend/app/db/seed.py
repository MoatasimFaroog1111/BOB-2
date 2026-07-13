import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.core import Organization, User
from app.security.auth import hash_password, validate_password_strength

logger = logging.getLogger(__name__)

DEFAULT_OWNER_EMAIL = "owner@guardian.local"


def seed_db(db: Session) -> None:
    """Seed non-sensitive baseline data.

    Production deliberately never creates an owner account automatically. A production
    administrator must be provisioned through a controlled bootstrap process after the
    database is deployed.
    """
    org = db.query(Organization).filter(Organization.id == 1).first()
    if not org:
        logger.info("Seeding default organization...")
        org = Organization(
            id=1,
            name="GTC International",
            legal_name="GTC International Co.",
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

    # Development/test owner creation is opt-in and requires an explicitly supplied
    # strong password. There is no fallback password in source code.
    seed_password = settings.GUARDIAN_SEED_PASSWORD.strip()
    if not seed_password:
        logger.info(
            "GUARDIAN_SEED_PASSWORD is not set; skipping development owner bootstrap."
        )
        return

    is_valid, error = validate_password_strength(seed_password)
    if not is_valid:
        raise ValueError(f"GUARDIAN_SEED_PASSWORD is not strong enough: {error}")

    user = db.query(User).filter(User.email == DEFAULT_OWNER_EMAIL).first()
    if user:
        logger.info("Development owner already exists; seed will not change its password.")
        return

    logger.warning("Creating opt-in development owner account: %s", DEFAULT_OWNER_EMAIL)
    user = User(
        id=1,
        organization_id=1,
        email=DEFAULT_OWNER_EMAIL,
        full_name="System Owner",
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
        # A failed bootstrap must fail startup instead of leaving production in an
        # unknown or partially initialized state.
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()
