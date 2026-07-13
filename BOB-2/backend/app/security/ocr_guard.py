"""Global guardrails for pytesseract OCR execution.

pytesseract invokes the Tesseract binary in a separate subprocess. This wrapper adds a
hard timeout and a small concurrency limit to every OCR call, including legacy call
sites that do not pass security options explicitly.
"""

import logging
import threading

from app.core.config import settings

logger = logging.getLogger(__name__)
_installed = False
_semaphore = threading.BoundedSemaphore(value=2)


def install_ocr_guard() -> None:
    global _installed
    if _installed:
        return

    import pytesseract

    original = pytesseract.image_to_string

    def guarded_image_to_string(*args, **kwargs):
        kwargs.setdefault("timeout", settings.OCR_TIMEOUT_SECONDS)
        acquired = _semaphore.acquire(timeout=settings.OCR_TIMEOUT_SECONDS)
        if not acquired:
            raise RuntimeError("OCR capacity limit reached")
        try:
            return original(*args, **kwargs)
        finally:
            _semaphore.release()

    pytesseract.image_to_string = guarded_image_to_string
    _installed = True
    logger.info(
        "OCR guard installed with %ss subprocess timeout and concurrency limit 2",
        settings.OCR_TIMEOUT_SECONDS,
    )
