"""
Seed deterministic fake data for local development and demos.

Usage:
    python scripts/seed_fake_data.py

Safe to re-run:
- roles, privileges, users, alerts are upserted
- demo deliveries are skipped if their BOL already exists
- demo work orders are skipped if their product already exists
"""

import asyncio
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Allow running from backend/ root or from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.security import hash_password
from app.models.delivery import Delivery, DeliveryItem
from app.models.inventory import InventoryItem, LowStockAlert
from app.models.user import Role, RolePrivilegeAssignment, User, UserRoleAssignment
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db",
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
        },
    },
    "receiving_clerk": {
        "description": "Receives deliveries and reviews OCR-assisted intake.",
        "privileges": {
            "authenticated",
            "receiving.view",
            "deliveries.create",
            "deliveries.view",
        },
    },
    "production_supervisor": {
        "description": "Plans, sequences, and allocates work orders.",
        "privileges": {
            "authenticated",
            "inventory.view",
            "work_orders.view",
            "work_orders.create",
            "work_orders.assign",
            "work_orders.status_update",
            "work_orders.sequence",
            "work_orders.allocate",
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

RAW_MATERIALS = [
    {
        "material_type": "Steel Rod",
        "locations": ["RACK-A1", "RACK-A2"],
        "threshold": Decimal("40"),
        "lot_prefix": "STL",
    },
    {
        "material_type": "Aluminum Sheet",
        "locations": ["RACK-B1", "RACK-B2"],
        "threshold": Decimal("35"),
        "lot_prefix": "ALM",
    },
    {
        "material_type": "Plastic Resin",
        "locations": ["BULK-01", "BULK-02"],
        "threshold": Decimal("60"),
        "lot_prefix": "RSN",
    },
    {
        "material_type": "Printed Film",
        "locations": ["RACK-C1", "RACK-C2"],
        "threshold": Decimal("30"),
        "lot_prefix": "FIL",
    },
    {
        "material_type": "Cardboard Core",
        "locations": ["RACK-D1", "RACK-D2"],
        "threshold": Decimal("20"),
        "lot_prefix": "CRD",
    },
    {
        "material_type": "Adhesive Roll",
        "locations": ["RACK-E1", "RACK-E2"],
        "threshold": Decimal("25"),
        "lot_prefix": "ADH",
    },
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


def dec(value: int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"))


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
    db: AsyncSession, material_type: str, threshold: Decimal, created_by: int
) -> bool:
    result = await db.execute(
        select(LowStockAlert).where(LowStockAlert.material_type == material_type)
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        db.add(
            LowStockAlert(
                material_type=material_type,
                threshold=threshold,
                created_by=created_by,
            )
        )
        return True
    alert.threshold = threshold
    alert.created_by = created_by
    return False


async def create_demo_deliveries(
    db: AsyncSession, created_by: int
) -> tuple[int, int, int]:
    created_deliveries = 0
    created_delivery_items = 0
    created_inventory_items = 0
    today = date.today()

    for index in range(1, 25):
        bol_reference = f"DEMO-BOL-{today.year}-{index:03d}"
        existing = await db.execute(
            select(Delivery.id).where(Delivery.bol_reference == bol_reference)
        )
        if existing.scalar_one_or_none() is not None:
            continue

        delivery_date = today - timedelta(days=index * 2)
        delivery = Delivery(
            supplier=SUPPLIERS[(index - 1) % len(SUPPLIERS)],
            carrier=CARRIERS[(index - 1) % len(CARRIERS)],
            delivery_date=delivery_date,
            bol_reference=bol_reference,
            created_by=created_by,
        )
        db.add(delivery)
        await db.flush()
        created_deliveries += 1

        item_count = 2 + (index % 3)
        delivery_items: list[DeliveryItem] = []
        for offset in range(item_count):
            material = RAW_MATERIALS[(index + offset - 1) % len(RAW_MATERIALS)]
            quantity = dec(30 + ((index * 11 + offset * 7) % 90))
            storage_location = material["locations"][
                (index + offset - 1) % len(material["locations"])
            ]
            lot_batch = (
                f"DEMO-LOT-{material['lot_prefix']}-{delivery_date.strftime('%y%m%d')}-{offset + 1}"
            )
            item = DeliveryItem(
                delivery_id=delivery.id,
                material_type=str(material["material_type"]),
                quantity=quantity,
                lot_batch_number=lot_batch,
                storage_location=storage_location,
            )
            db.add(item)
            delivery_items.append(item)
            created_delivery_items += 1

        await db.flush()

        for item in delivery_items:
            inventory_item = InventoryItem(
                material_type=item.material_type,
                category="raw",
                quantity_on_hand=item.quantity,
                lot_batch_number=item.lot_batch_number,
                storage_location=item.storage_location,
                source_delivery_item_id=item.id,
            )
            db.add(inventory_item)
            await db.flush()
            item.inventory_item_id = inventory_item.id
            created_inventory_items += 1

    return created_deliveries, created_delivery_items, created_inventory_items


async def build_inventory_index(
    db: AsyncSession,
) -> dict[str, list[InventoryItem]]:
    result = await db.execute(
        select(InventoryItem)
        .where(InventoryItem.category == "raw")
        .order_by(InventoryItem.material_type, InventoryItem.last_updated.asc(), InventoryItem.id.asc())
    )
    items_by_type: dict[str, list[InventoryItem]] = defaultdict(list)
    for item in result.scalars().all():
        items_by_type[item.material_type].append(item)
    return items_by_type


async def allocate_inventory(
    db: AsyncSession,
    items_by_type: dict[str, list[InventoryItem]],
    *,
    material_type: str,
    required_qty: Decimal,
    work_order_material_id: int,
    timestamp: datetime,
) -> int:
    remaining = required_qty
    allocation_count = 0
    inventory_items = items_by_type.get(material_type, [])

    total_available = sum(dec(item.quantity_on_hand) for item in inventory_items)
    if total_available < remaining:
        raise RuntimeError(
            f"Not enough seeded inventory for '{material_type}'. "
            f"Need {required_qty}, have {total_available}."
        )

    for item in inventory_items:
        if remaining <= 0:
            break
        available = dec(item.quantity_on_hand)
        if available <= 0:
            continue

        qty_taken = min(available, remaining)
        item.quantity_on_hand = available - qty_taken
        item.last_updated = timestamp
        db.add(
            MaterialAllocation(
                work_order_material_id=work_order_material_id,
                inventory_id=item.id,
                lot_batch_number=item.lot_batch_number,
                quantity_allocated=qty_taken,
                allocated_at=timestamp,
            )
        )
        remaining -= qty_taken
        allocation_count += 1

    return allocation_count


async def ensure_finished_inventory(
    db: AsyncSession,
    *,
    material_type: str,
    quantity_on_hand: Decimal,
    lot_batch_number: str,
    storage_location: str,
    timestamp: datetime,
) -> bool:
    existing = await db.execute(
        select(InventoryItem.id).where(
            InventoryItem.lot_batch_number == lot_batch_number
        )
    )
    if existing.scalar_one_or_none() is not None:
        return False

    db.add(
        InventoryItem(
            material_type=material_type,
            category="finished",
            quantity_on_hand=quantity_on_hand,
            lot_batch_number=lot_batch_number,
            storage_location=storage_location,
            last_updated=timestamp,
        )
    )
    return True


async def create_demo_work_orders(
    db: AsyncSession,
    *,
    created_by: int,
) -> tuple[int, int, int, int]:
    created_work_orders = 0
    created_work_order_materials = 0
    created_allocations = 0
    created_finished_inventory = 0
    items_by_type = await build_inventory_index(db)
    today = date.today()

    for sequence, spec in enumerate(WORK_ORDER_SEEDS, start=1):
        existing = await db.execute(
            select(WorkOrder.id).where(WorkOrder.product == spec.product)
        )
        if existing.scalar_one_or_none() is not None:
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

        for material_type, qty in spec.materials:
            work_order_material = WorkOrderMaterial(
                work_order_id=work_order.id,
                material_type=material_type,
                quantity_required=qty,
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
                    required_qty=qty,
                    work_order_material_id=work_order_material.id,
                    timestamp=now,
                )
                work_order_material.quantity_allocated = qty
                created_allocations += allocation_rows

        if spec.status in {"completed", "ready_for_shipment"}:
            lot_batch_number = f"DEMO-FG-{work_order.id:04d}"
            created = await ensure_finished_inventory(
                db,
                material_type=spec.product,
                quantity_on_hand=spec.quantity_produced,
                lot_batch_number=lot_batch_number,
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


async def seed_fake_data() -> None:
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

        admin_user = user_map["admin"]
        for material in RAW_MATERIALS:
            alert_create_count += int(
                await ensure_low_stock_alert(
                    db,
                    str(material["material_type"]),
                    Decimal(material["threshold"]),
                    admin_user.id,
                )
            )

        delivery_counts = await create_demo_deliveries(db, user_map["clerk1"].id)
        work_order_counts = await create_demo_work_orders(
            db, created_by=user_map["supervisor1"].id
        )

        await db.commit()

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
        print(f"  roles created: {role_create_count}")
        print(f"  privileges assigned: {role_privilege_count}")
        print(f"  users created: {user_create_count}")
        print(f"  user-role assignments created: {role_assignment_count}")
        print(f"  low-stock alerts created: {alert_create_count}")
        print(f"  deliveries created: {delivery_counts[0]}")
        print(f"  delivery items created: {delivery_counts[1]}")
        print(f"  raw inventory items created: {delivery_counts[2]}")
        print(f"  work orders created: {work_order_counts[0]}")
        print(f"  work-order materials created: {work_order_counts[1]}")
        print(f"  material allocations created: {work_order_counts[2]}")
        print(f"  finished inventory items created: {work_order_counts[3]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_fake_data())
