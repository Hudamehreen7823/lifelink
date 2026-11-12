"""SQLite persistence layer.

Design notes (mirrors the blueprint's "constraints + transactions" requirement):
  * CHECK constraints make it impossible for `quantity_available` to go negative
    or exceed `quantity`, so the same quantity can never be allocated twice even
    if application code has a bug.
  * Every state-changing operation runs inside `tx()`, which opens a
    BEGIN IMMEDIATE transaction (takes the write lock up front, so two
    concurrent reservations are serialised).
"""
from __future__ import annotations

import contextlib
import os
import sqlite3

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lifelink.db")


def db_path() -> str:
    return os.environ.get("LIFELINK_DB", DEFAULT_DB)


SCHEMA = """
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN
        ('food_bank','shelter','orphanage','school','library','ngo','community','business','individual')),
    address TEXT,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    capacity_per_week INTEGER NOT NULL DEFAULT 100 CHECK (capacity_per_week >= 0)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('provider','recipient','volunteer','admin')),
    verification_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending','verified','rejected')),
    organization_id INTEGER REFERENCES organizations(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL CHECK (category IN ('food','books','clothes','household')),
    title TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    quantity_available INTEGER NOT NULL,
    unit TEXT NOT NULL DEFAULT 'items',
    condition TEXT NOT NULL DEFAULT 'good' CHECK (condition IN ('new','good','fair')),
    deadline TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','withdrawn')),
    created_at TEXT NOT NULL,
    CHECK (quantity_available >= 0 AND quantity_available <= quantity)
);

CREATE TABLE IF NOT EXISTS resource_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL CHECK (category IN ('food','books','clothes','household')),
    description TEXT NOT NULL DEFAULT '',
    quantity_needed INTEGER NOT NULL CHECK (quantity_needed > 0),
    urgency INTEGER NOT NULL CHECK (urgency BETWEEN 1 AND 5),
    min_condition TEXT NOT NULL DEFAULT 'any' CHECK (min_condition IN ('any','fair','good','new')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','fulfilled','cancelled')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id INTEGER NOT NULL REFERENCES resources(id),
    request_id INTEGER NOT NULL REFERENCES resource_requests(id),
    score REAL NOT NULL,
    rank INTEGER NOT NULL,
    components TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (resource_id, request_id)
);

CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    resource_id INTEGER NOT NULL REFERENCES resources(id),
    request_id INTEGER NOT NULL REFERENCES resource_requests(id),
    quantity_allocated INTEGER NOT NULL CHECK (quantity_allocated > 0),
    status TEXT NOT NULL CHECK (status IN
        ('offered','accepted','picked_up','delivered','completed','rejected','expired')),
    auto INTEGER NOT NULL DEFAULT 0,
    reserved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    responded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_alloc_request ON allocations(request_id, status);
CREATE INDEX IF NOT EXISTS idx_alloc_resource ON allocations(resource_id, status);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL UNIQUE REFERENCES allocations(id),
    volunteer_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'assigned'
        CHECK (status IN ('assigned','picked_up','delivered','cancelled')),
    assigned_at TEXT NOT NULL,
    pickup_time TEXT,
    delivery_time TEXT,
    deadline_met INTEGER,
    confirmation_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (confirmation_status IN ('pending','confirmed','disputed')),
    note TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    message TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'in_app' CHECK (channel IN ('in_app','email')),
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent','pending','failed')),
    is_read INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextlib.contextmanager
def tx(conn: sqlite3.Connection):
    """Write transaction. BEGIN IMMEDIATE serialises concurrent writers."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def get_conn():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
