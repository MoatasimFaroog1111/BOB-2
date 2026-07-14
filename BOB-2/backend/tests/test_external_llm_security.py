"""Regression tests for tenant-scoped external LLM disclosure controls."""

from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.config import settings
from app.models.core import AuditLog, Organization, User
from app.models.external_llm import ExternalLLMPolicy
from app.security.auth import hash_password
from app.services import external_llm_gateway as gateway_module
from app.services.external_llm_gateway import (
    ExternalLLMAuditError,
    ExternalLLMGateway,
    ExternalLLMPolicyDenied,
    ExternalLLMProviderError,
    ExternalLLMRequestContext,
    _bounded_response_json,
    _validate_external_endpoint,
    sanitize_external_payload,
)


def _seed_actor(db, *, organization_id: int = 1, user_id: int = 1):
    organization = Organization(
        id=organization_id,
        name=f"Organization {organization_id}",
        legal_name=f"Organization {organization_id}",
        country="SA",
        is_active=True,
    )
    user = User(
        id=user_id,
        organization_id=organization_id,
        email=f"owner{user_id}@example.test",
        full_name=f"Owner {user_id}",
        role="owner",
        hashed_password=hash_password("Test@Pass1234!"),
        is_active=True,
    )
    db.add_all([organization, user])
    db.commit()
    return organization, user


def _enable_global(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", True)
    monkeypatch.setattr(settings, "EXTERNAL_LLM_REQUIRED_DPA_VERSION", "2026-07-v1")
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_PROVIDERS", "deepseek")
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_MODELS", "deepseek:deepseek-chat")
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_HOSTS", "api.deepseek.com")
    monkeypatch.setattr(settings, "EXTERNAL_LLM_MAX_REQUEST_BYTES", 262_144)
    monkeypatch.setattr(settings, "EXTERNAL_LLM_MAX_RESPONSE_BYTES", 1_048_576)
    monkeypatch.setattr(settings, "EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS", 4_000)


def _create_policy(
    db,
    *,
    organization_id: int = 1,
    user_id: int = 1,
    enabled: bool = True,
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    purposes: list[str] | None = None,
    allow_text: bool = False,
    allow_financial_values: bool = False,
    max_text_chars: int = 0,
    dpa_version: str = "2026-07-v1",
    dpa_reference: str | None = "DPA-TEST-001",
    region: str | None = "KSA",
    retention: str | None = "contractual_zero_retention",
    revoked_at: datetime | None = None,
):
    policy = ExternalLLMPolicy(
        organization_id=organization_id,
        external_llm_enabled=enabled,
        approved_provider=provider,
        approved_model=model,
        allowed_purposes=purposes or ["accounting_reasoning"],
        allow_redacted_document_text=allow_text,
        allow_financial_values=allow_financial_values,
        max_redacted_text_chars=max_text_chars,
        dpa_version=dpa_version,
        dpa_reference=dpa_reference,
        data_residency_region=region,
        provider_retention_mode=retention,
        accepted_by_user_id=user_id,
        accepted_at=datetime.utcnow(),
        revoked_at=revoked_at,
        policy_version=1,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def _context(
    *,
    organization_id: int = 1,
    user_id: int = 1,
    purpose: str = "accounting_reasoning",
    request_id: str = "request-test-1",
):
    return ExternalLLMRequestContext(
        organization_id=organization_id,
        user_id=user_id,
        purpose=purpose,
        source_type="invoice",
        request_id=request_id,
    )


def _success_response(content: str = '{"summary":"ok","confidence_score":0.9}'):
    return {"choices": [{"message": {"content": content}}]}


def test_legacy_llm_service_contains_no_external_provider_or_fallback():
    source = Path("app/services/llm_service.py").read_text(encoding="utf-8")
    forbidden = (
        "DeepSeek",
        "DEEPSEEK_API_URL",
        "_call_deepseek",
        "api.deepseek.com",
        "falls back",
    )
    assert not [item for item in forbidden if item in source]
    assert "LOCAL_LLM_ENABLED" in source
    assert "address.is_loopback" in source
    assert "There is deliberately no external-provider fallback" in source


def test_local_llm_disabled_never_attempts_network(monkeypatch):
    from app.services import llm_service

    monkeypatch.setattr(settings, "LOCAL_LLM_ENABLED", False)
    monkeypatch.setattr(
        llm_service,
        "_call_local_ollama",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )
    assert llm_service.chat("system", "user") is None


def test_api_key_is_not_consent_when_global_switch_is_off(db, monkeypatch):
    _seed_actor(db)
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", False)
    _create_policy(db)
    sent = []
    gateway = ExternalLLMGateway(
        db=db,
        context=_context(),
        provider="deepseek",
        model="deepseek-chat",
        api_key="configured-key",
        transport=lambda *_args: sent.append(True) or _success_response(),
    )
    with pytest.raises(ExternalLLMPolicyDenied) as exc:
        gateway.execute_chat_completion(system_prompt="system", structured_payload={"summary": "safe"})
    assert exc.value.reason == "external_llm_global_kill_switch"
    assert sent == []
    audit = db.query(AuditLog).filter(AuditLog.action == "external_llm_disclosure_blocked").one()
    assert audit.details["reason"] == "external_llm_global_kill_switch"


@pytest.mark.parametrize(
    ("policy_kwargs", "purpose", "expected_reason"),
    [
        ({"enabled": False}, "accounting_reasoning", "external_llm_tenant_not_enabled"),
        ({"dpa_version": "old"}, "accounting_reasoning", "external_llm_dpa_not_current"),
        ({"dpa_reference": None}, "accounting_reasoning", "external_llm_dpa_not_current"),
        ({"region": None}, "accounting_reasoning", "external_llm_dpa_not_current"),
        ({"retention": None}, "accounting_reasoning", "external_llm_dpa_not_current"),
        ({"revoked_at": datetime.utcnow()}, "accounting_reasoning", "external_llm_dpa_not_current"),
        ({"provider": "openai"}, "accounting_reasoning", "external_llm_provider_not_approved"),
        ({"model": "other-model"}, "accounting_reasoning", "external_llm_model_not_approved"),
        ({"purposes": ["accounting_reasoning"]}, "natural_language_intent", "external_llm_purpose_not_approved"),
    ],
)
def test_policy_dpa_provider_model_and_purpose_fail_closed(
    db, monkeypatch, policy_kwargs, purpose, expected_reason
):
    _seed_actor(db)
    _enable_global(monkeypatch)
    _create_policy(db, **policy_kwargs)
    gateway = ExternalLLMGateway(
        db=db,
        context=_context(purpose=purpose),
        provider="deepseek",
        model="deepseek-chat",
        api_key="configured-key",
        transport=lambda *_args: _success_response(),
    )
    with pytest.raises(ExternalLLMPolicyDenied) as exc:
        gateway.execute_chat_completion(system_prompt="system", structured_payload={"summary": "safe"})
    assert exc.value.reason == expected_reason


def test_missing_tenant_policy_fails_closed_and_is_audited(db, monkeypatch):
    _seed_actor(db)
    _enable_global(monkeypatch)
    gateway = ExternalLLMGateway(
        db=db,
        context=_context(),
        provider="deepseek",
        model="deepseek-chat",
        api_key="configured-key",
        transport=lambda *_args: _success_response(),
    )
    with pytest.raises(ExternalLLMPolicyDenied) as exc:
        gateway.execute_chat_completion(system_prompt="system", structured_payload={})
    assert exc.value.reason == "external_llm_tenant_not_enabled"
    assert db.query(AuditLog).filter(AuditLog.action == "external_llm_disclosure_blocked").count() == 1


def test_inactive_or_cross_tenant_actor_is_blocked(db, monkeypatch):
    organization, user = _seed_actor(db)
    _enable_global(monkeypatch)
    _create_policy(db)
    user.organization_id = None
    db.commit()
    gateway = ExternalLLMGateway(
        db=db,
        context=_context(),
        provider="deepseek",
        model="deepseek-chat",
        api_key="configured-key",
        transport=lambda *_args: _success_response(),
    )
    with pytest.raises(ExternalLLMPolicyDenied) as exc:
        gateway.execute_chat_completion(system_prompt="system", structured_payload={})
    assert exc.value.reason == "external_llm_user_invalid"

    user.organization_id = organization.id
    user.is_active = False
    db.commit()
    with pytest.raises(ExternalLLMPolicyDenied) as inactive:
        gateway.execute_chat_completion(system_prompt="system", structured_payload={})
    assert inactive.value.reason == "external_llm_user_invalid"


def test_sanitizer_omits_raw_text_and_redacts_structured_sensitive_fields(db, monkeypatch):
    _seed_actor(db)
    policy = _create_policy(db, allow_text=False, allow_financial_values=False)
    sanitized = sanitize_external_payload(
        structured_payload={
            "partner_name": "Guardian Supplier LLC",
            "email": "finance@example.com",
            "iban": "SA4320000003302122299940",
            "vat_number": "300514273800003",
            "invoice_number": "INV-2026-00001",
            "amount_total": "64083.75",
            "nested": {"phone": "+966501234567", "summary": "ordinary text"},
        },
        raw_document_text="Supplier: Guardian Supplier LLC SAR 64083.75",
        policy=policy,
    )
    serialized = json.dumps(sanitized.payload, ensure_ascii=False)
    for forbidden in (
        "Guardian Supplier",
        "finance@example.com",
        "SA4320000003302122299940",
        "300514273800003",
        "INV-2026-00001",
        "64083.75",
        "+966501234567",
    ):
        assert forbidden not in serialized
    assert "redacted_document_text" not in sanitized.payload
    assert sanitized.redaction_counts["raw_document_text_omitted"] == 1
    assert len(sanitized.payload_hash) == 64


def test_optional_redacted_text_removes_party_identifiers_references_and_financial_values(db, monkeypatch):
    _seed_actor(db)
    monkeypatch.setattr(settings, "EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS", 300)
    policy = _create_policy(
        db,
        allow_text=True,
        allow_financial_values=False,
        max_text_chars=300,
    )
    raw = (
        "Supplier: Guardian Technical Contracting Company\n"
        "Address: Al Khobar, Saudi Arabia\n"
        "Email finance@example.com Phone +966501234567\n"
        "IBAN SA43 2000 0003 3021 2229 9940 VAT 300514273800003\n"
        "Invoice INV-2026-00001 Total SAR 64,083.75"
    )
    sanitized = sanitize_external_payload(
        structured_payload={"document_type": "invoice"},
        raw_document_text=raw,
        policy=policy,
    )
    disclosed = sanitized.payload["redacted_document_text"]
    for forbidden in (
        "Guardian Technical",
        "Al Khobar",
        "finance@example.com",
        "+966501234567",
        "SA43 2000",
        "300514273800003",
        "INV-2026-00001",
        "64,083.75",
    ):
        assert forbidden not in disclosed
    assert len(disclosed) <= 300


def test_sanitized_payload_hash_is_stable(db):
    _seed_actor(db)
    policy = _create_policy(db)
    one = sanitize_external_payload(
        structured_payload={"b": 2, "a": 1},
        raw_document_text="",
        policy=policy,
    )
    two = sanitize_external_payload(
        structured_payload={"a": 1, "b": 2},
        raw_document_text="",
        policy=policy,
    )
    assert one.payload_hash == two.payload_hash


def test_successful_gateway_sends_only_sanitized_content_and_records_started_and_success(
    db, monkeypatch
):
    _seed_actor(db)
    _enable_global(monkeypatch)
    _create_policy(db, allow_text=False, allow_financial_values=False)
    captured: dict[str, Any] = {}

    def transport(url, payload, api_key):
        captured.update({"url": url, "payload": payload, "api_key": api_key})
        return _success_response()

    gateway = ExternalLLMGateway(
        db=db,
        context=_context(),
        provider="deepseek",
        model="deepseek-chat",
        api_key="configured-key",
        transport=transport,
    )
    response = gateway.execute_chat_completion(
        system_prompt="Return JSON only.",
        structured_payload={
            "partner_name": "Secret Supplier",
            "amount_total": "9999.99",
            "email": "secret@example.com",
            "summary": "Review invoice",
        },
        raw_document_text="Secret Supplier secret@example.com SAR 9999.99",
    )
    assert response["choices"]
    sent = json.dumps(captured["payload"], ensure_ascii=False)
    assert "Secret Supplier" not in sent
    assert "secret@example.com" not in sent
    assert "9999.99" not in sent
    assert captured["api_key"] == "configured-key"

    events = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "external_llm")
        .order_by(AuditLog.id.asc())
        .all()
    )
    assert [event.action for event in events] == [
        "external_llm_disclosure_started",
        "external_llm_disclosure_succeeded",
    ]
    audit_json = json.dumps([event.details for event in events], ensure_ascii=False)
    for forbidden in ("Secret Supplier", "secret@example.com", "9999.99", "Return JSON only"):
        assert forbidden not in audit_json
    assert events[0].details["payload_hash"]
    assert events[0].details["redaction_counts"]


def test_provider_failure_records_started_and_failed_without_raw_provider_body(db, monkeypatch):
    _seed_actor(db)
    _enable_global(monkeypatch)
    _create_policy(db)

    def failing_transport(*_args):
        raise RuntimeError("provider leaked body: confidential-content")

    gateway = ExternalLLMGateway(
        db=db,
        context=_context(),
        provider="deepseek",
        model="deepseek-chat",
        api_key="configured-key",
        transport=failing_transport,
    )
    with pytest.raises(ExternalLLMProviderError):
        gateway.execute_chat_completion(system_prompt="system", structured_payload={"summary": "safe"})
    events = db.query(AuditLog).filter(AuditLog.entity_type == "external_llm").order_by(AuditLog.id).all()
    assert [event.action for event in events] == [
        "external_llm_disclosure_started",
        "external_llm_disclosure_failed",
    ]
    assert "confidential-content" not in json.dumps([event.details for event in events])


def test_audit_failure_before_send_prevents_transport(db, monkeypatch):
    _seed_actor(db)
    _enable_global(monkeypatch)
    _create_policy(db)
    sent: list[bool] = []
    original = gateway_module.record_external_llm_event

    def fail_started(db_session, *, context, action, details):
        if action == "external_llm_disclosure_started":
            raise ExternalLLMAuditError("audit unavailable")
        return original(db_session, context=context, action=action, details=details)

    monkeypatch.setattr(gateway_module, "record_external_llm_event", fail_started)
    gateway = ExternalLLMGateway(
        db=db,
        context=_context(),
        provider="deepseek",
        model="deepseek-chat",
        api_key="configured-key",
        transport=lambda *_args: sent.append(True) or _success_response(),
    )
    with pytest.raises(ExternalLLMAuditError):
        gateway.execute_chat_completion(system_prompt="system", structured_payload={"summary": "safe"})
    assert sent == []


@pytest.mark.parametrize(
    "url",
    [
        "http://api.deepseek.com/chat/completions",
        "https://evil.example/chat/completions",
        "https://user:password@api.deepseek.com/chat/completions",
        "https://api.deepseek.com:8443/chat/completions",
        "https://api.deepseek.com/chat/completions?redirect=x",
        "https://api.deepseek.com/v1/models",
        "https://api.deepseek.com/../chat/completions",
    ],
)
def test_external_endpoint_rejects_unapproved_url_forms(monkeypatch, url):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_HOSTS", "api.deepseek.com")
    with pytest.raises(ExternalLLMProviderError):
        _validate_external_endpoint(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "10.0.0.5", "169.254.169.254"])
def test_external_endpoint_rejects_private_loopback_and_metadata_dns(monkeypatch, address):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_HOSTS", "api.deepseek.com")

    def resolver(_host, port, _family, _socktype):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
        return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    with pytest.raises(ExternalLLMProviderError):
        _validate_external_endpoint("https://api.deepseek.com/chat/completions")


def test_external_endpoint_accepts_exact_https_host_with_public_dns(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_HOSTS", "api.deepseek.com")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port, _family, _socktype: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))
        ],
    )
    endpoint = _validate_external_endpoint("https://api.deepseek.com/chat/completions")
    assert endpoint.hostname == "api.deepseek.com"
    assert endpoint.resolved_ips == ("8.8.8.8",)


class _FakeResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None, status: int = 200):
        self.chunks = list(chunks)
        self.headers = headers or {}
        self.status = status
        self.closed = False

    def getheader(self, name: str, default=None):
        return self.headers.get(name, default)

    def read(self, _size: int):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


def test_external_response_declared_and_streamed_size_are_bounded(monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_MAX_RESPONSE_BYTES", 5)
    declared = _FakeResponse([], {"Content-Length": "6"})
    with pytest.raises(ExternalLLMProviderError) as declared_error:
        _bounded_response_json(declared)
    assert declared_error.value.reason == "external_llm_response_too_large"
    assert declared.closed is True

    streamed = _FakeResponse([b"1234", b"56"])
    with pytest.raises(ExternalLLMProviderError) as stream_error:
        _bounded_response_json(streamed)
    assert stream_error.value.reason == "external_llm_response_too_large"
    assert streamed.closed is True


def test_policy_admin_requires_current_dpa_and_never_returns_api_key(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", False)
    monkeypatch.setattr(settings, "ACCOUNTING_LLM_API_KEY", "super-secret-key")
    get_response = client.get("/api/v1/llm/policy", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json()["policy"] is None
    assert get_response.json()["api_key_configured"] is True
    assert "super-secret-key" not in get_response.text

    no_accept = client.put(
        "/api/v1/llm/policy",
        headers=auth_headers,
        json={
            "external_llm_enabled": True,
            "approved_provider": "deepseek",
            "approved_model": "deepseek-chat",
            "allowed_purposes": ["accounting_reasoning"],
            "allow_redacted_document_text": False,
            "allow_financial_values": False,
            "max_redacted_text_chars": 0,
            "dpa_version": "2026-07-v1",
            "dpa_reference": "DPA-LEGAL-001",
            "data_residency_region": "KSA",
            "provider_retention_mode": "contractual_zero_retention",
            "accept_dpa": False,
        },
    )
    assert no_accept.status_code == 400

    accepted_payload = no_accept.request.content
    accepted_json = json.loads(accepted_payload.decode("utf-8"))
    accepted_json["accept_dpa"] = True
    accepted = client.put("/api/v1/llm/policy", headers=auth_headers, json=accepted_json)
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["policy"]["external_llm_enabled"] is True
    assert body["effective_enabled"] is False
    assert body["policy"]["accepted_by_user_id"] == 1
    assert "super-secret-key" not in accepted.text


def test_policy_admin_is_tenant_scoped_and_disclosure_list_excludes_other_tenant(
    client, auth_headers, db
):
    second_org, second_user = _seed_actor(db, organization_id=2, user_id=2)
    db.add(
        ExternalLLMPolicy(
            organization_id=second_org.id,
            external_llm_enabled=True,
            approved_provider="deepseek",
            approved_model="deepseek-chat",
            allowed_purposes=["accounting_reasoning"],
            allow_redacted_document_text=False,
            allow_financial_values=False,
            max_redacted_text_chars=0,
            dpa_version="2026-07-v1",
            dpa_reference="OTHER-DPA",
            data_residency_region="KSA",
            provider_retention_mode="contractual_zero_retention",
            accepted_by_user_id=second_user.id,
            accepted_at=datetime.utcnow(),
            policy_version=1,
        )
    )
    db.add_all(
        [
            AuditLog(
                organization_id=1,
                user_id=1,
                action="external_llm_disclosure_blocked",
                entity_type="external_llm",
                entity_id="org1-request",
                details={"reason": "test"},
            ),
            AuditLog(
                organization_id=2,
                user_id=2,
                action="external_llm_disclosure_succeeded",
                entity_type="external_llm",
                entity_id="org2-secret-request",
                details={"payload_hash": "other"},
            ),
        ]
    )
    db.commit()

    policy = client.get("/api/v1/llm/policy", headers=auth_headers)
    assert policy.status_code == 200
    assert policy.json()["organization_id"] == 1
    assert policy.json()["policy"] is None

    disclosures = client.get("/api/v1/llm/disclosures", headers=auth_headers)
    assert disclosures.status_code == 200
    assert [row["request_id"] for row in disclosures.json()] == ["org1-request"]
    assert "org2-secret-request" not in disclosures.text


def test_agents_endpoint_uses_authenticated_tenant_and_blocks_external_by_default(
    client, auth_headers, db, monkeypatch
):
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", False)
    text = (
        "Tax Invoice INV/2026/0002 Supplier: Guardian Technical Contracting Company "
        "Date: 2026-07-04 Subtotal SAR 1000 VAT SAR 150 Total SAR 1150"
    )
    response = client.post(
        "/api/v1/agents/run-accounting-workflow",
        json={"text": text, "source_type": "invoice", "organization_id": 1, "language": "auto"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organization_id"] == 1
    assert body["llm_reasoning"]["status"] == "blocked_by_policy"
    assert body["final_recommendation"]["auto_posted_to_erp"] is False
    assert (
        db.query(AuditLog)
        .filter(AuditLog.action == "external_llm_disclosure_blocked")
        .count()
        == 1
    )

    mismatch = client.post(
        "/api/v1/agents/run-accounting-workflow",
        json={"text": text, "source_type": "invoice", "organization_id": 2},
        headers=auth_headers,
    )
    assert mismatch.status_code == 403


def test_accounting_reasoner_has_no_direct_http_client():
    source = Path("app/services/llm_accounting_reasoner.py").read_text(encoding="utf-8")
    assert "urllib.request" not in source
    assert "ExternalLLMGateway" in source
    assert "raw_document_text=text" in source
    assert "db_session" in source
