# Backend Architecture & Development Guide

## Overview

The backend implements a **FastAPI + Python** service for the GrowthBook Feature Flag Ops Dashboard. It orchestrates safe, auditable flag promotions across environments with mandatory conflict resolution, comprehensive audit trails, and rollback capability.

**Stack:**
- **Framework:** FastAPI (async Python)
- **Database:** PostgreSQL with SQLAlchemy ORM + Alembic migrations
- **External Integration:** GrowthBook REST API (via secret key)
- **Deployment:** Podman Compose (local dev + private network prod)

---

## Folder Structure

The codebase is organized to enforce **SOLID principles**, **DRY**, and scalability.

```
backend/
  app/
    models/
      __init__.py
      database.py          # SQLAlchemy ORM models (market_registry, promotion_batches, flag_snapshots, audit_log)
    
    schemas/
      __init__.py
      market.py            # Pydantic request/response schemas (to be created)
      diff.py              # Diff request/response schemas (to be created)
      promotion.py         # Promotion request/response schemas (to be created)
      audit.py             # Audit log request/response schemas (to be created)
    
    services/              # Core business logic (orchestration, domain rules)
      __init__.py
      diff_engine.py       # Compute diffs: In Sync / Missing / Conflict / Updated
      promotion_orchestrator.py  # Promotion execution: snapshot → update → audit
      audit_logger.py      # Append-only audit event recording
    
    adapters/              # External integrations (interfaces + implementations)
      __init__.py
      interfaces.py        # Abstract base classes (IFeatureFlagProvider, etc.)
      growthbook.py        # GrowthBook REST API adapter — ONLY place calling GrowthBook
    
    repositories/          # Data persistence layer (DB abstraction)
      __init__.py
      db.py                # Repository implementations (market, snapshot, audit)
    
    routers/               # FastAPI route handlers (HTTP endpoints)
      __init__.py
      diff.py              # GET /api/diff
      # TODO: markets.py, promotions.py, audit.py, health.py
    
    db.py                  # Database session management, connection pooling
    __init__.py
  
  main.py                  # FastAPI app initialization, dependency injection setup
  migrations/              # Alembic database migrations
  tests/
    __init__.py
    unit/                  # Unit tests (mock all external deps)
    integration/           # Integration tests (real DB + mocked GrowthBook)
    conftest.py            # Pytest fixtures (mock adapters, test DB, etc.)
  
  requirements.txt
  Dockerfile
  .env.example
  README.md               # This file
  ARCHITECTURE.md         # Folder organization & developer rules
```

---

## Promotion Execution Flow (Implementation Detail)

When a user calls `POST /api/promotions/execute`, here's what happens:

```
HTTP Request (routers/promotions.py)
    ↓
1. Parse & Validate Request
    ↓
2. Call PromotionOrchestrator.execute()
    ├─ VALIDATE: market exists, target env in chain, conflicts resolved
    ├─ SNAPSHOT: Query GrowthBook API for CURRENT rules in target env
    │           Save to flag_snapshots table (if ANY fails, BLOCK promotion)
    ├─ EXECUTE: For each flag:
          │           - Compute new rules (apply resolution decision)
          │             - Two-layer check: first ensure the feature exists in the target environment (create/update as needed), then compare source vs target rules.
          │               * If the feature does not exist in the target, create/update it using source metadata so the feature is present in the target env before applying rules.
          │               * If the source has rules and they differ from target, apply source rules to target.
              │               * If the source has NO rules (empty list): the operator must explicitly mark the resolution as `force=true` to apply a change. In that case the orchestrator MUST write an explicit empty `rules: []` to the target environment which causes the target to evaluate to the feature's `defaultValue`. This is a required core behavior (not optional) to ensure intentional, auditable changes for default-only features; the action and rationale MUST be recorded in the audit entry.
    │           - Call GrowthBookAdapter.update_flag() 
    │               → PATCH /flags/{flag_key}?environment={target_env}
    │           - If ANY fails, rollback all already-updated flags
    ├─ UPDATE MAPPING: Update `flag_market_mapping` to reflect which flags are active in the target market; persist mapping changes and include them in `promotion_batches` metadata. If mapping update fails, trigger rollback.
    ├─ RECORD:  Create entry in promotion_batches table
    └─ AUDIT:   Call AuditLogger.record() with (who, what, when, old→new values)
    ↓
3. Return HTTP Response with promotion_batch_id
    ↓
4. Frontend shows success + audit log entry
```

**Critical Implementation Points:**

| Step | Module | Rule | Why |
|---|---|---|---|
| Snapshot | `PromotionOrchestrator` | P-B6: Must save before any GrowthBook calls | Rollback depends on snapshot; no snapshot = no recovery |
| Execute | `GrowthBookAdapter` | P-B1: ONLY place calling GrowthBook API | If API changes, only this file is touched |
| Rollback | `PromotionOrchestrator` | P-B7: Partial failure = rollback all | Partial promotion leaves envs inconsistent (the bug we prevent) |
| Audit | `AuditLogger` | P-B2: ONLY place writing audit log | Audit must be immutable; scattered writes = compliance gaps |
| Testable | `PromotionOrchestrator` | P-B3: No FastAPI/Pydantic imports | Must be testable without server (use mock adapter) |

**Example Test (pseudocode):**

```python
def test_promotion_execute_with_rollback():
    """If GrowthBook API fails on 2nd flag, all flags are rolled back."""
    
    orchestrator = PromotionOrchestrator(
        adapter=MockGrowthBookAdapter(fail_on_flag="flag_2"),
        repo=MockSnapshotRepository(),
        audit=MockAuditLogger()
    )
    
    with pytest.raises(PromotionRolledBackError):
        orchestrator.execute(
            market="AU",
            from_env="QA",
            to_env="pre-prod",
            flags=["flag_1", "flag_2"],
            resolutions=[...]
        )
    
    # Verify flag_1 was rolled back to pre-snapshot state
    assert repo.get_rollback_calls() == [("flag_1", pre_snapshot_rules)]
```

---

## Folder Responsibilities

### `models/database.py`
**Responsibility:** Define SQLAlchemy ORM models for database tables.

**What goes here:**
- Market registry model
- Promotion batches model
- Flag snapshots model
- Audit log model

**What does NOT go here:**
- Business logic
- Queries (use repositories)
- Pydantic schemas

**Rule:** Only SQLAlchemy `Base` classes. No logic.

---

### `schemas/`
**Responsibility:** Define Pydantic request/response models for API contracts.

**Structure:**
- `market.py` — Market-related schemas
- `diff.py` — Diff-related schemas
- `promotion.py` — Promotion-related schemas
- `audit.py` — Audit log schemas

**Rule:** Define once, import everywhere. Never duplicate. Never inline schemas in routers.

---

### `services/`
**Responsibility:** Implement core business logic, orchestration, and domain rules.

**`diff_engine.py`**
- Compares flag configurations between environments
- Categorizes each flag: In Sync / Missing / Conflict / Updated
- No HTTP, no Pydantic, no DB session — just pure logic
- Testable standalone without FastAPI server

**`promotion_orchestrator.py`**
- Manages promotion batch lifecycle
- Saves pre-promotion snapshot → executes updates → records audit
- Handles rollback: restore from snapshot
- All-or-nothing promotion: if any flag update fails, rollback all
- Rule: MUST NOT know about HTTP, FastAPI, or Pydantic

**`audit_logger.py`**
- Records every action: who, what, when, where, old value, new value
- Append-only event log (immutable)
- Rule: ALL audit writes go through this module. No direct DB writes from other modules.

---

### `adapters/`
**Responsibility:** Integrate with external systems (e.g., GrowthBook) behind interfaces.

**`interfaces.py`**
- Abstract base classes: `IFeatureFlagProvider`, `ISnapshotRepository`, etc.
- Defines contracts; allows mock implementations for testing

**`growthbook.py`**
- Implements `IFeatureFlagProvider`
- ONLY place that calls GrowthBook REST API
- Rule: No other module may call GrowthBook directly. All calls go through this adapter.
- Why: If GrowthBook API changes, only this file is touched.

---

### `repositories/`
**Responsibility:** Abstract database persistence behind a stable interface.

**`db.py`**
- Implements repository classes: `MarketRegistryRepository`, `SnapshotRepository`, `AuditRepository`
- ALL `INSERT`, `UPDATE`, `SELECT` logic here
- Services call repositories; repositories call ORM
- Rule: No raw SQL or ORM queries outside this folder (G-B8)

---

### `routers/`
**Responsibility:** Handle HTTP requests and responses. Thin layer — translate HTTP ↔ domain.

**`diff.py`**
- `GET /api/diff?market=AU&from_env=QA&to_env=pre-prod`
- Calls `DiffEngine.compute()` → returns Pydantic schema

**Pattern:**
1. Extract data from FastAPI request/query
2. Call a service (e.g., `diff_engine.compute()`)
3. Return Pydantic response schema

**Rule:** No business logic in routers. Services own the logic.

---

### `db.py` (app-level)
**Responsibility:** Database session management and connection pooling.

**Provides:**
- `SessionLocal` — session factory for dependency injection
- Engine configuration
- Connection pooling setup

---

## Developer Rules

### Generic Rules (Apply to Any Project)

**Backend:**

| Rule | Principle |
|---|---|
| Every public function/class has a docstring | Readability |
| No secrets or API keys in code — use env vars | Security (OWASP A02) |
| All Pydantic schemas in `schemas/` — never inline | DRY (G-B3) |
| All HTTP errors via global exception handler — no scattered `return JSONResponse` | DRY (G-B4) |
| Every new module implements an `IXxx` interface | SOLID-D (G-B5) |
| New behavior added as subclass, not by modifying existing class | SOLID-O (G-B6) |
| Each class/module has single responsibility | SOLID-S (G-B7) |
| All DB access through repository classes | Repository pattern (G-B8) |
| Every new endpoint has at least one test | Quality baseline (G-B9) |

### Project-Specific Rules (For This Problem)

| Rule | Why |
|---|---|
| **No GrowthBook API call outside `adapters/growthbook.py`** (P-B1) | GrowthBook API can change; one adapter = one change point |
| **All audit log writes through `AuditLogger.record()`** (P-B2) | Audit must be immutable & consistent; compliance gap risk if writes are scattered |
| **`PromotionOrchestrator` has no FastAPI/Pydantic/HTTP** (P-B3) | Promotion logic is safety-critical; must be testable without server |
| **Environment chain read ONLY from `market_registry` DB** (P-B4) | 15+ markets have different env chains; hardcoding breaks scaling |
| **New conflict resolution as new `IResolutionStrategy` subclass** (P-B5) | Conflict resolution is safety gate; changing it risks regressions |
| **Snapshot saved BEFORE promotion; promotion blocked if snapshot fails** (P-B6) | Rollback depends entirely on snapshot; no snapshot = no recovery |
| **Promotion is all-or-nothing; partial failure triggers rollback** (P-B7) | Partial promotion leaves environments inconsistent — exactly what this tool prevents |
| **Two-layer promotion scope: auto-include Missing, require decision on Conflict** (P-B8) | Reduces user friction (Missing = no ambiguity); focuses decisions on actual conflicts |
| **Flag→Market mapping updated only via repository and orchestrator** (P-B9) | Mapping must be durable, included in audits, and rolled back if promotion is rolled back |

---

## Running Locally

### Setup

1. **Activate virtual environment:**
   ```bash
   cd backend
   source .venv/bin/activate  # macOS/Linux
   # or
   .venv\Scripts\activate     # Windows
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with GrowthBook API key and URL
   ```

4. **Initialize database:**
   ```bash
   cd migrations
   alembic upgrade head
   ```

### Run Dev Server

```bash
python -m uvicorn main:app --reload --port 8000
```

**Access:**
- FastAPI docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Run Tests

```bash
pytest tests/ -v          # All tests
pytest tests/unit/ -v     # Unit tests only
pytest tests/integration/ -v  # Integration tests only
pytest tests/ -k "diff"   # Filter by name
```

### Run with Podman Compose

```bash
podman-compose up
```

**Access:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Postgres: localhost:5432

---

## Architecture Principles

### SOLID

| Principle | Applied As |
|---|---|
| **S** — Single Responsibility | `DiffEngine` only computes diffs; `AuditLogger` only logs; `GrowthBookAdapter` only calls GrowthBook |
| **O** — Open / Closed | New conflict resolution strategies added as `IResolutionStrategy` subclasses, not by modifying `ConflictResolver` |
| **L** — Liskov Substitution | `MockGrowthBookAdapter` replaces `GrowthBookAdapter` transparently in tests |
| **I** — Interface Segregation | Frontend schemas separate from internal DB models; endpoints don't leak unrelated fields |
| **D** — Dependency Inversion | Services depend on `IFeatureFlagProvider`, not concrete `GrowthBookAdapter` |

### DRY

| Principle | Applied As |
|---|---|
| **Single source of truth for env chains** | `market_registry` table is the only place env order is defined |
| **Shared Pydantic schemas** | Request/response models defined once in `schemas/`, imported everywhere |
| **Centralised diff logic** | All diff categorization in `DiffEngine.compute()`; frontend just renders |
| **Single audit write path** | All audit entries written through `AuditLogger.record()` |
| **Shared error handling** | Single global exception handler converts domain exceptions to consistent JSON |

---

## Design Patterns

| Pattern | Used In | Benefit |
|---|---|---|
| **Adapter** | `GrowthBookAdapter` wraps GrowthBook REST API | Shields internal logic from upstream API changes |
| **Repository** | `MarketRegistryRepository`, `SnapshotRepository`, `AuditRepository` | Abstracts persistence; easily testable with mocks |
| **Strategy** | `IResolutionStrategy` (keep target, use source, custom) | Extensible without modifying existing code |
| **Command + Memento** | `PromotionOrchestrator` + `FlagSnapshot` | Enables undo/rollback via snapshots |
| **Facade** | FastAPI routers | Hide orchestration complexity behind clean HTTP endpoints |
| **Observer / Event Log** | `AuditLogger` | Decouple side-effects; immutable audit trail |

---

## Adapter API Methods & Promotion Behavior (PoC)

The `GrowthBookAdapter` exposes a small set of primitives the `PromotionOrchestrator` uses. Keep this adapter minimal — all GrowthBook HTTP/JSON handling must live here.

Suggested method signatures:

```
class IFeatureFlagProvider:
  async def get_feature(self, flag_key: str, environment: str) -> dict: ...
  async def create_feature(self, feature_payload: dict, environment: str) -> dict: ...
  async def update_feature(self, flag_key: str, feature_payload: dict, environment: str) -> dict: ...
  async def publish_feature(self, flag_key: str, environment: str) -> dict: ...
  async def enable_feature(self, flag_key: str, environment: str, enabled: bool) -> dict: ...

class GrowthBookAdapter(IFeatureFlagProvider):
  # implements the HTTP calls to GrowthBook REST API and translates errors

**GrowthBook API v2 Integration**

GrowthBook v2 provides improved feature shapes (flat `rules` with per-rule scope) and a dedicated toggle endpoint to atomically enable/disable a feature in one or more environments. Prefer v2 endpoints for integrations.

Key v2 endpoints (base URL: `https://api.growthbook.io/api/v2`):
- `POST /features/:id/toggle` — Toggle a feature on/off in one or more environments. Body: `{"environments": {"qa": true}, "reason": "..."}`.
- `POST /features/:id` — Partially update a feature (patch). Accepts `environments` map and/or full `rules` array (replaces the rules array when supplied).
- `GET /features/:id` — Retrieve feature with unified `rules` array and per-environment `enabled` flags.

Adapter implementation notes:
- Prefer `POST /features/:id/toggle` to flip environment traffic atomically. It is explicitly intended for kill-switch or CI workflows.
- If the toggle endpoint is not available (self-hosted older versions), fall back to `POST /features/:id` with an `environments` map. When setting `enabled: true` on an environment, include a `rules` array when required by the server (some installations validate that `rules` must be an array).
- If v2 endpoints are not supported, the adapter may fall back to v1 endpoints (`/api/v1/features/:id`) as a last resort.

Example curl for v2 toggle (paste into Postman):

```bash
curl -X POST "https://api.growthbook.io/api/v2/features/test-feature/toggle" \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "environments": { "qa": true },
    "reason": "Enable in QA via API"
  }' | jq .
```

Adapter pseudocode for `enable_feature`:

```py
async def enable_feature(flag_key: str, environment: str, enabled: bool):
    # Try v2 toggle first
    resp = await http.post(f"/api/v2/features/{flag_key}/toggle", json={"environments": {environment: enabled}})
    if resp.status_code in (404, 405):
        # Fallback to patching the feature (include rules when required)
        body = {"environments": {environment: {"enabled": enabled, "rules": []}}}
        resp = await http.post(f"/api/v2/features/{flag_key}", json=body)
    if not resp.ok:
        raise AdapterError("Failed to change environment enabled state")
    return resp.json()
```

Testing notes:
- Add unit tests to confirm the adapter calls `/toggle` first and falls back to `/features/:id` on 404/405.
- Add integration tests (mock GrowthBook) to assert `enabled` state is reflected after toggle; also assert that when `rules` are required the adapter sends an array to satisfy server validation.

```

Promotion behavior (PoC rules implemented by `PromotionOrchestrator`):

- Missing flag (exists in source, absent in target):
  1. Build `feature_payload` from source metadata (including `defaultValue`, `rules`, `description`, `enabled` state)
  2. Call `create_feature(feature_payload, target_env)`
  3. If creation returns success, optionally call `publish_feature(flag_key, target_env)` (PoC — include publish in flow)
  4. Ensure `enabled` state in target matches source by calling `enable_feature(flag_key, target_env, enabled=source_enabled)` if needed

- Conflict flag (exists in both but different rules):
  1. Build `feature_payload` containing the full ruleset for the market (overwrite semantics)
  2. Call `update_feature(flag_key, feature_payload, target_env)`
  3. Call `publish_feature(flag_key, target_env)` as part of PoC flow

Notes:
- For PoC we include an explicit `publish_feature` step after create/update. If GrowthBook applies updates immediately, the publish call can be a no-op later.
- All adapter calls must raise domain-specific exceptions (e.g., `AdapterError`, `NotFoundError`, `ConflictError`) which the orchestrator translates to rollback decisions.
- Adapter must support an idempotent `create_feature` that returns existing feature if already present (or raise `ConflictError`).

Pseudocode (PromotionOrchestrator.execute):

```
for flag in flags_to_promote:
  src = adapter.get_feature(flag, from_env)
  try:
    tgt = adapter.get_feature(flag, to_env)
  except NotFoundError:
    # Missing: create with full src payload
    adapter.create_feature(build_payload_from(src), to_env)
    adapter.publish_feature(flag, to_env)
    adapter.enable_feature(flag, to_env, src["enabled"])
    continue

  # Conflict: overwrite full rules
  payload = build_payload_from(src)
  adapter.update_feature(flag, payload, to_env)
  adapter.publish_feature(flag, to_env)

# If any adapter call fails, rollback by applying snapshots via adapter.update_feature(snapshot_payload, env)
```

---

---

## PR Checklist

Before opening a PR, author self-checks:

**Generic:**
- [ ] All public functions/classes have docstrings
- [ ] No secrets or credentials in code
- [ ] All schemas in `schemas/` (not inline)
- [ ] All errors raised as named exceptions, caught by global handler
- [ ] New modules implement an `IXxx` interface
- [ ] New behavior added as subclass, not modifying existing class
- [ ] Each class/module has single responsibility
- [ ] All DB access through repository classes
- [ ] New endpoints have at least one test

**Project-Specific:**
- [ ] No GrowthBook API call outside `adapters/growthbook.py`
- [ ] No audit log write outside `AuditLogger.record()`
- [ ] `PromotionOrchestrator` has no FastAPI/Pydantic imports
- [ ] No hardcoded environment names or market codes
- [ ] New conflict resolution type added as new `IResolutionStrategy` subclass
- [ ] Snapshot saved before promotion; promotion blocked if snapshot write fails
- [ ] Partial failure triggers full rollback (not silent partial completion)
- [ ] Diff Engine auto-includes Missing flags; only requires explicit resolution for Conflicts (P-B8)

> **Reviewer:** If any box is unchecked, request changes — do not approve.

---

## Common Tasks

### Adding a New Endpoint

1. Create router file in `routers/` (e.g., `routers/markets.py`)
2. Define request/response schemas in `schemas/` (e.g., `schemas/market.py`)
3. Call services (not repositories directly)
4. Use global exception handler for errors
5. Add unit tests in `tests/unit/`
6. Add integration tests in `tests/integration/`

### Adding a New Service

1. Create file in `services/` (e.g., `services/notification_manager.py`)
2. Define interface in `adapters/interfaces.py` if external integration needed
3. Depend on repository interfaces, not concrete classes
4. No HTTP, Pydantic, or FastAPI imports
5. Add unit tests with mock repositories/adapters

### Adding a New Repository

1. Create file in `repositories/` (e.g., `repositories/notification_repo.py`)
2. Inherit from base repository class (if one exists)
3. All queries go here; no ORM calls elsewhere
4. Add unit tests with mock DB

---

## Debugging

### Enable Debug Logging

Set in `.env`:
```
LOG_LEVEL=DEBUG
```

### Run Single Test

```bash
pytest tests/unit/test_diff_engine.py::test_compute_diff -v
```

### Debug with PDB

```python
import pdb; pdb.set_trace()
```

Then in test runner:
```bash
pytest tests/ -s --pdb
```

---

## Deployment

### Local Testing

```bash
podman-compose up
```

### Build Docker Image

```bash
docker build -t gbflag-ops-backend:latest .
```

### Push to Private Registry

```bash
docker tag gbflag-ops-backend:latest <registry>/gbflag-ops-backend:latest
docker push <registry>/gbflag-ops-backend:latest
```

### Deploy to Private Network

See deployment runbook in `../docs/deployment/` (TBD).

---

## Troubleshooting

### Import Errors After Folder Restructure

**Problem:** `ModuleNotFoundError: No module named 'app.diff_engine'`

**Solution:** Update imports to new paths:
- `from app.diff_engine import ...` → `from app.services.diff_engine import ...`
- `from app.growthbook_adapter import ...` → `from app.adapters.growthbook import ...`
- `from app.models import ...` → `from app.models.database import ...`

### Tests Fail After Restructure

**Problem:** Pytest cannot find modules

**Solution:**
```bash
# Reinstall package in editable mode
pip install -e .

# Or run from backend root:
python -m pytest tests/
```

### GrowthBook API Timeout

**Problem:** Requests to GrowthBook hang or timeout

**Solution:**
1. Check firewall rules (GrowthBook endpoint must be accessible from private network)
2. Verify API key in `.env` (not empty or malformed)
3. Check GrowthBook service status
4. Add timeout in `adapters/growthbook.py` and retry logic

---

## Next Steps

- [ ] Implement `promotion_orchestrator.py`
- [ ] Implement `audit_logger.py`
- [ ] Create remaining schema files (`market.py`, `promotion.py`, `audit.py`)
- [ ] Add health check endpoint (`routers/health.py`)
- [ ] Add integration tests for all endpoints
- [ ] Add E2E tests for promotion workflow

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-24  
**Owner:** Architecture ()
