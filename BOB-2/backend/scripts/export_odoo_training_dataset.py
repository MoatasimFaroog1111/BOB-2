"""Read-only Odoo accounting dataset export for supervised journal-entry learning."""
from __future__ import annotations

import argparse, base64, hashlib, json, mimetypes, os, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.database import SessionLocal
from app.erp.factory import get_erp_provider
from app.models.core import ERPConnection
from app.security.encryption import decrypt_value

MODELS: dict[str, tuple[str, ...]] = {
    "res.company": ("id","name","vat","country_id","currency_id","parent_id"),
    "res.currency": ("id","name","symbol","rounding","decimal_places","active"),
    "res.currency.rate": ("id","name","rate","company_rate","inverse_company_rate","currency_id","company_id"),
    "res.partner": ("id","name","display_name","vat","email","phone","mobile","company_type","is_company","customer_rank","supplier_rank","parent_id","company_id","property_account_receivable_id","property_account_payable_id","property_payment_term_id","property_supplier_payment_term_id","category_id","active"),
    "res.partner.bank": ("id","acc_number","sanitized_acc_number","partner_id","bank_id","currency_id","company_id","active"),
    "account.account": ("id","code","name","account_type","reconcile","deprecated","currency_id","company_ids","tag_ids","group_id"),
    "account.journal": ("id","code","name","type","active","company_id","currency_id","default_account_id","suspense_account_id"),
    "account.tax": ("id","name","description","amount","amount_type","type_tax_use","price_include","include_base_amount","tax_group_id","company_id","active","invoice_repartition_line_ids","refund_repartition_line_ids"),
    "account.tax.group": ("id","name","sequence","company_id"),
    "account.fiscal.position": ("id","name","company_id","tax_ids","account_ids","active","auto_apply","vat_required","country_id","country_group_id"),
    "account.payment.term": ("id","name","company_id","active","line_ids"),
    "account.analytic.plan": ("id","name","parent_id","company_id","default_applicability"),
    "account.analytic.account": ("id","name","code","partner_id","plan_id","company_id","currency_id","active"),
    "account.analytic.distribution.model": ("id","partner_id","partner_category_id","product_id","product_categ_id","account_prefix","company_id","analytic_distribution"),
    "product.category": ("id","name","parent_id","property_account_income_categ_id","property_account_expense_categ_id","property_stock_valuation_account_id"),
    "product.template": ("id","name","default_code","categ_id","type","list_price","standard_price","taxes_id","supplier_taxes_id","property_account_income_id","property_account_expense_id","company_id","active"),
    "product.product": ("id","name","display_name","default_code","product_tmpl_id","categ_id","lst_price","standard_price","barcode","company_id","active"),
    "purchase.order": ("id","name","partner_id","partner_ref","date_order","date_approve","state","currency_id","amount_untaxed","amount_tax","amount_total","company_id","invoice_status","order_line","notes"),
    "purchase.order.line": ("id","order_id","name","product_id","product_qty","product_uom","price_unit","price_subtotal","price_tax","price_total","taxes_id","analytic_distribution","date_planned","qty_invoiced","qty_received"),
    "sale.order": ("id","name","client_order_ref","partner_id","date_order","state","currency_id","amount_untaxed","amount_tax","amount_total","company_id","invoice_status","order_line","note"),
    "sale.order.line": ("id","order_id","name","product_id","product_uom_qty","product_uom","price_unit","discount","price_subtotal","price_tax","price_total","tax_id","analytic_distribution","qty_invoiced","qty_delivered"),
    "hr.expense": ("id","name","date","employee_id","product_id","total_amount","total_amount_currency","currency_id","company_id","payment_mode","state","sheet_id","account_id","analytic_distribution","tax_ids","reference"),
    "hr.expense.sheet": ("id","name","employee_id","accounting_date","state","company_id","journal_id","account_move_ids","expense_line_ids"),
    "account.asset": ("id","name","original_value","salvage_value","book_value","acquisition_date","state","method","method_number","method_period","account_asset_id","account_depreciation_id","account_depreciation_expense_id","journal_id","company_id","currency_id","partner_id","original_move_line_ids"),
    "account.payment": ("id","name","date","payment_type","partner_type","partner_id","amount","currency_id","journal_id","destination_journal_id","payment_method_line_id","memo","ref","state","company_id","move_id","partner_bank_id"),
    "account.bank.statement": ("id","name","date","balance_start","balance_end_real","balance_end","journal_id","company_id","line_ids"),
    "account.bank.statement.line": ("id","date","payment_ref","amount","foreign_currency_id","amount_currency","partner_id","account_number","transaction_type","statement_id","journal_id","company_id","move_id","sequence"),
    "account.reconcile.model": ("id","name","sequence","rule_type","auto_reconcile","to_check","matching_order","match_journal_ids","match_partner","match_partner_ids","match_label","match_label_param","match_amount","match_amount_min","match_amount_max","line_ids","company_id"),
    "account.reconcile.model.line": ("id","model_id","sequence","label","account_id","amount_type","amount","tax_ids","analytic_distribution"),
    "account.move": ("id","name","ref","date","invoice_date","invoice_date_due","move_type","state","journal_id","partner_id","commercial_partner_id","currency_id","company_id","amount_untaxed","amount_tax","amount_total","amount_residual","payment_state","invoice_origin","payment_reference","narration","invoice_user_id","invoice_payment_term_id","fiscal_position_id","line_ids","invoice_line_ids","reversed_entry_id","reversal_move_id","auto_post","create_date","write_date"),
    "account.move.line": ("id","move_id","date","name","ref","account_id","partner_id","journal_id","company_id","currency_id","debit","credit","balance","amount_currency","amount_residual","amount_residual_currency","tax_ids","tax_line_id","product_id","product_uom_id","quantity","price_unit","discount","price_subtotal","price_total","analytic_distribution","reconciled","matching_number","payment_id","statement_line_id","purchase_line_id","sale_line_ids","create_date","write_date"),
}
REQUIRED = {"res.company","account.account","account.journal","account.move","account.move.line"}


def m2o(value: Any) -> int | None:
    try:
        if isinstance(value, (list, tuple)) and value: value = value[0]
        return int(value) if value not in (None, False, "") else None
    except (TypeError, ValueError): return None


def utcnow() -> str: return datetime.now(timezone.utc).isoformat()


class Reader:
    def __init__(self, erp: Any, batch: int, company_ids: list[int]):
        self.erp, self.batch = erp, batch
        self.context = {"active_test": False}
        if company_ids: self.context["allowed_company_ids"] = company_ids
        self._fields: dict[str, set[str]] = {}

    def fields(self, model: str) -> set[str]:
        if model not in self._fields:
            meta = self.erp.execute_kw(model, "fields_get", [], {"attributes": ["type"]})
            self._fields[model] = set(meta or {})
        return self._fields[model]

    def rows(self, model: str, wanted: tuple[str, ...], domain: list | None = None):
        available = self.fields(model)
        fields = [x for x in wanted if x in available]
        if "id" not in fields: fields.insert(0, "id")
        last_id = 0
        while True:
            d = list(domain or []) + [["id", ">", last_id]]
            page = self.erp.execute_kw(model, "search_read", [d], {"fields": fields, "limit": self.batch, "order": "id asc", "context": self.context}) or []
            if not page: break
            for row in page: yield row
            new_id = max(int(x["id"]) for x in page)
            if new_id <= last_id: raise RuntimeError(f"pagination stalled for {model}")
            last_id = new_id

    def binary(self, attachment_id: int) -> str | None:
        rows = self.erp.execute_kw("ir.attachment", "read", [[attachment_id]], {"fields": ["datas"], "context": self.context}) or []
        return str(rows[0].get("datas")) if rows and rows[0].get("datas") else None


class Exporter:
    def __init__(self, erp: Any, out: Path, batch: int, company_ids: list[int], metadata_only: bool):
        self.erp, self.out, self.reader = erp, out, Reader(erp, batch, company_ids)
        self.metadata_only = metadata_only
        self.counts: dict[str, int] = {}; self.skipped: dict[str, str] = {}
        self.failures: list[dict[str, Any]] = []; self.bytes = 0; self.examples = 0
        self.db = sqlite3.connect(out / "training_index.sqlite3")
        self.db.executescript("CREATE TABLE IF NOT EXISTS moves(id INTEGER PRIMARY KEY,p TEXT);CREATE TABLE IF NOT EXISTS lines(id INTEGER PRIMARY KEY,move_id INTEGER,p TEXT);CREATE INDEX IF NOT EXISTS lines_move ON lines(move_id);CREATE TABLE IF NOT EXISTS att(id INTEGER PRIMARY KEY,res_model TEXT,res_id INTEGER,p TEXT);CREATE INDEX IF NOT EXISTS att_res ON att(res_model,res_id);")

    def jsonl(self, path: Path, rows):
        path.parent.mkdir(parents=True, exist_ok=True); n = 0
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":"))+"\n"); n += 1
        return n

    def export_models(self):
        for model, fields in MODELS.items():
            path = self.out / "records" / f"{model.replace('.', '_')}.jsonl"
            try:
                def stream():
                    for row in self.reader.rows(model, fields):
                        if model == "account.move": self.db.execute("INSERT OR REPLACE INTO moves VALUES(?,?)", (int(row["id"]), json.dumps(row, ensure_ascii=False, default=str)))
                        elif model == "account.move.line":
                            mid = m2o(row.get("move_id"))
                            if mid: self.db.execute("INSERT OR REPLACE INTO lines VALUES(?,?,?)", (int(row["id"]), mid, json.dumps(row, ensure_ascii=False, default=str)))
                        yield row
                self.counts[model] = self.jsonl(path, stream()); self.db.commit()
            except Exception as exc:
                path.unlink(missing_ok=True); msg = f"{type(exc).__name__}: {exc}"[:1000]
                if model in REQUIRED: raise RuntimeError(f"required export failed: {model}: {msg}") from exc
                self.skipped[model] = msg

    def export_attachments(self):
        fields = ("id","name","res_model","res_id","mimetype","type","url","file_size","checksum","description","company_id","public","create_uid","create_date","write_uid","write_date")
        models = list(MODELS)
        root = self.out / "attachments"; root.mkdir(parents=True, exist_ok=True)
        def stream():
            for row in self.reader.rows("ir.attachment", fields, [["res_model","in",models]]):
                meta = dict(row); meta["download"] = None
                if not self.metadata_only and str(row.get("type") or "binary") == "binary":
                    try:
                        data = self.reader.binary(int(row["id"]))
                        if data:
                            raw = base64.b64decode(data, validate=False); sha = hashlib.sha256(raw).hexdigest()
                            suffix = Path(str(row.get("name") or "")).suffix.lower() or (mimetypes.guess_extension(str(row.get("mimetype") or "")) or "")
                            suffix = suffix if len(suffix) <= 12 and re.fullmatch(r"\.[A-Za-z0-9._+-]+", suffix or "") else ""
                            stem = re.sub(r"[^A-Za-z0-9._-]+","_",Path(str(row.get("name") or "attachment")).stem)[:80] or "attachment"
                            file = root / f"{int(row['id'])}_{stem}_{sha[:12]}{suffix}"; file.write_bytes(raw)
                            meta["download"] = {"relative_path": str(file.relative_to(self.out)).replace("\\","/"), "sha256": sha, "bytes": len(raw)}; self.bytes += len(raw)
                        else: self.failures.append({"attachment_id": row.get("id"), "name": row.get("name"), "error": "empty/unavailable binary"})
                    except Exception as exc: self.failures.append({"attachment_id": row.get("id"), "name": row.get("name"), "error": f"{type(exc).__name__}: {exc}"})
                self.db.execute("INSERT OR REPLACE INTO att VALUES(?,?,?,?)", (int(row["id"]), str(row.get("res_model") or ""), m2o(row.get("res_id")), json.dumps(meta, ensure_ascii=False, default=str)))
                yield meta
        self.counts["ir.attachment"] = self.jsonl(self.out / "records" / "ir_attachment.jsonl", stream()); self.db.commit()

    def build_examples(self):
        path = self.out / "training" / "examples.jsonl"; path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for mid, payload in self.db.execute("SELECT id,p FROM moves ORDER BY id"):
                move = json.loads(payload)
                if move.get("state") != "posted": continue
                attachments = [json.loads(x[0]) for x in self.db.execute("SELECT p FROM att WHERE res_model='account.move' AND res_id=? ORDER BY id", (mid,))]
                if not attachments: continue
                lines = [json.loads(x[0]) for x in self.db.execute("SELECT p FROM lines WHERE move_id=? ORDER BY id", (mid,))]
                debit, credit, taxes, analytics = set(), set(), set(), set(); td = tc = 0.0
                for line in lines:
                    acc = m2o(line.get("account_id")); d = float(line.get("debit") or 0); c = float(line.get("credit") or 0); td += d; tc += c
                    if acc and d > 0: debit.add(acc)
                    if acc and c > 0: credit.add(acc)
                    for t in line.get("tax_ids") or []:
                        try: taxes.add(int(t[0] if isinstance(t,(list,tuple)) else t))
                        except (TypeError,ValueError): pass
                    ad = line.get("analytic_distribution") or {}
                    if isinstance(ad, dict):
                        for key in ad:
                            for part in str(key).split(","):
                                try: analytics.add(int(part.strip()))
                                except ValueError: pass
                ex = {"example_id":f"account.move:{mid}","input":{"attachments":attachments},"target":{"journal_entry":{"move":move,"lines":lines},"labels":{"debit_account_ids":sorted(debit),"credit_account_ids":sorted(credit),"tax_ids":sorted(taxes),"analytic_account_ids":sorted(analytics),"total_debit":round(td,6),"total_credit":round(tc,6),"balanced":abs(td-tc)<=1e-6}},"provenance":{"source_system":"odoo","source_model":"account.move","source_id":mid}}
                f.write(json.dumps(ex, ensure_ascii=False, default=str, separators=(",", ":"))+"\n"); self.examples += 1

    def run(self):
        self.out.mkdir(parents=True, exist_ok=True); started = utcnow(); connection = self.erp.test_connection()
        try:
            self.export_models(); self.export_attachments(); self.build_examples()
            manifest = {"schema_version":1,"started_at":started,"finished_at":utcnow(),"connection":connection,"model_counts":self.counts,"skipped_models":self.skipped,"attachment_bytes":self.bytes,"attachment_failures":self.failures,"training_examples":self.examples,"layout":{"records":"records/*.jsonl","attachments":"attachments/*","training":"training/examples.jsonl","index":"training_index.sqlite3"}}
            (self.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return manifest
        finally: self.db.commit(); self.db.close()


def provider_from_saved(org_id: int | None):
    db = SessionLocal()
    try:
        q = db.query(ERPConnection).filter(ERPConnection.is_active == True)  # noqa:E712
        if org_id is not None: q = q.filter(ERPConnection.organization_id == org_id)
        rows = [x for x in q.all() if str(x.provider or "").lower() == "odoo"]
        if not rows: raise RuntimeError("No active saved Odoo connection")
        if len(rows) > 1 and org_id is None: raise RuntimeError(f"Multiple Odoo connections; use --organization-id. IDs={sorted({x.organization_id for x in rows})}")
        c = rows[0]; sec = json.loads(decrypt_value(c.encrypted_secret_ref)); user = sec.get("username"); password = sec.get("password")
        if not user or not password: raise RuntimeError("Saved Odoo credentials are incomplete")
        return get_erp_provider(provider=c.provider, url=c.base_url, db=c.database_name or "", username=user, password=password)
    finally: db.close()


def provider_from_env():
    url=os.getenv("ODOO_URL",""); db=os.getenv("ODOO_DB",""); user=os.getenv("ODOO_USERNAME") or os.getenv("ODOO_USER") or ""; password=os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY") or ""
    if not all((url,db,user,password)): raise RuntimeError("Odoo environment variables are incomplete")
    return get_erp_provider(provider="odoo", url=url, db=db, username=user, password=password)


def main():
    p=argparse.ArgumentParser(); p.add_argument("--output",default="/data/storage/odoo-training-dataset"); p.add_argument("--batch-size",type=int,default=100); p.add_argument("--organization-id",type=int); p.add_argument("--company-id",type=int,action="append",default=[]); p.add_argument("--metadata-only",action="store_true"); a=p.parse_args()
    try: erp=provider_from_saved(a.organization_id)
    except Exception as saved:
        try: erp=provider_from_env()
        except Exception as env: raise RuntimeError(f"No usable Odoo connection. saved={saved}; env={env}") from env
    result=Exporter(erp,Path(a.output).expanduser().resolve(),a.batch_size,sorted(set(a.company_id)),a.metadata_only).run(); print(json.dumps(result,ensure_ascii=False,indent=2,default=str))

if __name__ == "__main__": main()
