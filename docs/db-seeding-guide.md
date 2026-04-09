# Database Seeding Guide

This repository now includes:

- `backend/scripts/create_admin.py` - creates or resets the built-in admin user
- `backend/scripts/seed_fake_data.py` - seeds deterministic fake data for local demos

This document defines the recommended approach for seeding local/demo data into the PostgreSQL database for development, demos, and UI testing.

## Goal

Seed a realistic but safe development dataset that supports:

- login and role-based navigation
- receiving workflows
- inventory browsing and low-stock alerts
- traceability dialogs
- work order creation and allocation flows
- dashboard counts and charts

## Current Data Model

Core tables involved in seeding:

- `users`
- `roles`
- `user_role_assignments`
- `role_privilege_assignments`
- `deliveries`
- `delivery_items`
- `inventory_items`
- `low_stock_alerts`
- `work_orders`
- `work_order_materials`
- `material_allocations`

## Recommended Seed Order

Seed in this order to satisfy foreign keys and keep relationships realistic:

1. roles
2. role privilege assignments
3. users
4. user role assignments
5. low stock alerts
6. deliveries
7. delivery items
8. inventory items
9. work orders
10. work order materials
11. material allocations

## Minimum Seed Dataset

### Users

Create at least these users:

- `admin` - full system access
- `supervisor1` - production supervisor
- `clerk1` - receiving clerk
- `operator1` - machine operator on `Line A`
- `operator2` - machine operator on `Line B`

Suggested fields:

- active status for all demo users
- mixed `preferred_language` values (`en`, `es`)
- `production_line` only for machine operators

## Demo Credentials

The seed script prepares these local/demo credentials:

- `admin` / `admin123`
- `supervisor1` / `demo123`
- `clerk1` / `demo123`
- `operator1` / `demo123`
- `operator2` / `demo123`

Do not use these outside local/demo environments.

## Role and Privilege Coverage

Seed enough roles and privilege assignments to exercise the frontend navigation and page guards.

At minimum, cover:

- receiving access
- inventory view and adjust access
- work order view/create/allocate/status access
- audit access
- user management access

If role names already exist in the database, reuse them instead of inventing parallel role sets.

## Deliveries

Seed 20-40 deliveries across the last 60 days.

Recommended variety:

- 5-8 suppliers
- 3-4 carriers
- unique `bol_reference` values
- mixed recent and older delivery dates

Each delivery should include 1-5 delivery items.

## Delivery Items

Seed realistic raw materials such as:

- Steel Rod
- Aluminum Sheet
- Cardboard Core
- Plastic Resin
- Adhesive Roll
- Printed Film

Required constraints:

- `quantity > 0`
- non-empty `lot_batch_number`
- non-empty `storage_location`

Storage location examples:

- `RACK-A1`
- `RACK-A2`
- `RACK-B1`
- `BULK-01`
- `FG-01`

## Inventory Items

For each seeded delivery item, create a linked inventory item when appropriate.

Recommended rules:

- most received materials become `category = "raw"`
- some finished goods can be seeded separately with `category = "finished"`
- preserve the same `lot_batch_number` from the source delivery item
- set `source_delivery_item_id` to support traceability

Use varied `quantity_on_hand` values so the UI shows:

- normal stock
- low stock
- nearly depleted lots

## Low Stock Alerts

Seed 4-8 `low_stock_alerts` records for common materials.

Choose thresholds so some inventory items are triggered and some are not. This ensures:

- dashboard alert states render
- inventory badges appear
- admin views are easy to verify manually

## Work Orders

Seed 10-20 work orders with a mix of:

- `created`
- `materials_allocated`
- `in_production`
- `completed`

Use multiple priorities:

- `low`
- `medium`
- `high`
- `urgent`

Spread orders across:

- `Line A`
- `Line B`

## Work Order Materials

Each work order should include 1-4 material requirements.

Use materials that actually exist in seeded inventory so allocation and traceability flows work.

## Material Allocations

Seed allocations for some, but not all, work orders.

Recommended distribution:

- some work orders with no allocations yet
- some partially allocated
- some fully allocated

This creates realistic variation for:

- allocation screens
- traceability views
- inventory consumption examples

## Recommended Volumes

For a good local demo dataset:

- users: 5-8
- roles: 4-6
- deliveries: 25
- delivery items: 60-100
- inventory items: 60-100
- low stock alerts: 6
- work orders: 12
- work order materials: 25-35
- material allocations: 15-25

## Idempotency Rules

The seed process should be rerunnable without creating uncontrolled duplicates.

Recommended approach:

- upsert users by `username`
- upsert roles by `role_name`
- upsert low stock alerts by `material_type`
- upsert deliveries by `bol_reference`
- generate deterministic fake values using a fixed random seed

For local development, it is acceptable to support either:

- a full reset-and-seed mode, or
- an idempotent incremental seed mode

## Seed Script

Seed command:

```bash
cd backend
python scripts/seed_fake_data.py
```

## Seed Script Responsibilities

The implemented seed script:

- ensure base roles and privileges exist
- ensure demo users exist
- create deliveries, delivery items, and inventory
- create low stock alerts
- create work orders and material requirements
- create some material allocations
- print a concise summary of inserted or updated records

## Local Runbook

Recommended local setup sequence:

```bash
cd backend
alembic upgrade head
python scripts/create_admin.py
python scripts/seed_fake_data.py
```

Then log in from the frontend with seeded credentials and verify:

- `/en/login`
- `/en/receiving`
- `/en/inventory`
- `/en/dashboard`

## Open Decisions

Before implementing the seed script, decide:

1. Should the seeder hard reset business tables before inserting demo data?
2. Should Faker be added as a dependency, or should we use deterministic hard-coded sample pools?
3. Should the seed script create only local demo data, or also test fixtures useful for screenshots and stakeholder demos?
4. Should finished goods inventory be seeded directly or only emerge from completed work orders?

## Recommendation

Prefer a deterministic Python seed script with curated sample pools over fully random Faker output.

That will make:

- UI screenshots repeatable
- debugging easier
- traceability relationships easier to reason about
- demos more stable across reseeds
