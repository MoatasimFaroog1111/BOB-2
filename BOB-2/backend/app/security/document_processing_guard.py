"""Guard legacy document-processing call sites that bypass UploadFile validation."""

import logging
from pathlib import Path

from app.core.config import settings
from app.security.file_validation import (
    scan_for_malware,
    validate_file_content,
    validate_file_extension,
    validate_file_size,
)

logger = logging.getLogger(__name__)
_installed = False


def _validate_path_before_processing(file_path: str) -> None:
    path = Path(file_path)
    if not path.is_file():
        raise ValueError("Document path does not reference a regular file")

    validate_file_extension(path.name)
    maximum = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    with path.open("rb") as handle:
        content = handle.read(maximum + 1)

    validate_file_size(content)
    scan_for_malware(content)
    validate_file_content(content, path.suffix.lower())


def install_document_processing_guard() -> None:
    """Patch the shared document AI entrypoint so every caller is validated."""
    global _installed
    if _installed:
        return

    from app.erp.document_ai import GuardianDocumentAI

    original_extract_text = GuardianDocumentAI.extract_text

    def guarded_extract_text(self, file_path: str) -> str:
        _validate_path_before_processing(file_path)
        return original_extract_text(self, file_path)

    GuardianDocumentAI.extract_text = guarded_extract_text
    _installed = True
    logger.info("Document processing guard installed")
