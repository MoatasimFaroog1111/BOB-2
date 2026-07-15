from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.core import AuthSession
from app.models.session_security import (
    AuthSessionRotationState,
    AuthSessionSecurityEvent,
)
from app.security.auth import decode_refresh_token
from app.services.refresh_token_rotation import claim_refresh_generation


def _login(client, seeded_user, *, user_agent: str = "atomic-refresh-test"):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded_user["email"],
            "password": seeded_user["password"],
        },
        headers={"User-Agent": user_agent},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_login_creates_generation_zero_and_non_secret_event(client, seeded_user, db):
    login = _login(client, seeded_user)
    token_payload = decode_refresh_token(login["refresh_token"])
    assert token_payload["rgn"] == 0

    state = db.query(AuthSessionRotationState).one()
    assert state.generation == 0
    assert state.session_id == token_payload["sid"]
    assert state.family_id == token_payload["fid"]

    event = db.query(AuthSessionSecurityEvent).filter_by(event_type="session_created").one()
    assert event.outcome == "success"
    assert event.generation == 0
    assert event.user_agent_hash
    serialized = str(event.event_metadata or {}).lower()
    for forbidden in ("token", "jti", "password", "secret", "credential"):
        assert forbidden not in serialized


def test_refresh_advances_generation_and_replay_revokes_family(client, seeded_user, db):
    login = _login(client, seeded_user)
    old_refresh = login["refresh_token"]

    rotated = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
        headers={"User-Agent": "atomic-refresh-test"},
    )
    assert rotated.status_code == 200, rotated.text
    new_refresh = rotated.json()["refresh_token"]
    assert decode_refresh_token(new_refresh)["rgn"] == 1

    state = db.query(AuthSessionRotationState).one()
    db.refresh(state)
    assert state.generation == 1
    assert state.last_rotated_at is not None
    assert db.query(AuthSessionSecurityEvent).filter_by(event_type="refresh_rotated").count() == 1

    replay = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
        headers={"User-Agent": "atomic-refresh-test"},
    )
    assert replay.status_code == 401

    session = db.query(AuthSession).one()
    db.refresh(session)
    assert session.revoked_at is not None
    assert session.revocation_reason == "refresh_replay_or_expiry"
    assert (
        db.query(AuthSessionSecurityEvent)
        .filter_by(event_type="refresh_replay_detected", outcome="denied")
        .count()
        == 1
    )

    winner_after_replay = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_refresh},
        headers={"User-Agent": "atomic-refresh-test"},
    )
    assert winner_after_replay.status_code == 401


def test_compare_and_swap_allows_only_one_concurrent_generation_claim(tmp_path: Path):
    database_path = tmp_path / "refresh-race.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    Base.metadata.create_all(bind=engine)
    LocalSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with LocalSession() as db:
        db.add(
            AuthSessionRotationState(
                session_id="race-session",
                family_id="race-family",
                generation=0,
            )
        )
        db.commit()

    barrier = Barrier(2)

    def worker() -> bool:
        with LocalSession() as db:
            barrier.wait(timeout=10)
            claimed = claim_refresh_generation(
                db,
                session_id="race-session",
                family_id="race-family",
                expected_generation=0,
                rotated_at=__import__("datetime").datetime.utcnow(),
            )
            db.commit()
            return claimed

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: worker(), range(2)))

    assert sorted(results) == [False, True]
    with LocalSession() as db:
        state = db.query(AuthSessionRotationState).filter_by(session_id="race-session").one()
        assert state.generation == 1

    engine.dispose()
