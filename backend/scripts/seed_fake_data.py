"""
Seed deterministic fake data for local development and demos.

Usage:
    python scripts/seed_fake_data.py                  # the demo fixture (scale 1)
    python scripts/seed_fake_data.py --scale 50       # 50× the volume, for benchmarking
    python scripts/seed_fake_data.py --deliveries 400 --work-orders 0
    python scripts/seed_fake_data.py --scale 10 --json

`--scale 1` is the **demo fixture contract**: its output is bit-identical to what this script
produced before the scale knob existed, because the 83 Playwright e2e tests log in as these users
and read these rows. Scale N is a strict superset of scale 1 — index 1..24 always generate the same
deliveries — so re-running at a higher scale adds rows instead of conflicting with them.

There is deliberately no RNG and no `--seed`: every value is arithmetic on the row index, so two
runs of the same arguments produce the same database without needing a seed to be recorded.

Safe to re-run:
- roles, privileges, users, contacts, products, alerts are upserted
- demo deliveries are skipped if their BOL already exists
- demo work orders are skipped if their product already exists

Schema: deliveries and shipments hang off delivery_notes, which carry the partner, document
number and date; delivery_items and inventory_lots reference products;
quantities are integer ×100 where applicable (inventory, delivery lines, low-stock thresholds).

Note on `--materials M`: raising it past the 6 named materials changes which material each
delivery line draws, so the fixture is no longer the demo fixture — it is a benchmark corpus.
It also dilutes supply for the base 6 materials that work orders consume, so combine it with
`--work-orders 0` or a higher `--deliveries` if allocation runs short.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Allow running from backend/ root or from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.security import hash_password
from app.models.contact import Contact
from app.models.delivery import Delivery, DeliveryItem
from app.models.delivery_note import DeliveryNote, DeliveryNoteType
from app.models.inventory import InventoryLot, InventoryTransaction, LowStockAlert
from app.models.product import Product
from app.models.user import Role, RolePrivilegeAssignment, User, UserRoleAssignment
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/acra_db",
)

ADMIN_PASSWORD = "admin123"
DEMO_PASSWORD = "demo123"

ROLE_DEFINITIONS: dict[str, dict[str, object]] = {
    "company_admin": {
        "description": "Full system access for local demos.",
        "privileges": {
            "authenticated",
            "receiving.view",
            "deliveries.create",
            "deliveries.view",
            "inventory.view",
            "inventory.adjust",
            "work_orders.view",
            "work_orders.create",
            "work_orders.assign",
            "work_orders.status_update",
            "work_orders.sequence",
            "work_orders.allocate",
            "users.manage",
            "audit.view",
            "master_data.manage",
            "production.worksheet.view",
            "production.worksheet.create",
            "production.worksheet.close",
            "shipping.view",
            "shipping.create",
        },
    },
    "receiving_clerk": {
        "description": "Receives deliveries and reviews OCR-assisted intake.",
        "privileges": {
            "authenticated",
            "receiving.view",
            "deliveries.create",
            "deliveries.view",
            "shipping.view",
            "shipping.create",
        },
    },
    "production_supervisor": {
        "description": "Plans, sequences, and allocates work orders.",
        "privileges": {
            "authenticated",
            "inventory.view",
            "shipping.view",
            "work_orders.view",
            "work_orders.create",
            "work_orders.assign",
            "work_orders.status_update",
            "work_orders.sequence",
            "work_orders.allocate",
            "production.worksheet.view",
            "production.worksheet.create",
            "production.worksheet.close",
        },
    },
    "machine_operator": {
        "description": "Views active work orders for the assigned line.",
        "privileges": {
            "authenticated",
            "work_orders.view",
        },
    },
}

USER_SPECS = [
    {
        "username": "admin",
        "password": ADMIN_PASSWORD,
        "full_name": "Administrator",
        "preferred_language": "en",
        "production_line": None,
        "roles": ["company_admin"],
    },
    {
        "username": "supervisor1",
        "password": DEMO_PASSWORD,
        "full_name": "Marina Lopez",
        "preferred_language": "en",
        "production_line": None,
        "roles": ["production_supervisor"],
    },
    {
        "username": "clerk1",
        "password": DEMO_PASSWORD,
        "full_name": "Daniel Cruz",
        "preferred_language": "es",
        "production_line": None,
        "roles": ["receiving_clerk"],
    },
    {
        "username": "operator1",
        "password": DEMO_PASSWORD,
        "full_name": "Iris Chen",
        "preferred_language": "en",
        "production_line": "Line A",
        "roles": ["machine_operator"],
    },
    {
        "username": "operator2",
        "password": DEMO_PASSWORD,
        "full_name": "Mateo Rivera",
        "preferred_language": "es",
        "production_line": "Line B",
        "roles": ["machine_operator"],
    },
]

@dataclass(frozen=True)
class MaterialSpec:
    material_type: str
    locations: tuple[str, ...]
    threshold: Decimal
    lot_prefix: str


BASE_MATERIALS = [
    MaterialSpec("Steel Rod", ("RACK-A1", "RACK-A2"), Decimal("40"), "STL"),
    MaterialSpec("Aluminum Sheet", ("RACK-B1", "RACK-B2"), Decimal("35"), "ALM"),
    MaterialSpec("Plastic Resin", ("BULK-01", "BULK-02"), Decimal("60"), "RSN"),
    MaterialSpec("Printed Film", ("RACK-C1", "RACK-C2"), Decimal("30"), "FIL"),
    MaterialSpec("Cardboard Core", ("RACK-D1", "RACK-D2"), Decimal("20"), "CRD"),
    MaterialSpec("Adhesive Roll", ("RACK-E1", "RACK-E2"), Decimal("25"), "ADH"),
]

SUPPLIERS = [
    "Northwind Materials",
    "Blue Harbor Packaging",
    "Summit Metals",
    "Pacific Resins",
    "Boxline Supply",
    "Prime Flex Films",
]

CARRIERS = [
    "DHL Freight",
    "FedEx Freight",
    "RoadRunner Logistics",
    "TransNational Cargo",
]


@dataclass(frozen=True)
class WorkOrderSeed:
    product: str
    quantity_required: Decimal
    priority: str
    status: str
    target_in_days: int
    production_line: str
    quantity_produced: Decimal
    # material quantities: display units (matches work_order API); inventory uses ×100 internally
    materials: tuple[tuple[str, Decimal], ...]


WORK_ORDER_SEEDS = [
    WorkOrderSeed(
        product="[DEMO] Retail Carton Run Alpha",
        quantity_required=Decimal("500"),
        priority="high",
        status="created",
        target_in_days=3,
        production_line="Line A",
        quantity_produced=Decimal("0"),
        materials=(
            ("Cardboard Core", Decimal("40")),
            ("Printed Film", Decimal("22")),
            ("Adhesive Roll", Decimal("12")),
        ),
    ),
    WorkOrderSeed(
        product="[DEMO] Retail Carton Run Beta",
        quantity_required=Decimal("650"),
        priority="urgent",
        status="materials_allocated",
        target_in_days=5,
        production_line="Line B",
        quantity_produced=Decimal("0"),
        materials=(
            ("Cardboard Core", Decimal("48")),
            ("Printed Film", Decimal("26")),
            ("Plastic Resin", Decimal("36")),
        ),
    ),
    WorkOrderSeed(
        product="[DEMO] Shipping Sleeve Gamma",
        quantity_required=Decimal("420"),
        priority="medium",
        status="in_production",
        target_in_days=7,
        production_line="Line A",
        quantity_produced=Decimal("160"),
        materials=(
            ("Steel Rod", Decimal("55")),
            ("Aluminum Sheet", Decimal("32")),
            ("Adhesive Roll", Decimal("10")),
        ),
    ),
    WorkOrderSeed(
        product="[DEMO] Display Carton Delta",
        quantity_required=Decimal("300"),
        priority="low",
        status="completed",
        target_in_days=-2,
        production_line="Line B",
        quantity_produced=Decimal("300"),
        materials=(
            ("Cardboard Core", Decimal("26")),
            ("Printed Film", Decimal("18")),
            ("Adhesive Roll", Decimal("9")),
        ),
    ),
    WorkOrderSeed(
        product="[DEMO] Protective Insert Echo",
        quantity_required=Decimal("480"),
        priority="medium",
        status="ready_for_shipment",
        target_in_days=-1,
        production_line="Line A",
        quantity_produced=Decimal("480"),
        materials=(
            ("Plastic Resin", Decimal("44")),
            ("Printed Film", Decimal("12")),
        ),
    ),
    WorkOrderSeed(
        product="[DEMO] Heavy Duty Crate Foxtrot",
        quantity_required=Decimal("190"),
        priority="high",
        status="materials_allocated",
        target_in_days=9,
        production_line="Line B",
        quantity_produced=Decimal("0"),
        materials=(
            ("Steel Rod", Decimal("70")),
            ("Aluminum Sheet", Decimal("28")),
        ),
    ),
    WorkOrderSeed(
        product="[DEMO] Utility Box Golf",
        quantity_required=Decimal("720"),
        priority="medium",
        status="created",
        target_in_days=12,
        production_line="Line A",
        quantity_produced=Decimal("0"),
        materials=(
            ("Cardboard Core", Decimal("54")),
            ("Plastic Resin", Decimal("24")),
        ),
    ),
    WorkOrderSeed(
        product="[DEMO] Transit Tube Hotel",
        quantity_required=Decimal("360"),
        priority="high",
        status="in_production",
        target_in_days=6,
        production_line="Line B",
        quantity_produced=Decimal("110"),
        materials=(
            ("Steel Rod", Decimal("28")),
            ("Cardboard Core", Decimal("31")),
            ("Adhesive Roll", Decimal("8")),
        ),
    ),
]


# ---------------------------------------------------------------------------
# Planning layer — pure, no database
#
# Everything below decides *what rows should exist*; nothing here touches a session. Keeping the
# decision pure is what lets `tests/test_seed_scaling.py` pin the scale-1 fixture with a golden
# snapshot in milliseconds, which is the regression lock protecting the 83 Playwright tests.
# ---------------------------------------------------------------------------

DELIVERIES_PER_SCALE = 24  # the pre-scale-knob delivery count; one scale unit
WORK_ORDERS_PER_SCALE = len(WORK_ORDER_SEEDS)

# Delivery dates step 2 days per index. Left unbounded, scale 100 reaches ~13 years back, which
# reads as a bug in a demo; wrapping keeps the corpus inside ~2 years. Indices 1..24 are unaffected
# (index % 365 == index), so the demo fixture is untouched. Dates are not unique-constrained, so
# the collisions this introduces at high scale are harmless.
DATE_WINDOW_INDICES = 365


@dataclass(frozen=True)
class DeliveryItemSpec:
    material_type: str
    lot_prefix: str
    storage_location: str
    line_number: int  # 1-based position within the delivery
    pallets: int
    units_per_pallet: int
    quantity_x100: int


@dataclass(frozen=True)
class DeliverySpec:
    index: int
    bol_reference: str
    supplier: str
    carrier: str
    delivery_date: date
    items: tuple[DeliveryItemSpec, ...]


def plan_materials(count: int) -> list[MaterialSpec]:
    """The 6 named materials, then deterministic filler to reach `count`.

    Filler exists for A8-6: the availability aggregation groups by (item, state), so stressing it
    needs more *products*, not just more lots against the same six.
    """
    if count <= len(BASE_MATERIALS):
        return list(BASE_MATERIALS[:count])

    materials = list(BASE_MATERIALS)
    for i in range(len(BASE_MATERIALS), count):
        n = i + 1
        materials.append(
            MaterialSpec(
                material_type=f"Synthetic Material {n:03d}",
                locations=(f"RACK-S{n:03d}-1", f"RACK-S{n:03d}-2"),
                # Cycles 20/30/40/50/60 — the same spread as the named materials.
                threshold=Decimal(20 + (i % 5) * 10),
                lot_prefix=f"SYN{n:03d}",
            )
        )
    return materials


def plan_deliveries(
    count: int, today: date, materials: list[MaterialSpec] | None = None
) -> list[DeliverySpec]:
    """Every field is arithmetic on `index`/`offset` — no RNG, no clock beyond `today`."""
    catalogue = list(BASE_MATERIALS) if materials is None else materials
    specs: list[DeliverySpec] = []

    for index in range(1, count + 1):
        bol_reference = f"DEMO-BOL-{today.year}-{index:03d}"
        delivery_date = today - timedelta(days=(index % DATE_WINDOW_INDICES) * 2)
        item_count = 2 + (index % 3)

        items = []
        for offset in range(item_count):
            material = catalogue[(index + offset - 1) % len(catalogue)]
            pallets = 2 + ((index + offset) % 8)
            units_per_pallet = 100 + (((index * 3 + offset) % 10) * 50)
            items.append(
                DeliveryItemSpec(
                    material_type=material.material_type,
                    lot_prefix=material.lot_prefix,
                    storage_location=material.locations[offset % len(material.locations)],
                    line_number=offset + 1,
                    pallets=pallets,
                    units_per_pallet=units_per_pallet,
                    quantity_x100=pallets * units_per_pallet * 100,
                )
            )

        specs.append(
            DeliverySpec(
                index=index,
                bol_reference=bol_reference,
                supplier=SUPPLIERS[(index - 1) % len(SUPPLIERS)],
                carrier=CARRIERS[(index - 1) % len(CARRIERS)],
                delivery_date=delivery_date,
                items=tuple(items),
            )
        )

    return specs


def plan_work_orders(count: int) -> list[WorkOrderSeed]:
    """Cycle the 8 base seeds, suffixing replicas.

    `create_demo_work_orders` skips on an exact `WorkOrder.product` match, so replicas that reused
    the base name would be silently dropped and every scale would yield 8 work orders. Replica 0
    keeps the bare name, which is what preserves the scale-1 fixture.
    """
    orders: list[WorkOrderSeed] = []
    for i in range(count):
        base = WORK_ORDER_SEEDS[i % len(WORK_ORDER_SEEDS)]
        replica = i // len(WORK_ORDER_SEEDS)
        product = base.product if replica == 0 else f"{base.product} #{replica + 1}"
        orders.append(replace(base, product=product))
    return orders


def material_balance(
    deliveries: list[DeliverySpec], work_orders: list[WorkOrderSeed]
) -> dict[str, tuple[int, int]]:
    """Planned (supply_x100, demand_x100) per material type.

    `allocate_inventory` aborts the whole seed when a material runs short. This makes that
    predictable from the plan alone, so the scaling tests can prove the default ratios stay
    feasible instead of arguing it from supply and demand both being multiplied by N.
    """
    supply: dict[str, int] = defaultdict(int)
    demand: dict[str, int] = defaultdict(int)

    for delivery in deliveries:
        for item in delivery.items:
            supply[item.material_type] += item.quantity_x100

    for order in work_orders:
        # Work orders with status "created" are seeded unallocated.
        if order.status == "created":
            continue
        for material_type, qty_display in order.materials:
            demand[material_type] += int(qty_display * Decimal("100"))

    return {
        material_type: (supply.get(material_type, 0), demand.get(material_type, 0))
        for material_type in set(supply) | set(demand)
    }


def resolve_volumes(args: argparse.Namespace) -> tuple[int, int, int]:
    """(delivery_count, work_order_count, material_count) from the parsed CLI."""
    deliveries = (
        args.deliveries
        if args.deliveries is not None
        else DELIVERIES_PER_SCALE * args.scale
    )
    work_orders = (
        args.work_orders
        if args.work_orders is not None
        else WORK_ORDERS_PER_SCALE * args.scale
    )
    return deliveries, work_orders, args.materials


# asyncpg binds one parameter per IN element and the PostgreSQL wire protocol caps a statement at
# 32 767 of them. Measured: a 24 000-element IN succeeds, 65 000 raises InterfaceError. Chunking
# keeps the existence pre-checks O(1) queries per 10 000 rows instead of one per row, without
# reintroducing a ceiling — unchunked, --scale would have died around 1 365.
IN_CLAUSE_CHUNK = 10_000


async def _existing_values(db: AsyncSession, column, values: list[str], *extra_where) -> set[str]:
    """Which of `values` already exist in `column`, fetched in bind-parameter-safe chunks."""
    found: set[str] = set()
    for start in range(0, len(values), IN_CLAUSE_CHUNK):
        chunk = values[start : start + IN_CLAUSE_CHUNK]
        stmt = select(column).where(column.in_(chunk), *extra_where)
        rows = await db.execute(stmt)
        found.update(row[0] for row in rows.fetchall())
    return found


async def ensure_contact(db: AsyncSession, name: str, type_: str) -> Contact:
    result = await db.execute(
        select(Contact).where(Contact.name == name, Contact.type == type_)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = Contact(name=name, type=type_)
        db.add(row)
        await db.flush()
    return row


async def ensure_product(db: AsyncSession, name: str, *, category: str = "raw") -> Product:
    result = await db.execute(select(Product).where(Product.name == name))
    row = result.scalar_one_or_none()
    if row is None:
        row = Product(name=name, category=category, description=None)
        db.add(row)
        await db.flush()
    return row


async def ensure_role(db: AsyncSession, role_name: str, description: str) -> tuple[Role, bool]:
    result = await db.execute(select(Role).where(Role.role_name == role_name))
    role = result.scalar_one_or_none()
    created = False
    if role is None:
        role = Role(role_name=role_name, description=description)
        db.add(role)
        await db.flush()
        created = True
    else:
        role.description = description
    return role, created


async def ensure_role_privileges(
    db: AsyncSession, role: Role, privileges: set[str]
) -> int:
    existing_rows = await db.execute(
        select(RolePrivilegeAssignment.privilege_name).where(
            RolePrivilegeAssignment.role_id == role.id
        )
    )
    existing = {row[0] for row in existing_rows.fetchall()}
    added = 0
    for privilege in sorted(privileges - existing):
        db.add(
            RolePrivilegeAssignment(role_id=role.id, privilege_name=privilege)
        )
        added += 1
    return added


async def ensure_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    full_name: str,
    preferred_language: str,
    production_line: str | None,
) -> tuple[User, bool]:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    created = False
    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(password),
            full_name=full_name,
            preferred_language=preferred_language,
            production_line=production_line,
            status="active",
        )
        db.add(user)
        await db.flush()
        created = True
    else:
        user.password_hash = hash_password(password)
        user.full_name = full_name
        user.preferred_language = preferred_language
        user.production_line = production_line
        user.status = "active"
    return user, created


async def ensure_user_role(db: AsyncSession, user_id: int, role_id: int) -> bool:
    result = await db.execute(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.role_id == role_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        db.add(UserRoleAssignment(user_id=user_id, role_id=role_id))
        return True
    return False


async def ensure_low_stock_alert(
    db: AsyncSession,
    *,
    product_id: int,
    threshold_x100: int,
    created_by: int,
) -> bool:
    result = await db.execute(
        select(LowStockAlert).where(LowStockAlert.product_id == product_id)
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        db.add(
            LowStockAlert(
                product_id=product_id,
                threshold=threshold_x100,
                created_by=created_by,
            )
        )
        return True
    alert.threshold = threshold_x100
    alert.created_by = created_by
    return False


async def create_demo_deliveries(
    db: AsyncSession,
    specs: list[DeliverySpec],
    *,
    created_by: int,
    supplier_ids: dict[str, int],
    carrier_ids: dict[str, int],
    products_by_name: dict[str, Product],
) -> tuple[int, int, int]:
    created_deliveries = 0
    created_delivery_items = 0
    created_inventory_lots = 0

    # One pre-fetch per 10 000 deliveries instead of a SELECT per delivery: at scale 100 that is
    # 2 400 round-trips replaced by one.
    already_seeded = await _existing_values(
        db,
        DeliveryNote.document_number,
        [s.bol_reference for s in specs],
        DeliveryNote.type == DeliveryNoteType.INBOUND.value,
    )

    for spec in specs:
        if spec.bol_reference in already_seeded:
            continue

        # §4.1/§4.2 — the paper document that arrived with the goods owns the
        # supplier, reference and date.
        note = DeliveryNote(
            type=DeliveryNoteType.INBOUND.value,
            partner_id=supplier_ids[spec.supplier],
            document_number=spec.bol_reference,
            document_date=spec.delivery_date.strftime("%d/%m/%y"),
            uploaded=True,
            created_by=created_by,
        )
        db.add(note)
        await db.flush()

        delivery = Delivery(
            delivery_note_id=note.id,
            carrier_id=carrier_ids[spec.carrier],
            notes=None,
            created_by=created_by,
        )
        db.add(delivery)
        await db.flush()
        created_deliveries += 1

        pairs: list[tuple[DeliveryItem, InventoryLot]] = []

        for item_spec in spec.items:
            product = products_by_name[item_spec.material_type]

            item = DeliveryItem(
                delivery_id=delivery.id,
                product_id=product.id,
                description=(
                    f"Demo batch — {item_spec.lot_prefix}-"
                    f"{spec.delivery_date.strftime('%y%m%d')}-{item_spec.line_number}"
                ),
                quantity=item_spec.quantity_x100,
                pallets=item_spec.pallets,
                units_per_pallet=item_spec.units_per_pallet,
                leftover=None,
            )
            db.add(item)

            lot = InventoryLot(
                product_id=product.id,
                lot_number=f"{item_spec.lot_prefix}-{spec.bol_reference}-{item_spec.line_number}",
                storage_location=item_spec.storage_location,
                status="in_storage",
                quantity_on_hand=item_spec.quantity_x100,
                source_delivery_item_id=None,
                pallet_number=item_spec.pallets,
            )
            db.add(lot)
            pairs.append((item, lot))
            created_delivery_items += 1

        await db.flush()

        for item, lot in pairs:
            lot.source_delivery_item_id = item.id
            item.inventory_lot_id = lot.id
            db.add(
                InventoryTransaction(
                    lot_id=lot.id,
                    transaction_type="receive",
                    quantity=item.quantity,
                    reference_type="delivery",
                    reference_id=delivery.id,
                    reason=f"Seeded receive — {note.document_number}",
                    created_by=created_by,
                )
            )
            created_inventory_lots += 1

    return created_deliveries, created_delivery_items, created_inventory_lots


async def build_inventory_index(
    db: AsyncSession,
) -> dict[str, list[InventoryLot]]:
    result = await db.execute(
        select(InventoryLot, Product.name)
        .join(Product, InventoryLot.product_id == Product.id)
        .where(
            Product.category == "raw",
            InventoryLot.status == "in_storage",
            InventoryLot.quantity_on_hand > 0,
        )
        .order_by(Product.name, InventoryLot.id.asc())
    )
    items_by_type: dict[str, list[InventoryLot]] = defaultdict(list)
    for lot, product_name in result.all():
        items_by_type[product_name].append(lot)
    return items_by_type


async def allocate_inventory(
    db: AsyncSession,
    items_by_type: dict[str, list[InventoryLot]],
    *,
    material_type: str,
    required_qty_display: Decimal,
    work_order_material_id: int,
    timestamp: datetime,
) -> int:
    """Deduct display-unit requirement from lots stored as integer ×100."""
    remaining_x100 = float(required_qty_display * Decimal("100"))
    allocation_count = 0
    inventory_items = items_by_type.get(material_type, [])

    total_available = sum(float(item.quantity_on_hand) for item in inventory_items)
    if total_available < remaining_x100 - 1e-3:
        raise RuntimeError(
            f"Not enough seeded inventory for '{material_type}'. "
            f"Need {required_qty_display} (×100={remaining_x100}), have {total_available} on hand.\n"
            "Work-order demand has outrun delivery supply. Raise --deliveries (or --scale), "
            "lower --work-orders, or drop --materials back towards 6 — extra materials dilute "
            "the six that work orders actually consume."
        )

    for item in inventory_items:
        if remaining_x100 <= 0:
            break
        available = float(item.quantity_on_hand)
        if available <= 0:
            continue

        qty_taken_x100 = min(remaining_x100, available)
        item.quantity_on_hand = int(round(item.quantity_on_hand - qty_taken_x100))
        lot_label = item.lot_number or f"LOT-{item.id}"
        db.add(
            MaterialAllocation(
                work_order_material_id=work_order_material_id,
                inventory_id=item.id,
                lot_batch_number=lot_label,
                quantity_allocated=qty_taken_x100,
                allocated_at=timestamp,
            )
        )
        remaining_x100 -= qty_taken_x100
        allocation_count += 1

    return allocation_count


async def ensure_finished_inventory(
    db: AsyncSession,
    *,
    lot_number: str,
    quantity_units: Decimal,
    storage_location: str,
    timestamp: datetime,
) -> bool:
    existing = await db.execute(
        select(InventoryLot.id).where(InventoryLot.lot_number == lot_number)
    )
    if existing.scalar_one_or_none() is not None:
        return False

    qty_x100 = int((quantity_units * Decimal("100")).quantize(Decimal("1")))
    db.add(
        InventoryLot(
            lot_number=lot_number,
            storage_location=storage_location,
            status="in_storage",
            quantity_on_hand=qty_x100,
            source_delivery_item_id=None,
        )
    )
    return True


async def create_demo_work_orders(
    db: AsyncSession,
    specs: list[WorkOrderSeed],
    *,
    created_by: int,
) -> tuple[int, int, int, int]:
    created_work_orders = 0
    created_work_order_materials = 0
    created_allocations = 0
    created_finished_inventory = 0
    items_by_type = await build_inventory_index(db)
    today = date.today()

    # Same batching as the delivery pre-check: one query per 10 000 instead of one per work order.
    already_seeded = await _existing_values(
        db, WorkOrder.product, [s.product for s in specs]
    )

    for sequence, spec in enumerate(specs, start=1):
        if spec.product in already_seeded:
            continue

        now = datetime.now(timezone.utc)
        work_order = WorkOrder(
            product=spec.product,
            quantity_required=spec.quantity_required,
            quantity_produced=spec.quantity_produced,
            priority=spec.priority,
            display_sequence=sequence,
            status=spec.status,
            target_date=today + timedelta(days=spec.target_in_days),
            production_line=spec.production_line,
            created_by=created_by,
            updated_at=now,
        )
        db.add(work_order)
        await db.flush()
        created_work_orders += 1

        for material_type, qty_display in spec.materials:
            work_order_material = WorkOrderMaterial(
                work_order_id=work_order.id,
                material_type=material_type,
                quantity_required=qty_display,
                quantity_allocated=Decimal("0"),
            )
            db.add(work_order_material)
            await db.flush()
            created_work_order_materials += 1

            if spec.status != "created":
                allocation_rows = await allocate_inventory(
                    db,
                    items_by_type,
                    material_type=material_type,
                    required_qty_display=qty_display,
                    work_order_material_id=work_order_material.id,
                    timestamp=now,
                )
                work_order_material.quantity_allocated = qty_display
                created_allocations += allocation_rows

        if spec.status in {"completed", "ready_for_shipment"}:
            lot_number = f"DEMO-FG-{work_order.id:04d}"
            created = await ensure_finished_inventory(
                db,
                lot_number=lot_number,
                quantity_units=spec.quantity_produced,
                storage_location="FG-01",
                timestamp=now,
            )
            if created:
                created_finished_inventory += 1

    return (
        created_work_orders,
        created_work_order_materials,
        created_allocations,
        created_finished_inventory,
    )


async def seed_fake_data(
    *,
    delivery_count: int = DELIVERIES_PER_SCALE,
    work_order_count: int = WORK_ORDERS_PER_SCALE,
    material_count: int = len(BASE_MATERIALS),
    today: date | None = None,
) -> dict[str, int]:
    """Write the planned fixture and return the per-table created counts."""
    today = today or date.today()
    materials = plan_materials(material_count)
    delivery_specs = plan_deliveries(delivery_count, today, materials)
    work_order_specs = plan_work_orders(work_order_count)

    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        role_create_count = 0
        role_privilege_count = 0
        user_create_count = 0
        role_assignment_count = 0
        alert_create_count = 0

        role_map: dict[str, Role] = {}
        for role_name, definition in ROLE_DEFINITIONS.items():
            role, created = await ensure_role(
                db,
                role_name=role_name,
                description=str(definition["description"]),
            )
            role_map[role_name] = role
            role_create_count += int(created)
            role_privilege_count += await ensure_role_privileges(
                db, role, set(definition["privileges"])
            )

        user_map: dict[str, User] = {}
        for spec in USER_SPECS:
            user, created = await ensure_user(
                db,
                username=spec["username"],
                password=spec["password"],
                full_name=spec["full_name"],
                preferred_language=spec["preferred_language"],
                production_line=spec["production_line"],
            )
            user_map[spec["username"]] = user
            user_create_count += int(created)

            for role_name in spec["roles"]:
                role_assignment_count += int(
                    await ensure_user_role(db, user.id, role_map[role_name].id)
                )

        supplier_ids: dict[str, int] = {}
        for name in SUPPLIERS:
            supplier_ids[name] = (await ensure_contact(db, name, "provider")).id

        carrier_ids: dict[str, int] = {}
        for name in CARRIERS:
            carrier_ids[name] = (await ensure_contact(db, name, "carrier")).id

        products_by_name: dict[str, Product] = {}
        for material in materials:
            products_by_name[material.material_type] = await ensure_product(
                db, material.material_type, category="raw"
            )

        admin_user = user_map["admin"]
        for material in materials:
            product = products_by_name[material.material_type]
            threshold_x100 = int((material.threshold * Decimal("100")).quantize(Decimal("1")))
            alert_create_count += int(
                await ensure_low_stock_alert(
                    db,
                    product_id=product.id,
                    threshold_x100=threshold_x100,
                    created_by=admin_user.id,
                )
            )

        delivery_counts = await create_demo_deliveries(
            db,
            delivery_specs,
            created_by=user_map["clerk1"].id,
            supplier_ids=supplier_ids,
            carrier_ids=carrier_ids,
            products_by_name=products_by_name,
        )
        work_order_counts = await create_demo_work_orders(
            db, work_order_specs, created_by=user_map["supervisor1"].id
        )

        await db.commit()

        counts = {
            "roles": role_create_count,
            "role_privileges": role_privilege_count,
            "users": user_create_count,
            "user_role_assignments": role_assignment_count,
            "low_stock_alerts": alert_create_count,
            "deliveries": delivery_counts[0],
            "delivery_items": delivery_counts[1],
            "raw_inventory_lots": delivery_counts[2],
            "work_orders": work_order_counts[0],
            "work_order_materials": work_order_counts[1],
            "material_allocations": work_order_counts[2],
            "finished_inventory_lots": work_order_counts[3],
        }

    await engine.dispose()
    return counts


COUNT_LABELS = {
    "roles": "roles created",
    "role_privileges": "privileges assigned",
    "users": "users created",
    "user_role_assignments": "user-role assignments created",
    "low_stock_alerts": "low-stock alerts created",
    "deliveries": "deliveries created",
    "delivery_items": "delivery items created",
    "raw_inventory_lots": "raw inventory lots created",
    "work_orders": "work orders created",
    "work_order_materials": "work-order materials created",
    "material_allocations": "material allocations created",
    "finished_inventory_lots": "finished inventory lots created",
}


def print_summary(counts: dict[str, int]) -> None:
    print("Seed complete.")
    print()
    print("Users ready:")
    print("  admin / admin123")
    print("  supervisor1 / demo123")
    print("  clerk1 / demo123")
    print("  operator1 / demo123")
    print("  operator2 / demo123")
    print()
    print("Changes applied:")
    for key, label in COUNT_LABELS.items():
        print(f"  {label}: {counts[key]}")


def positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or greater, got {value}")
    return value


def non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or greater, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed deterministic fake data. Scale 1 is the demo fixture the e2e suite "
        "depends on; higher scales are benchmark corpora.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scale",
        type=positive_int,
        default=1,
        metavar="N",
        help=f"volume multiplier: {DELIVERIES_PER_SCALE} deliveries and "
        f"{WORK_ORDERS_PER_SCALE} work orders per unit (default: 1)",
    )
    parser.add_argument(
        "--deliveries",
        type=non_negative_int,
        default=None,
        metavar="N",
        help="absolute delivery count, overriding --scale on this axis",
    )
    parser.add_argument(
        "--work-orders",
        type=non_negative_int,
        default=None,
        metavar="N",
        help="absolute work-order count, overriding --scale on this axis",
    )
    parser.add_argument(
        "--materials",
        type=positive_int,
        default=len(BASE_MATERIALS),
        metavar="M",
        help=f"size of the raw-material catalogue (default: {len(BASE_MATERIALS)}). Past "
        f"{len(BASE_MATERIALS)} the fixture stops being the demo fixture.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable summary instead of prose (feeds the A8-2 harness)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    delivery_count, work_order_count, material_count = resolve_volumes(args)

    started = time.monotonic()
    try:
        counts = asyncio.run(
            seed_fake_data(
                delivery_count=delivery_count,
                work_order_count=work_order_count,
                material_count=material_count,
            )
        )
    except RuntimeError as exc:
        # Allocation ran out of stock. That is a choice-of-arguments problem, not a crash, so it
        # gets a clean message instead of a traceback. Nothing was committed — the session exits
        # without commit, so the database is untouched.
        print(f"Seed aborted: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    elapsed = time.monotonic() - started

    if args.json:
        print(
            json.dumps(
                {
                    "params": {
                        "scale": args.scale,
                        "deliveries": delivery_count,
                        "work_orders": work_order_count,
                        "materials": material_count,
                    },
                    "elapsed_seconds": round(elapsed, 3),
                    "counts": counts,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print_summary(counts)
        print()
        print(f"Elapsed: {elapsed:.2f}s")


if __name__ == "__main__":
    main()
