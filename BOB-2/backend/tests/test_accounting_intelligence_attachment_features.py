from app.ml.accounting_intelligence.attachment_features import (
    AttachmentTextFeature,
    GuardedERPAttachmentFeatureExtractor,
)
from app.ml.accounting_intelligence.contracts import HistoricalAccountingExample
from app.ml.accounting_intelligence.odoo_attachment_enricher import OdooAttachmentLearningEnricher


class ExplodingDocumentAI:
    def extract_text(self, _path: str) -> str:
        raise AssertionError("OCR/parser must not be called for rejected input")


class FakeExtractor:
    def extract(self, attachment):
        return AttachmentTextFeature(
            attachment_id=int(attachment["id"]),
            filename=str(attachment["name"]),
            text="Tax invoice internet service VAT 15 percent SAR 1150",
            status="extracted",
        )


class FakeERP:
    def execute_kw(self, model, method, args, kwargs=None):
        assert model == "ir.attachment"
        if method == "search_read":
            return [
                {
                    "id": 90,
                    "name": "invoice.pdf",
                    "res_id": 1,
                    "mimetype": "application/pdf",
                    "file_size": 100,
                    "type": "binary",
                }
            ]
        if method == "read":
            return [
                {
                    "id": 90,
                    "name": "invoice.pdf",
                    "mimetype": "application/pdf",
                    "datas": "unused-by-fake-extractor",
                }
            ]
        raise AssertionError(f"Unexpected method: {method}")


def test_unsupported_attachment_never_reaches_parser():
    extractor = GuardedERPAttachmentFeatureExtractor(document_ai=ExplodingDocumentAI())
    result = extractor.extract({"id": 1, "name": "macro.xlsm", "datas": "AA=="})
    assert result.status == "skipped_unsupported_type"
    assert result.text == ""


def test_invalid_base64_is_rejected_before_parser():
    extractor = GuardedERPAttachmentFeatureExtractor(document_ai=ExplodingDocumentAI())
    result = extractor.extract({"id": 2, "name": "invoice.pdf", "datas": "not-valid-base64***"})
    assert result.status == "rejected"
    assert result.text == ""


def test_non_ascii_base64_payload_is_rejected_before_parser():
    extractor = GuardedERPAttachmentFeatureExtractor(document_ai=ExplodingDocumentAI())
    result = extractor.extract({"id": 3, "name": "invoice.pdf", "datas": "بيانات-ليست-base64"})
    assert result.status == "rejected"
    assert result.text == ""


def test_enricher_feeds_extracted_attachment_text_into_learning_features():
    example = HistoricalAccountingExample(
        source_id=1,
        source_reference="account.move:1",
        text="stc monthly service amount_bucket 1k_9k",
        occurred_on="2026-08-01",
        amount=1150.0,
        currency="SAR",
        move_type="in_invoice",
        journal_id=5,
        partner_id=7,
        debit_account_ids=(10,),
        credit_account_ids=(30,),
        attachment_features=("invoice.pdf application/pdf",),
    )
    enriched, stats = OdooAttachmentLearningEnricher(
        FakeERP(),
        extractor=FakeExtractor(),
    ).enrich([example], max_attachments=10)

    assert stats["requested"] == 1
    assert stats["extracted"] == 1
    assert "tax invoice internet service" in enriched[0].text
    assert any("attachment_content" in feature for feature in enriched[0].attachment_features)
    assert enriched[0].feature_metadata["attachment_content_learning"]["extracted"] == 1
