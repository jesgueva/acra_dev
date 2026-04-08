"""
Unit tests for T03 — verifies ORM models and Pydantic schemas are importable
and behave correctly without requiring a database connection.
"""
import pytest
from pydantic import ValidationError


def test_model_imports():
    from app.models import (
        AuditLog,
        Delivery,
        DeliveryItem,
        InventoryItem,
        LowStockAlert,
        MaterialAllocation,
        Role,
        User,
        UserRoleAssignment,
        WorkOrder,
        WorkOrderMaterial,
    )
    assert User.__tablename__ == "users"
    assert Role.__tablename__ == "roles"
    assert Delivery.__tablename__ == "deliveries"
    assert InventoryItem.__tablename__ == "inventory_items"
    assert WorkOrder.__tablename__ == "work_orders"
    assert AuditLog.__tablename__ == "audit_logs"


def test_schema_imports():
    from app.schemas import (
        DeliveryCreate,
        LoginRequest,
        LowStockAlertCreate,
        WorkOrderCreate,
    )
    assert LoginRequest.__name__ == "LoginRequest"
    assert DeliveryCreate.__name__ == "DeliveryCreate"
    assert WorkOrderCreate.__name__ == "WorkOrderCreate"
    assert LowStockAlertCreate.__name__ == "LowStockAlertCreate"


def test_delivery_create_schema_valid():
    from app.schemas import DeliveryCreate

    payload = DeliveryCreate(
        supplier="ACME Corp",
        carrier="FastFreight",
        delivery_date="2026-04-08",
        bol_reference="BOL-001",
        items=[
            {
                "material_type": "Steel Rod",
                "quantity": 50.0,
                "lot_batch_number": "LOT-A",
                "storage_location": "A-01",
            }
        ],
    )
    assert payload.supplier == "ACME Corp"
    assert len(payload.items) == 1
    assert payload.items[0].quantity == 50.0


def test_delivery_create_schema_rejects_missing_items():
    from app.schemas import DeliveryCreate

    with pytest.raises(ValidationError):
        DeliveryCreate(
            supplier="ACME Corp",
            carrier="FastFreight",
            delivery_date="2026-04-08",
            bol_reference="BOL-001",
            items=[],  # empty list not allowed (min_length=1)
        )


def test_work_order_create_schema_rejects_invalid_priority():
    from app.schemas import WorkOrderCreate

    with pytest.raises(ValidationError):
        WorkOrderCreate(
            product="Widget A",
            quantity_required=100,
            priority="critical",  # not a valid priority
            target_date="2026-05-01",
            materials=[{"material_type": "Steel", "quantity_required": 10}],
        )
