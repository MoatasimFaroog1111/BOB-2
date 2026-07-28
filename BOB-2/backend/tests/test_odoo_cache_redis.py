"""Real-Redis regression tests for the tenant-scoped Odoo cache."""

from __future__ import annotations

import multiprocessing
import os
import queue as queue_module
import uuid
from typing import Any, Callable

import pytest
from redis import Redis

pytestmark = pytest.mark.skipif(
    not os.environ.get("REDIS_URL"),
    reason="A real Redis URL is required for cross-process cache tests",
)


def _configure_runtime(redis_url: str) -> None:
    os.environ["APP_ENV"] = "test"
    os.environ["REDIS_URL"] = redis_url

    from app.core.config import settings

    settings.APP_ENV = "test"
    settings.REDIS_URL = redis_url


def _write_cache(
    redis_url: str,
    organization_id: int,
    provider_url: str,
    db_name: str,
    kind: str,
    data: list[dict[str, Any]],
    result_queue,
) -> None:
    try:
        _configure_runtime(redis_url)
        from app.erp.odoo_cache import set_cached
        from app.security.tenant_scope import tenant_scope

        with tenant_scope(organization_id):
            set_cached(provider_url, db_name, kind, data)
        result_queue.put(("ok", True))
    except Exception as exc:  # pragma: no cover - surfaced to the parent process
        result_queue.put(("error", repr(exc)))
        raise


def _read_cache(
    redis_url: str,
    organization_id: int,
    provider_url: str,
    db_name: str,
    kind: str,
    result_queue,
) -> None:
    try:
        _configure_runtime(redis_url)
        from app.erp.odoo_cache import get_cached
        from app.security.tenant_scope import tenant_scope

        with tenant_scope(organization_id):
            value = get_cached(provider_url, db_name, kind)
        result_queue.put(("ok", value))
    except Exception as exc:  # pragma: no cover - surfaced to the parent process
        result_queue.put(("error", repr(exc)))
        raise


def _invalidate_cache(
    redis_url: str,
    organization_id: int,
    provider_url: str,
    db_name: str,
    result_queue,
) -> None:
    try:
        _configure_runtime(redis_url)
        from app.erp.odoo_cache import invalidate
        from app.security.tenant_scope import tenant_scope

        with tenant_scope(organization_id):
            invalidate(provider_url, db_name)
        result_queue.put(("ok", True))
    except Exception as exc:  # pragma: no cover - surfaced to the parent process
        result_queue.put(("error", repr(exc)))
        raise


def _run_in_fresh_process(
    context,
    target: Callable[..., None],
    *args: Any,
) -> Any:
    result_queue = context.Queue()
    process = context.Process(
        target=target,
        args=(*args, result_queue),
    )
    process.start()
    process.join(timeout=30)

    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        pytest.fail(f"Child process timed out: {target.__name__}")

    assert process.exitcode == 0
    try:
        status, payload = result_queue.get(timeout=5)
    except queue_module.Empty:
        pytest.fail(f"Child process returned no result: {target.__name__}")
    assert status == "ok", payload
    return payload


def _expected_key(
    organization_id: int,
    provider_url: str,
    db_name: str,
    kind: str,
) -> str:
    return (
        f"guardian:test:odoo-cache:org:{organization_id}:"
        f"org:{organization_id}|{provider_url}|{db_name}|{kind}"
    )


def test_set_in_one_process_is_readable_in_another_process():
    redis_url = os.environ["REDIS_URL"]
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    redis_client.ping()
    context = multiprocessing.get_context("spawn")

    token = uuid.uuid4().hex
    organization_id = 41001
    provider_url = f"https://odoo.example/{token}"
    db_name = f"db-{token}"
    kind = "accounts"
    data = [{"id": 101, "code": "100001", "name": "Liquidity Transfer"}]
    key = _expected_key(organization_id, provider_url, db_name, kind)

    redis_client.delete(key)
    try:
        _run_in_fresh_process(
            context,
            _write_cache,
            redis_url,
            organization_id,
            provider_url,
            db_name,
            kind,
            data,
        )
        read_value = _run_in_fresh_process(
            context,
            _read_cache,
            redis_url,
            organization_id,
            provider_url,
            db_name,
            kind,
        )

        assert read_value == data
        assert redis_client.exists(key) == 1
        ttl = redis_client.ttl(key)
        assert 0 < ttl <= 600
    finally:
        redis_client.delete(key)
        redis_client.close()


def test_invalidate_does_not_cross_tenant_boundaries():
    redis_url = os.environ["REDIS_URL"]
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    redis_client.ping()
    context = multiprocessing.get_context("spawn")

    token = uuid.uuid4().hex
    organization_a = 42001
    organization_b = 42002
    provider_url = f"https://odoo.example/{token}"
    db_name = f"db-{token}"
    kind = "journals"
    data_a = [{"id": 1, "name": "Tenant A Bank"}]
    data_b = [{"id": 2, "name": "Tenant B Bank"}]
    key_a = _expected_key(organization_a, provider_url, db_name, kind)
    key_b = _expected_key(organization_b, provider_url, db_name, kind)

    redis_client.delete(key_a, key_b)
    try:
        _run_in_fresh_process(
            context,
            _write_cache,
            redis_url,
            organization_a,
            provider_url,
            db_name,
            kind,
            data_a,
        )
        _run_in_fresh_process(
            context,
            _write_cache,
            redis_url,
            organization_b,
            provider_url,
            db_name,
            kind,
            data_b,
        )
        _run_in_fresh_process(
            context,
            _invalidate_cache,
            redis_url,
            organization_a,
            provider_url,
            db_name,
        )

        assert _run_in_fresh_process(
            context,
            _read_cache,
            redis_url,
            organization_a,
            provider_url,
            db_name,
            kind,
        ) is None
        assert _run_in_fresh_process(
            context,
            _read_cache,
            redis_url,
            organization_b,
            provider_url,
            db_name,
            kind,
        ) == data_b
        assert redis_client.exists(key_a) == 0
        assert redis_client.exists(key_b) == 1
    finally:
        redis_client.delete(key_a, key_b)
        redis_client.close()
