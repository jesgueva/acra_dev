# Plan — ACR-39: Unified DeliveryNote document model

**Ticket:** [ACR-39](https://linear.app/chronos-laboral/issue/ACR-39) · High · `blockedBy: []`
**Branch:** `ticket-39/unified-delivery-note-model`
**Refs:** `acra_docs/reference/client_domain_model.md` §4.1–§4.3 · `acra_docs/reference/target_schema.md` §4, §6

---

## 0. Headline finding — the acceptance criterion is not fully reachable

The ticket's acceptance reads: *"Every `StockMovement` has a non-null `delivery_note_id`."*

**`stock_movements` does not exist.** `backend/app/models/stock_movement.py:1-34` is enums only —
`StockState` and `MovementType`, explicitly "not mapped to a table or registered with Alembic yet".
Its migration slot `009_stock_movement_ledger_placeholder.py:20-22` is a documented no-op.
`target_schema.md:12-15` confirms: ACR-23 delivered the skeleton; the real ledger table belongs to an
**unticketed** "ledger migration" (`target_schema.md:146`).

So the FK constraint half of ACR-39 has nothing to attach to. What ACR-39 *can* deliver — and what
ACR-31 actually needs from it — is the **document model itself**: the `delivery_notes` table, the
INTERNAL note generator, and existing inbound/outbound documents resolving to notes of the correct
type. The `stock_movements.delivery_note_id NOT NULL` column is then a three-line addition inside the
ledger migration, which ACR-39 makes possible on day one instead of retrofitting.

**Proposed scope:** everything in §4.1/§4.2/§4.3 except the movement FK. Revised acceptance in §7.

---

## 1. Current state

### Two unrelated document tables, no shared abstraction

| Concern | Inbound | Outbound |
|---|---|---|
| Header | `Delivery` — `backend/app/models/delivery.py:7-17` | `Shipment` — `backend/app/models/shipment.py:7-25` |
| Document number | `bol_reference` `String(100)` :14 | `bol_number` `String(100)` :13 |
| Document date | `delivery_date` `String(20)` :13 | `shipment_date` `String(20)` :14 |
| Partner | `contact_id` → contacts :11 | `contact_id` → contacts :11 |
| Carrier | `carrier_id` :12 | `carrier_id` :12 |
| Kind | *(implicit — always inbound)* | `type` + CHECK `customer_order\|transfer_out` :16-24 |
| Provenance (`uploaded`) | — | — |
| `source` (§4.3) | — | — |
| Lines | `DeliveryItem` :20-31 (pallet math + OCR) | `ShipmentItem` :28-40 (lot + qty) |

Both carry the same six document facts under different names. Neither models a **system-generated
internal** note, which is the case ACR-31 hits when a worksheet approval writes Issue/Receipt movements.

### Where documents are written today
- Inbound: `services/delivery_service.py:90-98` builds the `Delivery`; duplicate-BOL guard at :57-66;
  per-lot `InventoryTransaction(type="receive")` at :154-162.
- Outbound: `services/shipment_service.py:113-123` builds the `Shipment`; `InventoryTransaction(type="ship")`
  at :140-147.
- Neither writes anything resembling a delivery note.

### Contacts
`models/contact.py:12` — `type` is a bare `String(20)`. **No CHECK constraint exists** (verified across
`005_contacts_products.py:18-22`; the only `type IN (...)` constraints in the tree are
`008_shipments.py:39` and `007_inventory_ledger.py:99`). Adding `"transfer"` per `target_schema.md:60`
is therefore a **data + UI change only — no constraint migration needed.**
Frontend enumerates the literals at `master-data/ContactsView.tsx:185` (and badge map :62-64).

### Migration chain — contested
`backend/alembic/versions/` on `master` ends at `009`. Slot `010` is **claimed twice** by unmerged work:

| File | Branch | Ticket |
|---|---|---|
| `010_stock_reservations.py` | `ticket-27/reservations`, `ticket-27/stock-reservations` | ACR-27 |
| `010_production_worksheets.py` | `ticket-30/concurrency-safe-worksheet-close-spike` | ACR-30 |

`target_schema.md:19-23` further records that `010` (reservations) **is already applied to the shared
local database**, so `alembic upgrade head` fails on any branch lacking that file.
→ **Operational consequence:** this ticket must build against a **fresh dedicated database**, not the
shared one. See §6.

### RBAC
`shipping.create` / `shipping.view` are used by `routers/shipments.py:18,31,47` but granted to **no role**
in `002_role_privilege_assignments.py` (grep shows no `shipping.*` entry) — the known ISS-04/KI-08 gap
owned by **ACR-35**. The Shipping nav link is correspondingly commented out at
`components/layout/NavSidebar.tsx:31`. **ACR-39 does not fix this** — it would collide with ACR-35.
New note endpoints therefore reuse existing, already-granted privileges (§3.4).

### Closest pattern to imitate
`contacts` / `products` (migration `005`, `models/contact.py`, `routers/contacts.py`,
`services/contact_service.py`, `tests/test_contacts.py`) — a small master-data table with
router→service layering, `require_privilege`, and audit writes. `delivery_notes` mirrors it.

---

## 2. Design decision — the ticket's open question #1

> *Do `deliveries` and `shipments` **become** delivery notes, or does `DeliveryNote` sit above them as a
> document layer they reference?*

**Decision (approved 2026-07-23): a document layer that owns document identity (option 2, hardened),
with the duplicated columns dropped from the children.** Scope confirmed at the same time: the
movement FK is deferred to the ledger migration (§0, §7).

Collapsing the tables (option 1) is not viable in one ticket: `DeliveryItem` carries pallet math and the
OCR transcription path that `target_schema.md:247-250` explicitly freezes ("the most likely way to
misread D-02"), while `ShipmentItem` is lot-keyed. The two line shapes are genuinely different documents,
and merging them would rewrite both shipped operator flows while ACR-26/27/30 are all in flight.

The ticket's stated objection to option 2 — *"risks two sources of truth"* — is real but avoidable, and
avoiding it is what makes this plan more than an additive FK:

- `delivery_notes` becomes **authoritative** for the six shared document facts (type, partner,
  document_number, document_date, uploaded, source).
- `deliveries` and `shipments` each get `delivery_note_id` — **UNIQUE, NOT NULL** after backfill (1:1).
- The now-duplicated columns are **migrated onto the note and dropped from the children** in the same
  reversible migration. One fact, one column, one table.
- Children keep only what is genuinely channel-specific: `deliveries.carrier_id` + its items;
  `shipments.carrier_id` + its lot items.

This is option 1's single-source-of-truth guarantee at option 2's blast radius.

**Open questions #2 and #3 — resolved here, no sign-off needed:**

- **#2 Human-readable number for INTERNAL notes → yes, auto-generated.** Format `INT-{YYYYMMDD}-{seq:04d}`
  (e.g. `INT-20260723-0007`), unique per day. Operators cite documents on the floor and the audit trail
  reads as nonsense with bare IDs. Cost is one helper function.
- **#3 `source` lands here, not on `shipments`.** `target_schema.md:227` currently assigns
  `shipments.source` to ACR-33, but §4.3 of the domain model describes `source` as a property of the
  *Delivery Note*, and putting it on the note is what stops it landing twice. **ACR-33 consumes
  `delivery_notes.source`** and does not add its own column. Requires a comment on ACR-33 + a
  `target_schema.md` correction (§5 below).

---

## 3. Data / API

### 3.1 New model — `backend/app/models/delivery_note.py`

```python
class DeliveryNoteType(str, Enum):
    INBOUND         = "inbound"
    TRANSFER        = "transfer"
    DIRECT_CUSTOMER = "direct_customer"
    INTERNAL        = "internal"

class DeliveryNote(Base):
    __tablename__ = "delivery_notes"
    id, type, source, partner_id → contacts.id (nullable — INTERNAL has none),
    document_number (String(100), NOT NULL), document_date (String(20), NOT NULL),
    uploaded (Boolean, NOT NULL, default False), notes (Text),
    created_by → users.id, created_at
    CheckConstraint("type IN ('inbound','transfer','direct_customer','internal')", name="ck_delivery_notes_type")
    UniqueConstraint("type", "document_number", name="uq_delivery_notes_type_document_number")
```

`document_date` stays `String(20)` to match `Delivery.delivery_date:13` / `Shipment.shipment_date:14`
rather than introducing a third date convention in one ticket.

### 3.2 Migration `011_delivery_notes.py` (`down_revision = "009"`)

**Numbering:** `010` is double-claimed (§1); `target_schema.md:17` earmarks `011` for the unticketed ledger
migration. ACR-39 is real work landing now, so it takes `011` and the ledger takes the next free slot —
recorded in `target_schema.md` as part of this ticket. `down_revision = "009"` because `master` head is
`009`; whichever of the contested branches merges second re-points its own `down_revision` (the standing
manual-resolution convention in `CLAUDE.md` → *Merge Notes*).

Upgrade, reversible throughout:
1. Create `delivery_notes` + indexes on `partner_id`, `document_date`, `type`.
2. Add nullable `delivery_note_id` to `deliveries` and `shipments`.
3. **Backfill inbound** — one `INBOUND` note per `deliveries` row: `document_number ← bol_reference`,
   `document_date ← delivery_date`, `partner_id ← contact_id`, `uploaded ← true` (§4.2: goods arrived with
   a paper document), `created_by ← created_by`.
4. **Backfill outbound** — one note per `shipments` row, mapping the existing CHECK values:
   `type = 'transfer'` where `shipments.type = 'transfer_out'`, else `'direct_customer'`;
   `document_number ← bol_number`, `document_date ← shipment_date`, `partner_id ← contact_id`,
   `uploaded ← false` (system-generated).
5. Set both `delivery_note_id` columns `NOT NULL` + `UNIQUE`.
6. Drop the migrated columns: `deliveries.bol_reference`, `deliveries.delivery_date`,
   `deliveries.contact_id`; `shipments.bol_number`, `shipments.shipment_date`, `shipments.contact_id`,
   `shipments.type` (and `ck_shipments_type`).

Downgrade re-adds the columns, copies values back from the notes, drops `delivery_notes`.

> **Backfill collision risk:** `uq_delivery_notes_type_document_number` can trip if seed/live data holds a
> duplicate BOL — `delivery_service.py:57-66` permits duplicates via `force=true`. The migration must
> de-duplicate by suffixing (` (2)`, ` (3)`) rather than aborting. Covered by a test in §4.

### 3.3 Service — `backend/app/services/delivery_note_service.py`

- `create_note(...)` — validated creation.
- `generate_internal_note(db, *, user_id, reason)` → `DeliveryNote` with `type=INTERNAL`, `uploaded=False`,
  `partner_id=None`, auto `document_number` via `_next_internal_number(db)`. **This is the function ACR-31
  calls**; it takes an open session and does not commit (matching `write_audit`'s caller-commits contract,
  `core/audit.py`).
- `list_notes(...)` / `get_note(...)` — filter by `type`, `partner_id`, date range; paginated in the shape
  of `list_shipments` (`shipment_service.py:170-227`).

`delivery_service.create_delivery` and `shipment_service.create_shipment` are refactored to create their
note first and hang the header off it.

### 3.4 Endpoints — `backend/app/routers/delivery_notes.py` (prefix `/api/v1/delivery-notes`)

| Method | Path | Privilege | Notes |
|---|---|---|---|
| `GET` | `` | `require_any_privilege("deliveries.view", "shipping.view")` | paginated list, filters |
| `GET` | `/{id}` | `require_any_privilege("deliveries.view", "shipping.view")` | detail |

**No POST.** Notes are created as a side effect of receiving, shipping, and (later) worksheet approval —
a bare create endpoint would let a note exist with no movement behind it, inverting §4.1. This also keeps
ACR-39 clear of the ungranted `shipping.*` privileges owned by ACR-35: `deliveries.view` is already
granted in `002`, so the read endpoints are reachable today.

Register in `app/main.py` (expect a merge conflict here — `CLAUDE.md` → *Merge Notes*).

### 3.5 Contacts — `"transfer"` type
Add to the frontend literal set (`ContactsView.tsx:185` + badge map :62-64) and `messages/en.json` /
`es.json`. No migration (no CHECK constraint exists). `ShippingView.tsx:124` continues to request
`type: "client"`; a follow-up in ACR-33 decides whether transfer partners appear in that picker — out of
scope here.

### 3.6 Frontend
- `frontend/src/components/shipping/ShippingView.tsx` — read `document_number` / `document_date` / note
  `type` off the nested note in the shipment response instead of the dropped flat columns.
- `frontend/src/components/receiving/DeliveryList.tsx`, `NewDeliveryForm.tsx`, `ReceivingView.tsx` — same
  swap for `bol_reference` / `delivery_date`.
- **New** `frontend/src/components/delivery-notes/DeliveryNotesView.tsx` — read-only table of all notes
  (type badge, document number, partner, date, uploaded/system chip), the surface that makes §4.1 visible.
  Route `frontend/app/[locale]/delivery-notes/page.tsx`; nav entry in `NavSidebar.tsx` gated on
  `PRIVILEGES.RECEIVING_VIEW` (already granted — deliberately *not* `SHIPPING_VIEW`, per §3.4).
- `PageHeader`, shadcn `Table`/`Badge`/`Skeleton`/`Select` only; links locale-prefixed via `useLocale()`.

---

## 4. Test plan

### Backend (`tests/test_delivery_notes.py` — new)
Use `_make_session` / `_make_user` / `_override` from `tests/conftest.py:7-64` (RBAC = exactly 3 queries;
service queries start at index 3).
- `GET /delivery-notes` 200 + pagination shape; filter by `type`, by `partner_id`, by date range.
- `GET /delivery-notes/{id}` 200; unknown id → 404.
- **RBAC 403** on both endpoints for a user holding neither `deliveries.view` nor `shipping.view`.
- `generate_internal_note` — sets `type=internal`, `uploaded=False`, `partner_id=None`; `document_number`
  matches `INT-\d{8}-\d{4}`; two calls in one day yield distinct, incrementing numbers.
- Validation: unknown `type` rejected; blank `document_number` rejected; duplicate `(type, document_number)`
  → 409.

### Backend (existing files — updated, not replaced)
- `tests/test_deliveries.py` — creating a delivery now also creates exactly one `INBOUND` note with
  `uploaded=True`; the delivery links to it; duplicate-BOL `force=true` path still works and yields a
  de-duplicated `document_number`.
- `tests/test_shipments.py` — `transfer_out` → `TRANSFER` note, default → `DIRECT_CUSTOMER` note,
  `uploaded=False`; `source` round-trips on a direct-customer note.
- `tests/test_schema.py` / `tests/test_models_schemas.py` — new model + dropped columns.

### Migration test (`tests/integration/`)
Seed 2 deliveries (one a forced duplicate BOL) + 2 shipments (one of each type) at `009`, run
`upgrade head`, assert: 4 notes with correct types/`uploaded` flags, both FKs NOT NULL, duplicate BOL
de-duplicated. Then `downgrade` and assert the original columns and values return.

### Frontend (Jest)
`DeliveryNotesView.test.tsx` — loading skeleton, populated table, empty state, type-filter change refetches,
error alert. Updated assertions in the receiving/shipping component tests for the renamed fields.

### Coverage
`pytest --cov=app.models.delivery_note --cov=app.services.delivery_note_service --cov=app.routers.delivery_notes --cov-report=term-missing`, ≥85%.

---

## 5. Doc + Linear follow-ups (part of this ticket)
- `acra_docs/reference/target_schema.md` — §3 row for `delivery_notes` moves from "LATER / not yet ticketed"
  to ACR-39; §4 row for `shipments.source` re-pointed to `delivery_notes.source`; §6 gap #1 closed;
  the `011` earmark in §1.2/§3 re-pointed to the next free slot.
- Comment on **ACR-33** that `source` now lives on the note (its plan must not add `shipments.source`).
- Comment on **ACR-31** that `generate_internal_note()` is the function to call on worksheet approval.

---

## 6. Live verification
Against a **fresh dedicated database** (`acra_acr39` — *not* the shared one, which is pinned at the
contested `010`; see §1), `alembic upgrade head`, seeded, backend on 8000, frontend `npm run build && npm run start`:

1. `/en/receiving` → create a delivery → `/en/delivery-notes` shows a new **INBOUND** note, uploaded chip,
   matching document number and partner.
2. Repeat with a duplicate BOL + force → second note appears with a de-duplicated number, no 500.
3. `/en/master-data/contacts` → create a contact of type **transfer** → it renders with its own badge.
4. `/en/shipping` → create a `transfer_out` shipment → **TRANSFER** note; create a customer order →
   **DIRECT_CUSTOMER** note with `source` populated.
5. Filter the notes table by each type and by date range; check the empty state.
6. A user without `deliveries.view`/`shipping.view` gets **403** from `/api/v1/delivery-notes` directly —
   not merely a hidden nav link.
7. `/es/delivery-notes` — labels and date formats localize; both themes.
8. Console and network clean throughout — no unhandled errors, no 500s.

---

## 7. Revised acceptance
- [ ] `delivery_notes` exists with all four types and the `uploaded` provenance flag.
- [ ] Every `deliveries` and `shipments` row resolves 1:1 to a note of the correct type; the duplicated
      document columns are gone from the children (single source of truth).
- [ ] `generate_internal_note()` exists, tested, and ready for ACR-31's approval transaction.
- [ ] `contacts.type` accepts and renders `"transfer"`.
- [ ] `source` lives on the note; ACR-33 notified.
- [ ] Read-only Delivery Notes UI, locale + RBAC verified.
- [ ] Migration reversible; up/down proven by test.
- [ ] **Deferred to the ledger migration:** `stock_movements.delivery_note_id NOT NULL`. §4.1 becomes
      constraint-enforceable there; ACR-39 supplies the table and the generator it needs.

---

## 8. Risks / open questions

| # | Item | Severity | Handling |
|---|---|---|---|
| R1 | **Acceptance can't be fully met** — no `stock_movements` table (§0) | High | ✅ Resolved — scope revised per §7; movement FK deferred to the ledger migration |
| R2 | **Q1 answered as "document layer + drop duplicated columns"** (§2) — touches both shipped operator flows | High | ✅ Approved 2026-07-23. Regression risk sits in the receiving + shipping flows; §4 covers both with updated tests, §6 walks them live |
| R3 | Migration slot contention — `010` double-claimed, `011` earmarked (§1, §3.2) | High | Take `011`, `down_revision = "009"`, build on a fresh DB, doc corrected in §5 |
| R4 | Merge conflicts with ACR-26/27/30 in `main.py`, `models/`, `alembic/` | Medium | Expected per `CLAUDE.md` *Merge Notes*; ACR-39 touches no `stock_movement.py` / `inventory.py` code that ACR-26 is editing |
| R5 | Backfill trips the uniqueness constraint on duplicate BOLs | Medium | De-duplicate by suffixing; explicit migration test (§4) |
| R6 | `shipping.*` granted to no role (ISS-04) — new endpoints would 403 for everyone | Medium | Sidestepped: read endpoints accept `deliveries.view`; the grant stays ACR-35's |
| R7 | `document_date` kept as `String(20)` | Low | Deliberate — matches both existing columns; a real date type is a separate sweep |
| R8 | **ACR-33 has uncommitted work that already added `shipments.source`** — found 2026-07-23 in `acra-worktrees/ticket-33-shipment-invoice-transfer-direct-source` (ticket still in Backlog, nothing committed): adds `source` + `ck_shipments_source_direct_only`, retypes `type` to `transfer\|direct_customer`, adds `shipment_items.unit_price`, and claims slot `010` a **third** time (`010_shipment_invoices.py`) | High | Q3 stands — `source` lands on the note; ACR-33 drops its column and reads the note's. Convergent win: ACR-33 independently chose the same `transfer`/`direct_customer` values this plan uses, so the vocabulary already agrees. **Backfill maps from `master`'s live values (`customer_order`/`transfer_out`)**, correct while ACR-33 is unmerged; re-point the mapping if ACR-33 lands first. Comment filed on ACR-33 |

**No open blocking questions** — R1 and R2 were signed off on 2026-07-23; everything else is decided
and justified above.

---

## 9. Build order
1. Branch + fresh DB; confirm `alembic upgrade head` green at `009`.
2. Model + schemas (`delivery_note.py` ×2) + tests for the model/enum.
3. Migration `011` — create, backfill, NOT NULL, drop; **write the up/down integration test alongside it**.
4. `delivery_note_service.py` incl. `generate_internal_note` + its tests.
5. Router + registration in `main.py` + RBAC/validation tests.
6. Refactor `delivery_service` / `shipment_service` onto notes; update their existing tests.
7. Frontend: field renames in receiving + shipping views; their Jest updates.
8. New `DeliveryNotesView` + route + nav + i18n messages + Jest tests.
9. Contacts `"transfer"` type (UI + messages).
10. Doc corrections (§5) + Linear comments on ACR-33 / ACR-31.
11. Full gate: pytest ≥85%, jest, lint, build, smoke, Playwright `ticket-39.spec.ts`.
