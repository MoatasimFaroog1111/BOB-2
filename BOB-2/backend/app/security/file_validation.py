"""Fail-closed validation for financial document uploads."""

import asyncio
import io
import os
import zipfile
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings


class FileValidationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


DANGEROUS_EXTENSIONS = {
    ".exe", ".dll", ".bat", ".cmd", ".sh", ".py", ".js", ".php",
    ".jsp", ".asp", ".aspx", ".rb", ".pl", ".cgi", ".com", ".scr",
    ".msi", ".vbs", ".wsf", ".ps1", ".psm1", ".jar", ".zip", ".rar",
    ".7z", ".docm", ".xlsm", ".xlam", ".pptm",
}

TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".ofx", ".qfx", ".qif", ".mt940", ".sta"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _looks_like_text(content: bytes) -> bool:
    if b"\x00" in content[:4096]:
        return False
    sample = content[:8192]
    for encoding in ("utf-8", "cp1252"):
        try:
            decoded = sample.decode(encoding)
            if not decoded:
                return False
            printable = sum(char.isprintable() or char in "\r\n\t" for char in decoded)
            return printable / len(decoded) >= 0.9
        except UnicodeDecodeError:
            continue
    return False


def _inspect_office_zip(content: bytes) -> Optional[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = {name.replace("\\", "/") for name in archive.namelist()}
            if "[Content_Types].xml" in names and any(name.startswith("xl/") for name in names):
                return ".xlsx"
    except (zipfile.BadZipFile, OSError):
        return None
    return None


def detect_file_type(content: bytes, declared_extension: str) -> Optional[str]:
    if content.startswith(b"%PDF-"):
        return ".pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        return ".webp"
    if content.startswith(b"PK\x03\x04"):
        return _inspect_office_zip(content)
    if declared_extension in TEXT_EXTENSIONS and _looks_like_text(content):
        return declared_extension
    return None


def validate_file_extension(filename: Optional[str]) -> bool:
    if not filename:
        raise FileValidationError("Filename is required")

    ext = Path(filename).suffix.lower()
    if not ext:
        raise FileValidationError("A file extension is required")
    if ext in DANGEROUS_EXTENSIONS:
        raise FileValidationError(f"File type '{ext}' is not allowed for security reasons")

    allowed_exts = settings.allowed_upload_extensions_list
    if ext not in allowed_exts:
        raise FileValidationError(
            f"File extension '{ext}' is not allowed. Allowed: {', '.join(allowed_exts)}"
        )
    return True


def validate_file_size(content: bytes) -> bool:
    max_size_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_size_bytes:
        raise FileValidationError(
            f"File size exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB"
        )
    return True


def _validate_zip_member_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if normalized.startswith("/") or ".." in path.parts:
        raise FileValidationError("Archive contains an unsafe path")


def validate_xlsx_archive(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > settings.MAX_ARCHIVE_FILES:
                raise FileValidationError("Spreadsheet contains too many embedded files")

            total_uncompressed = 0
            for member in members:
                _validate_zip_member_name(member.filename)
                lower_name = member.filename.lower()
                if lower_name.endswith("vbaproject.bin") or "/externalLinks/".lower() in lower_name:
                    raise FileValidationError(
                        "Macro-enabled or externally linked spreadsheets are not allowed"
                    )

                total_uncompressed += member.file_size
                if total_uncompressed > settings.MAX_ARCHIVE_UNCOMPRESSED_MB * 1024 * 1024:
                    raise FileValidationError("Spreadsheet expands beyond the safe size limit")

                if member.file_size > 1_000_000:
                    compressed = max(member.compress_size, 1)
                    if member.file_size / compressed > 100:
                        raise FileValidationError("Suspicious spreadsheet compression ratio detected")
    except zipfile.BadZipFile as exc:
        raise FileValidationError("Invalid XLSX archive") from exc


def validate_pdf(content: bytes) -> None:
    try:
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
        try:
            if document.is_encrypted:
                raise FileValidationError("Encrypted PDF files are not accepted")
            if document.page_count > settings.MAX_PDF_PAGES:
                raise FileValidationError(
                    f"PDF exceeds the maximum of {settings.MAX_PDF_PAGES} pages"
                )
        finally:
            document.close()
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("Invalid or corrupted PDF file") from exc


def validate_image(content: bytes) -> None:
    try:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > settings.MAX_IMAGE_PIXELS:
                raise FileValidationError("Image dimensions exceed the safe processing limit")
            image.verify()
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("Invalid or unsafe image file") from exc


def validate_file_content(content: bytes, declared_extension: str) -> bool:
    if not content:
        raise FileValidationError("File is empty")

    declared_ext = declared_extension.lower()
    detected_ext = detect_file_type(content, declared_ext)
    if detected_ext is None:
        raise FileValidationError("Unknown or unsupported file content")

    normalized_declared = ".jpg" if declared_ext == ".jpeg" else declared_ext
    normalized_detected = ".jpg" if detected_ext == ".jpeg" else detected_ext
    if normalized_detected != normalized_declared:
        raise FileValidationError(
            "File content does not match its extension "
            f"(detected: {detected_ext}, declared: {declared_ext})"
        )

    if declared_ext == ".xlsx":
        validate_xlsx_archive(content)
    elif declared_ext == ".pdf":
        validate_pdf(content)
    elif declared_ext in IMAGE_EXTENSIONS:
        validate_image(content)
    return True


def scan_for_malware(content: bytes) -> None:
    """Scan bytes with ClamAV and fail closed when scanning is required."""
    if not settings.CLAMAV_HOST:
        if settings.REQUIRE_MALWARE_SCAN:
            raise FileValidationError("Malware scanner is not configured")
        return

    try:
        import clamd

        client = clamd.ClamdNetworkSocket(
            host=settings.CLAMAV_HOST,
            port=settings.CLAMAV_PORT,
            timeout=10,
        )
        result = client.instream(io.BytesIO(content))
        status_value = result.get("stream") if isinstance(result, dict) else None
        scan_status = status_value[0] if status_value else None
        signature = status_value[1] if status_value and len(status_value) > 1 else None

        if scan_status == "FOUND":
            raise FileValidationError(
                f"Upload rejected by malware scanner: {signature or 'malware detected'}"
            )
        if scan_status != "OK":
            raise FileValidationError("Malware scanner returned an indeterminate result")
    except FileValidationError:
        raise
    except Exception as exc:
        if settings.REQUIRE_MALWARE_SCAN:
            raise FileValidationError("Malware scan could not be completed") from exc


def sanitize_filename(filename: str) -> str:
    if not filename:
        return "unnamed_file"
    filename = os.path.basename(filename).replace("\x00", "")
    for char in ['<', '>', ':', '"', '|', '?', '*']:
        filename = filename.replace(char, "_")
    name, ext = os.path.splitext(filename)
    if len(filename) > 255:
        filename = name[: 255 - len(ext)] + ext
    return filename


async def validate_upload_file(file: UploadFile) -> Tuple[bool, Optional[str]]:
    try:
        if not file.filename:
            raise FileValidationError("File must have a filename")

        safe_filename = sanitize_filename(file.filename)
        validate_file_extension(safe_filename)

        max_size_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        content = await file.read(max_size_bytes + 1)
        await file.seek(0)

        validate_file_size(content)
        ext = Path(safe_filename).suffix.lower()

        # Scan before invoking parsers, decompression, OCR, or image decoders.
        await asyncio.to_thread(scan_for_malware, content)
        await asyncio.to_thread(validate_file_content, content, ext)
        return True, None
    except FileValidationError as exc:
        return False, str(exc.detail)
    except Exception:
        return False, "File validation failed"


async def validate_upload_files(
    files: List[UploadFile],
) -> List[Tuple[UploadFile, bool, Optional[str]]]:
    results = []
    for file in files:
        is_valid, error = await validate_upload_file(file)
        results.append((file, is_valid, error))
    return results


def validate_file_path(path: str, base_dir: str) -> bool:
    try:
        target_path = Path(path).resolve()
        allowed_base = Path(base_dir).resolve()
        if not target_path.is_relative_to(allowed_base):
            raise FileValidationError("Path traversal detected - file outside allowed directory")
        return True
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("Path validation failed") from exc
