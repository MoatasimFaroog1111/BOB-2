"""Shared fixtures for the backend test suite."""

import os

# Force non-production environment for tests
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.main import app

# In-memory SQLite for fast, isolated tests
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def _setup_db():
    """Create tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def db():
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded_user(db):
    """Seed a test user and return its email/password."""
    from app.models.core import Organization, User
    from app.security.auth import hash_password

    org = Organization(id=1, name="Test Org", legal_name="Test", country="SA", is_active=True)
    db.add(org)
    db.commit()

    password = "Test@Pass1234!"
    user = User(
        id=1,
        organization_id=1,
        email="test@guardian-ai.com",
        full_name="Test User",
        role="owner",
        hashed_password=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    return {"email": "test@guardian-ai.com", "password": password}
