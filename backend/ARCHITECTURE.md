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
