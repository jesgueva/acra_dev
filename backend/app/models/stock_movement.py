"""Phase 2 — StockMovement ledger model (skeleton).

Realigns inventory from lot-centric rows (``InventoryLot``) to an **append-only ledger** keyed by
``(item, state)``: on-hand is the sum of signed movement quantities, and every operator surface
(receiving, production close, shipment) records movements instead of mutating rows.

This is an intentional skeleton for the Sprint I baseline. The movement-type / stock-state
vocabulary is fixed here so dependent code can reference it, but the concrete ORM table and its
Alembic migration land in **Sprint II** (see ``docs/architecture.md`` and ``docs/RISK_LOG.md``
RSK-01/RSK-02). Deliberately **not** mapped to a table or registered with Alembic yet.
"""

from enum import Enum


class StockState(str, Enum):
    """The states a quantity of an item can occupy in the ledger."""

    IN_STORAGE = "in_storage"
    IN_PRODUCTION = "in_production"
    SHIPPED = "shipped"
    CONSUMED = "consumed"


class MovementType(str, Enum):
    """The kinds of signed movement the ledger records."""

    RECEIPT = "receipt"      # +qty inbound (receiving)
    RESERVE = "reserve"      # earmark for a worksheet (reduces available, not on-hand)
    CONSUME = "consume"      # -qty at production-worksheet close
    ISSUE = "issue"          # -qty at shipment
    ADJUST = "adjust"        # signed manual correction
    TRANSFER = "transfer"    # move between states / locations
