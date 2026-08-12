"""Application service for bank-statement -> daily entry -> audit workflow.

HTTP handlers delegate here so persistence, Odoo reads, immutable evidence, and status
transitions remain outside presentation code. This service never posts an account.move.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.money import money_to_str, parse_money
from app.erp.bank_reconciliation import parse_file
from app.erp.bank_rule_suggestions import fetch_odoo_bank_rules
from app.erp.factory import get_erp_provider
from app.models.core import (
    ApprovalRequest,
    AuditLog,
    Document,
    ERPConnection,
    JournalEntryRecord,
)
from app.security.encryption import decrypt_value
from app.services.accounting_audit_engine import AccountingAuditEngine
from app.services.daily_bank_entry_builder import (
    BankJournalContext,
    DailyBankEntryBuilder,
    DailyBankEntryBuildError,
)


REVIEW_REQUEST_TYPE = "daily_bank_entry_audit"
PENDING_AUDIT = "pending_audit"
AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
NEEDS_REVISION = "needs_revision"
APPROVED = "approved"


class DailyBankReviewError(ValueError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ReviewDocumentStore:
    """Tenant-isolated persisted evidence store for review packages."""

    def __init__(self, storage_root: str | Path | None = None) -> None:
        self._root = Path(storage_root or settings.STORAGE_DIR).resolve()

    def _tenant_dir(self, organization_id: int) -> Path:
        path = (self._root / "daily-bank-review" / f"org-{organization_id}").resolve()
        if not path.is_relative_to(self._root):
            raise DailyBankReviewError("Invalid review document storage path")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def persist(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> tuple[Document, dict[str, Any]]:
        if not content:
            raise DailyBankReviewError("Source bank statement is empty")
        suffix = Path(filename).suffix.lower()
        safe_disk_name = f"{uuid.uuid4().hex}{suffix}"
        target = (self._tenant_dir(organization_id) / safe_disk_name).resolve()
        if not target.is_relative_to(self._root):
            raise DailyBankReviewError("Invalid review document storage path")
        target.write_bytes(content)
        sha256 = hashlib.sha256(content).hexdigest()

        document = Document(
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename=filename,
            content_type=content_type,
            storage_path=str(target),
            status="review_draft",
            classification="bank_statement",
        )
        db.add(document)
        db.flush()
        evidence = {
            "document_id": document.id,
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "size": len(content),
            "sha256": sha256,
            "classification": "bank_statement",
        }
        return document, evidence

    def resolve_tenant_path(self, document: Document, organization_id: int) -> Path:
        if document.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Review document not found.")
        target = Path(document.storage_path).resolve()
        tenant_root = self._tenant_dir(organization_id)
        if not target.is_relative_to(tenant_root) or not target.is_file():
            raise HTTPException(status_code=404, detail="Review document evidence is unavailable.")
        return target


class TenantERPResolver:
    """Resolve the tenant's active ERP provider without exposing credentials."""

    def resolve(self, db: Session, organization_id: int):
        connection = (
            db.query(ERPConnection)
            .filter(
                ERPConnection.organization_id == organization_id,
                ERPConnection.is_active.is_(True),
            )
            .order_by(ERPConnection.id.asc())
            .first()
        )
        if not connection or not connection.encrypted_secret_ref:
            raise HTTPException(status_code=404, detail="No active ERP connection found.")
        try:
            secret = json.loads(decrypt_value(connection.encrypted_secret_ref))
            username = str(secret["username"])
            password = str(secret["password"])
        except Exception as exc:
            raise HTTPException(status_code=503, detail="ERP credentials are unavailable.") from exc

        provider = get_erp_provider(
            provider=connection.provider,
            url=connection.base_url,
            db=connection.database_name or "",
            username=username,
            password=password,
        )
        return connection, provider


class OdooDailyBankContextLoader:
    """Read the exact bank journal, Bank Rules, and account metadata from Odoo."""

    @staticmethod
    def _account_ids_from_rules(rules: list[dict[str, Any]]) -> set[int]:
        ids: set[int] = set()
        for rule in rules:
            for line in rule.get("lines") or []:
                value = line.get("account_id")
                if isinstance(value, (list, tuple)) and value:
                    ids.add(int(value[0]))
                elif isinstance(value, int):
                    ids.add(value)
        return ids

    def load(
        self,
        erp: Any,
        *,
        journal_id: int,
        company_id: int | None = None,
    ) -> tuple[BankJournalContext, list[dict[str, Any]], dict[int, dict[str, Any]]]:
        journals = erp.discover_bank_journals(company_id=company_id)
        selected = next(
            (item for item in journals if int(item.get("journal_id") or 0) == int(journal_id)),
            None,
        )
        if not selected:
            raise HTTPException(status_code=422, detail="Selected journal is not an active Odoo bank journal.")
        account_id = int(selected.get("account_id") or 0)
        if account_id <= 0:
            raise HTTPException(status_code=422, detail="Selected Odoo bank journal has no liquidity account.")
        selected_company_id = int(selected.get("company_id") or 0) or company_id

        rules = fetch_odoo_bank_rules(
            erp,
            company_id=selected_company_id,
            bank_journal_id=int(journal_id),
            limit=500,
        )
        account_ids = self._account_ids_from_rules(rules)
        account_ids.add(account_id)
        accounts = erp.execute_kw(
            "account.account",
            "search_read",
            [[["id", "in", sorted(account_ids)]]],
            {"fields": ["id", "code", "name"], "limit": max(len(account_ids), 1)},
        )
        account_catalog = {int(row["id"]): row for row in accounts if row.get("id")}
        bank_account = account_catalog.get(account_id) or {}
        bank_code = str(bank_account.get("code") or selected.get("account_code") or "").strip()
        bank_name = str(bank_account.get("name") or selected.get("account_name") or "").strip()
        if not bank_code or not bank_name:
            raise HTTPException(status_code=422, detail="Odoo bank account code/name could not be resolved.")

        journal = BankJournalContext(
            journal_id=int(selected["journal_id"]),
            journal_name=str(selected.get("journal_name") or ""),
            journal_code=str(selected.get("journal_code") or ""),
            bank_account_id=account_id,
            bank_account_code=bank_code,
            bank_account_name=bank_name,
            company_id=selected_company_id,
        )
        return journal, rules, account_catalog


class DailyBankReviewService:
    def __init__(
        self,
        *,
        document_store: ReviewDocumentStore | None = None,
        erp_resolver: TenantERPResolver | None = None,
        context_loader: OdooDailyBankContextLoader | None = None,
        builder: DailyBankEntryBuilder | None = None,
        auditor: AccountingAuditEngine | None = None,
    ) -> None:
        self._documents = document_store or ReviewDocumentStore()
        self._erp_resolver = erp_resolver or TenantERPResolver()
        self._context_loader = context_loader or OdooDailyBankContextLoader()
        self._builder = builder or DailyBankEntryBuilder()
        self._auditor = auditor or AccountingAuditEngine()

    @staticmethod
    def _audit_log(
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        action: str,
        entity_type: str,
        entity_id: str | None,
        details: dict[str, Any],
    ) -> None:
        db.add(AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        ))

    def _rebuild_document_entries(
        self,
        db: Session,
        *,
        organization_id: int,
        document: Document,
        journal_id: int,
        company_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        source_path = self._documents.resolve_tenant_path(document, organization_id)
        source_bytes = source_path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        transactions = parse_file(str(source_path))
        if not transactions:
            raise HTTPException(status_code=422, detail="No bank transactions were found in the source statement.")
        _connection, erp = self._erp_resolver.resolve(db, organization_id)
        journal, rules, account_catalog = self._context_loader.load(
            erp,
            journal_id=journal_id,
            company_id=company_id,
        )
        try:
            entries = self._builder.build(
                transactions,
                rules=rules,
                journal=journal,
                account_catalog=account_catalog,
            )
        except DailyBankEntryBuildError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        context = {
            "journal_id": journal.journal_id,
            "journal_name": journal.journal_name,
            "journal_code": journal.journal_code,
            "bank_account_id": journal.bank_account_id,
            "bank_account_code": journal.bank_account_code,
            "bank_account_name": journal.bank_account_name,
            "company_id": journal.company_id,
            "rule_count": len(rules),
        }
        return entries, context, source_hash

    def prepare(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        filename: str,
        content_type: str | None,
        content: bytes,
        journal_id: int,
        company_id: int | None = None,
    ) -> dict[str, Any]:
        document: Document | None = None
        try:
            document, source = self._documents.persist(
                db,
                organization_id=organization_id,
                user_id=user_id,
                filename=filename,
                content_type=content_type,
                content=content,
            )
            entries, context, rebuilt_hash = self._rebuild_document_entries(
                db,
                organization_id=organization_id,
                document=document,
                journal_id=journal_id,
                company_id=company_id,
            )
            if rebuilt_hash != source["sha256"]:
                raise DailyBankReviewError("Persisted source statement failed integrity verification")
            document.status = "review_prepared"
            package_summary = {
                "document_id": document.id,
                "daily_entry_count": len(entries),
                "transaction_count": sum(int(entry["transaction_count"]) for entry in entries),
                "unresolved_count": sum(int(entry["unresolved_count"]) for entry in entries),
                "low_confidence_count": sum(int(entry["low_confidence_count"]) for entry in entries),
                "rule_count": context["rule_count"],
                "journal_id": context["journal_id"],
            }
            self._audit_log(
                db,
                organization_id=organization_id,
                user_id=user_id,
                action="daily_bank_review.prepared",
                entity_type="document",
                entity_id=str(document.id),
                details={**package_summary, "source_sha256": source["sha256"]},
            )
            db.commit()
            return {
                "status": "prepared",
                "safe_to_post": False,
                "human_review_required": True,
                "source_document": source,
                "bank_journal": context,
                "summary": package_summary,
                "entries": entries,
            }
        except Exception:
            db.rollback()
            if document is not None:
                try:
                    path = Path(document.storage_path)
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
            raise

    @staticmethod
    def _approval_for_journal_entry(
        db: Session,
        *,
        organization_id: int,
        journal_entry_id: int,
    ) -> ApprovalRequest | None:
        candidates = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.request_type == REVIEW_REQUEST_TYPE,
            )
            .order_by(ApprovalRequest.id.desc())
            .limit(500)
            .all()
        )
        for approval in candidates:
            if int((approval.payload or {}).get("journal_entry_id") or 0) == journal_entry_id:
                return approval
        return None

    def submit(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        document_id: int,
        journal_id: int,
        company_id: int | None = None,
    ) -> dict[str, Any]:
        document = (
            db.query(Document)
            .filter(Document.id == document_id, Document.organization_id == organization_id)
            .first()
        )
        if not document or document.classification != "bank_statement":
            raise HTTPException(status_code=404, detail="Prepared bank statement was not found.")

        entries, context, source_hash = self._rebuild_document_entries(
            db,
            organization_id=organization_id,
            document=document,
            journal_id=journal_id,
            company_id=company_id,
        )
        source_document = {
            "document_id": document.id,
            "filename": document.filename,
            "content_type": document.content_type or "application/octet-stream",
            "size": Path(document.storage_path).stat().st_size,
            "sha256": source_hash,
            "classification": document.classification,
        }

        reviews: list[dict[str, Any]] = []
        try:
            for entry in entries:
                reference = f"BANK-REVIEW:{document.id}:{entry['entry_date']}:{entry['entry_hash'][:16]}"
                record = (
                    db.query(JournalEntryRecord)
                    .filter(
                        JournalEntryRecord.organization_id == organization_id,
                        JournalEntryRecord.reference == reference,
                    )
                    .first()
                )
                if record is None:
                    record = JournalEntryRecord(
                        organization_id=organization_id,
                        created_by_user_id=user_id,
                        entry_date=date.fromisoformat(str(entry["entry_date"])),
                        reference=reference,
                        memo=f"Daily bank review from {document.filename}",
                        status="awaiting_audit",
                        lines=entry["lines"],
                        total_debit=parse_money(entry["total_debit"]),
                        total_credit=parse_money(entry["total_credit"]),
                    )
                    db.add(record)
                    db.flush()

                approval = self._approval_for_journal_entry(
                    db,
                    organization_id=organization_id,
                    journal_entry_id=record.id,
                )
                if approval is None:
                    package_core = {
                        "journal_entry_id": record.id,
                        "source_document": source_document,
                        "supporting_documents": [],
                        "bank_journal": context,
                        "entry": entry,
                        "prepared_by_user_id": user_id,
                        "prepared_at": _utc_now_iso(),
                        "safe_to_post": False,
                        "posting_performed": False,
                    }
                    package_hash = _canonical_hash(package_core)
                    approval = ApprovalRequest(
                        organization_id=organization_id,
                        requested_by_user_id=user_id,
                        request_type=REVIEW_REQUEST_TYPE,
                        status=PENDING_AUDIT,
                        payload={**package_core, "package_hash": package_hash},
                    )
                    db.add(approval)
                    db.flush()
                    self._audit_log(
                        db,
                        organization_id=organization_id,
                        user_id=user_id,
                        action="daily_bank_review.submitted_for_audit",
                        entity_type="approval_request",
                        entity_id=str(approval.id),
                        details={
                            "journal_entry_id": record.id,
                            "document_id": document.id,
                            "entry_date": entry["entry_date"],
                            "entry_hash": entry["entry_hash"],
                            "package_hash": package_hash,
                            "ready_for_posting": entry["ready_for_posting"],
                        },
                    )

                reviews.append({
                    "approval_id": approval.id,
                    "journal_entry_id": record.id,
                    "entry_date": entry["entry_date"],
                    "status": approval.status,
                    "transaction_count": entry["transaction_count"],
                    "unresolved_count": entry["unresolved_count"],
                    "low_confidence_count": entry["low_confidence_count"],
                    "total_debit": entry["total_debit"],
                    "total_credit": entry["total_credit"],
                })

            document.status = "pending_audit"
            db.commit()
        except Exception:
            db.rollback()
            raise

        return {
            "status": "submitted_for_audit",
            "safe_to_post": False,
            "posting_performed": False,
            "review_count": len(reviews),
            "reviews": reviews,
        }

    @staticmethod
    def _serialize_approval(approval: ApprovalRequest) -> dict[str, Any]:
        payload = approval.payload or {}
        entry = payload.get("entry") or {}
        source = payload.get("source_document") or {}
        journal = payload.get("bank_journal") or {}
        audit_result = payload.get("audit_result")
        return {
            "approval_id": approval.id,
            "status": approval.status,
            "requested_by_user_id": approval.requested_by_user_id,
            "approved_by_user_id": approval.approved_by_user_id,
            "decision_note": approval.decision_note,
            "created_at": approval.created_at.isoformat() if approval.created_at else None,
            "updated_at": approval.updated_at.isoformat() if approval.updated_at else None,
            "journal_entry_id": payload.get("journal_entry_id"),
            "entry_date": entry.get("entry_date"),
            "transaction_count": entry.get("transaction_count"),
            "unresolved_count": entry.get("unresolved_count"),
            "low_confidence_count": entry.get("low_confidence_count"),
            "total_debit": entry.get("total_debit"),
            "total_credit": entry.get("total_credit"),
            "ready_for_posting": entry.get("ready_for_posting", False),
            "source_document": source,
            "bank_journal": journal,
            "audit_result": audit_result,
            "safe_to_post": False,
            "posting_performed": False,
        }

    def list_queue(self, db: Session, *, organization_id: int, limit: int = 100) -> list[dict[str, Any]]:
        rows = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.request_type == REVIEW_REQUEST_TYPE,
            )
            .order_by(ApprovalRequest.id.desc())
            .limit(min(max(limit, 1), 200))
            .all()
        )
        return [self._serialize_approval(row) for row in rows]

    def get_review(self, db: Session, *, organization_id: int, approval_id: int) -> dict[str, Any]:
        approval = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.request_type == REVIEW_REQUEST_TYPE,
            )
            .first()
        )
        if not approval:
            raise HTTPException(status_code=404, detail="Daily bank audit package not found.")
        result = self._serialize_approval(approval)
        result["package"] = approval.payload
        return result

    def audit(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        approval_id: int,
    ) -> dict[str, Any]:
        approval = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.request_type == REVIEW_REQUEST_TYPE,
            )
            .first()
        )
        if not approval:
            raise HTTPException(status_code=404, detail="Daily bank audit package not found.")
        if approval.status == APPROVED:
            raise HTTPException(status_code=409, detail="Approved review packages are immutable for re-audit.")

        payload = dict(approval.payload or {})
        source = dict(payload.get("source_document") or {})
        submitted_entry = dict(payload.get("entry") or {})
        journal = dict(payload.get("bank_journal") or {})
        document_id = int(source.get("document_id") or 0)
        journal_id = int(journal.get("journal_id") or 0)
        document = (
            db.query(Document)
            .filter(Document.id == document_id, Document.organization_id == organization_id)
            .first()
        )
        if not document:
            raise HTTPException(status_code=422, detail="Source bank statement evidence is missing.")

        current_entries, _context, actual_hash = self._rebuild_document_entries(
            db,
            organization_id=organization_id,
            document=document,
            journal_id=journal_id,
            company_id=journal.get("company_id"),
        )
        current = next(
            (entry for entry in current_entries if entry.get("entry_date") == submitted_entry.get("entry_date")),
            None,
        )
        current_hash = str(current.get("entry_hash")) if current else "missing-current-entry"
        source_hash_verified = bool(source.get("sha256") and source.get("sha256") == actual_hash)
        audit_result = self._auditor.audit_entry(
            submitted_entry,
            source_document=source,
            source_hash_verified=source_hash_verified,
            current_entry_hash=current_hash,
        )
        audit_result["audited_at"] = _utc_now_iso()
        audit_result["audited_by_user_id"] = user_id
        audit_result["current_entry_hash"] = current_hash
        audit_result["source_hash_verified"] = source_hash_verified

        payload["audit_result"] = audit_result
        payload["safe_to_post"] = False
        payload["posting_performed"] = False
        approval.payload = payload
        approval.status = NEEDS_REVISION if audit_result["blocking_count"] else AWAITING_HUMAN_APPROVAL

        journal_entry_id = int(payload.get("journal_entry_id") or 0)
        record = (
            db.query(JournalEntryRecord)
            .filter(JournalEntryRecord.id == journal_entry_id, JournalEntryRecord.organization_id == organization_id)
            .first()
        )
        if record:
            record.status = "needs_revision" if audit_result["blocking_count"] else "audit_reviewed"

        self._audit_log(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="daily_bank_review.audited",
            entity_type="approval_request",
            entity_id=str(approval.id),
            details={
                "journal_entry_id": journal_entry_id,
                "risk_level": audit_result["risk_level"],
                "recommendation": audit_result["recommendation"],
                "blocking_count": audit_result["blocking_count"],
                "warning_count": audit_result["warning_count"],
                "source_hash_verified": source_hash_verified,
                "rule_drift": current_hash != str(submitted_entry.get("entry_hash") or ""),
            },
        )
        db.commit()
        return self.get_review(db, organization_id=organization_id, approval_id=approval_id)

    def decide(
        self,
        db: Session,
        *,
        organization_id: int,
        user_id: int,
        approval_id: int,
        decision: str,
        note: str = "",
    ) -> dict[str, Any]:
        approval = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.organization_id == organization_id,
                ApprovalRequest.request_type == REVIEW_REQUEST_TYPE,
            )
            .first()
        )
        if not approval:
            raise HTTPException(status_code=404, detail="Daily bank audit package not found.")
        normalized = decision.strip().lower()
        if normalized not in {"approve", "return"}:
            raise HTTPException(status_code=422, detail="Decision must be 'approve' or 'return'.")

        payload = dict(approval.payload or {})
        audit_result = payload.get("audit_result") or {}
        journal_entry_id = int(payload.get("journal_entry_id") or 0)
        record = (
            db.query(JournalEntryRecord)
            .filter(JournalEntryRecord.id == journal_entry_id, JournalEntryRecord.organization_id == organization_id)
            .first()
        )
        if not record:
            raise HTTPException(status_code=422, detail="Journal entry review snapshot is missing.")

        if normalized == "approve":
            if approval.status != AWAITING_HUMAN_APPROVAL:
                raise HTTPException(status_code=409, detail="The package must complete audit before human approval.")
            if not audit_result or int(audit_result.get("blocking_count") or 0) > 0:
                raise HTTPException(status_code=409, detail="Blocking audit findings prevent approval.")
            approval.status = APPROVED
            approval.approved_by_user_id = user_id
            record.status = "approved"
            action = "daily_bank_review.human_approved"
        else:
            if approval.status == APPROVED:
                raise HTTPException(status_code=409, detail="Approved packages cannot be returned by this workflow.")
            approval.status = NEEDS_REVISION
            record.status = "needs_revision"
            action = "daily_bank_review.returned_for_revision"

        approval.decision_note = note.strip()[:4000] or None
        payload["human_decision"] = {
            "decision": normalized,
            "decided_by_user_id": user_id,
            "decided_at": _utc_now_iso(),
            "note": approval.decision_note,
        }
        payload["safe_to_post"] = False
        payload["posting_performed"] = False
        approval.payload = payload
        self._audit_log(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            entity_type="approval_request",
            entity_id=str(approval.id),
            details={
                "journal_entry_id": record.id,
                "decision": normalized,
                "posting_performed": False,
            },
        )
        db.commit()
        return self.get_review(db, organization_id=organization_id, approval_id=approval_id)

    def review_document_path(self, db: Session, *, organization_id: int, document_id: int) -> tuple[Document, Path]:
        document = (
            db.query(Document)
            .filter(Document.id == document_id, Document.organization_id == organization_id)
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail="Review document not found.")
        return document, self._documents.resolve_tenant_path(document, organization_id)


daily_bank_review_service = DailyBankReviewService()
