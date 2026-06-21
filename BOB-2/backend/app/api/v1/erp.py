import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.core import ERPConnection
from app.security.file_validation import validate_upload_files, sanitize_filename, FileValidationError
from app.erp.factory import get_erp_provider
from app.security.encryption import encrypt_value, decrypt_value
from app.erp.discovery import run_discovery_orchestrator, load_financial_kb
from app.erp.document_ai import GuardianDocumentAI
from app.erp.odoo_cache import get_cached, set_cached, invalidate as invalidate_odoo_cache
from app.erp.bank_reconciliation import reconcile as bank_reconcile, reconcile_with_odoo_data

router = APIRouter()


class ERPConnectionRequest(BaseModel):
    provider: str = Field(default="odoo")
    url: str
    db: str
    username: str
    password: str


class ERPConnectionResponse(BaseModel):
    id: int
    provider: str
    url: str
    db: str
    username: str
    is_active: bool


@router.post("/test-connection")
def test_erp_connection(payload: ERPConnectionRequest):
    try:
        erp = get_erp_provider(
            provider=payload.provider,
            url=payload.url,
            db=payload.db,
            username=payload.username,
            password=payload.password,
        )
        return erp.test_connection()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection test failed: {str(e)}"
        )


@router.post("/connection", response_model=ERPConnectionResponse)
def save_erp_connection(payload: ERPConnectionRequest, db: Session = Depends(get_db)):
    try:
        erp = get_erp_provider(
            provider=payload.provider,
            url=payload.url,
            db=payload.db,
            username=payload.username,
            password=payload.password,
        )
        test_result = erp.test_connection()
        if not test_result.get("connected"):
            raise ValueError("Authentication failed on the ERP provider.")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot save connection: verification failed ({str(e)})"
        )

    secret_data = {
        "username": payload.username,
        "password": payload.password
    }
    encrypted_secret = encrypt_value(json.dumps(secret_data))

    conn = db.query(ERPConnection).filter(ERPConnection.organization_id == 1).first()
    if conn:
        conn.provider = payload.provider
        conn.base_url = payload.url
        conn.database_name = payload.db
        conn.encrypted_secret_ref = encrypted_secret
        conn.is_active = True
    else:
        conn = ERPConnection(
            organization_id=1,
            provider=payload.provider,
            base_url=payload.url,
            database_name=payload.db,
            auth_type="password",
            encrypted_secret_ref=encrypted_secret,
            is_active=True
        )
        db.add(conn)

    db.commit()
    db.refresh(conn)

    invalidate_odoo_cache(conn.base_url, conn.database_name or "")

    return ERPConnectionResponse(
        id=conn.id,
        provider=conn.provider,
        url=conn.base_url,
        db=conn.database_name or "",
        username=payload.username,
        is_active=conn.is_active
    )


@router.get("/connection", response_model=ERPConnectionResponse)
def get_erp_connection(db: Session = Depends(get_db)):
    conn = db.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No saved active ERP connection found."
        )

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username", "")
    except Exception:
        username = ""

    return ERPConnectionResponse(
        id=conn.id,
        provider=conn.provider,
        url=conn.base_url,
        db=conn.database_name or "",
        username=username,
        is_active=conn.is_active
    )


@router.post("/test-saved")
def test_saved_connection(db: Session = Depends(get_db)):
    conn = db.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No saved active ERP connection found."
        )

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt connection credentials."
        )

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )
        return erp.test_connection()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection test on saved credentials failed: {str(e)}"
        )


@router.get("/company-info-saved")
def get_saved_company_info(db: Session = Depends(get_db)):
    conn = db.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No saved active ERP connection found."
        )

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt connection credentials."
        )

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )
        return erp.get_company_info()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch company info: {str(e)}"
        )


@router.post("/discover")
def trigger_erp_discovery(db: Session = Depends(get_db)):
    conn = db.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No saved active ERP connection found. Please connect to an ERP first."
        )

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt connection credentials."
        )

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )
        return run_discovery_orchestrator(erp)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ERP Discovery failed: {str(e)}"
        )


@router.get("/discovery")
def get_discovered_kb():
    kb = load_financial_kb()
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No discovered financial structure found. Please trigger discovery first."
        )
    return kb


@router.post("/upload-documents")
def upload_documents(files: List[UploadFile] = File(...)):
    results = []
    ai = GuardianDocumentAI()

    for file in files:
        try:
            suffix = Path(file.filename).suffix if file.filename else ""
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                shutil.copyfileobj(file.file, temp_file)
                temp_path = temp_file.name

            try:
                analysis = ai.analyze_document(temp_path)
                analysis["original_filename"] = file.filename

                results.append({
                    "filename": file.filename,
                    "status": "analyzed",
                    "result": analysis,
                })
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": str(e),
            })

    return {
        "status": "batch_analyzed",
        "file_count": len(files),
        "success_count": len([x for x in results if x["status"] == "analyzed"]),
        "error_count": len([x for x in results if x["status"] == "error"]),
        "results": results,
    }


@router.post("/match-documents")
def match_documents(
    files: List[UploadFile] = File(...),
    db_session: Session = Depends(get_db)
):
    import re
    import difflib
    from datetime import datetime

    def _safe_text(value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _normalize_text(value) -> str:
        text = _safe_text(value).lower()
        text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
        text = re.sub(r"[^\w\u0600-\u06FF\s\-\/\.]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _extract_number(value):
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value)
        text = text.replace(",", "")
        text = re.sub(r"[^\d\.\-]", "", text)

        if not text or text in ["-", ".", "-."]:
            return None

        try:
            return float(text)
        except Exception:
            return None

    def _amount_score(doc_amount, move_amount) -> float:
        doc_val = _extract_number(doc_amount)
        move_val = _extract_number(move_amount)

        if doc_val is None or move_val is None:
            return 0.0

        doc_val = abs(doc_val)
        move_val = abs(move_val)

        if doc_val == 0 and move_val == 0:
            return 1.0

        if doc_val == 0 or move_val == 0:
            return 0.0

        diff = abs(doc_val - move_val)
        tolerance = max(1.0, move_val * 0.01)

        if diff <= tolerance:
            return 1.0

        ratio = min(doc_val, move_val) / max(doc_val, move_val)

        if ratio >= 0.99:
            return 0.95
        if ratio >= 0.97:
            return 0.85
        if ratio >= 0.95:
            return 0.75
        if ratio >= 0.90:
            return 0.55

        return 0.0

    def _normalize_date(date_value: str) -> str:
        if not date_value:
            return ""

        date_str = str(date_value).strip()
        
        # 1. Clean Eastern Arabic numerals to Western Arabic numerals (e.g., ٠-٩ to 0-9)
        arabic_digits = "٠١٢٣٤٥٦٧٨٩"
        english_digits = "0123456789"
        for a, e in zip(arabic_digits, english_digits):
            date_str = date_str.replace(a, e)

        # Remove day of week
        date_str = re.sub(r'\b(الأحد|الأثنين|الثلاثاء|الأربعاء|الخميس|الجمعة|السبت|Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)\b', '', date_str, flags=re.IGNORECASE)

        # Translate English/Arabic months to numbers
        months_map = {
            "january": "01", "february": "02", "march": "03", "april": "04", "may": "05", "june": "06",
            "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12",
            "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06",
            "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
            "يناير": "01", "فبراير": "02", "مارس": "03", "أبريل": "04", "ابريل": "04", "مايو": "05", "يونيو": "06", "يونيه": "06",
            "يوليو": "07", "يوليه": "07", "أغسطس": "08", "اغسطس": "08", "سبتمبر": "09", "أكتوبر": "10", "اكتوبر": "10",
            "نوفمبر": "11", "ديسمبر": "12"
        }
        
        date_str_lower = date_str.lower()
        for month_name, month_num in months_map.items():
            if month_name in date_str_lower:
                match_day_year = re.search(r'\b(\d{1,2})\b.*\b(\d{4})\b', date_str)
                if match_day_year:
                    day = int(match_day_year.group(1))
                    year = int(match_day_year.group(2))
                    try:
                        return datetime(year, int(month_num), day).strftime("%Y-%m-%d")
                    except Exception:
                        pass

        # Try YYYY-MM-DD or YYYY/MM/DD
        match_yyyy = re.search(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', date_str)
        if match_yyyy:
            year = int(match_yyyy.group(1))
            month = int(match_yyyy.group(2))
            day = int(match_yyyy.group(3))
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except Exception:
                pass

        # Try DD-MM-YYYY or DD/MM/YYYY
        match_dd = re.search(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b', date_str)
        if match_dd:
            val1 = int(match_dd.group(1))
            val2 = int(match_dd.group(2))
            year = int(match_dd.group(3))
            if val2 > 12:
                day = val2
                month = val1
            else:
                day = val1
                month = val2
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except Exception:
                pass

        return ""

    def _date_score(doc_date, move_date) -> float:
        norm_doc = _normalize_date(doc_date)
        norm_move = _normalize_date(move_date)

        if not norm_doc or not norm_move:
            return 0.0

        if norm_doc == norm_move:
            return 1.0

        try:
            d1 = datetime.strptime(norm_doc, "%Y-%m-%d")
            d2 = datetime.strptime(norm_move, "%Y-%m-%d")
            days_diff = abs((d1 - d2).days)

            if days_diff <= 1:
                return 0.85
            if days_diff <= 3:
                return 0.65
            if days_diff <= 7:
                return 0.35
        except Exception:
            return 0.0

        return 0.0

    def _reference_score(doc_text: str, move: dict) -> float:
        doc_text_norm = _normalize_text(doc_text)

        refs = [
            move.get("name"),
            move.get("ref"),
            move.get("payment_reference"),
        ]

        best = 0.0

        for ref in refs:
            ref_text = _normalize_text(ref)
            if not ref_text:
                continue

            if ref_text in doc_text_norm:
                best = max(best, 1.0)
                continue

            ref_tokens = [x for x in re.findall(r"[\w\-\/]+", ref_text) if len(x) >= 4]
            if ref_tokens:
                matched = sum(1 for token in ref_tokens if token in doc_text_norm)
                token_ratio = matched / len(ref_tokens)
                best = max(best, token_ratio)

        return min(best, 1.0)

    def _description_score(doc_text: str, move: dict) -> float:
        doc_norm = _normalize_text(doc_text)

        journal = move.get("journal_id")
        journal_name = journal[1] if isinstance(journal, list) and len(journal) > 1 else ""

        system_desc = " ".join([
            _safe_text(move.get("name")),
            _safe_text(move.get("ref")),
            _safe_text(move.get("payment_reference")),
            _safe_text(journal_name),
        ])

        sys_norm = _normalize_text(system_desc)

        if not doc_norm or not sys_norm:
            return 0.0

        sys_words = [w for w in re.findall(r"[\w\u0600-\u06FF\-\/]+", sys_norm) if len(w) >= 3]

        overlap_ratio = 0.0
        if sys_words:
            matched_count = sum(1 for w in sys_words if w in doc_norm)
            overlap_ratio = matched_count / len(sys_words)

        char_ratio = difflib.SequenceMatcher(None, doc_norm[:1200], sys_norm).ratio()

        return min(max(overlap_ratio, char_ratio), 1.0)

    def _partner_score(fields: dict, doc_text: str, move: dict) -> float:
        doc_partner = (
            fields.get("vendor_name")
            or fields.get("supplier_name")
            or fields.get("customer_name")
            or fields.get("partner_name")
            or fields.get("company_name")
            or ""
        )

        doc_blob = _normalize_text(f"{doc_partner} {doc_text}")

        partner = move.get("partner_id")
        partner_name = ""
        if isinstance(partner, list) and len(partner) > 1:
            partner_name = partner[1]

        partner_norm = _normalize_text(partner_name)

        if not partner_norm or not doc_blob:
            return 0.0

        if partner_norm in doc_blob:
            return 1.0

        partner_words = [w for w in re.findall(r"[\w\u0600-\u06FF]+", partner_norm) if len(w) >= 3]
        if not partner_words:
            return 0.0

        matched = sum(1 for w in partner_words if w in doc_blob)
        return min(matched / len(partner_words), 1.0)

    def _build_confidence_label(score: float) -> str:
        if score >= 85:
            return "high"
        if score >= 65:
            return "medium"
        if score >= 45:
            return "low"
        return "weak"

    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    erp = get_erp_provider(
        provider=conn.provider,
        url=conn.base_url,
        db=conn.database_name or "",
        username=username,
        password=password,
    )

    ai = GuardianDocumentAI()
    results = []

    print(f"=== START MATCHING DIAGNOSTIC FOR {len(files)} FILES ===")
    for file in files:
        try:
            suffix = Path(file.filename).suffix if file.filename else ""
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                shutil.copyfileobj(file.file, temp_file)
                temp_path = temp_file.name

            try:
                analysis = ai.analyze_document(temp_path)
                fields = analysis.get("fields") or {}

                doc_amount = (
                    fields.get("total_amount")
                    or fields.get("amount_total")
                    or fields.get("total")
                    or fields.get("grand_total")
                    or fields.get("invoice_total")
                    or fields.get("payment_amount")
                )

                doc_date = (
                    fields.get("invoice_date")
                    or fields.get("date")
                    or fields.get("processing_date")
                    or fields.get("payment_date")
                    or fields.get("transaction_date")
                )

                doc_class = analysis.get("document_class") or fields.get("document_class") or "unknown"
                doc_desc = analysis.get("raw_text_preview") or analysis.get("raw_text") or ""

                print(f"[DIAGNOSTIC] File: {file.filename}")
                print(f"[DIAGNOSTIC] Extracted Class: {doc_class}")
                print(f"[DIAGNOSTIC] Extracted Amount: {doc_amount} (Type: {type(doc_amount)})")
                print(f"[DIAGNOSTIC] Initial Extracted Date: {doc_date}")

                if not doc_date:
                    text_month_pat = r'\b(\d{1,2})\s+(يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يونيه|يوليو|يوليه|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b'
                    match = re.search(text_month_pat, doc_desc, re.IGNORECASE)
                    if match:
                        doc_date = match.group(0)
                        print(f"[DIAGNOSTIC] Fallback Date Match (text month): {doc_date}")
                    else:
                        match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", doc_desc)
                        if match:
                            doc_date = match.group(0)
                            print(f"[DIAGNOSTIC] Fallback Date Match (DD-MM-YYYY): {doc_date}")
                        else:
                            match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", doc_desc)
                            if match:
                                doc_date = match.group(0)
                                print(f"[DIAGNOSTIC] Fallback Date Match (YYYY-MM-DD): {doc_date}")

                norm_doc_date = _normalize_date(doc_date)
                print(f"[DIAGNOSTIC] Normalized Doc Date: '{norm_doc_date}'")

                matched_moves = []
                moves = []
                if doc_amount is not None:
                    doc_val = abs(float(doc_amount))
                    min_val = doc_val * 0.99
                    max_val = doc_val * 1.01
                    
                    # Search in both draft and posted states
                    domain = [
                        ("state", "in", ["draft", "posted"]),
                        ("amount_total", ">=", min_val),
                        ("amount_total", "<=", max_val)
                    ]
                    
                    # Search matching accounting date or invoice/bill date with a 4-day window for clearing delay
                    if norm_doc_date:
                        from datetime import datetime, timedelta
                        try:
                            doc_dt = datetime.strptime(norm_doc_date, "%Y-%m-%d")
                            min_date = (doc_dt - timedelta(days=4)).strftime("%Y-%m-%d")
                            max_date = (doc_dt + timedelta(days=4)).strftime("%Y-%m-%d")
                        except Exception:
                            min_date = norm_doc_date
                            max_date = norm_doc_date
                        
                        domain.extend([
                            "|",
                            "&", ("date", ">=", min_date), ("date", "<=", max_date),
                            "&", ("invoice_date", ">=", min_date), ("invoice_date", "<=", max_date)
                        ])
                        
                    print(f"[DIAGNOSTIC] Fetching moves directly from Odoo matching: date={norm_doc_date}, amount_range=[{min_val:.2f}, {max_val:.2f}]")
                    try:
                        moves = erp.execute_kw(
                            "account.move",
                            "search_read",
                            [domain],
                            {
                                "fields": [
                                    "name",
                                    "ref",
                                    "date",
                                    "invoice_date",
                                    "amount_total",
                                    "journal_id",
                                    "payment_reference",
                                    "partner_id",
                                    "move_type",
                                    "attachment_ids",
                                    "line_ids",
                                ],
                                "limit": 50
                            }
                        )
                        print(f"[DIAGNOSTIC] Odoo database search returned {len(moves)} moves.")
                    except Exception as e:
                        print(f"[DIAGNOSTIC] Odoo search failed: {e}")
                else:
                    print(f"[DIAGNOSTIC] Skipping Odoo search because amount is missing: amount={doc_amount}")

                print(f"[DIAGNOSTIC] Comparing with {len(moves)} Odoo moves...")

                for move in moves:
                    amount_s = _amount_score(doc_amount, move.get("amount_total"))
                    move_date = move.get("invoice_date") or move.get("date")
                    date_s = _date_score(doc_date, move_date)
                    ref_s = _reference_score(doc_desc, move)
                    desc_s = _description_score(doc_desc, move)
                    partner_s = _partner_score(fields, doc_desc, move)

                    # Print compare info if amount is close (score > 0) or date matches (score > 0)
                    if amount_s > 0 or date_s > 0:
                        print(f"  -> {move.get('name')}: AmountScore={amount_s:.2f} (Odoo={move.get('amount_total')}, Doc={doc_amount}), DateScore={date_s:.2f} (Odoo={move.get('date')}, Doc={doc_date})")

                    if amount_s <= 0:
                        continue

                    if date_s <= 0 and ref_s < 0.80 and desc_s < 0.55:
                        continue

                    final_score = (
                        amount_s * 45
                        + date_s * 25
                        + ref_s * 15
                        + partner_s * 10
                        + desc_s * 5
                    )

                    if final_score < 45:
                        print(f"    * Move {move.get('name')} skipped: final score {final_score:.1f} < 45")
                        continue

                    journal = move.get("journal_id")
                    journal_name = journal[1] if isinstance(journal, list) and len(journal) > 1 else ""

                    partner = move.get("partner_id")
                    partner_name = partner[1] if isinstance(partner, list) and len(partner) > 1 else ""

                    attachment_ids = move.get("attachment_ids") or []
                    attachments_details = []
                    if attachment_ids:
                        try:
                            raw_attachments = erp.execute_kw(
                                "ir.attachment",
                                "search_read",
                                [[["id", "in", attachment_ids]]],
                                {"fields": ["id", "name", "mimetype"]}
                            )
                            base_url = conn.base_url.rstrip('/')
                            for att in raw_attachments:
                                attachments_details.append({
                                    "id": att.get("id"),
                                    "name": att.get("name"),
                                    "mimetype": att.get("mimetype"),
                                    "url": f"{base_url}/web/content/{att.get('id')}?download=true"
                                })
                        except Exception as e:
                            print(f"[DIAGNOSTIC] Failed to fetch Odoo attachments: {e}")

                    base_url = conn.base_url.rstrip('/')
                    odoo_url = f"{base_url}/web#id={move.get('id')}&model=account.move&view_type=form"

                    line_ids = move.get("line_ids") or []
                    journal_items_details = []
                    if line_ids:
                        try:
                            raw_lines = erp.execute_kw(
                                "account.move.line",
                                "search_read",
                                [[["id", "in", line_ids]]],
                                {"fields": ["account_id", "name", "debit", "credit", "quantity", "price_unit", "price_subtotal", "product_id"]}
                            )
                            for line in raw_lines:
                                account_val = line.get("account_id")
                                account_name = account_val[1] if isinstance(account_val, list) and len(account_val) > 1 else (str(account_val) if account_val else "")
                                
                                product_val = line.get("product_id")
                                product_name = product_val[1] if isinstance(product_val, list) and len(product_val) > 1 else (str(product_val) if product_val else "")

                                journal_items_details.append({
                                    "id": line.get("id"),
                                    "account_name": account_name,
                                    "label": line.get("name") or "",
                                    "debit": float(line.get("debit") or 0.0),
                                    "credit": float(line.get("credit") or 0.0),
                                    "quantity": float(line.get("quantity") or 0.0),
                                    "price_unit": float(line.get("price_unit") or 0.0),
                                    "price_subtotal": float(line.get("price_subtotal") or 0.0),
                                    "product_name": product_name
                                })
                        except Exception as e:
                            print(f"[DIAGNOSTIC] Failed to fetch Odoo move lines: {e}")

                    matched_moves.append({
                        "id": move.get("id"),
                        "name": move.get("name"),
                        "ref": move.get("ref"),
                        "date": move.get("date"),
                        "amount_total": move.get("amount_total"),
                        "journal_name": journal_name,
                        "partner_name": partner_name,
                        "move_type": move.get("move_type"),
                        "similarity": round(final_score, 1),
                        "confidence": _build_confidence_label(final_score),
                        "attachments": attachments_details,
                        "odoo_url": odoo_url,
                        "journal_items": journal_items_details,
                        "score_details": {
                            "amount_score": round(amount_s * 100, 1),
                            "date_score": round(date_s * 100, 1),
                            "reference_score": round(ref_s * 100, 1),
                            "partner_score": round(partner_s * 100, 1),
                            "description_score": round(desc_s * 100, 1),
                        }
                    })

                matched_moves.sort(key=lambda x: x["similarity"], reverse=True)

                results.append({
                    "filename": file.filename,
                    "status": "analyzed",
                    "document_class": doc_class,
                    "matched_moves": matched_moves[:10],
                    "fields": fields
                })

            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": str(e),
            })

    return {
        "status": "success",
        "results": results
    }


@router.post("/attach-document")
def attach_document(
    file: UploadFile = File(...),
    move_id: int = Form(...),
    db_session: Session = Depends(get_db)
):
    import base64

    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        # 1. Verify if move exists and resolve its company_id to prevent inconsistencies
        moves = erp.execute_kw(
            "account.move",
            "search_read",
            [[["id", "=", move_id]]],
            {"fields": ["company_id"], "limit": 1}
        )
        if not moves:
            raise ValueError(f"المعاملة رقم {move_id} غير موجودة في أودو.")

        move_company_id = moves[0]["company_id"][0] if moves[0].get("company_id") else False

        file_content = file.file.read()
        file_data = base64.b64encode(file_content).decode("utf-8")

        attachment_vals = {
            "name": file.filename,
            "type": "binary",
            "datas": file_data,
            "res_model": "account.move",
            "res_id": move_id,
        }
        if move_company_id:
            attachment_vals["company_id"] = move_company_id

        attachment_id = erp.execute_kw(
            "ir.attachment",
            "create",
            [attachment_vals]
        )

        return {
            "status": "success",
            "message": f"Document attached successfully to move {move_id}",
            "attachment_id": attachment_id
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to attach document to Odoo: {str(e)}")


class JournalLineRequest(BaseModel):
    account_id: int
    account_name: str
    debit: float
    credit: float
    name: str
    partner_id: Optional[int] = None


class ProposeTransactionRequest(BaseModel):
    filename: str
    document_class: str
    amount: float
    date: str
    partner_name: str = ""
    raw_text: str = ""


class RegisterDocumentRequest(BaseModel):
    filename: str
    document_class: str
    amount: float
    date: str
    partner_name: str = ""
    partner_id: Optional[int] = None
    ref: str = ""
    raw_text: str = ""
    lines: List[JournalLineRequest] = None


@router.get("/partners")
def get_partners(db_session: Session = Depends(get_db)):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        partners = erp.execute_kw(
            "res.partner",
            "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "limit": 1000}
        )
        partners.sort(key=lambda x: (x.get("name") or "").lower())
        return partners
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch partners from Odoo: {str(e)}")


@router.post("/propose-transaction")
def propose_transaction(payload: ProposeTransactionRequest, db_session: Session = Depends(get_db)):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        # 1. Resolve Company ID
        users = erp.execute_kw(
            "res.users",
            "search_read",
            [[["login", "=", username]]],
            {"fields": ["company_id"], "limit": 1}
        )
        user_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        # 2. Extract Partner Name and find in Odoo
        suggested_partner_id = None
        suggested_partner_name = ""
        
        try:
            partners_list = get_cached(conn.base_url, conn.database_name or "", "partners")
            if partners_list is None:
                partners_list = erp.execute_kw(
                    "res.partner",
                    "search_read",
                    [[["active", "=", True]]],
                    {"fields": ["id", "name"], "limit": 5000}
                )
                set_cached(conn.base_url, conn.database_name or "", "partners", partners_list)
            
            doc_text_lower = f"{(payload.raw_text or '')} {payload.filename} {payload.partner_name}".lower()
            
            # Extract clean words from document text to enforce word-boundary matching
            import re
            doc_words = set(re.findall(r"[\w\u0600-\u06FF]+", doc_text_lower))
            
            ENGLISH_TO_ARABIC_MAP = {
                "mohamed": ["محمد"],
                "mohammed": ["محمد"],
                "muhammad": ["محمد"],
                "mohammad": ["محمد"],
                "ahmed": ["احمد", "أحمد"],
                "ahmad": ["احمد", "أحمد"],
                "shaaban": ["شعبان"],
                "shaban": ["شعبان"],
                "ali": ["علي"],
                "ibrahim": ["ابراهيم", "إبراهيم"],
                "ebrahim": ["ابراهيم", "إبراهيم"],
                "mahmoud": ["محمود"],
                "saeed": ["سعيد"],
                "said": ["سعيد"],
                "abdullah": ["عبدالله", "عبد الله"],
                "hussein": ["حسين"],
                "huseyin": ["حسين"],
                "hussain": ["حسين"],
                "hassan": ["حسن"],
                "hasan": ["حسن"],
                "soliman": ["سليمان"],
                "sulaiman": ["سليمان"],
                "suleiman": ["سليمان"],
                "sherif": ["شريف"],
                "khaled": ["خالد"],
                "khalid": ["خالد"],
                "saleh": ["صالح"],
                "saad": ["سعد", "سعيد"],
                "youssef": ["يوسف"],
                "yousef": ["يوسف"],
                "emad": ["عماد"],
                "nour": ["نور"],
                "adel": ["عادل"],
                "mustafa": ["مصطفى"],
                "mostafa": ["مصطفى"],
                "gamal": ["جمال"],
                "jamal": ["جمال"],
                "samir": ["سمير"],
                "sameer": ["سمير"],
                "fathy": ["فتحي"],
                "fathi": ["فتحي"],
                "tarek": ["طارق"],
                "tariq": ["طارق"],
                "hashem": ["هاشم", "هشام"],
                "hisham": ["هشام", "هاشم"],
                "ramadan": ["رمضان"],
                "magdy": ["مجدي"],
                "osama": ["اسامة", "أسامة"],
                "reda": ["رضا"],
                "anwar": ["انور", "أنور"],
                "waqas": ["وقاص"],
                "umar": ["عمر"],
                "omar": ["عمر"],
                "farooq": ["فاروق"],
                "faroog": ["فاروق"],
                "naser": ["ناصر", "نصير"],
                "naseer": ["ناصر", "نصير"],
            }
            
            best_score = -1.0
            best_matched_count = 0
            best_partner = None
            
            for partner in partners_list:
                p_name = partner.get("name") or ""
                name_clean = re.sub(r"[^\w\s]", " ", p_name.lower())
                p_words = [w.strip() for w in name_clean.split() if len(w.strip()) >= 3]
                if not p_words:
                    continue
                
                matched_count = 0
                for w in p_words:
                    # Direct match in document words
                    if w in doc_words:
                        matched_count += 1
                        continue
                    # Arabic transliteration match in document words
                    ar_vars = ENGLISH_TO_ARABIC_MAP.get(w)
                    if ar_vars:
                        matched = False
                        for ar in ar_vars:
                            if ar in doc_words:
                                matched = True
                                break
                            # Prefix-aware regex matching (e.g. لمحمد matches محمد)
                            pattern = r'(?:^|[^a-zA-Z0-9\u0600-\u06FF])[لبوف]?(?:ال)?' + re.escape(ar) + r'(?:$|[^a-zA-Z0-9\u0600-\u06FF])'
                            if re.search(pattern, doc_text_lower):
                                matched = True
                                break
                        if matched:
                            matched_count += 1
                            continue
                
                score = matched_count / len(p_words)
                
                # Apply tiny penalty for Petty Cash accounts to avoid shadowing actual partners in ties
                is_petty_cash = any(k in p_name.lower() or k in p_name for k in ["petty", "cash", "بيتي", "كاش"])
                adjusted_score = score - 0.01 if is_petty_cash else score
                
                if score >= 0.50:
                    # Prioritize higher score first, or tie-break with more matched words
                    if adjusted_score > best_score or (adjusted_score == best_score and matched_count > best_matched_count):
                        best_score = adjusted_score
                        best_matched_count = matched_count
                        best_partner = partner
            
            if best_partner:
                suggested_partner_id = best_partner["id"]
                suggested_partner_name = best_partner["name"]
                print(f"[DIAGNOSTIC] Smart partner match found: {suggested_partner_name} (Score: {best_score:.2f}, Matched Words: {best_matched_count})")
        except Exception as pe:
            print(f"[DIAGNOSTIC] Partner scan failed: {pe}")

        if not suggested_partner_id and payload.partner_name:
            try:
                partners = erp.execute_kw(
                    "res.partner",
                    "search_read",
                    [[["name", "ilike", payload.partner_name]]],
                    {"fields": ["id", "name"], "limit": 1}
                )
                if partners:
                    suggested_partner_id = partners[0]["id"]
                    suggested_partner_name = partners[0]["name"]
            except Exception as pe2:
                print(f"[DIAGNOSTIC] Partner search by name failed: {pe2}")

        # 3. Fetch default accounts (cached, sequential — xmlrpc is not thread-safe)
        cache_db = conn.database_name or ""
        accts_cache_key = f"accounts_{user_company_id or 'all'}"
        accts = get_cached(conn.base_url, cache_db, accts_cache_key)
        if accts is None:
            accts = {"expense": [], "payable": [], "suspense": [], "fallback": []}
            for kind, domain in [
                ("expense", [("account_type", "=", "expense")]),
                ("payable", [("account_type", "=", "liability_payable")]),
                ("suspense", [("name", "ilike", "suspense")]),
                ("fallback", []),
            ]:
                d = list(domain)
                if user_company_id:
                    d.append(("company_ids", "in", [user_company_id]))
                try:
                    accts[kind] = erp.execute_kw(
                        "account.account", "search_read",
                        [d], {"fields": ["id", "name", "code"], "limit": 1}
                    )
                except Exception:
                    pass
            set_cached(conn.base_url, cache_db, accts_cache_key, accts)

        expense_account_id = False
        expense_account_name = "Expense Account"
        if accts["expense"]:
            expense_account_id = accts["expense"][0]["id"]
            expense_account_name = f"{accts['expense'][0]['code']} {accts['expense'][0]['name']}"
        elif accts["fallback"]:
            expense_account_id = accts["fallback"][0]["id"]
            expense_account_name = f"{accts['fallback'][0]['code']} {accts['fallback'][0]['name']}"

        payable_account_id = False
        payable_account_name = "Payable Account"
        if accts["payable"]:
            payable_account_id = accts["payable"][0]["id"]
            payable_account_name = f"{accts['payable'][0]['code']} {accts['payable'][0]['name']}"

        suspense_account_id = False
        suspense_account_name = "Suspense Account"
        if accts["suspense"]:
            suspense_account_id = accts["suspense"][0]["id"]
            suspense_account_name = f"{accts['suspense'][0]['code']} {accts['suspense'][0]['name']}"

        if not payable_account_id:
            payable_account_id = expense_account_id
            payable_account_name = expense_account_name
        if not suspense_account_id:
            suspense_account_id = expense_account_id
            suspense_account_name = expense_account_name

        # 4. Bank Rules / Reconcile Models Matching (cached)
        rule_matched = None
        rule_account_id = None
        rule_account_name = ""
        rule_line_label = ""
        
        if user_company_id:
            try:
                import re
                reconcile_cache_key = f"reconcile_{user_company_id}"
                reconcile_models = get_cached(conn.base_url, cache_db, reconcile_cache_key)
                if reconcile_models is None:
                    reconcile_models = erp.execute_kw(
                        "account.reconcile.model",
                        "search_read",
                        [[["company_id", "=", user_company_id]]],
                        {"fields": ["id", "name", "match_label", "match_label_param", "line_ids"], "order": "sequence"}
                    )
                    set_cached(conn.base_url, cache_db, reconcile_cache_key, reconcile_models)
                
                doc_blob = f"{payload.filename} {payload.raw_text}".lower()
                
                for model in reconcile_models:
                    match_label = model.get("match_label")
                    param = model.get("match_label_param")
                    if not match_label or not param:
                         continue
                         
                    matched = False
                    if match_label == "contains":
                        if param.lower() in doc_blob:
                            matched = True
                    elif match_label == "match_regex":
                        try:
                            pattern = re.compile(param, re.IGNORECASE)
                            if pattern.search(doc_blob):
                                matched = True
                        except Exception as re_err:
                            print(f"[DIAGNOSTIC] Regex compile error for rule {model.get('name')}: {re_err}")
                            
                    if matched:
                        line_ids = model.get("line_ids")
                        if line_ids:
                            lines_detail = erp.execute_kw(
                                "account.reconcile.model.line",
                                "search_read",
                                [[["id", "in", line_ids]]],
                                {"fields": ["account_id", "label"], "limit": 1}
                            )
                            if lines_detail and lines_detail[0].get("account_id"):
                                rule_matched = model.get("name")
                                rule_account_id = lines_detail[0]["account_id"][0]
                                rule_account_name = lines_detail[0]["account_id"][1]
                                rule_line_label = lines_detail[0].get("label") or f"Reconciliation: {model.get('name')}"
                                break
            except Exception as model_err:
                print(f"[DIAGNOSTIC] Failed to evaluate reconcile models: {model_err}")

        # Override petty cash debit account to 102014 if matched rule uses Ibrahim Petty Cash or name has petty cash
        if rule_account_id:
            rule_acc_name_lower = rule_account_name.lower()
            rule_matched_lower = (rule_matched or "").lower()
            
            # Check for various forms of Petty Cash / Ibrahim Petty Cash in both English and Arabic
            is_petty_cash_acc = (
                "105002" in rule_acc_name_lower
                or "ibrahim petty cash" in rule_acc_name_lower
                or "ابراهيم بيتي كاش" in rule_acc_name_lower
                or ("petty" in rule_acc_name_lower and "cash" in rule_acc_name_lower)
                or ("بيتي" in rule_acc_name_lower and "كاش" in rule_acc_name_lower)
                or ("ابراهيم" in rule_acc_name_lower and ("كاش" in rule_acc_name_lower or "cash" in rule_acc_name_lower))
            )
            
            is_petty_cash_rule = (
                "petty cash" in rule_matched_lower
                or "بيتي كاش" in rule_matched_lower
                or "pettycash" in rule_matched_lower
                or "بيتي" in rule_matched_lower
            )
            
            if is_petty_cash_acc or is_petty_cash_rule:
                try:
                    accs = erp.execute_kw(
                        "account.account",
                        "search_read",
                        [[["code", "=", "102014"]]],
                        {"fields": ["id", "name", "code"], "limit": 1}
                    )
                    if accs:
                        rule_account_id = accs[0]["id"]
                        rule_account_name = f"{accs[0]['code']} {accs[0]['name']}"
                        print(f"[DIAGNOSTIC] Overrode petty cash debit account to 102014: {rule_account_name} (ID: {rule_account_id})")
                except Exception as override_err:
                    print(f"[DIAGNOSTIC] Failed to override petty cash account: {override_err}")

        # 5. Build proposal based on type
        doc_class = (payload.document_class or "").lower()
        filename_lower = (payload.filename or "").lower()
        raw_text_lower = (payload.raw_text or "").lower()
        
        is_payroll = (
            doc_class == "payroll" or
            "payroll" in filename_lower or
            "salary" in filename_lower or
            "مسير" in filename_lower or
            "رواتب" in filename_lower or
            "مسير" in raw_text_lower or
            "رواتب" in raw_text_lower or
            "payroll" in raw_text_lower or
            "salary" in raw_text_lower
        )
        
        is_bank = not is_payroll and (
            doc_class in ["bank", "cash", "receipt"] or
            (doc_class not in ["sale", "purchase"] and (
                "statement" in filename_lower or
                "bank" in filename_lower or
                "receipt" in filename_lower or
                "إشعار" in filename_lower or
                "ايصال" in filename_lower or
                "إيصال" in filename_lower or
                "كشف" in filename_lower or
                "statement" in raw_text_lower or
                "bank" in raw_text_lower or
                "receipt" in raw_text_lower or
                "إشعار" in raw_text_lower or
                "إيصال" in raw_text_lower or
                "ايصال" in raw_text_lower or
                "كشف" in raw_text_lower
            ))
        )
        
        is_invoice = not is_payroll and not is_bank and (
            doc_class in ["invoice", "bill", "sale", "purchase"] or
            "invoice" in filename_lower or
            "bill" in filename_lower or
            "فاتورة" in filename_lower or
            "invoice" in raw_text_lower or
            "bill" in raw_text_lower or
            "فاتورة" in raw_text_lower
        )

        proposed_lines = []
        journal_name = "Miscellaneous Operations"
        
        if is_payroll:
            salary_expense_id = False
            salary_expense_name = "Salary Expense Account"
            salary_payable_id = False
            salary_payable_name = "Salary Payable Account"
            try:
                domain = [("name", "ilike", "salary"), ("name", "ilike", "expense")]
                if user_company_id:
                    domain.append(("company_ids", "in", [user_company_id]))
                accs = erp.execute_kw(
                    "account.account",
                    "search_read",
                    [domain],
                    {"fields": ["id", "name", "code"], "limit": 1}
                )
                if accs:
                    salary_expense_id = accs[0]["id"]
                    salary_expense_name = f"{accs[0]['code']} {accs[0]['name']}"
            except Exception:
                pass
                
            try:
                domain = [("name", "ilike", "payable"), ("name", "ilike", "salary")]
                if user_company_id:
                    domain.append(("company_ids", "in", [user_company_id]))
                accs = erp.execute_kw(
                    "account.account",
                    "search_read",
                    [domain],
                    {"fields": ["id", "name", "code"], "limit": 1}
                )
                if accs:
                    salary_payable_id = accs[0]["id"]
                    salary_payable_name = f"{accs[0]['code']} {accs[0]['name']}"
            except Exception:
                pass
                
            if not salary_expense_id:
                salary_expense_id = expense_account_id
                salary_expense_name = expense_account_name
            if not salary_payable_id:
                salary_payable_id = payable_account_id
                salary_payable_name = payable_account_name
                
            proposed_lines = [
                {
                    "account_id": salary_expense_id,
                    "account_name": salary_expense_name,
                    "debit": payload.amount,
                    "credit": 0.0,
                    "name": f"مصروفات رواتب من {payload.filename}"
                },
                {
                    "account_id": salary_payable_id,
                    "account_name": salary_payable_name,
                    "debit": 0.0,
                    "credit": payload.amount,
                    "name": f"رواتب مستحقة من {payload.filename}"
                }
            ]
            journal_name = "Miscellaneous Operations"
            
        elif is_bank:
            bank_account_id = False
            bank_account_name = "Bank Account"
            try:
                domain = [("type", "=", "bank")]
                if user_company_id:
                    domain.append(("company_id", "=", user_company_id))
                journals = erp.execute_kw(
                    "account.journal",
                    "search_read",
                    [domain],
                    {"fields": ["id", "default_account_id"], "limit": 1}
                )
                if journals and journals[0].get("default_account_id"):
                    def_acc = journals[0]["default_account_id"]
                    bank_account_id = def_acc[0]
                    bank_account_name = def_acc[1]
            except Exception:
                pass
                
            if not bank_account_id:
                bank_account_id = expense_account_id
                bank_account_name = expense_account_name
                
            matched_acc_id = rule_account_id if rule_account_id else suspense_account_id
            matched_acc_name = rule_account_name if rule_account_id else suspense_account_name
            line_lbl = rule_line_label if rule_account_id else f"عملية بنكية من {payload.filename}"
            
            proposed_lines = [
                {
                    "account_id": matched_acc_id,
                    "account_name": matched_acc_name,
                    "debit": payload.amount,
                    "credit": 0.0,
                    "name": line_lbl
                },
                {
                    "account_id": bank_account_id,
                    "account_name": bank_account_name,
                    "debit": 0.0,
                    "credit": payload.amount,
                    "name": f"سداد بنكي من {payload.filename}"
                }
            ]
            journal_name = "Bank"
            
        elif is_invoice:
            matched_acc_id = rule_account_id if rule_account_id else expense_account_id
            matched_acc_name = rule_account_name if rule_account_id else expense_account_name
            line_lbl = rule_line_label if rule_account_id else f"فاتورة من المستند {payload.filename}"
            
            proposed_lines = [
                {
                    "account_id": matched_acc_id,
                    "account_name": matched_acc_name,
                    "debit": payload.amount,
                    "credit": 0.0,
                    "name": line_lbl
                },
                {
                    "account_id": payable_account_id,
                    "account_name": payable_account_name,
                    "debit": 0.0,
                    "credit": payload.amount,
                    "name": f"قيد المورد من {payload.filename}"
                }
            ]
            journal_name = "Vendor Bills"
            
        else:
            matched_acc_id = rule_account_id if rule_account_id else expense_account_id
            matched_acc_name = rule_account_name if rule_account_id else expense_account_name
            line_lbl = rule_line_label if rule_account_id else f"تسجيل مستند عام {payload.filename}"
            
            proposed_lines = [
                {
                    "account_id": matched_acc_id,
                    "account_name": matched_acc_name,
                    "debit": payload.amount,
                    "credit": 0.0,
                    "name": line_lbl
                },
                {
                    "account_id": suspense_account_id,
                    "account_name": suspense_account_name,
                    "debit": 0.0,
                    "credit": payload.amount,
                    "name": f"قيد مقابل مستند عام {payload.filename}"
                }
            ]
            journal_name = "Miscellaneous Operations"

        return {
            "status": "success",
            "suggested_partner_id": suggested_partner_id,
            "suggested_partner_name": suggested_partner_name,
            "journal_name": journal_name,
            "rule_matched": rule_matched,
            "lines": proposed_lines
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to propose transaction: {str(e)}")



@router.post("/register-document")
def register_document(payload: RegisterDocumentRequest, db_session: Session = Depends(get_db)):
    from datetime import date

    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        # Fetch current user info to resolve company_id
        users = erp.execute_kw(
            "res.users",
            "search_read",
            [[["login", "=", username]]],
            {"fields": ["company_id"], "limit": 1}
        )
        user_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False
        print(f"[DIAGNOSTIC] Register Document User Company ID: {user_company_id}")

        # Classification Logic
        doc_class = (payload.document_class or "").lower()
        filename_lower = (payload.filename or "").lower()
        raw_text_lower = (payload.raw_text or "").lower()
        
        # 1. Check Payroll (مسير رواتب)
        is_payroll = (
            doc_class == "payroll" or
            "payroll" in filename_lower or
            "salary" in filename_lower or
            "مسير" in filename_lower or
            "رواتب" in filename_lower or
            "مسير" in raw_text_lower or
            "رواتب" in raw_text_lower or
            "payroll" in raw_text_lower or
            "salary" in raw_text_lower
        )
        
        # 2. Check Bank Transaction (عملية بنكية)
        is_bank = not is_payroll and (
            doc_class == "receipt" or
            "statement" in filename_lower or
            "bank" in filename_lower or
            "receipt" in filename_lower or
            "إشعار" in filename_lower or
            "ايصال" in filename_lower or
            "إيصال" in filename_lower or
            "كشف" in filename_lower or
            "statement" in raw_text_lower or
            "bank" in raw_text_lower or
            "receipt" in raw_text_lower or
            "إشعار" in raw_text_lower or
            "إيصال" in raw_text_lower or
            "ايصال" in raw_text_lower or
            "كشف" in raw_text_lower
        )
        
        # 3. Check Invoice (فاتورة مورد)
        is_invoice = not is_payroll and not is_bank and (
            doc_class == "invoice" or
            "invoice" in filename_lower or
            "bill" in filename_lower or
            "فاتورة" in filename_lower or
            "invoice" in raw_text_lower or
            "bill" in raw_text_lower or
            "فاتورة" in raw_text_lower
        )

        # Resolve partner/vendor name
        partner_id = payload.partner_id
        if not partner_id and payload.partner_name:
            try:
                partners = erp.execute_kw(
                    "res.partner",
                    "search",
                    [[["name", "ilike", payload.partner_name]]],
                    {"limit": 1}
                )
                if partners:
                    partner_id = partners[0]
                else:
                    partner_id = erp.execute_kw(
                        "res.partner",
                        "create",
                        [{"name": payload.partner_name}]
                    )
            except Exception as pe:
                print(f"[DIAGNOSTIC] Partner resolution failed: {pe}")

        # Fetch Default Accounts with Company filter
        expense_account_id = False
        try:
            domain = [("account_type", "=", "expense")]
            if user_company_id:
                domain.append(("company_ids", "in", [user_company_id]))
            accs = erp.execute_kw(
                "account.account",
                "search_read",
                [domain],
                {"fields": ["id"], "limit": 1}
            )
            if accs:
                expense_account_id = accs[0]["id"]
        except Exception as e:
            print(f"[DIAGNOSTIC] Expense account search 1 failed: {e}")
            try:
                domain = [("user_type_id.type", "=", "expense")]
                if user_company_id:
                    domain.append(("company_ids", "in", [user_company_id]))
                accs = erp.execute_kw(
                    "account.account",
                    "search_read",
                    [domain],
                    {"fields": ["id"], "limit": 1}
                )
                if accs:
                    expense_account_id = accs[0]["id"]
            except Exception as e2:
                print(f"[DIAGNOSTIC] Expense account search 2 failed: {e2}")

        if not expense_account_id:
            try:
                domain = []
                if user_company_id:
                    domain.append(("company_ids", "in", [user_company_id]))
                accs = erp.execute_kw(
                    "account.account",
                    "search_read",
                    [domain],
                    {"fields": ["id"], "limit": 1}
                )
                if accs:
                    expense_account_id = accs[0]["id"]
            except Exception as e3:
                print(f"[DIAGNOSTIC] Expense account fallback failed: {e3}")

        payable_account_id = False
        try:
            domain = [("account_type", "=", "liability_payable")]
            if user_company_id:
                domain.append(("company_ids", "in", [user_company_id]))
            accs = erp.execute_kw(
                "account.account",
                "search_read",
                [domain],
                {"fields": ["id"], "limit": 1}
            )
            if accs:
                payable_account_id = accs[0]["id"]
        except Exception as e:
            print(f"[DIAGNOSTIC] Payable account search 1 failed: {e}")
            try:
                domain = [("user_type_id.type", "=", "payable")]
                if user_company_id:
                    domain.append(("company_ids", "in", [user_company_id]))
                accs = erp.execute_kw(
                    "account.account",
                    "search_read",
                    [domain],
                    {"fields": ["id"], "limit": 1}
                )
                if accs:
                    payable_account_id = accs[0]["id"]
            except Exception as e2:
                print(f"[DIAGNOSTIC] Payable account search 2 failed: {e2}")
        
        if not payable_account_id:
            payable_account_id = expense_account_id

        suspense_account_id = False
        try:
            domain = [("name", "ilike", "suspense")]
            if user_company_id:
                domain.append(("company_ids", "in", [user_company_id]))
            accs = erp.execute_kw(
                "account.account",
                "search_read",
                [domain],
                {"fields": ["id"], "limit": 1}
            )
            if accs:
                suspense_account_id = accs[0]["id"]
            else:
                domain = [("name", "ilike", "clearing")]
                if user_company_id:
                    domain.append(("company_ids", "in", [user_company_id]))
                accs = erp.execute_kw(
                    "account.account",
                    "search_read",
                    [domain],
                    {"fields": ["id"], "limit": 1}
                )
                if accs:
                    suspense_account_id = accs[0]["id"]
        except Exception as e:
            print(f"[DIAGNOSTIC] Suspense account search failed: {e}")

        if not suspense_account_id:
            suspense_account_id = expense_account_id

        # Build date
        invoice_date_val = str(date.today())
        if payload.date:
            from datetime import datetime
            try:
                datetime.strptime(payload.date, "%Y-%m-%d")
                invoice_date_val = payload.date
            except Exception:
                pass

        # Build Move Structure by Category
        journal_id = False
        move_vals = {}
        journal_name = "Vendor Bills"

        if payload.lines:
            doc_class_lower = (payload.document_class or "").lower()
            is_bank_journal = (
                doc_class_lower == "receipt" or
                "statement" in payload.filename.lower() or
                "bank" in payload.filename.lower() or
                "receipt" in payload.filename.lower() or
                "إشعار" in payload.filename.lower() or
                "ايصال" in payload.filename.lower() or
                "إيصال" in payload.filename.lower() or
                "كشف" in payload.filename.lower()
            )
            is_invoice_journal = not is_bank_journal and (
                doc_class_lower == "invoice" or
                "invoice" in payload.filename.lower() or
                "bill" in payload.filename.lower() or
                "فاتورة" in payload.filename.lower()
            )
            
            journal_type = "general"
            if is_bank_journal:
                journal_type = "bank"
                journal_name = "Bank"
            elif is_invoice_journal:
                journal_type = "purchase"
                journal_name = "Vendor Bills"
            else:
                journal_name = "Miscellaneous Operations"
                
            try:
                domain = [("type", "=", journal_type)]
                if user_company_id:
                    domain.append(("company_id", "=", user_company_id))
                journals = erp.execute_kw(
                    "account.journal",
                    "search_read",
                    [domain],
                    {"fields": ["id"], "limit": 1}
                )
                if journals:
                    journal_id = journals[0]["id"]
            except Exception:
                pass

            if is_invoice_journal:
                move_vals = {
                    "move_type": "in_invoice",
                    "invoice_date": invoice_date_val,
                    "ref": payload.ref or f"Doc {payload.filename}",
                    "invoice_line_ids": [
                        (0, 0, {
                            "name": line.name,
                            "quantity": 1.0,
                            "price_unit": line.debit or line.credit or payload.amount,
                            "account_id": line.account_id,
                        }) for line in payload.lines
                    ]
                }
            else:
                move_vals = {
                    "move_type": "entry",
                    "date": invoice_date_val,
                    "ref": payload.ref or f"Doc {payload.filename}",
                    "line_ids": [
                        (0, 0, {
                            "account_id": line.account_id,
                            "name": line.name,
                            "debit": line.debit,
                            "credit": line.credit,
                            "partner_id": line.partner_id if line.partner_id is not None else (partner_id or False),
                        }) for line in payload.lines
                    ]
                }
                
            if partner_id:
                move_vals["partner_id"] = partner_id
            if journal_id:
                move_vals["journal_id"] = journal_id
        else:
            if is_invoice:
                # Vendor Bill
                try:
                    domain = [("type", "=", "purchase")]
                    if user_company_id:
                        domain.append(("company_id", "=", user_company_id))
                    journals = erp.execute_kw(
                        "account.journal",
                        "search_read",
                        [domain],
                        {"fields": ["id"], "limit": 1}
                    )
                    if journals:
                        journal_id = journals[0]["id"]
                except Exception:
                    pass

                move_vals = {
                    "move_type": "in_invoice",
                    "invoice_date": invoice_date_val,
                    "ref": payload.ref or f"Doc {payload.filename}",
                    "invoice_line_ids": [
                        (0, 0, {
                            "name": f"فاتورة من المستند {payload.filename}",
                            "quantity": 1.0,
                            "price_unit": payload.amount,
                            "account_id": expense_account_id,
                        })
                    ]
                }
                if partner_id:
                    move_vals["partner_id"] = partner_id
                if journal_id:
                    move_vals["journal_id"] = journal_id
                
                journal_name = "Vendor Bills"

            elif is_bank:
                # Bank Journal Entry
                bank_account_id = False
                try:
                    domain = [("type", "=", "bank")]
                    if user_company_id:
                        domain.append(("company_id", "=", user_company_id))
                    journals = erp.execute_kw(
                        "account.journal",
                        "search_read",
                        [domain],
                        {"fields": ["id", "default_account_id"], "limit": 1}
                    )
                    if journals:
                        journal_id = journals[0]["id"]
                        def_acc = journals[0].get("default_account_id")
                        bank_account_id = def_acc[0] if isinstance(def_acc, list) else def_acc
                except Exception:
                    pass

                if not bank_account_id:
                    bank_account_id = expense_account_id

                move_vals = {
                    "move_type": "entry",
                    "date": invoice_date_val,
                    "ref": payload.ref or f"إشعار بنكي {payload.filename}",
                    "line_ids": [
                        (0, 0, {
                            "account_id": suspense_account_id,
                            "name": f"عملية بنكية من {payload.filename}",
                            "debit": payload.amount,
                            "credit": 0.0,
                        }),
                        (0, 0, {
                            "account_id": bank_account_id,
                            "name": f"سداد بنكي من {payload.filename}",
                            "debit": 0.0,
                            "credit": payload.amount,
                        })
                    ]
                }
                if journal_id:
                    move_vals["journal_id"] = journal_id
                
                journal_name = "Bank"

            elif is_payroll:
                # Payroll Entry
                salary_expense_id = False
                salary_payable_id = False
                try:
                    domain = [("name", "ilike", "salary"), ("name", "ilike", "expense")]
                    if user_company_id:
                        domain.append(("company_ids", "in", [user_company_id]))
                    accs = erp.execute_kw(
                        "account.account",
                        "search_read",
                        [domain],
                        {"fields": ["id"], "limit": 1}
                    )
                    if accs:
                        salary_expense_id = accs[0]["id"]
                except Exception as e:
                    print(f"[DIAGNOSTIC] Salary expense search failed: {e}")

                try:
                    domain = [("name", "ilike", "payable"), ("name", "ilike", "salary")]
                    if user_company_id:
                        domain.append(("company_ids", "in", [user_company_id]))
                    accs = erp.execute_kw(
                        "account.account",
                        "search_read",
                        [domain],
                        {"fields": ["id"], "limit": 1}
                    )
                    if accs:
                        salary_payable_id = accs[0]["id"]
                except Exception as e:
                    print(f"[DIAGNOSTIC] Salary payable search failed: {e}")

                if not salary_expense_id:
                    salary_expense_id = expense_account_id
                if not salary_payable_id:
                    salary_payable_id = payable_account_id

                try:
                    domain = [("type", "=", "general")]
                    if user_company_id:
                        domain.append(("company_id", "=", user_company_id))
                    journals = erp.execute_kw(
                        "account.journal",
                        "search_read",
                        [domain],
                        {"fields": ["id"], "limit": 1}
                    )
                    if journals:
                        journal_id = journals[0]["id"]
                except Exception:
                    pass

                move_vals = {
                    "move_type": "entry",
                    "date": invoice_date_val,
                    "ref": payload.ref or f"مسير رواتب {payload.filename}",
                    "line_ids": [
                        (0, 0, {
                            "account_id": salary_expense_id,
                            "name": f"مصروفات رواتب من {payload.filename}",
                            "debit": payload.amount,
                            "credit": 0.0,
                        }),
                        (0, 0, {
                            "account_id": salary_payable_id,
                            "name": f"رواتب مستحقة من {payload.filename}",
                            "debit": 0.0,
                            "credit": payload.amount,
                        })
                    ]
                }
                if journal_id:
                    move_vals["journal_id"] = journal_id
                
                journal_name = "Miscellaneous Operations"

            else:
                # Miscellaneous Entry
                try:
                    domain = [("type", "=", "general")]
                    if user_company_id:
                        domain.append(("company_id", "=", user_company_id))
                    journals = erp.execute_kw(
                        "account.journal",
                        "search_read",
                        [domain],
                        {"fields": ["id"], "limit": 1}
                    )
                    if journals:
                        journal_id = journals[0]["id"]
                except Exception:
                    pass

                move_vals = {
                    "move_type": "entry",
                    "date": invoice_date_val,
                    "ref": payload.ref or f"قيد عام {payload.filename}",
                    "line_ids": [
                        (0, 0, {
                            "account_id": expense_account_id,
                            "name": f"تسجيل مستند عام {payload.filename}",
                            "debit": payload.amount,
                            "credit": 0.0,
                        }),
                        (0, 0, {
                            "account_id": suspense_account_id,
                            "name": f"قيد مقابل مستند عام {payload.filename}",
                            "debit": 0.0,
                            "credit": payload.amount,
                        })
                    ]
                }
                if journal_id:
                    move_vals["journal_id"] = journal_id

                journal_name = "Miscellaneous Operations"

        # Create move
        move_id = erp.execute_kw(
            "account.move",
            "create",
            [move_vals]
        )

        # Read the name of the created move
        move_name = f"BILL/{move_id}"
        try:
            created_moves = erp.execute_kw(
                "account.move",
                "read",
                [[move_id]],
                {"fields": ["name"]}
            )
            if created_moves and created_moves[0].get("name"):
                move_name = created_moves[0].get("name")
        except Exception as ne:
            print(f"[DIAGNOSTIC] Failed to read created move name: {ne}")

        base_url = conn.base_url.rstrip('/')
        odoo_url = f"{base_url}/web#id={move_id}&model=account.move&view_type=form"

        return {
            "status": "success",
            "message": "Transaction created successfully in Odoo",
            "move_id": move_id,
            "move_name": move_name,
            "odoo_url": odoo_url,
            "partner_name": payload.partner_name,
            "journal_name": journal_name,
            "account_id": expense_account_id
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create transaction in Odoo: {str(e)}")


class SheetPayload(BaseModel):
    id: str
    name: str
    gridData: List[List[str]]
    rowCount: int
    colCount: int

from typing import Optional

class ChatSpreadsheetRequest(BaseModel):
    prompt: str
    sheets: List[SheetPayload]
    active_sheet_id: str
    company_id: Optional[int] = 1

@router.post("/chat-spreadsheet")
def chat_spreadsheet(payload: ChatSpreadsheetRequest, db_session: Session = Depends(get_db)):
    import urllib.request
    import json
    from pathlib import Path

    # Find active sheet
    active_sheet = None
    for s in payload.sheets:
        if s.id == payload.active_sheet_id:
            active_sheet = s
            break
    if not active_sheet:
        active_sheet = payload.sheets[0]

    # Try to load api key
    grok_api_key = settings.GROK_API_KEY
    if not grok_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider is not configured. Please set GROK_API_KEY.",
        )

    # Fetch dynamic Odoo accounts, partners, and bank rules if connection is active
    odoo_accounts = []
    odoo_partners = []
    odoo_bank_rules = []
    odoo_connected = False
    
    try:
        conn = db_session.query(ERPConnection).filter(
            ERPConnection.organization_id == 1,
            ERPConnection.is_active == True
        ).first()
        
        if conn:
            secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
            username = secret_data.get("username")
            password = secret_data.get("password")
            
            erp = get_erp_provider(
                provider=conn.provider,
                url=conn.base_url,
                db=conn.database_name or "",
                username=username,
                password=password,
            )
            
            # 1. Resolve Company ID
            users = erp.execute_kw(
                "res.users",
                "search_read",
                [[["login", "=", username]]],
                {"fields": ["company_id"], "limit": 1}
            )
            user_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

            # Fetch active partners
            odoo_partners = erp.execute_kw(
                "res.partner",
                "search_read",
                [[["active", "=", True]]],
                {"fields": ["id", "name"], "limit": 2000}
            )
            
            # Fetch active accounts
            odoo_accounts = erp.execute_kw(
                "account.account",
                "search_read",
                [[]],
                {"fields": ["id", "code", "name", "account_type"], "limit": 2000}
            )

            # Fetch active bank rules / reconcile models
            if user_company_id:
                try:
                    reconcile_models = erp.execute_kw(
                        "account.reconcile.model",
                        "search_read",
                        [[["company_id", "=", user_company_id]]],
                        {"fields": ["id", "name", "match_label", "match_label_param", "line_ids"], "order": "sequence"}
                    )
                    
                    all_line_ids = []
                    for model in reconcile_models:
                        line_ids = model.get("line_ids")
                        if line_ids:
                            all_line_ids.extend(line_ids)
                    
                    model_lines = {}
                    if all_line_ids:
                        lines_detail = erp.execute_kw(
                            "account.reconcile.model.line",
                            "search_read",
                            [[["id", "in", list(set(all_line_ids))]]],
                            {"fields": ["id", "account_id", "label"]}
                        )
                        model_lines = {l["id"]: l for l in lines_detail}
                    
                    for model in reconcile_models:
                        m_name = model.get("name")
                        m_label = model.get("match_label")
                        m_param = model.get("match_label_param")
                        line_ids = model.get("line_ids") or []
                        
                        acc_code = ""
                        acc_name = ""
                        line_label = ""
                        if line_ids:
                            first_line_id = line_ids[0]
                            detail = model_lines.get(first_line_id)
                            if detail and detail.get("account_id"):
                                acc_id_val = detail["account_id"]
                                if isinstance(acc_id_val, (list, tuple)):
                                    acc_name = acc_id_val[1]
                                    import re as pyre
                                    m_code = pyre.match(r"^(\d+)", acc_name)
                                    if m_code:
                                        acc_code = m_code.group(1)
                                    else:
                                        acc_code = acc_name
                                else:
                                    acc_code = str(acc_id_val)
                                line_label = detail.get("label") or ""
                        
                        if acc_code:
                            odoo_bank_rules.append({
                                "name": m_name,
                                "match_label": m_label,
                                "match_label_param": m_param,
                                "account_code": acc_code,
                                "account_name": acc_name,
                                "line_label": line_label
                            })
                except Exception as rule_err:
                    print(f"[Spreadsheet Agent] Failed to load reconcile models: {rule_err}")

            odoo_connected = True
            print(f"[Spreadsheet Agent] Successfully loaded {len(odoo_partners)} partners, {len(odoo_accounts)} accounts, and {len(odoo_bank_rules)} bank rules from Odoo.")
    except Exception as e:
        print(f"[Spreadsheet Agent] Failed to fetch Odoo context: {e}")

    # Format Odoo context for LLM
    partners_text = ""
    accounts_text = ""
    bank_rules_text = ""
    if odoo_connected:
        partners_text = "\n".join([f"- ID: {p['id']}, Name: {p['name']}" for p in odoo_partners if p.get('name')])
        accounts_text = "\n".join([f"- Code: {a['code']}, Name: {a['name']}, Type: {a['account_type']}" for a in odoo_accounts])
        bank_rules_text = "\n".join([
            f"- Rule: Name=\"{r['name']}\", MatchLabel={r['match_label']}, Param=\"{r['match_label_param']}\" -> Account={r['account_code']} ({r['account_name']}), Label=\"{r['line_label']}\""
            for r in odoo_bank_rules
        ])
    else:
        partners_text = "No active Odoo connection or could not fetch partners."
        accounts_text = "No active Odoo connection or could not fetch accounts."
        bank_rules_text = "No active Odoo connection or could not fetch bank rules."

    system_prompt = (
        "You are an exceptionally intelligent spreadsheet layout, accounting formatting, and data organizing assistant (intelligent agent).\n"
        "Your job is to help users organize, format, and structure their spreadsheet data. The user wants to format sheets to be ready to register in Odoo.\n"
        "Odoo journal entries require the following standard columns:\n"
        "- Column A (index 0): Account Code / رمز الحساب (e.g. 101001, 102014, 501001, etc.)\n"
        "- Column B (index 1): Description / البيان\n"
        "- Column C (index 2): Debit / مدين\n"
        "- Column D (index 3): Credit / دائن\n"
        "- Column E (index 4): Partner / الشريك\n\n"
        "You can manipulate the active sheet's grid data (a 2D array of strings), rename the active sheet, create sheets, or delete sheets.\n"
        "You must return a JSON object with the following fields:\n"
        "- \"message\": (string) Your response. Explain what you changed or ask clarifying questions if information is missing or ambiguous.\n"
        "- \"grid_data\": (optional, list of list of strings) The updated grid data (matrix of string cells) for the active sheet.\n"
        "- \"active_sheet_name\": (optional, string) The new name of the active sheet.\n"
        "- \"create_sheet\": (optional, object with \"name\" and \"grid_data\") If you need to create a new sheet.\n"
        "- \"delete_sheet_id\": (optional, string) ID of a sheet to delete.\n\n"
        "CRITICAL BEHAVIOR RULES:\n"
        "1. BILINGUAL RESPONSE ALIGNMENT:\n"
        "   - Detect the language of the user's prompt (Arabic or English).\n"
        "   - If the user writes in Arabic, your \"message\" MUST be written in fluent, professional Arabic. All explanations and questions must be in Arabic.\n"
        "   - If the user writes in English, your \"message\" MUST be written in fluent, professional English.\n"
        "   - The spreadsheet grid headers can match the user's language preference or standard accounting terms (e.g. 'رمز الحساب', 'البيان', 'مدين', 'دائن', 'الشريك' for Arabic, or 'Account Code', 'Description', 'Debit', 'Credit', 'Partner' for English).\n\n"
        "2. SPELLING CORRECTION & TYPO TOLERANCE:\n"
        "   - Be extremely robust against human typing errors, misspellings, and translation differences (in both the user query and the sheet data).\n"
        "   - Understand what the user wants even with typos or incomplete sentences. Correct any spelling errors in the sheet labels/descriptions.\n\n"
        "3. INTELLIGENT ODOO RECORD MATCHING:\n"
        "   - You are provided with the active list of Odoo Partners and Odoo Accounts (code, name, type).\n"
        "   - Compare the partner names and account descriptions/names referenced by the user (or already in the sheet) against these Odoo lists.\n"
        "   - If a name is written in Arabic but exists in Odoo in English (or vice versa), translate/match them intelligently. For example:\n"
        "     * User writes 'ابراهيم بيتي كاش' or 'بيتي كاش ابراهيم' -> Match it with Odoo Account code '102014' or Odoo partner 'Ibrahim Petty Cash' or similar from the list.\n"
        "     * User writes 'محمد شعبان' -> Match it with Odoo Partner 'Mohammed Ahmed Shaban' or similar from the list.\n"
        "   - In Column A (Account Code), you MUST fill the EXACT account code from the matched Odoo account (e.g. '102014', '501001', '101001'). Do not invent codes.\n"
        "   - In Column E (Partner), you MUST fill the EXACT name of the matched Odoo partner (e.g., 'Mohammed Ahmed Shaban' or 'Ibrahim Petty Cash') or the provided partner name if new.\n"
        "   - Ensure the Odoo matching is highly accurate and resolves minor spelling discrepancies.\n\n"
        "4. DOUBLE-ENTRY BOOKKEEPING & TRANSACTION BALANCING RULE:\n"
        "   - In double-entry bookkeeping (قيود يومية), every single transaction or amount must be recorded exactly twice: once as a Debit (مدين) entry and once as a Credit (دائن) entry.\n"
        "   - Whenever you format, clean, balance, review, or generate accounting entries, you MUST ensure that each transaction amount appears in two separate rows: one row where the amount is under the Debit column, and another row where the exact same amount is under the Credit column.\n"
        "   - If the user's spreadsheet contains single-sided entries (e.g. only debits or only credits), you MUST generate or duplicate those rows to provide their matching offset (e.g., offset against a bank/cash account, suspense account, or the correct matched Odoo account) so that the sheet is completely balanced (Total Debit equals Total Credit).\n"
        "   - Each transaction must have its offset, ensuring no single-sided entries remain in the final grid data.\n\n"
        "5. ODOO BANK RECONCILIATION RULES (BANK RULES) APPLICATION:\n"
        "   - You are provided with the active list of Odoo Bank Rules (Reconcile Models).\n"
        "   - When formatting bank entries or statements (قيد بنك / كشف حساب), check if the transaction details (البيان) matches any Odoo Bank Rule:\n"
        "     * If the rule's MatchLabel is 'contains' and its Param is present in the transaction details (case-insensitive), it is a match.\n"
        "     * If the rule's MatchLabel is 'match_regex' and its Param matches the transaction details as a regex pattern, it is a match.\n"
        "     * Examples: 'OUTGOING INSTANT PAYMENT' matches regex 'OUTGOING\\ INSTANT\\ PAYMENT' (rule 'Cash (copy)', maps to account code '105002'). 'INSTANT PAYMENT FEES' contains 'Fees' (rule 'Fees', maps to account code '400051').\n"
        "   - If a rule matches a transaction, you MUST map Column A (Account Code) to that rule's account code, and Column B (Description) to the rule's line label or transaction details. Map Column E (Partner) if the rule or text indicates a specific partner.\n"
        "   - If no rule matches, map it to a reasonable default account (e.g., Suspense Account or other relevant account).\n"
        "   - Every bank transaction must be split/represented as a double-entry (balanced Debit and Credit) where one row uses the matched rule account and the other row uses the bank account (e.g., code 101001 Riyadh Bank or active bank account).\n\n"
        "6. GENERAL GRID RULES:\n"
        "   - Keep cell grid dimensions consistent. The grid_data should be a rectangular array (all rows having the same number of columns).\n"
        "   - Output ONLY valid JSON. Do not include markdown wraps like ```json in your response, just the raw JSON object."
    )
 
    user_prompt = (
        f"User Request: \"{payload.prompt}\"\n\n"
        f"Active Sheet Details:\n"
        f"- Name: \"{active_sheet.name}\"\n"
        f"- ID: \"{active_sheet.id}\"\n"
        f"- Current Grid Data (Rows: {active_sheet.rowCount}, Cols: {active_sheet.colCount}):\n"
        f"{json.dumps(active_sheet.gridData, ensure_ascii=False)}\n\n"
        f"All Available Sheets in the Session:\n"
        f"{json.dumps([{'id': s.id, 'name': s.name} for s in payload.sheets], ensure_ascii=False)}\n\n"
        f"=== CONNECTED ODOO DATABASE CONTEXT ===\n"
        f"Odoo Accounts (Code, Name, Type):\n"
        f"{accounts_text[:20000]}\n\n"
        f"Odoo Partners (ID, Name):\n"
        f"{partners_text[:20000]}\n\n"
        f"Odoo Bank Rules (Reconcile Models):\n"
        f"{bank_rules_text[:15000]}\n"
    )

    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {grok_api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "grok-4.3",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.0
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            res_data = response.read().decode("utf-8")
            res_json = json.loads(res_data)
            content = res_json["choices"][0]["message"]["content"].strip()
            
            # Clean markdown code blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
                
            response_obj = json.loads(content)
            return response_obj
    except Exception as e:
        print(f"[Spreadsheet Agent Error] Call failed: {e}")
        return {
            "message": f"عذراً، حدث خطأ أثناء الاتصال بمساعد التنسيق: {str(e)}",
            "grid_data": None
        }


class ParseManualTextRequest(BaseModel):
    text: str
    company_id: Optional[int] = 1


@router.post("/parse-manual-text")
def parse_manual_text(payload: ParseManualTextRequest, db_session: Session = Depends(get_db)):
    import urllib.request
    import json
    from pathlib import Path

    # Try to load api key
    grok_api_key = settings.GROK_API_KEY
    if not grok_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider is not configured. Please set GROK_API_KEY.",
        )

    # Fetch dynamic Odoo accounts and partners if connection is active
    odoo_accounts = []
    odoo_partners = []
    odoo_connected = False
    
    try:
        conn = db_session.query(ERPConnection).filter(
            ERPConnection.organization_id == 1,
            ERPConnection.is_active == True
        ).first()
        
        if conn:
            secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
            username = secret_data.get("username")
            password = secret_data.get("password")
            
            erp = get_erp_provider(
                provider=conn.provider,
                url=conn.base_url,
                db=conn.database_name or "",
                username=username,
                password=password,
            )
            
            # Fetch active partners
            odoo_partners = erp.execute_kw(
                "res.partner",
                "search_read",
                [[["active", "=", True]]],
                {"fields": ["id", "name"], "limit": 2000}
            )
            
            # Fetch active accounts
            odoo_accounts = erp.execute_kw(
                "account.account",
                "search_read",
                [[]],
                {"fields": ["id", "code", "name", "account_type"], "limit": 2000}
            )
            odoo_connected = True
            print(f"[Parse Manual Text] Loaded {len(odoo_partners)} partners and {len(odoo_accounts)} accounts from Odoo.")
    except Exception as e:
        print(f"[Parse Manual Text] Failed to fetch Odoo context: {e}")

    # Format Odoo context for LLM
    partners_text = ""
    accounts_text = ""
    if odoo_connected:
        partners_text = "\n".join([f"- ID: {p['id']}, Name: {p['name']}" for p in odoo_partners if p.get('name')])
        accounts_text = "\n".join([f"- Code: {a['code']}, Name: {a['name']}, Type: {a['account_type']}" for a in odoo_accounts])
    else:
        partners_text = "No active Odoo connection or could not fetch partners."
        accounts_text = "No active Odoo connection or could not fetch accounts."

    system_prompt = (
        "You are an exceptionally intelligent accounting parsing agent.\n"
        "Your task is to take a raw text input written or pasted by the user and extract journal entry details from it.\n"
        "The input text could be a pasted table (tab-separated or comma-separated rows) or natural language description of an accounting transaction.\n"
        "You must extract the following fields:\n"
        "- Transaction Date: (YYYY-MM-DD format, fallback to today's date if not specified)\n"
        "- Transaction Reference / Description: (string)\n"
        "- Journal Name / Class: (general_journal, bank, invoice, etc.)\n"
        "- Lines: A list of journal entry lines, where each line contains:\n"
        "  * account_code: (string, the account code or code pattern referenced in the text)\n"
        "  * name: (string, the line description or account description)\n"
        "  * debit: (float, 0.0 if not specified)\n"
        "  * credit: (float, 0.0 if not specified)\n"
        "  * partner_name: (string, the partner name if specified, empty string otherwise)\n\n"
        "You must return ONLY a valid JSON object with the following schema:\n"
        "{\n"
        "  \"date\": \"YYYY-MM-DD\",\n"
        "  \"ref\": \"Description\",\n"
        "  \"journal\": \"general_journal\" | \"bank\" | \"invoice\",\n"
        "  \"lines\": [\n"
        "    {\n"
        "      \"account_code\": \"code\",\n"
        "      \"name\": \"line explanation\",\n"
        "      \"debit\": 100.0,\n"
        "      \"credit\": 0.0,\n"
        "      \"partner_name\": \"partner name\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "CRITICAL RULES:\n"
        "1. Direct Mapping: Try to match and assign account codes based on the available Odoo Accounts and Partner lists provided in the prompt.\n"
        "2. Typo Tolerance: Correct any spelling mistakes or translation discrepancies.\n"
        "3. Value Added Tax (VAT) Splitting:\n"
        "   - Analyze the raw text for VAT or tax details (e.g. 'VAT AMOUNT 0.15' on a fee of '1.00', or '1.15 inclusive of 0.15 VAT').\n"
        "   - For any transaction that contains a VAT component, you MUST split the debit side into two lines:\n"
        "     * Base fee/expense debit: Debit the base fee amount (e.g., 1.00) to the respective bank charges/expense account (e.g., code 400051).\n"
        "     * VAT debit: Debit the VAT amount (e.g., 0.15) to the VAT input tax account (code 104041).\n"
        "4. Individual Credit Offsets (No Grouping):\n"
        "   - Do NOT group the credit/offset side into a single summary line.\n"
        "   - Every debit transaction (base + VAT) must have its own corresponding credit line to the bank account (e.g., Riyadh Bank 101001) matching its exact transaction total.\n"
        "   - If there are multiple separate transactions, generate separate credit offsets for each one so they can be reconciled line-by-line in Odoo.\n"
        "5. Output format: Return ONLY the raw JSON object. Do not include markdown code block syntax (like ```json)."
    )

    user_prompt = (
        f"User Input Text:\n\"\"\"\n{payload.text}\n\"\"\"\n\n"
        f"=== CONNECTED ODOO DATABASE CONTEXT ===\n"
        f"Odoo Accounts (Code, Name, Type):\n"
        f"{accounts_text[:30000]}\n\n"
        f"Odoo Partners (ID, Name):\n"
        f"{partners_text[:30000]}\n"
    )

    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {grok_api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "grok-4.3",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.0
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            res_data = response.read().decode("utf-8")
            res_json = json.loads(res_data)
            content = res_json["choices"][0]["message"]["content"].strip()
            
            # Clean markdown code blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
                
            parsed_data = json.loads(content)
            
            # Resolve accounts and partners context
            resolved_lines = []
            for line in parsed_data.get("lines", []):
                parsed_code = str(line.get("account_code", "")).strip()
                parsed_debit = float(line.get("debit") or 0.0)
                parsed_credit = float(line.get("credit") or 0.0)
                parsed_name = str(line.get("name", "")).strip()
                parsed_partner = str(line.get("partner_name", "")).strip()
                
                # Match Account
                matched_acc = None
                if parsed_code and odoo_accounts:
                    matched_acc = next((a for a in odoo_accounts if a["code"] == parsed_code), None)
                    if not matched_acc:
                        # Fuzzy match by code contains or name contains
                        matched_acc = next((a for a in odoo_accounts if parsed_code.lower() in a["code"].lower() or (a["name"] and isinstance(a["name"], str) and parsed_code.lower() in a["name"].lower())), None)
                        
                # Match Partner
                matched_partner_id = None
                matched_partner_name = parsed_partner
                if parsed_partner and odoo_partners:
                    # Fuzzy match partner name
                    matched_p = next((p for p in odoo_partners if p["name"] and isinstance(p["name"], str) and parsed_partner.lower() in p["name"].lower()), None)
                    if matched_p:
                        matched_partner_id = matched_p["id"]
                        matched_partner_name = matched_p["name"]
                        
                resolved_lines.append({
                    "account_id": matched_acc["id"] if matched_acc else 0,
                    "account_name": f"{matched_acc['code']} {matched_acc['name']}" if matched_acc else (f"{parsed_code} (غير معرف)" if parsed_code else "حساب غير محدد"),
                    "account_code": matched_acc["code"] if matched_acc else parsed_code,
                    "debit": parsed_debit,
                    "credit": parsed_credit,
                    "name": parsed_name or "قيد يدوي",
                    "partner_id": matched_partner_id,
                    "partner_name": matched_partner_name
                })
                
            return {
                "status": "success",
                "date": parsed_data.get("date") or "",
                "ref": parsed_data.get("ref") or "",
                "journal": parsed_data.get("journal") or "general_journal",
                "lines": resolved_lines
            }
    except Exception as e:
        print(f"[Parse Manual Text Error] Call failed: {e}")
        return {
            "status": "error",
            "message": f"عذراً، حدث خطأ أثناء تحليل النص المدخل: {str(e)}",
            "lines": []
        }


class DetectAttachmentsRequest(BaseModel):
    company_id: Optional[int] = 1
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    account_id: Optional[int] = None


@router.post("/detect-attachments")
def detect_attachments(payload: DetectAttachmentsRequest, db_session: Session = Depends(get_db)):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        # Resolve Company ID
        users = erp.execute_kw(
            "res.users",
            "search_read",
            [[["login", "=", username]]],
            {"fields": ["company_id"], "limit": 1}
        )
        user_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        # Build domain
        domain = []
        if user_company_id:
            domain.append(["company_id", "=", user_company_id])

        if payload.account_id:
            # If account is filtered, find move lines for this account first
            line_domain = [["account_id", "=", payload.account_id]]
            if user_company_id:
                line_domain.append(["company_id", "=", user_company_id])
            if payload.date_from:
                line_domain.append(["date", ">=", payload.date_from])
            if payload.date_to:
                line_domain.append(["date", "<=", payload.date_to])

            lines = erp.execute_kw(
                "account.move.line",
                "search_read",
                [line_domain],
                {
                    "fields": ["move_id"],
                    "limit": 1000,
                }
            )

            move_ids = []
            for line in lines:
                m_val = line.get("move_id")
                if m_val and isinstance(m_val, list):
                    move_ids.append(m_val[0])
                elif isinstance(m_val, int):
                    move_ids.append(m_val)

            move_ids = list(set(move_ids))

            if not move_ids:
                return {
                    "status": "success",
                    "attached": [],
                    "not_attached": [],
                    "summary": {"attached_count": 0, "not_attached_count": 0, "total_count": 0}
                }

            domain.append(["id", "in", move_ids])
        else:
            # If no account filter, apply date filters directly on account.move
            if payload.date_from:
                domain.append(["date", ">=", payload.date_from])
            if payload.date_to:
                domain.append(["date", "<=", payload.date_to])

        # Query the moves
        moves = erp.execute_kw(
            "account.move",
            "search_read",
            [domain],
            {
                "fields": ["id", "name", "ref", "date", "amount_total", "partner_id", "journal_id"],
                "order": "date desc, name desc",
                "limit": 300,
            }
        )

        if not moves:
            return {
                "status": "success",
                "attached": [],
                "not_attached": [],
                "summary": {"attached_count": 0, "not_attached_count": 0, "total_count": 0}
            }

        move_ids = [m["id"] for m in moves]

        # Fetch detailed lines for all these moves
        move_lines_data = []
        if move_ids:
            try:
                move_lines_data = erp.execute_kw(
                    "account.move.line",
                    "search_read",
                    [[["move_id", "in", move_ids]]],
                    {"fields": ["id", "move_id", "account_id", "name", "debit", "credit"]}
                )
            except Exception as le:
                print(f"[Detect Attachments] Failed to fetch move lines: {le}")

        # Group lines by move_id
        lines_by_move = {}
        for line in move_lines_data:
            m_id = line["move_id"][0] if isinstance(line["move_id"], list) and len(line["move_id"]) > 0 else (line["move_id"] if isinstance(line["move_id"], int) else None)
            if not m_id:
                continue
            lines_by_move.setdefault(m_id, []).append({
                "id": line["id"],
                "account_code": line["account_id"][1].split(" ")[0] if isinstance(line["account_id"], list) and len(line["account_id"]) > 1 else "",
                "account_name": line["account_id"][1] if isinstance(line["account_id"], list) and len(line["account_id"]) > 1 else "",
                "name": line.get("name") or "",
                "debit": line.get("debit") or 0.0,
                "credit": line.get("credit") or 0.0,
            })

        # Check attachments in ir.attachment
        attachments = erp.execute_kw(
            "ir.attachment",
            "search_read",
            [[["res_model", "=", "account.move"], ["res_id", "in", move_ids]]],
            {
                "fields": ["id", "res_id", "name"],
            }
        )

        attached_move_ids = set()
        move_attachments = {}
        for att in attachments:
            res_id = att["res_id"]
            attached_move_ids.add(res_id)
            move_attachments.setdefault(res_id, []).append({
                "id": att["id"],
                "name": att["name"]
            })

        attached_list = []
        not_attached_list = []

        for m in moves:
            mid = m["id"]

            # Format partner
            partner_name = ""
            p_val = m.get("partner_id")
            if p_val and isinstance(p_val, list) and len(p_val) > 1:
                partner_name = p_val[1]
            elif isinstance(p_val, str):
                partner_name = p_val

            # Format journal
            journal_name = ""
            j_val = m.get("journal_id")
            if j_val and isinstance(j_val, list) and len(j_val) > 1:
                journal_name = j_val[1]

            move_data = {
                "id": mid,
                "name": m.get("name") or "",
                "ref": m.get("ref") or "",
                "date": m.get("date") or "",
                "amount_total": m.get("amount_total") or 0.0,
                "partner_name": partner_name,
                "journal_name": journal_name,
                "attachments": move_attachments.get(mid, []),
                "lines": lines_by_move.get(mid, []),
            }

            if mid in attached_move_ids:
                attached_list.append(move_data)
            else:
                not_attached_list.append(move_data)

        return {
            "status": "success",
            "attached": attached_list,
            "not_attached": not_attached_list,
            "summary": {
                "attached_count": len(attached_list),
                "not_attached_count": len(not_attached_list),
                "total_count": len(moves)
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Odoo query failed: {str(e)}")


@router.get("/accounts")
def get_accounts(db_session: Session = Depends(get_db)):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        users = erp.execute_kw(
            "res.users",
            "search_read",
            [[["login", "=", username]]],
            {"fields": ["company_id"], "limit": 1}
        )
        user_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        domain = []
        if user_company_id:
            domain.append(["company_ids", "in", [user_company_id]])

        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [domain],
            {
                "fields": ["id", "code", "name"],
                "order": "code asc",
                "limit": 1000,
            }
        )
        return accounts
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch accounts: {str(e)}")


@router.get("/attachment/{attachment_id}")
def get_attachment(attachment_id: int, db_session: Session = Depends(get_db)):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        attachment = erp.execute_kw(
            "ir.attachment",
            "search_read",
            [[["id", "=", attachment_id]]],
            {"fields": ["name", "datas", "mimetype"], "limit": 1}
        )

        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found in Odoo.")

        att_data = attachment[0]
        name = att_data.get("name") or "attachment"
        datas_b64 = att_data.get("datas")
        mimetype = att_data.get("mimetype") or "application/octet-stream"

        if not datas_b64:
            raise HTTPException(status_code=404, detail="Attachment contains no data.")

        import base64
        from fastapi.responses import Response
        file_bytes = base64.b64decode(datas_b64)

        return Response(content=file_bytes, media_type=mimetype, headers={
            "Content-Disposition": f"inline; filename={name}"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch attachment: {str(e)}")


@router.get("/journals")
def get_journals(db_session: Session = Depends(get_db)):
    conn = db_session.query(ERPConnection).filter(
        ERPConnection.organization_id == 1,
        ERPConnection.is_active == True
    ).first()

    if not conn:
        raise HTTPException(status_code=404, detail="No active ERP connection found.")

    try:
        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        username = secret_data.get("username")
        password = secret_data.get("password")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt connection credentials.")

    try:
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=username,
            password=password,
        )

        users = erp.execute_kw(
            "res.users",
            "search_read",
            [[["login", "=", username]]],
            {"fields": ["company_id"], "limit": 1}
        )
        user_company_id = users[0]["company_id"][0] if users and users[0].get("company_id") else False

        domain = []
        if user_company_id:
            domain.append(["company_id", "=", user_company_id])

        journals = erp.execute_kw(
            "account.journal",
            "search_read",
            [domain],
            {
                "fields": ["id", "code", "name", "type"],
                "limit": 100,
            }
        )
        return journals
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch journals: {str(e)}")


class TelegramConfigRequest(BaseModel):
    token: str
    is_active: bool = True


@router.get("/telegram-config")
def get_telegram_config():
    import urllib.request

    from app.services.telegram_bot import get_telegram_token

    token = get_telegram_token()
    config_path = settings.storage_path / "telegram_config.json"

    is_active = False
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            is_active = config.get("is_active", False)
        except Exception:
            pass

    if not token:
        return {"token": "", "is_active": is_active, "bot_info": None}

    bot_info = None
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        with urllib.request.urlopen(url, timeout=5) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            if res_data.get("ok"):
                bot_info = {
                    "username": res_data["result"].get("username"),
                    "first_name": res_data["result"].get("first_name"),
                }
    except Exception as e:
        print(f"[Telegram Config] Failed to fetch getMe: {e}")

    # Mask the token for the frontend (only show first 10 chars)
    masked_token = token[:10] + "..." if len(token) > 10 else token

    return {
        "token": masked_token,
        "is_active": is_active,
        "bot_info": bot_info,
    }


@router.post("/telegram-config")
def save_telegram_config(payload: TelegramConfigRequest):
    import urllib.request
    from pathlib import Path
    
    token = payload.token.strip()
    if token:
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            with urllib.request.urlopen(url, timeout=10) as res:
                res_data = json.loads(res.read().decode("utf-8"))
                if not res_data.get("ok"):
                    raise Exception("Invalid token response")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Telegram Bot Token: {str(e)}")
            
    from app.services.telegram_bot import save_telegram_config as bot_save_config
    from app.services.telegram_bot import start_telegram_bot, stop_telegram_bot

    is_active = payload.is_active if token else False
    if not bot_save_config(token, is_active):
        raise HTTPException(status_code=500, detail="Failed to save Telegram configuration.")

    stop_telegram_bot()
    if is_active:
        start_telegram_bot()

    return {"status": "success", "message": "Telegram configuration saved successfully."}


@router.post("/bank-reconciliation")
def bank_reconciliation(
    statement: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Compare bank statement vs Odoo bank account and return discrepancies."""
    import tempfile
    statement_path = ""
    try:
        # Save uploaded statement to temp file
        stmt_suffix = Path(statement.filename).suffix if statement.filename else ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=stmt_suffix) as f:
            shutil.copyfileobj(statement.file, f)
            statement_path = f.name

        # Load Odoo connection and fetch bank transactions
        conn = db.query(ERPConnection).filter(
            ERPConnection.organization_id == 1,
            ERPConnection.is_active == True
        ).first()
        if not conn:
            raise ValueError("لا يوجد اتصال نشط بنظام ERP. يرجى إعداد اتصال Odoo أولاً من صفحة ERP.")

        secret_data = json.loads(decrypt_value(conn.encrypted_secret_ref))
        erp = get_erp_provider(
            provider=conn.provider,
            url=conn.base_url,
            db=conn.database_name or "",
            username=secret_data.get("username", ""),
            password=secret_data.get("password", ""),
        )

        odoo_move_lines = erp.fetch_bank_transactions()
        result = reconcile_with_odoo_data(statement_path, odoo_move_lines)

        return {
            "status": "success",
            "statement_only": [t.model_dump() for t in result.statement_only],
            "ledger_only": [t.model_dump() for t in result.ledger_only],
            "matched": [t.model_dump() for t in result.matched],
            "statement_total": result.statement_total,
            "ledger_total": result.ledger_total,
            "difference": result.difference,
            "statement_count": result.statement_count,
            "ledger_count": result.ledger_count,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bank reconciliation failed: {str(e)}"
        )
    finally:
        if statement_path and os.path.exists(statement_path):
            os.remove(statement_path)