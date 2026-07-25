"""unified delivery_notes document model

Domain model §4.1: every stock movement attaches to a Delivery Note. §4.2: notes are either
*uploaded* (an external document arrived with the goods) or *system-generated*.

Before this revision the six shared document facts lived twice — once on ``deliveries``
(``contact_id``, ``bol_reference``, ``delivery_date``) and once on ``shipments`` (``contact_id``,
``bol_number``, ``shipment_date``, ``type``) — and the internal case had no table at all. This
revision creates ``delivery_notes``, backfills one note per existing row, makes the link
``NOT NULL UNIQUE``, and **drops the duplicated columns** so each fact has exactly one home.

Numbering: slot ``010``/``011`` were contested while this was in flight. ACR-27 (reservations) took
``010`` and ACR-30 (production worksheets) took ``011`` on ``master`` first, so this revision moved
to ``012`` and now revises ``011`` — the standing manual resolution for concurrent branches
(CLAUDE.md → Merge Notes). ACR-33's unmerged ``010_shipment_invoices.py`` still needs the same
treatment.

**Downgrade caveats**, both inherent rather than incidental:

1. INTERNAL notes have no ``deliveries``/``shipments`` row to fold back into and are dropped with
   the table. Every inbound/outbound note round-trips.
2. A document number that was de-duplicated on the way up (``BOL-DUP`` → ``BOL-DUP (2)``) keeps its
   suffix on the way down. Reversing it would mean guessing which suffixes were ours, and the
   duplicate was only ever reachable through the ``force=true`` override.

Revision ID: 012
Revises: 011
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


# Temporary provenance marker ('delivery:12' / 'shipment:7') so the backfill can link each new note
# back to the row it came from without re-deriving the de-duplicated document number. Dropped at
# the end of upgrade().
_REF = "migration_legacy_ref"


def upgrade():
    # ── 1. the document table ────────────────────────────────────────────────
    op.create_table(
        "delivery_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("document_number", sa.String(100), nullable=False),
        sa.Column("document_date", sa.String(20), nullable=False),
        sa.Column("uploaded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(_REF, sa.String(50), nullable=True),
        sa.CheckConstraint(
            "type IN ('inbound', 'transfer', 'direct_customer', 'internal')",
            name="ck_delivery_notes_type",
        ),
        sa.CheckConstraint(
            "source IS NULL OR type = 'direct_customer'",
            name="ck_delivery_notes_source_direct_only",
        ),
    )
    op.create_index("ix_delivery_notes_type", "delivery_notes", ["type"])
    op.create_index("ix_delivery_notes_partner_id", "delivery_notes", ["partner_id"])
    op.create_index("ix_delivery_notes_document_date", "delivery_notes", ["document_date"])

    # ── 2. nullable links, filled in below ───────────────────────────────────
    op.add_column("deliveries", sa.Column("delivery_note_id", sa.Integer(), nullable=True))
    op.add_column("shipments", sa.Column("delivery_note_id", sa.Integer(), nullable=True))

    # ── 3. backfill inbound (§4.2 — goods arrived with a paper document) ─────
    # `deliveries.bol_reference` is not unique: delivery_service permits duplicates via force=true.
    # Suffix the 2nd+ occurrence so uq_delivery_notes_type_document_number can be added below.
    op.execute(
        """
        INSERT INTO delivery_notes (
            type, source, partner_id, document_number, document_date,
            uploaded, notes, created_by, created_at, migration_legacy_ref
        )
        SELECT
            'inbound',
            NULL,
            d.contact_id,
            CASE WHEN d.rn = 1
                 THEN d.bol_reference
                 ELSE left(d.bol_reference, 100 - length(' (' || d.rn || ')'))
                      || ' (' || d.rn || ')'
            END,
            d.delivery_date,
            true,
            NULL,
            d.created_by,
            d.created_at,
            'delivery:' || d.id
        FROM (
            SELECT id, contact_id, bol_reference, delivery_date, created_by, created_at,
                   ROW_NUMBER() OVER (PARTITION BY bol_reference ORDER BY id) AS rn
            FROM deliveries
        ) d
        ORDER BY d.id
        """
    )

    # ── 4. backfill outbound (system-generated → uploaded = false) ───────────
    # Maps master's live vocabulary: 'transfer_out' → transfer, everything else → direct_customer.
    # De-duplication partitions by the mapped type, since uniqueness is per (type, number).
    op.execute(
        """
        INSERT INTO delivery_notes (
            type, source, partner_id, document_number, document_date,
            uploaded, notes, created_by, created_at, migration_legacy_ref
        )
        SELECT
            s.mapped_type,
            NULL,
            s.contact_id,
            CASE WHEN s.rn = 1
                 THEN s.bol_number
                 ELSE left(s.bol_number, 100 - length(' (' || s.rn || ')'))
                      || ' (' || s.rn || ')'
            END,
            s.shipment_date,
            false,
            NULL,
            s.created_by,
            s.created_at,
            'shipment:' || s.id
        FROM (
            SELECT id, contact_id, bol_number, shipment_date, created_by, created_at,
                   CASE WHEN type = 'transfer_out' THEN 'transfer' ELSE 'direct_customer' END
                       AS mapped_type,
                   ROW_NUMBER() OVER (
                       PARTITION BY
                           CASE WHEN type = 'transfer_out' THEN 'transfer' ELSE 'direct_customer' END,
                           bol_number
                       ORDER BY id
                   ) AS rn
            FROM shipments
        ) s
        ORDER BY s.id
        """
    )

    # ── 5. link, then enforce ────────────────────────────────────────────────
    op.execute(
        """
        UPDATE deliveries d SET delivery_note_id = dn.id
        FROM delivery_notes dn
        WHERE dn.migration_legacy_ref = 'delivery:' || d.id
        """
    )
    op.execute(
        """
        UPDATE shipments s SET delivery_note_id = dn.id
        FROM delivery_notes dn
        WHERE dn.migration_legacy_ref = 'shipment:' || s.id
        """
    )

    op.create_unique_constraint(
        "uq_delivery_notes_type_document_number",
        "delivery_notes",
        ["type", "document_number"],
    )
    op.drop_column("delivery_notes", _REF)

    op.alter_column("deliveries", "delivery_note_id", nullable=False)
    op.alter_column("shipments", "delivery_note_id", nullable=False)
    op.create_unique_constraint(
        "uq_deliveries_delivery_note_id", "deliveries", ["delivery_note_id"]
    )
    op.create_unique_constraint(
        "uq_shipments_delivery_note_id", "shipments", ["delivery_note_id"]
    )
    op.create_foreign_key(
        "fk_deliveries_delivery_note_id", "deliveries", "delivery_notes",
        ["delivery_note_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_shipments_delivery_note_id", "shipments", "delivery_notes",
        ["delivery_note_id"], ["id"],
    )

    # ── 6. drop the now-duplicated columns — one fact, one home ──────────────
    op.drop_column("deliveries", "bol_reference")
    op.drop_column("deliveries", "delivery_date")
    op.drop_column("deliveries", "contact_id")

    op.drop_constraint("ck_shipments_type", "shipments", type_="check")
    op.drop_column("shipments", "bol_number")
    op.drop_column("shipments", "shipment_date")
    op.drop_column("shipments", "contact_id")
    op.drop_column("shipments", "type")


def downgrade():
    # ── 1. re-add the columns, nullable while they are repopulated ───────────
    op.add_column("deliveries", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.add_column("deliveries", sa.Column("delivery_date", sa.String(20), nullable=True))
    op.add_column("deliveries", sa.Column("bol_reference", sa.String(100), nullable=True))
    op.create_foreign_key(
        "fk_deliveries_contact_id", "deliveries", "contacts", ["contact_id"], ["id"]
    )

    op.add_column("shipments", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.add_column("shipments", sa.Column("bol_number", sa.String(100), nullable=True))
    op.add_column("shipments", sa.Column("shipment_date", sa.String(20), nullable=True))
    op.add_column("shipments", sa.Column("type", sa.String(30), nullable=True))
    op.create_foreign_key(
        "fk_shipments_contact_id", "shipments", "contacts", ["contact_id"], ["id"]
    )

    # ── 2. copy the facts back off the notes ─────────────────────────────────
    op.execute(
        """
        UPDATE deliveries d SET
            contact_id    = dn.partner_id,
            delivery_date = dn.document_date,
            bol_reference = dn.document_number
        FROM delivery_notes dn
        WHERE dn.id = d.delivery_note_id
        """
    )
    op.execute(
        """
        UPDATE shipments s SET
            contact_id    = dn.partner_id,
            shipment_date = dn.document_date,
            bol_number    = dn.document_number,
            type          = CASE WHEN dn.type = 'transfer'
                                 THEN 'transfer_out' ELSE 'customer_order' END
        FROM delivery_notes dn
        WHERE dn.id = s.delivery_note_id
        """
    )

    # ── 3. restore the original NOT NULL / CHECK guarantees ──────────────────
    op.alter_column("deliveries", "delivery_date", nullable=False)
    op.alter_column("deliveries", "bol_reference", nullable=False)
    op.alter_column("shipments", "bol_number", nullable=False)
    op.alter_column("shipments", "shipment_date", nullable=False)
    op.alter_column(
        "shipments", "type", nullable=False, server_default="customer_order"
    )
    op.create_check_constraint(
        "ck_shipments_type", "shipments", "type IN ('customer_order', 'transfer_out')"
    )

    # ── 4. drop the links and the table (INTERNAL notes are lost — see header)
    op.drop_constraint("fk_shipments_delivery_note_id", "shipments", type_="foreignkey")
    op.drop_constraint("fk_deliveries_delivery_note_id", "deliveries", type_="foreignkey")
    op.drop_column("shipments", "delivery_note_id")
    op.drop_column("deliveries", "delivery_note_id")

    op.drop_index("ix_delivery_notes_document_date", table_name="delivery_notes")
    op.drop_index("ix_delivery_notes_partner_id", table_name="delivery_notes")
    op.drop_index("ix_delivery_notes_type", table_name="delivery_notes")
    op.drop_table("delivery_notes")
