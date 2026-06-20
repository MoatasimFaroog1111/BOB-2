import logging
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.models.core import Organization, User
from app.security.auth import hash_password

logger = logging.getLogger(__name__)


def seed_db(db: Session) -> None:
    # 1. Seed default organization if empty
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
        logger.info(f"Default organization seeded: {org.name}")
    else:
        logger.info("Organization already exists.")

    # 2. Seed default user if empty
    user = db.query(User).filter(User.email == "owner@guardian.local").first()
    if not user:
        logger.info("Seeding default owner user...")
        user = User(
            id=1,
            organization_id=1,
            email="owner@guardian.local",
            full_name="System Owner",
            role="owner",
            hashed_password=hash_password("admin123"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        logger.info(f"Default user seeded: {user.email}")
    else:
        logger.info("User already exists.")


def run_seed():
    db = SessionLocal()
    try:
        seed_db(db)
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()
