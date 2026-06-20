import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


class GuardianDocumentAI:
    def extract_text(self, file_path: str) -> str:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return self._extract_pdf_text(path)

        if suffix in [".txt", ".csv", ".json", ".xml", ".html", ".md"]:
            return path.read_text(encoding="utf-8", errors="ignore")

        return self._extract_image_text(path)

    def _extract_pdf_text(self, path: Path) -> str:
        try:
            import fitz

            text_parts = []
            doc = fitz.open(str(path))

            for page in doc:
                text_parts.append(page.get_text())

            text = "\n".join(text_parts).strip()

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
            
            return "\n".join(ocr_parts).strip()

        except Exception as e:
            print(f"Error in _extract_pdf_text: {e}")
            return self._ocr_file(path)

    def _extract_image_text(self, path: Path) -> str:
        return self._ocr_file(path)

    def _ocr_file(self, path: Path) -> str:
        try:
            from PIL import Image
            image = Image.open(str(path))
            return self._ocr_image(image)
        except Exception as e:
            return f"OCR_ERROR: {e}"

    def _ocr_image(self, image) -> str:
        try:
            import pytesseract
            import os
            from PIL import ImageEnhance, Image

            # Preprocess image for OCR to handle low quality / scanned documents
            try:
                # Convert to grayscale
                img = image.convert('L')
                # Resize 2x
                w, h = img.size
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = 1 # Fallback to ANTIALIAS/LANCZOS value in older Pillow versions
                
                img = img.resize((w * 2, h * 2), resample)
                # Enhance Contrast
                img = ImageEnhance.Contrast(img).enhance(2.5)
                # Enhance Sharpness
                img = ImageEnhance.Sharpness(img).enhance(2.0)
            except Exception as prep_err:
                print(f"[OCR Preprocessing] Failed: {prep_err}")
                img = image

            # Set tesseract path on Windows if not already in PATH
            tesseract_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe")
            ]
            for t_path in tesseract_paths:
                if os.path.exists(t_path):
                    pytesseract.pytesseract.tesseract_cmd = t_path
                    break

            return pytesseract.image_to_string(img, lang="eng+ara")
        except Exception as e:
            return f"OCR_ERROR: {e}"

    @staticmethod
    def _clean_text(text: str) -> str:
        return text.replace("\u200f", "").replace("\u200e", "").strip()

    @staticmethod
    def _parse_amount(value: str) -> Optional[float]:
        try:
            return float(value.replace(",", "").strip())
        except Exception:
            return None

    @staticmethod
    def _first_regex(text: str, patterns: list[str], flags=re.IGNORECASE) -> Optional[str]:
        for pattern in patterns:
            match = re.search(pattern, text, flags)
            if match:
                return match.group(1).strip()
        return None

    def detect_document_class(self, text: str, file_path: str = "") -> str:
        text_l = text.lower()
        name_l = Path(file_path).name.lower()

        receipt_markers = [
            "account transaction details receipt",
            "riyad bank",
            "riyadh bank",
            "processing date",
            "transaction details",
            "utility bill payment",
            "residents",
            "biller id",
            "mol,sub",
            "خدمات المقيمين",
            "وزارة العمل",
            "سداد",
        ]

        if any(marker in text_l for marker in receipt_markers) or "سداد" in name_l:
            return "receipt"

        invoice_markers = [
            "invoice",
            "tax invoice",
            "فاتورة",
            "vat",
            "total amount",
            "invoice number",
        ]

        if any(marker in text_l for marker in invoice_markers):
            return "invoice"

        return "unknown"

    def extract_receipt_fields(self, text: str) -> Dict[str, Any]:
        clean = self._clean_text(text)

        amount_text = self._first_regex(
            clean,
            [
                r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س)",
                r"Amount\s*\n.*?\n([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)",
                r"Total\s*(?:Amount)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)",
            ],
        )

        amount = self._parse_amount(amount_text) if amount_text else None

        processing_date = self._first_regex(
            clean,
            [
                r"Processing Date\s*\n.*?\n([0-9]{2}-[0-9]{2}-[0-9]{4})",
                r"\b([0-9]{2}-[0-9]{2}-[0-9]{4})\b",
                r"\b([0-9]{2}/[0-9]{2}/[0-9]{4})\b",
            ],
        )

        iban = self._first_regex(
            clean,
            [
                r"\b(SA[0-9]{22})\b",
            ],
        )

        ref_number = self._first_regex(
            clean,
            [
                r"REF\s*([A-Z0-9]+)",
                r"REF\s+([0-9]{8,})",
                r"REF\s*\n?([A-Z0-9]{8,})",
            ],
        )

        sub_number = self._first_regex(
            clean,
            [
                r"SUB\s*([0-9]{6,})",
                r"SUB([0-9]{6,})",
            ],
        )

        biller_id = self._first_regex(
            clean,
            [
                r"BILLER\s*ID\s*:\s*([0-9]+)",
                r"BILLER ID:\s*([0-9]+)",
            ],
        )

        cheque_or_account_number = self._first_regex(
            clean,
            [
                r"Cheque No\s*\n([0-9]+)",
                r"Account Number\s*\n([0-9]+)",
            ],
        )

        service_type = None
        service_name = None

        if re.search(r"\bMOL\b|وزارة العمل|BILLER\s*ID\s*:\s*050", clean, re.IGNORECASE):
            service_type = "MOL"
            service_name = "وزارة العمل / Work Permit Payment"

        elif re.search(r"\bRESIDENTS\b|خدمات المقيمين|BILLER\s*ID\s*:\s*090", clean, re.IGNORECASE):
            service_type = "RESIDENTS"
            service_name = "خدمات المقيمين / Resident Services"

        elif re.search(r"UTILITY BILL PAYMENT", clean, re.IGNORECASE):
            service_type = "UTILITY_BILL_PAYMENT"
            service_name = "Utility Bill Payment"

        bank_name = None
        if re.search(r"Riyad Bank|Riyadh Bank", clean, re.IGNORECASE):
            bank_name = "Riyad Bank"

        narration = self._extract_receipt_narration(clean)

        return {
            "document_class": "receipt",
            "receipt_type": "bank_receipt",
            "bank_name": bank_name,
            "iban": iban,
            "account_number": cheque_or_account_number,
            "processing_date": processing_date,
            "transaction_ref": ref_number,
            "sub_number": sub_number,
            "biller_id": biller_id,
            "service_type": service_type,
            "service_name": service_name,
            "amount": amount,
            "total_amount": amount,
            "currency_guess": "SAR",
            "narration": narration,
            "invoice_number": None,
            "invoice_date": processing_date,
            "supplier_name": service_name or bank_name,
            "taxable_amount": None,
            "vat_amount": None,
            "nontaxable_amount": amount,
        }

    def _extract_receipt_narration(self, text: str) -> Optional[str]:
        match = re.search(
            r"(RESIDENTS.*?|MOL.*?|UTILITY BILL PAYMENT.*?)(?:Narration|Cheque No|Transaction Details)",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if not match:
            return None

        narration = match.group(1)
        narration = re.sub(r"\s+", " ", narration).strip()
        return narration[:500]

    def extract_invoice_fields(self, text: str) -> Dict[str, Any]:
        clean = self._clean_text(text)

        invoice_number = self._first_regex(
            clean,
            [
                r"Invoice Number\s*[^\w]*([A-Z0-9\-\/]+)",
                r"الفاتورة رقم\s*([A-Z0-9\-\/]+)",
                r"\b(SA[0-9]{4,})\b",
            ],
        )

        invoice_date = self._first_regex(
            clean,
            [
                r"Invoice Issue Date\s*[^\d]*([0-9]{2}/[0-9]{2}/[0-9]{4})",
                r"Invoice Date\s*[^\d]*([0-9]{2}/[0-9]{2}/[0-9]{4})",
                r"\b([0-9]{2}/[0-9]{2}/[0-9]{4})\b",
            ],
        )

        taxable_amount_text = self._first_regex(
            clean,
            [
                r"Untaxed\s+Amount\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"Taxable\s+Amount\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"Subtotal\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"المجموع الفرعي\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"المبلغ الخاضع للضريبة\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
            ],
            flags=re.IGNORECASE | re.DOTALL,
        )

        vat_amount_text = self._first_regex(
            clean,
            [
                r"VAT\s+Taxes\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"VAT\s+Tax\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"The Tax.*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"VAT\s*\n.*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"الضريبة\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"ضريبة القيمة المضافة\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
            ],
            flags=re.IGNORECASE | re.DOTALL,
        )

        nontaxable_amount_text = self._first_regex(
            clean,
            [
                r"Nontaxable Amount.*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
            ],
            flags=re.IGNORECASE | re.DOTALL,
        )

        total_amount_text = self._first_regex(
            clean,
            [
                r"Total Amount.*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"Total\s*:\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"Total\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"الإجمالي.*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
                r"الاجمالي.*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س))?",
            ],
            flags=re.IGNORECASE | re.DOTALL,
        )

        taxable_amount = self._parse_amount(taxable_amount_text) if taxable_amount_text else None
        vat_amount = self._parse_amount(vat_amount_text) if vat_amount_text else None
        nontaxable_amount = self._parse_amount(nontaxable_amount_text) if nontaxable_amount_text else None
        total_amount = self._parse_amount(total_amount_text) if total_amount_text else None

        supplier_name = self.detect_supplier_name(clean)

        return {
            "document_class": "invoice",
            "supplier_name": supplier_name,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "taxable_amount": taxable_amount,
            "vat_amount": vat_amount,
            "nontaxable_amount": nontaxable_amount,
            "total_amount": total_amount,
            "currency_guess": "SAR",
        }

    def detect_supplier_name(self, text: str) -> Optional[str]:
        text_l = text.lower()

        if "yesatlas" in text_l or "modarby" in text_l or "findcourse" in text_l:
            return "Atlas / Modarby"

        if "riyad bank" in text_l or "riyadh bank" in text_l:
            return "Riyad Bank"

        return None

    def analyze_document(self, file_path: str) -> Dict[str, Any]:
        raw_text = self.extract_text(file_path)
        document_class = self.detect_document_class(raw_text, file_path=file_path)

        if document_class == "receipt":
            fields = self.extract_receipt_fields(raw_text)
        elif document_class == "invoice":
            fields = self.extract_invoice_fields(raw_text)
        else:
            fields = {
                "document_class": "unknown",
                "supplier_name": None,
                "invoice_number": None,
                "invoice_date": None,
                "vat_amount": None,
                "total_amount": None,
                "currency_guess": "SAR",
            }

        warnings = []

        if raw_text.startswith("OCR_ERROR:"):
            warnings.append("ocr_engine_missing_or_failed")

        if not fields.get("supplier_name"):
            warnings.append("supplier_name_not_detected")

        if fields.get("total_amount") is None:
            warnings.append("total_amount_not_detected")

        if fields.get("vat_amount") is None and fields.get("document_class") == "invoice":
            warnings.append("vat_amount_not_detected")

        return {
            "status": "analyzed",
            "source_file": str(file_path),
            "document_type": self.detect_document_type(file_path),
            "document_class": fields.get("document_class", document_class),
            "fields": fields,
            "warnings": warnings,
            "safe_to_post": False,
            "next_step": "Review extracted fields, then create accounting preview.",
            "raw_text_preview": raw_text[:4000],
        }

    def detect_document_type(self, file_path: str) -> str:
        suffix = Path(file_path).suffix.lower()

        if suffix == ".pdf":
            return "pdf_invoice_or_document"

        if suffix in [".png", ".jpg", ".jpeg", ".webp"]:
            return "image_invoice_or_document"

        return "unknown_document"
