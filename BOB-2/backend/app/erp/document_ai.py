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
                # Resize 1.5x (balances OCR accuracy vs speed)
                w, h = img.size
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = 1  # Fallback for older Pillow versions
                
                img = img.resize((int(w * 1.5), int(h * 1.5)), resample)
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

        # SADAD / Government receipts
        sadad_markers = [
            "سداد", "sadad", "biller id", "payment confirmation",
            "تأكيد الدفع", "إيصال دفع",
        ]
        if any(m in text_l for m in sadad_markers) or "سداد" in name_l:
            return "sadad_receipt"

        # Bank receipts
        receipt_markers = [
            "account transaction details receipt",
            "riyad bank", "riyadh bank", "rajhi bank", "الراجحي",
            "processing date", "transaction details",
            "utility bill payment", "residents", "mol,sub",
            "خدمات المقيمين", "وزارة العمل",
            "إيصال", "receipt",
        ]
        if any(m in text_l for m in receipt_markers):
            return "receipt"

        # Payment vouchers
        voucher_markers = [
            "payment voucher", "سند صرف", "سند قبض",
            "payment order", "أمر صرف",
        ]
        if any(m in text_l for m in voucher_markers):
            return "payment_voucher"

        # Purchase orders
        po_markers = [
            "purchase order", "أمر شراء", "طلب شراء",
            "p.o. number", "po number", "order confirmation",
        ]
        if any(m in text_l for m in po_markers):
            return "purchase_order"

        # Bank statements
        statement_markers = [
            "bank statement", "كشف حساب", "كشف بنك",
            "account statement", "statement of account",
            "opening balance", "closing balance",
            "الرصيد الافتتاحي", "الرصيد الختامي",
        ]
        if any(m in text_l for m in statement_markers):
            return "bank_statement"

        # ZATCA tax invoices (check before generic invoice)
        zatca_markers = [
            "zatca", "هيئة الزكاة", "الزكاة والضريبة",
            "tax invoice", "فاتورة ضريبية",
            "الرقم الضريبي", "tax identification",
            "qr code", "رمز الاستجابة",
        ]
        if any(m in text_l for m in zatca_markers):
            return "zatca_invoice"

        # Vendor bills
        vendor_markers = [
            "vendor bill", "فاتورة مورد", "فاتورة مشتريات",
            "supplier invoice", "bill to",
        ]
        if any(m in text_l for m in vendor_markers):
            return "vendor_bill"

        # Generic invoices
        invoice_markers = [
            "invoice", "فاتورة", "vat",
            "total amount", "invoice number",
            "رقم الفاتورة", "المبلغ الإجمالي",
        ]
        if any(m in text_l for m in invoice_markers):
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

    _AMT_SUFFIX = r"(?:\s*(?:SAR|SR|sR|S\.R\.|R\.S\.|ر\.س|ريال))?"
    _AMT_NUM = r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)" + _AMT_SUFFIX

    def _extract_common_fields(self, text: str) -> Dict[str, Any]:
        """Extract fields common across all document types."""
        clean = self._clean_text(text)

        vat_number = self._first_regex(clean, [
            r"(?:VAT|Tax|الرقم الضريبي|TIN|Tax ID)\s*(?:Number|No|#|:)?\s*([0-9]{15})",
            r"\b(3[0-9]{14})\b",
        ])

        iban = self._first_regex(clean, [r"\b(SA[0-9]{22})\b"])
        account_number = self._first_regex(clean, [
            r"Account\s*(?:Number|No|#)\s*:?\s*([0-9]{10,})",
            r"رقم الحساب\s*:?\s*([0-9]{10,})",
        ])

        currency = "SAR"
        if re.search(r"\b(?:USD|\$|دولار)\b", clean, re.IGNORECASE):
            currency = "USD"
        elif re.search(r"\b(?:EUR|€|يورو)\b", clean, re.IGNORECASE):
            currency = "EUR"
        elif re.search(r"\b(?:AED|درهم)\b", clean, re.IGNORECASE):
            currency = "AED"

        customer_name = self._first_regex(clean, [
            r"(?:Customer|العميل|Bill To|Ship To)\s*:?\s*(.+?)(?:\n|$)",
        ])

        transaction_ref = self._first_regex(clean, [
            r"(?:Reference|Ref|المرجع|رقم المرجع)\s*(?:No|#|:)?\s*([A-Z0-9\-\/]{4,})",
        ])

        payment_date = self._first_regex(clean, [
            r"(?:Payment Date|تاريخ الدفع|تاريخ السداد)\s*:?\s*([0-9]{2}[/\-][0-9]{2}[/\-][0-9]{4})",
        ])

        po_number = self._first_regex(clean, [
            r"(?:P\.?O\.?|Purchase Order|أمر شراء)\s*(?:Number|No|#|:)?\s*([A-Z0-9\-\/]{3,})",
        ])

        due_date = self._first_regex(clean, [
            r"(?:Due Date|تاريخ الاستحقاق|Maturity)\s*:?\s*([0-9]{2}[/\-][0-9]{2}[/\-][0-9]{4})",
        ])

        return {
            "vat_number": vat_number,
            "iban": iban,
            "account_number": account_number,
            "currency": currency,
            "customer_name": customer_name,
            "transaction_reference": transaction_ref,
            "payment_date": payment_date,
            "po_number": po_number,
            "due_date": due_date,
        }

    def extract_invoice_fields(self, text: str) -> Dict[str, Any]:
        clean = self._clean_text(text)
        common = self._extract_common_fields(text)

        invoice_number = self._first_regex(
            clean,
            [
                r"Invoice\s*(?:Number|No|#)\s*[^\w]*([A-Z0-9\-\/]+)",
                r"رقم الفاتورة\s*:?\s*([A-Z0-9\-\/]+)",
                r"الفاتورة رقم\s*([A-Z0-9\-\/]+)",
            ],
        )

        invoice_date = self._first_regex(
            clean,
            [
                r"Invoice\s*(?:Issue)?\s*Date\s*[^\d]*([0-9]{2}[/\-][0-9]{2}[/\-][0-9]{4})",
                r"تاريخ الفاتورة\s*:?\s*([0-9]{2}[/\-][0-9]{2}[/\-][0-9]{4})",
                r"\b([0-9]{2}/[0-9]{2}/[0-9]{4})\b",
                r"\b([0-9]{4}-[0-9]{2}-[0-9]{2})\b",
            ],
        )

        taxable_amount_text = self._first_regex(
            clean,
            [
                r"Untaxed\s+Amount\s+" + self._AMT_NUM,
                r"Taxable\s+Amount\s+" + self._AMT_NUM,
                r"Subtotal\s+" + self._AMT_NUM,
                r"المجموع الفرعي\s+" + self._AMT_NUM,
                r"المبلغ الخاضع للضريبة\s+" + self._AMT_NUM,
            ],
            flags=re.IGNORECASE | re.DOTALL,
        )

        vat_amount_text = self._first_regex(
            clean,
            [
                r"VAT\s+(?:Tax(?:es)?)?\s*" + self._AMT_NUM,
                r"The Tax.*?" + self._AMT_NUM,
                r"الضريبة\s+" + self._AMT_NUM,
                r"ضريبة القيمة المضافة\s+" + self._AMT_NUM,
            ],
            flags=re.IGNORECASE | re.DOTALL,
        )

        nontaxable_amount_text = self._first_regex(
            clean,
            [r"Nontaxable Amount.*?" + self._AMT_NUM],
            flags=re.IGNORECASE | re.DOTALL,
        )

        total_amount_text = self._first_regex(
            clean,
            [
                r"Total\s*(?:Amount)?\s*:?\s*" + self._AMT_NUM,
                r"الإجمالي.*?" + self._AMT_NUM,
                r"الاجمالي.*?" + self._AMT_NUM,
                r"المبلغ الإجمالي.*?" + self._AMT_NUM,
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
            "customer_name": common.get("customer_name"),
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "due_date": common.get("due_date"),
            "taxable_amount": taxable_amount,
            "vat_amount": vat_amount,
            "nontaxable_amount": nontaxable_amount,
            "total_amount": total_amount,
            "currency": common.get("currency", "SAR"),
            "vat_number": common.get("vat_number"),
            "iban": common.get("iban"),
            "account_number": common.get("account_number"),
            "transaction_reference": common.get("transaction_reference"),
            "payment_date": common.get("payment_date"),
            "po_number": common.get("po_number"),
            # Legacy key kept for backward-compat
            "currency_guess": common.get("currency", "SAR"),
        }

    def extract_payment_voucher_fields(self, text: str) -> Dict[str, Any]:
        clean = self._clean_text(text)
        common = self._extract_common_fields(text)
        amount_text = self._first_regex(
            clean,
            [r"(?:Amount|المبلغ)\s*:?\s*" + self._AMT_NUM],
            flags=re.IGNORECASE,
        )
        return {
            "document_class": "payment_voucher",
            "supplier_name": self.detect_supplier_name(clean),
            "total_amount": self._parse_amount(amount_text) if amount_text else None,
            **common,
        }

    def extract_purchase_order_fields(self, text: str) -> Dict[str, Any]:
        clean = self._clean_text(text)
        common = self._extract_common_fields(text)
        total_text = self._first_regex(
            clean,
            [r"(?:Total|الإجمالي|Grand Total)\s*:?\s*" + self._AMT_NUM],
            flags=re.IGNORECASE,
        )
        return {
            "document_class": "purchase_order",
            "supplier_name": self.detect_supplier_name(clean),
            "total_amount": self._parse_amount(total_text) if total_text else None,
            **common,
        }

    def extract_bank_statement_fields(self, text: str) -> Dict[str, Any]:
        clean = self._clean_text(text)
        common = self._extract_common_fields(text)
        return {
            "document_class": "bank_statement",
            "supplier_name": self.detect_supplier_name(clean),
            "total_amount": None,
            **common,
        }

    def detect_supplier_name(self, text: str) -> Optional[str]:
        text_l = text.lower()

        known = [
            (["yesatlas", "modarby", "findcourse"], "Atlas / Modarby"),
            (["riyad bank", "riyadh bank"], "Riyad Bank"),
            (["rajhi", "الراجحي"], "Al Rajhi Bank"),
            (["الأهلي", "ahli", "snb"], "Saudi National Bank"),
            (["stc", "اس تي سي", "الاتصالات السعودية"], "STC"),
            (["aramco", "أرامكو"], "Saudi Aramco"),
            (["sabic", "سابك"], "SABIC"),
        ]
        for markers, name in known:
            if any(m in text_l for m in markers):
                return name

        supplier_regex = self._first_regex(text, [
            r"(?:Supplier|Vendor|المورد|اسم المورد)\s*:?\s*(.+?)(?:\n|$)",
        ])
        return supplier_regex

    def analyze_document(self, file_path: str) -> Dict[str, Any]:
        raw_text = self.extract_text(file_path)
        document_class = self.detect_document_class(raw_text, file_path=file_path)

        _extractors = {
            "receipt": self.extract_receipt_fields,
            "sadad_receipt": self.extract_receipt_fields,
            "invoice": self.extract_invoice_fields,
            "zatca_invoice": self.extract_invoice_fields,
            "vendor_bill": self.extract_invoice_fields,
            "payment_voucher": self.extract_payment_voucher_fields,
            "purchase_order": self.extract_purchase_order_fields,
            "bank_statement": self.extract_bank_statement_fields,
        }

        extractor = _extractors.get(document_class)
        if extractor:
            fields = extractor(raw_text)
            fields["document_class"] = document_class
        else:
            common = self._extract_common_fields(raw_text)
            fields = {
                "document_class": "unknown",
                "supplier_name": self.detect_supplier_name(self._clean_text(raw_text)),
                "invoice_number": None,
                "invoice_date": None,
                "vat_amount": None,
                "total_amount": None,
                "currency": common.get("currency", "SAR"),
                "currency_guess": common.get("currency", "SAR"),
                **common,
            }

        warnings: list[str] = []

        if raw_text.startswith("OCR_ERROR:"):
            warnings.append("ocr_engine_missing_or_failed")

        if not fields.get("supplier_name"):
            warnings.append("supplier_name_not_detected")

        if fields.get("total_amount") is None:
            warnings.append("total_amount_not_detected")

        if fields.get("vat_amount") is None and document_class in ("invoice", "zatca_invoice", "vendor_bill"):
            warnings.append("vat_amount_not_detected")

        if not fields.get("vat_number") and document_class in ("zatca_invoice",):
            warnings.append("vat_number_not_detected")

        if not fields.get("invoice_number") and document_class in ("invoice", "zatca_invoice", "vendor_bill"):
            warnings.append("invoice_number_not_detected")

        return {
            "status": "analyzed",
            "source_file": str(file_path),
            "document_type": self.detect_document_type(file_path),
            "document_class": document_class,
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
