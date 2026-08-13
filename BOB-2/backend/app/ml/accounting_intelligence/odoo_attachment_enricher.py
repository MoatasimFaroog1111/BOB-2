"""Optional, bounded enrichment of historical examples with ERP attachment text."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.ml.accounting_intelligence.attachment_features import GuardedERPAttachmentFeatureExtractor
from app.ml.accounting_intelligence.contracts import HistoricalAccountingExample

_SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv"}


class OdooAttachmentLearningEnricher:
    """Read a bounded number of historical attachment binaries for guarded OCR/text features."""

    def __init__(
        self,
        erp: Any,
        *,
        extractor: GuardedERPAttachmentFeatureExtractor | None = None,
    ):
        self.erp = erp
        self.extractor = extractor or GuardedERPAttachmentFeatureExtractor()

    @staticmethod
    def _res_id(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def enrich(
        self,
        examples: list[HistoricalAccountingExample],
        *,
        max_attachments: int = 100,
        max_attachments_per_move: int = 3,
    ) -> tuple[list[HistoricalAccountingExample], dict[str, int]]:
        if not examples or max_attachments <= 0:
            return examples, {"requested": 0, "extracted": 0, "rejected": 0, "skipped": 0, "failed": 0}

        global_limit = min(max(int(max_attachments), 1), 500)
        per_move_limit = min(max(int(max_attachments_per_move), 1), 5)
        move_ids = [example.source_id for example in examples]
        try:
            metadata_rows = list(
                self.erp.execute_kw(
                    "ir.attachment",
                    "search_read",
                    [[
                        ["res_model", "=", "account.move"],
                        ["res_id", "in", move_ids],
                        ["type", "=", "binary"],
                    ]],
                    {
                        "fields": ["id", "name", "res_id", "mimetype", "file_size", "type"],
                        "order": "res_id asc, id asc",
                        "limit": min(global_limit * 4, 2000),
                    },
                )
                or []
            )
        except Exception:
            return examples, {"requested": 0, "extracted": 0, "rejected": 0, "skipped": 0, "failed": 0}

        max_bytes = int(settings.MAX_UPLOAD_SIZE_MB) * 1024 * 1024
        candidates_by_move: dict[int, list[dict[str, Any]]] = defaultdict(list)
        skipped_metadata = 0
        for row in metadata_rows:
            move_id = self._res_id(row.get("res_id"))
            if not move_id or len(candidates_by_move[move_id]) >= per_move_limit:
                continue
            extension = Path(str(row.get("name") or "")).suffix.lower()
            try:
                file_size = int(row.get("file_size") or 0)
            except (TypeError, ValueError):
                file_size = 0
            if extension not in _SUPPORTED_EXTENSIONS or (file_size and file_size > max_bytes):
                skipped_metadata += 1
                continue
            candidates_by_move[move_id].append(row)

        selected: list[tuple[int, dict[str, Any]]] = []
        # Round-robin by move prevents one invoice with many attachments from consuming the batch.
        depth = 0
        while len(selected) < global_limit:
            added = False
            for move_id in move_ids:
                rows = candidates_by_move.get(move_id, [])
                if depth < len(rows):
                    selected.append((move_id, rows[depth]))
                    added = True
                    if len(selected) >= global_limit:
                        break
            if not added:
                break
            depth += 1

        text_by_move: dict[int, list[str]] = defaultdict(list)
        status_by_move: dict[int, Counter] = defaultdict(Counter)
        global_status: Counter = Counter()
        for move_id, metadata in selected:
            attachment_id = int(metadata.get("id") or 0)
            try:
                rows = self.erp.execute_kw(
                    "ir.attachment",
                    "read",
                    [[attachment_id]],
                    {"fields": ["id", "name", "mimetype", "datas"]},
                )
                payload = dict(rows[0]) if rows else dict(metadata)
            except Exception:
                status_by_move[move_id]["failed"] += 1
                global_status["failed"] += 1
                continue

            result = self.extractor.extract(payload)
            status_by_move[move_id][result.status] += 1
            if result.status == "extracted" and result.text:
                text_by_move[move_id].append(
                    f"attachment_content {result.filename} {result.text}"
                )
                global_status["extracted"] += 1
            elif result.status == "rejected":
                global_status["rejected"] += 1
            elif result.status.startswith("skipped") or result.status == "no_text":
                global_status["skipped"] += 1
            else:
                global_status["failed"] += 1

        enriched: list[HistoricalAccountingExample] = []
        for example in examples:
            content_features = text_by_move.get(example.source_id, [])
            statuses = status_by_move.get(example.source_id, Counter())
            metadata = dict(example.feature_metadata or {})
            if statuses:
                metadata["attachment_content_learning"] = dict(statuses)
            enriched.append(
                replace(
                    example,
                    attachment_features=tuple(list(example.attachment_features) + content_features),
                    feature_metadata=metadata,
                )
            )

        return enriched, {
            "requested": len(selected),
            "extracted": int(global_status["extracted"]),
            "rejected": int(global_status["rejected"]),
            "skipped": int(global_status["skipped"] + skipped_metadata),
            "failed": int(global_status["failed"]),
        }
