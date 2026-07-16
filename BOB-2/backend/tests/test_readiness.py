from app.services import readiness as readiness_module


def test_readiness_endpoint_is_ready_when_dependencies_pass(client, monkeypatch):
    monkeypatch.setattr(
        readiness_module,
        "readiness_snapshot",
        lambda: {
            "status": "ready",
            "components": {"database": True, "redis": True, "storage": True},
        },
    )
    # main imported the callable directly; patch its reference too.
    from app import main as main_module

    monkeypatch.setattr(main_module, "readiness_snapshot", readiness_module.readiness_snapshot)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_endpoint_fails_closed_without_details(client, monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module,
        "readiness_snapshot",
        lambda: {
            "status": "not_ready",
            "components": {"database": False, "redis": True, "storage": True},
        },
    )
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": False, "redis": True, "storage": True},
    }
