# ACRA Integrated Manufacturing Execution System (MES)
## Low-Level Design
**Version:** 1.0
**Date:** March 23, 2026
**Author:** Jesus Esgueva
**SRS Reference:** MES SRS v2.1

This LLD defines how the modules in the HLD are implemented. It covers the database schema, API contracts, core algorithms, backend classes, frontend components, and RBAC rules.

---

## 1. Database Schema

The PostgreSQL design uses 11 tables. Primary keys, foreign keys, and check constraints enforce the core business rules at the data layer.

---

### 1.1 `users`

Stores login accounts, language preference, and account status. Passwords are stored as bcrypt hashes.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `user_id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `username` | `VARCHAR(50)` | `NOT NULL`, `UNIQUE` | Login identifier; must be unique across all accounts |
| `password_hash` | `VARCHAR(255)` | `NOT NULL` | bcrypt hash of the user's password (NFR-005) |
| `full_name` | `VARCHAR(150)` | `NOT NULL` | Display name shown throughout the UI |
| `preferred_language` | `VARCHAR(10)` | `NOT NULL`, `DEFAULT 'en'` | ISO language code: `'en'` or `'es'` (LR-001, LR-002) |
| `status` | `VARCHAR(20)` | `NOT NULL`, `DEFAULT 'active'` | Either `'active'` or `'inactive'` (FR-038) |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT NOW()` | Account creation timestamp in UTC |

**DDL:**
```sql
CREATE TABLE users (
    user_id          SERIAL        PRIMARY KEY,
    username         VARCHAR(50)   NOT NULL UNIQUE,
    password_hash    VARCHAR(255)  NOT NULL,
    full_name        VARCHAR(150)  NOT NULL,
    preferred_language VARCHAR(10) NOT NULL DEFAULT 'en',
    status           VARCHAR(20)   NOT NULL DEFAULT 'active'
                                   CHECK (status IN ('active', 'inactive')),
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
```

---

### 1.2 `roles`

Stores the four system roles. Role names are unique and human-readable.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `role_id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `role_name` | `VARCHAR(100)` | `NOT NULL`, `UNIQUE` | e.g., `'company_admin'`, `'receiving_clerk'`, `'production_supervisor'`, `'machine_operator'` |
| `description` | `TEXT` | | Human-readable description of the role |

**DDL:**
```sql
CREATE TABLE roles (
    role_id     SERIAL        PRIMARY KEY,
    role_name   VARCHAR(100)  NOT NULL UNIQUE,
    description TEXT
);

-- Seed data (SRS Section 4.4.2)
INSERT INTO roles (role_name, description) VALUES
    ('company_admin',         'Full system access; manages users, settings, work orders, and all reports.'),
    ('receiving_clerk',       'Logs incoming material deliveries and performs OCR scanning.'),
    ('production_supervisor', 'Prioritizes and plans work orders, assigns production lines, monitors active orders.'),
    ('machine_operator',      'Views active work orders assigned to their production line.');
```

---

### 1.3 `user_role_assignments`

Junction table for the multi-role model. A user's effective privileges are the union of all assigned roles.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `user_id` | `INTEGER` | `NOT NULL`, `FK → users(user_id)` | References the assigned user |
| `role_id` | `INTEGER` | `NOT NULL`, `FK → roles(role_id)` | References the assigned role |
| `assigned_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT NOW()` | Timestamp of role assignment for audit purposes |

**Composite Primary Key:** `(user_id, role_id)` — prevents duplicate role assignments.

**DDL:**
```sql
CREATE TABLE user_role_assignments (
    user_id     INTEGER     NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id     INTEGER     NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);
```

---

### 1.4 `deliveries`

Header record for an incoming bill of lading.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `delivery_id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `supplier` | `VARCHAR(200)` | `NOT NULL` | Name of the supplying vendor |
| `carrier` | `VARCHAR(200)` | `NOT NULL` | Truck/carrier information |
| `delivery_date` | `DATE` | `NOT NULL` | Date the delivery physically arrived at the facility |
| `bol_reference` | `VARCHAR(100)` | `NOT NULL`, `UNIQUE` | Bill of lading reference number; enforces duplicate detection (UC-001 E2) |
| `created_by` | `INTEGER` | `NOT NULL`, `FK → users(user_id)` | User who recorded the delivery (Clerk or Admin) |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT NOW()` | Timestamp of record creation |

**DDL:**
```sql
CREATE TABLE deliveries (
    delivery_id   SERIAL        PRIMARY KEY,
    supplier      VARCHAR(200)  NOT NULL,
    carrier       VARCHAR(200)  NOT NULL,
    delivery_date DATE          NOT NULL,
    bol_reference VARCHAR(100)  NOT NULL UNIQUE,
    created_by    INTEGER       NOT NULL REFERENCES users(user_id),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
```

---

### 1.5 `delivery_items`

Line items recorded under a delivery. Each confirmed row creates one inventory record and keeps source-to-stock traceability.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `item_id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `delivery_id` | `INTEGER` | `NOT NULL`, `FK → deliveries(delivery_id)` | Parent delivery record |
| `material_type` | `VARCHAR(200)` | `NOT NULL` | Name/description of the material received |
| `quantity` | `NUMERIC(12,3)` | `NOT NULL`, `CHECK > 0` | Quantity received; supports fractional units |
| `lot_batch_number` | `VARCHAR(100)` | `NOT NULL` | Supplier-assigned lot or batch identifier (FR-010) |
| `storage_location` | `VARCHAR(100)` | `NOT NULL` | Where the material was placed in the facility |
| `inventory_item_id` | `INTEGER` | `FK → inventory_items(inventory_id)` | Set after delivery confirmation; links to the created inventory record |

**DDL:**
```sql
CREATE TABLE delivery_items (
    item_id           SERIAL           PRIMARY KEY,
    delivery_id       INTEGER          NOT NULL REFERENCES deliveries(delivery_id) ON DELETE CASCADE,
    material_type     VARCHAR(200)     NOT NULL,
    quantity          NUMERIC(12,3)    NOT NULL CHECK (quantity > 0),
    lot_batch_number  VARCHAR(100)     NOT NULL,
    storage_location  VARCHAR(100)     NOT NULL,
    inventory_item_id INTEGER          REFERENCES inventory_items(inventory_id)
);
```

*Note: The forward reference to `inventory_items` is resolved at delivery confirmation time; the column is nullable until then.*

---

### 1.6 `inventory_items`

Current stock by lot and location for raw materials and finished goods.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `inventory_id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `material_type` | `VARCHAR(200)` | `NOT NULL` | Name/description of the material |
| `category` | `VARCHAR(20)` | `NOT NULL`, `CHECK IN ('raw', 'finished')` | Distinguishes raw materials (FR-006) from finished goods (FR-007) |
| `quantity_on_hand` | `NUMERIC(12,3)` | `NOT NULL`, `DEFAULT 0`, `CHECK >= 0` | Current available stock; never negative |
| `lot_batch_number` | `VARCHAR(100)` | `NOT NULL` | Lot/batch identifier for traceability (FR-010) |
| `storage_location` | `VARCHAR(100)` | `NOT NULL` | Physical location within the facility |
| `source_delivery_item_id` | `INTEGER` | `FK → delivery_items(item_id)` | Links back to the delivery line that created this record (FR-010) |
| `last_updated` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT NOW()` | Timestamp of the last quantity change (NFR-004) |

**DDL:**
```sql
CREATE TABLE inventory_items (
    inventory_id           SERIAL          PRIMARY KEY,
    material_type          VARCHAR(200)    NOT NULL,
    category               VARCHAR(20)     NOT NULL CHECK (category IN ('raw', 'finished')),
    quantity_on_hand       NUMERIC(12,3)   NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
    lot_batch_number       VARCHAR(100)    NOT NULL,
    storage_location       VARCHAR(100)    NOT NULL,
    source_delivery_item_id INTEGER        REFERENCES delivery_items(item_id),
    last_updated           TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
```

---

### 1.7 `work_orders`

Production order header. It stores lifecycle state, scheduling fields, and queue order.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `work_order_id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `product` | `VARCHAR(200)` | `NOT NULL` | Product to manufacture |
| `quantity_required` | `NUMERIC(12,3)` | `NOT NULL`, `CHECK > 0` | Total units to produce |
| `quantity_produced` | `NUMERIC(12,3)` | `NOT NULL`, `DEFAULT 0`, `CHECK >= 0` | Units completed so far |
| `priority` | `VARCHAR(20)` | `NOT NULL`, `DEFAULT 'medium'` | `'low'`, `'medium'`, `'high'`, or `'urgent'` |
| `display_sequence` | `INTEGER` | `NOT NULL`, `DEFAULT 0` | Manual queue order inside the same priority bucket |
| `status` | `VARCHAR(30)` | `NOT NULL`, `DEFAULT 'created'` | `'created'`, `'materials_allocated'`, `'in_production'`, `'completed'`, `'ready_for_shipment'` |
| `target_date` | `DATE` | `NOT NULL` | Target completion date |
| `production_line` | `VARCHAR(50)` | | Assigned line |
| `created_by` | `INTEGER` | `NOT NULL`, `FK → users(user_id)` | Admin who created the work order |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT NOW()` | Creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT NOW()` | Last status, schedule, or quantity update |

**DDL:**
```sql
CREATE TABLE work_orders (
    work_order_id     SERIAL          PRIMARY KEY,
    product           VARCHAR(200)    NOT NULL,
    quantity_required NUMERIC(12,3)   NOT NULL CHECK (quantity_required > 0),
    quantity_produced NUMERIC(12,3)   NOT NULL DEFAULT 0 CHECK (quantity_produced >= 0),
    priority          VARCHAR(20)     NOT NULL DEFAULT 'medium'
                                      CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    display_sequence  INTEGER         NOT NULL DEFAULT 0,
    status            VARCHAR(30)     NOT NULL DEFAULT 'created'
                                      CHECK (status IN (
                                          'created', 'materials_allocated',
                                          'in_production', 'completed', 'ready_for_shipment'
                                      )),
    target_date       DATE            NOT NULL,
    production_line   VARCHAR(50),
    created_by        INTEGER         NOT NULL REFERENCES users(user_id),
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
```

---

### 1.8 `work_order_materials`

Material requirements per work order. Per-lot reservations are stored in `material_allocations`.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `work_order_id` | `INTEGER` | `NOT NULL`, `FK → work_orders(work_order_id)` | Parent work order |
| `material_type` | `VARCHAR(200)` | `NOT NULL` | Required material |
| `quantity_required` | `NUMERIC(12,3)` | `NOT NULL`, `CHECK > 0` | Amount needed |
| `quantity_allocated` | `NUMERIC(12,3)` | `NOT NULL`, `DEFAULT 0`, `CHECK >= 0` | Total reserved amount |

**DDL:**
```sql
CREATE TABLE work_order_materials (
    id                  SERIAL          PRIMARY KEY,
    work_order_id       INTEGER         NOT NULL REFERENCES work_orders(work_order_id) ON DELETE CASCADE,
    material_type       VARCHAR(200)    NOT NULL,
    quantity_required   NUMERIC(12,3)   NOT NULL CHECK (quantity_required > 0),
    quantity_allocated  NUMERIC(12,3)   NOT NULL DEFAULT 0 CHECK (quantity_allocated >= 0)
);
```

---

### 1.9 `material_allocations`

Per-lot reservations created during material allocation. This table preserves full traceability when one requirement is fulfilled from multiple inventory lots.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `allocation_id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `work_order_material_id` | `INTEGER` | `NOT NULL`, `FK → work_order_materials(id)` | Material requirement being fulfilled |
| `inventory_id` | `INTEGER` | `NOT NULL`, `FK → inventory_items(inventory_id)` | Source inventory row |
| `lot_batch_number` | `VARCHAR(100)` | `NOT NULL` | Lot used for this reservation |
| `quantity_allocated` | `NUMERIC(12,3)` | `NOT NULL`, `CHECK > 0` | Reserved quantity from this lot |
| `allocated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT NOW()` | Reservation timestamp |

**DDL:**
```sql
CREATE TABLE material_allocations (
    allocation_id          SERIAL          PRIMARY KEY,
    work_order_material_id INTEGER         NOT NULL REFERENCES work_order_materials(id) ON DELETE CASCADE,
    inventory_id           INTEGER         NOT NULL REFERENCES inventory_items(inventory_id),
    lot_batch_number       VARCHAR(100)    NOT NULL,
    quantity_allocated     NUMERIC(12,3)   NOT NULL CHECK (quantity_allocated > 0),
    allocated_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
```

---

### 1.10 `audit_logs`

Immutable log of data-changing operations. `details` stores structured event context in JSONB.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `log_id` | `BIGSERIAL` | `PRIMARY KEY` | Large integer; audit logs grow without bound |
| `user_id` | `INTEGER` | `FK → users(user_id)` | User who performed the action; nullable for system-initiated events |
| `action` | `VARCHAR(100)` | `NOT NULL` | Verb describing the event, e.g., `'LOGIN'`, `'DELIVERY_CONFIRMED'`, `'INVENTORY_ADJUSTED'`, `'WORK_ORDER_CREATED'` |
| `entity_type` | `VARCHAR(100)` | `NOT NULL` | Table/entity affected, e.g., `'delivery'`, `'inventory_item'`, `'work_order'` |
| `entity_id` | `INTEGER` | | PK of the affected record |
| `details` | `JSONB` | | Structured context: old values, new values, notes (NFR-009) |
| `timestamp` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT NOW()` | UTC timestamp of the event |

**DDL:**
```sql
CREATE TABLE audit_logs (
    log_id      BIGSERIAL     PRIMARY KEY,
    user_id     INTEGER       REFERENCES users(user_id),
    action      VARCHAR(100)  NOT NULL,
    entity_type VARCHAR(100)  NOT NULL,
    entity_id   INTEGER,
    details     JSONB,
    timestamp   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Index for efficient audit queries by entity (NFR-001)
CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_logs_user   ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_time   ON audit_logs(timestamp DESC);
```

---

### 1.11 `low_stock_alerts`

Per-material low-stock thresholds.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `alert_id` | `SERIAL` | `PRIMARY KEY` | Auto-incrementing surrogate key |
| `material_type` | `VARCHAR(200)` | `NOT NULL`, `UNIQUE` | One threshold per material type (FR-009) |
| `threshold` | `NUMERIC(12,3)` | `NOT NULL`, `CHECK >= 0` | Quantity at or below which an alert fires |
| `created_by` | `INTEGER` | `NOT NULL`, `FK → users(user_id)` | Admin who configured the threshold (FR-009) |

**DDL:**
```sql
CREATE TABLE low_stock_alerts (
    alert_id      SERIAL          PRIMARY KEY,
    material_type VARCHAR(200)    NOT NULL UNIQUE,
    threshold     NUMERIC(12,3)   NOT NULL CHECK (threshold >= 0),
    created_by    INTEGER         NOT NULL REFERENCES users(user_id)
);
```

---

## 2. Entity Relationships

The relationships below are the implementation reference.

| Parent | Child | Cardinality | FK |
|--------|-------|-------------|----|
| `users` | `user_role_assignments` | 1:M | `user_role_assignments.user_id` |
| `roles` | `user_role_assignments` | 1:M | `user_role_assignments.role_id` |
| `users` | `deliveries` | 1:M | `deliveries.created_by` |
| `deliveries` | `delivery_items` | 1:M | `delivery_items.delivery_id` |
| `delivery_items` | `inventory_items` | 1:1 after confirmation | `inventory_items.source_delivery_item_id` |
| `inventory_items` | `delivery_items` | 1:0..1 back-link | `delivery_items.inventory_item_id` |
| `users` | `work_orders` | 1:M | `work_orders.created_by` |
| `work_orders` | `work_order_materials` | 1:M | `work_order_materials.work_order_id` |
| `work_order_materials` | `material_allocations` | 1:M | `material_allocations.work_order_material_id` |
| `inventory_items` | `material_allocations` | 1:M | `material_allocations.inventory_id` |
| `users` | `audit_logs` | 1:M | `audit_logs.user_id` |
| `users` | `low_stock_alerts` | 1:M | `low_stock_alerts.created_by` |

---

## 3. API Endpoints per Module

All endpoints are served by the FastAPI backend over HTTPS (NFR-006). Authorization is enforced at the API layer via JWT-based RBAC middleware on every request (NFR-007, FR-037). Request and response bodies use JSON unless noted otherwise. HTTP status codes follow REST conventions: `200 OK`, `201 Created`, `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `409 Conflict`, `500 Internal Server Error`.

---

### 3.1 Authentication

#### `POST /auth/login`

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Path** | `/auth/login` |
| **Description** | Validates user credentials and issues a JWT. Writes a `LOGIN` event to the audit log (FR-039). |
| **Required Role(s)** | Public (no authentication required) |
| **Request Body** | `{ "username": "string", "password": "string" }` |
| **Success Response** | `200 OK` — `{ "access_token": "string (JWT)", "token_type": "bearer", "user": { "user_id": int, "full_name": "string", "roles": ["string"], "preferred_language": "string" } }` |
| **Error Responses** | `401` — Invalid credentials (UC-011 E1); `403` — Account deactivated (UC-011 E2) |
| **SRS References** | FR-036, FR-037, FR-039, NFR-005, NFR-006, NFR-008 |

#### `POST /auth/logout`

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Path** | `/auth/logout` |
| **Description** | Invalidates the current session token and writes a `LOGOUT` event to the audit log (FR-039). |
| **Required Role(s)** | Any authenticated user |
| **Request Body** | None (JWT passed in `Authorization: Bearer` header) |
| **Success Response** | `200 OK` — `{ "message": "Logged out successfully." }` |
| **Error Responses** | `401` — Missing or invalid token |
| **SRS References** | FR-039, NFR-008, NFR-009 |

---

### 3.2 Receiving Module

#### `POST /deliveries`

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Path** | `/deliveries` |
| **Description** | Creates a new delivery record along with its line items. Upon confirmation, the system automatically creates `inventory_items` entries for each line item and links them via `inventory_item_id` (FR-004). Writes a `DELIVERY_CONFIRMED` audit log entry. |
| **Required Role(s)** | `receiving_clerk`, `company_admin` (PRV-001) |
| **Request Body** | `{ "supplier": "string", "carrier": "string", "delivery_date": "YYYY-MM-DD", "bol_reference": "string", "items": [ { "material_type": "string", "quantity": number, "lot_batch_number": "string", "storage_location": "string" } ] }` |
| **Success Response** | `201 Created` — `{ "delivery_id": int, "items_created": int, "message": "Delivery recorded successfully. X items added to inventory." }` |
| **Error Responses** | `400` — Missing required fields; `409` — Duplicate BOL reference (UC-001 E2) |
| **SRS References** | FR-001, FR-003, FR-004, FR-005, NFR-004, NFR-009 |

#### `POST /deliveries/ocr`

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Path** | `/deliveries/ocr` |
| **Description** | Accepts a multipart image upload of a bill of lading, processes it through the OCR engine, and returns a structured JSON payload of extracted fields. The client displays the result in an editable form for clerk review (FR-003). Does not persist any records. |
| **Required Role(s)** | `receiving_clerk`, `company_admin` (PRV-003) |
| **Request Body** | `multipart/form-data` — field `file`: image (JPEG, PNG, PDF) |
| **Success Response** | `200 OK` — `{ "supplier": "string\|null", "carrier": "string\|null", "bol_reference": "string\|null", "delivery_date": "string\|null", "items": [ { "material_type": "string", "quantity": number\|null, "lot_batch_number": "string\|null" } ], "confidence": float }` |
| **Error Responses** | `422` — OCR extraction failed; client shown manual entry fallback (UC-001 E1); `400` — Unsupported file type |
| **SRS References** | FR-002, FR-003, NFR-002 |

#### `GET /deliveries`

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Path** | `/deliveries` |
| **Description** | Returns a paginated, searchable log of all delivery records (FR-005). Supports filtering by supplier, carrier, date range, and BOL reference. |
| **Required Role(s)** | `receiving_clerk`, `company_admin` (PRV-002) |
| **Query Parameters** | `supplier` (string), `carrier` (string), `bol_reference` (string), `date_from` (YYYY-MM-DD), `date_to` (YYYY-MM-DD), `page` (int, default 1), `page_size` (int, default 25) |
| **Success Response** | `200 OK` — `{ "total": int, "page": int, "results": [ { "delivery_id": int, "supplier": "string", "carrier": "string", "delivery_date": "string", "bol_reference": "string", "created_by": "string", "created_at": "string", "items": [...] } ] }` |
| **Error Responses** | `400` — Invalid date format |
| **SRS References** | FR-005, NFR-001 |

---

### 3.3 Inventory Module

#### `GET /inventory`

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Path** | `/inventory` |
| **Description** | Returns paginated inventory items filterable by material type, category, lot/batch number, storage location, and date range (FR-006, FR-007, FR-011). |
| **Required Role(s)** | `receiving_clerk`, `production_supervisor`, `company_admin` (PRV-004) |
| **Query Parameters** | `category` (`raw`\|`finished`), `material_type` (string), `lot_batch_number` (string), `storage_location` (string), `date_from` (YYYY-MM-DD), `date_to` (YYYY-MM-DD), `page` (int), `page_size` (int) |
| **Success Response** | `200 OK` — `{ "total": int, "results": [ { "inventory_id": int, "material_type": "string", "category": "string", "quantity_on_hand": number, "lot_batch_number": "string", "storage_location": "string", "last_updated": "string" } ] }` |
| **Error Responses** | `400` — Invalid filter values |
| **SRS References** | FR-006, FR-007, FR-011 |

#### `PATCH /inventory/{id}`

| Field | Value |
|-------|-------|
| **Method** | `PATCH` |
| **Path** | `/inventory/{id}` |
| **Description** | Allows an Admin to manually adjust the `quantity_on_hand` for an inventory item (e.g., following a physical count). Writes an `INVENTORY_ADJUSTED` audit log entry including the old and new values (FR-012). Inventory update is reflected within 2 seconds (NFR-004). |
| **Required Role(s)** | `company_admin` only (PRV-005) |
| **Path Parameter** | `id` — `inventory_id` of the item to adjust |
| **Request Body** | `{ "quantity_on_hand": number, "reason": "string" }` |
| **Success Response** | `200 OK` — `{ "inventory_id": int, "quantity_on_hand": number, "last_updated": "string" }` |
| **Error Responses** | `403` — Non-admin caller; `404` — Item not found; `400` — Negative quantity |
| **SRS References** | FR-008, FR-012, NFR-004, NFR-009 |

#### `GET /inventory/trace/{lot_batch_number}`

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Path** | `/inventory/trace/{lot_batch_number}` |
| **Description** | Returns a full traceability report for the given lot/batch number, showing the source delivery, current inventory status, and any work orders that consumed or allocated materials from this lot (FR-010). |
| **Required Role(s)** | `production_supervisor`, `company_admin` (PRV-007) |
| **Path Parameter** | `lot_batch_number` — lot/batch identifier to trace |
| **Success Response** | `200 OK` — `{ "lot_batch_number": "string", "source_delivery": { ... }, "inventory_items": [ ... ], "work_orders": [ ... ] }` |
| **Error Responses** | `404` — No records found for this lot number |
| **SRS References** | FR-010, FR-011 |

#### `GET /inventory/alerts`

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Path** | `/inventory/alerts` |
| **Description** | Returns all configured low-stock alert thresholds and indicates which materials are currently at or below their threshold (FR-009). |
| **Required Role(s)** | `company_admin` (PRV-006) |
| **Query Parameters** | None |
| **Success Response** | `200 OK` — `{ "alerts": [ { "alert_id": int, "material_type": "string", "threshold": number, "current_quantity": number, "is_triggered": bool } ] }` |
| **Error Responses** | `403` — Non-admin caller |
| **SRS References** | FR-009 |

#### `POST /inventory/alerts`

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Path** | `/inventory/alerts` |
| **Description** | Creates or updates a low-stock alert threshold for a given material type (FR-009). If a threshold already exists for the material, it is overwritten (upsert behavior). |
| **Required Role(s)** | `company_admin` (PRV-006) |
| **Request Body** | `{ "material_type": "string", "threshold": number }` |
| **Success Response** | `201 Created` — `{ "alert_id": int, "material_type": "string", "threshold": number }` |
| **Error Responses** | `400` — Invalid threshold (negative); `403` — Non-admin caller |
| **SRS References** | FR-009 |

#### `GET /inventory/export`

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Path** | `/inventory/export` |
| **Description** | Generates and returns a CSV file of all current inventory items, optionally filtered by the same parameters as `GET /inventory` (UC-002 A1). |
| **Required Role(s)** | `receiving_clerk`, `production_supervisor`, `company_admin` (PRV-004) |
| **Query Parameters** | Same as `GET /inventory` |
| **Success Response** | `200 OK` — `Content-Type: text/csv; charset=utf-8` with `Content-Disposition: attachment; filename="inventory_export.csv"` |
| **Error Responses** | `403` — Insufficient privileges |
| **SRS References** | FR-011, UC-002 A1 |

---

### 3.4 Work Order Module

#### `POST /work-orders`

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Path** | `/work-orders` |
| **Description** | Creates a new work order with status `created`. Validates that required materials exist in inventory and warns if quantities are insufficient (FR-019). Does not allocate inventory at creation time — allocation is a separate step (UC-004). |
| **Required Role(s)** | `company_admin` (PRV-008) |
| **Request Body** | `{ "product": "string", "quantity_required": number, "priority": "low\|medium\|high\|urgent", "target_date": "YYYY-MM-DD", "production_line": "string\|null", "materials": [ { "material_type": "string", "quantity_required": number } ] }` |
| **Success Response** | `201 Created` — `{ "work_order_id": int, "status": "created", "material_availability": [ { "material_type": "string", "required": number, "available": number, "sufficient": bool } ] }` |
| **Error Responses** | `400` — Missing required fields or invalid priority/date |
| **SRS References** | FR-013, FR-014, FR-018, FR-019 |

#### `GET /work-orders`

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Path** | `/work-orders` |
| **Description** | Returns a paginated list of work orders. Machine Operators see only orders assigned to their production line; other roles see all orders. Filterable by status and production line (FR-016, FR-017). |
| **Required Role(s)** | All authenticated roles (PRV-009) |
| **Query Parameters** | `status` (string), `production_line` (string), `priority` (string), `page` (int), `page_size` (int) |
| **Success Response** | `200 OK` — `{ "total": int, "results": [ { "work_order_id": int, "product": "string", "status": "string", "priority": "string", "production_line": "string", "target_date": "string", "quantity_required": number, "quantity_produced": number } ] }` |
| **Error Responses** | `400` — Invalid filter values |
| **SRS References** | FR-016, FR-017, FR-021 |

#### `PATCH /work-orders/{id}/allocate`

| Field | Value |
|-------|-------|
| **Method** | `PATCH` |
| **Path** | `/work-orders/{id}/allocate` |
| **Description** | Triggers material allocation for the specified work order (UC-004). Uses pessimistic database locking (`SELECT ... FOR UPDATE`) to prevent concurrent allocation conflicts. Deducts quantities from `inventory_items` and updates `work_order_materials.quantity_allocated`. Advances work order status to `materials_allocated` on success. See Section 4.1 for the full algorithm. |
| **Required Role(s)** | `company_admin`, `production_supervisor` (PRV-011) |
| **Path Parameter** | `id` — `work_order_id` |
| **Request Body** | None (materials already defined in `work_order_materials`) |
| **Success Response** | `200 OK` — `{ "work_order_id": int, "status": "materials_allocated", "allocated": [ { "material_type": "string", "quantity_allocated": number } ] }` |
| **Error Responses** | `409` — Insufficient inventory for one or more materials (UC-004 E1); `400` — Work order not in `created` status |
| **SRS References** | FR-015, FR-016, FR-018, FR-019, NFR-004 |

#### `PATCH /work-orders/{id}/assign`

| Field | Value |
|-------|-------|
| **Method** | `PATCH` |
| **Path** | `/work-orders/{id}/assign` |
| **Description** | Assigns or reassigns a work order to a specific production line (FR-015, UC-005). Warns if the target line already has the maximum number of active orders (UC-005 E2). |
| **Required Role(s)** | `company_admin`, `production_supervisor` (PRV-010) |
| **Path Parameter** | `id` — `work_order_id` |
| **Request Body** | `{ "production_line": "string" }` |
| **Success Response** | `200 OK` — `{ "work_order_id": int, "production_line": "string" }` |
| **Error Responses** | `404` — Work order not found; `400` — Invalid production line name |
| **SRS References** | FR-015, FR-017, UC-005 |

#### `PATCH /work-orders/{id}/status`

| Field | Value |
|-------|-------|
| **Method** | `PATCH` |
| **Path** | `/work-orders/{id}/status` |
| **Description** | Advances a work order to the next lifecycle status (FR-016). The backend enforces valid transitions only: `created → materials_allocated` (via allocate endpoint), `materials_allocated → in_production`, `in_production → completed`, `completed → ready_for_shipment`. |
| **Required Role(s)** | `company_admin`, `production_supervisor` (PRV-012) |
| **Path Parameter** | `id` — `work_order_id` |
| **Request Body** | `{ "status": "string", "quantity_produced": number\|null }` |
| **Success Response** | `200 OK` — `{ "work_order_id": int, "status": "string", "updated_at": "string" }` |
| **Error Responses** | `400` — Invalid or disallowed status transition; `404` — Work order not found |
| **SRS References** | FR-016, FR-021 |

#### `GET /work-orders/{id}`

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Path** | `/work-orders/{id}` |
| **Description** | Returns full detail for a single work order, including all associated materials and their allocation status. |
| **Required Role(s)** | All authenticated roles (PRV-009) |
| **Path Parameter** | `id` — `work_order_id` |
| **Success Response** | `200 OK` — `{ "work_order_id": int, "product": "string", "status": "string", "priority": "string", "production_line": "string", "target_date": "string", "quantity_required": number, "quantity_produced": number, "created_by": "string", "created_at": "string", "materials": [ { "material_type": "string", "quantity_required": number, "quantity_allocated": number, "lot_batch_number": "string" } ] }` |
| **Error Responses** | `404` — Work order not found |
| **SRS References** | FR-016, FR-017, FR-021 |

---

### 3.5 User Management Module

#### `GET /users`

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Path** | `/users` |
| **Description** | Returns a paginated list of all user accounts with their assigned roles and account status (UC-009, FR-038). |
| **Required Role(s)** | `company_admin` (PRV-015) |
| **Query Parameters** | `status` (`active`\|`inactive`), `role` (string), `page` (int), `page_size` (int) |
| **Success Response** | `200 OK` — `{ "total": int, "results": [ { "user_id": int, "username": "string", "full_name": "string", "roles": ["string"], "status": "string", "created_at": "string" } ] }` |
| **SRS References** | FR-038, UC-009 |

#### `POST /users`

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Path** | `/users` |
| **Description** | Creates a new user account (UC-009 Step 3–5). Password is hashed with bcrypt before storage (NFR-005). |
| **Required Role(s)** | `company_admin` (PRV-015) |
| **Request Body** | `{ "username": "string", "full_name": "string", "password": "string", "preferred_language": "en\|es", "role_ids": [int] }` |
| **Success Response** | `201 Created` — `{ "user_id": int, "username": "string", "message": "User account created successfully." }` |
| **Error Responses** | `409` — Duplicate username (UC-009 E1) |
| **SRS References** | FR-035, FR-038, NFR-005 |

#### `PATCH /users/{id}`

| Field | Value |
|-------|-------|
| **Method** | `PATCH` |
| **Path** | `/users/{id}` |
| **Description** | Updates a user's full name, preferred language, or account status. Deactivation is blocked if the user is the last active Admin (UC-009 E2). Writes a `USER_UPDATED` audit log entry (NFR-009). |
| **Required Role(s)** | `company_admin` (PRV-015) |
| **Path Parameter** | `id` — `user_id` |
| **Request Body** | `{ "full_name": "string\|null", "preferred_language": "string\|null", "status": "active\|inactive\|null" }` |
| **Success Response** | `200 OK` — `{ "user_id": int, "full_name": "string", "status": "string" }` |
| **Error Responses** | `409` — Cannot deactivate last Admin (UC-009 E2); `404` — User not found |
| **SRS References** | FR-038, UC-009 A1, UC-009 A2 |

#### `POST /users/{id}/roles`

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Path** | `/users/{id}/roles` |
| **Description** | Replaces the user's role assignments with the provided list (full replace, not additive). Supports the multi-role model described in SRS Section 4.4.3. Writes a `ROLES_UPDATED` audit log entry. |
| **Required Role(s)** | `company_admin` (PRV-015) |
| **Path Parameter** | `id` — `user_id` |
| **Request Body** | `{ "role_ids": [int] }` |
| **Success Response** | `200 OK` — `{ "user_id": int, "roles": ["string"] }` |
| **Error Responses** | `400` — Invalid role IDs; `404` — User not found |
| **SRS References** | FR-035, FR-038, SRS Section 4.4.3 |

---

## 4. Key Algorithms

### 4.1 Material Allocation Algorithm (UC-004, FR-018)

This algorithm runs when `PATCH /work-orders/{id}/allocate` is called. Pessimistic locking (`SELECT ... FOR UPDATE`) prevents concurrent requests from allocating the same inventory rows, satisfying FR-019 and NFR-004.

```
ALGORITHM: AllocateMaterialsToWorkOrder(work_order_id, requesting_user_id)

PRE-CONDITIONS:
  - work_order.status == 'created'
  - Caller has PRV-011 privilege

STEPS:
  1. BEGIN TRANSACTION (serializable isolation level)

  2. SELECT work_order WHERE work_order_id = ? FOR UPDATE
     - If status != 'created': ROLLBACK; return HTTP 400 "Invalid status for allocation"

  3. Fetch all work_order_materials rows for this work_order_id
     - Group by material_type to build a requirements map:
       { material_type → quantity_required }

  4. For each material_type in requirements map:
     a. SELECT inventory_items
        WHERE material_type = ?
          AND category = 'raw'
          AND quantity_on_hand > 0
        ORDER BY last_updated ASC          -- FIFO: oldest stock consumed first
        FOR UPDATE                         -- Pessimistic lock on all candidate rows

     b. Sum quantity_on_hand across locked rows.
        If sum < quantity_required:
          ROLLBACK
          Return HTTP 409 { "error": "Insufficient stock", "material": material_type,
                            "required": quantity_required, "available": sum }

     c. Iterate locked rows in FIFO order, deducting from quantity_on_hand:
        remaining_to_deduct = quantity_required
        For each row:
          deduct = MIN(row.quantity_on_hand, remaining_to_deduct)
          UPDATE inventory_items SET quantity_on_hand = quantity_on_hand - deduct,
                                     last_updated = NOW()
                 WHERE inventory_id = row.inventory_id
          remaining_to_deduct -= deduct
          Record (lot_batch_number, deduct) for audit trail
          If remaining_to_deduct == 0: break

  5. For each work_order_materials row:
     UPDATE work_order_materials
        SET quantity_allocated = quantity_required,
            lot_batch_number   = <lot from step 4c>
      WHERE id = ?

  6. UPDATE work_orders
        SET status = 'materials_allocated'
      WHERE work_order_id = ?

  7. COMMIT TRANSACTION

  8. INSERT INTO audit_logs
       (user_id, action, entity_type, entity_id, details, timestamp)
     VALUES
       (requesting_user_id, 'MATERIALS_ALLOCATED', 'work_order', work_order_id,
        { "materials": [ { material_type, qty_allocated, lot } ], ... }, NOW())

  9. Check low_stock_alerts: for each material_type just deducted, compare
     new quantity_on_hand against low_stock_alerts.threshold.
     If triggered, surface alert in GET /inventory/alerts response.

 10. Return HTTP 200 with allocated quantities and updated work order status.

POST-CONDITIONS:
  - work_order.status == 'materials_allocated'
  - inventory_items.quantity_on_hand reduced by allocated amounts
  - audit_logs entry created (NFR-009)
```

---

### 4.2 RBAC Enforcement Flow (FR-037, NFR-007)

This middleware runs on every incoming API request (except `POST /auth/login`). It is implemented as a FastAPI dependency injected into all protected route handlers.

```
ALGORITHM: EnforceRBAC(http_request, required_privilege)

STEPS:
  1. Extract JWT from HTTP header: Authorization: Bearer <token>
     If absent: return HTTP 401 "Authentication required"

  2. Verify JWT signature using server secret key.
     If invalid or expired: return HTTP 401 "Token invalid or expired"
     Note: Tokens expire after 30 minutes of inactivity (NFR-008)

  3. Decode JWT payload → extract user_id

  4. Query database:
     SELECT r.role_name
       FROM user_role_assignments ura
       JOIN roles r ON ura.role_id = r.role_id
      WHERE ura.user_id = user_id

     → returns a list of role names assigned to this user

  5. Look up each role_name in the hardcoded ROLE_PRIVILEGE_MAP
     (defined as a Python constant mirroring SRS Section 4.4.2):
     {
       'company_admin':         { all PRV-001 through PRV-017 },
       'receiving_clerk':       { PRV-001, PRV-002, PRV-003, PRV-004 },
       'production_supervisor': { PRV-004, PRV-007, PRV-009, PRV-010, PRV-011, PRV-012 },
       'machine_operator':      { PRV-009 }
     }

  6. Compute effective_privileges = UNION of all privilege sets across assigned roles
     (multi-role union per SRS Section 4.4.3)

  7. If required_privilege NOT IN effective_privileges:
     return HTTP 403 "Insufficient privileges"

  8. Attach user_id and effective_privileges to the request context.
     Proceed to the route handler.

SPECIAL CASES:
  - Machine Operators on GET /work-orders: filter results to
    work_orders.production_line matching their assigned line only.
  - System-level audit writes (step 8 of allocation) use a dedicated
    service account user_id and bypass RBAC checks.
```

---

### 4.3 OCR Flow (FR-002, FR-003, NFR-002)

This algorithm runs when `POST /deliveries/ocr` is called. It processes the uploaded bill of lading image and returns structured extracted data for clerk review. The OCR step does not persist any data.

```
ALGORITHM: ProcessBOLOCR(uploaded_image_file)

PRE-CONDITIONS:
  - Caller has PRV-003 privilege
  - File is JPEG, PNG, or PDF; max size 10 MB

STEPS:
  1. RECEIVE image upload from multipart/form-data request.
     Validate file type and size. If invalid: return HTTP 400.

  2. PREPROCESS IMAGE (improves OCR accuracy):
     a. Convert to grayscale
     b. Apply Gaussian blur to reduce noise
     c. Binarize using adaptive threshold (Otsu's method)
     d. Deskew if rotation > 2 degrees
     e. Scale to 300 DPI if below resolution threshold

  3. RUN OCR ENGINE:
     - Primary: pytesseract (Tesseract v5) with eng+spa language models
     - If cloud OCR configured: delegate to cloud API (e.g., Google Vision)
     - Capture raw text string output

  4. APPLY EXTRACTION PATTERNS via regex:
     a. Supplier name  — line following keywords "SHIPPER:", "SUPPLIER:", "FROM:"
     b. Carrier name   — line following "CARRIER:", "TRUCKING:", "TRANSPORT:"
     c. BOL reference  — line following "BOL#", "BILL OF LADING NO.", "REFERENCE:"
                         or pattern: [A-Z]{2,4}-\d{4,10}
     d. Delivery date  — date patterns: MM/DD/YYYY, DD/MM/YYYY, YYYY-MM-DD
     e. Line items     — tabular rows containing:
                         (material description, quantity + unit, lot/batch number)
                         Parsed with column-alignment heuristics.

  5. BUILD STRUCTURED RESPONSE:
     {
       "supplier":       <extracted or null>,
       "carrier":        <extracted or null>,
       "bol_reference":  <extracted or null>,
       "delivery_date":  <extracted or null>,
       "items": [
         { "material_type": <string>, "quantity": <number or null>,
           "lot_batch_number": <string or null> }
       ],
       "confidence": <float 0.0–1.0 based on extraction completeness>
     }

  6. If zero fields extracted (confidence == 0.0):
     return HTTP 422 {
       "error": "Unable to extract data from the uploaded document.
                 Please try again with a clearer image or enter data manually."
     }
     (UC-001 E1)

  7. Return HTTP 200 with structured JSON.
     Client renders result in editable delivery form for clerk review (FR-003).

POST-CONDITIONS:
  - No database records created
  - Raw image is NOT persisted (privacy by default)
  - Total processing time target: ≤ 10 seconds (NFR-002)
```

---

## 5. Key Classes with Methods

The following table describes the ten primary backend model classes. These correspond directly to the database tables defined in Section 1. All classes are implemented as SQLAlchemy ORM models with Pydantic schemas for API serialization (NFR-021, NFR-022).

| Class | Key Methods |
|-------|-------------|
| `User` | `create(username, full_name, password, preferred_language, role_ids[])` — hashes password (NFR-005), inserts user record and role assignments, writes audit log; `authenticate(username, password)` — verifies bcrypt hash, issues JWT, writes LOGIN audit entry (FR-036, FR-039); `deactivate(user_id)` — sets status to `'inactive'`, checks last-admin guard (UC-009 E2), writes audit log (FR-038); `assignRole(user_id, role_id)` — inserts into `user_role_assignments`, writes ROLES_UPDATED audit log (FR-038) |
| `Role` | `getPrivileges(role_id)` — returns the static set of privilege strings for a role from the ROLE_PRIVILEGE_MAP constant (SRS Section 4.4.2); `hasPrivilege(role_id, privilege_id)` — returns boolean; used by RBAC middleware in Section 4.2 (FR-037) |
| `UserRoleAssignment` | `assign(user_id, role_id)` — inserts a row into `user_role_assignments` if not already present (SRS Section 4.4.3); `revoke(user_id, role_id)` — deletes the assignment row; both methods write USER_ROLES_UPDATED audit entries |
| `Delivery` | `create(supplier, carrier, bol_ref, items[])` — inserts delivery and all delivery_item rows within a single transaction (FR-001, FR-003); `confirm()` — triggers inventory item creation for each line item, updates `delivery_items.inventory_item_id`, writes DELIVERY_CONFIRMED audit log (FR-004); `search(filters)` — applies dynamic WHERE clauses for supplier/carrier/date/BOL filters (FR-005) |
| `DeliveryItem` | `linkToInventory(inventory_id)` — sets `delivery_items.inventory_item_id = inventory_id` after the corresponding `inventory_items` row is created during delivery confirmation (FR-004, FR-010); enables bidirectional traceability |
| `InventoryItem` | `adjustQuantity(delta, reason)` — Admin-only; adds delta (positive or negative) to `quantity_on_hand`, enforces non-negative constraint, writes INVENTORY_ADJUSTED audit log with old/new values (FR-012, NFR-009); `reserve(quantity)` — called during material allocation; decrements `quantity_on_hand` atomically within an open transaction (UC-004, FR-018); `traceByLot(lot_batch_number)` — queries delivery origin and work order usage for the lot (FR-010); `exportCSV(filters)` — streams inventory rows as CSV (UC-002 A1, FR-011) |
| `WorkOrder` | `create(product, qty, materials[], priority, target_date)` — inserts work_order and work_order_materials rows; validates material availability and returns sufficiency report (FR-013, FR-019); `allocateMaterials()` — executes the allocation algorithm in Section 4.1 (UC-004, FR-018); `assignLine(production_line)` — sets `work_orders.production_line`, validates line capacity (FR-015, UC-005); `advanceStatus(new_status)` — enforces valid lifecycle transitions and updates status (FR-016); `checkMaterialAvailability()` — read-only query summing available stock per required material (FR-019) |
| `WorkOrderMaterial` | `allocate(qty, lot_batch_number)` — updates `quantity_allocated` and records the lot source; called within the allocation transaction (FR-018); `getRemainingShortfall()` — returns `MAX(0, quantity_required - quantity_allocated)`, used to report partial allocation status (FR-019) |
| `AuditLog` | `record(user_id, action, entity_type, entity_id, details)` — inserts an immutable audit log row; called after every data-modifying operation throughout the system (FR-012, FR-039, NFR-009); `query(filters)` — returns paginated audit log rows filtered by user, action type, entity, or time range; accessible only to Admin (PRV-017) |
| `LowStockAlert` | `configure(material_type, threshold)` — upserts a threshold record in `low_stock_alerts` for the given material (FR-009, PRV-006); `evaluate(inventory_item)` — compares `inventory_item.quantity_on_hand` against the configured threshold and returns `True` if the alert is triggered; called after every inventory deduction (FR-009) |

---

## 6. Frontend Structure

The Next.js frontend is structured around module-specific routes. Each page is composed of reusable React components. The UI enforces role-based visibility on the frontend (NFR-007) in addition to the API-layer RBAC in Section 4.2. The interface is fully mobile-responsive (NFR-010) and supports English and Spanish via i18n translation files (LR-001 through LR-007).

| Route | Page Purpose | Components |
|-------|-------------|------------|
| `/login` | User authentication entry point (UC-011) | `AuthForm` — username/password form with submit, error display, and "invalid credentials" feedback (NFR-013, NFR-016) |
| `/dashboard` | Role-specific landing page after login; provides at-a-glance operational summary | `SummaryCard` — per-role stat cards (e.g., pending deliveries for Clerk, active work orders for Supervisor, low stock count for Admin); `AlertBanner` — displays triggered low-stock alerts (FR-009); `QuickActionBar` — role-appropriate shortcut links |
| `/receiving` | Delivery log and new delivery workflow (FR-001–FR-005) | `DeliveryList` — paginated, searchable table of all delivery records with filters for supplier, BOL, and date (FR-005); `NewDeliveryForm` — multi-line delivery entry form with per-item rows for material, quantity, lot, and location (FR-001); `OCRUploader` — image upload widget that calls `POST /deliveries/ocr`, displays extracted fields in editable overlay, and pre-populates `NewDeliveryForm` on accept (FR-002, FR-003) |
| `/inventory` | Inventory viewing, filtering, and traceability (FR-006–FR-012) | `InventoryTable` — paginated table of inventory items with column sort; shows low-stock badge when alert is triggered (FR-009); `FilterPanel` — sidebar filter controls: category toggle (raw/finished), material type search, lot number, location, date range (FR-011); `TraceabilityView` — modal or detail panel showing source delivery → current stock → consuming work orders for a given lot number (FR-010); `ExportButton` — triggers `GET /inventory/export` CSV download (UC-002 A1); `AdjustQuantityModal` — Admin-only inline form for manual quantity adjustment with required reason field (FR-012) |
| `/work-orders` | Work order list, creation, allocation, and scheduling (FR-013–FR-021) | `WorkOrderList` — paginated table grouped by status; Machine Operators see only their line's orders (FR-017, FR-021); `WorkOrderDetail` — full detail view with materials list, allocation status, status history, and action buttons (FR-016); `CreateWorkOrderForm` — Admin-only form for product, quantity, priority, target date, and material requirements (FR-013); `AllocateMaterialsModal` — confirms material allocation for a work order; shows availability per material (UC-004, FR-018); `PriorityReorder` — drag-and-drop list for Production Supervisor to set daily work order priority (UC-005, FR-017); `AssignLineDropdown` — production line assignment control (FR-015) |
| `/users` | User account management (FR-035–FR-039, UC-009) | `UserTable` — paginated list of users with name, role badges, and status indicator; `UserForm` — create or edit user: full name, username, password (create only), language preference, role multi-select, and active/inactive toggle (FR-038); `DeactivateConfirmDialog` — confirmation prompt before deactivation (NFR-012) |
| `/audit` | Audit log viewer (FR-012, NFR-009) | `AuditLogTable` — read-only, paginated log table with columns: timestamp, user, action, entity, details; supports filtering by user, action type, entity, and date range; Admin only (PRV-017) |

---

## 7. Role-Permission Matrix

This matrix maps the four roles defined in SRS Section 4.4.2 to every system feature and API endpoint. It is the authoritative reference for both frontend visibility control and backend RBAC enforcement (FR-037, NFR-007). A filled circle (●) indicates the role has access; an empty circle (○) indicates no access.

### 7.1 Feature-Level Matrix

| Feature / Privilege | Company Admin | Receiving Clerk | Production Supervisor | Machine Operator |
|---------------------|:-------------:|:---------------:|:---------------------:|:----------------:|
| **Authentication** | | | | |
| Login / Logout | ● | ● | ● | ● |
| Session auto-logout after 30 min (NFR-008) | ● | ● | ● | ● |
| **Receiving & Intake** | | | | |
| Create new delivery record (PRV-001, FR-001) | ● | ● | ○ | ○ |
| View delivery history / log (PRV-002, FR-005) | ● | ● | ○ | ○ |
| OCR scan bill of lading (PRV-003, FR-002) | ● | ● | ○ | ○ |
| **Inventory Management** | | | | |
| View inventory — raw materials (PRV-004, FR-006) | ● | ● | ● | ○ |
| View inventory — finished goods (PRV-004, FR-007) | ● | ● | ● | ○ |
| Filter & search inventory (PRV-004, FR-011) | ● | ● | ● | ○ |
| Export inventory to CSV (PRV-004, FR-011) | ● | ● | ● | ○ |
| Manual quantity adjustment (PRV-005, FR-008) | ● | ○ | ○ | ○ |
| Configure low-stock alerts (PRV-006, FR-009) | ● | ○ | ○ | ○ |
| View low-stock alerts (PRV-006, FR-009) | ● | ○ | ○ | ○ |
| Lot/batch traceability report (PRV-007, FR-010) | ● | ○ | ● | ○ |
| **Work Order Management** | | | | |
| Create work orders (PRV-008, FR-013) | ● | ○ | ○ | ○ |
| View work orders (PRV-009, FR-017) | ● | ○ | ● | ● (own line only) |
| Assign production line (PRV-010, FR-015) | ● | ○ | ● | ○ |
| Allocate materials (PRV-011, FR-018) | ● | ○ | ● | ○ |
| Update status / confirm completion (PRV-012, FR-016) | ● | ○ | ● | ○ |
| Prioritize / reorder work orders (PRV-012, FR-017) | ● | ○ | ● | ○ |
| **User Management** | | | | |
| View all user accounts (PRV-015, FR-038) | ● | ○ | ○ | ○ |
| Create user accounts (PRV-015, FR-038) | ● | ○ | ○ | ○ |
| Edit user accounts (PRV-015, FR-038) | ● | ○ | ○ | ○ |
| Deactivate user accounts (PRV-015, FR-038) | ● | ○ | ○ | ○ |
| Assign / revoke roles (PRV-015, FR-038) | ● | ○ | ○ | ○ |
| **Audit & Reporting** | | | | |
| View system audit logs (PRV-017, FR-012) | ● | ○ | ○ | ○ |

---

### 7.2 API Endpoint-Level Matrix

| Endpoint | Company Admin | Receiving Clerk | Production Supervisor | Machine Operator |
|----------|:-------------:|:---------------:|:---------------------:|:----------------:|
| `POST /auth/login` | ● | ● | ● | ● |
| `POST /auth/logout` | ● | ● | ● | ● |
| `POST /deliveries` | ● | ● | ○ | ○ |
| `POST /deliveries/ocr` | ● | ● | ○ | ○ |
| `GET /deliveries` | ● | ● | ○ | ○ |
| `GET /inventory` | ● | ● | ● | ○ |
| `PATCH /inventory/{id}` | ● | ○ | ○ | ○ |
| `GET /inventory/trace/{lot}` | ● | ○ | ● | ○ |
| `GET /inventory/alerts` | ● | ○ | ○ | ○ |
| `POST /inventory/alerts` | ● | ○ | ○ | ○ |
| `GET /inventory/export` | ● | ● | ● | ○ |
| `POST /work-orders` | ● | ○ | ○ | ○ |
| `GET /work-orders` | ● | ○ | ● | ● (filtered) |
| `PATCH /work-orders/{id}/allocate` | ● | ○ | ● | ○ |
| `PATCH /work-orders/{id}/assign` | ● | ○ | ● | ○ |
| `PATCH /work-orders/{id}/status` | ● | ○ | ● | ○ |
| `GET /work-orders/{id}` | ● | ○ | ● | ● (own line only) |
| `GET /users` | ● | ○ | ○ | ○ |
| `POST /users` | ● | ○ | ○ | ○ |
| `PATCH /users/{id}` | ● | ○ | ○ | ○ |
| `POST /users/{id}/roles` | ● | ○ | ○ | ○ |

---

### 7.3 Multi-Role Union Behavior (SRS Section 4.4.3)

When a user is assigned multiple roles, their effective privilege set is the **union** of all privileges from each role. No privilege is reduced by holding multiple roles. Examples:

| User's Assigned Roles | Effective Privileges |
|----------------------|---------------------|
| `receiving_clerk` + `production_supervisor` | PRV-001, PRV-002, PRV-003, PRV-004, PRV-007, PRV-009, PRV-010, PRV-011, PRV-012 |
| `production_supervisor` + `machine_operator` | PRV-004, PRV-007, PRV-009, PRV-010, PRV-011, PRV-012 (machine_operator adds no new privileges beyond those of supervisor) |
| `company_admin` + any other role | All PRV-001 through PRV-017 (admin is a superset of all roles) |

---

*End of Low-Level Design Document*
*MES LLD v1.0 — All design decisions trace to SRS v2.1 functional requirements (FR-001–FR-039), non-functional requirements (NFR-001–NFR-023), and use cases (UC-001–UC-011).*
