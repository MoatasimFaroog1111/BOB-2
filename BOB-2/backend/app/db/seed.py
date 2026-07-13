import logging
import os

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.core import Organization, User
from app.security.auth import hash_password, validate_password_strength

logger = logging.getLogger(__name__)


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}


def seed_db(db: Session) -> None:
    # Seed a default organization only for an empty database.
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

    # Production owners must be provisioned through an explicit administrative
    # workflow. Never create a known owner identity automatically in production.
    if _is_production():
        logger.info("Skipping owner seed in production.")
        return

    seed_email = os.getenv("GUARDIAN_SEED_EMAIL", "").strip().lower()
    seed_password = os.getenv("GUARDIAN_SEED_PASSWORD", "")
    if not seed_email and not seed_password:
        logger.info("No development seed owner requested.")
        return
    if not seed_email or not seed_password:
        raise RuntimeError(
            "GUARDIAN_SEED_EMAIL and GUARDIAN_SEED_PASSWORD must both be set to seed an owner"
        )

    validate_password_strength(seed_password)
    user = db.query(User).filter(User.email == seed_email).first()
    if user:
        logger.info("Seed owner already exists.")
        return

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
    logger.info("Development seed owner created.")


def run_seed() -> None:
    db = SessionLocal()
    try:
        seed_db(db)
    except Exception:
        logger.exception("Database seeding failed")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()
