# Plan — ACR-35: Seed `shipping.*` privileges + surface Shipping nav

**Ticket:** [ACR-35](https://linear.app/chronos-laboral/issue/ACR-35/seed-shipping-privileges-surface-shipping-nav) · Medium
**Branch:** `ticket-35/seed-shipping-privileges-nav` (cut from `origin/master` @ `1ac2a7c`)
**Blocker:** ACR-25 (decision gate) — **Done**
**Refs:** F2 · KI-08 · ISS-04

> **Goal.** `shipping.create` / `shipping.view` are granted to no role, so every shipment endpoint
> 403s for every user and the Shipping page is unreachable. Grant them in the role-privilege seed
> and surface the Shipping nav link.
>
> **Acceptance.** An authorized role reaches shipment endpoints (no 403); the Shipping link appears
> in the nav.

---

## 1. Current state

### The backend half — privileges required but never granted

The shipments router requires two privileges:

- `backend/app/routers/shipments.py:18` — `require_privilege("shipping.create")` on `POST /api/v1/shipments`
- `backend/app/routers/shipments.py:31` — `require_privilege("shipping.view")` on `GET /api/v1/shipments`
- `backend/app/routers/shipments.py:47` — `require_privilege("shipping.view")` on `GET /api/v1/shipments/{id}`

`require_privilege` resolves privileges at request time straight from the DB
(`backend/app/core/rbac.py:47-55` builds `effective_privileges` from `role_privilege_assignments`;
`rbac.py:83-88` raises 403 when the name is absent). There is no in-code privilege registry — the
table *is* the source of truth.

The seed in `backend/alembic/versions/002_role_privilege_assignments.py:38-72` grants 24
role/privilege pairs. **Neither `shipping.view` nor `shipping.create` is among them**, for any of
the four roles. `git grep shipping backend/alembic/` returns nothing. So on any DB built from
migrations, all three endpoints 403 for every user, including `company_admin`.

### The frontend half — a page with no way in

The Shipping page already exists and is complete:

- `frontend/app/[locale]/shipping/page.tsx` — route, renders `<ShippingView />`
- `frontend/src/components/shipping/ShippingView.tsx` — list + create dialog, 21 i18n keys
- `frontend/messages/en.json` / `es.json` — `nav.shippingNav` = "Shipping" / "Expedición" **already present**
- `frontend/src/lib/privileges.ts:10-11` — `SHIPPING_VIEW` / `SHIPPING_CREATE` constants **already present**

The only thing missing is the nav entry, commented out at
`frontend/src/components/layout/NavSidebar.tsx:31`:

```tsx
// { key: "shippingNav" as const, path: "shipping", icon: PackageCheck, privilege: PRIVILEGES.RECEIVING_VIEW },
```

Note the placeholder privilege is `RECEIVING_VIEW`, which is wrong for this link — it must be
`SHIPPING_VIEW`. `PackageCheck` is already imported (`NavSidebar.tsx:16`), so uncommenting costs no
new import. The `workOrders` entry on line 30 is also commented out; that belongs to ACR-18 on
another branch — **leave it alone**.

`ShippingView.tsx:229` renders the "New Shipment" button unconditionally — no privilege check. Once
`shipping.view` is granted to roles that lack `shipping.create`, those users would see a button
whose submit 403s.

### The closest pattern to imitate

ACR-27's migration `backend/alembic/versions/010_stock_reservations.py:59-76` does exactly this job
for `inventory.reserve` — and its comment even names this ticket:

```python
# Roles that run production worksheets, i.e. the ones that reserve stock.
_RESERVE_ROLES = ("company_admin", "production_supervisor")
...
    roles_sql = ", ".join(f"('{role}')" for role in _RESERVE_ROLES)
    op.execute(f"""
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, 'inventory.reserve'
        FROM roles r
        JOIN (VALUES {roles_sql}) AS p(role_name) ON r.role_name = p.role_name
    """)

def downgrade():
    op.execute("DELETE FROM role_privilege_assignments WHERE privilege_name = 'inventory.reserve'")
```

A role-name join (not a hardcoded id) plus a `DELETE … WHERE privilege_name = …` downgrade. Follow
this shape exactly.

### Second source of truth: the dev seed script

`backend/scripts/seed_fake_data.py:50-98` carries its own `ROLE_DEFINITIONS` privilege sets, and they
have **drifted from migration 002** — the script grants `receiving.view` and `master_data.manage`,
which the migration never seeds. Neither list has `shipping.*`. Both must be updated or the demo DB
and the migrated DB disagree again.

### Next migration revision

`origin/master` tops out at `010_stock_reservations` (`down_revision = "009"`). **The new revision is
`012`, revising `011`.** Heads-up: the in-flight ACR-26 branch carries a *different* `010_production_worksheets`;
that collision is between ACR-26 and ACR-27 and is not this ticket's to resolve, but expect a merge
conversation if ACR-26 lands first.

---

## 2. Change list

### CREATE

| File | Purpose |
|---|---|
| `backend/alembic/versions/012_shipping_privileges.py` | Seed `shipping.view` / `shipping.create` grants; reversible via `DELETE … WHERE privilege_name IN (…)` |
| `backend/tests/test_shipping_privileges.py` | Guard test — every privilege any router requires is seeded by some migration |
| `frontend/src/components/shipping/__tests__/ShippingView.test.tsx` | Component tests incl. the create-button privilege gate |
| `frontend/e2e/ticket-35.spec.ts` | Committed Playwright spec for the nav → page → create flow |

### MODIFY

| File | Change |
|---|---|
| `backend/scripts/seed_fake_data.py` | Add `shipping.*` to `ROLE_DEFINITIONS` so the demo DB matches migration 012 |
| `backend/tests/test_schema.py` | Live-DB assertion: `role_privilege_assignments` holds the expected `shipping.*` rows |
| `backend/tests/test_shipments.py` | Add the missing-privilege 403 cases (currently only 401-no-auth is covered) |
| `frontend/src/components/layout/NavSidebar.tsx` | Uncomment the shipping entry, gate it on `PRIVILEGES.SHIPPING_VIEW` |
| `frontend/src/components/shipping/ShippingView.tsx` | Gate the "New Shipment" button on `PRIVILEGES.SHIPPING_CREATE` |
| `frontend/src/components/layout/__tests__/NavSidebar.test.tsx` | Shipping link shown with the privilege, hidden without |

No model, schema, service, or endpoint changes. No new tables or columns.

---

## 3. Data / API

### Migration `012_shipping_privileges`

```python
revision = "012"
down_revision = "011"

# Dispatch is a dock function: the clerk works both inbound and outbound.
_SHIPPING_VIEW_ROLES   = ("company_admin", "production_supervisor", "receiving_clerk")
_SHIPPING_CREATE_ROLES = ("company_admin", "receiving_clerk")
```

**Role mapping decision** (resolved from the existing pattern, not a new product call): this mirrors
the `deliveries.create` / `deliveries.view` split already in migration 002 — the clerk *creates* dock
paperwork, the supervisor *sees* it, the machine operator gets neither. `machine_operator` holds only
`work_orders.view` today and gains nothing here.

| Role | `shipping.view` | `shipping.create` |
|---|:--:|:--:|
| `company_admin` | ✅ | ✅ |
| `receiving_clerk` | ✅ | ✅ |
| `production_supervisor` | ✅ | — |
| `machine_operator` | — | — |

Upgrade uses the `JOIN (VALUES …) ON r.role_name = …` form from migration 010 so it is id-agnostic
and idempotent against the seeded roles. Downgrade deletes both privilege names. The insert must be
safe to re-run after a partial rollback — use `ON CONFLICT DO NOTHING` against the
`(role_id, privilege_name)` primary key (`002_role_privilege_assignments.py:29`).

### Endpoint contracts

Unchanged. Behaviour change only:

| Endpoint | Privilege | Before | After |
|---|---|---|---|
| `POST /api/v1/shipments` | `shipping.create` | 403 for all | 201 for admin/clerk; 403 for supervisor/operator |
| `GET /api/v1/shipments` | `shipping.view` | 403 for all | 200 for admin/clerk/supervisor; 403 for operator |
| `GET /api/v1/shipments/{id}` | `shipping.view` | 403 for all | as above |

---

## 4. Test plan

### Backend

`backend/tests/test_shipments.py` (extend — currently 9 tests, none covering missing-privilege 403):

1. `test_create_shipment_missing_privilege_returns_403` — a user holding `shipping.view` only is
   refused on `POST`; assert `"shipping.create"` appears in `detail` (mirrors
   `test_reservations.py:532`).
2. `test_list_shipments_missing_privilege_returns_403` — a user holding no shipping privilege is
   refused on `GET`.
3. `test_get_shipment_missing_privilege_returns_403` — same for the detail endpoint.

Use `_make_rbac_session` / `_override` from `tests/conftest.py`, matching the file's existing style.

`backend/tests/test_shipping_privileges.py` (new — the regression guard that makes this class of bug
loud). No DB: parse `backend/app/routers/*.py` for every `require_privilege("…")` /
`require_any_privilege("…", …)` literal, parse every `backend/alembic/versions/*.py` for privilege
names appearing in a `role_privilege_assignments` insert, and assert the router set is a subset of
the seeded set.

4. `test_every_router_privilege_is_seeded` — the guard above.
5. `test_shipping_privileges_are_seeded_for_expected_roles` — assert migration 012's role tuples
   match the table in §3, so a future edit that silently drops a role fails here.

> The guard test will flag `master_data.view` and `master_data.manage` — required by
> `routers/contacts.py:32,41` and `routers/products.py:32,41` but seeded by no migration. That is the
> *same* defect as this ticket, on a different privilege, and is out of ACR-35's stated scope.
> It ships with a named `_UNSEEDED_KNOWN_GAPS` allowlist carrying a `# TODO(ACR-NN)` marker, and I
> will file the follow-up ticket rather than silently widen this migration. `receiving.view` is not
> flagged — no router requires it; it only gates nav links.

### Frontend

`frontend/src/components/layout/__tests__/NavSidebar.test.tsx` (extend):

6. Shipping link renders and points at `/en/shipping` when the user holds `SHIPPING_VIEW`.
7. Shipping link is absent when the user holds only `RECEIVING_VIEW` / `INVENTORY_VIEW`
   (guards against the `RECEIVING_VIEW` placeholder sneaking back in).

`frontend/src/components/shipping/__tests__/ShippingView.test.tsx` (new; mock `useAuth` +
`apiClient` the way `NavSidebar.test.tsx` and `Users.test.tsx` do):

8. Renders the shipment table from a mocked list response.
9. Empty response renders the `noShipments` state, not a crash.
10. "New Shipment" button is present with `SHIPPING_CREATE`.
11. "New Shipment" button is absent with `SHIPPING_VIEW` only.
12. Loading state renders skeletons.

### E2E — `frontend/e2e/ticket-35.spec.ts`

Against a real `npm run build && npm run start` server (**not `next dev`** — KI-02):

13. Admin logs in → Shipping link visible in sidebar → click → `/en/shipping` loads, table renders,
    **no 403 in the network panel**.
14. Supervisor sees the Shipping link but no "New Shipment" button.
15. Machine operator does not see the Shipping link, and a direct `/en/shipping` visit surfaces an
    error rather than a populated table — i.e. blocked, not merely hidden.
16. `/es/shipping` shows "Expedición" in the nav.

---

## 5. Live verification (browser walk)

1. `alembic upgrade head` on a **fresh** DB, then `python scripts/seed_fake_data.py`.
2. Log in as `admin` / `admin123` → the sidebar shows **Shipping** with the `PackageCheck` icon.
3. Click it → `/en/shipping` renders the list. **Network panel: `GET /api/v1/shipments` is 200, not 403.**
4. "New Shipment" → fill BOL, date, client, carrier, one lot line → submit → row appears; `POST` is 201.
5. Validation: empty submit, whitespace-only BOL, quantity `0`, negative, non-numeric, over-length
   BOL, duplicate BOL, unknown lot id → each surfaces a message, none 500s.
6. Cancel, double-submit, and refresh mid-dialog.
7. Log in as the supervisor demo user → Shipping link present, "New Shipment" **absent**, list loads.
8. Log in as the machine operator → Shipping link **absent**; navigate directly to `/en/shipping` →
   blocked with an error, no data leak.
9. Toggle to `/es/` → nav reads **Expedición**; toggle light/dark; check the console is clean throughout.
10. `alembic downgrade 010` → grants disappear, endpoints 403 again → `upgrade head` restores them.

---

## 6. Risks / open questions

| # | Item | Call |
|---|---|---|
| R1 | **Which roles get which privilege** | **Decided** — mirrors the existing `deliveries.*` split (see §3). Not escalating; it follows an in-repo pattern. |
| R2 | **`master_data.*` has the identical bug** | **Decided** — out of scope; documented allowlist in the guard test + follow-up ticket filed. Widening migration 012 would exceed the ticket. |
| R3 | **Migration number collision** | **Happened.** ACR-30 merged (#27) mid-build and took `011_production_worksheets`. Rebased onto the new `origin/master` and renumbered this migration to `012`, revising `011`. |
| R4 | **ACR-33 is in flight on shipping** | It touches `shipment_service` / invoice generation and the Shipping *page*; this ticket touches the seed + nav entry + button gate. Overlap is `ShippingView.tsx` only. Keep the diff there to the two-line privilege gate to stay mergeable. |
| R5 | **`seed_fake_data.py` drift** | Root cause of the whole class of bug: two privilege lists, no test tying them together. The guard test covers routers→migrations. Tying `seed_fake_data` to the migration is left as a note in the follow-up. |
| R6 | **Existing DBs** | Anyone with a DB already at `head` picks the grants up on `alembic upgrade head`; no data backfill needed. |

---

## 7. Build order

1. Cut `ticket-35/seed-shipping-privileges-nav` from `origin/master`; bring up Postgres on the port
   that is actually free (`CLAUDE.md` says 5433; local `.env` may say 5434 — check before starting).
2. Write `012_shipping_privileges.py`; `alembic upgrade head`; `alembic downgrade 010`; `upgrade head`
   again to prove reversibility.
3. Add the `shipping.*` grants to `seed_fake_data.py`; re-seed.
4. Backend tests: the three 403 cases in `test_shipments.py`, then `test_shipping_privileges.py`,
   then the `test_schema.py` live assertion. Run `pytest` with coverage.
5. Frontend: uncomment the nav entry with `SHIPPING_VIEW`; extend `NavSidebar.test.tsx`; `npx jest`.
6. Gate the "New Shipment" button on `SHIPPING_CREATE`; add `ShippingView.test.tsx`; `npx jest`.
7. Build + start the frontend; walk §5 in the browser across roles, locales, and themes; screenshot
   each state.
8. Write and run `frontend/e2e/ticket-35.spec.ts` against the built server.
9. Full gate: `pytest` (≥85% on touched `app.*`), `npx jest`, `npm run lint`, `npm run build`,
   `./scripts/smoke-test.sh`.
10. Draft PR into `master`, body ending `Closes ACR-35`. File the `master_data.*` follow-up ticket.
