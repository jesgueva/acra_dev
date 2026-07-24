"""Migration 011 up/down against a real database (ACR-39).

The delivery-note backfill is the riskiest part of this ticket: it rewrites live receiving and
shipping rows, de-duplicates BoL references that `force=true` allowed to repeat, and drops columns.
Mocked sessions cannot prove any of that, so this test builds a scratch database, seeds it at `009`,
migrates to `011`, asserts the result, then migrates back down.

Skipped automatically when no Postgres is reachable.
"""
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]

asyncpg = pytest.importorskip("asyncpg")

pytestmark = pytest.mark.asyncio


def _dsn_parts():
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        pytest.skip("DATABASE_URL not set")
    # alembic/SQLAlchemy use the +asyncpg dialect prefix; asyncpg itself does not.
    dsn = raw.replace("postgresql+asyncpg://", "postgresql://")
    m = re.match(r"postgresql://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)", dsn)
    if not m:
        pytest.skip(f"unrecognized DATABASE_URL form: {dsn}")
    user, password, host, port, _db = m.groups()
    return user, password, host, int(port)


async def _connect(db: str):
    user, password, host, port = _dsn_parts()
    try:
        return await asyncpg.connect(
            user=user, password=password, host=host, port=port, database=db
        )
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"Postgres unreachable: {exc}")


def _alembic(scratch_db: str, *args: str) -> None:
    user, password, host, port = _dsn_parts()
    env = {
        **os.environ,
        "DATABASE_URL": (
            f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{scratch_db}"
        ),
    }
    # Must be the console script, not `python -m`: running from backend/ puts the local
    # `alembic/` migrations directory on sys.path, where it shadows the installed package.
    exe = Path(sys.executable).with_name("alembic")
    if not exe.exists():  # pragma: no cover - env dependent
        found = shutil.which("alembic")
        if not found:
            pytest.skip("alembic console script not found")
        exe = Path(found)

    proc = subprocess.run(
        [str(exe), *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"alembic {' '.join(args)} failed:\n{proc.stderr}"


@pytest.fixture
async def scratch_db():
    """A throwaway database migrated to 009, dropped on the way out."""
    name = f"acra_mig_{uuid.uuid4().hex[:12]}"
    admin = await _connect("postgres")
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()

    try:
        _alembic(name, "upgrade", "009")
        yield name
    finally:
        admin = await _connect("postgres")
        try:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                name,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        finally:
            await admin.close()


async def _seed_at_009(conn) -> None:
    """Two deliveries sharing a BoL (the force=true path) and one shipment of each flavour."""
    user_id = await conn.fetchval(
        "INSERT INTO users (username, password_hash, full_name, status) "
        "VALUES ('mig', 'x', 'Mig Tester', 'active') RETURNING id"
    )
    provider_id = await conn.fetchval(
        "INSERT INTO contacts (name, type) VALUES ('Acme Provider', 'provider') RETURNING id"
    )
    client_id = await conn.fetchval(
        "INSERT INTO contacts (name, type) VALUES ('Beta Client', 'client') RETURNING id"
    )

    for note_text, day in (("first", "2026-07-01"), ("second", "2026-07-02")):
        await conn.execute(
            "INSERT INTO deliveries (contact_id, delivery_date, bol_reference, notes, created_by) "
            "VALUES ($1, $2, 'BOL-DUP', $3, $4)",
            provider_id, day, note_text, user_id,
        )

    await conn.execute(
        "INSERT INTO shipments (contact_id, bol_number, shipment_date, type, created_by) "
        "VALUES ($1, 'SHP-100', '2026-07-03', 'transfer_out', $2)",
        client_id, user_id,
    )
    await conn.execute(
        "INSERT INTO shipments (contact_id, bol_number, shipment_date, type, created_by) "
        "VALUES ($1, 'SHP-200', '2026-07-04', 'customer_order', $2)",
        client_id, user_id,
    )


async def test_migration_011_backfills_and_reverses(scratch_db):
    conn = await _connect(scratch_db)
    try:
        await _seed_at_009(conn)
    finally:
        await conn.close()

    _alembic(scratch_db, "upgrade", "011")

    conn = await _connect(scratch_db)
    try:
        notes = await conn.fetch(
            "SELECT type, document_number, document_date, uploaded, partner_id "
            "FROM delivery_notes ORDER BY id"
        )
        assert len(notes) == 4

        inbound = [n for n in notes if n["type"] == "inbound"]
        assert len(inbound) == 2
        # §4.2 — goods arrived with a paper document.
        assert all(n["uploaded"] for n in inbound)
        # The repeated BoL is de-duplicated rather than aborting the migration.
        assert [n["document_number"] for n in inbound] == ["BOL-DUP", "BOL-DUP (2)"]

        outbound = {n["type"]: n for n in notes if n["type"] != "inbound"}
        assert set(outbound) == {"transfer", "direct_customer"}
        assert outbound["transfer"]["document_number"] == "SHP-100"
        assert outbound["direct_customer"]["document_number"] == "SHP-200"
        # System-generated, so not uploaded.
        assert not any(n["uploaded"] for n in outbound.values())

        # Every header resolves 1:1 to a note.
        assert await conn.fetchval(
            "SELECT count(*) FROM deliveries WHERE delivery_note_id IS NULL"
        ) == 0
        assert await conn.fetchval(
            "SELECT count(*) FROM shipments WHERE delivery_note_id IS NULL"
        ) == 0
        assert await conn.fetchval(
            "SELECT count(DISTINCT delivery_note_id) FROM deliveries"
        ) == 2

        # The duplicated columns are gone — one fact, one home.
        for table, column in (
            ("deliveries", "bol_reference"),
            ("deliveries", "delivery_date"),
            ("deliveries", "contact_id"),
            ("shipments", "bol_number"),
            ("shipments", "shipment_date"),
            ("shipments", "contact_id"),
            ("shipments", "type"),
        ):
            assert await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = $2",
                table, column,
            ) == 0, f"{table}.{column} should have been dropped"

        # The temporary backfill marker must not survive.
        assert await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'delivery_notes' AND column_name = 'migration_legacy_ref'"
        ) == 0
    finally:
        await conn.close()

    _alembic(scratch_db, "downgrade", "009")

    conn = await _connect(scratch_db)
    try:
        assert await conn.fetchval("SELECT to_regclass('delivery_notes')") is None

        deliveries = await conn.fetch(
            "SELECT contact_id, delivery_date, bol_reference FROM deliveries ORDER BY id"
        )
        assert [d["delivery_date"] for d in deliveries] == ["2026-07-01", "2026-07-02"]
        assert all(d["contact_id"] is not None for d in deliveries)
        # The de-dup suffix is retained by design — see the migration docstring.
        assert [d["bol_reference"] for d in deliveries] == ["BOL-DUP", "BOL-DUP (2)"]

        shipments = await conn.fetch(
            "SELECT bol_number, shipment_date, type FROM shipments ORDER BY id"
        )
        assert [s["type"] for s in shipments] == ["transfer_out", "customer_order"]
        assert [s["bol_number"] for s in shipments] == ["SHP-100", "SHP-200"]
    finally:
        await conn.close()


async def test_migration_011_enforces_note_constraints(scratch_db):
    """The CHECK constraints §4.1/§4.3 rely on are real, not conventional."""
    _alembic(scratch_db, "upgrade", "011")

    conn = await _connect(scratch_db)
    try:
        user_id = await conn.fetchval(
            "INSERT INTO users (username, password_hash, full_name, status) "
            "VALUES ('c', 'x', 'C', 'active') RETURNING id"
        )

        async def insert(note_type: str, number: str, source=None):
            await conn.execute(
                "INSERT INTO delivery_notes "
                "(type, source, document_number, document_date, uploaded, created_by) "
                "VALUES ($1, $2, $3, '2026-07-23', false, $4)",
                note_type, source, number, user_id,
            )

        with pytest.raises(asyncpg.CheckViolationError):
            await insert("not_a_type", "X-1")

        # §4.3 — source belongs only to a direct-customer note.
        with pytest.raises(asyncpg.CheckViolationError):
            await insert("transfer", "X-2", source="SC")
        await insert("direct_customer", "X-3", source="SC")

        # Uniqueness is per (type, number): the same string may appear under another type.
        await insert("internal", "X-4")
        with pytest.raises(asyncpg.UniqueViolationError):
            await insert("internal", "X-4")
        await insert("transfer", "X-4")
    finally:
        await conn.close()
