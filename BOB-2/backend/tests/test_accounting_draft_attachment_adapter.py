from __future__ import annotations

import base64
import hashlib

from app.erp.accounting_draft_attachment_adapter import OdooAccountingDraftAttachmentAdapter


class _AttachmentERPStub:
    def __init__(self):
        self.calls = []
        self.created_vals = None

    def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        if model == "account.move" and method == "search_read":
            return [
                {
                    "id": 23060,
                    "name": False,
                    "ref": "BOB-MLV2-test",
                    "state": "draft",
                    "company_id": [1, "Company"],
                }
            ]
        if model == "ir.attachment" and method == "fields_get":
            return {
                "id": {"type": "integer"},
                "name": {"type": "char"},
                "type": {"type": "selection"},
                "datas": {"type": "binary"},
                "mimetype": {"type": "char"},
                "checksum": {"type": "char"},
                "file_size": {"type": "integer"},
                "res_model": {"type": "char"},
                "res_id": {"type": "many2one"},
                "company_id": {"type": "many2one"},
                "description": {"type": "text"},
            }
        if model == "ir.attachment" and method == "search_read":
            return []
        if model == "ir.attachment" and method == "create":
            self.created_vals = args[0]
            return 501
        if model == "ir.attachment" and method == "read":
            raw = base64.b64decode(self.created_vals["datas"])
            return [
                {
                    "id": 501,
                    "name": self.created_vals["name"],
                    "mimetype": self.created_vals["mimetype"],
                    "checksum": hashlib.sha1(raw).hexdigest(),
                    "file_size": len(raw),
                    "res_model": "account.move",
                    "res_id": 23060,
                }
            ]
        raise AssertionError(f"Unexpected ERP call: {model}.{method}")


def test_attachment_adapter_links_source_document_to_draft_without_posting():
    erp = _AttachmentERPStub()
    content = b"safe source pdf bytes"
    result = OdooAccountingDraftAttachmentAdapter(erp).attach(
        move_id=23060,
        filename="receipt.pdf",
        mimetype="application/pdf",
        content=content,
    )
    assert result["created"] is True
    assert result["move_id"] == 23060
    assert result["sha256"] == hashlib.sha256(content).hexdigest()
    assert erp.created_vals["res_model"] == "account.move"
    assert erp.created_vals["res_id"] == 23060
    methods = [method for _model, method, _args, _kwargs in erp.calls]
    assert "action_post" not in methods


class _ExistingAttachmentERPStub(_AttachmentERPStub):
    def execute_kw(self, model, method, args, kwargs=None):
        if model == "ir.attachment" and method == "search_read":
            return [
                {
                    "id": 777,
                    "name": "receipt.pdf",
                    "mimetype": "application/pdf",
                    "checksum": hashlib.sha1(b"safe source pdf bytes").hexdigest(),
                    "file_size": len(b"safe source pdf bytes"),
                    "res_model": "account.move",
                    "res_id": 23060,
                }
            ]
        return super().execute_kw(model, method, args, kwargs)


def test_attachment_adapter_reuses_identical_attachment_idempotently():
    erp = _ExistingAttachmentERPStub()
    result = OdooAccountingDraftAttachmentAdapter(erp).attach(
        move_id=23060,
        filename="receipt.pdf",
        mimetype="application/pdf",
        content=b"safe source pdf bytes",
    )
    assert result["created"] is False
    assert result["idempotent_reuse"] is True
    assert result["attachment_id"] == 777
