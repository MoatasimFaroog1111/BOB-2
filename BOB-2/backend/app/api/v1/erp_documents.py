"""Document upload, matching, and ERP attachment HTTP component."""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.erp.document_ai import GuardianDocumentAI
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value
from app.security.tenant_scope import current_organization_id

logger = logging.getLogger(__name__)
router = APIRouter()


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
        ERPConnection.organization_id == current_organization_id(required=True),
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

    logger.info(f"=== START MATCHING DIAGNOSTIC FOR {len(files)} FILES ===")
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

                logger.info(f"[DIAGNOSTIC] File: {file.filename}")
                logger.info(f"[DIAGNOSTIC] Extracted Class: {doc_class}")
                logger.info(f"[DIAGNOSTIC] Extracted Amount: {doc_amount} (Type: {type(doc_amount)})")
                logger.info(f"[DIAGNOSTIC] Initial Extracted Date: {doc_date}")

                if not doc_date:
                    text_month_pat = r'\b(\d{1,2})\s+(يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يونيه|يوليو|يوليه|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b'
                    match = re.search(text_month_pat, doc_desc, re.IGNORECASE)
                    if match:
                        doc_date = match.group(0)
                        logger.info(f"[DIAGNOSTIC] Fallback Date Match (text month): {doc_date}")
                    else:
                        match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", doc_desc)
                        if match:
                            doc_date = match.group(0)
                            logger.info(f"[DIAGNOSTIC] Fallback Date Match (DD-MM-YYYY): {doc_date}")
                        else:
                            match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", doc_desc)
                            if match:
                                doc_date = match.group(0)
                                logger.info(f"[DIAGNOSTIC] Fallback Date Match (YYYY-MM-DD): {doc_date}")

                norm_doc_date = _normalize_date(doc_date)
                logger.info(f"[DIAGNOSTIC] Normalized Doc Date: '{norm_doc_date}'")

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
                        
                    logger.info(f"[DIAGNOSTIC] Fetching moves directly from Odoo matching: date={norm_doc_date}, amount_range=[{min_val:.2f}, {max_val:.2f}]")
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
                        logger.info(f"[DIAGNOSTIC] Odoo database search returned {len(moves)} moves.")
                    except Exception as e:
                        logger.info(f"[DIAGNOSTIC] Odoo search failed: {e}")
                else:
                    logger.info(f"[DIAGNOSTIC] Skipping Odoo search because amount is missing: amount={doc_amount}")

                # --- Vector DB: index document and compute vector similarity ---
                vector_scores: dict[int, float] = {}
                try:
                    from app.services.vector_db import index_document, search_similar_documents
                    doc_meta = {
                        "filename": file.filename or "",
                        "document_class": doc_class,
                        "amount": str(doc_amount or ""),
                        "date": str(doc_date or ""),
                    }
                    index_document(doc_desc[:4000], file.filename or "unknown", doc_meta)

                    for move in moves:
                        move_text = " ".join(filter(None, [
                            str(move.get("name") or ""),
                            str(move.get("ref") or ""),
                            str(move.get("payment_reference") or ""),
                        ]))
                        if move_text.strip():
                            index_document(
                                move_text,
                                f"odoo_move_{move.get('id', 0)}",
                                {"move_id": str(move.get("id", "")), "source": "odoo_move"},
                            )

                    if doc_desc.strip():
                        hits = search_similar_documents(doc_desc[:4000], n_results=50)
                        for hit in hits:
                            meta = hit.get("metadata", {})
                            move_id_str = meta.get("move_id", "")
                            if move_id_str and meta.get("source") == "odoo_move":
                                try:
                                    vector_scores[int(move_id_str)] = hit.get("score", 0.0)
                                except (ValueError, TypeError):
                                    pass
                except Exception as vec_err:
                    logger.info(f"[DIAGNOSTIC] Vector DB scoring skipped: {vec_err}")

                logger.info(f"[DIAGNOSTIC] Comparing with {len(moves)} Odoo moves...")

                for move in moves:
                    amount_s = _amount_score(doc_amount, move.get("amount_total"))
                    move_date = move.get("invoice_date") or move.get("date")
                    date_s = _date_score(doc_date, move_date)
                    ref_s = _reference_score(doc_desc, move)
                    desc_s = _description_score(doc_desc, move)
                    partner_s = _partner_score(fields, doc_desc, move)
                    vec_s = vector_scores.get(move.get("id", 0), 0.0)

                    # Print compare info if amount is close (score > 0) or date matches (score > 0)
                    if amount_s > 0 or date_s > 0:
                        logger.info(f"  -> {move.get('name')}: AmountScore={amount_s:.2f} (Odoo={move.get('amount_total')}, Doc={doc_amount}), DateScore={date_s:.2f} (Odoo={move.get('date')}, Doc={doc_date}), VectorScore={vec_s:.2f}")

                    if amount_s <= 0:
                        continue

                    if date_s <= 0 and ref_s < 0.80 and desc_s < 0.55 and vec_s < 0.70:
                        continue

                    final_score = (
                        amount_s * 35
                        + date_s * 20
                        + ref_s * 12
                        + partner_s * 8
                        + desc_s * 5
                        + vec_s * 20
                    )

                    if final_score < 45:
                        logger.info(f"    * Move {move.get('name')} skipped: final score {final_score:.1f} < 45")
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
                            logger.info(f"[DIAGNOSTIC] Failed to fetch Odoo attachments: {e}")

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
                            logger.info(f"[DIAGNOSTIC] Failed to fetch Odoo move lines: {e}")

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
                            "vector_similarity_score": round(vec_s * 100, 1),
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
        ERPConnection.organization_id == current_organization_id(required=True),
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

