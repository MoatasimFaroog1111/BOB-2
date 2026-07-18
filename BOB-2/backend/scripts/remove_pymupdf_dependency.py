"""Replace the AGPL/commercial PyMuPDF runtime with permissive PDF libraries.

This migration is deterministic and idempotent so GitHub Actions can apply it to
an isolated release branch, run regressions, and commit only a successful result.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_function(
    path: Path,
    *,
    start_pattern: str,
    end_pattern: str,
    replacement: str,
) -> None:
    content = path.read_text(encoding="utf-8")
    if replacement.strip() in content:
        return
    pattern = re.compile(rf"(?ms)^{start_pattern}.*?(?=^{end_pattern})")
    updated, count = pattern.subn(
        lambda _match: replacement.rstrip() + "\n\n",
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"Expected function boundary not found in {path}: {start_pattern}")
    compile(updated, str(path), "exec")
    path.write_text(updated, encoding="utf-8")


def replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    if new in content:
        return
    if old not in content:
        raise RuntimeError(f"Expected migration token not found in {path}: {old!r}")
    updated = content.replace(old, new, 1)
    compile(updated, str(path), "exec")
    path.write_text(updated, encoding="utf-8")


def migrate_requirements(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    replacement = "pypdf==6.14.2\npdfplumber==0.11.10\npypdfium2==5.12.0"
    if replacement in content and "PyMuPDF==" not in content:
        return
    if "PyMuPDF==1.28.0" not in content:
        raise RuntimeError(f"Pinned PyMuPDF line not found in {path}")
    path.write_text(
        content.replace("PyMuPDF==1.28.0", replacement, 1),
        encoding="utf-8",
    )


def main() -> None:
    for requirements in (ROOT / "requirements.txt", ROOT / "requirements.runtime.txt"):
        migrate_requirements(requirements)

    replace_function(
        ROOT / "app/security/file_validation.py",
        start_pattern=r"def validate_pdf\(content: bytes\) -> None:",
        end_pattern=r"def validate_image\(content: bytes\) -> None:",
        replacement='''def validate_pdf(content: bytes) -> None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise FileValidationError("Encrypted PDF files are not accepted")
        if len(reader.pages) > settings.MAX_PDF_PAGES:
            raise FileValidationError(
                f"PDF exceeds the maximum of {settings.MAX_PDF_PAGES} pages"
            )
        for page in reader.pages:
            _ = page.mediabox
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("Invalid or corrupted PDF file") from exc
''',
    )

    replace_function(
        ROOT / "app/erp/document_ai.py",
        start_pattern=r"    def _extract_pdf_text\(self, path: Path\) -> str:",
        end_pattern=r"    def _extract_image_text\(self, path: Path\) -> str:",
        replacement='''    def _extract_pdf_text(self, path: Path) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path), strict=True)
            if reader.is_encrypted:
                return "OCR_ERROR: encrypted PDF is not supported"
            text_parts = [(page.extract_text() or "") for page in reader.pages]
            text = "\\n".join(text_parts).strip()
            if text:
                return text

            import pypdfium2 as pdfium

            ocr_parts = []
            document = pdfium.PdfDocument(str(path))
            try:
                for page_index in range(len(document)):
                    page = document[page_index]
                    bitmap = None
                    try:
                        bitmap = page.render(scale=150 / 72)
                        image = bitmap.to_pil()
                        ocr_parts.append(self._ocr_image(image))
                    except Exception as page_err:
                        print(f"Error OCR on page: {page_err}")
                    finally:
                        if bitmap is not None:
                            bitmap.close()
                        page.close()
            finally:
                document.close()
            return "\\n".join(ocr_parts).strip()

        except Exception as e:
            print(f"Error in _extract_pdf_text: {e}")
            return self._ocr_file(path)
''',
    )

    replace_function(
        ROOT / "app/erp/pdf_statement_parser.py",
        start_pattern=r"def _group_pdf_lines\(doc\).*?:",
        end_pattern=r"def _is_summary_or_header\(text: str\) -> bool:",
        replacement='''def _group_pdf_lines(doc) -> list[tuple[int, float, list[tuple[float, float, str]]]]:
    lines: list[tuple[int, float, list[tuple[float, float, str]]]] = []
    for page_no, page in enumerate(doc.pages, 1):
        words = page.extract_words(
            x_tolerance=1,
            y_tolerance=4.5,
            keep_blank_chars=False,
            use_text_flow=False,
        ) or []
        current: list[tuple[float, float, str]] = []
        current_y: Optional[float] = None
        for word in words:
            text = _digits(str(word.get("text", ""))).strip()
            if not text:
                continue
            x0 = float(word.get("x0", 0.0))
            x1 = float(word.get("x1", x0))
            y0 = float(word.get("top", 0.0))
            if current_y is None or abs(y0 - current_y) <= 4.5:
                current.append((x0, x1, text))
                current_y = y0 if current_y is None else current_y
            else:
                lines.append((page_no, current_y, sorted(current, key=lambda item: item[0])))
                current = [(x0, x1, text)]
                current_y = y0
        if current:
            lines.append((page_no, current_y or 0.0, sorted(current, key=lambda item: item[0])))
    return lines
''',
    )

    parser = ROOT / "app/erp/pdf_statement_parser.py"
    replace_once(
        parser,
        "    import fitz\n\n    doc = fitz.open(file_path)",
        "    import pdfplumber\n\n    doc = pdfplumber.open(file_path)",
    )

    forbidden = []
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import fitz" in text or "PyMuPDF" in text:
            forbidden.append(str(path.relative_to(ROOT)))
    if forbidden:
        raise RuntimeError(f"PyMuPDF references remain: {forbidden}")

    print("pymupdf-replacement-ready")


if __name__ == "__main__":
    main()
