# Plan — ACR-33: Shipment invoice generation + Transfer/Direct source

**Ticket:** [ACR-33](https://linear.app/chronos-laboral/issue/ACR-33) (High) — *Shipment: invoice
generation + Transfer/Direct source (folded from ACR-24)*
**Branch:** `ticket-33/shipment-invoice-transfer-direct-source`
**Blocked by:** ACR-23 (Inventory Ledger redesign) — **Done** ✅
**Refs:** `acra_docs/reference/client_domain_model.md` §4.1–§4.3 · `reference/target_schema.md` §4 ·
supersedes ACR-24

---

## 1. Current state

### Backend — the shipment module already exists end to end

| Layer | File | What is there today |
|---|---|---|
| Model | `backend/app/models/shipment.py:7` | `Shipment(contact_id, carrier_id, bol_number, shipment_date, notes, type, created_by, created_at)` + `ShipmentItem(shipment_id, lot_id, quantity)` |
| Constraint | `backend/app/models/shipment.py:21` | `ck_shipments_type`: `type IN ('customer_order', 'transfer_out')` |
| Migration | `backend/alembic/versions/008_shipments.py:17` | creates both tables + 4 indexes; reversible |
| Schema | `backend/app/schemas/shipment.py:23` | `ShipmentCreate` / `ShipmentResponse` / `ShipmentListResponse` |
| Service | `backend/app/services/shipment_service.py:88` | `create_shipment` validates lots exist + sufficient stock, decrements `lot.quantity_on_hand`, flips lot → `shipped` at zero, writes an `InventoryTransaction(transaction_type="ship", quantity=-qty)`, audits `shipment.created` |
| Router | `backend/app/routers/shipments.py:15` | `POST ""`, `GET ""`, `GET "/{id}"` behind `shipping.create` / `shipping.view` |
| Tests | `backend/tests/test_shipments.py` | 9 tests, no live DB, `_make_rbac_session(privileges=("shipping.view","shipping.create"))` |

### Frontend

- `frontend/app/[locale]/shipping/page.tsx` → `ShippingView`.
- `frontend/src/components/shipping/ShippingView.tsx:89` — list table, create dialog (BOL, date,
  client, carrier, type, notes, lot lines), detail dialog. Uses `toStore`/`toDisplay` (×100).
- `frontend/messages/{en,es}.json` → `shipping.*` keys exist.
- **No Jest test file exists for `ShippingView`** — it is the only feature module without one.
- `frontend/e2e/ticket-19.spec.ts` + `frontend/playwright.config.ts` are the e2e pattern to copy.

### The three real gaps vs. acceptance criteria

1. **Vocabulary is not the domain model's.** DB says `customer_order | transfer_out`; §4.3 says
   **Transfer** vs **Direct Customer** delivery notes.
2. **No `source` field.** `target_schema.md:227` assigns `shipments.source` explicitly to **ACR-33**.
3. **No invoice anywhere.** `grep -ri invoice acra_docs/reference/` → *zero hits*. Invoice is
   ACR-24's carried-forward intent with no domain spec behind it (see §6, Decisions).

### Already satisfied — do not rebuild

> *"Both generate Issue movements against the ledger"*

`shipment_service.py:140` already writes the negative `InventoryTransaction`, which **is** master's
ledger today: `app/models/stock_movement.py:1` is an explicit *skeleton* (`StockState` /
`MovementType` enums only, no table) and `009_stock_movement_ledger_placeholder.py` is a deliberate
no-op — the real `stock_movements` table lands in Sprint II. So this criterion is met by existing
code; ACR-33 **asserts** it in tests rather than reimplementing it.

---

## 2. Change list

### CREATE

| File | Purpose |
|---|---|
| `backend/alembic/versions/010_shipment_invoices.py` | rename type vocabulary (+data migration), add `shipments.source`, add `shipment_items.unit_price`, create `invoices` + `invoice_lines`, grant `shipping.*` to `company_admin`. `down_revision="009"`. Reversible. |
| `backend/app/models/invoice.py` | `Invoice` + `InvoiceLine` ORM |
| `backend/app/schemas/invoice.py` | `InvoiceResponse`, `InvoiceLineResponse` |
| `backend/app/services/invoice_service.py` | `generate_invoice(shipment_id, …)`, `get_invoice_for_shipment(…)` |
| `backend/app/routers/invoices.py` | `POST /shipments/{id}/invoice`, `GET /shipments/{id}/invoice` |
| `backend/tests/test_invoices.py` | invoice service + router tests |
| `frontend/src/components/shipping/__tests__/Shipping.test.tsx` | first Jest coverage for `ShippingView` |
| `frontend/e2e/ticket-33.spec.ts` | e2e: create direct-customer shipment w/ source → generate invoice |

### MODIFY

| File | Change |
|---|---|
| `backend/app/models/shipment.py` | `type` check → `('transfer','direct_customer')`; add `source`; add `ShipmentItem.unit_price`; add `ck_shipments_source_direct_only` |
| `backend/app/schemas/shipment.py` | `type` as `Literal["transfer","direct_customer"]` default `direct_customer`; `source: Optional[str]`; `ShipmentItemCreate.unit_price: Optional[int]`; echo both on responses |
| `backend/app/services/shipment_service.py` | persist `source` + `unit_price`; reject `source` on a `transfer` (422); include both in the response mapper |
| `backend/app/main.py` | `include_router(invoices.router)` |
| `backend/app/models/__init__.py` | export `Invoice`, `InvoiceLine` |
| `backend/tests/test_shipments.py` | update fixtures to the new vocabulary; add `source` + `unit_price` cases |
| `frontend/src/components/shipping/ShippingView.tsx` | type select → Transfer / Direct Customer; conditional `source` input; per-line unit price; invoice button + panel in the detail dialog |
| `frontend/src/lib/privileges.ts` | (no change — `SHIPPING_VIEW` / `SHIPPING_CREATE` already exist) |
| `frontend/src/components/layout/NavSidebar.tsx:31` | uncomment the Shipping nav item, fix its privilege to `PRIVILEGES.SHIPPING_VIEW` |
| `frontend/messages/en.json`, `es.json` | `shipping.transfer`, `shipping.directCustomer`, `shipping.source`, `shipping.unitPrice`, `shipping.invoice*` keys |
| `CHANGELOG.md` | entry |

---

## 3. Data / API

### 3.1 Migration `010_shipment_invoices` (reversible, `down_revision="009"`)

```sql
-- 1. vocabulary (data-preserving)
UPDATE shipments SET type='direct_customer' WHERE type='customer_order';
UPDATE shipments SET type='transfer'        WHERE type='transfer_out';
-- drop ck_shipments_type; recreate as type IN ('transfer','direct_customer')

-- 2. §4.3 source
ALTER TABLE shipments ADD COLUMN source VARCHAR(50) NULL;
-- ck_shipments_source_direct_only: source IS NULL OR type = 'direct_customer'

-- 3. price snapshot
ALTER TABLE shipment_items ADD COLUMN unit_price INTEGER NULL;  -- ×100
-- ck_shipment_items_unit_price: unit_price IS NULL OR unit_price >= 0
```

```
invoices(
  id PK, shipment_id FK→shipments UNIQUE NOT NULL,
  invoice_number VARCHAR(50) UNIQUE NOT NULL,
  invoice_date VARCHAR(20) NOT NULL,
  currency VARCHAR(3) NOT NULL DEFAULT 'USD',
  subtotal_amount INTEGER NOT NULL,   -- ×100
  tax_amount      INTEGER NOT NULL DEFAULT 0,
  total_amount    INTEGER NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'issued',   -- issued | void
  created_by FK→users, created_at TIMESTAMPTZ
)
invoice_lines(
  id PK, invoice_id FK→invoices ON DELETE CASCADE,
  shipment_item_id FK→shipment_items,
  description VARCHAR(300), quantity INTEGER, unit_price INTEGER, line_total INTEGER
)
```

Plus the ACR-35 unblock (see §6 D5):

```sql
INSERT INTO role_privilege_assignments (role_id, privilege_name)
SELECT r.id, v.p FROM roles r CROSS JOIN (VALUES ('shipping.view'),('shipping.create')) v(p)
WHERE r.role_name = 'company_admin'
ON CONFLICT DO NOTHING;
```

`downgrade()` reverses every step, mapping the vocabulary back.

### 3.2 Endpoints

| Method | Path | Privilege | Behavior |
|---|---|---|---|
| `POST` | `/api/v1/shipments/{id}/invoice` | `shipping.create` | 201 + `InvoiceResponse`; 404 unknown shipment; **409** if one already exists |
| `GET` | `/api/v1/shipments/{id}/invoice` | `shipping.view` | 200 + `InvoiceResponse`; 404 if none |

`POST /api/v1/shipments` gains `source` and per-item `unit_price`; **422** when `source` is set on a
`transfer`, and when `type` is outside the two values (Pydantic `Literal`).

**Invoice number:** `INV-{year of shipment_date}-{shipment_id:05d}` — deterministic from the
shipment, so there is no sequence to race on (contrast ACR-30's optimistic-version problem). The
`UNIQUE` constraint is the backstop.

**Totals:** `line_total = quantity × unit_price / 100` (both ×100 → divide once to stay ×100);
`subtotal = Σ line_total`; `tax_amount = 0`; `total = subtotal + tax`. Lines with a null
`unit_price` contribute 0.

---

## 4. Test plan

### Backend — `tests/test_invoices.py` (new)

| # | Case | Expect |
|---|---|---|
| 1 | `POST /shipments/{id}/invoice` happy path | 201, `invoice_number == INV-2026-00001`, totals correct |
| 2 | ...with mixed null/priced lines | null line contributes 0 to subtotal |
| 3 | ...shipment not found | 404 |
| 4 | ...invoice already exists | 409 |
| 5 | **RBAC** — token without `shipping.create` | **403** |
| 6 | `GET .../invoice` happy path | 200, lines echo `shipment_item_id` |
| 7 | `GET .../invoice` when none | 404 |
| 8 | **RBAC** — `GET` without `shipping.view` | **403** |
| 9 | no auth header | 401/403 |
| 10 | rounding: `quantity=333, unit_price=333` | exact integer arithmetic, no float drift |

### Backend — `tests/test_shipments.py` (extend)

| # | Case | Expect |
|---|---|---|
| 11 | create `direct_customer` with `source="SC"` | 201, `source` echoed |
| 12 | create `transfer` with `source` set | **422** |
| 13 | create with `type="customer_order"` (retired value) | **422** |
| 14 | create with negative `unit_price` | **422** |
| 15 | ledger assertion — an `InventoryTransaction(type="ship", qty=-n)` is written per line | passes for *both* shipment types |

Existing 9 tests updated to the new vocabulary. All use `_make_rbac_session` /
`_make_session` from `tests/conftest.py` (3-query RBAC sequence), no live DB.

**Coverage gate:** `pytest --cov=app.services.invoice_service --cov=app.routers.invoices
--cov=app.services.shipment_service --cov-report=term-missing` ≥ 85%.

### Frontend — `Shipping.test.tsx` (new)

Loading skeleton · error alert · empty state · rows render · type badge shows
"Transfer"/"Direct Customer" · `source` input appears only for Direct Customer · submit with zero
valid lines shows the inline `Alert` · invoice button renders in the detail dialog.

### e2e — `frontend/e2e/ticket-33.spec.ts`

Login as admin → Shipping (nav link now visible) → New Shipment → Direct Customer + `source=SC` +
one priced lot line → submit → row appears → open detail → Generate Invoice → invoice number +
total render → reload → invoice persists. Run against `npm run build && npm run start`, **never
`next dev`** (KI-02).

---

## 5. Live verification (browser)

1. `/en/shipping` — Shipping link present in the sidebar (it is commented out today).
2. Create **Direct Customer** shipment: `source` field visible, accepts `SC`.
3. Switch the type select to **Transfer**: `source` field disappears / clears.
4. Empty submit, whitespace-only BOL, over-length BOL (>100), quantity `0`, `-5`, non-numeric,
   quantity above lot on-hand → each rejected with a visible `Alert`, no 500 in the network panel.
5. Double-click submit → exactly one shipment created.
6. Generate invoice → panel shows number + total; press Generate again → 409 surfaced as a message,
   not a crash.
7. Browser refresh mid-dialog; cancel/back paths.
8. Log in as `receiving_clerk` (no `shipping.*`) → Shipping nav hidden **and** `/en/shipping`
   blocked, and `POST /shipments/{id}/invoice` returns 403 when called directly.
9. `/es/shipping` — all new labels translated; light + dark theme.
10. Console + network clean throughout.

---

## 6. Decisions taken (no domain spec existed — recorded here and in the PR)

- **D1 — Rename the vocabulary rather than adding to it.** `customer_order → direct_customer`,
  `transfer_out → transfer`, with a data migration. Keeping both spellings would leave two names for
  one concept, which is exactly the drift ACR-26 is cleaning up.
- **D2 — `source` is nullable and legal only on `direct_customer`.** §4.3 phrases it as "*if* it
  ships from San Cayetano's stock", so it is optional, not required. Enforced by CHECK + a 422.
- **D3 — Prices are snapshotted on the shipment line, not looked up.** `products` has **no** price
  column (`models/product.py:7`) and none is planned in `target_schema.md`. Capturing `unit_price`
  at ship time is standard invoicing practice and is correct regardless of where a catalogue price
  eventually lives. No `products` change — that table is contested by migration `011`/Q4.
- **D4 — `tax_amount` column exists but is always 0.** No tax model exists anywhere in the domain
  docs. The column keeps the shape right without inventing tax rules.
- **D5 — Grant `shipping.view`/`shipping.create` to `company_admin` in this migration.** They are
  granted to *no* role today (`002_role_privilege_assignments.py:44` has no `shipping.*` rows), so
  every shipment endpoint 403s and the feature is unverifiable. This is a one-role slice of
  **ACR-35**, which keeps the wider role matrix (`forklift_operator`, worksheet privileges). Noted
  in the PR so ACR-35 does not redo it.
- **D6 — Do not touch `contacts.type`.** `target_schema.md:226` assigns the `"transfer"` contact
  type to migration `011`/ACR-26, which is **In Progress**. The Transfer partner dropdown keeps
  querying `type=client` and will pick up `transfer` contacts once ACR-26 lands.
- **D7 — Both shipment types can be invoiced.** A transfer to a partner entity is still an invoiced
  movement; blocking it would be an unforced assumption.
- **D8 — Invoices are immutable once generated.** No edit/delete endpoint; `status` carries `void`
  for a future ticket. Second `POST` → 409.

## 7. Risks

- **⚠️ Migration slot `010` is contested three ways.** This branch is cut from `origin/master`
  (`9f72293`), whose migration head is `009` — so `010` with `down_revision="009"` is correct *here*.
  But **local** `master` (`2f17de7`, unpushed) already carries ACR-30's `010_production_worksheets`,
  and the in-flight ACR-27 worktrees carry a third `010_stock_reservations`. Whichever branch merges
  second renumbers — a two-line change (`revision` + `down_revision`). **Flag prominently in the PR
  body.** `target_schema.md` additionally promises an `011` for ACR-26's Q4/D-07 cleanup.
- **Vocabulary rename is a breaking API change** for any client sending `customer_order`. Only
  `ShippingView` and the backend tests send it today; both are updated in this branch.
- `GET /contacts` requires `master_data.view` **or** `deliveries.create`
  (`routers/contacts.py:21`) — a shipping-only user cannot populate the client/carrier dropdowns.
  Out of scope here (it is an ACR-35 role-matrix question); `company_admin` has `master_data.view`,
  so live verification is unaffected. Note it in the report.
- Postgres port: `CLAUDE.md` documents 5433 but that port is often squatted; check the live port and
  export `DATABASE_URL` to match reality.

## 8. Build order

1. Migration `010` + `models/shipment.py` + `models/invoice.py` → `alembic upgrade head`.
2. Schemas (`shipment.py`, `invoice.py`) with the `Literal` type + source validation.
3. `shipment_service` — persist `source`/`unit_price`, 422 rule. **Tests for it immediately.**
4. `invoice_service` + `routers/invoices.py` + `main.py` wiring. **Tests immediately.**
5. Update `tests/test_shipments.py` to the new vocabulary; run the coverage gate.
6. `ShippingView.tsx` — type select, conditional source, unit price, invoice panel + i18n.
7. `NavSidebar.tsx` — surface Shipping.
8. `Shipping.test.tsx` Jest; `npx jest`, `npm run lint`, `npm run build`.
9. `e2e/ticket-33.spec.ts` against a production build; live browser sweep (§5).
10. `./scripts/smoke-test.sh`, CHANGELOG, draft PR.
