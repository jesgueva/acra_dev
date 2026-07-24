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
    """What production has done to a quantity of an item — the *material* axis.

    Deliberately **not** a lifecycle axis. An earlier skeleton used
    ``in_storage / in_production / shipped / consumed``, which conflated two orthogonal ideas: a
    quantity is ``IN_STORAGE`` *and* ``RAW_MATERIAL`` at the same time, so those were never
    alternatives. Worse, in an append-only ledger where ``on_hand = Σ signed qty``, shipping is a
    negative movement rather than a destination state — recording ``ISSUE -100 state=SHIPPED``
    yields ``on_hand(item, SHIPPED) == -100``, which is meaningless.

    Lifecycle is expressed by :class:`MovementType` (``ISSUE``, ``CONSUME``) plus
    ``StockReservation`` (ACR-27), never by this enum.

    ``AUXILIARY`` items (e.g. Stripes) carry **no** state — they hold a single on-hand balance, so
    their movements leave ``state`` NULL. Auxiliary is a category on the item, not a member here
    (see ``client_domain_model.md`` §3.2 and ACR-26 Q4).
    """

    RAW_MATERIAL = "raw_material"
    WORK_IN_PROGRESS = "work_in_progress"
    FINISHED_GOOD = "finished_good"


class MovementType(str, Enum):
    """The kinds of signed movement the ledger records.

    Confirmed complete by the ACR-25 decision gate: no ``SCRAP`` (D-05 — scrap stays an implicit
    ``actual - planned`` delta) and no return type (D-06 — returns are out of scope, handled as a
    manual ``ADJUST`` with a reason).
    """

    RECEIPT = "receipt"      # +qty inbound (receiving)
    RESERVE = "reserve"      # earmark for a worksheet (reduces available, not on-hand)
    CONSUME = "consume"      # -qty at production-worksheet close
    ISSUE = "issue"          # -qty at shipment
    ADJUST = "adjust"        # signed manual correction — NOT the planned/actual delta (§7.1)
    TRANSFER = "transfer"    # move between states / locations (net zero on quantity)
