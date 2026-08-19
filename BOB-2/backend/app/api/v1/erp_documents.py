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
from app.services import erp_document_matching

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

                doc_amount, doc_date, doc_class, doc_desc = erp_document_matching.extract_document_fields(
                    analysis, fields
                )

                norm_doc_date = erp_document_matching.normalize_date(doc_date)
                logger.info(f"[DIAGNOSTIC] Normalized Doc Date: '{norm_doc_date}'")

                moves = erp_document_matching.find_candidate_moves(erp, doc_amount, norm_doc_date)

                vector_scores = erp_document_matching.compute_vector_scores(
                    doc_desc, file.filename, doc_class, doc_amount, doc_date, moves
                )

                matched_moves = erp_document_matching.score_and_rank_moves(
                    fields, doc_amount, doc_date, doc_desc, moves, vector_scores, erp, conn
                )

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

