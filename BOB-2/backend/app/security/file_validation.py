"""
File upload security validation utilities.
Validates file types, sizes, and content for uploaded files.
Uses built-in magic number detection (no external dependencies).
"""
import os
from pathlib import Path
from typing import List, Tuple, Optional
from fastapi import UploadFile, HTTPException, status
from app.core.config import settings


class FileValidationError(HTTPException):
    """Custom exception for file validation errors."""
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


# Magic bytes signatures for file type detection (no external library needed)
MAGIC_SIGNATURES = {
    b"%PDF":                                  ".pdf",
    b"\x89PNG\r\n\x1a\n":                    ".png",
    b"\xff\xd8\xff":                          ".jpg",   # JPEG
    b"GIF87a":                                ".gif",
    b"GIF89a":                                ".gif",
    b"RIFF":                                  ".webp",  # further check needed
    b"PK\x03\x04":                            ".docx",  # also .xlsx, .zip
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":    ".doc",   # also .xls (OLE format)
}

# Allowed extensions
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".txt", ".csv", ".docx", ".xlsx", ".doc", ".xls",
}

# Dangerous extensions that should never be allowed
DANGEROUS_EXTENSIONS = {
    ".exe", ".dll", ".bat", ".cmd", ".sh", ".py", ".js", ".php",
    ".jsp", ".asp", ".aspx", ".rb", ".pl", ".cgi", ".com",
    ".scr", ".msi", ".vbs", ".wsf", ".ps1", ".psm1", ".jar",
}


def detect_file_type(content: bytes) -> Optional[str]:
    """Detect file type from magic bytes without external libraries."""
    for signature, ext in MAGIC_SIGNATURES.items():
        if content.startswith(signature):
            # Extra check for webp (RIFF....WEBP)
            if signature == b"RIFF" and len(content) >= 12:
                if content[8:12] == b"WEBP":
                    return ".webp"
                # Not webp, skip
                continue
            return ext
    # Plain text fallback (txt/csv)
    try:
        content[:512].decode("utf-8")
        return ".txt"
    except Exception:
        return None


def validate_file_extension(filename: Optional[str]) -> bool:
    """Validate that file extension is allowed."""
    if not filename:
        raise FileValidationError("Filename is required")

    ext = Path(filename).suffix.lower()

    # Check for dangerous extensions
    if ext in DANGEROUS_EXTENSIONS:
        raise FileValidationError(f"File type '{ext}' is not allowed for security reasons")

    # Check against allowed extensions from settings
    allowed_exts = settings.allowed_upload_extensions_list
    if ext not in allowed_exts:
        raise FileValidationError(
            f"File extension '{ext}' is not allowed. Allowed: {', '.join(allowed_exts)}"
        )

    return True


def validate_file_size(content: bytes) -> bool:
    """Validate that file size is within limits."""
    max_size_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    if len(content) > max_size_bytes:
        raise FileValidationError(
            f"File size exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB"
        )

    return True


def validate_file_content(content: bytes, declared_extension: str) -> bool:
    """
    Validate file content using built-in magic number detection.
    Ensures file content matches the declared extension.
    """
    if not content:
        raise FileValidationError("File is empty")

    detected_ext = detect_file_type(content)
    declared_ext = declared_extension.lower()

    # Allow jpg/jpeg interchange
    if declared_ext == ".jpeg":
        declared_ext = ".jpg"

    # If we can detect the type, verify it matches the declared extension
    if detected_ext is not None:
        # .docx and .xlsx both start with PK (ZIP), allow both
        if detected_ext == ".docx" and declared_ext in {".docx", ".xlsx"}:
            return True
        # .doc and .xls both use OLE format
        if detected_ext == ".doc" and declared_ext in {".doc", ".xls"}:
            return True
        # txt also covers csv
        if detected_ext == ".txt" and declared_ext in {".txt", ".csv"}:
            return True

        if detected_ext != declared_ext:
            raise FileValidationError(
                f"File content does not match its extension "
                f"(detected: {detected_ext}, declared: {declared_ext})"
            )

    return True


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and other attacks."""
    if not filename:
        return "unnamed_file"

    # Remove path traversal characters
    filename = os.path.basename(filename)

    # Remove null bytes
    filename = filename.replace("\x00", "")

    # Replace dangerous characters
    dangerous_chars = ['<', '>', ':', '"', '|', '?', '*']
    for char in dangerous_chars:
        filename = filename.replace(char, "_")

    # Limit length
    max_length = 255
    name, ext = os.path.splitext(filename)
    if len(filename) > max_length:
        name = name[:max_length - len(ext)]
        filename = name + ext

    return filename


async def validate_upload_file(file: UploadFile) -> Tuple[bool, Optional[str]]:
    """
    Comprehensive validation of an uploaded file.
    Returns (is_valid, error_message).
    """
    try:
        # Validate filename
        if not file.filename:
            raise FileValidationError("File must have a filename")

        # Sanitize and validate extension
        safe_filename = sanitize_filename(file.filename)
        validate_file_extension(safe_filename)

        # Read and validate content
        content = await file.read()

        # Reset file position for further processing
        await file.seek(0)

        # Validate size
        validate_file_size(content)

        # Validate content type
        ext = Path(safe_filename).suffix
        validate_file_content(content, ext)

        return True, None

    except FileValidationError as e:
        return False, str(e.detail)
    except Exception as e:
        return False, f"File validation failed: {str(e)}"


async def validate_upload_files(files: List[UploadFile]) -> List[Tuple[UploadFile, bool, Optional[str]]]:
    """Validate multiple uploaded files."""
    results = []
    for file in files:
        is_valid, error = await validate_upload_file(file)
        results.append((file, is_valid, error))
    return results


def validate_file_path(path: str, base_dir: str) -> bool:
    """
    Validate that a file path is within the allowed base directory.
    Prevents path traversal attacks using modern path resolution.
    """
    try:
        # Resolve to absolute, real paths
        target_path = Path(path).resolve()
        allowed_base = Path(base_dir).resolve()

        # Check if the target path is relative to the allowed base directory
        if not target_path.is_relative_to(allowed_base):
            raise FileValidationError("Path traversal detected - file outside allowed directory")

        return True
    except Exception as e:
        if isinstance(e, FileValidationError):
            raise
        raise FileValidationError(f"Path validation failed: {str(e)}")
