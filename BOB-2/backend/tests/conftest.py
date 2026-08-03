"""Shared fixtures for the backend test suite."""
import os
import tempfile

# Force non-production, non-persistent, network-isolated test services before
# importing the app. Embedding tests must use the deterministic local fallback
# instead of downloading multi-gigabyte Hugging Face models during CI.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_STORE_PROVIDER", "memory")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
_test_hf_home = os.path.join(tempfile.gettempdir(), "guardianai-test-huggingface")
os.environ["HF_HOME"] = _test_hf_home
os.environ["SENTENCE_TRANSFORMERS_HOME"] = _test_hf_home

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    """Seed a test user and return its credentials and tenant identity."""
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
    return {
        "email": "test@guardian-ai.com",
        "password": password,
        "organization_id": org.id,
        "user_id": user.id,
    }


@pytest.fixture()
def auth_headers(client, seeded_user):
    """Return a real bearer token from the hardened login flow."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded_user["email"],
            "password": seeded_user["password"],
        },
        headers={"User-Agent": "pytest-authenticated-client"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
