"""Regression tests for the security-hardening controls."""

import io
import zipfile

import pytest
from starlette.requests import Request

from app.core.config import settings
from app.security.file_validation import FileValidationError, validate_file_content
from app.security.rate_limiter import get_client_identifier


def _request(peer_ip: str, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer_ip, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def _xlsx_bytes(extra_files: dict[str, bytes] | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr("xl/workbook.xml", b"<workbook />")
        for name, content in (extra_files or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


class TestFileValidation:
    def test_unknown_binary_content_is_rejected(self):
        with pytest.raises(FileValidationError, match="Unknown or unsupported"):
            validate_file_content(b"\x00\x01\x02\x03not-a-document", ".pdf")

    def test_extension_spoofing_is_rejected(self):
        with pytest.raises(FileValidationError, match="does not match"):
            validate_file_content(b"%PDF-1.7\n", ".png")

    def test_macro_enabled_xlsx_is_rejected(self):
        content = _xlsx_bytes({"xl/vbaProject.bin": b"macro"})
        with pytest.raises(FileValidationError, match="Macro-enabled"):
            validate_file_content(content, ".xlsx")

    def test_archive_path_traversal_is_rejected(self):
        content = _xlsx_bytes({"../escape.xml": b"bad"})
        with pytest.raises(FileValidationError, match="unsafe path"):
            validate_file_content(content, ".xlsx")

    def test_minimal_xlsx_is_accepted(self):
        assert validate_file_content(_xlsx_bytes(), ".xlsx") is True


class TestTrustedProxyIdentity:
    def test_untrusted_peer_cannot_spoof_forwarded_ip(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8")
        request = _request(
            "203.0.113.10",
            [(b"x-forwarded-for", b"198.51.100.77")],
        )
        assert get_client_identifier(request) == "203.0.113.10"

    def test_trusted_proxy_can_supply_client_ip(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8")
        request = _request(
            "10.1.2.3",
            [(b"x-forwarded-for", b"198.51.100.77, 10.1.2.3")],
        )
        assert get_client_identifier(request) == "198.51.100.77"

    def test_invalid_forwarded_ip_falls_back_to_proxy_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8")
        request = _request(
            "10.1.2.3",
            [(b"x-forwarded-for", b"not-an-ip")],
        )
        assert get_client_identifier(request) == "10.1.2.3"
