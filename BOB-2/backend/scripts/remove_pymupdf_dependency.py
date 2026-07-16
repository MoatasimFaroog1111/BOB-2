"""Replace the AGPL/commercial PyMuPDF runtime with permissive PDF libraries.

This migration is deterministic and idempotent so GitHub Actions can apply it to
an isolated release branch, run regressions, and commit only a successful result.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    if new in content:
        return
    if old not in content:
        raise RuntimeError(f"Expected migration block not found in {path}")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


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

    replace_once(
        ROOT / "app/security/file_validation.py",
        '''def validate_pdf(content: bytes) -> None:
    try:
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
        try:
            if document.needs_pass:
                raise FileValidationError("encrypted_pdf_not_allowed")
            if document.page_count > settings.MAX_PDF_PAGES:
                raise FileValidationError("pdf_page_limit_exceeded")
        finally:
            document.close()
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("malformed_pdf") from exc
''',
        '''def validate_pdf(content: bytes) -> None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise FileValidationError("encrypted_pdf_not_allowed")
        if len(reader.pages) > settings.MAX_PDF_PAGES:
            raise FileValidationError("pdf_page_limit_exceeded")
        # Force page-tree parsing so truncated/corrupt files fail validation.
        for page in reader.pages:
            _ = page.mediabox
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("malformed_pdf") from exc
''',
    )

    replace_once(
        ROOT / "app/erp/document_ai.py",
        '''    def _extract_pdf_text(self, path: Path) -> str:
        try:
            import fitz

            text_parts = []
            doc = fitz.open(str(path))

            for page in doc:
                text_parts.append(page.get_text())

            text = "\\n".join(text_parts).strip()

            if text:
                return text

            # Scanned PDF fallback: Render pages to images and run OCR
            import io
            from PIL import Image
            
            ocr_parts = []
            for page in doc:
                try:
                    pix = page.get_pixmap(dpi=150)
                    img_data = pix.tobytes("png")
                    img = Image.open(io.BytesIO(img_data))
                    page_text = self._ocr_image(img)
                    ocr_parts.append(page_text)
                except Exception as page_err:
                    print(f"Error OCR on page: {page_err}")
            
            return "\\n".join(ocr_parts).strip()

        except Exception as e:
            print(f"Error in _extract_pdf_text: {e}")
            return self._ocr_file(path)
''',
        '''    def _extract_pdf_text(self, path: Path) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path), strict=True)
            if reader.is_encrypted:
                return "OCR_ERROR: encrypted PDF is not supported"
            text_parts = [(page.extract_text() or "") for page in reader.pages]
            text = "\\n".join(text_parts).strip()
            if text:
                return text

            # Scanned PDF fallback: render with permissive PDFium bindings.
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

    replace_once(
        ROOT / "app/erp/pdf_statement_parser.py",
        '''def _group_pdf_lines(doc) -> List[Tuple[int, float, List[Tuple[float, str]]]]:
    grouped: List[Tuple[int, float, List[Tuple[float, str]]]] = []
    for page_no, page in enumerate(doc, start=1):
        words = page.get_text("words")
        lines: list[dict] = []
        for x0, y0, _x1, _y1, text, *_rest in words:
            clean = str(text).strip()
            if not clean:
                continue
            target = None
            for line in lines:
                if abs(line["y"] - float(y0)) <= Y_TOLERANCE:
                    target = line
                    break
            if target is None:
                target = {"y": float(y0), "words": []}
                lines.append(target)
            target["words"].append((float(x0), clean))
        for line in sorted(lines, key=lambda item: item["y"]):
            grouped.append((page_no, line["y"], sorted(line["words"], key=lambda item: item[0])))
    return grouped
''',
        '''def _group_pdf_lines(doc) -> List[Tuple[int, float, List[Tuple[float, str]]]]:
    grouped: List[Tuple[int, float, List[Tuple[float, str]]]] = []
    for page_no, page in enumerate(doc.pages, start=1):
        words = page.extract_words(
            x_tolerance=1,
            y_tolerance=Y_TOLERANCE,
            keep_blank_chars=False,
            use_text_flow=False,
        ) or []
        lines: list[dict] = []
        for word in words:
            clean = str(word.get("text", "")).strip()
            if not clean:
                continue
            x0 = float(word.get("x0", 0.0))
            y0 = float(word.get("top", 0.0))
            target = None
            for line in lines:
                if abs(line["y"] - y0) <= Y_TOLERANCE:
                    target = line
                    break
            if target is None:
                target = {"y": y0, "words": []}
                lines.append(target)
            target["words"].append((x0, clean))
        for line in sorted(lines, key=lambda item: item["y"]):
            grouped.append((page_no, line["y"], sorted(line["words"], key=lambda item: item[0])))
    return grouped
''',
    )

    replace_once(
        ROOT / "app/erp/pdf_statement_parser.py",
        '''def parse_pdf_statement(file_path: str, make_txn: Callable, ocr_image_to_text: Callable) -> List[object]:
    import fitz

    doc = fitz.open(file_path)
''',
        '''def parse_pdf_statement(file_path: str, make_txn: Callable, ocr_image_to_text: Callable) -> List[object]:
    import pdfplumber

    doc = pdfplumber.open(file_path)
''',
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
