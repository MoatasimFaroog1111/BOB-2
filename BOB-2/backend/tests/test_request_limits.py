"""Regression tests for pre-parser request limits."""

from app.core.config import settings


def test_declared_oversized_body_is_rejected_before_parsing(client):
    response = client.post(
        "/api/v1/auth/login",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(settings.MAX_REQUEST_SIZE_MB * 1024 * 1024 + 1),
        },
    )
    assert response.status_code == 413
    assert "maximum size" in response.json()["detail"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_too_many_multipart_files_are_rejected_before_temp_storage(
    client,
    auth_headers,
):
    files = [
        ("files", (f"document-{index}.txt", b"safe text", "text/plain"))
        for index in range(settings.MAX_UPLOAD_FILES + 1)
    ]
    response = client.post(
        "/api/v1/erp/upload-documents",
        files=files,
        headers=auth_headers,
    )
    assert response.status_code == 413
    assert f"maximum of {settings.MAX_UPLOAD_FILES} files" in response.json()["detail"]
