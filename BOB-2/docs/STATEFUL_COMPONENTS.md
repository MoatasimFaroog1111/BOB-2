# Stateful Components Inventory

**Task:** T1 — inventory process-local state before multi-replica work  
**Scope:** `BOB-2/backend/app`  
**Baseline:** `main` at the time this branch was created  
**Status:** documentation only; no runtime behavior is changed by this task

## Inventory method

The inventory is based on the mandatory search:

```bash
grep -rn "threading\.\|ContextVar\|_store\|defaultdict\|BoundedSemaphore" BOB-2/backend/app
```

Each meaningful match is classified as one of:

- `must-move-to-redis`: correctness, coordination, abuse control, or operational state must be shared across replicas.
- `safe-per-process`: deliberately local implementation state that does not represent durable or cross-replica business state.
- `delete`: compatibility or web-process state that should disappear when the owning workload is moved to the worker.

The `_store` alternative also matches lexical references such as module names (`secret_store`), configuration names, imports, and helper names. Those references do not themselves hold state. They are covered under **Lexical-only `_store` matches** below; the actual state owned by the secret-store implementation is inventoried separately.

## Summary

| Domain | Current process-local state | Classification | Planned owner |
|---|---|---|---|
| Odoo cache | module dictionary and lock | `must-move-to-redis` | T3 Redis cache |
| Authentication rate limiting | development fallback dictionaries; per-module Redis client | `safe-per-process` for non-production fallback; shared client refactor required | T2 shared Redis client |
| Telegram ingestion | queue, worker threads, counters, rate buckets, stop state | `must-move-to-redis` / `delete` | T4/T6 worker and Redis |
| Telegram bot facade | polling thread, stop event, compatibility pending map | `delete` | T6 worker-only runtime and durable approvals |
| Telegram runtime guard | emergency flag, status text, monkey-patch lifecycle | mixed: shared controls must move; web lifecycle state must be deleted | T6/T7 worker controls and heartbeat |
| Tenant scope | `ContextVar` carrying the active organization | `safe-per-process` | request/task context; workers must set it explicitly |
| OCR guard | installed flag and bounded semaphore | `safe-per-process` | per-worker resource guard |
| Secret store | memory-provider values and provider singleton | `safe-per-process` only outside production | development/test provider; production remains durable/remote |
| Vector embedding adapter | provider singleton and circuit-breaker flag | `safe-per-process` | per-process model/cache state |
| Historical reconciliation suggestions | function-local `defaultdict` | `safe-per-process` | request-local temporary grouping |

## Detailed findings

### 1. `app/erp/odoo_cache.py`

**Matches:** `threading.Lock`, `_store`.

Current state:

- `_store` contains tenant-scoped Odoo data for up to 600 seconds.
- `_lock` protects the dictionary only inside one Python process.
- Cache invalidation scans only the local dictionary.

**Classification:** `must-move-to-redis`.

**Reason:** two web replicas can return different cached values, and invalidation on one replica does not invalidate another. This is cross-request and cross-replica application data.

**Required follow-up:** T3 must preserve the existing tenant key material, use Redis expiry, and use `SCAN` rather than `KEYS` for invalidation.

---

### 2. `app/security/rate_limiter.py`

**Matches:** `defaultdict`; the module also owns dictionaries and a Redis connection handle.

Current state:

- `_attempts` is a process-local `defaultdict(list)`.
- `_lockouts` is a process-local dictionary.
- `_redis` is a connection created directly by this module.

**Classification:**

- `_attempts` and `_lockouts`: `safe-per-process` **only as the existing non-production fallback**. They must never become the production source of truth.
- `_redis` connection/pool handle: `safe-per-process`, but its construction must be centralized by T2.

**Reason:** production already fails closed when Redis is unavailable. The local dictionaries are intentionally a development fallback, not acceptable distributed abuse-control state.

**Required follow-up:** T2 must route this module through the shared Redis client and ensure there is no `Redis.from_url` outside `app/core/redis_client.py`.

---

### 3. `app/services/telegram_ingestion.py`

**Matches:** `threading` and multiple process-local collections.

Current state in `BoundedTelegramIngestionQueue`:

- `_queue`: bounded `queue.Queue`.
- `_lock`: process-local `RLock`.
- `_stop_event`: process-local event.
- `_workers`: daemon worker threads.
- `_pending_by_actor`: process-local counter.
- `_pending_by_organization`: process-local counter.
- `_attempts_by_actor`: process-local rate-window deques.
- `_global_queue` and `_queue_lock`: module singleton and lifecycle lock.

**Classification:**

- Queue payloads, actor/organization pending counts, and upload-rate buckets: `must-move-to-redis` through the background-task/Telegram design.
- In-web worker threads, `_global_queue`, `_queue_lock`, and web-owned stop lifecycle: `delete` from the web process.

**Reason:** every replica can create its own queue and workers, independently enforce limits, and potentially process the same Telegram update. These values affect correctness and abuse control across replicas.

**Required follow-up:** T4 provides the Redis-backed worker system; T6 moves Telegram ingestion to the worker, adds a Redis leadership lock, and converts distributed limits to Redis counters.

---

### 4. `app/services/telegram_bot.py`

**Matches:** `threading` and `_store` lexical references through `secret_store` imports.

Current state:

- `PENDING_ENTRIES`: process-local compatibility map.
- `pending_entries_lock`: process-local lock.
- `bot_thread`: polling thread reference.
- `stop_event`: polling stop signal.

**Classification:** `delete`.

**Reason:** durable approval rows are already documented in the code as authoritative. The compatibility map must not be used for distributed correctness. Polling and its thread lifecycle must no longer belong to a web replica.

**Required follow-up:** T6 removes bot start/stop from the web lifespan and runs one receiver under worker leadership.

---

### 5. `app/services/telegram_runtime.py`

**Matches:** `threading.RLock` and `threading.Event`.

Current state:

- `_runtime_lock`: protects installation/start/stop only within one process.
- `_emergency_disabled`: process-local emergency flag.
- `_installed`, `_original_start`, `_original_stop`: monkey-patch lifecycle state.
- `_last_reason`: process-local operational status.

**Classification:**

- `_emergency_disabled`: `must-move-to-redis` or another durable shared control so disabling applies to every replica and worker.
- `_last_reason`: `delete` and replace with worker-owned status/heartbeat consumed by readiness.
- `_runtime_lock`, `_installed`, `_original_start`, `_original_stop`: `delete` from the web process when the compatibility guard is removed; any remaining worker-local installation lock is `safe-per-process`.

**Reason:** an emergency control and runtime status cannot be replica-specific. Monkey-patching a web-owned polling lifecycle is no longer needed after T6.

**Required follow-up:** T6 owns receiver leadership and lifecycle; T7 exposes worker heartbeat/readiness.

---

### 6. `app/security/tenant_scope.py`

**Match:** `ContextVar`.

Current state:

- `_current_organization_id` carries the authenticated organization inside one execution context and is reset by the context manager.

**Classification:** `safe-per-process`.

**Reason:** this is request/task context, not durable business state. `ContextVar` isolation is appropriate for concurrent requests. It must not be assumed to propagate to a separately executed background job.

**Required follow-up:** every T4 worker task must receive `organization_id` explicitly and open `tenant_scope(organization_id)` before tenant-scoped work.

---

### 7. `app/security/dependencies.py`

**Match:** the word `ContextVar` appears in documentation describing FastAPI context propagation.

**Classification:** no owned state; justified non-state match.

**Reason:** the file does not define a `ContextVar`. It binds and resets the tenant scope through `tenant_scope()` for the lifetime of a financial request.

---

### 8. `app/security/ocr_guard.py`

**Matches:** `threading`, `BoundedSemaphore`.

Current state:

- `_installed` prevents repeated monkey-patching in one process.
- `_semaphore` caps concurrent Tesseract subprocesses to two per process.

**Classification:** `safe-per-process`.

**Reason:** these values protect local process resources and do not represent tenant, job, or business state. A worker replica may safely maintain its own OCR concurrency guard. Global capacity should be controlled by worker concurrency/deployment sizing, not by sharing this semaphore.

**Required follow-up:** retain the timeout and guard when OCR moves to T4/T5 workers; do not weaken fail-closed validation.

---

### 9. `app/services/secret_store.py`

**Matches:** `threading`; many `_store` matches are identifiers/imports related to the secret-store domain.

Current state:

- `_MEMORY_VALUES`: in-memory secret values used by `MemorySecretProvider`.
- `_MEMORY_LOCK`: protects memory-provider values.
- `_PROVIDER`: lazily initialized provider singleton.
- `_PROVIDER_LOCK`: protects provider initialization/reset.

**Classification:**

- `_MEMORY_VALUES` and `_MEMORY_LOCK`: `safe-per-process` **only because the memory provider is explicitly forbidden in production**; intended for local development/tests.
- `_PROVIDER` and `_PROVIDER_LOCK`: `safe-per-process`; they cache a provider client/object, not tenant secret data in production.

**Reason:** production secrets are held by the configured durable provider. Turning the memory provider into shared Redis storage would weaken the current security model and is not required for stateless production replicas.

**Required follow-up:** none for T2/T3. Keep the production prohibition and existing runtime security checks unchanged.

---

### 10. `app/services/vector_db.py`

**Explicit T1 scope file; state is not selected by the mandatory grep alternatives.**

Current state:

- `_embedding_provider`: lazily initialized process-local provider/model object.
- `_embedding_unavailable`: process-local circuit-breaker flag.

**Classification:** `safe-per-process`.

**Reason:** model/client initialization and a local availability circuit breaker are cache/health state, not durable vector data. Vector records themselves are already persisted in the database. Different replicas may temporarily have different breaker states without crossing tenant boundaries or losing records.

**Required follow-up:** T8 changes database similarity execution to pgvector; T9 makes the active provider observable. A distributed breaker can be considered later only if operational evidence shows it is needed.

---

### 11. `app/api/v1/bank_reconciliation_entry_suggestions.py`

**Match:** `defaultdict`.

Current state:

- `by_move = defaultdict(list)` is created inside `_fetch_historical_bank_entries()` and discarded when the request finishes.

**Classification:** `safe-per-process`.

**Reason:** it is function-local temporary grouping, does not survive the request, and is not shared mutable module state.

---

## Lexical-only `_store` matches

The mandatory grep pattern `_store` also returns references that do not own a long-lived store, including:

- imports and calls involving `app.services.secret_store`;
- configuration fields and validation names containing `SECRET_STORE` / `secret_store`;
- provider implementation names such as `azure_secret_provider` and `encrypted_secret_provider`;
- API/service code that calls the secret-store interface;
- comments, audit action names, and error codes containing `secret_store`.

These matches are not independent state holders. Their state ownership resolves to `app/services/secret_store.py` and its configured provider, which is classified above. No caller should be migrated to Redis merely because its identifier contains `_store`.

## Decisions that gate later tasks

1. T2 may centralize Redis connections and key construction, but must not change `validate_runtime_security` behavior or production fail-closed semantics.
2. T3 owns Odoo cache migration; it must preserve mandatory tenant identity in every key.
3. T4/T6 own Telegram queue, distributed limits, receiver leadership, and web-thread removal.
4. T4 workers must receive `organization_id` explicitly; inherited `ContextVar` state is forbidden as a job contract.
5. OCR semaphore state remains local to each worker process.
6. Memory secret storage remains non-production only and must not be promoted into a production Redis secret store.
7. Vector provider/circuit-breaker state remains local unless a later operational requirement explicitly introduces a distributed breaker.

## Acceptance checklist

- [x] Mandatory grep alternatives reviewed across `BOB-2/backend/app`.
- [x] Every meaningful long-lived match classified as `must-move-to-redis`, `safe-per-process`, or `delete`.
- [x] Non-state `ContextVar`, `defaultdict`, and `_store` matches are explicitly justified.
- [x] All files named in T1 are covered.
- [x] No application or security behavior changed.
- [x] No file under `app/core/config.py` or `app/main.py` changed.
- [x] This task contains one documentation commit only.
