"""
Seed deterministic fake data for local development and demos.

Usage:
    python scripts/seed_fake_data.py

Safe to re-run:
- roles, privileges, users, contacts, products, alerts are upserted
- demo deliveries are skipped if their BOL already exists
- demo work orders are skipped if their product already exists

Schema: deliveries and shipments hang off delivery_notes, which carry the partner, document
number and date; delivery_items and inventory_lots reference products;
quantities are integer ×100 where applicable (inventory, delivery lines, low-stock thresholds).
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
    *,
    created_by: int,
    supplier_ids: dict[str, int],
    carrier_ids: dict[str, int],
    products_by_name: dict[str, Product],
) -> tuple[int, int, int]:
    created_deliveries = 0
    created_delivery_items = 0
    created_inventory_lots = 0
    today = date.today()

    for index in range(1, 25):
        bol_reference = f"DEMO-BOL-{today.year}-{index:03d}"
        existing = await db.execute(
            select(DeliveryNote.id).where(
                DeliveryNote.type == DeliveryNoteType.INBOUND.value,
                DeliveryNote.document_number == bol_reference,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        delivery_date = today - timedelta(days=index * 2)
        supplier_name = SUPPLIERS[(index - 1) % len(SUPPLIERS)]
        carrier_name = CARRIERS[(index - 1) % len(CARRIERS)]

        # §4.1/§4.2 — the paper document that arrived with the goods owns the
        # supplier, reference and date.
        note = DeliveryNote(
            type=DeliveryNoteType.INBOUND.value,
            partner_id=supplier_ids[supplier_name],
            document_number=bol_reference,
            document_date=delivery_date.strftime("%d/%m/%y"),
            uploaded=True,
            created_by=created_by,
        )
        db.add(note)
        await db.flush()

        delivery = Delivery(
            delivery_note_id=note.id,
            carrier_id=carrier_ids[carrier_name],
            notes=None,
            created_by=created_by,
        )
        db.add(delivery)
        await db.flush()
        created_deliveries += 1

        item_count = 2 + (index % 3)
        pairs: list[tuple[DeliveryItem, InventoryLot, Product]] = []

        for offset in range(item_count):
            material = RAW_MATERIALS[(index + offset - 1) % len(RAW_MATERIALS)]
            product = products_by_name[str(material["material_type"])]
            pallets = 2 + ((index + offset) % 8)
            units_per_pallet = 100 + (((index * 3 + offset) % 10) * 50)
            total_units = pallets * units_per_pallet
            quantity_x100 = int(total_units * 100)

            item = DeliveryItem(
                delivery_id=delivery.id,
                product_id=product.id,
                description=(
                    f"Demo batch — {material['lot_prefix']}-"
                    f"{delivery_date.strftime('%y%m%d')}-{offset + 1}"
                ),
                quantity=quantity_x100,
                pallets=pallets,
                units_per_pallet=units_per_pallet,
                leftover=None,
            )
            db.add(item)

            lot = InventoryLot(
                product_id=product.id,
                lot_number=f"{material['lot_prefix']}-{bol_reference}-{offset + 1}",
                storage_location=material["locations"][offset % len(material["locations"])],
                status="in_storage",
                quantity_on_hand=quantity_x100,
                source_delivery_item_id=None,
                pallet_number=pallets,
            )
            db.add(lot)
            pairs.append((item, lot, product))
            created_delivery_items += 1

        await db.flush()

        for item, lot, _product in pairs:
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
            f"Need {required_qty_display} (×100={remaining_x100}), have {total_available} on hand."
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

        supplier_ids: dict[str, int] = {}
        for name in SUPPLIERS:
            supplier_ids[name] = (await ensure_contact(db, name, "provider")).id

        carrier_ids: dict[str, int] = {}
        for name in CARRIERS:
            carrier_ids[name] = (await ensure_contact(db, name, "carrier")).id

        products_by_name: dict[str, Product] = {}
        for material in RAW_MATERIALS:
            name = str(material["material_type"])
            products_by_name[name] = await ensure_product(db, name, category="raw")

        admin_user = user_map["admin"]
        for material in RAW_MATERIALS:
            product = products_by_name[str(material["material_type"])]
            threshold_x100 = int((material["threshold"] * Decimal("100")).quantize(Decimal("1")))
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
            created_by=user_map["clerk1"].id,
            supplier_ids=supplier_ids,
            carrier_ids=carrier_ids,
            products_by_name=products_by_name,
        )
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
        print(f"  raw inventory lots created: {delivery_counts[2]}")
        print(f"  work orders created: {work_order_counts[0]}")
        print(f"  work-order materials created: {work_order_counts[1]}")
        print(f"  material allocations created: {work_order_counts[2]}")
        print(f"  finished inventory lots created: {work_order_counts[3]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_fake_data())
