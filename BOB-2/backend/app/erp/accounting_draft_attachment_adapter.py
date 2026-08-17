"""Idempotent attachment writer for unposted accounting drafts.

The adapter is deliberately separate from accounting inference/proposal logic.  It
accepts already-validated bytes, verifies the target account.move is still a draft,
and attaches the source document through ir.attachment without any posting action.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any


class AccountingDraftAttachmentError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class OdooAccountingDraftAttachmentAdapter:
    MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

    def __init__(self, erp: Any):
        self.erp = erp

    @staticmethod
    def _m2o_id(value: Any) -> int | None:
        if isinstance(value, (list, tuple)) and value:
            try:
                return int(value[0]) if value[0] else None
            except (TypeError, ValueError):
                return None
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    def _draft(self, move_id: int) -> dict[str, Any]:
        try:
            rows = self.erp.execute_kw(
                "account.move",
                "search_read",
                [[["id", "=", int(move_id)]]],
                {
                    "fields": ["id", "name", "ref", "state", "company_id"],
                    "limit": 1,
                },
            ) or []
        except Exception as exc:
            raise AccountingDraftAttachmentError(
                "ODOO_DRAFT_ATTACHMENT_TARGET_READ_FAILED",
                f"Failed to read attachment target: {type(exc).__name__}.",
            ) from exc
        if not rows:
            raise AccountingDraftAttachmentError(
                "ODOO_DRAFT_ATTACHMENT_TARGET_NOT_FOUND",
                "The requested Odoo account.move does not exist.",
            )
        row = dict(rows[0])
        if str(row.get("state") or "") != "draft":
            raise AccountingDraftAttachmentError(
                "ODOO_DRAFT_ATTACHMENT_TARGET_NOT_DRAFT",
                "Source documents may be attached by this adapter only while the move is draft.",
            )
        return row

    def _fields(self) -> dict[str, Any]:
        try:
            return self.erp.execute_kw(
                "ir.attachment",
                "fields_get",
                [],
                {"attributes": ["type"]},
            ) or {}
        except Exception as exc:
            raise AccountingDraftAttachmentError(
                "ODOO_ATTACHMENT_FIELDS_READ_FAILED",
                f"Failed to inspect Odoo attachment fields: {type(exc).__name__}.",
            ) from exc

    def attach(
        self,
        *,
        move_id: int,
        filename: str,
        mimetype: str,
        content: bytes,
    ) -> dict[str, Any]:
        clean_name = str(filename or "").strip()
        if not clean_name:
            raise AccountingDraftAttachmentError(
                "ATTACHMENT_FILENAME_REQUIRED",
                "A source-document filename is required.",
            )
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise AccountingDraftAttachmentError(
                "ATTACHMENT_CONTENT_REQUIRED",
                "Source-document bytes are required.",
            )
        raw = bytes(content)
        if len(raw) > self.MAX_ATTACHMENT_BYTES:
            raise AccountingDraftAttachmentError(
                "ATTACHMENT_TOO_LARGE",
                "Source document exceeds the 25 MiB draft-attachment limit.",
            )

        move = self._draft(move_id)
        company_id = self._m2o_id(move.get("company_id"))
        fields = self._fields()
        sha1 = hashlib.sha1(raw).hexdigest()
        sha256 = hashlib.sha256(raw).hexdigest()

        domain = [
            ["res_model", "=", "account.move"],
            ["res_id", "=", int(move_id)],
        ]
        if "checksum" in fields:
            domain.append(["checksum", "=", sha1])
        else:
            domain.append(["name", "=", clean_name])

        try:
            existing = self.erp.execute_kw(
                "ir.attachment",
                "search_read",
                [domain],
                {
                    "fields": [
                        field
                        for field in ("id", "name", "mimetype", "checksum", "file_size", "res_model", "res_id")
                        if field in fields
                    ],
                    "limit": 2,
                },
            ) or []
        except Exception as exc:
            raise AccountingDraftAttachmentError(
                "ODOO_ATTACHMENT_IDEMPOTENCY_LOOKUP_FAILED",
                f"Failed to check existing source attachment: {type(exc).__name__}.",
            ) from exc

        if len(existing) > 1:
            raise AccountingDraftAttachmentError(
                "ODOO_DUPLICATE_SOURCE_ATTACHMENTS",
                "More than one identical source attachment already exists on this draft.",
            )
        if existing:
            row = dict(existing[0])
            return {
                "created": False,
                "idempotent_reuse": True,
                "attachment_id": int(row["id"]),
                "move_id": int(move_id),
                "filename": str(row.get("name") or clean_name),
                "mimetype": str(row.get("mimetype") or mimetype or "application/octet-stream"),
                "sha256": sha256,
            }

        vals: dict[str, Any] = {
            "name": clean_name,
            "type": "binary",
            "datas": base64.b64encode(raw).decode("ascii"),
            "res_model": "account.move",
            "res_id": int(move_id),
        }
        if "mimetype" in fields and mimetype:
            vals["mimetype"] = str(mimetype)
        if "company_id" in fields and company_id:
            vals["company_id"] = company_id
        if "description" in fields:
            vals["description"] = f"BOB source document SHA256:{sha256}"

        try:
            attachment_id = self.erp.execute_kw("ir.attachment", "create", [vals])
            if isinstance(attachment_id, list):
                attachment_id = attachment_id[0]
            attachment_id = int(attachment_id)
        except Exception as exc:
            raise AccountingDraftAttachmentError(
                "ODOO_SOURCE_ATTACHMENT_CREATE_FAILED",
                f"Failed to attach source document to Odoo draft: {type(exc).__name__}.",
            ) from exc

        try:
            rows = self.erp.execute_kw(
                "ir.attachment",
                "read",
                [[attachment_id]],
                {
                    "fields": [
                        field
                        for field in ("id", "name", "mimetype", "checksum", "file_size", "res_model", "res_id")
                        if field in fields
                    ]
                },
            ) or []
        except Exception as exc:
            raise AccountingDraftAttachmentError(
                "ODOO_SOURCE_ATTACHMENT_VERIFY_FAILED",
                f"Attachment was created but could not be re-read: {type(exc).__name__}.",
            ) from exc
        if not rows:
            raise AccountingDraftAttachmentError(
                "ODOO_SOURCE_ATTACHMENT_VERIFY_EMPTY",
                "Odoo returned no attachment while verifying the source document.",
            )
        row = dict(rows[0])
        if str(row.get("res_model") or "") != "account.move" or int(row.get("res_id") or 0) != int(move_id):
            raise AccountingDraftAttachmentError(
                "ODOO_SOURCE_ATTACHMENT_TARGET_MISMATCH",
                "Created attachment is not linked to the requested account.move.",
            )
        if "checksum" in fields and str(row.get("checksum") or "") != sha1:
            raise AccountingDraftAttachmentError(
                "ODOO_SOURCE_ATTACHMENT_CHECKSUM_MISMATCH",
                "Created attachment checksum does not match the uploaded source document.",
            )

        return {
            "created": True,
            "idempotent_reuse": False,
            "attachment_id": attachment_id,
            "move_id": int(move_id),
            "filename": str(row.get("name") or clean_name),
            "mimetype": str(row.get("mimetype") or mimetype or "application/octet-stream"),
            "sha256": sha256,
        }
