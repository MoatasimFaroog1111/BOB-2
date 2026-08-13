"""Guarded text-feature extraction for historical ERP attachments.

Historical attachment bytes are never passed directly to a parser. They go through
the same size, malware, and content/type validation used by financial uploads,
then the existing GuardianDocumentAI extractor is reused. Extraction is bounded so
learning cannot turn into an unbounded ERP download/OCR workload.
"""

from __future__ import annotations

import base64
import binascii
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.erp.document_ai import GuardianDocumentAI
from app.security.file_validation import (
    FileValidationError,
    sanitize_filename,
    scan_for_malware,
    validate_file_content,
    validate_file_size,
)

# Formats supported by both the hardened byte validator and GuardianDocumentAI.
_SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv"}


@dataclass(frozen=True)
class AttachmentTextFeature:
    attachment_id: int
    filename: str
    text: str
    status: str
    error: str | None = None


class GuardedERPAttachmentFeatureExtractor:
    """Extract bounded document text without weakening the upload security boundary."""

    def __init__(
        self,
        *,
        document_ai: GuardianDocumentAI | None = None,
        max_text_chars: int = 6000,
    ):
        self.document_ai = document_ai or GuardianDocumentAI()
        self.max_text_chars = max(500, min(int(max_text_chars), 20000))

    @staticmethod
    def _decode_base64(value: Any) -> bytes:
        if not value:
            return b""
        try:
            if isinstance(value, bytes):
                encoded = value
            else:
                encoded = str(value).encode("ascii", errors="strict")
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
            raise FileValidationError("ERP attachment payload is not valid base64") from exc

    def extract(self, attachment: dict[str, Any]) -> AttachmentTextFeature:
        attachment_id = int(attachment.get("id") or 0)
        filename = sanitize_filename(str(attachment.get("name") or f"attachment-{attachment_id}"))
        extension = Path(filename).suffix.lower()
        if extension == ".jpeg":
            normalized_extension = ".jpg"
        else:
            normalized_extension = extension

        if extension not in _SUPPORTED_EXTENSIONS:
            return AttachmentTextFeature(
                attachment_id=attachment_id,
                filename=filename,
                text="",
                status="skipped_unsupported_type",
                error=f"Unsupported learning attachment extension: {extension or 'none'}",
            )

        try:
            content = self._decode_base64(attachment.get("datas"))
            validate_file_size(content)
            # Scan before invoking any parser/OCR, matching the normal upload path.
            scan_for_malware(content)
            validate_file_content(content, normalized_extension)

            with tempfile.NamedTemporaryFile(suffix=normalized_extension, delete=True) as temp_file:
                temp_file.write(content)
                temp_file.flush()
                text = self.document_ai.extract_text(temp_file.name).strip()

            if not text or text.startswith("OCR_ERROR:"):
                return AttachmentTextFeature(
                    attachment_id=attachment_id,
                    filename=filename,
                    text="",
                    status="no_text",
                    error=text[:500] if text else "No extractable text",
                )
            return AttachmentTextFeature(
                attachment_id=attachment_id,
                filename=filename,
                text=text[: self.max_text_chars],
                status="extracted",
            )
        except (FileValidationError, OSError, ValueError) as exc:
            detail = getattr(exc, "detail", None)
            return AttachmentTextFeature(
                attachment_id=attachment_id,
                filename=filename,
                text="",
                status="rejected",
                error=str(detail or exc)[:500],
            )
        except Exception as exc:
            # Attachment extraction is optional evidence. Never abort the accounting
            # history sync because one historical file cannot be parsed.
            return AttachmentTextFeature(
                attachment_id=attachment_id,
                filename=filename,
                text="",
                status="failed",
                error=type(exc).__name__,
            )
